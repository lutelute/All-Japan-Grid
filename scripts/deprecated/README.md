# scripts/deprecated/ — 隔離された旧版スクリプト

**削除ではなく隔離**: ここにあるスクリプトは設計・試行錯誤の記録として保全されている。
ただし**後継スクリプトと同じ出力ファイルを書く**ため、誤って実行すると論文用の公開図を
旧品質で上書きする。通常運用では使用しないこと。

| 旧版（ここ） | 後継（scripts/） | 共有していた出力 | 隔離理由 |
|---|---|---|---|
| `gen_dynamics_fig.py` | `gen_dynamics_fig_v2.py`（Kundur 2エリアモデル） | `papers/figs/fig_dynamics_improved.png` | 旧版はプロトタイプ動揺モデル。自身の docstring で DEPRECATED 宣言済み |
| `gen_satellite_500kv.py` | `gen_satellite_v3.py`（正しい Web Mercator 投影） | `papers/figs/fig_satellite_validation.png` | 旧版は投影が不正確。自身の docstring で DEPRECATED 宣言済み |

- 隔離日: 2026-06-08（全体レビュー Phase A）
- 完全に不要と確定したら削除してよい（git 履歴にも残る）
