# West Island AC Convergence — Root-Cause Analysis

National zonal powerflow で、east(tohoku+tokyo) / hokkaido / okinawa は AC 収束する
一方、**west 島(60 Hz の 6 地域 chubu/hokuriku/kansai/chugoku/shikoku/kyushu、約 8,400 バス)
は AC 非収束(DC=OK)** だった。本書はその真因を pws-160core で段階的に切り分けた記録である。

## 1. 究明環境

- 実機: pws-160core (Xeon ×4 / 160T / 252 GB)。`scripts/run_national_powerflow.py`
  を numba 有効・前処理ベクトル化（`prune_dc_infeasible` / `scale_line_ratings` の
  per-round `deepcopy` 除去）に高速化した版で実行。
- 反復診断は west 島を一度構築して `/tmp/west_base.pkl` にキャッシュし、
  `scripts/test_west_*.py` で高速に試行（build 約 9 分 → 以降ロード数秒）。

## 2. 切り分け結果（いずれも実測）

| 仮説 | 検証方法 | 結果 |
|---|---|---|
| **Q(無効電力補償)の過剰** | reactive = 0.0/0.2/0.4/0.6/0.8 を sweep (`test_west_reactive.py`) | 全 FAIL（**reactive=0=シャント0 でも非収束** → 無関係） |
| 極短線(near-zero-Z) | <0.05〜1.0 km の線を bus 融合 (`test_west_fuse.py`) | 全 FAIL（最短 4 m・X 最小 0.0015 Ω の 2,480 本を融合しても非収束 → 副次的） |
| 断片化(52 連結成分) | 成分構造 (`test_west_connectivity.py`) | 最大成分が **98%(8,238/8,382)** を被覆 → 断片化は主因でない |
| 負荷 > 発電 | 地域別 balance + 地域別 AC (`test_west_byregion.py`) | 一因：kansai/kyushu のみ FAIL |
| **下位網の変圧器** | 変圧器除外 / 154 kV 以上のみ (`test_kansai_diag.py`) | **no-trafo=OK・hv≥154=OK → これが真因** |

## 3. 地域別 AC（決定的）

各地域を単独で解くと、**発電 > 負荷の 4 地域は収束、負荷 > 発電の 2 地域は FAIL**（100% 相関）:

| 地域 | P_load | P_gen | 単独 AC |
|---|---|---|---|
| chubu | 19,910 | 23,226 | OK (vm 0.898–1.008) |
| chugoku | 8,643 | 12,139 | OK (vm 0.867–1.002) |
| hokuriku | 3,542 | 3,848 | OK (vm 0.907–1.022) |
| shikoku | 2,735 | 5,116 | OK (vm 0.755–1.002) |
| **kansai** | 21,762 | 16,380 | **FAIL** |
| **kyushu** | 12,608 | 11,295 | **FAIL** |

`balance_power` が west 島全体で発電を一律スケールするため、需要集中かつ OSM 発電が
過小な kansai/kyushu で局所的に「実発電 < 負荷」となり解けない。ただし **gen 容量
(max_p_mw) 自体は足りており**、地域別に re-balance すると両地域とも P_gen > P_load に
できる（`test_west_rebalance.py`）。

## 4. 真因：下位網の悪条件変圧器

re-balance で kansai/kyushu を発電 > 負荷にしても、なお地域単独 AC は FAIL
(`test_west_final.py`)。さらに切り分けると(`test_kansai_diag.py`, `test_kansai_trafo.py`):

- **変圧器を除外すると収束**（vm 0.873–1.000, 2 反復）
- **154 kV 以上のみにすると収束**（vm 0.953–1.012, 2 反復）
- **gs(3000 反復)でも FAIL** ＝ ソルバ選択でなく系統構造の問題
- 変圧器 vk_percent は 8–12%（正常範囲）だが **電圧比 最大 20**、低圧側に
  **非標準電圧 22 / 25 / 30 / 33 / 100 kV** が混在。vk フロアや非標準母線除外
  単独では収束しない。

→ kansai/kyushu の AC 非収束は、**154 kV 未満の下位網（66–132 kV、計 539 変圧器、
極端な電圧比、非標準電圧）が作る悪条件 Ybus** が NR/GS のヤコビアンを特異化するため。
これは OSM 下位網のデータ品質（誤接続・極端変圧器・非標準電圧タグ）の限界に起因する。

## 5. 結論

| 範囲 | AC | DC |
|---|---|---|
| east(tohoku+tokyo) / hokkaido / okinawa | ✅ | ✅ |
| west: chubu / chugoku / hokuriku / shikoku | （単独では収束するが zonal 一括は規模で困難） | ✅ |
| west: kansai / kyushu | ❌（下位網品質限界） | ✅ |

west 島は **DC（全系統収束済み）で確定**。east が全電圧 AC 収束するのに対し west が
DC 止まりなのは、規模(8,238 バス一括)と kansai/kyushu 下位網のデータ品質差による。
**「地図があってもバスレベルの電気モデルは別物」** という本データセットの limitation の
具体例であり、AC 級解析には OCCTO 等の下位網パラメータ補完が前提となる。

## 6. 再現手順

```bash
# 全国 zonal（west は DC=OK / AC=FAIL を確認）
PYTHONPATH=. python scripts/run_national_powerflow.py --islands west \
  --output-dir docs/data/powerflow_national

# 真因の段階診断（/tmp/west_base.pkl を最初に生成）
PYTHONPATH=. python scripts/test_west_connectivity.py   # 成分構造・極短線
PYTHONPATH=. python scripts/test_west_byregion.py       # 地域別 AC（負荷/発電相関）
PYTHONPATH=. python scripts/test_west_rebalance.py      # 地域別 re-balance
DIAG_ZONE=kansai PYTHONPATH=. python scripts/test_kansai_diag.py   # 変圧器が真因
```

## 7. 付記：非標準電圧クリーニング（データ品質改善）

究明で `vn_kv` に **22 / 25 / 30 / 33 / 100 kV の非標準電圧**が残ると判明した。
WHITEPAPER 6.2 記載の `_clean_voltage`（標準クラスへのスナップ）が
`examples/build_snapped_topology.py` の snapped 経路に**未実装**だったのが原因
（`_parse_voltage_kv` は数値化のみ）。`_clean_voltage` を実装し、変電所(198行付近)と
送電線(235行付近)の電圧を `VALID_VOLTAGES=[66,77,110,132,154,187,220,275,500]` に
スナップするよう修正した。

修正後（kansai 再build, pws-160core 実測）:
- `vn_kv` = **[66,77,110,154,187,275,500]**（非標準値が解消、22/25/30/33→66、100→110）
- 変圧器 **539 → 488**（同電圧化で一部が線路化、極端な 20:1 電圧比が解消）
- **データ品質は明確に向上**（可視化・MATPOWER 変換・モデル正確性に寄与）

ただし baseline AC は依然 FAIL（no-trafo / hv≥154 は OK のまま）。**AC 非収束は電圧の
標準化では解消せず、下位網(66–132 kV)の規模・構造に起因する**ことが改めて裏付けられた。
電圧クリーニングはデータ品質改善であって AC 収束の処方ではない。
