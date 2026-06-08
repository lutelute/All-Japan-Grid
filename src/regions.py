"""Canonical region registry — the single source of truth for region facts.

All region constants (the ordered 10-region list, Japanese/English names,
synchronous-system frequency, bounding boxes) are derived here from
``config/regions.yaml`` so they are defined exactly once. Modules that
used to hard-code their own copies (``REGIONS`` lists, ``REGION_JA`` /
``REGION_NAME`` maps, ``REGION_FREQUENCY_HZ`` / ``REGION_FREQ``) should
import from here instead — see ``REVIEW_FINDINGS.md`` Phase C.

The values are loaded once at import time. ``national_backbone`` is a
config entry but not a data region, so it is excluded from :data:`REGIONS`.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

import yaml

_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "config", "regions.yaml"
)


def _load() -> Dict[str, Any]:
    with open(_CONFIG_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


_CONFIG: Dict[str, Any] = _load()
_REGIONS: Dict[str, Any] = _CONFIG["regions"]

#: Region ids in canonical (config) order: hokkaido … okinawa.
REGIONS: List[str] = list(_REGIONS.keys())

#: region id -> Japanese name (北海道, 東北, …).
REGION_JA: Dict[str, str] = {r: c["name_ja"] for r, c in _REGIONS.items()}

#: region id -> English name (Hokkaido, Tohoku, …).
REGION_EN: Dict[str, str] = {r: c["name_en"] for r, c in _REGIONS.items()}

#: region id -> synchronous-system frequency in Hz (50 east / 60 west).
REGION_FREQUENCY_HZ: Dict[str, int] = {
    r: c["frequency_hz"] for r, c in _REGIONS.items()
}

#: region id -> {lat_min, lat_max, lon_min, lon_max}.
REGION_BBOX: Dict[str, Dict[str, float]] = {
    r: c["bounding_box"] for r, c in _REGIONS.items()
}


def region_config(region: str) -> Dict[str, Any]:
    """Return the full config block for ``region`` (raises KeyError if unknown)."""
    return _REGIONS[region]


def frequency_hz(region: str) -> int:
    """Return the synchronous-system frequency (Hz) for ``region``."""
    return REGION_FREQUENCY_HZ[region]


def name_ja(region: str) -> str:
    """Return the Japanese name for ``region``."""
    return REGION_JA[region]
