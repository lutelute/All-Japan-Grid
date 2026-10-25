# UC resource-bounded frontier

Synthetic hourly zonal UC; 4 storage units are additional to the commitment-unit count.

| Units | Hours | Solver | Start | Outcome | Last phase | Gap (%) | Wall (s) | Peak RSS (GiB) |
|---:|---:|---|---|---|---|---:|---:|---:|
| 800 | 168 | HiGHS | rolling | feasible_above_target | complete | 100.0000 | 2590.96 | 6.506 |

A resource cutoff identifies a limit of this formulation, implementation, machine, and budget.
It does not prove that a larger UC instance is mathematically unsolvable.
RSS is sampled and may overshoot the requested ceiling. Skipped cells are unmeasured.
