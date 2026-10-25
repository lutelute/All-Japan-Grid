"""A UC-specific solver: one exact dynamic program per unit, coupled by prices.

The bottom (lower bound). Every thermal unit's schedules (minimum up and down time, startup type by
hours off, output between its minimum and maximum) are priced exactly by dynamic programming against the
prices of the rows that couple units: regional balance and reserve. The master LP keeps only those rows
plus storage and interconnections. Its value plus each unit's most negative reduced cost is a valid lower
bound (the Lagrangian bound), the LP over the convex hull of every unit's schedules. The leak of the
textbook formulation, where the LP counts a cold start as a hot one (99.6 % of its LP gap,
docs/research/uc800-open-solver/IMPLEMENTATION_STATUS.md §6.1), cannot happen: the DP counts hours off.

The band (upper bound). Unit-hours on which the master puts all weight on one value are sunk and fixed;
the original MILP (src.uc.solver, with ramps and the storage binaries) is solved over the floating rest.

Ramps are left out of the pricing, so the bound is that of a relaxation (still valid); the upper bound
enforces them.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import highspy
import numpy as np

from src.uc.models import UCParameters
from src.uc.solver import SPILL_PENALTY

INF = float("inf")
SLACK_COST = 1e7          # yen per MWh of unserved demand or missing reserve: makes the first master feasible


@dataclass
class Units:
    """Thermal units as arrays. States: on for k+1 hours (k < M), off for d+1 hours (d < D); the last one counts 'or more'."""
    ids: List[str]
    region: np.ndarray
    cap: np.ndarray
    pmin: np.ndarray
    fuel: np.ndarray
    fixed: np.ndarray       # no-load + labour, yen per hour on
    sd: np.ndarray          # shutdown cost
    su: np.ndarray          # (U, D): startup after d+1 hours off; inf if too early or past the unit's last off state
    mcap: np.ndarray        # index of the unit's 'on for >= min up time' state
    dcap: np.ndarray        # index of the unit's 'off for >= max(min down, cold) hours' state
    init: np.ndarray        # initial state, unified index (on k -> k, off d -> M + d)
    allowed: np.ndarray     # (U, T) False in maintenance windows
    M: int
    D: int


def unit_table(params: UCParameters) -> Units:
    gens = [g for g in params.generators if not g.is_storage]
    regions = region_names(params)
    T = params.time_horizon.num_periods
    steps = params.time_horizon.period_indices
    mut = np.array([max(1, int(g.min_up_time_h)) for g in gens])
    dmax = np.array([max(1, int(g.min_down_time_h), int(g.cold_start_h) if g.has_thermal_startup else 0) for g in gens])
    M, D = int(mut.max()), int(dmax.max())
    su = np.full((len(gens), D), INF)
    for i, g in enumerate(gens):
        for d in range(int(dmax[i])):
            off = d + 1
            if off < max(1, int(g.min_down_time_h)):
                continue
            if g.has_thermal_startup:
                su[i, d] = g.hot_start_cost if off < g.warm_start_h else g.warm_start_cost if off < g.cold_start_h else g.cold_start_cost
            else:
                su[i, d] = g.startup_cost
    u0 = params.initial_commitment or {}
    hist = params.initial_history_h or {}
    init = np.empty(len(gens), dtype=np.int64)
    for i, g in enumerate(gens):
        h = hist.get(g.id)
        if u0.get(g.id, 0):
            init[i] = (min(h, mut[i]) - 1) if h and h > 0 else mut[i] - 1
        else:
            init[i] = M + ((min(-h, dmax[i]) - 1) if h and h < 0 else dmax[i] - 1)
    allowed = np.ones((len(gens), T), dtype=bool)
    for i, g in enumerate(gens):
        for a, b in g.maintenance_windows:
            for j, t in enumerate(steps):
                if a <= t < b:
                    allowed[i, j] = False
    return Units(ids=[g.id for g in gens], region=np.array([regions.index(g.region) for g in gens]),
                 cap=np.array([g.capacity_mw for g in gens]), pmin=np.array([g.p_min_mw for g in gens]),
                 fuel=np.array([g.fuel_cost_per_mwh for g in gens]),
                 fixed=np.array([g.no_load_cost + g.labor_cost_per_h for g in gens]),
                 sd=np.array([g.shutdown_cost for g in gens]), su=su, mcap=mut - 1, dcap=dmax - 1, init=init,
                 allowed=allowed, M=M, D=D)


def region_names(params: UCParameters) -> List[str]:
    return list(params.regional_demands) if params.regional_demands else ["all"]


def best_schedules(units: Units, oncost: np.ndarray):
    """Cheapest schedule of every unit when an hour on costs oncost[g, t] (startups and shutdowns as given).

    Returns (value, u) with u the (U, T) on/off pattern. All units at once; the loop runs over hours only.
    """
    U, T = oncost.shape
    M, D = units.M, units.D
    ar = np.arange(U)
    on_ok = np.arange(M)[None, :] <= units.mcap[:, None]
    off_ok = np.arange(D)[None, :] <= units.dcap[:, None]
    V = np.full((U, M + D), INF)
    V[ar, units.init] = 0.0
    pred = np.empty((T, U, M + D), dtype=np.int16)
    for t in range(T):
        Von, Voff = V[:, :M], V[:, M:]
        new = np.full((U, M + D), INF)
        pr = np.full((U, M + D), -1, dtype=np.int16)
        cand = Voff + units.su
        dbest = np.argmin(cand, axis=1)
        new[:, 0], pr[:, 0] = cand[ar, dbest], M + dbest
        if M > 1:
            new[:, 1:M], pr[:, 1:M] = Von[:, :M - 1], np.arange(M - 1)[None, :]
        stay = Von[ar, units.mcap]
        b = stay < new[ar, units.mcap]
        new[ar[b], units.mcap[b]], pr[ar[b], units.mcap[b]] = stay[b], units.mcap[b]
        new[:, :M] = np.where(on_ok & units.allowed[:, t:t + 1], new[:, :M] + oncost[:, t:t + 1], INF)
        new[:, M], pr[:, M] = Von[ar, units.mcap] + units.sd, units.mcap
        if D > 1:
            new[:, M + 1:], pr[:, M + 1:] = Voff[:, :D - 1], M + np.arange(D - 1)[None, :]
        stay = Voff[ar, units.dcap]
        idx = M + units.dcap
        b = stay < new[ar, idx]
        new[ar[b], idx[b]], pr[ar[b], idx[b]] = stay[b], idx[b]
        new[:, M:] = np.where(off_ok, new[:, M:], INF)
        V, pred[t] = new, pr
    s = np.argmin(V, axis=1)
    value = V[ar, s]
    u = np.zeros((U, T), dtype=bool)
    for t in range(T - 1, -1, -1):
        u[:, t] = s < M
        s = pred[t, ar, s]
    return value, u


def schedule_cost(units: Units, u: np.ndarray, p: np.ndarray, rows=None) -> np.ndarray:
    """True cost of schedules u (on/off) and p (MW), walked hour by hour from the initial state."""
    rows = np.arange(len(units.ids)) if rows is None else rows
    U, T = u.shape
    on = units.init[rows] < units.M
    off_h = np.where(on, 0, units.init[rows] - units.M + 1)
    cost = np.zeros(U)
    ar = np.arange(U)
    for t in range(T):
        start = u[:, t] & ~on
        stop = ~u[:, t] & on
        d = np.clip(off_h - 1, 0, units.D - 1)
        cost += np.where(start, units.su[rows, d], 0.0) + np.where(stop, units.sd[rows], 0.0)
        cost += u[:, t] * (units.fixed[rows] + units.fuel[rows] * p[:, t])
        off_h = np.where(u[:, t], 0, np.minimum(off_h + 1, units.dcap[rows] + 1))
        on = u[:, t]
    return cost


@dataclass
class ColGenResult:
    lower_bound: float
    master_value: float
    iterations: int
    columns: int
    seconds: float
    trace: List[dict] = field(default_factory=list)
    ubar: Optional[np.ndarray] = None          # (U, T) weight the master puts on 'on'
    unit_ids: List[str] = field(default_factory=list)
    duals: Optional[Dict[str, np.ndarray]] = None


class Master:
    """Restricted master LP: convex weights of unit schedules, storage, interconnections, spill, slacks."""

    def __init__(self, params: UCParameters, units: Units, threads: int = 1):
        self.params, self.units = params, units
        T = self.T = params.time_horizon.num_periods
        regions = self.regions = region_names(params)
        R, U = len(regions), len(units.ids)
        dem = params.regional_demands or {"all": params.demand.demands}
        storage = self.storage = [g for g in params.generators if g.is_storage]
        S = len(storage)
        if params.reserve_requirement_mw is not None:
            req = np.array(params.reserve_requirement_mw, dtype=float)
        else:
            req = np.array(params.demand.demands) * (1 + params.reserve_margin) if params.reserve_margin > 0 else np.full(T, -INF)
        req = req - sum(g.capacity_mw for g in storage)        # storage commitment is free and counts fully
        self.bal = np.arange(R * T).reshape(R, T)
        self.res = R * T + np.arange(T)
        self.conv = R * T + T + np.arange(U)
        self.soc = R * T + T + U + np.arange(S * T).reshape(S, T) if S else np.zeros((0, T), dtype=int)
        self.mode = R * T + T + U + S * T + np.arange(S * T).reshape(S, T) if S else np.zeros((0, T), dtype=int)
        nrow = R * T + T + U + 2 * S * T
        lo, hi = np.zeros(nrow), np.zeros(nrow)
        for r, name in enumerate(regions):
            lo[self.bal[r]] = hi[self.bal[r]] = np.array(dem[name], dtype=float)
        lo[self.res], hi[self.res] = req, INF
        lo[self.conv] = hi[self.conv] = 1.0
        for s, g in enumerate(storage):
            lo[self.soc[s]] = hi[self.soc[s]] = 0.0
            lo[self.soc[s][0]] = hi[self.soc[s][0]] = g.initial_soc_fraction * g.storage_capacity_mwh
            lo[self.mode[s]], hi[self.mode[s]] = -INF, 1.0
        h = self.h = highspy.Highs()
        h.setOptionValue("output_flag", False)
        h.setOptionValue("threads", threads)
        h.addRows(nrow, lo, hi, 0, np.zeros(1, dtype=np.int32), np.zeros(0, dtype=np.int32), np.zeros(0))
        self.ncol = 0
        cols = []                                               # (cost, lb, ub, rows, vals)
        for s, g in enumerate(storage):
            r = regions.index(g.region)
            rc = g.charge_rate_mw if g.charge_rate_mw is not None else g.capacity_mw
            rd = g.discharge_rate_mw if g.discharge_rate_mw is not None else g.capacity_mw
            dt = params.time_horizon.period_duration_h
            for t in range(T):
                cols.append((0.0, 0.0, rc, [self.bal[r, t], self.soc[s, t], self.mode[s, t]], [-1.0, -g.charge_efficiency * dt, 1.0 / rc]))
                cols.append((0.0, 0.0, rd, [self.bal[r, t], self.soc[s, t], self.mode[s, t]], [1.0, dt / g.discharge_efficiency, 1.0 / rd]))
                last = t == T - 1
                rows, vals = [self.soc[s, t]], [1.0]
                if not last:
                    rows.append(self.soc[s, t + 1]); vals.append(-1.0)
                cols.append((0.0, g.min_terminal_soc_fraction * g.storage_capacity_mwh if last else 0.0,
                             g.storage_capacity_mwh, rows, vals))
        for ic in params.interconnections or []:
            a, b = regions.index(ic.from_region), regions.index(ic.to_region)
            fwd, rev = getattr(ic, "cap_fwd", ic.capacity_mw), getattr(ic, "cap_rev", ic.capacity_mw)
            for t in range(T):
                cols.append((0.0, -rev, fwd, [self.bal[b, t], self.bal[a, t]], [1.0, -1.0]))
        for r in range(R):
            for t in range(T):
                if params.interconnections:
                    cols.append((SPILL_PENALTY, 0.0, INF, [self.bal[r, t]], [-1.0]))
                cols.append((SLACK_COST, 0.0, INF, [self.bal[r, t]], [1.0]))
        for t in range(T):
            cols.append((SLACK_COST, 0.0, INF, [self.res[t]], [1.0]))
        self._add(cols)
        self.fixed_cols = self.ncol
        self.col_unit: List[int] = []
        self.col_u: List[np.ndarray] = []
        self.col_cost: List[float] = []

    def _add(self, cols):
        if not cols:
            return
        starts, idx, val = [], [], []
        for c in cols:
            starts.append(len(idx)); idx.extend(c[3]); val.extend(c[4])
        self.h.addCols(len(cols), np.array([c[0] for c in cols]), np.array([c[1] for c in cols]),
                       np.array([c[2] for c in cols]), len(idx), np.array(starts, dtype=np.int32),
                       np.array(idx, dtype=np.int32), np.array(val, dtype=float))
        self.ncol += len(cols)

    def add_schedules(self, rows: np.ndarray, u: np.ndarray, p: np.ndarray, cost: np.ndarray):
        units, T = self.units, self.T
        cols = []
        for j, g in enumerate(rows):
            on = np.nonzero(u[j])[0]
            r = units.region[g]
            cols.append((float(cost[j]), 0.0, INF,
                         list(self.bal[r, on]) + list(self.res[on]) + [self.conv[g]],
                         list(p[j, on]) + [float(units.cap[g])] * len(on) + [1.0]))
            self.col_unit.append(int(g)); self.col_u.append(u[j].copy()); self.col_cost.append(float(cost[j]))
        self._add(cols)

    def solve(self):
        highspy.Highs.resetGlobalScheduler(True)    # one thread pool per process (src/uc/solver.py does the same)
        self.h.run()
        st = self.h.getModelStatus()
        if st != highspy.HighsModelStatus.kOptimal:
            self.h.clearSolver()
            self.h.run()
            st = self.h.getModelStatus()
        if st != highspy.HighsModelStatus.kOptimal:
            raise RuntimeError(f"master LP: {self.h.modelStatusToString(st)}")
        sol = self.h.getSolution()
        y = np.array(sol.row_dual)
        x = np.array(sol.col_value)
        return self.h.getInfo().objective_function_value, y, x


def solve_colgen(params: UCParameters, *, time_limit_s: float = 600.0, tol: float = 1e-6, max_iter: int = 500,
                 smoothing: float = 0.5, threads: int = 1, log=print, keep_prices: bool = False) -> ColGenResult:
    """Column generation to the Lagrangian bound. Duals are smoothed (Wentges) for the columns; the bound uses the exact ones."""
    t0 = time.monotonic()
    units = unit_table(params)
    U, T = len(units.ids), params.time_horizon.num_periods
    master = Master(params, units, threads=threads)
    R = len(master.regions)

    def columns(pi, sigma):
        price = pi[units.region]                                # (U, T)
        margin = units.fuel[:, None] - price
        p = np.where(margin < 0, units.cap[:, None], units.pmin[:, None])
        oncost = units.fixed[:, None] + margin * p - sigma[None, :] * units.cap[:, None]
        value, u = best_schedules(units, oncost)
        p = np.where(u, p, 0.0)
        return value, u, p

    # first columns: every unit off and on at full output, then the schedules at a flat price
    rows = np.arange(U)
    for pi0 in (np.zeros((R, T)), np.full((R, T), float(np.percentile(units.fuel, 75)))):
        _, u, p = columns(pi0, np.zeros(T))
        master.add_schedules(rows, u, p, schedule_cost(units, u, p))
    sign, center, best_lb = None, None, -INF
    trace = []
    for it in range(max_iter):
        z, y, x = master.solve()
        if sign is None:                                        # HiGHS reduced cost = c - A^T (sign * row_dual)
            dual = np.array(master.h.getSolution().col_dual)
            sign = _dual_sign(master, y, dual)
        y = sign * y
        pi = y[master.bal]
        sigma = np.maximum(y[master.res], 0.0)
        mu = y[master.conv]
        value, u, p = columns(pi, sigma)
        rc = value - mu
        lb = z + float(np.minimum(rc, 0.0).sum())
        if lb > best_lb:
            best_lb, center = lb, (pi.copy(), sigma.copy())
        new = rc < -tol * max(1.0, abs(z)) / U
        if new.any():
            master.add_schedules(rows[new], u[new], p[new], schedule_cost(units, u[new], p[new], rows[new]))
        n_smooth = 0
        if center is not None and smoothing > 0:
            ps = smoothing * center[0] + (1 - smoothing) * pi
            ss = smoothing * center[1] + (1 - smoothing) * sigma
            vs, us, pss = columns(ps, ss)
            # keep the smoothed schedules that also price out at the exact duals
            rcs = (schedule_cost(units, us, pss) - (pi[units.region] * pss).sum(1)
                   - (sigma[None, :] * units.cap[:, None] * us).sum(1) - mu)
            keep = rcs < -tol * max(1.0, abs(z)) / U
            keep &= ~np.all(us == u, axis=1) | ~new
            if keep.any():
                master.add_schedules(rows[keep], us[keep], pss[keep], schedule_cost(units, us[keep], pss[keep], rows[keep]))
                n_smooth = int(keep.sum())
        gap = (z - best_lb) / max(1.0, abs(z))
        trace.append({"it": it, "master": z, "lb": lb, "best_lb": best_lb, "gap": gap, "new": int(new.sum()),
                      "smooth": n_smooth, "cols": len(master.col_unit), "s": round(time.monotonic() - t0, 2)})
        log(trace[-1])
        if keep_prices:                                         # for pictures: the prices sent out and who answered
            trace[-1].update(pi=np.round(pi, 1).tolist(), sigma=np.round(sigma, 1).tolist(),
                             new_units=np.nonzero(new)[0].tolist(),
                             new_u=["".join("1" if b else "0" for b in row) for row in u[new]])
        if gap < tol or (not new.any() and n_smooth == 0) or time.monotonic() - t0 > time_limit_s:
            break
    lam = x[master.fixed_cols:]
    ubar = np.zeros((U, T))
    for j, g in enumerate(master.col_unit[:len(lam)]):
        if lam[j] > 0:
            ubar[g] += lam[j] * master.col_u[j]
    return ColGenResult(lower_bound=best_lb, master_value=z, iterations=len(trace), columns=len(master.col_unit),
                        seconds=time.monotonic() - t0, trace=trace, ubar=ubar, unit_ids=units.ids,
                        duals={"pi": pi, "sigma": sigma})


def _dual_sign(master: Master, y: np.ndarray, col_dual: np.ndarray) -> float:
    lp = master.h.getLp()
    A = lp.a_matrix_
    starts, index, value = np.array(A.start_), np.array(A.index_), np.array(A.value_)
    cost = np.array(lp.col_cost_)
    j = np.arange(master.fixed_cols, master.ncol)[:200]
    for s in (1.0, -1.0):
        ok = True
        for k in j:
            a, b = starts[k], starts[k + 1]
            rc = cost[k] - s * float(value[a:b] @ y[index[a:b]])
            if abs(rc - col_dual[k]) > 1e-6 * max(1.0, abs(cost[k])):
                ok = False
                break
        if ok:
            return s
    raise RuntimeError("cannot match HiGHS reduced costs to the row duals")


def solve_band(params: UCParameters, cg: ColGenResult, *, time_limit_s: float = 300.0, gap: float = 1e-4,
               threads: int = 1, eps: float = 1e-6):
    """Upper bound: fix the unit-hours the master sunk to 0 or 1, solve the original MILP over the floating rest."""
    from src.uc.solver import solve_uc

    steps = params.time_horizon.period_indices
    sunk = {}
    for i, gid in enumerate(cg.unit_ids):
        for j, t in enumerate(steps):
            x = cg.ubar[i, j]
            if x <= eps:
                sunk[(gid, t)] = 0
            elif x >= 1 - eps:
                sunk[(gid, t)] = 1

    def hook(model, var):
        u = var["u"]
        for key, val in sunk.items():
            u[key].lowBound = u[key].upBound = val

    params.model_hook = hook
    params.solver_name, params.solver_time_limit_s, params.mip_gap = "HiGHS", time_limit_s, gap
    params.solver_options = dict(params.solver_options, threads=threads)
    if "startup_type" not in params.strengthen:
        params.strengthen = tuple(params.strengthen) + ("startup_type",)
    return solve_uc(params), len(sunk)
