# 南海トラフ停電シナリオ卓

前提を切り替えて、揺れの直後 3 時間の系統と 90 日の復旧を比べる 1 枚の HTML。

```
PYTHONPATH=hazard/nankai/src:hazard/nankai/scripts python3 hazard/nankai/scripts/build_scenario_tool.py \
  --out docs/reports/nankai_hazard_2026-09-13/tool/nankai_scenario_tool.html
node hazard/nankai/tool/test_model.mjs     # JS の計算を Python(reference.json)と照合
```

| ファイル | 中身 |
|---|---|
| `model.js` | 計算部。`make_restoration_workforce.py` の build / simulate / customers_out の移植 |
| `app.js`・`style.css`・`index.template.html` | 画面 |
| `test_model.mjs`・`reference.json` | 照合(4 通りの前提) |
| `data.json` | 生成物(HTML に埋め込むデータ。git 管理外) |

- 系統の前提(変圧器台帳・東京湾の浸水・過負荷リレー)は動的カスケードを事前に計算した run を切り替える。対応は `build_scenario_tool.py` の `WEST_RUNS`・`EAST_RUNS`(run_v8 系 = UFLS の段階的な再送電あり。12 通りは `scripts/run_v8_batch.sh`)。
- 被害と復旧の前提はブラウザで計算し直す。補助 DB(`hazard/nankai/data/external/hazard_support/`)が要る。
- 埋め込むのは母線ごとの解析結果と入力、各社が公表する事業所の位置だけ。送配電事業者の台帳の生値は入れない。
- 「揺れが届き、リレーが開き、灯りが消えていく」の再生は、組み合わせごとに代表サンプル(3 分後の受電が中央値に最も近いもの)を同じ乱数で再計算した記録を使う(`build_scenario_tool.py` の `trace_block`、run ごとに `output/<run>/<島>/trace_rep.npz` に保存)。再計算した 3 分後の受電がモンテカルロの記録と 1 MW 以上ずれたら止まる。
- 母線ごとの状態は「変わった瞬間」だけを持つ(値: 島の順位 × 21 + 20 受電中 / 250 周波数崩壊 / 251 孤立 / 252 設備損傷 / 253 もともと受電していない / 254 UFLS で丸ごと消灯)。
- UFLS の表示: 計算(dynamics.FreqCore)は島内の全母線から一様に削るが、表示は遮断 MW を保ったまま優先順位の高い母線を丸ごと消灯にする(`src/nankai/ufls_display.py`、テスト `tests/test_ufls_display.py`)。優先順位は母線 id のハッシュで固定(対象の変電所は非公表のため仮定)。遮断が増えると前の選択に足すので、段が進んでも灯りがちらつかない。

## 再生を動画に書き出す(スライド用)

```
python3 hazard/nankai/tool/export_server.py docs/reports/nankai_hazard_2026-09-13/tool <フレーム保存先> 8733
# ブラウザで http://127.0.0.1:8733/nankai_scenario_tool.html を開き、前提を選んでからコンソールで
#   window.exportNight()            # 夜景の再生。既定 1920×1080・全フレーム(531 枚)を POST。{width, height, every, start, end} で変えられる
#   window.exportRestore()          # 復旧 90 日の地図。REC_DAYS の 103 日点を 1 枚ずつ r_0000.png〜 に
ffmpeg -framerate 20 -pattern_type glob -i '<フレーム保存先>/f*.png' -vf format=yuv420p -c:v libx264 -crf 20 -movflags +faststart out.mp4
ffmpeg -framerate 6 -pattern_type glob -i '<フレーム保存先>/r_*.png' -vf format=yuv420p -c:v libx264 -crf 20 -movflags +faststart restore.mp4
```

- 書き出しは画面と同じ描画(`paintMap` / `paintRestoreMap`)に、右の情報欄(時計・受電の内訳・周波数・直近の事象・凡例・前提 / 復旧は日・停電の内訳・働く人・推移・応援の到着)を `paintInfo` / `paintRestoreInfo` でキャンバスに足したもの。Artifact の中では POST 先が無いので何もしない。
- 代表サンプル以外(東京が一気に崩壊する #59 など)は `python3 scripts/build_scenario_tool.py --samples west=81,east=59 --out <書き出し専用の HTML>` で、指定したサンプルの記録を再計算して埋めた HTML を別に作る(既定の前提だけ計算し他の前提はそれを流用。`data.json` は触らない)。記録は `output/<run>/<島>/trace_s<N>_v2.npz` に残る。
- フレームは `canvas.toDataURL()` の文字列を POST する(`toBlob` はタブが隠れると約 1 fps に絞られる)。長い書き出しは await せずに始め、`window.__exportProgress` / `__exportDone` / `__exportError` を見る。
- 既定の前提の書き出し(`docs/reports/nankai_hazard_2026-09-13/tool/`): `nankai_scenario_night_default`(西 #81・東 #89)、`nankai_scenario_night_east_collapse_early`(東 #59・揺れの直後に崩れる型)、`nankai_scenario_night_east_collapse_tsunami`(東 #9・90 分後に崩れる型)の各 .mp4(1920×1080・20 fps・26.5 秒)/ .gif(1280 px・10 fps)と静止画、`nankai_scenario_restore_default`(復旧 90 日・103 コマ・6 fps・17 秒)の .mp4 / .gif と 7 日・90 日の静止画。
