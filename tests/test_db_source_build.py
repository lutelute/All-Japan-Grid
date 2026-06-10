"""DB-direct topology build (VISION step 5): grid.db as the only source.

`build_network_snapped(db=...)` composes the three layers in memory from
the unified database (raw + enrichments effective view) instead of
reading data/*.geojson. This test ingests the real okinawa files into an
in-memory GridDatabase and asserts the DB-built network is IDENTICAL to
the file-built one — the whole power-flow pipeline therefore reproduces
from `ajgrid db ingest` alone.
"""

import os

import pytest

pytest.importorskip("pandapower")

from src.db.geojson_sync import LAYERS, ingest_geojson  # noqa: E402
from src.db.grid_db import GridDatabase  # noqa: E402
from src.powerflow.snapped_topology import DATA_DIR, build_network_snapped  # noqa: E402


@pytest.fixture(scope="module")
def okinawa_db():
    db = GridDatabase(":memory:")
    for layer in LAYERS:
        path = os.path.join(DATA_DIR, f"okinawa_{layer}.geojson")
        ingest_geojson(db, "okinawa", layer, path)
    return db


def _signature(net):
    subs = sorted((s.id, s.name, round(s.voltage_kv, 1)) for s in net.substations)
    lines = sorted((ln.from_substation_id, ln.to_substation_id,
                    round(ln.voltage_kv, 1), round(ln.length_km, 4),
                    int(getattr(ln, "num_parallel", 1)))
                   for ln in net.transmission_lines)
    gens = sorted((g.connected_bus_id, round(g.capacity_mw, 1), g.fuel_type)
                  for g in net.generators)
    return subs, lines, gens


def test_db_build_identical_to_file_build(okinawa_db):
    net_files = build_network_snapped("okinawa")
    net_db = build_network_snapped("okinawa", db=okinawa_db)
    assert net_db is not None
    assert _signature(net_db) == _signature(net_files)


def test_db_path_string_accepted(tmp_path, okinawa_db):
    # a path string is resolved to a GridDatabase internally
    dbfile = tmp_path / "mini.db"
    db2 = GridDatabase(str(dbfile))
    for layer in LAYERS:
        ingest_geojson(db2, "okinawa", layer,
                       os.path.join(DATA_DIR, f"okinawa_{layer}.geojson"))
    net = build_network_snapped("okinawa", db=str(dbfile))
    assert net is not None and len(net.substations) > 50
