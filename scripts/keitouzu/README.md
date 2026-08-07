# scripts/keitouzu — open-keitouzu 突合パイプライン

[open-keitouzu](https://github.com/ibarapascal/open-keitouzu)（十社公式系統図PDFから
抽出された基幹＋154kV の**論理トポロジ**、CC BY 4.0）を、AGJ built 正典への
**独立検証ソース**として突合する。

先方の `crosswalk.csv` が AGJ dataset v1.6.0 のノード ID への対応 657 件を同梱しており
（`target_system=ajg`）、**657/657 が built ノード ID に完全解決**する。

## 使い方

```bash
python3 scripts/keitouzu/fetch_keitouzu.py       # ピン留めコミットから data/external/keitouzu/ へ取得（sha256検証）
python3 scripts/keitouzu/crosscheck_keitouzu.py  # docs/reports/keitouzu_crosscheck_<date>.{md,json} を生成
```

`data/external/` は untracked（家訓: 外部データは源泉に留める）。tracked なのは
本スクリプトと生成レポートのみ。

## 検証の意味論

| 分類 | 意味 |
|---|---|
| hop=1 | keitouzu の辺が built で直接の変電所隣接として再現 |
| hop=2..4 | built が中間変電所で区間分割している粒度差（実質整合） |
| 食い違い候補 | 公式図は接続を主張するが built で再現されない。**どちらかが誤り** |
| 未解決 | 端点が crosswalk 未対応（地下変電所・匿名站・発電所白枠など） |

## 厳守事項

- **候補の自動採用はしない。** 採用は人間判断＋`docs/MODEL_INTERVENTIONS.md` への
  ①根拠②帳簿③無効化の3点記帳が必須。
- keitouzu 自体も人手 review を経ていない（confidence 大半が `extracted`、誤り率未測定）。
  食い違いは「公式図が正しい」ことを意味しない。原図（manifest の archive_url）に
  当たってから判断する。
- 帰属表示: 本データ利用箇所には CC BY 4.0 の attribution が必要（トップ README の
  Data Source 節に記載済み）。

## ピン留め

- commit `db1c6c6597e7210195b692a15fff4ad7de32a6db`（v1, 2026-08）
- 上流は予告なく改版する。更新時は fetch スクリプトの sha256 を更新し、
  crosscheck を再走させて差分をレポートすること。
