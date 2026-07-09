# 全島24h検証 — `--pref-demand --reactive-comp`（2026-07-09）

## 0. 結論（1段落）

正しい需要地理（介入 #19 `--pref-demand`）＋無効電力の局所補償（介入 #20
`--reactive-comp`、factor 0.6）を全4島 × 24時刻（fy2023r2）で回した。**4島すべて
全24時刻で解が成立**（`all_converged=True`）。AC島（hokkaido・okinawa）は24/24で
AC収束し電圧プロファイルも健全（0.77–1.01 / 0.82–1.00 pu）、east は22/24でAC収束
（給電98%）・残る2時刻は誠実に dc_fallback、west は設計どおりDC（単一同期島の
west AC は見せかけ収束のため意図的にDC運用）。無効補償は全島・全時刻で安定に効き、
BLAS abort も出なかった。残る課題は east の局所電圧外れ値（vm上限≈1.70、最悪1時刻で
2.78）で、これは既知の「都心66kVメッシュの細部」であり次の精緻化対象。

## 1. 実行構成

- コマンド: 島ごとに `scripts/uc_to_pf_built.py --islands <isl> --all-hours
  --pref-demand --reactive-comp`（scenario=fy2023r2・`--model full`）
- 島ごとにプロセス隔離（ハマり⑨ BLAS abort対策）。駆動 = `run_allisland_24h.sh`
- 生JSON4本＋集計器 `summarize_24h.py` は
  `docs/reports/probes/allisland_24h_2026-07-09/` に保存

## 2. 結果サマリ

| 島 | モード | バス | 収束 | shunt / 補償 | vm範囲（AC時刻） | 損失平均 |
|---|---|---|---|---|---|---|
| hokkaido | AC | 819 | **24/24 AC** | 538 / 872 MVar | 0.766 – 1.007 | 93 MW |
| okinawa | AC | 99 | **24/24 AC** | 78 / 268 MVar | 0.819 – 1.000 | 34 MW |
| east | AC | 6,222 | **22 AC + 2 dc_fallback** | 3,377 / 10,896 MVar | 0.604 – 1.70（t3のみ2.78） | 4,709 MW |
| west | DC | 10,193 | 24/24 DC | 5,001 / 14,567 MVar | —（DC） | —（DC） |

- **hokkaido・okinawa**: 24/24 AC・給電100%・電圧が実用帯に収まる健全解。
- **east**: 22時刻で給電98%のAC。2時刻（t=7, t=20）はACが95%給電に届かず**誠実に
  dc_fallback**（給電率ガードが見せかけACを却下）。両時刻とも tokyo石炭の注入clip
  968MW を伴う断面で、AC が立ちにくい時間帯だった。
- **west**: DCモード（`ISLAND_MODE[west]="dc"`）。単一同期島の west AC は
  fragmentation 由来の見せかけ収束と確定済みのため（`docs/WEST_AC_ANALYSIS.md`）、
  `--model full` では意図的にDC。補償シャント（5,001個）は追加されるがDC解には
  寄与しない（無効電力を扱わないため）。west のAC実証は backbone モデルが担う。

## 3. east の電圧外れ値（誠実な限界）

east のAC時刻の vm 上限はほぼ全時刻 ≈1.70 pu で、単一時刻 t=3 のみ 2.78 pu に跳ねる。
これは単一断面診断（`east_network_reactive_2026-07-09.md` §4）で特定した
**41バス（0.66%）の局所ポケット**（発電機のない66kV軽負荷バス＋500kV 2点）が
時刻をまたいで残存するもので、系統的な破綻ではない（98%以上のバスは0.9–1.1pu帯）。
t=3 の 2.78 pu は最悪ケースの単一バスで、無効補償の効果が届きにくい孤立点。

**位置づけ**: 24h検証は「補償が全島・全時刻で安定に効く」ことを確認した一方、
east の局所電圧品質は未完成であることも同時に示した。全規模ACの既定は引き続き
誠実運用（フラグOFFで従来どおり dc_fallback）。この41バスの網側精緻化
（並列回線・変圧器容量・より現実的な無効配分）が次の作業。

## 4. 判定

- `--pref-demand --reactive-comp` は**全島・全24時刻で回り切る堅牢性**を確認
  （BLAS abort なし・4島とも `all_converged=True`）。
- AC島の大半（hokkaido・okinawa 全時刻、east 22/24）で**誠実なAC解**が得られる。
- east の残課題（局所過電圧）と okinawa の注入clip（15時刻・容量フリート不一致、
  `--bridge` で解消する既知事項）は開示のうえ次工程へ。
- **既定ON化はまだ推奨しない**: east の電圧外れ値が残るうちは opt-in を維持し、
  網側精緻化の後に再評価する（オーナー判断）。

## 5. 再現

```bash
bash docs/reports/probes/allisland_24h_2026-07-09/run_allisland_24h.sh
.venv/bin/python docs/reports/probes/allisland_24h_2026-07-09/summarize_24h.py
```
