# 端点別名表を入れると照合はどう変わるか（ドライラン・2026-09-03）

- モデル: **Claude Opus 5**（フォーク trackF2-tepco-alias）。**正典 `all.json` は未変更**
- 基準: 正典から `par_src=='circuit_sources'` の枝を `par_prev` へ戻した #44 適用前の状態
- 別名表: `data/reference/tepco_endpoint_aliases.json` **31 件採用**（別名ヒット 98 回・low 0 件）

## 結果 — 分類は大きく正直になり、更新枝は 4 本減る

| 指標 | 前 | 後 | 差 |
|---|---:|---:|---:|
| 照合できた出典レコード | 2,079 | 2,096 | +17 |
| うち route 照合 | 840 | 875 | +35 |
| 未照合 | 2,834 | 2,817 | -17 |
| **更新対象の枝** | **421** | **417** | **-4** |
| 食い違い | 66 | 68 | +2 |

### 未照合の理由（ここが本題）

| 理由 | 前 | 後 |
|---|---:|---:|
| `unresolved endpoints` | 1,725 | **701** |
| `no usable endpoint (anonymized)` | 0 | **902** |
| `no usable endpoint (non-endpoint marker)` | 0 | **105** |
| `no name` | 926 | 926 |
| `name found but kv/region mismatch` | 84 | 84 |

**「解けない 1,725 件」の正体が分かれた**のが最大の成果。1,024 件は「公表側が匿名化した端点」と「そもそも変電所でない表記」で、回収不能と確定した。残る 701 件が本当の未解決（大半は正典に変電所が無い＝OSM 欠落）。

### 更新枝が 4 本減る理由（正直に）

別名で九州の端点（「18苅田」「14西谷」等）が解けた結果、その線が **route 照合**（枝特定的）で当たるようになり、従来の **name 照合**（同名の枝すべてに一律適用）を上書きした。route の経路に含まれないスタブ枝 2 本が更新対象から外れる。

| 外れた枝 | 線 | 理由 |
|---|---|---|
| 33.77598,130.98487 – 33.7766,130.98653 | 苅田分岐線 220kV | route の経路（10 枝）に含まれないスタブ |
| 33.7761,130.97877 – 33.7766,130.98653 | 苅田分岐線 220kV | 同上 |

台帳の設計どおり「経路照合は枝特定的」なので **route を採るほうが正しい**が、**更新枝は増えない**ことは明記しておく。別名表の価値は回収数ではなく分類の正直さにある。

## 親が適用するときのコマンドとゲート

```bash
PYTHONPATH=. python3 scripts/apply_circuit_sources.py            # ドライラン(既定で別名表を使う)
PYTHONPATH=. python3 scripts/apply_circuit_sources.py --write    # 正典 par を更新
PYTHONPATH=. python3 -m pytest -q tests/test_tepco_alias.py tests/test_circuit_sources.py
```

ゲート: ノード/枝数・周波数跨ぎ枝が不変 / east・west ピーク AC が収束維持 / N-1 の本四連系・上野線が 2・3 回線のままであること（別名は九州にしか効かないので変化しないはず）。

## 再現

```bash
# #44 適用前の状態を作る(par_prev へ戻す)
python3 -c "import json;d=json.load(open('docs/data/built/all.json'));[e.update(par=e['par_prev']) or [e.pop(k,None) for k in ('par_prev','par_src','par_note')] for e in d['edges'] if e.get('par_src')=='circuit_sources'];json.dump(d,open('/tmp/pre44.json','w'),ensure_ascii=False)"
PYTHONPATH=. python3 scripts/apply_circuit_sources.py --built /tmp/pre44.json --out-dir /tmp/base
```
