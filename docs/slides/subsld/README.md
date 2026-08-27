# SubSLD 発表資料

| ファイル | 用途 |
|---|---|
| `SubSLD法_academic.pptx` | 発表用デッキ（14枚・白基調・定式化と評価・ネイティブ数式） |
| `TALK_NOTES.md` | **発表台本**（15分/8分・デモ手順・想定質疑・事前チェック） |
| `build_deck_academic.js` | pptxgenjs 生成スクリプト |
| `assets/` | 図版（GeoPane クロップ・SLDPane・地域タイル） |

## 再生成

```bash
npm install pptxgenjs          # 初回のみ
node build_deck_academic.js    # → SubSLD_academic.pptx
```

出力名はスクリプト側の `writeFile` で決まる。上表の日本語ファイル名は配布用に
リネームしたもの。ダーク基調の一般向け版も一時期あったが、数値と構成が本デッキに
追い越されたため削除した（必要なら git 履歴 `192e95b` 以前から復元できる）。図の位置ずれ・文字あふれの確認は次で行う:

```bash
soffice --headless --convert-to pdf SubSLD_academic.pptx
pdftoppm -jpeg -r 100 SubSLD_academic.pdf pg   # 全ページを目視
```

## 数値の同期

デッキ内の実測値（母線way 14.2%・棄権 39.4%・CIM BusbarSection 4,743 / Bay 8,475 等）は
CHANGELOG v1.8.0 および issue #49 と一致させること。データを再生成したら
`TALK_NOTES.md` 末尾のチェックリストに従って確認する。

## 関連

- 論文: [`papers/subsld/`](../../../papers/subsld/)（IEEEtran・6ページ）
- 手法文書: [`docs/SUBSLD_METHOD.md`](../../SUBSLD_METHOD.md)
- ビューア: https://lutelute.github.io/All-Japan-Grid/subsld.html
