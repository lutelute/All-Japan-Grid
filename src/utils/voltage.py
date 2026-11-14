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

import os
from typing import Optional

# ── 介入#64(2026-11-15): 正典の電圧の級 ─────────────────────────────────────────────
# 網を組む段(src/powerflow/snapped_topology._clean_voltage)は、OSM の電圧をいちばん近い級に寄せる。
# 2026-11-14 までは 66 kV が最小の級で、22・33 kV の線(北海道・東北・関西など)は 66 kV に丸めていた
# (台帳に無い仮定だった。docs/MODEL_INTERVENTIONS.md の #64)。先生「33 kV もあるなら載せるといい」
# 「ちゃんと DB や正典を整えて」(2026-11-15)で、22・33 kV を級として持つ。
# 無効化(前の丸めに戻す): 環境変数 AJG_LOW_KV_CLASSES=0 で網を組み直す。
LOW_KV_CLASSES = os.environ.get("AJG_LOW_KV_CLASSES", "1") != "0"
KV_CLASSES: tuple = tuple(([22, 33] if LOW_KV_CLASSES else []) + [66, 77, 110, 132, 154, 187, 220, 275, 500])


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
