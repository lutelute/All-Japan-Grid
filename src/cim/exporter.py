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
import unicodedata
from typing import Dict, List, Optional, Tuple

from ..regions import REGION_EN as REGION_NAME  # noqa: F401
from .core import PROFILE_EQ, PROFILE_GL, RdfWriter, base_voltage_mrid, mrid

# REGION_NAME (English region names for IdentifiedObject.name of
# SubGeographicalRegion) is the canonical map from src.regions, re-exported
# here so `from src.cim.exporter import REGION_NAME` keeps working.

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


def _norm_site_name(name: object) -> str:
    """サイト名照合用の正規化(NFKC+空白除去)。

    構造DB(data/structures)のサイト名と GeoJSON の変電所名は同じ OSM 名を
    源泉に持つが、「新生駒 変電所」のような空白ゆれが実在する
    (transformer_provenance.normalize_site_key と同旨)。
    """
    return "".join(unicodedata.normalize("NFKC", str(name or "")).split())


def _vl_kv(vl_id: object) -> Optional[float]:
    """構造DBの voltage-level id (``…@275``) から kV を取り出す。"""
    try:
        return float(str(vl_id).rsplit("@", 1)[1])
    except (IndexError, ValueError):
        return None


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
        # 正規化サイト名 -> Substation mRID (構造DB由来の変圧器を正しい
        # 変電所コンテナへ収めるための照合表。同名は最初の feature 優先)。
        self._sub_by_name: Dict[str, str] = {}

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
        norm = _norm_site_name(name)
        if norm:
            self._sub_by_name.setdefault(norm, m)
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
        # Prefer the sourced capacity: apply_capacity_sources.py stamps a
        # one-primary-source nameplate value (capacity_mw_sourced) with its
        # citation. That authoritative value — not the raw OSM/P03
        # capacity_mw — is what the CIM export must carry (Phase 1-B
        # 出典伝播: the citation reaches downstream, not just the map popup).
        sourced_cap = props.get("capacity_mw_sourced")
        source_url = props.get("capacity_source_url")
        cap = sourced_cap if isinstance(sourced_cap, (int, float)) else props.get("capacity_mw")
        if isinstance(cap, (int, float)) and cap > 0:
            attrs["GeneratingUnit.ratedP"] = cap
            attrs["GeneratingUnit.maxOperatingP"] = cap
            attrs["GeneratingUnit.minOperatingP"] = 0
        # Carry the provenance URL into IdentifiedObject.description so the
        # value's origin is traceable in the CGMES model itself, not only
        # in the source DB (captation-prevention貫通 to CIM).
        if isinstance(source_url, str) and source_url.strip():
            attrs["IdentifiedObject.description"] = source_url.strip()
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

    def add_transformer(self, site_idx: int, t_idx: int,
                        site_name: str, spec: dict) -> Optional[str]:
        """構造DBの TransformerSpec 1件を PowerTransformer + 2 ends に写像する。

        Phase 1-B「PowerTransformer出力」: 変圧器出典DB
        (data/transformer_sources.jsonl → 構造DB source="nameplate") の銘板が
        CGMES まで届く。add_plant と同型で、**出典URLは
        IdentifiedObject.description に貫通**させる(捏造防止規約の下流貫通)。

        誠実性の規約:
          - ratedS は銘板(existing出典)を持つ spec のみ(sn_mva が None の
            structural spec には**書かない** — 定格の捏造をしない)。
          - ratedS は銘板の単機値。バンク台数(n_parallel)は名前の ``×N`` で
            開示する(CGMES 2.4 に台数属性が無いため)。
          - description は source="nameplate" の出典URLのみ(note 形式
            "url | quote" の URL 部)。
        """
        hv, lv = _vl_kv(spec.get("hv_vl_id")), _vl_kv(spec.get("lv_vl_id"))
        if not hv or not lv:
            return None   # 電圧階級が読めない spec は写像しない(捏造回避)
        self._ensure_region()
        m = mrid("trafo", self.region, site_idx, t_idx)
        par = int(spec.get("n_parallel") or 1)
        name = f"{site_name} {hv:g}/{lv:g}kV変圧器"
        if par > 1:
            name += f" ×{par}"
        attrs: Dict[str, object] = {
            "IdentifiedObject.name": name, "IdentifiedObject.mRID": m}
        sn = spec.get("sn_mva")
        if spec.get("source") == "nameplate":
            url = str(spec.get("note") or "").split(" | ", 1)[0].strip()
            if url.startswith("http"):
                attrs["IdentifiedObject.description"] = url
        refs: Dict[str, str] = {}
        container = self._sub_by_name.get(_norm_site_name(site_name))
        if container:
            refs["Equipment.EquipmentContainer"] = container
        self.eq.obj("PowerTransformer", m, attrs=attrs, refs=refs)
        for end, kv in ((1, hv), (2, lv)):
            cn = mrid("cn", self.region, "trafo", site_idx, t_idx, end)
            self.eq.obj("ConnectivityNode", cn,
                        attrs={"IdentifiedObject.mRID": cn})
            term = mrid("term", self.region, "trafo", site_idx, t_idx, end)
            self.eq.obj(
                "Terminal", term,
                attrs={"IdentifiedObject.mRID": term,
                       "ACDCTerminal.sequenceNumber": end},
                refs={"Terminal.ConductingEquipment": m,
                      "Terminal.ConnectivityNode": cn})
            pte = mrid("pte", self.region, site_idx, t_idx, end)
            end_attrs: Dict[str, object] = {
                "IdentifiedObject.mRID": pte,
                "TransformerEnd.endNumber": end,
                "PowerTransformerEnd.ratedU": kv,
            }
            if isinstance(sn, (int, float)) and sn > 0:
                end_attrs["PowerTransformerEnd.ratedS"] = sn
            self.eq.obj(
                "PowerTransformerEnd", pte,
                attrs=end_attrs,
                refs={"PowerTransformerEnd.PowerTransformer": m,
                      "TransformerEnd.BaseVoltage": self._base_voltage(kv),
                      "TransformerEnd.Terminal": term})
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
    # R層（OSM 生抽出）には出典付き容量の欄が無い。本 exporter は
    # `capacity_mw_sourced` を優先する実装だが、入力に欄が無いため 2026-08-09 時点で
    # CGMES の `GeneratingUnit.ratedP` は生値のままだった
    # （`capacity_provenance_reach_2026-08-09.md`）。R層は書き換えず、ここでD層を引く。
    from src.capacity_sources import geo_key as sourced_geo_key
    from src.capacity_sources import sourced_capacity_index
    sourced = sourced_capacity_index()

    for kind, adder in adders.items():
        path = os.path.join(data_dir, f"{region}_{kind}.geojson")
        n = 0
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                collection = json.load(fh)
            for i, feature in enumerate(collection.get("features", [])):
                props = feature.get("properties") or {}
                geom = feature.get("geometry")
                if (kind == "plants" and sourced
                        and isinstance(geom, dict) and geom.get("type") == "Point"):
                    hit = sourced.get(sourced_geo_key(
                        region, geom["coordinates"][0], geom["coordinates"][1]))
                    if hit:
                        props = {**props, **hit}
                try:
                    adder(i, props, geom)
                    n += 1
                except Exception:  # noqa: BLE001 — skip a single bad feature, keep going
                    continue
        counts[kind] = n

    # 構造DB(data/structures/{region}.json)の変圧器を PowerTransformer として
    # 写像する(Phase 1-B「PowerTransformer出力」)。構造DBは生成物(untracked)
    # なので無い環境ではスキップ = 従来出力と同一(再現には
    # build_structures_batch.py --all を先に実行)。
    n_tr = 0
    st_path = os.path.join(data_dir, "structures", f"{region}.json")
    if os.path.exists(st_path):
        with open(st_path, encoding="utf-8") as fh:
            st = json.load(fh)
        for s_i, site in enumerate(st.get("structures", [])):
            trs = site.get("transformers") or []
            if not trs:
                continue
            site_name = (site.get("site") or {}).get("name") or f"site{s_i}"
            for t_i, tr in enumerate(trs):
                try:
                    if exporter.add_transformer(s_i, t_i, site_name, tr):
                        n_tr += 1
                except Exception:  # noqa: BLE001 — 1 spec の不備で region を止めない
                    continue
    counts["transformers"] = n_tr

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
