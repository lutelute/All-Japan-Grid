# SubSLD 発表資料

デッキは**用途で2本**。中身は重なるが、立て方と根拠の縛りが違う。

| ファイル | 枚数 | 用途 |
|---|---|---|
| `SubSLD_paper_talk.pptx` | 16（本編14＋予備2） | **論文（`papers/subsld/`）の発表**。節バッジ §I–§X で本文に紐づき、数値は論文にあるものだけ |
| `SubSLD法_academic.pptx` | 14 | 研究会・ゼミ向けの一般発表。論文の節構成に縛られない |
| `TALK_NOTES.md` | — | 発表台本（15分/8分・デモ手順・想定質疑・事前チェック） |
| `build_deck_paper.js` / `build_deck_academic.js` | — | pptxgenjs 生成スクリプト |
| `assets/` | — | 図版（GeoPane クロップ・SLDPane・論文図の PNG・QR） |

論文発表なら `SubSLD_paper_talk.pptx` を使う。こちらは「数値衛生」を守って作ってある
（スクリプト冒頭のコメント参照）:

1. 同じ数値を2枚に出さない
2. 論文 Table II 系（S10）と Table III 系（S13）を同じ枚に並べない
3. 論文本文にある数値のみ。図の中の値は図に語らせ、再プロットしない
4. **開閉器・ループ・2ロールは論文未収載**なので予備 S16 に隔離し、赤帯で明示する

## 再生成

```bash
npm install pptxgenjs          # 初回のみ
node build_deck_paper.js       # → SubSLD_paper_talk.pptx
node build_deck_academic.js    # → SubSLD_academic.pptx（配布時に日本語名へリネーム）
```

図の位置ずれ・文字あふれは実際にレンダして目視する:

```bash
soffice --headless --convert-to pdf SubSLD_paper_talk.pptx
pdftoppm -jpeg -r 100 SubSLD_paper_talk.pdf pt   # pt-01.jpg … を全枚確認
```

## タイトルスライドの切り替え（academic 版）

タイトルは2パターン用意してある。`build_deck_academic.js` 冒頭付近の
`TITLE_LAYOUT` を書き換えて再生成する。

| 値 | 構図 | 性格 |
|---|---|---|
| `"band"`（既定） | 上下（文字が上・全幅の写真帯が下） | 論文タイトル型。副題・所属まで入り情報量が多い |
| `"split"` | 左右（文字が左・写真が右半分フルブリード） | 引きが強く掴みが良い。写真が主役 |

```js
const TITLE_LAYOUT = "band";   // "band" | "split"
```

どちらも `assets/` の既存素材だけで完結する（band は `title_strip.png`、
split は `geo_shinkeiyo.png`）。場に合わせて選ぶ。paper 版は band 固定。

## 数値の同期

デッキ内の実測値は `data/structures/summary.json`（サイト 7,239 / 端子 47,979 /
母線 5,228 / ベイ 8,753 / 変圧器 2,586 / 接続 11,586）と CHANGELOG v1.8.0・issue #49 に
一致させること。CIM 側の件数（BusbarSection 4,743 / Bay 8,475）は電圧階級が確定しない
VoltageLevel を書き出さないぶん構造DBより少ない — **この差は仕様**で、論文 §VIII に
理由を書いてある。データを再生成したら `TALK_NOTES.md` 末尾のチェックリストで確認する。

母線way記載率 14.2 % は issue #49 測定時点の値で、現行データでは 15.0 % にドリフト
している。論文本文と Fig.3 が相互に整合しているため**片方だけ直さない**こと
（→ `papers/subsld/README.md` の「投稿前に片づける」）。

## 関連

- 論文: [`papers/subsld/`](../../../papers/subsld/)（IEEEtran・6ページ）
- 手法文書: [`docs/SUBSLD_METHOD.md`](../../SUBSLD_METHOD.md)
- ビューア: https://lutelute.github.io/All-Japan-Grid/subsld.html
