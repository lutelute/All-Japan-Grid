"""GeoJSON -> CIM/CGMES exporter (EQ + GL profiles) for one region.

Maps the All-Japan-Grid raw GeoJSON (``data/<region>_{substations,lines,
plants}.geojson``) onto IEC 61970 CIM classes and writes two CGMES RDF/XML
files per region:

  * ``<region>_EQ.xml`` — Equipment profile (topology / electrical objects)
  * ``<region>_GL.xml`` — Geographical Location profile (coordinates)

This is the **Level-1** export: every feature becomes the correct CIM class
with its nominal voltage (``BaseVoltage``), regional container and geographic
location. Line terminals are given independent ``ConnectivityNode``s (a valid
equipment catalogue); shared-node connectivity for power-flow studies is the
**Level-2** export built from the snapped topology (``GridNetwork``).
"""

from __future__ import annotations

import json
import math
import os
from typing import Dict, List, Optional, Tuple

from .core import PROFILE_EQ, PROFILE_GL, RdfWriter, base_voltage_mrid, mrid

# English region names for IdentifiedObject.name of SubGeographicalRegion.
REGION_NAME: Dict[str, str] = {
    "hokkaido": "Hokkaido",
    "tohoku": "Tohoku",
    "tokyo": "Tokyo",
    "chubu": "Chubu",
    "hokuriku": "Hokuriku",
    "kansai": "Kansai",
    "chugoku": "Chugoku",
    "shikoku": "Shikoku",
    "kyushu": "Kyushu",
    "okinawa": "Okinawa",
}

# fuel_type -> CIM GeneratingUnit subclass (CGMES 2.4.15 / CIM16).
# CGMES 2.4 has no Geothermal/Battery generating-unit subclasses, so those
# fall back to ThermalGeneratingUnit / GeneratingUnit respectively.
_FUEL_TO_CIM: Dict[str, str] = {
    "coal": "ThermalGeneratingUnit",
    "lng": "ThermalGeneratingUnit",
    "gas": "ThermalGeneratingUnit",
    "oil": "ThermalGeneratingUnit",
    "biomass": "ThermalGeneratingUnit",
    "waste": "ThermalGeneratingUnit",
    "geothermal": "ThermalGeneratingUnit",
    "nuclear": "NuclearGeneratingUnit",
    "hydro": "HydroGeneratingUnit",
    "pumped_hydro": "HydroGeneratingUnit",
    "wind": "WindGeneratingUnit",
    "solar": "SolarGeneratingUnit",
    "battery": "GeneratingUnit",
    "mixed": "GeneratingUnit",
    "unknown": "GeneratingUnit",
}

# Generating-unit subclasses backed by a rotating SynchronousMachine.
_ROTATING = {"ThermalGeneratingUnit", "HydroGeneratingUnit", "NuclearGeneratingUnit"}


def parse_voltage_kv(
    raw: object,
) -> Tuple[Optional[float], List[float], Optional[str]]:
    """Parse an OSM ``voltage`` value to CIM-ready kV.

    Implements the ``voltage`` transform rules of ``config/data_schema.yaml``:
    splits on ``;``/``,``; a leading ``dc`` marks DC; a ``kv`` suffix means the
    number is already in kV, otherwise it is volts and divided by 1000; tokens
    that resolve to <= 0 kV are dropped.

    Args:
        raw: Raw OSM voltage (e.g. ``"154000;66000"``, ``"dc1500"``, ``"154kv"``).

    Returns:
        ``(max_kv, all_kv_descending, current_type)``. All-``None`` /empty list
        when no positive voltage could be parsed.
    """
    if raw is None:
        return None, [], None
    s = str(raw).strip()
    if not s or s in ("-1", "-1.0", "None", "null"):
        return None, [], None
    current = "ac"
    values: List[float] = []
    for token in s.replace(",", ";").split(";"):
        t = token.strip().lower()
        if not t:
            continue
        if t.startswith("dc"):
            current = "dc"
            t = t[2:]
        in_kv = False
        if t.endswith("kv"):
            in_kv = True
            t = t[:-2]
        elif t.endswith("v"):
            t = t[:-1]
        t = t.strip()
        try:
            num = float(t)
        except ValueError:
            continue
        kv = num if in_kv else num / 1000.0
        if kv > 0:
            values.append(kv)
    if not values:
        return None, [], None
    unique_desc = sorted(set(values), reverse=True)
    return unique_desc[0], unique_desc, current


