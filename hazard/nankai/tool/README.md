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

- 系統の前提(変圧器台帳・東京湾の浸水・過負荷リレー)は動的カスケードを事前に計算した run を切り替える。対応は `build_scenario_tool.py` の `WEST_RUNS`・`EAST_RUNS`。
- 被害と復旧の前提はブラウザで計算し直す。補助 DB(`hazard/nankai/data/external/hazard_support/`)が要る。
- 埋め込むのは母線ごとの解析結果と入力、各社が公表する事業所の位置だけ。送配電事業者の台帳の生値は入れない。
- 「揺れが届き、リレーが開き、灯りが消えていく」の再生は、組み合わせごとに代表サンプル(3 分後の受電が中央値に最も近いもの)を同じ乱数で再計算した記録を使う(`build_scenario_tool.py` の `trace_block`、run ごとに `output/<run>/<島>/trace_rep.npz` に保存)。再計算した 3 分後の受電がモンテカルロの記録と 1 MW 以上ずれたら止まる。
- 母線ごとの状態は「変わった瞬間」だけを持つ(値: 島の順位 × 21 + 20 受電中 / 250 周波数崩壊 / 251 孤立 / 252 設備損傷 / 253 もともと受電していない / 254 UFLS で丸ごと消灯)。
- UFLS の表示: 計算(dynamics.FreqCore)は島内の全母線から一様に削るが、表示は遮断 MW を保ったまま優先順位の高い母線を丸ごと消灯にする(`src/nankai/ufls_display.py`、テスト `tests/test_ufls_display.py`)。優先順位は母線 id のハッシュで固定(対象の変電所は非公表のため仮定)。遮断が増えると前の選択に足すので、段が進んでも灯りがちらつかない。
