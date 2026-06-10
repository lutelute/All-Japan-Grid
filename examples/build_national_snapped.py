"""Back-compat shim: the national zonal builder now lives in
``src.powerflow.national`` (phase-6 structural unification)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.powerflow.national import (  # noqa: E402,F401
    ALL_REGIONS,
    ISLANDS,
    build_island_networks,
    diagnose,
    load_interconnections,
)