def _representative_point(geom: Optional[dict]) -> Optional[Tuple[float, float]]:
    """Return a single ``(lon, lat)`` representative point for any geometry."""
    if not geom:
        return None
    gtype = geom.get("type")
    coords = geom.get("coordinates")
    if not coords:
        return None
    try:
        if gtype == "Point":
            return (float(coords[0]), float(coords[1]))
        if gtype == "LineString":
            return (float(coords[0][0]), float(coords[0][1]))
        if gtype == "Polygon":
            return (float(coords[0][0][0]), float(coords[0][0][1]))
        if gtype == "MultiPolygon":
            return (float(coords[0][0][0][0]), float(coords[0][0][0][1]))
    except (IndexError, TypeError, ValueError):
        return None
    return None


def _line_coords(geom: Optional[dict]) -> List[Tuple[float, float]]:
    """Return the ordered ``(lon, lat)`` vertices of a LineString geometry."""
    if not geom or geom.get("type") != "LineString":
        return []
    out: List[Tuple[float, float]] = []
    for p in geom.get("coordinates", []):
        try:
            out.append((float(p[0]), float(p[1])))
        except (IndexError, TypeError, ValueError):
            continue
    return out


def _haversine_m(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    """Great-circle distance in metres between two ``(lon, lat)`` points."""
    radius = 6371000.0
    lon1, lat1 = a
    lon2, lat2 = b
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(h))


def _polyline_length_m(coords: List[Tuple[float, float]]) -> float:
    """Cumulative great-circle length (metres) of a polyline."""
    if len(coords) < 2:
        return 0.0
    return sum(_haversine_m(coords[i], coords[i + 1]) for i in range(len(coords) - 1))


