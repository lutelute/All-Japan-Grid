# SubSLD paper (IEEE journal format)

**SubSLD: Evidence-Paired Generation of Substation Single-Line Diagrams from
Volunteered Geographic Information**

All-Japan-Grid v1.8.0 の SubSLD法 を論文化したもの。手法文書
[`docs/SUBSLD_METHOD.md`](../../docs/SUBSLD_METHOD.md) が実装寄りの記述、
本稿が学術的定式化（証拠閉包作用素・下界推定器・三値推論）にあたる。

## ビルド

```bash
bash build.sh          # pdflatex 3パス → subsld.pdf
```

TeX Live（IEEEtran, algorithmicx, booktabs, hyperref）が必要。

## 構成

| ファイル | 内容 |
|---|---|
| `subsld.tex` | 本文（IEEEtran journal・5ページ） |
| `figs/fig_concept.pdf` | Fig.1 概念図（観測 O → 証拠閉包 F → 構造 S* → ペア図） |
| `figs/fig_pair_geo.png` / `fig_pair_sld.png` | Fig.2 実証ペア図の実例（新京葉 500/275/154/66kV） |
| `figs/fig_coverage.pdf` | Fig.3 被覆評価（binding分布・流向内訳・母線way地域差） |
| `build.sh` | ビルドスクリプト |

## 図の再生成

Fig.1・Fig.3 は matplotlib 生成（本リポジトリの実測値を直書き）。Fig.2 は
`scripts/build_substation_structure.py --fig` の出力から GeoPane/SLDPane を
個別クロップしたもの。数値の出典は CHANGELOG v1.8.0 および issue #49。

## 本稿の主要数値（すべて実測）

- 7,239 サイト / 47,979 端子 / 母線 2,559 実測 + 2,669 推定
- 回線数の証拠被覆 68.2%（40,087線）・導体数タグ 12.7%
- binding分布: vertex 15.7% / polygon 29.3% / leadin 55.0%
- 流向: in 55.4% / out 5.2% / ⊥棄権 39.4%（18,851線グループ）
- 母線way記載率 14.2%（北海道53.3% ⇔ 沖縄5.1%）・Point型3.2%
- 判読14所: 64% が「直せるOSM欠測」

## 投稿前に片づける（2026-08-29 時点）

- **参考文献が未記載**（`\cite` が 0 件）。SciGRID / PyPSA-Eur / TTPLA は §II で
  名前を出しているだけなので、BibTeX を起こして引用に変える。**投稿の阻害要因。**
- **著者・投稿先が未定**（現状は単著・IEEEtran journal 体裁のまま）。
- **母線way記載率のドリフト**: 本文と Fig.3 の 14.2 % は issue #49 測定時点の値。
  介入#35/#36 と構造DB再生成を経た現在のデータで同じ定義（`osm_way_keys` を
  持つ母線を1つ以上もつサイト / 全サイト）を再計算すると **1,086 / 7,239 = 15.0 %**
  になる（地域差の傾向は不変。北海道 54.6 % ⇔ 東京 5.0 %）。中国・九州の2地域だけ
  差が大きい（14.7 / 16.5 % に対し図は 10.9 / 10.3 %）ので、**投稿前に測定
  スクリプトを一本に固定して Fig.3 ごと引き直すこと**。本文の数値と図はいまは
  相互に整合しているため、片方だけ書き換えてはいけない。
