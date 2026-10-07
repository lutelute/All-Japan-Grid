# 介入の妥当性の判断

2026-10-08 追加。モデルの介入([MODEL_INTERVENTIONS.md](MODEL_INTERVENTIONS.md))を既定にするかどうかを、何で判断するか。
オーナー指示「潮流計算とか何かで妥当性判断とかしたいけどその方法まで考えて実施しておいて」を受けて作り、
介入 #48(変電所内の変圧器を OSM で観測した組で結ぶ)で最初に使った。結果は
[reports/station_node_breaker_adoption_2026-10-07.md](reports/station_node_breaker_adoption_2026-10-07.md) §11。

## 3 つの物差し

どれか 1 つだけで採否を決めない。3 つが同じ向きを指したときだけ既定にする。

| 物差し | 問い | 正解に使うもの | 道具 |
|---|---|---|---|
| 1. 構造 | 介入が作る接続・設備は実在するか | OSM と独立の公表資料。系統情報公表の変圧器表、出典 DB(`data/transformer_sources.jsonl`)、各社の空容量・予想潮流一覧 | `scripts/validate_intervention.py` の `topology_vs_published`、公表一覧での個別の裏取り |
| 2. 潮流 | 介入で、潮流が公表実績に近づくか | 公表の潮流実績(年統計。線ごとに照合済み) | 同 `flows_vs_observed` |
| 3. 物理 | 解ける網のままか | 収束・電圧・損失・過負荷の数 | 同 `physics` |

### 1. 構造

介入が張る(または外す)ものを、OSM とは別の資料で確かめる。観測の誤りを観測で確かめても意味がない。

- 予測ごとに「正解の組をいくつ作れたか(再現率)」を数える。正解の資料は全台を載せているとは限らないので、
  予測にあって正解に無いものは「誤り」でなく「裏付け無し」と数える。
- 介入あり・なしで予測が分かれる所だけを別に数える。そこ以外は両方同じなので差が出ない。
- 手元の資料で決め手が無いときは、分かれる所を公表資料で 1 件ずつ裏取りする(#48 では各社の空容量・予想潮流一覧)。

### 2. 潮流

- 介入なし・ありで潮流を解き、線ごとの潮流を鍵つきで書き出す(`run_full_powerflow_from_db.py --dump-flows`)。
- 公表の潮流実績と同じ線で比べる。照合は `scripts/export_obs_compare.py` と同じ(観測の線 → モデルの線の経路)。
  モデルは 1 断面なので、実績の p95(絶対値)との比の対数誤差と、平均の向きの一致を見る。年度ごとの記録は 1 本にまとめる。
- **全線と、介入した場所の近く(15 km 以内)を分ける。** 介入は局所なので、全線の平均では薄まって差が見えない。
- 線ごとに「近づいた/離れた」を数え、符号検定の p 値を付ける。変化が 0.05(対数)未満の線は数えない。
- モデルの絶対誤差は大きい(全線の中央値で約 2.2 倍)。潮流の物差しは「向き」を見るもので、構造の物差しより弱い。

### 3. 物理

収束、最低電圧、損失、100% を超える線と変圧器の数。新しい過負荷が出たら、それが介入の誤りか、推定した容量のせいかを分けて書く。

## 使い方

```bash
PYTHONPATH=. .venv/bin/python scripts/run_full_powerflow_from_db.py --dump-flows --no-observed-trafos --output-dir OFF
PYTHONPATH=. .venv/bin/python scripts/run_full_powerflow_from_db.py --dump-flows --observed-trafos --output-dir ON
PYTHONPATH=. .venv/bin/python scripts/validate_intervention.py --off OFF --on ON \
    --matched-cache /tmp/obs_matched.json --out docs/reports/<日付>/validation.json
```

公表実績(`data/external/system_disclosure/normalized/line_observations.csv`)は非追跡なので、手元のチェックアウトで回す。
`--matched-cache` は照合の結果(数分かかる)を使い回すため。

他の介入に使うときは、介入の切り替え(引数か環境変数)を OFF と ON に渡す。介入した場所の一覧は、潮流の summary の
台帳から取る(#48 は `islands.*.observed_trafos`)。台帳を持たない介入は、まず台帳を作る(MODEL_INTERVENTIONS の保守規約 2)。

## 公表資料の扱い

東京電力パワーグリッドと関西電力送配電の公表資料の値(線路・変圧器の容量など)は All-Rights-Reserved。
私的な検証と集計にだけ使い、生の値をリポジトリにもモデルの書き出しにも入れない。レポートには判定と出典 URL だけを書く。
値の控えは非追跡の `data/external/system_disclosure/private_checks/` に置く。
