# 再現手順 — Reproducibility Recipe

fresh clone から本プロジェクトの全ヘッドライン数値を再現する完全レシピ。
**正本はDB**（`ajgrid db ingest` が raw + キュレーション資産を完全復元）であり、
潮流パイプラインはファイルを介さず DB から直接再現できる。

## 0. セットアップ

```bash
git clone https://github.com/lutelute/All-Japan-Grid && cd All-Japan-Grid
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest -q          # 950 passed が基準線
```

## 1. DB再構築（機械的更新の起点）

```bash
ajgrid db ingest             # data/*.geojson + data/db/enrichments.jsonl(キュレーション正本)
                             # → data/grid.db (66,177 features + 232k curated rows)
ajgrid coverage              # 来歴カバレッジ（検証済 vs 合成の正直な内訳）
```

## 2. 潮流計算（DBのみから再現）

```bash
ajgrid solve kansai --reconnect --source db --backbone   # AC収束・vm≥0.86
ajgrid solve tokyo  --reconnect --source db              # フルモデル
```

`--source db` はファイル構築と**完全同一**の網を構成する
（回帰テスト `tests/test_db_source_build.py` が同一性をpin）。

## 3. KPI・回帰（改善はすべてこの物差しで測る）

```bash
ajgrid validate --topology --all --solve --backbone \
    --json /tmp/now.json --baseline docs/reports/topology_backbone_stack_2026-06-11.json
```

ヘッドライン（2026-06-11時点・committed JSONと一致するはず）:
backbone/フル両モデル **AC 10/10**・backbone vm_min ≥0.86・合成線率 関西2.0%。

## 4. 外部データ（再配布不可 → 各自取得、コマンドは下記）

```bash
# 関西送配電 空容量CSV（毎日更新）
curl -L -o data/external/kansai_td/154kv_more_line.csv \
  https://www.kansai-td.co.jp/interchange/takusou/pdf/154kv_more_line.csv
# 東電 潮流実績（FY2024通年・基幹）: zipはCP932名 → scripts参照 or 手動展開
curl -A "Mozilla/5.0" -o data/external/tepco/tyouryu_kikan.zip \
  https://www.tepco.co.jp/pg/consignment/system/pdf/tyouryu_kikan.zip
# 国土数値情報 P03（発電施設GML; zip内部名はCP932→python zipfileで展開)
curl -A "Mozilla/5.0" -o /tmp/P03-13.zip https://nlftp.mlit.go.jp/ksj/gml/data/P03/P03-13/P03-13.zip
# → data/external/P03-13/P03-13-g.xml に展開後:
PYTHONPATH=. python scripts/db/enrich.py --p03 data/external/P03-13/P03-13-g.xml
# OCCTO 公表API（30分値・保持~14ヶ月）
python scripts/fetch_occto_kohyo.py --from 2025-04-01 --to 2026-06-09
# 開示集計のDB化（境界回廊の実測重み付け & --from-db 検証が有効になる）
PYTHONPATH=. python scripts/db/calibrate.py   # → measured_line_stats + measured_bus_loads
# 国勢調査2020 1kmメッシュ人口（e-Stat、出典明記で利用可。残余需要のspatial=population用）
python scripts/fetch_estat_mesh.py            # → data/external/estat/ (関東12メッシュ)
```

## 5. 外部検証（誠実指標）

```bash
python -m src.validation.external_match kansai \
    --csv data/external/kansai_td/154kv_more_line.csv      # 名前recall等
python -m src.validation.external_tepco                    # 帯別接続recall(trunk/154/66)
python -m src.validation.external_tepco --flows --backbone 0   # 3層内部ρ(フルモデル)
python -m src.validation.external_tepco --flows --backbone 0 --from-db
                                # ↑calibrate済DBから同じ物差しを再現(CSV直読み不要)
```

注意: 外部CSVは更新され続けるため、recall/ρは取得日でわずかに変動する。
committed スコアカード（docs/reports/external_*_2026-06-1*.json）が当時値の正本。

## 6. 成果物の再生成

```bash
bash scripts/regen_powerflow_snapped.sh --promote   # ライブマップ(docs/data/powerflow)
PYTHONPATH=. python scripts/export_cim_level2.py --verify   # CIM L2 + cim2pp往復
PYTHONPATH=. python scripts/validate_cgmes.py --all --dir dist/cim_level2
PYTHONPATH=. python scripts/gen_cim_national_pf.py  # 国家PF図(需要スケール無し)
PYTHONPATH=. python scripts/export_other_freq_layer.py      # 他周波数参考レイヤ
ajgrid solve national                                # 全国ゾーナル(westはDC)
```

## 7. 決定論の注意

- ビルダー・ディスパッチ・縮約は全て決定論（乱数不使用）。同一入力→同一網
- 唯一の非決定要素は**外部データの取得日**（OSM再fetch・各社CSV・OCCTO窓）。
  キュレーションは enrichments.jsonl（git追跡）に在るため再fetchでも保全される
- 各改善の判断根拠とKPI変化は `docs/reports/IMPROVEMENT_LOG.md`（モデル名つき台帳）
