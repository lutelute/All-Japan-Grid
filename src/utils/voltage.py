"""Canonical OSM ``voltage`` tag parsing (volts string -> kV).

A transmission feature may carry several voltages on one tag, separated by
``;`` or ``,`` (e.g. ``"154000;66000"`` = a 154 kV line with a 66 kV
underbuild). The **transmission** level is the highest of these, so a
multi-voltage tag resolves to its maximum. Taking the first element — as
several copies of this parser used to — mislabels ``"66000;154000"`` as
66 kV purely from token order, giving the same physical line different bus
voltages in different pipelines (REVIEW_FINDINGS #10).

Values above 1000 are assumed to be in volts and divided by 1000; smaller
values are treated as already-kV. Unparseable / non-positive input -> None.

Note: :func:`src.cim.exporter.parse_voltage_kv` is a richer, CIM-specific
variant (returns all voltages + AC/DC current type per
``config/data_schema.yaml``); this module is the plain max-kV parser shared
by the loaders, the topology builder and the enrichment scripts.
"""

from __future__ import annotations

from typing import Optional


def parse_voltage_kv(raw: object) -> Optional[float]:
    """Return the highest voltage (kV) in an OSM ``voltage`` tag, or None.

    Args:
        raw: Raw OSM voltage value (``"275000"``, ``"154000;66000"``,
            ``"77000,6600"``, ``"154"``, ``None`` …).

    Returns:
        Maximum voltage in kV, or ``None`` if nothing positive parses.
    """
    if raw is None:
        return None
    best = 0.0
    for part in str(raw).strip().replace(",", ";").split(";"):
        part = part.strip()
        if not part:
            continue
        try:
            v = float(part)
        except (ValueError, TypeError):
            continue
        kv = v / 1000.0 if v > 1000 else v
        if kv > best:
            best = kv
    return best if best > 0 else None
