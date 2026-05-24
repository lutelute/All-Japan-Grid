"""
All-Japan-Grid Network Builder
================================
Loads regional GeoJSON data and constructs a sparse Y-bus admittance matrix
suitable for power flow and dynamics simulations.

Design follows the approach in scripts/gen_nx_proper.py:
  - Voltage snapping to nearest standard level
  - Geographic proximity matching for line endpoints → bus assignment
  - Haversine distance for all geographic calculations
  - Kron-reducible Y-bus using scipy.sparse for scalability

Per-unit base: 100 MVA (S_BASE), voltage bases per voltage class.

Usage example::

    from src.dynamics.network.builder import GridNetwork, assign_generators

    grid = GridNetwork.from_geojson("data/", voltage_levels=[500, 275])
    grid = grid.largest_connected_component()
    Ybus = grid.build_ybus()
    gens = assign_generators(grid, "data/")
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from itertools import combinations
from typing import Dict, List, Optional, Tuple

import numpy as np
import scipy.sparse as sp
from scipy.sparse.csgraph import connected_components


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REGIONS: List[str] = [
    "hokkaido", "tohoku", "tokyo", "chubu",
    "hokuriku", "kansai", "chugoku", "shikoku", "kyushu", "okinawa",
]

# Standard voltage classes [kV] used for snapping
STANDARD_KV: List[int] = [500, 275, 154, 110, 77, 66]

# Line parameters per voltage class (Ω/km and μS/km, physical units)
# Used to compute Z_pu = Z_phys * S_base / V_base^2
# B_pu_km = b_us_km × 1e-6 × V_kv² / S_mva  (shunt charging susceptance per km)
LINE_PARAMS_OHM_KM: Dict[int, Dict[str, float]] = {
    500: {"r_ohm_km": 0.02,  "x_ohm_km": 0.30, "b_us_km": 2.7},
    275: {"r_ohm_km": 0.06,  "x_ohm_km": 0.35, "b_us_km": 2.3},
    154: {"r_ohm_km": 0.10,  "x_ohm_km": 0.40, "b_us_km": 1.8},
    110: {"r_ohm_km": 0.12,  "x_ohm_km": 0.42, "b_us_km": 1.5},
    77:  {"r_ohm_km": 0.18,  "x_ohm_km": 0.45, "b_us_km": 1.2},
    66:  {"r_ohm_km": 0.20,  "x_ohm_km": 0.45, "b_us_km": 1.0},
}

# Geographic matching thresholds [km] per voltage class
MATCH_THRESHOLD_KM: Dict[int, float] = {
    500: 8.0,
    275: 5.0,
    154: 3.0,
    110: 3.0,
    77:  2.0,
    66:  2.0,
}

# Default threshold for unknown voltage classes
MATCH_THRESHOLD_DEFAULT_KM: float = 3.0

# Generator-to-bus matching threshold [km]
GEN_MATCH_KM: float = 8.0

# Minimum line length per voltage class (transmission-level filter)
# 66/77 kV include many short distribution feeders → use longer threshold
MIN_LINE_LENGTH_BY_KV: Dict[int, float] = {
    500: 0.5,
    275: 0.5,
    154: 1.0,
    110: 2.0,
    77:  5.0,   # transmission lines only (feeders excluded)
    66:  5.0,   # transmission lines only (feeders excluded)
}
MIN_LINE_LENGTH_KM: float = 0.5  # default fallback

# Maximum per-unit admittance cap (avoids ill-conditioning from very short lines)
MAX_ADMITTANCE_PU: float = 200.0

# Standard transformer voltage pairs (hi_kv, lo_kv) — only create transformers for these
# Pairs like (500, 66) or (275, 66) are NOT standard and should not be created directly
STANDARD_TRANSFORMER_PAIRS: set = {
    (500, 275), (275, 220), (275, 154), (220, 154),
    (154, 110), (154, 77), (154, 66),
    (110, 66), (77, 66), (110, 77),
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class BusData:
    """Represents a single bus (substation) in the network."""

    id: int                        # Integer bus index (0-based, contiguous)
    name: str                      # Human-readable name
    base_kv: float                 # Nominal voltage [kV]
    region: str                    # Regional system name (e.g., "tokyo")
    lat: float                     # Geographic latitude [°]
    lon: float                     # Geographic longitude [°]
    bus_type: str = "PQ"           # "PQ", "PV", or "slack"
    V_mag: float = 1.0             # Voltage magnitude [pu] (initial / result)
    V_ang: float = 0.0             # Voltage angle [rad]  (initial / result)
    P_gen: float = 0.0             # Active generation [pu, 100 MVA base]
    Q_gen: float = 0.0             # Reactive generation [pu]
    P_load: float = 0.0            # Active load [pu]
    Q_load: float = 0.0            # Reactive load [pu]


@dataclass
class LineData:
    """Represents a single transmission line / branch."""

    from_bus: int                  # Bus index (0-based)
    to_bus: int                    # Bus index (0-based)
    R_pu: float                    # Series resistance [pu, 100 MVA base]
    X_pu: float                    # Series reactance  [pu]
    B_pu: float                    # Shunt susceptance [pu] (total line charging)
    base_kv: float                 # Line voltage class [kV]
    length_km: float               # Physical length [km]
    rating_mva: float = 0.0        # Thermal rating [MVA] (0 = unknown)


# ---------------------------------------------------------------------------
# Geographic utilities
# ---------------------------------------------------------------------------

def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance between two geographic points [km]."""
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2)
    return 2.0 * R * math.asin(math.sqrt(max(0.0, min(1.0, a))))


