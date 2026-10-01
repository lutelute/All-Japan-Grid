"""README に埋め込む数字を、データから作る(cog から呼ぶ)。

    cog -r README.md        # 数字を書き直す
    cog --check README.md   # 数字が古くなっていないか(CI)

手で書いた数字はモデルを作り直すたびに古くなる(例: 送電線 40,077 本 → 実際は 40,087 本)。
ここではダッシュボード(scripts/build_dashboard_data.py)と同じ関数と、公開している GeoJSON の
件数から数字を作る。リアルタイムの鮮度のように時間で変わる値は入れない(CI が毎時落ちるため)。
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

from scripts.build_dashboard_data import collect_model, count_interventions, read_versions

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"


def _features(name: str) -> int:
    return len(json.loads((DATA / name).read_text(encoding="utf-8"))["features"])


def numbers() -> dict:
    m = collect_model()
    v = read_versions()
    return {
        "lines": _features("lines_all.geojson"),
        "substations": _features("substations.geojson"),
        "subsld_sites": json.loads((DATA / "subsld_pages.json").read_text(encoding="utf-8"))["n_sites"],
        "plants": _features("plants_all.geojson"),
        "nodes": m.get("n_nodes", 0),
        "edges": m.get("n_edges", 0),
        "regions": m.get("n_regions", 10),
        "interventions": count_interventions(),
        "release": v["release"],
        "dataset": v["dataset"],
    }


def scale() -> str:
    n = numbers()
    return (
        f"**規模** — OSM から抽出: 送電線 {n['lines']:,} 本・変電所 {n['substations']:,} か所・"
        f"発電所 {n['plants']:,} か所({n['regions']} 地域)。潮流計算に使う正典モデル(`docs/data/built/`)は "
        f"{n['nodes']:,} ノード・{n['edges']:,} 枝。モデルに加えた仮定は介入台帳に {n['interventions']} 件。"
        f"リリース v{n['release']}・配布データセット v{n['dataset']}。\n"
        f"/ **Scale** — extracted from OSM: {n['lines']:,} lines, {n['substations']:,} substations, "
        f"{n['plants']:,} plants across {n['regions']} regions. The canonical model used for power flow has "
        f"{n['nodes']:,} nodes and {n['edges']:,} branches; {n['interventions']} modelling assumptions are listed in "
        f"the intervention registry. Release v{n['release']}, dataset v{n['dataset']}.\n"
    )


def badges() -> str:
    n = numbers()
    return (
        f"[![release](https://img.shields.io/badge/release-v{n['release']}-2f6fde)](CHANGELOG.md) "
        f"[![dataset](https://img.shields.io/badge/dataset-v{n['dataset']}-1f9d6b)]"
        f"(https://lutelute.github.io/All-Japan-Grid/download.html) "
        f"[![interventions](https://img.shields.io/badge/{quote('介入台帳')}-{n['interventions']}_{quote('件')}-b5561d)]"
        f"(docs/MODEL_INTERVENTIONS.md) "
        "[![data: ODbL](https://img.shields.io/badge/data-ODbL-555)](https://opendatacommons.org/licenses/odbl/) "
        "[![code: MIT](https://img.shields.io/badge/code-MIT-555)](LICENSE)\n"
    )


def subsld_paragraph() -> str:
    return (
        f"{numbers()['subsld_sites']:,} か所の変電所それぞれに、航空写真の上の構内図(OSM の実線形と端子)と、その場で描く\n"
        "単線結線図(母線・回線数・流向・変圧器)を並べます。推定した母線や流向は推定と明記します。\n"
        "制御所ビューでは開閉器をクリックして開け閉めでき、母線の明暗で充電状態がわかります。\n"
    )
