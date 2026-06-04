"""CGMES boundary set (EQ_BD + TP_BD): shared BaseVoltage definitions.

CGMES tooling (PowerFactory, CIMverter, ENTSO-E exchanges, ...) expects the EQ
and TP profiles to *reference* BaseVoltage objects defined in a shared
**boundary set**, rather than each file redefining them. This module emits that
boundary set so the All-Japan-Grid CGMES files interoperate cleanly.

The Level-2 EQ references these BaseVoltages by their deterministic mRID
(:func:`src.cim.core.base_voltage_mrid`), so the boundary and the equipment
files always agree on identity.
"""

from __future__ import annotations

import os
from typing import Iterable, Optional

from .core import RdfWriter, base_voltage_mrid, mrid

PROFILE_EQ_BD = "http://entsoe.eu/CIM/EquipmentBoundary/3/1"
PROFILE_TP_BD = "http://entsoe.eu/CIM/TopologyBoundary/3/1"

# Japanese transmission + common sub-transmission nominal voltages (kV). Used as
# the default when no measured voltage set is supplied.
BOUNDARY_VOLTAGES = [500.0, 275.0, 220.0, 187.0, 154.0, 132.0, 110.0,
                     77.0, 66.0, 33.0, 22.0, 6.6]


def generate_boundary(out_dir: str, voltages: Optional[Iterable[float]] = None) -> dict:
    """Write ``AllJapan_EQ_BD.xml`` + ``AllJapan_TP_BD.xml`` into ``out_dir``.

    Args:
        out_dir: Output directory for the two boundary files.
        voltages: Nominal voltages (kV) to define as BaseVoltage objects. When
            ``None``, :data:`BOUNDARY_VOLTAGES` is used. Pass the union of the
            voltages actually referenced by the equipment files so every
            reference resolves.

    Returns:
        Summary dict with the voltage list, object count and file paths.
    """
    kvs = sorted({round(float(v), 3) for v in (voltages or BOUNDARY_VOLTAGES)},
                 reverse=True)
    eq_bd = RdfWriter(PROFILE_EQ_BD, mrid("bdmodel", "eqbd")).header()
    for kv in kvs:
        m = base_voltage_mrid(kv)
        eq_bd.obj("BaseVoltage", m,
                  attrs={"IdentifiedObject.name": f"{kv:g} kV",
                         "IdentifiedObject.mRID": m,
                         "BaseVoltage.nominalVoltage": kv})
    # TP_BD: no cross-model boundary TopologicalNodes here (single-authority
    # model), so it carries only the FullModel header for profile completeness.
    tp_bd = RdfWriter(PROFILE_TP_BD, mrid("bdmodel", "tpbd")).header()

    os.makedirs(out_dir, exist_ok=True)
    eq_path = os.path.join(out_dir, "AllJapan_EQ_BD.xml")
    tp_path = os.path.join(out_dir, "AllJapan_TP_BD.xml")
    eq_bd.write(eq_path)
    tp_bd.write(tp_path)
    return {
        "voltages_kv": kvs,
        "eq_bd_objects": eq_bd.object_count,
        "eq_bd": eq_path,
        "tp_bd": tp_path,
    }
