# 北海道DC: 既定接続規則(cap)の最大負荷率 318% — 真因は「cap が電圧階級を見ない」

- 日付: 2026-09-01
- モデル: **Claude Opus 5**（記録あり）
- 状態: **真因確定・改善案(capkv)を実装。既定の変更はオーナー判断待ち**
- 検知: `tests/test_gen_attach_modes.py::test_hokkaido_dc_pins_the_effect_of_the_default_flip`

## 何が起きていたか

CI が 2026-06-27 以降ずっと赤で、この劣化が2か月埋もれていた。CI ログは最初の
assert（`nearest`）で止まっていたため、**より重大な `cap` 側の値が誰にも見えていなかった**。

| 指標 | ピン (2026-08-10b) | 現在 (2026-09-01) |
|---|---|---|
| `nearest`（旧接続規則） | 136.3% | 133.3% |
| `cap`（**既定**・介入#24） | 88.4% | **318.0%** |

テストの設計前提 `assert got["cap"] < got["nearest"]` が反転していた。
測定artifactではない（構造DB無しの CI 相当条件で `nearest = 133.3%` が CI の
エラー値と完全一致）。

## 真因

**京極発電所（400MW）が札幌市南区の 66kV バスに接続されていた。**

京極揚水発電所（後志管内京極町・200MW×2）は実際には 275kV 系統（西双葉開閉所）
に繋がる電源で、札幌の 66kV に載ることはあり得ない。

過負荷の連鎖はこうなっていた:

| 負荷率 | 線 | 区間 |
|---|---|---|
| **318.0%** | 同一敷地タイ(同定) | 平岸3条18変電所_2 → 平岸3条18変電所（66kV・255m・**68.6MVA定格**に218.1MW） |
| 149.6% | 定山渓温泉西1〜平岸3条18線 | 平岸3条18変電所_2 → 南区変電所 66kV |
| 146.8% | 同上 | 南区変電所 66kV → 南区変電所_2 |

`cap` モードの定義は「**バスに集まる枝の合計容量**がその発電所の出力以上になる
最寄りのバス」であり、**電圧階級を見ていない**。66kV バスでも枝が6本あれば合計は
400MVA を超えるため、400MW の京極が選ばれてしまう。しかし実際の潮流は合計容量に
均等分散するわけではなく、1本（同一敷地タイ）に集中して 318% になった。

当初「同一敷地タイに架空線の定格を当てているのが原因（計器のartifact）」と見たが、
**それは症状であって原因ではなかった**。66kV に 218MW を流す構成自体が誤りである。

端的な指標: 200MW超の大型機11台（計6,989MW）のうち、**cap では2台650MWが 66kV
以下に載る**。kvfit / capkv では 0台。

## 改善: `capkv` モード（cap ∧ kvfit）

`cap` の「電圧を見ない」欠陥だけを塞ぐモードを追加した
（`scripts/run_full_powerflow_from_db.py`・**既定は `cap` のまま変更していない**）。
合計容量と必要階級（出力を1回線で運べる最下位階級）の**両方**を満たす最寄りバスを採る。

### 全島×3モードの実測（DC・銘板無し条件）

| 島 | cap（既定） | kvfit | **capkv** |
|---|---|---|---|
| hokkaido | 318.0% / 4本 | 93.3% / 0本 | **86.3% / 0本** |
| okinawa | 181.3% / 10本 | 181.3% / 10本 | 181.3% / 10本 |
| **east** | **725.5% / 348本** | 935.4% / 417本 | **1031.4% / 439本** |
| west | 1102.7% / 364本 | 769.9% / 355本 | **693.9% / 351本** |

発電は全モードで保存されている（hokkaido: 417台・10,574.6MW が全モード同一。
配置だけが変わり、66kV 接続が 2,863→1,861MW に減って 187kV 以上が 7,331→8,333MW
に増える）。「過負荷が減ったのは電源を落としたから」ではない。

### east だけ逆を向く — 降圧点の欠損

east は接続電圧を正すと**悪化する**。capkv の最悪線を見ると理由がはっきりする:

| 負荷率 | 線 | 区間 |
|---|---|---|
| 1031.4% | 新淀線 | 淀橋変電所(**66kV**) → 新宿変電所(**275kV**) |
| 967.6% | 淀橋和田堀方面(図p12) | 淀橋変電所(66kV) → 和田堀変電所(66kV) |
| 596.6% | 西新宿線 | 西新宿変電所(**66kV**) → 東新宿変電所(**275kV**) |

最悪線が **66kV↔275kV をまたぐ線＝降圧点そのもの**である。大電源を高電圧へ正しく
移すほど、都心需要へ降ろす経路に潮流が集中する。既往の知見「真因は接続電圧**と
降圧点**の欠損。交互作用で是正の符号は反転する」がそのまま再現した。

**したがって `capkv` を全島一律の既定にすることはできない。**

## 判断が要る点（オーナー判断）

1. 既定を島別に分ける（hokkaido/west は capkv、east は cap 据え置き）ことを
   設計として許容するか。恣意性と引き換えに hokkaido の 318% と west の 1102% が消える
2. east は降圧点の補完が先。接続規則をいじる前に、都心 66kV↔275kV の変圧器容量を
   出典付きで埋める作業が要る（現出典で埋まるかは未確認）
3. 一律 `cap` 据え置きなら、hokkaido の 318% は既知の欠陥として残る

## 再現手順

```python
import json
import scripts.run_full_powerflow_from_db as pf
from src.powerflow.pref_demand import pref_zone_gwh
from src.powerflow.pipeline import add_reactive_compensation

pf._NAMEPLATES_CACHE = {}          # CI 相当（構造DB 無し）にする
db = json.load(open(pf.BUILT, encoding="utf-8"))
nodes, edges = db["nodes"], db["edges"]
cfg = pf.load_demand_config()
pref_gwh, _ = pref_zone_gwh(nodes)

for mode in ("cap", "kvfit", "capkv"):
    net, bus_of, _ = pf.build_island_net(
        "hokkaido", nodes, edges, 50.0, {},
        dedup_nodes=True, site_trafos=False, deenergize_unbuilt=False)
    pf.attach_generators(net, bus_of, nodes, "hokkaido", attach_mode=mode)
    pf.allocate_loads(net, cfg, pref_gwh=pref_gwh)
    add_reactive_compensation(net, factor=cfg.get("reactive_compensation_factor", 0.6))
    pf.add_per_component_slacks(net)
    pf.balance_by_zone(net, cfg)
    solved, _dc, _a, _b = pf.solve_island(net, max_ac_buses=0)
    print(mode, round(float(solved.res_line["loading_percent"].dropna().max()), 1))
```

注意: `balance_by_zone` の後の `net.gen.p_mw` は**運転出力**であって設備容量ではない
（京極は 400MW → 176MW に絞られる）。接続先の妥当性を見るときは balance 前を見ること。

## 参照

- 介入#24（`--gen-attach`）: `docs/MODEL_INTERVENTIONS.md`
- 同定タイの生成: `scripts/apply_disclosure_v2.py`（class=`same_site_identity`）
- モード評価の既往: `docs/reports/repair_search_2026-08-09.md`
