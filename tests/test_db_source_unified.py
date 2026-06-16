"""Phase 2 (DB正化 / 全面改修): 「正(source of truth)を1つに」の不変条件を全地域で固定。

確定事実(実測・2026-06-16):
- committed `data/{region}_*.geojson` は **DB(R層 raw ⟕ C層 enrichments)の忠実な D層 export**
  であり、全10地域で round-trip identity が成立する(`verify_roundtrip` クリーン)。
- 永続 `data/grid.db` から build したネットワークは files から build したものと **完全同値**
  (subs/lines/gens の厳密署名一致, ALL MATCH)。

→ ソースレベルでは正は1つ(DB)に統一済みで、committed files はその検証済みコピー。
この不変条件をテストで固定し、将来 files が DB から乖離(破壊的 in-place 編集や DB drift)
したら即検知する。CI-safe な round-trip は committed files だけで回り、grid.db を要しない
(grid.db は gitignore=ローカル専用なので build 同値は skipif でローカルのみ)。

不変条件: 物理接続=真・計算は検証器・捏造禁止・基底extract不変・committedスコアカード不可触。
"""
import os

import pytest

from src.db.geojson_sync import LAYERS, ingest_geojson, verify_roundtrip
from src.db.grid_db import GridDatabase
from src.powerflow.snapped_topology import DATA_DIR, build_network_snapped
from src.server.built_view import REGIONS_ALL

GRID_DB = os.path.join(DATA_DIR, "grid.db")


def _committed_regions():
    """base 3層 geojson が揃っている地域(committed)。"""
    out = []
    for r in REGIONS_ALL:
        if all(os.path.exists(os.path.join(DATA_DIR, f"{r}_{layer}.geojson"))
               for layer in LAYERS):
            out.append(r)
    return out


COMMITTED = _committed_regions()


@pytest.mark.parametrize("region", COMMITTED)
def test_committed_files_are_faithful_db_export(region):
    """単一の正(CI-safe・全地域): ingest(committed files)→export ≡ committed files。

    `verify_roundtrip` は `_src:` provenance マーカーを無視し effective view で比較する。
    クリーン = その地域の committed geojson は DB の正当な D層 export(=正がDBに一本化)。
    破壊的 in-place 編集で files が DB と乖離したらここで落ちる。
    """
    db = GridDatabase(":memory:")
    for layer in LAYERS:
        ingest_geojson(db, region, layer,
                       os.path.join(DATA_DIR, f"{region}_{layer}.geojson"))
    problems = []
    for layer in LAYERS:
        problems += [f"{layer}: {p}" for p in
                     verify_roundtrip(db, region, layer,
                                      os.path.join(DATA_DIR, f"{region}_{layer}.geojson"))]
    assert not problems, f"{region} の committed files が DB export と不一致: {problems[:5]}"


def _signature(net):
    subs = sorted((s.id, s.name, round(s.voltage_kv, 1)) for s in net.substations)
    lines = sorted((ln.from_substation_id, ln.to_substation_id,
                    round(ln.voltage_kv, 1), round(ln.length_km, 4),
                    int(getattr(ln, "num_parallel", 1)))
                   for ln in net.transmission_lines)
    gens = sorted((g.connected_bus_id, round(g.capacity_mw, 1), g.fuel_type)
                  for g in net.generators)
    return subs, lines, gens


@pytest.mark.skipif(not os.path.exists(GRID_DB),
                    reason="永続 grid.db 不在(gitignore=ローカル専用の drift guard)")
@pytest.mark.parametrize("region", ["okinawa", "hokuriku", "shikoku"])
def test_persistent_db_build_matches_files(region):
    """ローカル drift guard: 永続 grid.db からの build ≡ files からの build(同値)。

    全10地域で ALL MATCH を実測済(2026-06-16)。CIでは grid.db 不在のため skip。
    ローカルで DB を enrich したのに export し忘れる等の drift をここで検知する。
    """
    if region not in COMMITTED:
        pytest.skip(f"{region} not committed")
    db = GridDatabase(GRID_DB)
    net_files = build_network_snapped(region)            # 既定=files
    net_db = build_network_snapped(region, db=db)        # 永続DB
    assert net_db is not None and net_files is not None
    assert _signature(net_db) == _signature(net_files), \
        f"{region}: 永続grid.db build が files build と乖離(DB drift の疑い)"
