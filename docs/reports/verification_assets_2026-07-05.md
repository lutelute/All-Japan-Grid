# 検証資産の棚卸し — データ論文 V&V 章の材料 2026-07-05

**モデル**: Claude Fable 5
**目的**: 2026-07-02〜05 の Phase B / Ybus v4 / 潮流実証で生まれた検証資産を、
データ論文(Sci Data 級)の Validation 章にそのまま引ける形で一覧化する。
各項目は「主張・根拠ファイル・再現コマンド」の三点セット。

## 1. 出典トレーサビリティ(捏造防止の機械保証)

| 主張 | 数字 | 根拠 |
|---|---|---|
| 変圧器の全値が出典URL+原文引用つき | 611レコード(existing 266/planned 345)・invalid 0 | `data/transformer_sources.jsonl` + `python scripts/transformer_provenance.py verify` |
| 欠落出典は機械的にREJECTされる | selftest(no_url/no_quote/fake_url 全拒否) | `tests/test_transformer_provenance.py::test_reject_without_provenance` |
| planned(整備計画)は現況モデルに混入しない | 構造DB再生成でsummary不変・西山形はexisting 300が入りplanned 450が入らない | `::test_planned_not_applied` `::test_before_value_applied_nishi_yamagata` |
| 発電容量も同規約 | 45件(原子力/火力/揚水ほか)・verify 45ok | `data/generator_capacity_sources.jsonl`(2026-06-20系) |

## 2. 行列の数値検証(Ybus v4.0.0)

| 主張 | 数字 | 根拠 |
|---|---|---|
| 複素対称性 | max\|Y−Yᵀ\|=0 全4島 | `dist/ybus/meta.json` checks |
| 公式makeYbus vs 教科書式の相互アドミタンス | p99 ≤ 1.8e-16(機械精度) | 同上 |
| 再構成恒等式 Ybus==Cfᵀ·Yf+Ctᵀ·Yt+diag(Ysh) | 厳密ゼロ 全島 | 同上(v3) |
| Kron縮約==密Schur補行列 | 機械精度一致 | `tests/test_ybus_numeric.py` |
| バージョン・指紋管理 | v4.0.0・sha256指紋・CHANGELOG | meta.json(沖縄=v3と指紋一致=変更の局所性) |
| 銘板の伝播検証 | 12サイト・@nameplate刻印・電圧ペア厳密一致のみ | `{island}_branch.csv` + `meta.trafo_nameplate` |
| 条件数ゲート | 全島PASS(west 3.1e7 — v3の6.2e7から改善) | ybus_gate |

## 3. 潮流・時系列の実証(2026-07-05)

| 主張 | 数字 | 根拠 |
|---|---|---|
| 全規模AC(縮約なし)収束 | east 6,205バス・hokkaido 836・okinawa 99(vm 0.83-1.02pu) | `docs/data/powerflow_full/summary.json` |
| westはDCを正典とする(誠実性) | AC「収束」=fragmentationの見せかけと確定→DC解のみ出荷 | `docs/WEST_AC_ANALYSIS.md` + 遺物AC12ファイル削除(commit d80c0f1) |
| UC 24h×全4島=96断面 全収束 | east AC 24/24 ほか | `docs/reports/uc_pf_built_*_allhours_2026-07-05.json` |
| UC連系線 vs 実網tie潮流の整合(east) | tohoku→tokyo MAE 384MW(~7%)/24h | `docs/reports/slack_tie_diagnosis_2026-07-05.md` §3 |
| 需給整合の限界を定量開示 | slack east 25.5-37.3%の4メカニズム分解・断片上の実在電源17.9GW | 同 §2(**負の結果も検証資産**) |
| 実在しない連系線の検出 | kyushu↔shikoku 445MW(幻tie)を突合が検出 | 同 §3(検証手法が誤りを見つける能力の実証) |

## 4. CGMES(IEC 61970)との関係 — 既知ギャップ

- CGMES Level2 出力(`scripts/export_cim_level2.py`)は **snapped系譜**(`build_and_solve`)の
  netから `PowerTransformerEnd.ratedS = sn_mva × parallel` を書く。
- **Ybus v4の銘板は built系譜**(`build_island_net`)に適用したため、**現行CGMESには
  銘板が届いていない**(ratedSは階級典型値のまま)。
- 選択肢: (i) snapped系譜の `insert_transformers`(src/powerflow/transforms.py)へ同じ
  銘板適用を移植(バス名→サイト名の対応付けが要検討) (ii) CGMES出力をbuilt系譜へ移行
  (「builtが正典」原則には(ii)が整合するが工事が大きい)。**現状は本ドキュメントで
  ギャップとして明示**(論文でモデル系譜を書き分ける際の注意点)。
- CGMES自体の検証は既了: 全10地域VALID・dangling 0・cim2pp往復10 passed(2026-06-25)。

## 5. 論文で正直に書くべき限界(現時点)

1. 変圧器: 銘板12サイト以外は階級典型値。タップ出典0件(全器tap=1)。vk%/vkr%は銘板器も典型値
2. sn_total_mva(有報97件)は検算・上限用途(バンク按分せず)
3. 潮流の需給整合: slack 18-56%(島別・§3の分解つき)。「回る」と「正しく流れる」の距離を明示
4. east ACのピーク断面はprune ladder込み(発電未達~8.8GW@t=17)
5. 断片成分(east 517/west 2,531)は接続修復待ち — 修復判断は人間レビュー
   (機械はスクリーニングまで、2026-07-05オーナー方針)
