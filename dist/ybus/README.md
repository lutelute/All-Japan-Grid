# 数値 Ybus — バージョン管理された検証済みアドミタンス行列

built 正典(`docs/data/built/all.json`)から**決定的に再生成可能**な、日本全国送電網の
数値アドミタンス行列。4周波数島(北海道50Hz / 東日本50Hz / 西日本60Hz / 沖縄60Hz)は
非同期のため別行列であり、「全国」はこの4ブロックの直和。

## 生成(全4島 約90秒)

```bash
PYTHONPATH=. .venv/bin/python scripts/gen_ybus_numeric.py           # 全4島
PYTHONPATH=. .venv/bin/python scripts/gen_ybus_numeric.py --islands west
```

品質ゲート: `tests/test_ybus_numeric.py`。バージョン履歴は `meta.json` の
`changelog`(現行 = `ybus_version` フィールド)。git はバイナリ非追跡
(meta.json / README のみ追跡)。

## ファイル(島ごと)

| ファイル | 内容 |
|---|---|
| `{island}.mat` / `.npz` | フル Ybus + **Bbus**(DC) + **Yf/Yt**(枝) + バス/枝属性 |
| `{island}_bus.csv` | バス表(ybus_index 順: 名前・kV・緯度経度・地域) |
| `{island}_branch.csv` | 枝表(枝 index 順: kind=line/trafo・名前・from/to ybus_index・長さ・par・tap) |
| `{island}_backbone.mat` / `.npz` / `_backbone_bus.csv` | Kron 縮約バックボーン(≥154kV。沖縄は132kV) |
| `meta.json` | バージョン・sha256指紋・検証結果・条件数 |

## MATLAB での使い方

```matlab
S = load('west.mat');
Y = S.Ybus;                    % 10193x10193 complex sparse (pu, 100 MVA base)
spy(Y);                        % スパーシティ
% DC 潮流 / PTDF:
B = S.Bbus;                    % DC 行列(makeBdc 出力)
% 線潮流(電圧プロファイル V が与えられたら):
If = S.Yf * V;                 % 各枝の from 側電流 (枝順 = branch_*.csv)
% 枝→名前:  S.branch_name{k},  from/to は 0-based の ybus_index
% バックボーンだけで解析:
R = load('west_backbone.mat'); % 2779バス。full_index が元行列の行番号
```

## 検証(全島・pytest で回帰保証)

- 複素対称性 max|Y−Yᵀ| = 0
- 公式 makeYbus vs 教科書式(1/(r+jx)・並列合成・vk/vkr 変圧器)の相互アドミタンス
  一致 p99 ≤ 2e-16(機械精度)
- 再構成恒等式 **Ybus == Cfᵀ·Yf + Ctᵀ·Yt + diag(Ysh)** が厳密成立
- Kron 縮約 == 密 Schur 補行列(機械精度)
- AC/DC バス順序整合・枝順序(lookup)整合・条件数ゲート(<1e9)

## 正直な注意(現行モデルの限界)

- 変圧器は電圧階級ペアの**合成典型値**(タップ=1固定)。実銘板・タップは
  構造DB Phase B(出典付き充填)で置換予定(v4候補)
- 線路 R/X/B は `config/line_types.yaml` の階級代表値 × 実延長 × 並列回線数。
  導体種別・地中ケーブルの個別性は未反映
- 電圧不明バスは 66kV(最低送電クラス)として扱う(builder 既定)
