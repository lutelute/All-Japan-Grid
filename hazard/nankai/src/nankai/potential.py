"""ポテンシャル法(B): 潮流を解かず、ハザード・脆弱性・網の冗長性・供給余力の「ポテンシャル」から
停電しやすさを推定する。解析法(A)のモンテカルロ結果と比較するための軽量推定。

  P_out(i) = 1 − S_path(i) · A_supply(i)
    S_path : 中央値ハザード下での「最良経路の生存確率」。枝と母線に −ln(1−p_fail) の重みを置き、
             電源(≥100MW の火力/原子力/水力母線 or フラグメント仮想電源)からの最短路 = 最大生存路
    A_supply: 半径 R 内の生存発電ポテンシャル / 域内負荷 (上限1)。地震動で停止する火力・原子力が
             多い地域ほど下がる(供給力不足のポテンシャル)
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import scipy.sparse as sp
from scipy.sparse.csgraph import dijkstra
from scipy.stats import norm

from .fragility import p_exceed, substation_class


def analytic_pfail(sim, hs, t_days: float = 2.0) -> dict:
    """中央値ハザード hs (HazardSample) に対する解析的な故障確率(fragility の解析式を使う)。"""
    fm = sim.fm
    pga_site = np.zeros(len(sim.site_rows)); np.maximum.at(pga_site, sim.bus_site, hs.pga_g)
    i_site = np.zeros(len(sim.site_rows)); np.maximum.at(i_site, sim.bus_site, hs.intensity)
    pout = fm.substation_pout(sim.site_kv, pga_site, i_site)
    pts = np.array([float(fm.p["substation"]["tsunami"]["pfail_by_rank"].get(int(r), 1.0)) for r in sim.site_ts])
    p_site = 1 - (1 - pout) * (1 - pts)
    p_site[sim.site_is_junction] = 0.0
    pga_br = np.maximum(hs.pga_g[sim.bf], hs.pga_g[sim.bt]); i_br = np.maximum(hs.intensity[sim.bf], hs.intensity[sim.bt])
    p_long, p_short = fm.line_pfail(pga_br, sim.br_len, sim.br_par, sim.br_ts, intensity=i_br)
    p_line = 1 - (1 - p_long) * (1 - (p_short if t_days < 2 else 0.0))
    p_gen = fm.generator_pout(sim.gcls, hs.pga_g[sim.gb], hs.intensity[sim.gb], sim.gen_ts, t_days)
    p_gen[sim.gslack] = 0.0
    return {"p_site": p_site, "p_line": p_line, "p_gen": p_gen}


def potential_index(sim, hs, radius_km: float = 80.0, source_min_mw: float = 100.0, horizon: str = "day2") -> pd.DataFrame:
    """母線ごとのポテンシャル指標。horizon: 'immediate'(トリップ含む) / 'day2'(トリップ復帰後=損傷のみ)

    戻り列: p_site(自母線の変電所故障確率), s_path(電源までの最良経路生存率), a_supply(半径内の供給余力),
            potential_pout(= 1 − s_path·a_supply), hops_to_source(重み付き距離)"""
    pf = analytic_pfail(sim, hs, t_days=(0.0 if horizon == "immediate" else 2.0))
    n = sim.case.n_bus
    p_bus = pf["p_site"][sim.bus_site]
    w_node = -np.log(np.clip(1 - p_bus, 1e-6, 1))
    w_edge = -np.log(np.clip(1 - pf["p_line"], 1e-6, 1)) + 0.5 * (w_node[sim.bf] + w_node[sim.bt])
    A = sp.coo_matrix((w_edge + 1e-9, (sim.bf, sim.bt)), shape=(n, n)).tocsr()
    A = A + A.T
    # 電源: 大型機(損傷+トリップの生存を重み化)
    p_g = pf["p_gen"]
    big = (~sim.gslack) & (sim.gpmax >= source_min_mw) & np.isin(sim.gcls, ["thermal", "nuclear", "hydro", "geothermal", "unknown"])
    src_w = np.full(n, np.inf)
    for i in np.where(big | (sim.gslack & (sim.slack_cap > 0)))[0]:
        b = sim.gb[i]
        w = 0.0 if sim.gslack[i] else -np.log(max(1 - p_g[i], 1e-6))
        src_w[b] = min(src_w[b], w)
    sources = np.where(np.isfinite(src_w))[0]
    d = dijkstra(A, directed=False, indices=sources, min_only=True)
    # 電源自身の生存: min_only は最短路の電源を返すので近似的に加算
    d_src, pred, srcs = dijkstra(A, directed=False, indices=sources, min_only=True, return_predecessors=True)
    s_path = np.exp(-(d_src + np.where(np.isfinite(srcs) & (srcs >= 0), src_w[np.clip(srcs, 0, n - 1)], 0.0)))
    s_path = np.where(np.isfinite(d_src), s_path, 0.0) * np.exp(-0.5 * w_node)   # 自母線の生存
    # 供給余力ポテンシャル(半径 R 内)
    from scipy.spatial import cKDTree
    km_lat = 111.0; km_lon = 111.0 * np.cos(np.radians(np.nanmean(sim.lat)))
    xy = np.c_[sim.lat * km_lat, sim.lon * km_lon]
    tree = cKDTree(xy)
    # 供給ポテンシャル: 復旧期の利用可能出力(pmax×係数; 解析法と同じ定義)× 生存確率
    av = np.vectorize(lambda c: sim.avail.get(c, 0.5))(sim.gcls)
    g_avail = np.where(sim.gslack, sim.slack_cap, sim.gpmax * av) if horizon != "immediate" else np.where(sim.gslack, sim.slack_cap, sim.gp * sim.reserve)
    gen_surv = g_avail * (1 - p_g)
    gen_at_bus = np.bincount(sim.gb, weights=gen_surv, minlength=n)
    load = sim.cm.load
    A_sup = np.zeros(n)
    nb = tree.query_ball_point(xy, r=radius_km)
    for i, idx in enumerate(nb):
        idx = np.asarray(idx)
        L = load[idx].sum(); G = gen_at_bus[idx].sum()
        A_sup[i] = 1.0 if L <= 1e-6 else min(1.0, G / L)
    p_out = 1 - s_path * A_sup
    return pd.DataFrame({"bus_id": sim.case.bus.bus_id.values, "p_site": p_bus, "s_path": s_path, "a_supply": A_sup,
                         "potential_pout": np.clip(p_out, 0, 1), "hops_to_source": np.where(np.isfinite(d_src), d_src, np.nan)})
