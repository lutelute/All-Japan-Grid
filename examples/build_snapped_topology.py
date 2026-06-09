"""Back-compat shim — the snapped topology builder moved to src.powerflow.

The vertex-graph + tolerance-snap builder was promoted to
``src/powerflow/snapped_topology`` (Phase C pipeline promotion) so the
dependency flows src <- scripts/examples. This module re-exports the public
names so existing
``from examples.build_snapped_topology import build_network_snapped`` call
sites (and the CLI) keep working unchanged.
"""

from src.powerflow.snapped_topology import (  # noqa: F401
    DATA_DIR,
    _SubIndex,
    _clean_voltage,
    _get_centroid,
    _get_line_coords,
    _haversine_km,
    _parse_voltage_kv,
    build_network_snapped,
    diagnose,
    main,
)

if __name__ == "__main__":
    main()
