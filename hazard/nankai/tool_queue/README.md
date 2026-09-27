# 復旧の待ち行列卓(tool_queue)

南海トラフ巨大地震で壊れた変電所・送電線の修理を、班の被災・他社応援・修理の順番を変えて比べる 1 枚の HTML。
動画 `make_restoration_ops.py`(restoration_ops.mp4)の前提をそのままブラウザで動かせるようにしたもの。

公開: https://claude.ai/artifact/Ri8H6EdNjayzF8PZcihCRt(非公開リンク)

## 作り方

```bash
PYTHONPATH=hazard/nankai/src:hazard/nankai/scripts python3 hazard/nankai/scripts/build_queue_tool.py \
  --out docs/reports/nankai_hazard_2026-09-13/tool/nankai_restoration_queue.html      # 約 45 秒
node hazard/nankai/tool_queue/test_model.mjs                                             # JS と Python の照合
```

- `build_queue_tool.py` が代表サンプル・拠点・応援を `make_restoration_ops.py` の関数で作り、`data.json`(git 管理外)と
  `reference.json`(検算値)を書いて、`index.template.html` に `style.css`・`model.js`・`app.js`・データを埋め込む。
- iCloud 同期下では `data/derived` が中身の無い状態(dataless)になることがある。`brctl download <path>` で落としてから回す。

## 計算(model.js)

| 部分 | 元 | 照合 |
|---|---|---|
| 要員と資機材の被災 | `make_restoration_ops.availability`(pandas の groupby の補償付き加算まで同じ順) | 完了時刻が一致 |
| 他社応援 | `mutual_aid` | 同上 |
| 待ち行列(1 時間刻み・割り込みなし・班数は切り捨て) | `run_queues` | 優先順位 5 通りで完了時刻の差 0 |
| 停電需要家 | `CascadeModel.evaluate` の run_pf=False(電源とのつながりだけ) | 5 通りで差 0 軒 |

停電の軒数は、つながりだけで数えた値に「既定の優先順位で測った 潮流あり − つながりだけ」を時刻ごとの補正として足している
(つながりだけだと約 50 万軒少なく出る)。補正後の潮流ありとの差は多くの時刻で 5 万軒以内、「需要の大きい順」系の
56〜58 日だけ最大 34 万軒(`reference.json` の `resid_max`)。

## 画面で変えられるもの

優先順位 5 通り(電圧→需要 / 需要 / 直結の需要家÷修理日数 / 短い修理から / 長い修理から)・表の「先に」「後回し」・
地元の班数の倍率・要員の被災の重さ・資機材の回復日数・巡視・応援(百万口あたり班数・決定・招集・速度・送り先の配分)。

## 既定の前提での結果(代表サンプル 西 #1008・東 #1015)

停電 3 日後 590 万軒・7 日後 505 万軒・1 か月後 406 万軒、修理が全部片付くのは 241 日目。
「短い修理から」は 1 か月後 −35 万軒・片付くのは +30 日、「長い修理から」は 1 か月後 +74 万軒、
地元の班が半分なら 1 か月後 +25 万軒、応援 2.5 倍(100 万口あたり 5 班)なら 1 か月後 −21 万軒。
