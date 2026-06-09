# Coverage — provenance & validation snapshot / 来歴・検証カバレッジ

**正直な精度を一目で.** このプロジェクトは「地理トポロジ＋合成電気値」を土台に、
権威データで**裏付けられた部分**を増やしていく。本書はその**現在の裏付け率**のスナップショット。
最新値は `ajgrid coverage`（DBを読むだけ）で随時再生成できる。

> Honest accuracy at a glance. Regenerate the live figures any time with
> **`ajgrid coverage`** (reads `data/grid.db`; rebuild it with `ajgrid db ingest`).

**Snapshot — v1.3.x（2026-06、P03-13 取込後）**

```
Raw features: 66,177  (substations 6,962 / lines 40,077 / plants 19,138)

Plants validated against authoritative P03 (国土数値情報, ≤2 km):
  corroborated plants : 3,109  (16.2%)
   ├ authoritative capacity_mw : 2,433  (12.7%)
   └ authoritative operator    : 3,082  (16.1%)
  → the remaining 83.8% of plants are OSM-only (no authoritative corroboration).

Enrichments by provenance (source):
  legacy_marker        184,985
  endpoint_matching     30,173
  nominatim             13,867
  p03_db                13,705   ← authoritative: 国土数値情報 P03 (発電所)
  geocode_promotion      3,114
  overpass_db               20
```

## 何が「検証済み」で何が「合成」か / Validated vs synthetic

| 対象 | 状態 | 根拠 |
|---|---|---|
| 発電所の identity / capacity / operator | **16.2% 権威裏付け** | 国土数値情報 P03 と 2km 以内で一致（`source=p03_db`, `_p03_distance_km`） |
| 残り 83.8% の発電所 | OSM のみ | `operator` 等は OSM タグ依存・無保証 |
| トポロジ（接続・位置） | OSM 由来 | 衛星画像で主要設備を部分検証 |
| **線路 R/X/B・変圧器インピーダンス/タップ** | **全網 100% 合成** | 電圧クラス別の文献標準値・kV² 近似。**権威電気データ未取得** |

## 限界（必読）/ Hard limits

- **電気パラメータは運用判断に使えない.** R/X/B・変圧器諸元は全網で合成値。相対傾向・merit
  order は有意だが、個別設備の運用可否には使えない（[VISION.md](VISION.md) §2）。
- **P03 が裏付けるのは発電所の identity/capacity であって、インピーダンスではない.**
- 権威電気データの注入は **Pillar 3 = 事業者・OCCTO 連携**が律速（[ENGAGEMENT.md](ENGAGEMENT.md)）。

この線引きを `ajgrid coverage` が**毎回数値で出す**こと自体が、誇張された「日本系統モデル」を
増やさないための公共的価値である。
