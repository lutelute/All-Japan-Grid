# All-Japan-Grid — データセットの入口とチュートリアル

日本の送電網モデル (OpenStreetMap 由来・外部データで検証) を **DL して回す**ための入口です。
配布物のダウンロード方法と、代表的な 2 つの回し方（MATPOWER 潮流計算 / Excel で発電機を
設定して UC）を、そのまま動くスクリプト付きで用意しています。

---

## 1. まず何をダウンロードするか

配布は 1 つの zip バンドルにまとまっています（`datapackage.json` 準拠 + チュートリアル同梱）。

| プロファイル | 中身 | zip サイズ |
|---|---|---|
| **core** | MATPOWER 潮流ケース・正典 built モデル・GeoJSON・出典DB・チュートリアル・`src`/`config`（UC ソルバ込み） | 約 13 MB |
| **full** | core ＋ 数値 Ybus 一式（`.mat/.npz`）・主要 GeoJSON 全部 | 約 24 MB |

- **公開済みバンドル**: GitHub Releases → https://github.com/lutelute/All-Japan-Grid/releases
- **自分で作る**: リポジトリのルートで
  ```bash
  python scripts/make_dataset_bundle.py --profile core   # dist/bundle/ に出力
  ```
  作り方・公開手順は [`BUNDLE.md`](BUNDLE.md)。

DL 後は zip を展開し、その中で下記スクリプトを実行できます（バンドルは**自己完結**：
`src`・`config`・データを同梱しているので、リポジトリ全体を clone しなくても回ります）。

### 依存パッケージ

```bash
pip install -r requirements.txt          # pandapower, pulp, openpyxl, scipy, matplotlib ほか
# MATLAB 版の潮流を使う場合のみ MATPOWER (https://matpower.org/) を別途導入
```

---

## 2. 回し方その1 — MATPOWER で潮流計算 → [`01_matpower_powerflow/`](01_matpower_powerflow/)

配布ケース `dist/matpower_national/<island>.mat`（非同期 4 島）を読み、AC 潮流（Newton-Raphson）を
解きます。MATLAB 版・Python 版の両方を用意。

```bash
# Python (MATLAB 不要, pandapower)
python 01_matpower_powerflow/solve_pf.py okinawa

# MATLAB (MATPOWER)  ※先に addpath で MATPOWER を通す
matlab -batch "addpath(genpath('/path/to/matpower8.1')); solve_pf('okinawa')"
```

沖縄（最小・単一成分）は綺麗に収束します（損失 ≈ 1.4 %）。詳細と注意は
[`01_matpower_powerflow/README.md`](01_matpower_powerflow/README.md)。

---

## 3. 回し方その2 — Excel で発電機設定 → UC → [`02_uc_from_excel/`](02_uc_from_excel/)

発電機（定格・燃料・限界費用・起動費・最小 up/down 時間）と 24 時間需要を **Excel** で編集し、
24 時間の最小コスト起動停止計画（ユニットコミットメント）を MILP で解きます。

```bash
python 02_uc_from_excel/make_template.py       # 実フリートから generators_template.xlsx を生成
#   → Excel を開いて発電機・需要を編集
python 02_uc_from_excel/run_uc.py              # 解いて uc_result.xlsx / uc_result.png を出力
```

出力は発電機×時刻のディスパッチ表（Excel）と、燃料別の積み上げ発電量グラフ（PNG）。
詳細は [`02_uc_from_excel/README.md`](02_uc_from_excel/README.md)。

---

## 4. ライセンスと出典（引用時は必ず確認）

| 対象 | ライセンス |
|---|---|
| 送電網トポロジ（OSM 由来） | **ODbL-1.0**（© OpenStreetMap contributors） |
| 発電容量の出典 DB（Wikipedia 由来値を含む） | **CC-BY-SA-4.0** |
| WRI 全球発電所 DB（クロスチェック） | **CC-BY-4.0** |
| コード | リポジトリの `LICENSE` を参照 |

引用は `CITATION.cff` / `datapackage.json` を参照。出典の詳細は `DATA_DICTIONARY.md`。

---

## 5. データの限界（誠実な注意）

このデータセットは**モデル**であり、実系統そのものではありません。使う前に押さえてください。

- **多成分島は MATLAB 版と Python 版で挙動が異なります。** 沖縄以外の島は複数の弱連結成分に
  分かれ各成分に 1 slack を持ちます。**MATLAB（MATPOWER）は正しく解けます**（実機確認: 北海道は
  AC 収束・損失 +3.5%）が、**Python（pandapower `from_mpc`）は複数 slack を正しく変換できず**
  損失が負になる等の不整合が出ます（配布 `.mat` 自体は健全）。Python で大規模島を扱うなら
  MATLAB 版か、**UC → 潮流連成**を使ってください。「収束＝正しく解けた」ではない点も引き続き留意。
- **UC テンプレートのコスト・起動費・最小出力（Pmin）は例題用の一般既定値**（`config/uc_config.yaml`
  の typical estimates）で、特定発電所の実測値ではありません。実データがあれば Excel 上で
  上書きしてください。発電所名・燃料・定格（Pmax）は OSM 由来の実在フリートです。
- 変圧器・線路定数は電圧階級の代表値中心（銘板適用は一部）。詳細は `dist/ybus/README.md`。

失敗事例・既知の限界・国際ベンチマークは `docs/reports/` に整理されています。
