"""Legacy (nearest-substation) topology builder + GeoJSON feature parsers.

``build_network_from_geojson`` assembles a :class:`GridNetwork` by matching
each transmission-line endpoint and each plant to the nearest substation
within a distance threshold. The vertex-graph ``build_network_snapped``
(examples/build_snapped_topology) supersedes it for connectivity fidelity,
but the legacy builder is still the default ``topology="legacy"`` path for
several scripts.

Promoted from ``examples/run_powerflow_all`` (Phase C pipeline promotion)
so the dependency flows src <- scripts/examples; the example re-exports
these names for back-compat. ``DATA_DIR`` becomes a ``data_dir`` argument
defaulting to the repository ``data/`` directory.
"""

from __future__ import annotations

import json
import os

from src.model.generator import Generator
from src.model.grid_network import GridNetwork
from src.model.substation import Substation
from src.model.transmission_line import TransmissionLine
from src.regions import REGION_FREQUENCY_HZ
from src.utils.geo_utils import haversine_distance
from src.utils.voltage import parse_voltage_kv

DEFAULT_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")

# Default plant capacity (MW) by fuel when capacity_mw is missing.
_DEFAULT_CAPACITY_MW = {
    "nuclear": 900, "coal": 600, "gas": 400, "oil": 200,
    "oil;gas": 300, "gas;oil": 300, "coal;gas": 400, "gas;coal": 400,
    "coal;gas;oil": 400,
    "hydro": 30, "wind": 20, "solar": 10, "geothermal": 30,
    "biomass": 20, "waste": 5,
}
_DEFAULT_CAPACITY_FALLBACK = 10.0

# (lat, lon) order, matching this module's callers.
_haversine_km = haversine_distance


def _get_centroid(feature):
    geom = feature["geometry"]
    if geom is None:
        return None, None
    gtype = geom["type"]
    if gtype == "Point":
        return geom["coordinates"][1], geom["coordinates"][0]
    elif gtype == "Polygon":
        coords = geom["coordinates"][0]
    elif gtype == "MultiPolygon":
        coords = geom["coordinates"][0][0]
    else:
        return None, None
    lat = sum(c[1] for c in coords) / len(coords)
    lon = sum(c[0] for c in coords) / len(coords)
    return lat, lon


def _parse_voltage_kv(voltage_raw):
    """Parse OSM voltage string (in volts) to kV; 0.0 if none."""
    return parse_voltage_kv(voltage_raw) or 0.0


def _get_line_coords(feature):
    """Extract coordinates from a LineString or MultiLineString."""
    geom = feature.get("geometry")
    if not geom:
        return []
    gtype = geom["type"]
    if gtype == "LineString":
        return [(c[1], c[0]) for c in geom["coordinates"]]
    elif gtype == "MultiLineString":
        return [(c[1], c[0]) for c in geom["coordinates"][0]]
    return []


def _find_nearest_sub(lat, lon, sub_coords, max_km):
    """Find nearest substation within max_km."""
    best_id = None
    best_dist = float("inf")
    for slat, slon, sid in sub_coords:
        if abs(slat - lat) > 0.5:  # quick filter
            continue
        d = _haversine_km(lat, lon, slat, slon)
        if d < best_dist:
            best_dist = d
            best_id = sid
    return best_id if best_dist <= max_km else None