def _geom_centroid(geom: dict) -> Optional[Tuple[float, float]]:
    """
    Return (lon, lat) centroid of a GeoJSON geometry.

    Supports Point, Polygon, MultiPolygon.
    """
    gtype = geom.get("type", "")
    coords = geom.get("coordinates")
    if coords is None:
        return None

    if gtype == "Point":
        return float(coords[0]), float(coords[1])

    elif gtype == "Polygon":
        ring = coords[0]
        lon = float(np.mean([c[0] for c in ring]))
        lat = float(np.mean([c[1] for c in ring]))
        return lon, lat

    elif gtype == "MultiPolygon":
        all_c: List[list] = []
        for poly in coords:
            all_c.extend(poly[0])
        lon = float(np.mean([c[0] for c in all_c]))
        lat = float(np.mean([c[1] for c in all_c]))
        return lon, lat

    return None


def _snap_voltage_kv(v_str: object) -> int:
    """
    Parse a voltage field (may be "500000", "275000;154000", etc.) and snap
    to the nearest standard voltage class [kV]. Returns the PRIMARY (first) level.
    """
    try:
        raw = str(v_str).split(";")[0].strip().replace(",", "")
        kv = int(float(raw)) // 1000
        return min(STANDARD_KV, key=lambda c: abs(c - kv))
    except (TypeError, ValueError):
        return STANDARD_KV[-1]    # default to lowest class


def _all_voltages_kv(v_str: object, target_kv: set) -> List[int]:
    """
    Parse ALL voltage levels from a compound field ("154000;66000" etc.)
    and return those that are in target_kv, sorted high→low.
    """
    result = []
    for part in str(v_str).replace(",", ";").split(";"):
        part = part.strip()
        try:
            kv = int(float(part)) // 1000
            snapped = min(STANDARD_KV, key=lambda c: abs(c - kv))
            if snapped in target_kv and snapped not in result:
                result.append(snapped)
        except (TypeError, ValueError):
            pass
    return sorted(result, reverse=True)   # highest first


def _line_length_km(coords: List[List[float]]) -> float:
    """Sum of haversine distances along a polyline [km]."""
    total = 0.0
    for k in range(len(coords) - 1):
        total += _haversine_km(
            coords[k][0], coords[k][1],
            coords[k + 1][0], coords[k + 1][1],
        )
    return total


# ---------------------------------------------------------------------------
# Bus nearest-neighbour lookup
# ---------------------------------------------------------------------------

def _nearest_bus(
    lon: float,
    lat: float,
    buses: List[BusData],
    preferred_kv: int,
    threshold_km: float,
    strict: bool = False,
) -> Optional[int]:
    """
    Find the index of the nearest bus within *threshold_km*.

    When strict=True (used for line endpoint matching):
      Return only if a same-voltage bus is within threshold.
    When strict=False:
      1. Same voltage class and within threshold → return its id.
      2. Any voltage class within threshold → return its id.
      3. No bus within threshold → return None.
    """
    best_same_id: Optional[int] = None
    best_same_d: float = math.inf
    best_any_id: Optional[int] = None
    best_any_d: float = math.inf

    for b in buses:
        d = _haversine_km(lon, lat, b.lon, b.lat)
        if d < best_any_d:
            best_any_d = d
            best_any_id = b.id
        if b.base_kv == preferred_kv and d < best_same_d:
            best_same_d = d
            best_same_id = b.id

    if best_same_id is not None and best_same_d <= threshold_km:
        return best_same_id
    if not strict and best_any_id is not None and best_any_d <= threshold_km:
        return best_any_id
    return None


# ---------------------------------------------------------------------------
# Impedance conversion
# ---------------------------------------------------------------------------

def _pu_params(
    volt_kv: int,
    length_km: float,
    sbase_mva: float,
) -> Tuple[float, float, float]:
    """
    Compute (R_pu, X_pu, B_pu) for a line.

    Z_base [Ω] = V_base² [kV²] / S_base [MVA]
    Z_pu = Z_phys / Z_base = Z_phys * S_base / V_base²
    """
    params = LINE_PARAMS_OHM_KM.get(volt_kv, LINE_PARAMS_OHM_KM[66])
    z_base = (volt_kv ** 2) / sbase_mva          # Ω
    R_pu = params["r_ohm_km"] * length_km / z_base
    X_pu = params["x_ohm_km"] * length_km / z_base
    # Shunt charging: B_pu = b_us_km × L × 1e-6 / Y_base = b_us_km × L × 1e-6 × z_base
    B_pu = params["b_us_km"] * length_km * 1e-6 * z_base
    return R_pu, X_pu, B_pu


# ---------------------------------------------------------------------------
# Main network class
# ---------------------------------------------------------------------------

