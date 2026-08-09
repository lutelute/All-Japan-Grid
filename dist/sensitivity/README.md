# 感度行列 PTDF / LODF — 潮流を行列ひとつの掛け算にする

built 正典（`docs/data/built/all.json`）から**決定的に再生成可能**な線形感度行列。

- **PTDF** `[枝 × バス]` — バス注入 1 MW あたり各枝の潮流が何 MW 動くか。
  `枝潮流 = PTDF · バス注入` で、反復解法なしに潮流が得られる
- **LODF** `[枝 × 枝]` — ある枝の停止が他の枝の潮流をどれだけ動かすか。
  `停止後の潮流 = 基準潮流 + LODF[:,k] · 基準潮流[k]` で N-1 が解き直し不要になる

## 再生成（全4島 約 15 秒 + 保存）

```bash
PYTHONPATH=. python scripts/sensitivity/build_sensitivity.py            # 全4島
PYTHONPATH=. python scripts/sensitivity/build_sensitivity.py --islands west
PYTHONPATH=. python scripts/sensitivity/build_sensitivity.py --no-lodf  # PTDFのみ(軽い)
```

**行列本体（`*_sensitivity.npz`）は git に入れていない。** 密行列で west の LODF だけで
約 310 MB あり、再生成が 5 秒で済むため。代わりに**索引表と sha256 指紋**を同梱してあり、
再生成したものが同一かを `meta.json` の `sha256` で確認できる。

## 同梱ファイル

| ファイル | git | 内容 |
|---|---|---|
| `{island}_sensitivity.npz` | ✗ 再生成 | `ptdf` `lodf` `is_bridge` `base_mva` `slack_col` |
| `{island}_bus.csv` | ✓ | 行列の**列** → バス。`built_node_id` / `kv` / `lat` / `lon` |
| `{island}_branch.csv` | ✓ | 行列の**行** → 枝。`element` / `name` / `kv` / `capacity_mva` / `is_bridge` |
| `meta.json` | ✓ | 版・島ごとの統計・sha256 指紋 |

## 使い方

```python
import numpy as np, pandas as pd

d = np.load("dist/sensitivity/west_sensitivity.npz")
ptdf, lodf = d["ptdf"], d["lodf"]                    # [枝×バス], [枝×枝]
bus = pd.read_csv("dist/sensitivity/west_bus.csv")
br  = pd.read_csv("dist/sensitivity/west_branch.csv")

# 1) 任意の注入パターンから枝潮流を出す（反復なし・行列ベクトル積1回）
inj = np.zeros(ptdf.shape[1])                        # [MW] バス毎の注入（発電−負荷）
inj[bus.index[bus.built_node_id == "west_sub_123@275"][0]] = 1000
flow = ptdf @ inj

# 2) ある枝を停止したときの他枝の潮流（DC の枠内では厳密）
k = 42
if not br.is_bridge[k]:                              # 橋では LODF が定義できない
    flow_after = flow + lodf[:, k] * flow[k]

# 3) その地点に繋いだとき最初に埋まる枝
loading = np.abs(ptdf[:, col]) * 1000 / br.capacity_mva.to_numpy()
worst = br.iloc[np.nanargmax(loading)]
```

## 前提と限界

- **対象は各島の最大連結成分**。PTDF は連結かつ単一 slack の網でしか定義できない。
  本モデルは島ごとに数百の成分へ断片化しており、最大成分は需要の約 90% を保持する
  （`docs/reports/pf_frontier_*.md`）。残りの断片上のバスは行列に含まれない
- **直流近似**（電圧一定・無損失・小角度）。AC 解との枝潮流の差は中央値 0.2〜0.6 MW、
  95 パーセンタイルで 4〜48 MW（`docs/reports/sensitivity_bench_*.md`）。
  過負荷になりうる枝の screening には十分だが、**確定値としては AC で解き直すこと**
- **橋では LODF が定義できない。** 落とすと網が割れる枝で、本モデルでは 30〜36% を占める。
  `is_bridge` が立っている行/列は N-1 の一括評価から外し、個別に解く必要がある。
  なお `makeLODF` は inf を返さず対角を均すため、`isfinite` では橋を検出できない
  （判定は LODF の分母＝自己感度 `PTDF[k,f] − PTDF[k,t]` が 1 になるか）
- **`capacity_mva` は理論値**。線路は `√3·V·I`、変圧器は銘板容量で、実運用容量ではない。
  本モデルでは基準潮流が既にこれを超える枝があり（66kV 層に集中）、
  絶対的な空き容量の算出には容量データの出典付き充填が要る
- 数値誤差は問題にならない水準（条件数 3.8e4〜9.2e7、倍精度の理論限界 8e-12〜2e-8 MW、
  float32 保存でも最大 2.9e-4 MW。`docs/reports/sensitivity_numerics_*.md`）

## 品質ゲート

`tests/test_sensitivity_dist.py`。索引表の整合（行数・容量・橋フラグ）と、
`PTDF·P` が pandapower の DC 解を機械精度で再現することを確認する。

## 関連

- 速度・精度の実測 — `docs/reports/sensitivity_bench_*.md`
- 数値精度の切り分け — `docs/reports/sensitivity_numerics_*.md`
- 行列そのものの可視化 — `docs/assets/sensitivity/matrix_*.png`
- 地点別の系統混雑 — `docs/reports/hosting_capacity_*.md`