def build_network_from_geojson(region, data_dir=None):
    """Build a GridNetwork from OSM GeoJSON files for a region."""
    data_dir = data_dir or DEFAULT_DATA_DIR
    freq = REGION_FREQUENCY_HZ.get(region, 50)
    network = GridNetwork(region=region, frequency_hz=freq)

    # Load substations
    sub_path = os.path.join(data_dir, f"{region}_substations.geojson")
    if not os.path.exists(sub_path):
        return None
    with open(sub_path, encoding="utf-8") as f:
        subs_data = json.load(f)

    sub_id_map = {}  # feature index → substation id
    for i, feat in enumerate(subs_data["features"]):
        lat, lon = _get_centroid(feat)
        if lat is None:
            continue
        props = feat["properties"]
        name = props.get("name") or f"{region}_sub_{i}"
        voltage_kv = _parse_voltage_kv(props.get("voltage"))
        sub_id = f"{region}_sub_{i}"
        sub_id_map[i] = sub_id

        sub = Substation(
            id=sub_id,
            name=name,
            region=region,
            latitude=lat,
            longitude=lon,
            voltage_kv=max(voltage_kv, 0),
        )
        network.add_substation(sub)

    # Build spatial index of substations for endpoint matching
    sub_coords = []
    for sub in network.substations:
        sub_coords.append((sub.latitude, sub.longitude, sub.id))

    # Load lines and match endpoints to nearest substations
    lines_path = os.path.join(data_dir, f"{region}_lines.geojson")
    if os.path.exists(lines_path):
        with open(lines_path, encoding="utf-8") as f:
            lines_data = json.load(f)

        for i, feat in enumerate(lines_data["features"]):
            props = feat["properties"]
            name = props.get("name") or props.get("_display_name") or f"{region}_line_{i}"
            voltage_kv = _parse_voltage_kv(props.get("voltage"))

            coords = _get_line_coords(feat)
            if len(coords) < 2:
                continue

            start_lat, start_lon = coords[0]
            end_lat, end_lon = coords[-1]

            from_sub_id = _find_nearest_sub(start_lat, start_lon, sub_coords, 50.0)
            to_sub_id = _find_nearest_sub(end_lat, end_lon, sub_coords, 50.0)

            if not from_sub_id or not to_sub_id or from_sub_id == to_sub_id:
                continue

            length_km = 0.0
            for j in range(1, len(coords)):
                length_km += _haversine_km(coords[j-1][0], coords[j-1][1],
                                            coords[j][0], coords[j][1])

            if length_km <= 0:
                continue

            line_id = f"{region}_line_{i}"
            line = TransmissionLine(
                id=line_id,
                name=name,
                from_substation_id=from_sub_id,
                to_substation_id=to_sub_id,
                voltage_kv=max(voltage_kv, 0),
                length_km=length_km,
                region=region,
            )
            try:
                network.add_transmission_line(line)
            except ValueError:
                pass  # duplicate ID, skip

    # Load generators from plants GeoJSON
    plants_path = os.path.join(data_dir, f"{region}_plants.geojson")
    if os.path.exists(plants_path):
        with open(plants_path, encoding="utf-8") as f:
            plants_data = json.load(f)

        gen_count = 0
        for i, feat in enumerate(plants_data["features"]):
            lat, lon = _get_centroid(feat)
            if lat is None:
                continue
            props = feat["properties"]

            # Extract capacity
            capacity_mw = None
            raw_cap = props.get("capacity_mw")
            if raw_cap is not None:
                try:
                    capacity_mw = float(raw_cap)
                except (ValueError, TypeError):
                    pass

            fuel = props.get("plant:source") or props.get("fuel_type") or "unknown"
            # Clean fuel string (some have URLs)
            if fuel.startswith("http"):
                fuel = "unknown"

            if capacity_mw is None or capacity_mw <= 0:
                capacity_mw = _DEFAULT_CAPACITY_MW.get(fuel, _DEFAULT_CAPACITY_FALLBACK)

            # Match to nearest substation bus (< 5km)
            nearest_sub = _find_nearest_sub(lat, lon, sub_coords, 5.0)
            if not nearest_sub:
                # Relax to 20km for large plants
                if capacity_mw >= 100:
                    nearest_sub = _find_nearest_sub(lat, lon, sub_coords, 20.0)
                if not nearest_sub:
                    continue

            name = props.get("name") or props.get("_display_name") or f"{region}_plant_{i}"
            gen_id = f"{region}_gen_{i}"

            gen = Generator(
                id=gen_id,
                name=name,
                capacity_mw=capacity_mw,
                fuel_type=fuel,
                connected_bus_id=nearest_sub,
                region=region,
                latitude=lat,
                longitude=lon,
            )
            network.add_generator(gen)
            gen_count += 1

    return network
