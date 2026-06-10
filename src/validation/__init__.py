"""Validation pillar: measurable quality KPIs for the grid model.

The model's two weakest layers — topology connectivity and the electrical
power-flow case — were historically judged by eye. This package turns them
into numbers (fragmentation, synthetic-line rate, convergence, voltage
sanity, OSM tag evidence) so every change to the builders can be measured
against a pinned baseline instead of anecdotes.
"""

from src.validation.topology_metrics import (  # noqa: F401
    gather,
    render,
    solved_metrics,
    tag_coverage,
    topology_metrics,
)
