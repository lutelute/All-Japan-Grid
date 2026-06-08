"""Level-2 CIM/CGMES export: a solved pandapower network -> CGMES power-flow case.

Converts a fully-connected pandapower network (buses, lines, transformers,
loads, generators, ext_grid; with ``res_bus`` for the solved state) into the
five CGMES profiles needed for a power-flow exchange:

  * EQ  (Equipment)             — Substation/VoltageLevel/Line containers,
                                  ConnectivityNode, ACLineSegment, PowerTransformer
                                  (+End), EnergyConsumer, SynchronousMachine
                                  (+GeneratingUnit), ExternalNetworkInjection,
                                  Terminal, BaseVoltage
  * TP  (Topology)              — TopologicalNode, ConnectivityNode->TN binding
  * SSH (SteadyStateHypothesis) — EnergyConsumer.p/q, RotatingMachine.p/q,
                                  Terminal.connected
  * SV  (StateVariables)        — SvVoltage per TopologicalNode (from res_bus)
  * GL  (Geographical Location) — VoltageLevel coordinates (from bus.geo)

Unlike the Level-1 catalogue export, lines/transformers are joined at **shared**
ConnectivityNodes, so the result round-trips through pandapower ``cim2pp`` and is
power-flow solvable.
"""

from __future__ import annotations

import json
import math
import os
from typing import Dict, Optional

from ..regions import REGION_EN as REGION_NAME
from .core import PROFILE_EQ, PROFILE_GL, RdfWriter, base_voltage_mrid, mrid

PROFILE_TP = "http://entsoe.eu/CIM/Topology/4/1"
PROFILE_SSH = "http://entsoe.eu/CIM/SteadyStateHypothesis/1/1"
PROFILE_SV = "http://entsoe.eu/CIM/StateVariables/4/1"


def _num(value, default=0.0) -> float:
    """Coerce a possibly-NaN/None pandas value to a finite float."""
    try:
        f = float(value)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def _parallel(row) -> int:
    """Number of parallel circuits/banks for a line/trafo row (>= 1).

    pandapower divides branch impedance (and multiplies shunt admittance
    and rating) by this column; the CGMES export must bake the same
    factor into the single exported equipment, otherwise the round-trip
    network carries n-times the impedance (REVIEW_FINDINGS P0 #1).
    """
    return max(int(_num(row.get("parallel"), 1) or 1), 1)


def _in_service(row) -> bool:
    """Element in_service flag with NaN/None treated as True."""
    val = row.get("in_service", True)
    try:
        return bool(val) and not (isinstance(val, float) and math.isnan(val))
    except TypeError:
        return True


