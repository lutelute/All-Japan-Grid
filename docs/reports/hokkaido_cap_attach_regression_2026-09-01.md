# 北海道DC: 既定接続規則(cap)の最大負荷率が 88.4% → 318.0% に劣化

- 日付: 2026-09-01
- モデル: **Claude Opus 5**（記録あり）
- 状態: **未解決**（原因の切り分けまで。ピンは更新せず `xfail(strict)` で開示）
- 検知: `tests/test_gen_attach_modes.py::test_hokkaido_dc_pins_the_effect_of_the_default_flip`

## 何が起きたか

CI が 2026-06-27 以降ずっと赤で、その中にこの劣化が埋もれていた。CI ログは
最初の assert（`nearest`）で止まっていたため、**より重大な `cap` 側の値が
誰にも見えていなかった**。

| 指標 | ピン (2026-08-10b) | 現在 (2026-09-01) | 差 |
|---|---|---|---|
| `nearest`（旧接続規則） | 136.3% | **133.3%** | −3.0 |
| `cap`（**既定**接続規則・介入#24） | 88.4% | **318.0%** | **+229.6** |
| >100% の線 | — | nearest 2本 / cap 4本（全855本） | — |

テストの設計前提である `assert got["cap"] < got["nearest"]`
（＝既定ON化が改善になっている）が **反転している**。

## 測定artifactではないことの確認

- 構造DB（`data/structures/*.json`・銘板）を無効化した **CI 相当の条件**で
  再測定し、`nearest = 133.3%` が CI のエラーメッセージの値と**完全一致**した
- `cap = 318.0%` は銘板の有無に依らず同値（銘板ありのローカルでは
  `nearest` のみ 133.9% になる＝差は銘板由来で、cap の劣化とは無関係）

## 原因の切り分け

`cap` モードで過負荷になっている上位3線は、いずれも札幌市南区の同一系統に集中する:

| 負荷率 | 線名 | from → to |
|---|---|---|
| **318.0%** | **同一敷地タイ(同定)** | 平岸3条18変電所_2 → 平岸3条18変電所（66kV） |
| 149.6% | 定山渓温泉西1変電所~平岸3条18変電所線 | 平岸3条18変電所_2 → 南区変電所 66kV |
| 146.8% | 定山渓温泉西1変電所~平岸3条18変電所線 | 南区変電所 66kV → 南区変電所_2 |

（比較: `nearest` 側の最大は寒別支線 133.3%・留産線 110.6% で、別の場所）

最悪線は **「同一敷地タイ(同定)」** ── 2026-08-16 の同定・治癒作業
（`scripts/apply_disclosure_v2.py`, class=`same_site_identity`）で導入された、
同一変電所の重複ノード同士を結ぶエッジである。同一敷地なので長さがほぼ 0 →
インピーダンス極小で潮流が集中するが、**通常の 66kV 架空線として定格が
当たっている**。物理的には母線連絡（bus coupler）に相当する。

## 未確定（ここから先は判断が要る）

次の2つを切り分けられていない:

1. **計器側の artifact**: 母線連絡に架空線の定格を当てているため、
   負荷率という指標自体が意味を持っていない
2. **接続規則側の問題**: `cap` モードが実際にこの母線連絡へ潮流を
   集中させており、過負荷は実在の含意を持つ

`built` のエッジは `same_site: True` フラグを保持しているので、
判別・除外の道筋自体はある。ただし過負荷指標そのものに触る変更になるため、
`docs/MODEL_INTERVENTIONS.md`（介入台帳） への登録とオーナー判断を要する。

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

for mode in ("nearest", "cap"):
    net, bus_of, _ = pf.build_island_net(
        "hokkaido", nodes, edges, pf.ISLAND_FREQ["hokkaido"], {},
        dedup_nodes=True, site_trafos=False, deenergize_unbuilt=False)
    pf.attach_generators(net, bus_of, nodes, "hokkaido", attach_mode=mode)
    pf.allocate_loads(net, cfg, pref_gwh=pref_gwh)
    add_reactive_compensation(net, factor=cfg.get("reactive_compensation_factor", 0.6))
    pf.add_per_component_slacks(net)
    pf.balance_by_zone(net, cfg)
    solved, _dc, _a, _b = pf.solve_island(net, max_ac_buses=0)
    print(mode, round(float(solved.res_line["loading_percent"].dropna().max()), 1))
```

## 参照

- 介入#24（`--gen-attach`）: `docs/MODEL_INTERVENTIONS.md`
- 同定タイの生成: `scripts/apply_disclosure_v2.py`（class=`same_site_identity`）
- 過負荷の真因についての既往: `docs/reports/` の overload 系レポート
