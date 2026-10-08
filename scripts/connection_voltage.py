"""Voltage evidence shared by OSM way-chain recovery diagnostics."""
from __future__ import annotations


def voltage_signature(values):
    """Keep known positive classes; unknown values cannot reset the evidence."""
    import math
    known = set()
    for value in values:
        try:
            number = float(value)
        except (ValueError, TypeError):
            continue
        if math.isfinite(number) and number > 0:
            known.add(number)
    return tuple(sorted(known))


def route_voltage_compatible(values, tolerance=0.25):
    """All known classes must satisfy the existing 25% voltage gate.

    A route is a single line, with no transformer witness. In particular,
    66 kV -> unknown -> 154 kV must not become a transformer implicitly.
    Passing this screening gate is not evidence of a physical connection.
    """
    known = voltage_signature(values)
    return len(known) < 2 or known[-1] <= known[0] * (1 + tolerance)
