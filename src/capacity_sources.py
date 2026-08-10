"""出典付き容量（D層）を「読む側」へ渡す索引 — 潮流と CIM の共通入口。

## なぜ src に置くか

出典付き容量は `scripts/apply_capacity_sources.py` が D層
`docs/data/plants_*.geojson` に書き込む。一方、潮流と CIM が読むのは R層
`data/<region>_plants.geojson`（OSM 生抽出）なので、2026-08-09 の監査時点で
**出典値がどちらにも届いていなかった**
（`docs/reports/capacity_provenance_reach_2026-08-09.md`
「CIM が読む plants geojson で `capacity_mw_sourced` を持つのは 0 件」）。

R層は書き換えない（層の分離を守る）ので、**読む側がここを引く**。

置き場所が `scripts/` ではなく `src/` なのは、`src/cim/exporter.py` から引くのに
`sys.path` を実行時にいじる必要をなくすため。実行時の sys.path 差し込みは
「便利のための自動探索が試験の隔離を破る」典型で、pytest のモジュール解決を
汚す。`src` は既にパッケージなので普通に import できる。

索引が 1 箇所にあることも要点 — `_DEFAULT_CAP` が 4 箇所に散って
「テストが守っているのは 2 箇所だけ」になった轍を踏まない。
"""
from __future__ import annotations

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D_LAYER_PLANTS = os.path.join(ROOT, "docs", "data", "plants_all.geojson")

SOURCED_FIELDS = ("capacity_mw_sourced", "capacity_source_url",
                  "capacity_source_type", "capacity_source_conf",
                  "capacity_source_note")

_CACHE: dict | None = None


def geo_key(region, lon: float, lat: float) -> str:
    """座標キー。`scripts/apply_capacity_sources.geo_key` と同じ書式（4桁丸め）。"""
    return f"{region}:{lon:.4f},{lat:.4f}"


def sourced_capacity_index(path: str | None = None) -> dict:
    """{座標キー: {capacity_mw_sourced, capacity_source_url, ...}}。

    実測（2026-08-10）: D層に 350 件、R層と **350/350 一致・重複キー 0**。

    ⚠ 出典値 **0 は残す**（大間原発＝運転開始未定 等）。呼ぶ側で
    「0 だから既定値」と落としてはいけない — 0 も出典のある値である。

    path を明示した場合はキャッシュを使わない（テストが別ファイルを渡せるように）。
    """
    global _CACHE
    if path is None and _CACHE is not None:
        return _CACHE
    idx: dict = {}
    p = path or D_LAYER_PLANTS
    if os.path.exists(p):
        with open(p, encoding="utf-8") as fh:
            for ft in json.load(fh).get("features", []):
                pr = ft.get("properties") or {}
                g = ft.get("geometry") or {}
                if "capacity_mw_sourced" not in pr or g.get("type") != "Point":
                    continue
                idx[geo_key(pr.get("_region"), g["coordinates"][0],
                            g["coordinates"][1])] = {
                    f: pr[f] for f in SOURCED_FIELDS if f in pr}
    # **空はキャッシュしない。** 空を焼き付けると、一時的にファイルが見えない状況
    # （テストが `os.path.exists` を差し替えている最中など）で引かれた 0 件が
    # プロセス全体へ漏れる。2026-08-10 に実際にこれで 2 本落ちた。
    if path is None and idx:
        _CACHE = idx
    return idx


def reset_cache() -> None:
    """テスト用。プロセス内キャッシュを捨てる。"""
    global _CACHE
    _CACHE = None
