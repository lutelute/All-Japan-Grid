# Zenodo DOI 発行手順（初回 = v1.6.0 に合わせる）

策定 2026-07-10。資産ロードマップ Phase 2（docs/ROADMAP_ASSET.md）の「引用される作法」の一部。
リポジトリ側の準備（`.zenodo.json`・`CITATION.cff`）は完了済み。**残るのはオーナーの
Zenodo ログイン操作のみ**（外部公開操作のため機械実行しない）。

## なぜ DOI か
- v1.5.0 以降、データセットは GitHub Release で配布されているが**引用可能な永続識別子がない**
- Zenodo は concept DOI（全バージョン共通）+ version DOI（版ごと）を無料発行し、
  GitHub Release と自動連動する
- データ論文（Nature Scientific Data 級）投稿時に DOI は事実上必須

## 手順（オーナー操作・所要 ~10分）

1. https://zenodo.org に **GitHub アカウントでログイン**（Log in → GitHub）
2. 右上メニュー → **GitHub**（https://zenodo.org/account/settings/github/）
3. リポジトリ一覧から **lutelute/All-Japan-Grid** のトグルを **ON**
   - 一覧に出ない場合は「Sync now」を押す
4. **その後に** GitHub Release を発行する（= v1.6.0 が最初の DOI 対象になる）
   - トグル ON 以前の Release（v1.5.0 以前）には遡って DOI は付かない
5. Release 発行から数分で Zenodo にレコードが生成される
   - https://zenodo.org/account/settings/github/ の該当リポジトリ行に DOI バッジが出る
6. **concept DOI**（例 10.5281/zenodo.XXXXXXX、全バージョン共通）と
   **version DOI** を控える

## DOI 取得後にリポジトリへ反映すること（機械実行可・オーナーが DOI を貼れば実施）

- [ ] `CITATION.cff` に `doi: 10.5281/zenodo.XXXXXXX`（concept DOI）を追記
- [ ] `README.md` に DOI バッジ
  `[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.XXXXXXX.svg)](https://doi.org/10.5281/zenodo.XXXXXXX)`
- [ ] `docs/download.html` の引用セクションに DOI を追記
- [ ] `datapackage.json` の `id` に DOI を設定

## メタデータの正本
- `.zenodo.json`（リポジトリルート）— Zenodo はこれを優先して読む。
  タイトル・著者・ライセンス（データ=ODbL-1.0 / コード=MIT は description に明記）・
  キーワードは `CITATION.cff` と整合させてある。変更時は両方を同時に更新すること。
