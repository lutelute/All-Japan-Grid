# ページ（窓）の組み立て

`python build_page.py` で `build/uc800-story.html`（artifact に出す本体）と `build/check.html`（ブラウザ検証用）を作る。型は `../story_page.template.html`、データはこのフォルダの `*_compact.json`。動画（`uc800-story-v3_480p.mp4`・`uc-principles-v4_480p.mp4`）はリポジトリに入れていないので、無ければ動画なしで組む。

| データ | 作り方 |
|---|---|
| `solver_compact.json` | `solver_prep.py <colgen_800x48_viz.json> <HiGHS の solver.log> out`（第 1 部の競走・価格と 800 台） |
| `cgmap_compact.json` | `cgmap_prep.py <sweep の json の置き場> ../results/gpu3060/frontier-20261025/frontier.json out`（難しさの地図） |
| `net_compact.json` | `net_prep.py docs/data/built/all.json out`（送電網の実ルート、110kV 以上） |
| `year_compact.json` | `year_prep.py year_summary.json out suspects.json docs/data/built/all.json`（第 2 部の 1 年） |
| `stage2_compact.json` | `stage2_prep.py stage2_<日>.json year_summary.json out docs/data/built/all.json`（第 3 部、種違いの `_s*.json` を同じ場所に） |
| ほか | `geo_prep.py`（10 エリアの地図）、bnb・frontier・profile などは 10-25 以前の節 |

artifact: https://claude.ai/artifact/LocMd9pd3nGKuwPrTqxWbF（非公開）
