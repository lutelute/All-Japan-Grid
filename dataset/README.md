# All-Japan-Grid — データセットの入口とチュートリアル

日本の送電網モデル (OpenStreetMap 由来・外部データで検証) を **DL して回す**ための入口です。
配布物のダウンロード方法と、代表的な 2 つの回し方（MATPOWER 潮流計算 / Excel で発電機を
設定して UC）を、そのまま動くスクリプト付きで用意しています。

> 🌐 オンライン版のダウンロードページ: **https://lutelute.github.io/All-Japan-Grid/download.html**

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

**4 島とも AC で収束します**（MATPOWER・pandapower とも。損失は 1.9〜3.0 %）。west は江田島の
66kV の木 1 本（6 バス）を親バスへ畳んであります。詳細と注意は
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

## 4. 回し方その3 — 感度行列で高速スクリーニング → [`03_sensitivity_screening/`](03_sensitivity_screening/)

配布物 `dist/sensitivity/` の **PTDF / LODF** を読み、反復解法を使わずに行列の掛け算だけで
潮流・N-1・地点別の混雑を評価します。

```bash
python 03_sensitivity_screening/screen.py            # 沖縄（最小・数秒）
python 03_sensitivity_screening/screen.py west       # 主成分 7,087 バス
```

要点は「全地点を一度に」評価できること。西日本 7,087 地点の混雑感度が **0.5 秒**で出ます
（同じ答えを潮流の解き直しで得ると単純計算で 3.4 日）。行列本体は容量が大きいため git に
入っておらず、無ければスクリプトが生成します（west で約 5 秒）。

直流近似のスクリーニングであり確定値ではありません。詳細と限界は
[`03_sensitivity_screening/README.md`](03_sensitivity_screening/README.md)。

---

## 5. ライセンスと出典（引用時は必ず確認）

| 対象 | ライセンス |
|---|---|
| 送電網トポロジ（OSM 由来） | **ODbL-1.0**（© OpenStreetMap contributors） |
| 発電容量の出典 DB（Wikipedia 由来値を含む） | **CC-BY-SA-4.0** |
| WRI 全球発電所 DB（クロスチェック） | **CC-BY-4.0** |
| コード | リポジトリの `LICENSE` を参照 |

引用は `CITATION.cff` / `datapackage.json` を参照。出典の詳細は `DATA_DICTIONARY.md`。

---

## 6. データの限界（誠実な注意）

このデータセットは**モデル**であり、実系統そのものではありません。使う前に押さえてください。

- **AC 潮流が収束する＝正しく解けた、ではありません。** 配布ケースは fy2023 既定断面の
  スナップショットで、需要はエリア計を変電所へ合成配賦したもの、線路定数は電圧階級の代表値です。
  本系統から切れた断片の需要は合成の slack が賄っています。west は解ける形にするため江田島の
  66kV の木 1 本を畳んであります（`dist/matpower_national/meta.json` の `reduction`）。
  線ごとの潮流・電圧は個別に引用せず、地域ごとの集計や傾向に使ってください。
- **UC テンプレートのコスト・起動費・最小出力（Pmin）は例題用の一般既定値**（`config/uc_config.yaml`
  の typical estimates）で、特定発電所の実測値ではありません。実データがあれば Excel 上で
  上書きしてください。発電所名・燃料・定格（Pmax）は OSM 由来の実在フリートです。
- 変圧器・線路定数は電圧階級の代表値中心（銘板適用は一部）。詳細は `dist/ybus/README.md`。
- **線路の熱容量は理論値**（`√3·V·I`）で実運用容量ではありません。本モデルでは基準潮流が
  既にこれを超える枝があり（66kV 層に集中）、感度行列による接続可能量は絶対値ではなく
  **地点間の相対比較**として読んでください。詳細は `dist/sensitivity/README.md`。

失敗事例・既知の限界・国際ベンチマークは `docs/reports/` に整理されています。
