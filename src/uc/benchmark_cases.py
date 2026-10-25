"""Seeded synthetic UC cases, explicitly distinct from observed Japanese units."""

import math
import random

from src.model.generator import Generator
from src.uc.models import DemandProfile, Interconnection, TimeHorizon, UCParameters


def synthetic_case(units=800, hours=24, seed=17, start_hour=0):
    if units < 4 or hours < 1:
        raise ValueError("synthetic cases require >=4 units and >=1 hour")
    rng = random.Random(seed)
    regions = ["tohoku", "tokyo", "kansai", "kyushu"]
    generators = []
    capacities = dict.fromkeys(regions, 0.0)
    for i in range(units):
        fuel = ("coal", "lng", "lng", "oil")[i % 4]
        region = regions[(i // 4 + i % 4) % 4]
        cap = rng.uniform(300, 800) if fuel == "coal" else rng.uniform(150, 550)
        fraction = {"coal": 0.45, "lng": 0.3, "oil": 0.2}[fuel]
        cost = {"coal": 7000, "lng": 11000, "oil": 20000}[fuel] * rng.uniform(0.85, 1.15)
        minimum = {"coal": 8, "lng": 4, "oil": 2}[fuel]
        startup = cap * rng.uniform(3000, 7000)
        generators.append(Generator(
            id=f"syn_{i:04d}", name=f"Synthetic unit {i}", capacity_mw=cap,
            fuel_type=fuel, region=region, p_min_mw=cap * fraction,
            min_up_time_h=minimum, min_down_time_h=max(2, minimum // 2),
            ramp_up_mw_per_h=cap * (0.2 if fuel == "coal" else 0.5),
            ramp_down_mw_per_h=cap * (0.2 if fuel == "coal" else 0.5),
            fuel_cost_per_mwh=cost, no_load_cost=cap * rng.uniform(100, 300),
            startup_cost=startup, hot_start_cost=startup,
            warm_start_cost=1.6 * startup, cold_start_cost=2.5 * startup,
            warm_start_h=4, cold_start_h=12, shutdown_cost=0.1 * startup,
            source="synthetic_uc800_v1",
        ))
        capacities[region] += cap
    demands = {}
    for r, region in enumerate(regions):
        profile = []
        for t in range(start_hour, start_hour + hours):
            h = t % 24
            load = 0.53 + 0.14 * math.cos(2 * math.pi * (h - 18 - r * 0.4) / 24)
            solar = (0.08 + 0.035 * r) * max(0.0, math.sin(math.pi * (h - 6) / 12))
            seasonal = 0.04 * math.cos(2 * math.pi * t / 8760)
            weekly = 0.025 * math.sin(2 * math.pi * t / 168)
            profile.append(capacities[region] * (load - solar + seasonal + weekly))
        demands[region] = profile
        power = capacities[region] * 0.025
        generators.append(Generator(id=f"storage_{r}", name=f"Synthetic storage {r}",
            capacity_mw=power, fuel_type="battery", region=region,
            storage_capacity_mwh=power * 4, charge_rate_mw=power, discharge_rate_mw=power,
            charge_efficiency=0.9, discharge_efficiency=0.9,
            initial_soc_fraction=0.5, min_terminal_soc_fraction=0.5,
            source="synthetic_uc800_v1"))
    links = [Interconnection(id=f"syn_ic_{i}", name_en=f"Synthetic link {i}",
        from_region=regions[i], to_region=regions[(i + 1) % 4],
        capacity_mw=min(capacities[regions[i]], capacities[regions[(i + 1) % 4]]) * 0.12)
        for i in range(4)]
    return UCParameters(generators=generators,
        demand=DemandProfile(demands=[sum(d[t] for d in demands.values()) for t in range(hours)]),
        time_horizon=TimeHorizon(num_periods=hours), regional_demands=demands,
        interconnections=links, reserve_margin=0.05)
