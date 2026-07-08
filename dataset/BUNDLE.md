# 配布バンドルの作成と公開

外部の利用者が「DL して回す」ための自己完結 zip を作り、公開するための手順です。
**バンドルの生成はいつでも安全に行えます。公開（Release / Zenodo）は外向き・不可逆な操作
なので、オーナーが内容を確認してから実行してください。**

## 1. バンドルを生成する

```bash
python scripts/make_dataset_bundle.py                 # core（約 13 MB）
python scripts/make_dataset_bundle.py --profile full  # + Ybus 一式（約 24 MB）
```

出力（`dist/bundle/`, これは Git 追跡外）:

```
dist/bundle/
  all-japan-grid-dataset-v<VERSION>-core.zip
  all-japan-grid-dataset-v<VERSION>-core.MANIFEST.sha256
  all-japan-grid-dataset-v<VERSION>-full.zip
  all-japan-grid-dataset-v<VERSION>-full.MANIFEST.sha256
```

`<VERSION>` は `VERSION` ファイル（＝ `datapackage.json` の version）から取ります。

### 中身

| プロファイル | 含まれるもの |
|---|---|
| **core** | `datapackage.json` / 主要文書（README・LICENSE・NOTICE・CITATION・DATA_DICTIONARY・DATA_CATALOG）/ `pyproject.toml`・`requirements.txt` / `src`（UC ソルバ・モデル）/ `config` / `dataset`（チュートリアル）/ `dist/matpower_national`（runpf ケース）/ `docs/data/built`（正典）/ datapackage 記述の GeoJSON・出典 DB・WRI・CGMES index |
| **full** | core ＋ `dist/ybus`（数値 Ybus `.mat/.npz/CSV`）＋ 主要 GeoJSON |

`.DS_Store` / `__pycache__` / `*.pyc` / 実行成果物（`uc_result.*`・`*_res_bus.csv`）は自動除外。
zip 内トップに `all-japan-grid-dataset-v<VERSION>-<profile>/` を付け、展開時に散らかりません。
`MANIFEST.sha256` に全ファイルの SHA256 が入ります（zip 内にも同梱）。

## 2. 自己完結を確認する（任意）

```bash
mkdir -p /tmp/bt && unzip -q dist/bundle/all-japan-grid-dataset-v*-core.zip -d /tmp/bt
cd /tmp/bt/all-japan-grid-dataset-v*-core
pip install -r requirements.txt
python dataset/01_matpower_powerflow/solve_pf.py okinawa    # AC 収束
python dataset/02_uc_from_excel/run_uc.py                   # UC Optimal
```

## 3-A. GitHub Release として公開（オーナー実行）

```bash
# 事前に生成済みであること。VERSION に合わせてタグを付ける。
VERSION=$(cat VERSION)
gh release create "v${VERSION}" \
  dist/bundle/all-japan-grid-dataset-v${VERSION}-core.zip \
  dist/bundle/all-japan-grid-dataset-v${VERSION}-core.MANIFEST.sha256 \
  dist/bundle/all-japan-grid-dataset-v${VERSION}-full.zip \
  dist/bundle/all-japan-grid-dataset-v${VERSION}-full.MANIFEST.sha256 \
  --title "All-Japan-Grid dataset v${VERSION}" \
  --notes "OSM 由来の日本送電網モデル + MATPOWER/UC チュートリアル。SHA256 は同梱 MANIFEST を参照。"
```

既存の Release にアセットだけ足す場合は `gh release upload "v${VERSION}" <file> ...`。

## 3-B. Zenodo で DOI を付けて公開（対外引用向け・オーナー実行）

1. https://zenodo.org/ にログイン → **New upload**。
2. `-full.zip`（または両方）をアップロード。
3. メタデータを `datapackage.json` / `CITATION.cff` から転記：
   - Title: All-Japan-Grid dataset v<VERSION>
   - Authors: CITATION.cff の author
   - License: ODbL-1.0（データ）※ Wikipedia 由来値は CC-BY-SA-4.0（DATA_DICTIONARY 参照）
   - Related identifier: GitHub リポジトリ URL（`isSupplementTo`）
4. **Publish** すると DOI が発行されます（発行後の削除は不可）。
5. 得た DOI を `CITATION.cff` / `README.md` に追記。

> GitHub–Zenodo 連携を有効にしておくと、以後は Release 作成で自動的に Zenodo にアーカイブされ
> DOI が付きます（初回のみ手動連携が必要）。

## 注意

- 公開物にはトポロジ（ODbL）・Wikipedia 由来の容量値（CC-BY-SA）が含まれます。帰属表示を
  保ったまま配布してください（`NOTICE` / `datapackage.json` の licenses）。
- 送配電事業者の非公開値（線路別 rating 等）はバンドルに**含めていません**。追加しないこと。
- 公開は取り消しにくい操作です。タグ・バージョン・ライセンス表記を確認してから実行してください。