class Level2Exporter:
    """Builds CGMES EQ/TP/SSH/SV/GL from a solved pandapower network."""

    def __init__(self, net, region: str, f_hz: Optional[float] = None) -> None:
        """Initialise writers and shared containers for ``region``."""
        self.net = net
        self.region = region
        self.f_hz = float(f_hz if f_hz is not None else getattr(net, "f_hz", 50.0))
        self.eq = RdfWriter(PROFILE_EQ, mrid("l2model", "eq", region)).header()
        self.tp = RdfWriter(PROFILE_TP, mrid("l2model", "tp", region)).header()
        self.ssh = RdfWriter(PROFILE_SSH, mrid("l2model", "ssh", region)).header()
        self.sv = RdfWriter(PROFILE_SV, mrid("l2model", "sv", region)).header()
        self.gl = RdfWriter(PROFILE_GL, mrid("l2model", "gl", region)).header()
        self._used_voltages: set = set()
        self._cs_m: Optional[str] = None
        self._bus_cn: Dict[int, str] = {}
        self._bus_tn: Dict[int, str] = {}
        self._bus_on: Dict[int, bool] = {}
        # shared containers
        self._sub_geo = mrid("l2subgeo", region)
        geo = mrid("l2geo", "japan")
        self.eq.obj("GeographicalRegion", geo,
                    attrs={"IdentifiedObject.name": "Japan", "IdentifiedObject.mRID": geo})
        self.eq.obj("SubGeographicalRegion", self._sub_geo,
                    attrs={"IdentifiedObject.name": REGION_NAME.get(region, region),
                           "IdentifiedObject.mRID": self._sub_geo},
                    refs={"SubGeographicalRegion.Region": geo})
        self._substation = mrid("l2sub", region)
        self.eq.obj("Substation", self._substation,
                    attrs={"IdentifiedObject.name": f"{REGION_NAME.get(region, region)} grid",
                           "IdentifiedObject.mRID": self._substation},
                    refs={"Substation.Region": self._sub_geo})
        self._line_container = mrid("l2linec", region)
        self.eq.obj("Line", self._line_container,
                    attrs={"IdentifiedObject.name": f"{region} lines",
                           "IdentifiedObject.mRID": self._line_container},
                    refs={"Line.Region": self._sub_geo})

    # -- shared objects -----------------------------------------------------
    def _base_voltage(self, kv: float) -> str:
        """Return the BaseVoltage mRID for ``kv`` (defined in the EQ_BD boundary).

        The BaseVoltage objects live in the shared boundary file (see
        :mod:`src.cim.boundary`); here we record the voltage and return its
        deterministic mRID so EQ references resolve against the boundary.
        """
        key = round(float(kv), 3)
        self._used_voltages.add(key)
        return base_voltage_mrid(key)

    def _coordinate_system(self) -> str:
        if self._cs_m:
            return self._cs_m
        self._cs_m = mrid("l2cs", "wgs84")
        self.gl.obj("CoordinateSystem", self._cs_m,
                    attrs={"IdentifiedObject.name": "WGS84",
                           "IdentifiedObject.mRID": self._cs_m,
                           "CoordinateSystem.crsUrn": "urn:ogc:def:crs:EPSG::4326"})
        return self._cs_m

    def _location(self, psr_m: str, lon: float, lat: float) -> None:
        loc = mrid("l2loc", psr_m)
        self.gl.obj("Location", loc,
                    attrs={"IdentifiedObject.mRID": loc},
                    refs={"Location.CoordinateSystem": self._coordinate_system(),
                          "Location.PowerSystemResources": psr_m})
        pp = mrid("l2pp", psr_m)
        self.gl.obj("PositionPoint", pp,
                    attrs={"PositionPoint.sequenceNumber": 1,
                           "PositionPoint.xPosition": f"{lon:.6f}",
                           "PositionPoint.yPosition": f"{lat:.6f}"},
                    refs={"PositionPoint.Location": loc})

    # -- builders -----------------------------------------------------------
    def build(self) -> None:
        """Emit all five profiles in dependency order."""
        self._buses()
        self._lines()
        self._transformers()
        self._loads()
        self._generators()
        self._sgens()
        self._ext_grids()
        self._topological_island()

    def _buses(self) -> None:
        net = self.net
        res = getattr(net, "res_bus", None)
        for idx in net.bus.index:
            row = net.bus.loc[idx]
            vn = _num(row.vn_kv, 1.0)
            bv = self._base_voltage(vn)
            vl = mrid("l2vl", self.region, idx)
            self.eq.obj("VoltageLevel", vl,
                        attrs={"IdentifiedObject.name": str(row.get("name", f"bus{idx}")),
                               "IdentifiedObject.mRID": vl},
                        refs={"VoltageLevel.Substation": self._substation,
                              "VoltageLevel.BaseVoltage": bv})
            cn = mrid("l2cn", self.region, idx)
            self.eq.obj("ConnectivityNode", cn,
                        attrs={"IdentifiedObject.mRID": cn},
                        refs={"ConnectivityNode.ConnectivityNodeContainer": vl})
            tn = mrid("l2tn", self.region, idx)
            self.tp.obj("TopologicalNode", tn,
                        attrs={"IdentifiedObject.name": str(row.get("name", f"bus{idx}")),
                               "IdentifiedObject.mRID": tn},
                        refs={"TopologicalNode.BaseVoltage": bv,
                              "TopologicalNode.ConnectivityNodeContainer": vl})
            self.tp.obj("ConnectivityNode", cn,
                        refs={"ConnectivityNode.TopologicalNode": tn})
            self._bus_cn[idx] = cn
            self._bus_tn[idx] = tn
            self._bus_on[idx] = _in_service(row)
            # geo on the VoltageLevel
            geo = row.get("geo", None)
            if isinstance(geo, str) and geo:
                try:
                    c = json.loads(geo)["coordinates"]
                    self._location(vl, float(c[0]), float(c[1]))
                except (ValueError, KeyError, TypeError):
                    pass
            # SV voltage
            if res is not None and idx in res.index:
                vm = _num(res.at[idx, "vm_pu"], float("nan"))
                if math.isfinite(vm):
                    svm = mrid("l2sv", self.region, idx)
                    self.sv.obj("SvVoltage", svm,
                                attrs={"SvVoltage.v": round(vm * vn, 4),
                                       "SvVoltage.angle": round(_num(res.at[idx, "va_degree"]), 4)},
                                refs={"SvVoltage.TopologicalNode": tn})

    def _terminal(self, eqm: str, kind: str, idx: int, seq: int, bus: int,
                  connected: bool = True) -> str:
        t = mrid("l2term", self.region, kind, idx, seq)
        self.eq.obj("Terminal", t,
                    attrs={"IdentifiedObject.mRID": t, "ACDCTerminal.sequenceNumber": seq},
                    refs={"Terminal.ConductingEquipment": eqm,
                          "Terminal.ConnectivityNode": self._bus_cn[bus]})
        # Element AND bus in_service must both hold; otherwise the round-trip
        # re-energizes equipment the solved element net had switched off
        # (pruned lines, disabled-island loads — REVIEW_FINDINGS P0 #2).
        on = bool(connected) and self._bus_on.get(bus, True)
        self.ssh.obj("Terminal", t,
                     attrs={"ACDCTerminal.connected": "true" if on else "false"})
        return t

    def _reg_control(self, rc: str, term_m: str, target_kv: float, tag: str) -> None:
        """Emit a voltage RegulatingControl (EQ mode/Terminal + SSH enabled/target).

        cim2pp treats a RegulatingCondEq as controllable when it points to a
        voltage RegulatingControl whose ``enabled`` is true and whose owner's
        ``controlEnabled`` is true — that turns SynchronousMachine into a PV
        gen and ExternalNetworkInjection into the slack.
        """
        self.eq.obj("RegulatingControl", rc,
                    attrs={"IdentifiedObject.mRID": rc, "IdentifiedObject.name": f"rc_{tag}"},
                    refs={"RegulatingControl.Terminal": term_m},
                    enums={"RegulatingControl.mode": "RegulatingControlModeKind.voltage"})
        self.ssh.obj("RegulatingControl", rc,
                     attrs={"RegulatingControl.enabled": "true",
                            "RegulatingControl.targetValue": target_kv})

    def _lines(self) -> None:
        net = self.net
        for idx in net.line.index:
            row = net.line.loc[idx]
            length = _num(row.length_km, 0.0)
            par = _parallel(row)
            # Effective branch values of the parallel bundle, matching what
            # pandapower solves: series Z / n, shunt Y * n.
            r = _num(row.r_ohm_per_km) * length / par
            x = _num(row.x_ohm_per_km) * length / par
            bch = 2 * math.pi * self.f_hz * _num(row.c_nf_per_km) * 1e-9 * length * par
            gch = _num(row.get("g_us_per_km", 0.0)) * 1e-6 * length * par
            from_bus, to_bus = int(row.from_bus), int(row.to_bus)
            in_svc = _in_service(row)
            bv = self._base_voltage(_num(net.bus.at[from_bus, "vn_kv"], 1.0))
            m = mrid("l2line", self.region, idx)
            self.eq.obj("ACLineSegment", m,
                        attrs={"IdentifiedObject.name": str(row.get("name", f"line{idx}")),
                               "IdentifiedObject.mRID": m,
                               # km: the CGMES EQ profile encodes Conductor.length
                               # with unitMultiplier=k, and cim2pp reads km —
                               # the old m value round-tripped 1000x too long
                               # (REVIEW_FINDINGS P0 #8).
                               "Conductor.length": round(length, 3),
                               "ACLineSegment.r": round(r, 6),
                               "ACLineSegment.x": round(x, 6),
                               "ACLineSegment.bch": round(bch, 10),
                               "ACLineSegment.gch": round(gch, 10)},
                        refs={"Equipment.EquipmentContainer": self._line_container,
                              "ConductingEquipment.BaseVoltage": bv})
            self._terminal(m, "line", idx, 1, from_bus, connected=in_svc)
            self._terminal(m, "line", idx, 2, to_bus, connected=in_svc)

    def _transformers(self) -> None:
        net = self.net
        if not hasattr(net, "trafo"):
            return
        for idx in net.trafo.index:
            row = net.trafo.loc[idx]
            par = _parallel(row)
            # Export the bank as ONE transformer with the combined rating;
            # vk/vkr% are per-unit on the unit's own base, so computing the
            # ohmic impedance on the combined base sn_total = sn * n yields
            # exactly z_single / n — what pandapower solves for parallel=n
            # (REVIEW_FINDINGS P0 #1).
            sn = (_num(row.sn_mva, 1.0) or 1.0) * par
            vhv, vlv = _num(row.vn_hv_kv, 1.0), _num(row.vn_lv_kv, 1.0)
            zbase = (vlv * vlv) / sn if sn else 0.0
            zk = _num(row.vk_percent) / 100.0 * zbase
            rk = _num(row.vkr_percent) / 100.0 * zbase
            xk = math.sqrt(max(zk * zk - rk * rk, 0.0))
            # Magnetizing admittance referred to the HV end (siemens), kept
            # strictly non-zero so cim2pp's 1/(g+jb) star conversion stays finite.
            # pfe_kw is per unit -> n units; i0% holds on the combined base
            # because sn here is already the bank total.
            pfe = _num(row.get("pfe_kw")) * par
            i0 = _num(row.get("i0_percent"))
            g_mag = (pfe / 1000.0) / (vhv * vhv) if vhv else 0.0
            y_mag = (i0 / 100.0) * (sn / (vhv * vhv)) if vhv else 0.0
            b_mag = -math.sqrt(max(y_mag * y_mag - g_mag * g_mag, 0.0))
            if g_mag == 0.0 and b_mag == 0.0:
                b_mag = -1e-7
            in_svc = _in_service(row)
            m = mrid("l2trafo", self.region, idx)
            self.eq.obj("PowerTransformer", m,
                        attrs={"IdentifiedObject.name": str(row.get("name", f"trafo{idx}")),
                               "IdentifiedObject.mRID": m},
                        refs={"Equipment.EquipmentContainer": self._substation})
            # end 1 = HV (carries magnetizing g/b), end 2 = LV (carries r,x)
            ends = [(1, int(row.hv_bus), vhv, 0.0, 0.0, g_mag, b_mag),
                    (2, int(row.lv_bus), vlv, rk, xk, 0.0, 0.0)]
            for end, bus, vn, r, x, g, b in ends:
                pte = mrid("l2pte", self.region, idx, end)
                t = mrid("l2term", self.region, "trafo", idx, end)
                self.eq.obj("PowerTransformerEnd", pte,
                            attrs={"IdentifiedObject.mRID": pte,
                                   "TransformerEnd.endNumber": end,
                                   "PowerTransformerEnd.r": round(r, 6),
                                   "PowerTransformerEnd.x": round(x, 6),
                                   "PowerTransformerEnd.g": round(g, 10),
                                   "PowerTransformerEnd.b": round(b, 10),
                                   "PowerTransformerEnd.ratedU": vn,
                                   "PowerTransformerEnd.ratedS": sn},
                            refs={"PowerTransformerEnd.PowerTransformer": m,
                                  "TransformerEnd.BaseVoltage": self._base_voltage(vn),
                                  "TransformerEnd.Terminal": t})
                self.eq.obj("Terminal", t,
                            attrs={"IdentifiedObject.mRID": t,
                                   "ACDCTerminal.sequenceNumber": end},
                            refs={"Terminal.ConductingEquipment": m,
                                  "Terminal.ConnectivityNode": self._bus_cn[bus]})
                on = in_svc and self._bus_on.get(bus, True)
                self.ssh.obj("Terminal", t,
                             attrs={"ACDCTerminal.connected": "true" if on else "false"})

    def _loads(self) -> None:
        net = self.net
        if not hasattr(net, "load"):
            return
        for idx in net.load.index:
            row = net.load.loc[idx]
            bus = int(row.bus)
            m = mrid("l2load", self.region, idx)
            self.eq.obj("EnergyConsumer", m,
                        attrs={"IdentifiedObject.name": str(row.get("name", f"load{idx}")),
                               "IdentifiedObject.mRID": m},
                        refs={"Equipment.EquipmentContainer": mrid("l2vl", self.region, bus)})
            self._terminal(m, "load", idx, 1, bus, connected=_in_service(row))
            self.ssh.obj("EnergyConsumer", m,
                         attrs={"EnergyConsumer.p": round(_num(row.p_mw), 4),
                                "EnergyConsumer.q": round(_num(row.q_mvar), 4)})

    def _machine(self, kind: str, idx: int, bus: int, name: str,
                 p_mw: float, q_mvar: float, rateds: float,
                 minp: float, maxp: float,
                 voltage_control: bool = False, vm_pu: float = 1.0,
                 connected: bool = True) -> None:
        """Emit a GeneratingUnit + SynchronousMachine pair with SSH injection.

        When ``voltage_control`` is set, a voltage RegulatingControl is attached
        so cim2pp imports it as a PV generator (``gen``); otherwise it becomes a
        PQ static generator (``sgen``).
        """
        gu = mrid("l2gu", self.region, kind, idx)
        sm = mrid("l2sm", self.region, kind, idx)
        vn = _num(self.net.bus.at[bus, "vn_kv"], 1.0)
        bv = self._base_voltage(vn)
        rc = mrid("l2rc", self.region, kind, idx) if voltage_control else None
        self.eq.obj("GeneratingUnit", gu,
                    attrs={"IdentifiedObject.name": name,
                           "IdentifiedObject.mRID": gu,
                           "GeneratingUnit.minOperatingP": round(minp, 4),
                           "GeneratingUnit.maxOperatingP": round(maxp, 4)})
        sm_refs = {"RotatingMachine.GeneratingUnit": gu,
                   "ConductingEquipment.BaseVoltage": bv,
                   "Equipment.EquipmentContainer": mrid("l2vl", self.region, bus)}
        if rc:
            sm_refs["RegulatingCondEq.RegulatingControl"] = rc
        self.eq.obj("SynchronousMachine", sm,
                    attrs={"IdentifiedObject.name": name,
                           "IdentifiedObject.mRID": sm,
                           "RotatingMachine.ratedS": round(rateds, 4)},
                    refs=sm_refs)
        term = self._terminal(sm, kind, idx, 1, bus, connected=connected)
        # CGMES load convention: generation is negative injected power.
        ssh_attrs = {"RotatingMachine.p": round(-p_mw, 4),
                     "RotatingMachine.q": round(-q_mvar, 4)}
        if rc:
            ssh_attrs["RegulatingCondEq.controlEnabled"] = "true"
        self.ssh.obj("SynchronousMachine", sm, attrs=ssh_attrs)
        if rc:
            self._reg_control(rc, term, round(vm_pu * vn, 4), f"{kind}{idx}")

    def _generators(self) -> None:
        net = self.net
        if not hasattr(net, "gen"):
            return
        for idx in net.gen.index:
            row = net.gen.loc[idx]
            p = _num(row.p_mw)
            self._machine("gen", idx, int(row.bus), str(row.get("name", f"gen{idx}")),
                          p, 0.0, _num(row.get("sn_mva"), p) or p,
                          _num(row.get("min_p_mw")), _num(row.get("max_p_mw"), p),
                          voltage_control=True, vm_pu=_num(row.get("vm_pu"), 1.0),
                          connected=_in_service(row))

    def _sgens(self) -> None:
        net = self.net
        if not hasattr(net, "sgen"):
            return
        for idx in net.sgen.index:
            row = net.sgen.loc[idx]
            p = _num(row.p_mw)
            self._machine("sgen", idx, int(row.bus), str(row.get("name", f"sgen{idx}")),
                          p, _num(row.get("q_mvar")), _num(row.get("sn_mva"), p) or p,
                          0.0, p, connected=_in_service(row))

    def _ext_grids(self) -> None:
        net = self.net
        if not hasattr(net, "ext_grid"):
            return
        for idx in net.ext_grid.index:
            row = net.ext_grid.loc[idx]
            bus = int(row.bus)
            vn = _num(net.bus.at[bus, "vn_kv"], 1.0)
            m = mrid("l2ext", self.region, idx)
            bv = self._base_voltage(vn)
            rc = mrid("l2rcext", self.region, idx)
            self.eq.obj("ExternalNetworkInjection", m,
                        attrs={"IdentifiedObject.name": str(row.get("name", f"ext{idx}")),
                               "IdentifiedObject.mRID": m},
                        refs={"ConductingEquipment.BaseVoltage": bv,
                              "Equipment.EquipmentContainer": mrid("l2vl", self.region, bus),
                              "RegulatingCondEq.RegulatingControl": rc})
            term = self._terminal(m, "ext", idx, 1, bus, connected=_in_service(row))
            # referencePriority>0 + controllable -> cim2pp selects this as the slack
            self.ssh.obj("ExternalNetworkInjection", m,
                         attrs={"ExternalNetworkInjection.p": 0.0,
                                "ExternalNetworkInjection.q": 0.0,
                                "ExternalNetworkInjection.referencePriority": 1,
                                "RegulatingCondEq.controlEnabled": "true"})
            self._reg_control(rc, term, round(_num(row.get("vm_pu"), 1.0) * vn, 4), f"ext{idx}")

    def _topological_island(self) -> None:
        """Emit an SV TopologicalIsland fixing the slack (angle-reference) node."""
        net = self.net
        if len(net.bus) == 0:
            return
        if hasattr(net, "ext_grid") and len(net.ext_grid):
            slack_bus = int(net.ext_grid.bus.iloc[0])
        else:
            slack_bus = int(net.bus.index[0])
        isl = mrid("l2island", self.region)
        tns = [self._bus_tn[i] for i in net.bus.index if i in self._bus_tn]
        self.sv.obj("TopologicalIsland", isl,
                    attrs={"IdentifiedObject.name": self.region,
                           "IdentifiedObject.mRID": isl},
                    refs={"TopologicalIsland.AngleRefTopologicalNode": self._bus_tn.get(slack_bus),
                          "TopologicalIsland.TopologicalNodes": tns})

    def write(self, out_dir: str) -> dict:
        """Write the five profile files and return a summary dict."""
        os.makedirs(out_dir, exist_ok=True)
        files = {}
        for prof, writer in [("EQ", self.eq), ("TP", self.tp), ("SSH", self.ssh),
                             ("SV", self.sv), ("GL", self.gl)]:
            path = os.path.join(out_dir, f"{self.region}_L2_{prof}.xml")
            writer.write(path)
            files[prof] = (os.path.basename(path), writer.object_count)
        return {"region": self.region, "files": files,
                "buses": len(self.net.bus), "lines": len(self.net.line),
                "trafos": len(getattr(self.net, "trafo", [])),
                "loads": len(getattr(self.net, "load", [])),
                "gens": len(getattr(self.net, "gen", [])) + len(getattr(self.net, "sgen", [])),
                "base_voltages": sorted(self._used_voltages, reverse=True)}


def net_to_cgmes(net, region: str, out_dir: str, f_hz: Optional[float] = None) -> dict:
    """Convenience wrapper: build and write all CGMES profiles for ``net``."""
    exporter = Level2Exporter(net, region, f_hz=f_hz)
    exporter.build()
    return exporter.write(out_dir)
