# okinawa燃料フリート較正 — slack 47.3% → 3.7%（出典付き実フリートへの両側収束）

- 日付: 2026-07-07 / モデル: Claude Fable 5
- 位置づけ: slack解剖（`docs/reports/slack_tie_diagnosis_2026-07-05.md`）で確定した
  「okinawaの主犯 = 燃料別容量不一致（UC石油1,482 vs PF石油系600MW）」の解消。
  backboneでも直らない（47.9%不変）ことが実証済みだった＝ネットワークでなくフリートの問題。

## TL;DR

UC側の**合成フリート**（沖縄石油A〜D 420MW×4 + 石炭200MW — 実在しない発電機名・
石油偏重）と、PF側の**燃料別デフォルト容量**（OSM容量タグ欠損→coal 600×3等）が
両側で実態から乖離していた。両側を**出典付き実フリート**
（`data/generator_capacity_sources.jsonl`、2026-06-26収集・URL+原文quote済み）へ
収束させ、okinawa 24時間の slack を **47.3% → 3.7%**（需要比・24/24 AC収束）に改善した。

## 1. 実フリート（出典はすべて容量出典DBに収録済み・捏造なし）

| 発電所 | 容量 | 燃料 | 事業者 | 出典confidence |
|---|---|---|---|---|
| 吉の浦火力 | 502MW | LNG | 沖縄電力 | high |
| 金武火力 | 440MW | 石炭 | 沖縄電力 | high |
| 具志川火力 (Gushikawa) | 312MW | 石炭(+バイオマス混焼) | 沖縄電力 | high |
| 石川石炭火力 (Ishikawa J-Power) | 312MW | 石炭 | 電源開発 | high (official) |
| 石川火力 | 353MW | 石油/GT | 沖縄電力 | medium |
| 牧港火力 | 333MW | 石油系混成(重油125+GT163+GE45) | 沖縄電力 | medium |

火力計 2,252MW = 石炭1,064 / LNG 502 / 石油系686。
旧UC合成（石油1,680+石炭200）は燃料構成が根本的に違った（実態は石炭・LNG主体）。

## 2. 変更（3点）

1. **UC合成フリート廃止** — `src/uc/scenario.py` の okinawa 合成ブロックを削除。
   沖縄も他地域と同経路（GeoJSON + capacity_patches）でロードされる。
2. **capacity_patches の実値化** — `data/reference/capacity_patches.yaml` の
   旧・容量0パッチ6件（「合成火力に一本化」用）を出典付き実値パッチへ置換。
   UC（scenario ローダー）とPF（capacity_bridge）の双方が同じパッチを読むため、
   燃料別容量が両側で一致する（容量の正の一元化）。
3. **capacity_bridge の built系配線** — `scripts/uc_to_pf_built.py --bridge`（既定OFF。
   07-05正典結果との比較可能性を保つ）。適用レポート・注入clip/unmatchedを
   出力JSONに記録（silent truncation禁止）。

## 3. Ablation（okinawa 24時間・fullモデル99バス・AC 24/24収束）

| 構成 | mean \|slack\|/需要 | 残る不整合 |
|---|---|---|
| 旧: UC合成 + PFデフォルト容量（07-05正典） | **47.3%** | oil clip ~900MW/h ほか |
| UC実フリートのみ（--bridgeなし） | **7.2%** | lng clip 14時間(max102MW=PFガス既定400 vs UC LNG 502)・battery unmatched 4時間(max89MW) |
| UC実フリート + --bridge | **3.7%** | battery unmatched 4時間(max89MW)のみ |

- 残差3.7%の内訳: UC地域集約蓄電池（OCCTO参照100MW）の放電がPF側に受け皿なし
  （t=12/13/17のslack凸=131〜141MW）+ 損失 + 負荷按分の粗さ。
  slackが負の時間帯（t=1: -79MW等）は軽い余剰=UC出力がPF需要をわずかに上回る断面。
- 旧診断の「UC石油1,482MW」は合成フリート前提の数字。実フリートでは石油系686MWが上限
  となり、UCのメリットオーダーも石炭・LNG主体の現実的なコミットメントに変わった。

## 4. 再現

```bash
# 較正後（bridgeあり）
PYTHONPATH=. .venv/bin/python scripts/uc_to_pf_built.py \
    --islands okinawa --all-hours --bridge \
    --out docs/reports/uc_pf_built_okinawa_allhours_bridged_2026-07-07.json
# ablation（bridgeなし）
PYTHONPATH=. .venv/bin/python scripts/uc_to_pf_built.py \
    --islands okinawa --all-hours \
    --out docs/reports/uc_pf_built_okinawa_allhours_nobridge_2026-07-07.json
# ゲート
python -m pytest tests/test_uc_scenario.py tests/test_uc_capacity_bridge.py \
    tests/test_uc_pf_injection.py tests/test_substation_structures.py \
    tests/test_ybus_numeric.py tests/test_transformer_provenance.py -q
```

## 5. 開示・残課題

- **蓄電池のPF側受け皿なし**（unmatched 4時間 max89MW）— UCの地域集約蓄電池は
  設置場所の出典がなく、PF側に恣意的なバスで発電機を作らない（捏造回避）。
  出典付きの設置場所が得られたら受け皿を追加する。
- **牧港の混成燃料**（重油汽力+灯油GT+LNGガスエンジン）は oil 一括で近似
  （出典noteに内訳記録済み）。
- **--bridge は既定OFF** — east/west/hokkaido にも同パッチ+dedup+稼働炉リストが
  効くため、既定ON化は96断面の正典更新とセットでオーナー判断。
- テスト更新: `test_okinawa_synthetic_thermals_added`（合成ピン）→
  `test_okinawa_real_fleet_via_patches` + `test_okinawa_no_synthetic_thermals`。
