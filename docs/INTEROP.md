# Interop — 日本系統を自分のツールに1行で / Import into your own tools

[VISION.md](VISION.md) **Pillar 2（規格と相互運用）** の実体。本プロジェクトが CIM/CGMES と
MATPOWER という**標準交換形式**を公開するのは、誰もがリポジトリ内部に触れずに「日本の系統の
1地域」を標準ソルバへ取り込めるようにするため。本書はその**取り込みレシピ**と検証状況をまとめる。

> Publishing standards-based exchange formats means anyone can pull a region of
> Japan's grid into a standard solver in ~1 line. Runnable demo:
> [`examples/import_quickstart.py`](../examples/import_quickstart.py).

```bash
PYTHONPATH=. python3 examples/import_quickstart.py          # okinawa
PYTHONPATH=. python3 examples/import_quickstart.py kansai
```

---

## 取り込みマトリクス / Import matrix

| ツール | 入力形式 | 状態 | レシピ |
|---|---|---|---|
| **pandapower** | CIM/CGMES L2 | ✅ 自動テスト済 | `from_cim(file_list=[…EQ,TP,SSH,SV,GL,BD…])` |
| **pandapower** | MATPOWER `.mat` | ✅ 自動テスト済 | `from_mpc("okinawa.mat")` |
| **MATLAB/Octave MATPOWER** | MATPOWER `.mat` | 📄 文書化（要 MATPOWER） | `mpc = loadcase('okinawa.mat'); runpf(mpc)` |
| **PyPSA** | PYPOWER ブリッジ | 📄 文書化（要 `pip install pypsa`） | 下記 |
| **PSS/E, PowerFactory** | CGMES インポート | 📄 各ツールの CGMES 取込機能 | 各ベンダ手順 |

✅ = `examples/import_quickstart.py` + `tests/test_import_quickstart.py` で実ロード＆潮流を検証。
📄 = レシピは正しいが追加ツール依存のため本リポジトリの CI では走らせていない（自己責任で利用）。

---

## 1. pandapower ← CIM / CGMES Level 2 ★推奨

CGMES プロファイル一式（`dist/cim_level2/` に追跡済み、Release にも同梱）＋境界セットを渡す:

```python
from pandapower.converter.cim.cim2pp.from_cim import from_cim
net = from_cim(file_list=[
    "dist/cim_level2/okinawa_L2_EQ.xml",
    "dist/cim_level2/okinawa_L2_TP.xml",
    "dist/cim_level2/okinawa_L2_SSH.xml",
    "dist/cim_level2/okinawa_L2_SV.xml",
    "dist/cim_level2/okinawa_L2_GL.xml",
    "dist/cim_level2/AllJapan_EQ_BD.xml",   # boundary set（共通）
    "dist/cim_level2/AllJapan_TP_BD.xml",
])
import pandapower as pp; pp.runpp(net)
```

実測（okinawa）: 81 bus / 57 line / 25 trafo / 17 gen、AC 収束 vmin≈0.94 pu。
プロファイルは `ajgrid cim --regions okinawa` で再生成可能。8/10 地域が native に潮流収束
（[VISION.md](VISION.md) §1）。規格対応の詳細は [CIM_MAPPING.md](CIM_MAPPING.md)。

## 2. pandapower ← MATPOWER `.mat`

```python
from pandapower.converter.matpower.from_mpc import from_mpc
net = from_mpc("okinawa.mat")
```

`.mat` 全地域分は GitHub Releases（`output/` はビルド生成物のため非追跡）。手元生成は
[`examples/export_and_solve_matpower.py`](../examples/export_and_solve_matpower.py)。
エクスポート仕様は [MATPOWER_EXPORT_GUIDE.md](MATPOWER_EXPORT_GUIDE.md)。

## 3. MATLAB / Octave MATPOWER

```matlab
mpc     = loadcase('okinawa.mat');   % BUS/BRANCH/GEN/GENCOST
results = runpf(mpc);                 % or runopf(mpc) — GENCOST 付き
```

## 4. PyPSA（PYPOWER ブリッジ経由）

PyPSA は CGMES を直接は読まないため、pandapower 経由で PYPOWER ケースに変換して渡す:

```python
import pypsa
from pandapower.converter.pypower.to_ppc import to_ppc
# net は §1 か §2 で読み込んだ pandapower ネットワーク
n = pypsa.Network(); n.import_from_pypower_ppc(to_ppc(net))
```

> ※ PyPSA は任意依存のため本リポジトリの CI では検証していない。API はバージョンで変わりうる。

## 5. PSS/E・PowerFactory 等

これらは CGMES インポート機能を持つので、§1 のプロファイル一式（+境界）を各ツールの
CGMES 取込手順で読み込む。決定的 mRID・boundary set 整備済み（[CIM_MAPPING.md](CIM_MAPPING.md)）。

---

## 正直な限界 / Honest caveat

本データは **地理トポロジ + 合成電気パラメータ**（電圧クラス別の文献標準値）。
**相対傾向・merit order は有意**だが、**個別設備の運用可否判断には使えない**
（[VISION.md](VISION.md) §2、[README](../README.md) Disclaimer）。権威ある電気値での
置換・検証は Pillar 3 のフロンティア（[ENGAGEMENT.md](ENGAGEMENT.md)）。取り込んだモデルを
運用判断に使う前に、この線引きを必ず読むこと。
