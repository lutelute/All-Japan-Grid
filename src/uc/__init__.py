"""Unit commitment (UC) analysis package for the Japan Grid Pipeline.

Provides data models, solver interfaces, and result export for
generator unit commitment optimisation over configurable time horizons.
"""

from src.uc.adaptive_solver import AdaptiveUCResult, solve_adaptive
from src.uc.hardware_detector import HardwareProfile, detect_hardware
from src.uc.models import (
    DemandProfile,
    GeneratorSchedule,
    Interconnection,
    InterconnectionFlow,
    TimeHorizon,
    UCParameters,
    UCResult,
)
from src.uc.solver_strategy import SolverConfig, SolverTier

__all__ = [
    "AdaptiveUCResult",
    "DemandProfile",
    "GeneratorSchedule",
    "HardwareProfile",
    "Interconnection",
    "InterconnectionFlow",
    "SolverConfig",
    "SolverTier",
    "TimeHorizon",
    "UCParameters",
    "UCResult",
    "detect_hardware",
    "solve_adaptive",
]
