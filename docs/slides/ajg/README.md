# All-Japan-Grid 全史デッキ（the making of）

プロジェクトを最初から作った記録の発表資料。**5幕構成・16枚・20分**。

| ファイル | 内容 |
|---|---|
| `AllJapanGrid_story.pptx` | 本編デッキ（各枚のノート欄に話し方入り） |
| `build_deck_story.js` | pptxgenjs 生成スクリプト |
| `assets/` | 図版（既存の docs/assets/figs・subsldデッキ素材の再利用＋flow_mapフレーム） |

## 構成（5幕）

| 幕 | 版 | 主題 | 前の幕が残した問い |
|---|---|---|---|
| 第1幕 | v1.0 | 地理を掘る（OSM抽出・7段補完・UC/PF一式） | 「地図はある」→ モデルにした |
| 第2幕 | v1.1–1.4 | 電気にして標準で渡す（CIM/CGMES・統一DB・全10地域AC） | 作れた → 解けるのか？ |
| 第3幕 | v1.5–1.6 | 誠実さを制度にする（介入台帳・fake-ACガード・二重抽出根治） | 解けた → 本当か？ |
| 第4幕 | v1.7 | 公式開示と接続する（様式5・OCCTO容量・実測突合） | 正した → 現実と合うか？ |
| 第5幕 | v1.8 | 変電所の中へ（SubSLD法） | 網はできた → 最後の暗箱へ |

出典は `papers/ieee-openaccess.tex`（パイプライン・UC結果）、`papers/subsld/`（第5幕）、
`CHANGELOG.md`。SubSLD法の深掘りは姉妹デッキ
[`../subsld/SubSLD_paper_talk.pptx`](../subsld/) へ。

## 数値衛生（このデッキ固有の1条）

**すべての数値に測定時点（版）を付す。** 変電所数は定義が版で変わる：
- **6,962** = データセットの変電所 feature 数（v1.2 で確定した測定値）
- **7,239** = SubSLD 構造DBのサイト数（v1.8・別定義）

この2つを無ラベルで並べない。また `ieee-openaccess.tex` 本文の 8,164 は
既知の誤記（同論文の表合計は 6,962）— デッキでは使わず、S16 で宿題として明示している。

## 再生成

```bash
node build_deck_story.js       # → AllJapanGrid_story.pptx（node_modules は ../subsld へのリンク）
soffice --headless --convert-to pdf AllJapanGrid_story.pptx
pdftoppm -jpeg -r 100 AllJapanGrid_story.pdf st   # st-01.jpg … を全枚目視
```
