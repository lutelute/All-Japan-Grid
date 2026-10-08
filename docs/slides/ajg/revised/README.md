# All-Japan-Grid story 改善版

[PowerPointを開く](output/AllJapanGrid_story_revised_2026-09-12_v4.pptx)

[全30枚の一覧画像](output/preview.png)

本編26枚＋補足4枚、28〜30分程度。元の `AllJapanGrid_story.pptx` は保存し、別ファイルとして再構成した。研究者・学生向けに、公開地理を研究用の電力系統モデルに変えるときの課題と、その確認方法を説明する。

## 話の流れ

| 範囲 | 聴衆が理解すること |
|---|---|
| 1–6 | 何を調べるモデルか。地図だけでは電気の接続が決まらない理由 |
| 7–11 | 母線・ベイ・端子・変圧器。観測と推定と未確認の区別 |
| 12–16 | 接続訂正が計算を変える実例。収束・標準形式・UCの検証範囲 |
| 17–20 | 西日本の診断と、東日本の同一事故条件における急低下・回復 |
| 21–25 | 今回の接続再監査、秩父の断片、電圧判定バグ、本四の端点 |
| 26 | 根拠を接続モデルから計算結果まで追跡するという結論 |
| 27–30 | 数値の版、検証の限界、座標と電気母線の概念図、再現方法 |

各スライドに説明用ノートと出典を入れた。[発表ノートの一覧](TALK_NOTES.md) でも読める。

## 主な変更

- 元の41枚を、問い→接続→変電所内部→計算で確認→次の改善、という因果関係で再編した。
- 見出しを各ページの主張にし、本文の文字を大きくして、一度に読む論点を減らした。数値表はPowerPointで編集できるネイティブ表を使用した。
- 投稿用PDF、現在のTeX、元storyの数値を分離した。UCは投稿用PDF Table 6の783機版を採用し、757機／646機と混ぜていない。投稿PDF内部の図6と表6の機数不一致もノートに残した。
- SubSLD原稿の構内図と単線結線図を使い、全国のfeature数、サイト数、電圧別母線数を区別した。
- 収束を実系統の正しさと同一視せず、給電率・残差・slack・電圧の確認へつなげた。動揺図は過去のモデル実験と明示した。
- 全国接続を入力SHA付きで数え直し、新しい監査結果を具体例として追加した。

## GIF

新規に2本作成した。PowerPointには既存2本と合わせて4本のアニメーションを埋め込んでいる。

- [秩父の断片を広域から拡大する](assets/chichibu_review.gif): 実際のbuilt座標と枝を使用。近接点は接続確定を意味しない。
- [東日本の周波数低下と回復を読む](assets/east_frequency_explained.gif): `mm_traces_east_n3pk.npz` の保存時系列を使用。最低48.49 Hz、約15分後49.84 Hz。

編集画面ではGIFの最初のフレームだけが表示される場合がある。スライドショーでの再生用に埋め込んでいる。静止図として [周波数の最終状態](assets/east_frequency_final.png)、[秩父拡大図](assets/chichibu_detail.png) も保存した。

## 系統の監査

[接続レビューと改善の優先順位](../../../reports/codex_connection_audit_2026-09-12/REVIEW.md)

接続回収コードの不具合は修正した。近接候補と本四連系線の端点定義は、利用経路と証拠を記録した。正典の設備接続は自動変更していない。

## 再生成

```bash
python3 scripts/audit_story_connections.py
MPLCONFIGDIR=/tmp/ajg_story_review/mpl python3 scripts/gen_story_review_figures.py
REVISION=next /Users/shigenoburyuto/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node docs/slides/ajg/build_story_revised.mjs
```

builderはArtifact Toolを使用する。`RUNTIME_NODE_MODULES` でランタイムの場所を変更できる。同名の確定済み成果物を上書きしないため、再生成時は新しい `REVISION` を指定する。作業用ファイルと検証receiptは `.build/` に保存する。

配布PPTXの閲覧にはこのランタイムは不要。図の完全再生成には、Git管理外の保存時系列 `docs/data/agc/mm_traces_east_n3pk.npz` が必要で、そのSHAと評価値は `assets/frequency_summary.json` に記録した。投稿用PDFもGit管理外である。保存済みの画像・GIF・説明ノートと、元資料を再計算して得た結果を区別して確認する。

## 確認結果

最終ファイルを再読み込み・全30枚レンダリングして目視確認した。パッケージ、図形配置、指定フォント、10個のネイティブ表の検査は通過し、GIF4本とノート30ページの格納も確認した。PowerPointアプリ上での実際のスライドショー再生は未確認。最終PPTXのSHA256は `760bed32bc12e906a93e2c49d09cb059ca04a39c4e5ccd0e67b6730162cc35ca`。