class GridNetwork:
    """
    Transmission network built from All-Japan-Grid GeoJSON data.

    Attributes
    ----------
    buses : List[BusData]
        All buses (nodes) in the network.
    lines : List[LineData]
        All transmission lines (branches).
    sbase_mva : float
        MVA system base (default 100 MVA).
    """

    def __init__(
        self,
        buses: List[BusData],
        lines: List[LineData],
        sbase_mva: float = 100.0,
    ) -> None:
        self._buses: List[BusData] = buses
        self._lines: List[LineData] = lines
        self.sbase_mva: float = sbase_mva
        # Build fast lookup: bus_id → list index
        self._id_to_idx: Dict[int, int] = {b.id: i for i, b in enumerate(buses)}

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def buses(self) -> List[BusData]:
        return self._buses

    @property
    def lines(self) -> List[LineData]:
        return self._lines

    @property
    def nb(self) -> int:
        """Number of buses."""
        return len(self._buses)

    # ------------------------------------------------------------------
    # Index helpers
    # ------------------------------------------------------------------

    def get_bus_index(self, bus_id: int) -> int:
        """
        Return the list index for a given bus id.

        Raises KeyError if not found.
        """
        try:
            return self._id_to_idx[bus_id]
        except KeyError:
            raise KeyError(f"Bus id {bus_id} not found in network.")

    # ------------------------------------------------------------------
    # Y-bus construction
    # ------------------------------------------------------------------

    def build_ybus(self) -> sp.csc_matrix:
        """
        Build the sparse nodal admittance matrix (Y-bus) [pu].

        Returns
        -------
        scipy.sparse.csc_matrix, shape (nb, nb), dtype complex128
            Y[i, i] += y_ij  (diagonal)
            Y[i, j] -= y_ij  (off-diagonal)
        """
        n = self.nb
        row: List[int] = []
        col: List[int] = []
        dat: List[complex] = []

        def _add(r: int, c: int, val: complex) -> None:
            row.append(r)
            col.append(c)
            dat.append(val)

        for line in self._lines:
            i = self.get_bus_index(line.from_bus)
            j = self.get_bus_index(line.to_bus)

            Z = complex(line.R_pu, line.X_pu)
            if abs(Z) < 1e-12:
                continue
            y_series = 1.0 / Z
            y_shunt_half = 0.5j * line.B_pu

            # Diagonal: y_series + y_shunt (π model)
            _add(i, i,  y_series + y_shunt_half)
            _add(j, j,  y_series + y_shunt_half)
            # Off-diagonal
            _add(i, j, -y_series)
            _add(j, i, -y_series)

        Y = sp.coo_matrix((dat, (row, col)), shape=(n, n), dtype=complex)
        return Y.tocsc()

    # ------------------------------------------------------------------
    # Connected-component extraction
    # ------------------------------------------------------------------

    def top_k_components(self, k: int = 2, min_buses: int = 10) -> "List[GridNetwork]":
        """Return the k largest connected components as separate GridNetworks."""
        if self.nb == 0:
            return []
        n = self.nb
        id2idx = {b.id: i for i, b in enumerate(self._buses)}
        rows, cols, vals = [], [], []
        for ln in self._lines:
            fi = id2idx[ln.from_bus]; ti = id2idx[ln.to_bus]
            rows.extend([fi, ti]); cols.extend([ti, fi]); vals.extend([1, 1])
        adj = sp.coo_matrix((vals, (rows, cols)), shape=(n, n), dtype=int).tocsr()
        n_comp, labels = connected_components(adj, directed=False)
        sizes = np.bincount(labels)
        top_labels = [i for i in np.argsort(sizes)[::-1]
                      if sizes[i] >= min_buses][:k]
        result = []
        for lbl in top_labels:
            keep = np.where(labels == lbl)[0].tolist()
            old2new = {self._buses[i].id: ni for ni, i in enumerate(keep)}
            new_buses = []
            for new_idx, old_idx in enumerate(keep):
                b = self._buses[old_idx]
                new_buses.append(BusData(
                    id=new_idx, name=b.name, base_kv=b.base_kv,
                    region=b.region, lat=b.lat, lon=b.lon,
                    bus_type=b.bus_type, V_mag=b.V_mag, V_ang=b.V_ang,
                    P_gen=b.P_gen, Q_gen=b.Q_gen, P_load=b.P_load, Q_load=b.Q_load,
                ))
            new_lines = []
            for ln in self._lines:
                fi = old2new.get(ln.from_bus); ti = old2new.get(ln.to_bus)
                if fi is not None and ti is not None:
                    new_lines.append(LineData(
                        from_bus=fi, to_bus=ti, R_pu=ln.R_pu, X_pu=ln.X_pu,
                        B_pu=ln.B_pu, base_kv=ln.base_kv,
                        length_km=ln.length_km, rating_mva=ln.rating_mva,
                    ))
            result.append(GridNetwork(new_buses, new_lines, self.sbase_mva))
        return result

    def largest_connected_component(self) -> "GridNetwork":
        """
        Return a new GridNetwork containing only the largest connected
        component of the current network.

        Bus and line indices are re-numbered contiguously from 0.
        """
        if self.nb == 0:
            return GridNetwork([], [], self.sbase_mva)

        # Build adjacency using Y-bus connectivity (symmetric)
        n = self.nb
        rows, cols, vals = [], [], []
        for line in self._lines:
            i = self.get_bus_index(line.from_bus)
            j = self.get_bus_index(line.to_bus)
            rows.extend([i, j])
            cols.extend([j, i])
            vals.extend([1, 1])
        if vals:
            adj = sp.coo_matrix((vals, (rows, cols)), shape=(n, n), dtype=int).tocsr()
        else:
            adj = sp.csr_matrix((n, n), dtype=int)

        n_comp, labels = connected_components(adj, directed=False)

        comp_sizes = np.bincount(labels)
        main_label = int(np.argmax(comp_sizes))
        mask = labels == main_label
        keep_indices = np.where(mask)[0].tolist()

        old_id_to_new_idx: Dict[int, int] = {}
        new_buses: List[BusData] = []
        for new_idx, old_idx in enumerate(keep_indices):
            b = self._buses[old_idx]
            old_id_to_new_idx[b.id] = new_idx
            new_buses.append(BusData(
                id=new_idx,
                name=b.name,
                base_kv=b.base_kv,
                region=b.region,
                lat=b.lat,
                lon=b.lon,
                bus_type=b.bus_type,
                V_mag=b.V_mag,
                V_ang=b.V_ang,
                P_gen=b.P_gen,
                Q_gen=b.Q_gen,
                P_load=b.P_load,
                Q_load=b.Q_load,
            ))

        # Remap lines
        new_lines: List[LineData] = []
        for line in self._lines:
            fi = old_id_to_new_idx.get(line.from_bus)
            ti = old_id_to_new_idx.get(line.to_bus)
            if fi is not None and ti is not None:
                new_lines.append(LineData(
                    from_bus=fi,
                    to_bus=ti,
                    R_pu=line.R_pu,
                    X_pu=line.X_pu,
                    B_pu=line.B_pu,
                    base_kv=line.base_kv,
                    length_km=line.length_km,
                    rating_mva=line.rating_mva,
                ))

        return GridNetwork(new_buses, new_lines, self.sbase_mva)

    # ------------------------------------------------------------------
    # Hop-distance filter (removes LV buses far from HV backbone)
    # ------------------------------------------------------------------

    def filter_by_hv_distance(
        self,
        hv_threshold_kv: float = 110.0,
        max_hops: int = 2,
    ) -> "GridNetwork":
        """Remove buses that are more than *max_hops* graph hops from
        any bus with base_kv ≥ hv_threshold_kv.

        This prunes long radial 66 kV chains that are far from the
        HV backbone, which cause ill-conditioned Jacobians in NR.

        Parameters
        ----------
        hv_threshold_kv : float
            Buses at this voltage level or above are the "anchor" roots.
        max_hops : int
            Maximum number of hops from any root bus to include.
        """
        n = self.nb
        if n == 0:
            return GridNetwork([], [], self.sbase_mva)

        # Build adjacency list
        adj: Dict[int, List[int]] = {i: [] for i in range(n)}
        id_to_idx = {b.id: i for i, b in enumerate(self._buses)}
        for ln in self._lines:
            fi = id_to_idx[ln.from_bus]
            ti = id_to_idx[ln.to_bus]
            adj[fi].append(ti)
            adj[ti].append(fi)

        # BFS from all HV root buses simultaneously
        dist = [-1] * n
        queue = []
        for i, b in enumerate(self._buses):
            if b.base_kv >= hv_threshold_kv:
                dist[i] = 0
                queue.append(i)

        head = 0
        while head < len(queue):
            cur = queue[head]; head += 1
            if dist[cur] >= max_hops:
                continue
            for nb in adj[cur]:
                if dist[nb] == -1:
                    dist[nb] = dist[cur] + 1
                    queue.append(nb)

        keep_mask = [d != -1 for d in dist]
        keep_indices = [i for i, k in enumerate(keep_mask) if k]

        old_id_to_new: Dict[int, int] = {}
        new_buses: List[BusData] = []
        for new_idx, old_idx in enumerate(keep_indices):
            b = self._buses[old_idx]
            old_id_to_new[b.id] = new_idx
            new_buses.append(BusData(
                id=new_idx, name=b.name, base_kv=b.base_kv,
                region=b.region, lat=b.lat, lon=b.lon,
                bus_type=b.bus_type, V_mag=b.V_mag, V_ang=b.V_ang,
                P_gen=b.P_gen, Q_gen=b.Q_gen,
                P_load=b.P_load, Q_load=b.Q_load,
            ))

        new_lines: List[LineData] = []
        for ln in self._lines:
            fi = old_id_to_new.get(ln.from_bus)
            ti = old_id_to_new.get(ln.to_bus)
            if fi is not None and ti is not None:
                new_lines.append(LineData(
                    from_bus=fi, to_bus=ti,
                    R_pu=ln.R_pu, X_pu=ln.X_pu, B_pu=ln.B_pu,
                    base_kv=ln.base_kv, length_km=ln.length_km,
                    rating_mva=ln.rating_mva,
                ))

        return GridNetwork(new_buses, new_lines, self.sbase_mva)

    # ------------------------------------------------------------------
    # Class-method constructor
    # ------------------------------------------------------------------

    @classmethod
    def from_geojson(
        cls,
        data_dir: str,
        voltage_levels: List[int] = (500, 275),
        sbase_mva: float = 100.0,
        regions: Optional[List[str]] = None,
        cache_dir: Optional[str] = None,
    ) -> "GridNetwork":
        """
        Build a GridNetwork by loading all regional GeoJSON files.

        Parameters
        ----------
        data_dir : str
            Path to the directory containing ``{region}_substations.geojson``
            and ``{region}_lines.geojson`` files.
        voltage_levels : list of int
            Voltage classes to include [kV].  Default: [500, 275].
        sbase_mva : float
            MVA system base.  Default: 100 MVA.
        regions : list of str, optional
            Subset of regions to load.  Default: all 10 REGIONS.
        cache_dir : str, optional
            If provided, cache the built network as a pickle in this directory
            and reuse on subsequent calls with the same parameters.

        Returns
        -------
        GridNetwork
        """
        import pickle, hashlib
        target_regions = regions if regions is not None else REGIONS

        # ── Cache lookup ────────────────────────────────────────────────
        if cache_dir is not None:
            os.makedirs(cache_dir, exist_ok=True)
            cache_key = hashlib.md5(
                f"{sorted(voltage_levels)}-{sorted(target_regions)}-{sbase_mva}".encode()
            ).hexdigest()[:12]
            cache_path = os.path.join(cache_dir, f"gridnet_{cache_key}.pkl")
            if os.path.exists(cache_path):
                try:
                    with open(cache_path, "rb") as fh:
                        return pickle.load(fh)
                except Exception:
                    pass   # fall through to rebuild
        target_kv = set(int(v) for v in voltage_levels)

        # ── Step 1: Load buses (multi-voltage substations → multiple buses) ──
        buses: List[BusData] = []
        # transformer_pairs: (higher_bus_id, lower_bus_id) for co-located buses
        transformer_pairs: List[Tuple[int, int, int, int]] = []  # (hi_id, lo_id, hi_kv, lo_kv)
        bus_id = 0
        for region in target_regions:
            sub_path = os.path.join(data_dir, f"{region}_substations.geojson")
            if not os.path.exists(sub_path):
                continue
            with open(sub_path, encoding="utf-8") as fh:
                gj = json.load(fh)

            for feat in gj.get("features", []):
                props = feat.get("properties", {})
                raw_v = props.get("voltage")
                if raw_v is None:
                    continue
                # Get ALL voltage levels present at this substation
                all_kv = _all_voltages_kv(raw_v, target_kv)
                if not all_kv:
                    continue
                geom = feat.get("geometry")
                if geom is None:
                    continue
                pos = _geom_centroid(geom)
                if pos is None:
                    continue
                lon, lat = pos

                name = (
                    props.get("name")
                    or props.get("_display_name")
                    or f"{region}_{bus_id}"
                )

                # Create a bus for each voltage level at this substation
                new_bus_ids: List[Tuple[int, int]] = []   # (bus_id, kv)
                for v_kv in all_kv:
                    buses.append(BusData(
                        id=bus_id,
                        name=f"{name}_{v_kv}kV" if len(all_kv) > 1 else str(name),
                        base_kv=float(v_kv),
                        region=region,
                        lat=lat,
                        lon=lon,
                    ))
                    new_bus_ids.append((bus_id, v_kv))
                    bus_id += 1

                # Add transformer pairs only for standard adjacent voltage pairs
                for i in range(len(new_bus_ids) - 1):
                    hi_id, hi_kv = new_bus_ids[i]
                    lo_id, lo_kv = new_bus_ids[i + 1]
                    if (hi_kv, lo_kv) in STANDARD_TRANSFORMER_PAIRS:
                        transformer_pairs.append((hi_id, lo_id, hi_kv, lo_kv))


        if not buses:
            return cls([], [], sbase_mva)

        # ── Step 2: Load lines and build edges ────────────────────────
        lines: List[LineData] = []
        seen_edges: set = set()     # (min_id, max_id, volt_kv) → deduplicate

        for region in target_regions:
            line_path = os.path.join(data_dir, f"{region}_lines.geojson")
            if not os.path.exists(line_path):
                # Fall back to proximity-based connectivity if no lines file
                continue
            with open(line_path, encoding="utf-8") as fh:
                gj = json.load(fh)

            for feat in gj.get("features", []):
                props = feat.get("properties", {})
                raw_v = props.get("voltage")
                if raw_v is None:
                    continue
                v_kv = _snap_voltage_kv(raw_v)
                if v_kv not in target_kv:
                    continue

                geom = feat.get("geometry")
                if geom is None:
                    continue

                # Normalise to list-of-segments
                gtype = geom["type"]
                coords_list = geom.get("coordinates", [])
                if gtype == "LineString":
                    segments: List[List[List[float]]] = [coords_list]
                elif gtype == "MultiLineString":
                    segments = coords_list
                else:
                    continue

                threshold = MATCH_THRESHOLD_KM.get(v_kv, MATCH_THRESHOLD_DEFAULT_KM)

                min_len = MIN_LINE_LENGTH_BY_KV.get(v_kv, MIN_LINE_LENGTH_KM)

                for seg in segments:
                    if len(seg) < 2:
                        continue
                    length_km = _line_length_km(seg)
                    if length_km < min_len:
                        continue

                    # Match endpoints to nearest buses — strict: same voltage class only
                    s_lon, s_lat = seg[0][0],  seg[0][1]
                    e_lon, e_lat = seg[-1][0], seg[-1][1]

                    bi = _nearest_bus(s_lon, s_lat, buses, v_kv, threshold, strict=True)
                    bj = _nearest_bus(e_lon, e_lat, buses, v_kv, threshold, strict=True)

                    if bi is None or bj is None or bi == bj:
                        continue

                    # Deduplicate (undirected)
                    edge_key = (min(bi, bj), max(bi, bj), v_kv)
                    if edge_key in seen_edges:
                        continue
                    seen_edges.add(edge_key)

                    R_pu, X_pu, B_pu = _pu_params(v_kv, length_km, sbase_mva)

                    if (R_pu ** 2 + X_pu ** 2) < 1e-18:
                        continue

                    # Skip lines with admittance > cap (very short, degenerate)
                    y_mag = 1.0 / max((R_pu**2 + X_pu**2)**0.5, 1e-12)
                    if y_mag > MAX_ADMITTANCE_PU:
                        continue

                    lines.append(LineData(
                        from_bus=bi,
                        to_bus=bj,
                        R_pu=R_pu,
                        X_pu=X_pu,
                        B_pu=B_pu,
                        base_kv=float(v_kv),
                        length_km=length_km,
                    ))

        # ── Step 3: Add transformer branches for co-located multi-voltage buses ──
        # Transformer model: R=0.001 pu, X=0.10 pu (typical EHV/HV transformer)
        seen_tr: set = set()
        for hi_id, lo_id, hi_kv, lo_kv in transformer_pairs:
            # Make sure both bus IDs are valid
            if hi_id >= len(buses) or lo_id >= len(buses):
                continue
            edge_key = (min(hi_id, lo_id), max(hi_id, lo_id))
            if edge_key in seen_tr:
                continue
            seen_tr.add(edge_key)

            # Transformer reactance scaled by voltage ratio (pu on sbase)
            # Higher ratio → lower coupling → higher X in pu
            X_tr = 0.10 * (hi_kv / lo_kv) ** 0.5 / (sbase_mva / 100.0)
            X_tr = max(min(X_tr, 0.30), 0.05)   # clamp 0.05–0.30 pu

            # Rating estimate: lower-voltage side limits the capacity
            rating_mva = lo_kv * lo_kv / (sbase_mva * X_tr) * 0.3

            lines.append(LineData(
                from_bus=hi_id,
                to_bus=lo_id,
                R_pu=0.001,
                X_pu=X_tr,
                B_pu=0.0,
                base_kv=float(hi_kv),     # HV side nominal
                length_km=0.0,            # transformer (no physical length)
                rating_mva=rating_mva,
            ))

        # ── Step 4: Proximity-based connectivity ──────────────────────────
        # Connect isolated/weakly-connected buses to their k nearest same-voltage
        # neighbors within a generous distance threshold. This stitches the many
        # isolated substations (not covered by GeoJSON line data) into the network.
        # Uses scipy KDTree for O(n log n) NN search.
        try:
            from scipy.spatial import cKDTree
            # Build adjacency set from existing lines
            adj_set: set = set()
            for ln in lines:
                adj_set.add((min(ln.from_bus, ln.to_bus), max(ln.from_bus, ln.to_bus)))

            # Max proximity distance [km] per voltage class
            # 66 kV is excluded: proximity connections create too-long radial chains
            # causing reactive power imbalance → convergence failure.
            # Only GeoJSON-sourced 66 kV lines are used (real circuit data).
            PROX_KM: Dict[int, float] = {
                500: 400.0,
                275: 200.0,
                154:  80.0,
                110:  50.0,
                77:   20.0,
                66:    5.0,   # short urban connections only (X_pu ≤ 0.07)
            }
            # Maximum X_pu per proximity branch (skip long weak connections)
            MAX_PROX_X_PU = 0.20
            # k nearest neighbors to connect per bus
            K_NN = 2

            by_kv: Dict[int, List[int]] = {}   # kv → list of bus indices
            for i, b in enumerate(buses):
                kv = int(b.base_kv)
                by_kv.setdefault(kv, []).append(i)

            prox_seen: set = set()
            for kv, idxs in by_kv.items():
                if len(idxs) < 2:
                    continue
                max_km = PROX_KM.get(kv, 80.0)
                # Convert lat/lon to radians for approximate distance
                coords = np.array([[math.radians(buses[i].lat),
                                    math.radians(buses[i].lon)] for i in idxs])
                tree = cKDTree(coords)
                # Query k+1 (includes self) nearest within angular threshold
                ang_thresh = max_km / 6371.0   # arc-length approx
                k_q = min(K_NN + 1, len(idxs))
                dists, nbrs = tree.query(coords, k=k_q, distance_upper_bound=ang_thresh)
                for row_i, (dist_row, nbr_row) in enumerate(zip(dists, nbrs)):
                    src = idxs[row_i]
                    for dist_rad, col_j in zip(dist_row, nbr_row):
                        if col_j >= len(idxs):  # sentinel (beyond threshold)
                            continue
                        tgt = idxs[col_j]
                        if src == tgt:
                            continue
                        edge_key = (min(src, tgt), max(src, tgt))
                        if edge_key in adj_set or edge_key in prox_seen:
                            continue
                        prox_seen.add(edge_key)
                        length_km = dist_rad * 6371.0
                        if length_km < 0.1:
                            continue
                        R_pu, X_pu, B_pu = _pu_params(kv, length_km, sbase_mva)
                        if X_pu > MAX_PROX_X_PU:
                            continue   # skip high-impedance proximity links
                        y_mag = 1.0 / max((R_pu**2 + X_pu**2)**0.5, 1e-12)
                        if y_mag > MAX_ADMITTANCE_PU:
                            continue
                        lines.append(LineData(
                            from_bus=src,
                            to_bus=tgt,
                            R_pu=R_pu,
                            X_pu=X_pu,
                            B_pu=B_pu,
                            base_kv=float(kv),
                            length_km=length_km,
                        ))
        except ImportError:
            pass   # scipy not available; skip proximity step

        # ── Step 5: Bridge isolated components ────────────────────────────
        # Find all connected components; for each pair, add the shortest
        # inter-component edge (one per pair, per voltage class) so that
        # small isolated fragments join the main network.
        try:
            from scipy.spatial import cKDTree
            from scipy.sparse.csgraph import connected_components as _cc

            n_b = len(buses)
            id2idx2: Dict[int, int] = {b.id: i for i, b in enumerate(buses)}
            r2, c2, v2 = [], [], []
            for ln in lines:
                fi = id2idx2[ln.from_bus]; ti = id2idx2[ln.to_bus]
                r2 += [fi, ti]; c2 += [ti, fi]; v2 += [1, 1]
            if r2:
                adj2 = sp.coo_matrix((v2,(r2,c2)), shape=(n_b,n_b),dtype=int).tocsr()
            else:
                adj2 = sp.csr_matrix((n_b, n_b), dtype=int)
            _, comp_labels = _cc(adj2, directed=False)
            comp_sizes2 = np.bincount(comp_labels)

            # Only bridge components with ≥ 5 buses
            big_comps = [c for c in range(len(comp_sizes2)) if comp_sizes2[c] >= 5]
            BRIDGE_KM: Dict[int, float] = {500: 500.0, 275: 250.0, 154: 120.0}

            bridge_seen: set = set()
            for kv in [500, 275, 154]:
                kv_idxs_by_comp: Dict[int, List[int]] = {}
                for i, b in enumerate(buses):
                    if int(b.base_kv) == kv and comp_labels[i] in big_comps:
                        kv_idxs_by_comp.setdefault(comp_labels[i], []).append(i)
                comps_with_kv = [c for c in big_comps if c in kv_idxs_by_comp]
                if len(comps_with_kv) < 2:
                    continue
                max_km = BRIDGE_KM.get(kv, 150.0)
                ang_thresh = max_km / 6371.0
                # For each comp, find nearest bus in any other comp
                for ca in comps_with_kv:
                    ia = kv_idxs_by_comp[ca]
                    coords_a = np.array([[math.radians(buses[i].lat),
                                         math.radians(buses[i].lon)] for i in ia])
                    for cb in comps_with_kv:
                        if cb <= ca: continue
                        ib = kv_idxs_by_comp[cb]
                        coords_b = np.array([[math.radians(buses[i].lat),
                                              math.radians(buses[i].lon)] for i in ib])
                        tree_b = cKDTree(coords_b)
                        dists_ab, nbrs_ab = tree_b.query(coords_a, k=1)
                        best_row = int(np.argmin(dists_ab))
                        best_d = dists_ab[best_row]
                        if best_d > ang_thresh:
                            continue
                        src = ia[best_row]
                        tgt = ib[nbrs_ab[best_row]]
                        edge_key = (min(src,tgt), max(src,tgt))
                        if edge_key in bridge_seen:
                            continue
                        bridge_seen.add(edge_key)
                        length_km = best_d * 6371.0
                        R_pu, X_pu, B_pu = _pu_params(kv, length_km, sbase_mva)
                        if X_pu > 0.50:
                            continue  # too weak to be useful
                        lines.append(LineData(
                            from_bus=src, to_bus=tgt,
                            R_pu=R_pu, X_pu=X_pu, B_pu=B_pu,
                            base_kv=float(kv), length_km=length_km,
                        ))
        except ImportError:
            pass

        result = cls(buses, lines, sbase_mva)

        # ── Cache store ─────────────────────────────────────────────────
        if cache_dir is not None:
            try:
                with open(cache_path, "wb") as fh:
                    pickle.dump(result, fh)
            except Exception:
                pass

        return result

    # ------------------------------------------------------------------
    # Representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"GridNetwork(nb={self.nb}, lines={len(self._lines)}, "
            f"sbase={self.sbase_mva} MVA)"
        )