class CimExporter:
    """Accumulates CIM EQ + GL objects for a single region."""

    def __init__(self, region: str) -> None:
        """Create empty EQ/GL writers for ``region`` (call :meth:`header` next)."""
        self.region = region
        self.eq = RdfWriter(PROFILE_EQ, mrid("model", "eq", region))
        self.gl = RdfWriter(PROFILE_GL, mrid("model", "gl", region))
        self._base_voltages: Dict[float, str] = {}
        self._geo_region_m: Optional[str] = None
        self._sub_region_m: Optional[str] = None
        self._cs_m: Optional[str] = None

    def header(self) -> "CimExporter":
        """Emit the RDF/XML headers for both profiles."""
        self.eq.header()
        self.gl.header()
        return self

    # -- shared/reference objects (lazily created) --------------------------
    def _base_voltage(self, kv: Optional[float]) -> Optional[str]:
        """Return the BaseVoltage mRID for ``kv`` (defined in the boundary).

        The Level-1 EQ used to define BaseVoltage objects inline, which
        duplicated the rdf:IDs owned by the shared boundary set
        (``AllJapan_EQ_BD.xml``) — strict CGMES importers reject datasets
        with duplicate definitions (REVIEW_FINDINGS P0 #9). Like Level-2,
        the EQ now only *references* the deterministic boundary mRID
        (:func:`src.cim.core.base_voltage_mrid` yields the identical id
        the inline path produced) and records the voltage so the caller
        can generate a covering boundary set.
        """
        if kv is None:
            return None
        key = round(float(kv), 3)
        existing = self._base_voltages.get(key)
        if existing:
            return existing
        m = base_voltage_mrid(key)
        self._base_voltages[key] = m
        return m

    def _ensure_region(self) -> None:
        """Create the GeographicalRegion / SubGeographicalRegion once."""
        if self._sub_region_m is not None:
            return
        geo = mrid("georegion", "japan")
        self._geo_region_m = geo
        self.eq.obj(
            "GeographicalRegion",
            geo,
            attrs={"IdentifiedObject.name": "Japan", "IdentifiedObject.mRID": geo},
        )
        sub = mrid("subgeoregion", self.region)
        self._sub_region_m = sub
        self.eq.obj(
            "SubGeographicalRegion",
            sub,
            attrs={
                "IdentifiedObject.name": REGION_NAME.get(self.region, self.region),
                "IdentifiedObject.mRID": sub,
            },
            refs={"SubGeographicalRegion.Region": geo},
        )

    def _coordinate_system(self) -> str:
        """Return (creating once) the WGS84 CoordinateSystem mRID."""
        if self._cs_m is not None:
            return self._cs_m
        m = mrid("coordsys", "wgs84")
        self._cs_m = m
        self.gl.obj(
            "CoordinateSystem",
            m,
            attrs={
                "IdentifiedObject.name": "WGS84",
                "IdentifiedObject.mRID": m,
                "CoordinateSystem.crsUrn": "urn:ogc:def:crs:EPSG::4326",
            },
        )
        return m

    def _location(self, psr_mrid: str, points: List[Tuple[float, float]]) -> None:
        """Attach a GL Location + PositionPoints to a power-system resource."""
        if not points:
            return
        loc = mrid("location", psr_mrid)
        self.gl.obj(
            "Location",
            loc,
            attrs={"IdentifiedObject.mRID": loc},
            refs={
                "Location.CoordinateSystem": self._coordinate_system(),
                "Location.PowerSystemResources": psr_mrid,
            },
        )
        for seq, (lon, lat) in enumerate(points, start=1):
            pp = mrid("pospoint", psr_mrid, seq)
            self.gl.obj(
                "PositionPoint",
                pp,
                attrs={
                    "PositionPoint.sequenceNumber": seq,
                    "PositionPoint.xPosition": f"{lon:.6f}",
                    "PositionPoint.yPosition": f"{lat:.6f}",
                },
                refs={"PositionPoint.Location": loc},
            )

    # -- per-feature adders --------------------------------------------------
    def add_substation(self, idx: int, props: dict, geom: Optional[dict]) -> str:
        """Map one substation feature to Substation + VoltageLevel (+ geo)."""
        self._ensure_region()
        name = props.get("name") or props.get("_display_name") or f"{self.region}_sub_{idx}"
        m = mrid("substation", self.region, idx)
        self.eq.obj(
            "Substation",
            m,
            attrs={"IdentifiedObject.name": name, "IdentifiedObject.mRID": m},
            refs={"Substation.Region": self._sub_region_m},
        )
        kv, _, _ = parse_voltage_kv(props.get("voltage"))
        base_v = self._base_voltage(kv)
        vl = mrid("voltagelevel", self.region, idx)
        self.eq.obj(
            "VoltageLevel",
            vl,
            attrs={"IdentifiedObject.name": f"{name} VL", "IdentifiedObject.mRID": vl},
            refs={"VoltageLevel.Substation": m, "VoltageLevel.BaseVoltage": base_v},
        )
        point = _representative_point(geom)
        if point:
            self._location(m, [point])
        return m

    def add_line(self, idx: int, props: dict, geom: Optional[dict]) -> str:
        """Map one line feature to ACLineSegment + 2 Terminals/CNs (+ geo)."""
        self._ensure_region()
        name = props.get("name") or f"{self.region}_line_{idx}"
        m = mrid("line", self.region, idx)
        kv, _, _ = parse_voltage_kv(props.get("voltage") or props.get("voltage:design"))
        base_v = self._base_voltage(kv)
        coords = _line_coords(geom)
        attrs: Dict[str, object] = {"IdentifiedObject.name": name, "IdentifiedObject.mRID": m}
        length_m = _polyline_length_m(coords)
        if length_m > 0:
            attrs["Conductor.length"] = round(length_m, 1)
        self.eq.obj(
            "ACLineSegment",
            m,
            attrs=attrs,
            refs={"ConductingEquipment.BaseVoltage": base_v},
        )
        for seq in (1, 2):
            cn = mrid("cn", self.region, "line", idx, seq)
            self.eq.obj("ConnectivityNode", cn, attrs={"IdentifiedObject.mRID": cn})
            term = mrid("term", self.region, "line", idx, seq)
            self.eq.obj(
                "Terminal",
                term,
                attrs={"IdentifiedObject.mRID": term, "ACDCTerminal.sequenceNumber": seq},
                refs={"Terminal.ConductingEquipment": m, "Terminal.ConnectivityNode": cn},
            )
        if coords:
            self._location(m, coords)
        return m

    def add_plant(self, idx: int, props: dict, geom: Optional[dict]) -> str:
        """Map one plant feature to a fuel-specific GeneratingUnit (+ machine, geo)."""
        self._ensure_region()
        name = props.get("name") or props.get("_display_name") or f"{self.region}_plant_{idx}"
        fuel = str(props.get("fuel_type") or "unknown").strip().lower()
        cim_cls = _FUEL_TO_CIM.get(fuel, "GeneratingUnit")
        m = mrid("plant", self.region, idx)
        attrs: Dict[str, object] = {"IdentifiedObject.name": name, "IdentifiedObject.mRID": m}
        cap = props.get("capacity_mw")
        if isinstance(cap, (int, float)) and cap > 0:
            attrs["GeneratingUnit.ratedP"] = cap
            attrs["GeneratingUnit.maxOperatingP"] = cap
            attrs["GeneratingUnit.minOperatingP"] = 0
        self.eq.obj(cim_cls, m, attrs=attrs)
        if cim_cls in _ROTATING:
            sm = mrid("syncmachine", self.region, idx)
            kv, _, _ = parse_voltage_kv(props.get("voltage"))
            sm_attrs: Dict[str, object] = {
                "IdentifiedObject.name": f"{name} gen",
                "IdentifiedObject.mRID": sm,
            }
            if isinstance(cap, (int, float)) and cap > 0:
                sm_attrs["RotatingMachine.ratedS"] = cap
            self.eq.obj(
                "SynchronousMachine",
                sm,
                attrs=sm_attrs,
                refs={
                    "RotatingMachine.GeneratingUnit": m,
                    "ConductingEquipment.BaseVoltage": self._base_voltage(kv),
                },
            )
        point = _representative_point(geom)
        if point:
            self._location(m, [point])
        return m


