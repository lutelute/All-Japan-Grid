"""Rebuild the live map's national route tiers from the current model (D7).

    PYTHONPATH=. python scripts/gen_route_tiers.py

docs/data/powerflow/routes_{500,275,154,110,77,66}kv.geojson — the
line layer powerflow.js draws at the national zoom — were legacy
artifacts with no surviving generator (their lineage predates the
snapped builder; the new bus layer contacted them at only 66.8 %).
This recipe regenerates every tier from build_network_snapped (the
OSM-faithful model of ledger 85): real route paths, kv-untagged lines
fall into the 66 tier (they solve as 66 kV — ledger 89), property
schema kept (kv / name / region / loading / xfmr / npts_orig; loading
stays 0.0 = the viewer's "unmatched" state, as before).
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OUT_DIR = "docs/data/powerflow"
TIERS = [500, 275, 154, 110, 77, 66]
REGIONS = ["hokkaido", "tohoku", "tokyo", "chubu", "hokuriku",
           "kansai", "chugoku", "shikoku", "kyushu", "okinawa"]


def tier_of(kv: float) -> int:
    for t in TIERS:
        if kv >= t:
            return t
    return 66          # untagged lines solve as 66 kV (ledger 89)


def main() -> int:
    from src.powerflow.snapped_topology import build_network_snapped

    feats = {t: [] for t in TIERS}
    for region in REGIONS:
        net = build_network_snapped(region)
        if net is None:
            print(f"warning: no data for {region}")
            continue
        node = {s.id: (s.latitude, s.longitude) for s in net.substations}
        for ln in net.transmission_lines:
            if "_xfmr_" in ln.id or not ln.coordinates:
                continue
            if len(ln.coordinates) < 2:
                continue
            t = tier_of(float(ln.voltage_kv or 0))
            # endpoint snap to the node coordinates (the PR #16 / ledger 82
            # convention): the raw OSM path ends at the way's last vertex,
            # the bus dot sits at the substation representative point —
            # joining them is what makes dot/line contact mean connectivity
            cs = [[lon, lat] for (lat, lon) in ln.coordinates]
            fc = node.get(ln.from_substation_id)
            tc = node.get(ln.to_substation_id)
            if fc and tc:
                cs = [[fc[1], fc[0]]] + cs[1:-1] + [[tc[1], tc[0]]]
            feats[t].append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": cs,
                },
                "properties": {
                    "kv": t,
                    "name": str(ln.name)[:60],
                    "region": region,
                    "loading": 0.0,
                    "xfmr": False,
                    "npts_orig": len(ln.coordinates),
                },
            })
    for t in TIERS:
        path = os.path.join(OUT_DIR, f"routes_{t}kv.geojson")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"type": "FeatureCollection", "features": feats[t]}, f,
                      ensure_ascii=False)
        print(f"  routes_{t}kv: {len(feats[t]):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