# ---------------------------------------------------------------------------
# Generator assignment
# ---------------------------------------------------------------------------

def assign_generators(
    grid: GridNetwork,
    plants_data_dir: str,
    base_mva: float = 100.0,
    match_threshold_km: float = GEN_MATCH_KM,
    wri_csv: Optional[str] = None,
) -> List[Tuple[int, str, float, str]]:
    """Match generating plants to network buses by geographic proximity.

    Uses two sources (merged, de-duplicated by proximity):
    1. ``{region}_plants.geojson`` – OSM-based regional data
    2. WRI Global Power Plant Database CSV (if *wri_csv* is given or
       ``{plants_data_dir}/wri_global_power_plants.csv`` exists)

    WRI data takes precedence for large plants (capacity_mw ≥ 100) because
    its capacity values are more authoritative than OSM defaults.
    """
    # Valid fuel names (normalised to lowercase)
    FUEL_MAP: Dict[str, str] = {
        "gas": "gas", "lng": "gas", "ng": "gas",
        "coal": "coal", "thermal": "thermal",
        "oil": "oil", "petroleum": "oil",
        "nuclear": "nuclear",
        "hydro": "hydro", "water": "hydro",
        "pumped storage": "pumped", "pumped": "pumped",
        "geothermal": "geothermal",
        "biomass": "biomass", "biogas": "biomass",
        "waste": "waste", "refuse": "waste",
        "wind": "wind",
        "solar": "solar", "photovoltaic": "solar",
        "storage": "storage", "battery": "storage",
    }
    # Fuels to skip for transmission-level model
    # (small distributed solar/wind connect at distribution, not 154+ kV)
    SKIP_FUELS_SMALL: set = {"solar", "storage", "unknown", "other"}
    MIN_CAP_BY_FUEL: Dict[str, float] = {
        "nuclear": 100.0, "coal": 50.0, "gas": 50.0, "oil": 50.0,
        "thermal": 50.0, "hydro": 30.0, "pumped": 30.0,
        "geothermal": 10.0, "biomass": 10.0, "waste": 10.0,
        "wind": 50.0, "solar": 100.0,
    }

    CAP_DEFAULT: Dict[str, float] = {
        "nuclear": 1100.0, "coal": 700.0, "gas": 500.0,
        "thermal": 500.0, "oil": 400.0, "hydro": 200.0,
        "pumped": 400.0, "geothermal": 50.0,
        "biomass": 100.0, "waste": 30.0, "wind": 80.0, "solar": 50.0,
    }

    def _norm_fuel(raw: str) -> str:
        s = str(raw).lower().strip()
        for key, val in FUEL_MAP.items():
            if key in s:
                return val
        return "unknown"

    # ── collect raw plant list ─────────────────────────────────────────────
    raw_plants: List[Tuple[float, float, str, float, str]] = []  # (lon, lat, fuel, cap, name)

    # 1. OSM GeoJSON
    for region in REGIONS:
        plant_path = os.path.join(plants_data_dir, f"{region}_plants.geojson")
        if not os.path.exists(plant_path):
            continue
        with open(plant_path, encoding="utf-8") as fh:
            gj = json.load(fh)
        for feat in gj.get("features", []):
            props = feat.get("properties", {})
            fuel = _norm_fuel(props.get("fuel_type") or "unknown")
            if fuel in ("unknown", "other"):
                continue
            cap_raw = props.get("capacity_mw")
            try:
                cap = float(cap_raw)
                if cap != cap or cap <= 0:
                    cap = CAP_DEFAULT.get(fuel, 100.0)
            except (TypeError, ValueError):
                cap = CAP_DEFAULT.get(fuel, 100.0)
            geom = feat.get("geometry")
            if geom is None:
                continue
            pos = _geom_centroid(geom)
            if pos is None:
                continue
            name = str(props.get("name") or props.get("_display_name") or f"{region}_{fuel}")
            raw_plants.append((pos[0], pos[1], fuel, cap, name))

    # 2. WRI CSV (higher-quality capacity data for large plants)
    _wri_path = wri_csv or os.path.join(plants_data_dir, "wri_global_power_plants.csv")
    if os.path.exists(_wri_path):
        try:
            import csv
            with open(_wri_path, encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    if row.get("country", "").upper() != "JPN":
                        continue
                    fuel = _norm_fuel(row.get("primary_fuel", "unknown"))
                    try:
                        cap = float(row.get("capacity_mw", 0) or 0)
                    except ValueError:
                        continue
                    if cap <= 0:
                        continue
                    try:
                        lat = float(row.get("latitude", 0) or 0)
                        lon = float(row.get("longitude", 0) or 0)
                    except ValueError:
                        continue
                    if lat == 0 and lon == 0:
                        continue
                    name = str(row.get("name") or f"WRI_{fuel}")
                    raw_plants.append((lon, lat, fuel, cap, name))
        except Exception:
            pass

    # ── match plants to buses (de-duplicate by bus: keep max-cap per bus) ──
    # First filter by min capacity
    filtered: List[Tuple[float, float, str, float, str]] = []
    for lon, lat, fuel, cap, name in raw_plants:
        min_cap = MIN_CAP_BY_FUEL.get(fuel, 30.0)
        if cap < min_cap:
            continue
        if fuel in SKIP_FUELS_SMALL and cap < 100.0:
            continue
        filtered.append((lon, lat, fuel, cap, name))

    # Build KDTree over buses for fast lookup
    bus_lons = [b.lon for b in grid.buses]
    bus_lats = [b.lat for b in grid.buses]
    try:
        from scipy.spatial import cKDTree
        bus_coords = np.array([[math.radians(la), math.radians(lo)]
                               for la, lo in zip(bus_lats, bus_lons)])
        bus_tree = cKDTree(bus_coords)
        ang_thresh = match_threshold_km / 6371.0
        use_tree = True
    except ImportError:
        use_tree = False

    # bus_idx → (fuel, cap, name): best match per bus
    bus_best: Dict[int, Tuple[str, float, str]] = {}
    for lon, lat, fuel, cap, name in filtered:
        if use_tree:
            d, idx = bus_tree.query([math.radians(lat), math.radians(lon)], k=1)
            if d > ang_thresh:
                continue
            bus_id = grid.buses[idx].id
        else:
            best_id: Optional[int] = None
            best_d: float = math.inf
            for b in grid.buses:
                d = _haversine_km(lon, lat, b.lon, b.lat)
                if d < best_d:
                    best_d = d; best_id = b.id
            if best_id is None or best_d > match_threshold_km:
                continue
            bus_id = best_id

        if bus_id not in bus_best or cap > bus_best[bus_id][1]:
            bus_best[bus_id] = (fuel, cap, name)

    return [(bid, fuel, cap, name) for bid, (fuel, cap, name) in bus_best.items()]