def export_region(region: str, data_dir: str, out_dir: str) -> dict:
    """Export one region's GeoJSON to CGMES EQ + GL RDF/XML files.

    Args:
        region: Region key (e.g. ``"okinawa"``).
        data_dir: Directory holding ``<region>_<kind>.geojson``.
        out_dir: Output directory for ``<region>_EQ.xml`` / ``<region>_GL.xml``.

    Returns:
        A summary dict with per-kind feature counts, object counts and paths.
    """
    exporter = CimExporter(region).header()
    counts: Dict[str, int] = {}
    adders = {
        "substations": exporter.add_substation,
        "lines": exporter.add_line,
        "plants": exporter.add_plant,
    }
    for kind, adder in adders.items():
        path = os.path.join(data_dir, f"{region}_{kind}.geojson")
        n = 0
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                collection = json.load(fh)
            for i, feature in enumerate(collection.get("features", [])):
                props = feature.get("properties") or {}
                geom = feature.get("geometry")
                try:
                    adder(i, props, geom)
                    n += 1
                except Exception:  # noqa: BLE001 — skip a single bad feature, keep going
                    continue
        counts[kind] = n

    os.makedirs(out_dir, exist_ok=True)
    eq_path = os.path.join(out_dir, f"{region}_EQ.xml")
    gl_path = os.path.join(out_dir, f"{region}_GL.xml")
    exporter.eq.write(eq_path)
    exporter.gl.write(gl_path)
    return {
        "region": region,
        "counts": counts,
        "eq_objects": exporter.eq.object_count,
        "gl_objects": exporter.gl.object_count,
        "base_voltages": sorted(exporter._base_voltages.keys(), reverse=True),
        "eq_path": eq_path,
        "gl_path": gl_path,
    }
