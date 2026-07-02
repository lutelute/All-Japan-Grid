"""Node-breaker data model for substation internal structure (GridStitch P2).

Implements the owner directive (2026-07-02): lines terminate at substations,
and the substation is where voltage levels, transformers (taps), circuits and
conductors are joined — because loads are served from there. Connections must
be first-class data (persisted, with provenance), not per-build geometric
re-inference.

CIM alignment (IEC 61970 / CGMES):

    SubstationSite   -> cim:Substation        (site polygon = container)
    VoltageLevel     -> cim:VoltageLevel      (+ cim:BaseVoltage)
    BusbarSection    -> cim:BusbarSection     (collector bus per voltage level)
    Bay              -> cim:Bay               (feeder/equipment bay)
    Terminal         -> cim:Terminal          (line end bound to structure)
    TransformerSpec  -> cim:PowerTransformer  (+ ends, + RatioTapChanger)

Two views over the same objects: this node-breaker layer is faithful and
auditable; the bus-branch view (current builder output, ``{sid}@{kv}`` buses
+ transformer stubs) is derived from it by collapsing each VoltageLevel to
one bus. Nothing here fabricates connections: every Terminal carries the
evidence (``binding``) and provenance (``source``) for why it is attached.

Fabrication rules (project invariants):
    - Unknown voltage stays 0 (never guessed into ``nominal_kv``); an
      inferred value may be carried separately in ``inferred_kv`` with its
      derivation recorded in ``kv_source``.
    - Transformer electrical data (rating, impedance, taps) is only stored
      with an explicit ``source``; synthetic class-typical values remain the
      responsibility of the powerflow layer (``transforms._TRAFO_PARAMS``)
      and are never written into the model as if they were data.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SubstationSite:
    """Physical substation site (cim:Substation).

    One site per real-world substation. Region-boundary duplicates (the same
    physical substation ingested by two regional extracts) must resolve to a
    single site; secondary appearances are recorded in ``aliases``.
    """

    site_id: str                      # canonical id, e.g. "kansai_sub_123"
    name: str
    region: str                       # primary region (owner of the record)
    operator: Optional[str] = None
    substation_type: Optional[str] = None   # OSM substation=* (transmission/...)
    osm_keys: list = field(default_factory=list)   # geometry keys / osm ids
    aliases: list = field(default_factory=list)    # duplicate ids in other regions
    lat: Optional[float] = None       # representative point (polygon centroid)
    lon: Optional[float] = None
    source: str = "osm"


@dataclass
class VoltageLevel:
    """One voltage class inside a substation (cim:VoltageLevel).

    ``nominal_kv == 0`` means the level exists but its voltage is untagged
    in OSM. In that case ``inferred_kv``/``kv_source`` may carry a derived
    value (e.g. from adjacent bay voltage) for the computation layer, while
    the model honestly keeps the tag absence visible.
    """

    vl_id: str                        # "{site_id}@{kv}" or "{site_id}@u"
    site_id: str
    nominal_kv: float                 # 0.0 = untagged
    kv_source: str = "tag"            # tag | prop | bay-adjacency | unknown
    inferred_kv: Optional[float] = None


@dataclass
class BusbarSection:
    """Collector busbar of a voltage level (cim:BusbarSection).

    Aggregates the OSM ``line=busbar`` ways that are vertex-connected into
    one electrical node. An untagged busbar may be assigned to a voltage
    level by adjacency derivation (owner rule: "trace voltage from what it
    connects to — connection, not guessing"); in that case ``kv_inferred``
    holds the derived value and ``kv_evidence`` the observed adjacency
    counts, while the absence of an OSM tag stays visible.
    """

    busbar_id: str                    # "{vl_id}/bb{n}"
    vl_id: str
    osm_way_keys: list = field(default_factory=list)
    name: Optional[str] = None
    kv_inferred: Optional[float] = None   # set when vl assignment is derived
    kv_evidence: Optional[str] = None     # e.g. "bay:275x10,bay:500x1"


@dataclass
class Bay:
    """Feeder/equipment bay (cim:Bay).

    A vertex-connected group of OSM ``line=bay`` ways. ``busbar_ids`` lists
    the busbar sections this bay touches (shared vertices); a bay bridging
    two busbar sections of the same voltage level is a coupler candidate.
    """

    bay_id: str                       # "{vl_id}/bay{n}"
    vl_id: str
    osm_way_keys: list = field(default_factory=list)
    busbar_ids: list = field(default_factory=list)


@dataclass
class Terminal:
    """A transmission-line end bound to substation structure (cim:Terminal).

    This is the first-class record of "why this line is connected here".
    ``attach_id`` points at the most specific structure known (Bay, else
    BusbarSection, else VoltageLevel).

    Binding evidence vocabulary (ordered, strongest first):
        vertex-shared   line end shares an OSM vertex with bay/busbar
        polygon         line end lies inside the site polygon
        leadin          line end within lead-in band of the polygon
        name-evidence   line name asserts this substation ("A~B線")
        manual          human edit via GridStitch editor
    """

    terminal_id: str                  # "{site_id}/t{n}"
    site_id: str
    vl_id: str
    attach_kind: str                  # bay | busbar | voltage_level
    attach_id: str
    line_key: str                     # stable key of the external line
    line_name: Optional[str] = None
    circuit_ref: Optional[str] = None # circuit identity (OSM ref / 1号線|2号線)
    par: int = 1                      # parallel circuits carried by this end
    par_source: Optional[str] = None  # tag | cables | None(=geometric 1)
    binding: str = "polygon"
    confidence: float = 1.0
    source: str = "osm"


@dataclass
class TransformerSpec:
    """Transformer joining two voltage levels of a site (cim:PowerTransformer).

    HV/LV assignment is derived deterministically from voltage class order
    (no primary/secondary tag exists in OSM). Electrical data (``sn_mva``,
    impedances, tap fields) must carry ``source`` when set; ``source ==
    "structural"`` means only the existence/ends are asserted (the powerflow
    layer will use class-typical synthetic parameters as before).
    """

    trafo_id: str                     # "{site_id}/tr{n}"
    site_id: str
    hv_vl_id: str                     # end 1 (higher voltage class)
    lv_vl_id: str                     # end 2
    n_parallel: int = 1               # bank count
    sn_mva: Optional[float] = None
    # Ratio tap changer (schema mirrors db substation_attributes tap_*):
    tap_neutral: Optional[float] = None
    tap_min: Optional[float] = None
    tap_max: Optional[float] = None
    tap_step_percent: Optional[float] = None
    source: str = "structural"        # structural | nameplate(+url in note)
    note: Optional[str] = None


@dataclass
class SubstationStructure:
    """Complete node-breaker structure of one substation site."""

    site: SubstationSite
    voltage_levels: list = field(default_factory=list)
    busbars: list = field(default_factory=list)
    bays: list = field(default_factory=list)
    terminals: list = field(default_factory=list)
    transformers: list = field(default_factory=list)

    def summary(self) -> dict:
        """Compact counts for logs and A/B comparison."""
        return {
            "site": self.site.site_id,
            "name": self.site.name,
            "voltage_levels": [vl.nominal_kv for vl in self.voltage_levels],
            "n_busbars": len(self.busbars),
            "n_bays": len(self.bays),
            "n_terminals": len(self.terminals),
            "n_transformers": len(self.transformers),
        }
