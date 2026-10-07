# SubSLD法（実証ペア図法）— 変電所構成の全国機械生成手法

命名: 2026-08-26（オーナー依頼「この手法の名前教えて」への回答として制定）。
英名: Evidence-Paired Substation Single-Line Diagramming。

## 一言でいうと

**OSMの実証拠だけから、任意の変電所の「構内幾何（衛星写真上）× 単線結線図」の
ペア図を機械生成する手法。** 発端はオーナーが嶺南変電所で手作業実証した
「線は変電所に入り、変電所で電圧階級・タップ・回線・導体を接続する」(2026-07-02)
の全国機械化。

> **2026-10-07**: 変電所の中の観測の台帳(OSM の node ID で結ぶ node-breaker 層)を別に作った。
> SubSLD の構造 DB は計算と図のための仮説の層として残し、観測層で点検する。2 つの層の役割は
> [STATION_NODE_BREAKER.md](STATION_NODE_BREAKER.md)。同じ日に、母線・ベイの帰属を敷地の多角形で
> 決めるよう直した(それまでは外接矩形 +約 1 km の全部で、母線・ベイの約 25% を隣の変電所と二重に数えていた)。

## 3段パイプライン

| 段 | 名前 | 実装 | 生成物 |
|---|---|---|---|
| 1. 抽出 | **GridStitch P2**（既存名） | `scripts/build_substation_structure.py` `extract_structure` / `scripts/build_structures_batch.py` | 構造DB `data/structures/{region}.json`（node-breaker: Site/VoltageLevel/BusbarSection/Bay/Terminal/TransformerSpec・全国約4秒） |
| 2. 集約 | **プロパティ層** | `scripts/build_substation_properties.py` | `docs/data/substation_properties.json`（電圧階級・回線数circuits・導体数wires・条数cables を変電所ごとに集約）+ built subノードの `sub_props` |
| 3. 描画 | **SubSLD**（実証ペア図） | `scripts/build_substation_structure.py` `render_figure` | PNG: 左 **GeoPane** × 右 **SLDPane** |

## ペア図の構成要素

### GeoPane（構内幾何・地図側）
- 地理院シームレスフォト下敷き（`data/cache/gsi_tiles` にキャッシュ・出典焼き込み・
  オフライン時は白背景に自動フォールバック）
- 敷地ポリゴン=黄縁 / 母線way=電圧色太線 / ベイway=破線 /
  端子根拠マーカー（●vertex-shared ■polygon ▲leadin）
- 外部線を電圧階級色で着色（`_vclasses`）
- 鉄塔マーカー（OSM power=tower, `data/osm_raw_towers/`）
- 大規模所は母線クラスタのズームインセット（母線bboxが敷地の30%未満のとき自動）

### SLDPane（単線結線図・沖電式）
- 母線=電圧階級別の太い水平線（BusbarSection数でセクション分割）
- 線=母線に刺さる縦スタブ。**実際の接着先セクション**（Terminal.attach）に配置
- **平行ストローク本数=回線数par** / 破線=leadin根拠 / 導体数=wiresタグ注記
- **上スタブ=流入・下スタブ=流出（推定）**: 対向変電所の電圧階層で判定
  （全region connections+aliases マージ → 欠測時は線名 name-evidence フォールバック
  「A~B線」「X線」「A / B」併記分割）。灰=対向不明。流向矢印付き
- バスタイ=BT（2セクション以上に触れる Bay）
- 変圧器=母線間を貫く⧉＋接続ドット＋バンク数。銘板（MVA・タップ）は
  **出典付きデータがある場合のみ**表示
- トランスが付かない電圧階級に「スルー（変圧器なし）」を明記

## 不変条件（このプロジェクトの憲法に従う）

1. **OSM=正・捏造ゼロ**: 接続は頂点共有・ポリゴン内包・lead-in の実証拠のみ。
   母線・ベイがどの変電所のものかは敷地の多角形で決める(包含・入れ子は最内側・柵外 25 m・
   頂点がすべて 1 つの敷地に入る way。`internal_way_owners`、2026-10-07)。
   タグが無い値（回線数・導体数・銘板）は推測で埋めず unknown のまま見せる
2. **全端子に根拠**: binding 語彙（vertex-shared > polygon > leadin > name-evidence > manual）
3. **推定は推定と明記**: 流向（入/出）は対向の電圧階層による推定であり、
   図の凡例に「推定」を明記する。断定表現をしない
4. **決定的に再生成可能**: 全生成物は D層（OSM+構造DBから再現可能）

## 既知の限界

- **変圧器は電圧階級の梯子(隣どうしを結ぶ仮説)**。OSM が実機を描く 518 敷地のうち 32 か所で、梯子が段を飛ばす実機
  (275/77 の直結など)を見落としている。一覧は `scripts/compare_station_layers.py` →
  `docs/reports/station_layers_<日付>/transformer_pair_review.csv`。置き換えはオーナー判断
- 開閉器(SwitchSpec)はベイから推した開閉点で、OSM の実物ではない。実物は観測層(`data/stations`)にある

- **母線なし変電所が全国86%**（OSMマッピング粒度の地域差、issue #49）。
  母線なしサイトの SLDPane は母線1本仮定で描かれる
- 流向不明（灰）の主因は**対向変電所自体のOSM欠測**（issue #49 と同根）
- leadin binding は近傍通過線を誤って拾い得る（新京葉の66kV「高柳沼南線」等は要検証）
- wires タグ被覆は全国13%（導体数注記が出ない線が多い）

## 全所展開（次段）

- バッチ生成器（`scripts/build_subsld_batch.py` 予定）: 全約6,000サイト、
  再開可能（既存PNGスキップ）・タイル取得は礼儀正しく（キャッシュ+スロットル）・
  地域別出力 `data/subsld/{region}/`（**非追跡**・構造DBと同じ方針）+ index.json
- 想定規模: PNG 約600KB×6,000 ≒ 4GB / タイルキャッシュ数GB → NAS同期を推奨
- 対話的利用は editor 統合（クリック→その場生成）が本命

## 使い方

```bash
# 1所（ペア図PNG）
PYTHONPATH=. .venv/bin/python scripts/build_substation_structure.py \
    --region tokyo --name 新京葉変電所 --fig out/

# 構造DB再生成（全国約4秒）
PYTHONPATH=. .venv/bin/python scripts/build_structures_batch.py --all

# プロパティ層（built付与込み）
PYTHONPATH=. python3 scripts/build_substation_properties.py --attach
```
