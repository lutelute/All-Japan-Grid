# West-island AC 診断スクリプト群

west 島（60 Hz, 6 地域）の **AC 潮流非収束の真因究明**に用いた段階診断スクリプト。
pws-160core 上で実行し、`/tmp/west_base.pkl`（west 島を一度 build したキャッシュ、約 17 MB）
をロードして高速に反復する設計。結論と全経緯は `docs/WEST_AC_ANALYSIS.md` を参照。

| スクリプト | 用途 |
|---|---|
| `test_west_reactive.py` | Q（reactive 補償）感度 sweep — Q は無関係と判定 |
| `test_west_connectivity.py` | 連結成分・極短線の構造診断（**最初に実行**し `/tmp/west_base.pkl` を生成） |
| `test_west_fuse.py` | 極短線（near-zero-Z）融合の効果 — 副次的と判定 |
| `test_west_byregion.py` | 地域別 SOLO AC — 「発電>負荷で収束 / 負荷>発電で FAIL」の相関 |
| `test_west_rebalance.py` | 地域別 re-balance（発電を地域別に負荷へ合わせる） |
| `test_west_feasible.py` | 負荷 feasibility cap の効果 |
| `test_west_final.py` | re-balance + 地域別 AC（4/6 地域収束を確認） |
| `test_kansai_diag.py` | 変圧器/低圧部/初期値の切り分け（`DIAG_ZONE=kansai` または `kyushu`） — **変圧器が真因** |
| `test_kansai_trafo.py` | 悪条件変圧器の是正トライアル |

## 実行順

```bash
# 1) base を build して /tmp/west_base.pkl にキャッシュ（初回のみ ~9 分）
PYTHONPATH=. python scripts/diagnostics/test_west_connectivity.py
# 2) 以降は pickle ロードで高速（数秒〜分）
PYTHONPATH=. python scripts/diagnostics/test_west_byregion.py
DIAG_ZONE=kansai PYTHONPATH=. python scripts/diagnostics/test_kansai_diag.py
```

> 注: これらは一回的な真因究明の記録であり、本番パイプライン（`scripts/run_national_powerflow.py`）
> からは独立している。`/tmp/west_base.pkl` が無い場合は `test_west_connectivity.py` が再生成する。
