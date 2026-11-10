#!/usr/bin/env python3
"""線を伏せた同化の実験(試作): 観測の潮流の誤差は、注入(発電・需要の場所)と網のどちらから来るか.

やること(島ごと・時刻ごと):
  1. 日別断面と同じ手順で、その時刻の注入(発電・需要)の事前の見積もりを作る
  2. 直流の式で、観測のある線の潮流を「注入の一次式」にする(H)。pandapower の直流潮流と一致するかを確かめる
  3. 観測の線を 5 つに分け、4/5 の線の観測から注入の直しを推定し(事前の幅 S・観測の誤差 R の線形推定)、
     伏せた 1/5 の線の潮流を当てる
読むだけ。書くのは --out の JSON だけ。
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import math
import random
import statistics as st
import sys
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

warnings.filterwarnings("ignore")


def dc_structure(net):
    """直流の式の部品: 枝(線・変圧器)の両端と b[MW/rad]、基準の母線、主成分."""
    vn = net.bus["vn_kv"]
    fb, tb, bb, kind, idx = [], [], [], [], []
    ln = net.line[net.line.in_service]
    for i, r in ln.iterrows():
        x = float(r["x_ohm_per_km"]) * float(r["length_km"]) / max(int(r.get("parallel", 1) or 1), 1)
        if not (x > 0):
            continue
        v = float(vn[int(r["from_bus"])])
        fb.append(int(r["from_bus"])); tb.append(int(r["to_bus"])); bb.append(v * v / x)
        kind.append("line"); idx.append(i)
    tr = net.trafo[net.trafo.in_service]
    for i, r in tr.iterrows():
        vk, vkr = float(r["vk_percent"]), float(r.get("vkr_percent", 0) or 0)
        xf = math.sqrt(max(vk * vk - vkr * vkr, 1e-12)) / 100.0
        sn = float(r["sn_mva"]) * max(int(r.get("parallel", 1) or 1), 1)
        hv, lv = int(r["hv_bus"]), int(r["lv_bus"])
        # pandapower と同じく低圧側の母線の基準へ直し、公称電圧の比を巻数比にする
        x_sys = xf * (float(r["vn_lv_kv"]) ** 2 / sn) / (float(vn[lv]) ** 2)     # 1/MW
        ratio = (float(r["vn_hv_kv"]) / float(vn[hv])) / (float(r["vn_lv_kv"]) / float(vn[lv]))
        tp = r.get("tap_pos")
        if tp is not None and tp == tp and r.get("tap_step_percent") == r.get("tap_step_percent"):
            tn = r.get("tap_neutral")
            tn = 0 if tn is None or tn != tn else tn
            step = 1 + (float(tp) - float(tn)) * float(r["tap_step_percent"]) / 100.0
            ratio = ratio * step if str(r.get("tap_side")) == "hv" else ratio / step
        fb.append(hv); tb.append(lv); bb.append(1.0 / (x_sys * ratio))
        kind.append("trafo"); idx.append(i)
    return np.array(fb), np.array(tb), np.array(bb), kind, idx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--crosswalk", type=Path, required=True)
    ap.add_argument("--date", default="20261108")
    ap.add_argument("--islands", nargs="+", default=["hokkaido", "east", "west"])
    ap.add_argument("--alphas", nargs="+", type=float, default=[0.1, 0.3, 1.0])
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--balance", action="store_true")
    ap.add_argument("--closure-only", action="store_true", help="収支を合わせた前後の採点だけ(線を伏せた同化はしない)")
    ap.add_argument("--use-closed", action="store_true", help="線を伏せた同化の事前に、収支を合わせた注入を使う")
    a = ap.parse_args()
    ROOT = a.root.resolve()
    sys.path.insert(0, str(ROOT))
    import pandapower as pp
    import scripts.export_day_flows as edf
    import src.powerflow.point_demand as pdm
    from scripts.run_full_powerflow_from_db import (
        add_per_component_slacks, allocate_loads, attach_generators,
        balance_by_zone, build_island_net, load_demand_config)
    from src.powerflow.line_keys import line_keys
    from src.powerflow.pref_demand import pref_zone_gwh
    from scripts.fetch_area_fuelmix import ensure_fuelmix

    date = dt.datetime.strptime(a.date, "%Y%m%d").date()
    day = date.isoformat()
    today = json.loads((ROOT / "docs/data/flow_map/occto_today.json").read_text())
    cw = json.loads(a.crosswalk.read_text())
    obs = {}
    for lid, v in today["lines"].items():
        acc = defaultdict(list)
        for t, x in zip(today["times"], v["v"]):
            if x is not None and t[:10] == day:
                acc[int(t[11:13])].append(float(x))
        obs[lid] = {h: sum(xs) / len(xs) for h, xs in acc.items() if len(xs) == 2}

    # 観測の連系線の潮流(OCCTO、30 分値 2 コマの平均)→ 区域ごとの「域外へ」の量 [MW]
    ic_h = {}
    for name, v in today.get("ic", {}).items():
        acc = defaultdict(list)
        for t, x in zip(today["times"], v):
            if x and x[0] is not None and t[:10] == day:
                acc[int(t[11:13])].append(float(x[0]))
        ic_h[name] = {h: sum(xs) / len(xs) for h, xs in acc.items() if len(xs) == 2}

    def zone_export(h):
        g = lambda k: ic_h.get(k, {}).get(h)  # noqa: E731
        hk, sf, fc = g("北海道・本州間電力連系設備"), g("相馬双葉幹線"), g("周波数変換設備")
        kc, ks, cs, ck = g("西播東岡山線・山崎智頭線"), g("阿南紀北直流幹線"), g("本四連系線"), g("関門連系線")
        fch, fho, fka = g("中部フェンス"), g("北陸フェンス"), g("関西フェンス")
        if None in (hk, sf, fc, kc, ks, cs, ck, fch, fho, fka):
            return None
        return {"hokkaido": hk, "tohoku": sf - hk, "tokyo": -sf + fc, "chubu": -fc + fch, "hokuriku": -fho,
                "kansai": kc + ks - fka, "chugoku": -kc + cs + ck, "shikoku": -ks - cs, "kyushu": -ck}

    dem = edf.day_demand(date)
    fm = ensure_fuelmix(a.date)
    for z, zd in (fm or {}).get("zones", {}).items():
        darr = (zd.get("fuels") or {}).get("demand") or []
        hh = dem.setdefault(z, {})
        for h, v in enumerate(darr):
            if v is not None and h not in hh:
                hh[h] = float(v)
    built = json.loads((ROOT / "docs/data/built/all.json").read_text())
    nodes, edges = built["nodes"], built["edges"]
    cfg = load_demand_config()
    pref_gwh, _ = pref_zone_gwh(nodes)
    demand_pd = pdm.load_point_demand()
    avail = sorted({h for hh in dem.values() for h in hh})

    result = {"date": a.date, "islands": {}}
    for island, freq in (("hokkaido", 50), ("east", 50), ("west", 60), ("okinawa", 60)):
        if island not in a.islands:
            continue
        net, bus_of, _ = build_island_net(island, nodes, edges, freq, {})
        attach_generators(net, bus_of, nodes, island, attach_mode="cap", stats=True)
        pinned, _ = pdm.match_buses(net, demand_pd)
        allocate_loads(net, cfg, pref_gwh=pref_gwh, point_demand=pinned)
        add_per_component_slacks(net)
        bnd_pts = edf.setup_day_boundary(net, island) if fm else []
        bnd_series = edf.day_boundary_series(fm, island) if fm else {}
        zl0 = net.load.groupby(net.load.bus.map(net.bus["zone"])).p_mw.sum()
        keys = line_keys(net)
        key2line = defaultdict(list)
        for li, k in keys.items():
            key2line[k].append(li)
        for t in ("switch", "trafo3w", "impedance", "dcline", "xward", "ward"):
            n = len(getattr(net, t, []))
            if n:
                print(f"  ! {island}: {t} が {n} 個ある(この試作の直流の式に入っていない)")

        fb, tb, bb, kind, idx = dc_structure(net)
        buses = list(net.bus.index)
        pos = {b: i for i, b in enumerate(buses)}
        nb = len(buses)
        f_i = np.array([pos[b] for b in fb]); t_i = np.array([pos[b] for b in tb])
        nbr = len(bb)
        Cf = sp.csr_matrix((np.ones(nbr), (np.arange(nbr), f_i)), shape=(nbr, nb))
        Ct = sp.csr_matrix((np.ones(nbr), (np.arange(nbr), t_i)), shape=(nbr, nb))
        Bf = sp.diags(bb) @ (Cf - Ct)
        Bbus = (Cf - Ct).T @ Bf
        ncomp, lab = sp.csgraph.connected_components(Bbus, directed=False)
        ref_buses = [pos[int(b)] for b in net.ext_grid[net.ext_grid.in_service].bus]
        ref_buses += [pos[int(b)] for b in net.gen[net.gen.in_service & net.gen.get("slack", False)].bus] \
            if "slack" in net.gen.columns else []
        is_ref = np.zeros(nb, bool); is_ref[ref_buses] = True
        comp_has_ref = np.zeros(ncomp, bool); comp_has_ref[lab[is_ref]] = True
        free = np.where(~is_ref & comp_has_ref[lab])[0]
        fpos = -np.ones(nb, int); fpos[free] = np.arange(len(free))
        lu = spla.splu(Bbus[free][:, free].tocsc())
        line_row = {li: r for r, (kd, li) in enumerate(zip(kind, idx)) if kd == "line"}

        # 観測の線(照合 A・B だけ。C は向きを決めていないので使わない)
        mon = []
        for r in cw["lines"]:
            if r.get("island") != island or r.get("conf") not in ("A", "B") or r.get("single_ended"):
                continue
            lid = f"{r['area']}|{r['line']}|{r['direction']}"
            if not obs.get(lid):
                continue
            seg0 = r["segs"][0]
            tot_par = sum(par for _, _, par in seg0)
            nco = r.get("n_circ_obs")
            scale = (nco / tot_par) if nco and tot_par > nco else 1.0
            rows = [(line_row[li], sg) for k, sg, _ in seg0 for li in key2line.get(k, []) if li in line_row]
            if not rows:
                continue
            mon.append({"id": lid, "kv": r["kv"], "conf": r["conf"], "rows": rows, "scale": scale, "area": r["area"]})
        M = len(mon)
        Sm = sp.lil_matrix((M, nb))
        for m, mm in enumerate(mon):
            for row, sg in mm["rows"]:
                Sm[m, :] += mm["scale"] * sg * Bf[row, :]
        Sm = Sm.tocsr()[:, free]
        H = lu.solve(np.asarray(Sm.todense()).T).T        # M × n_free(B は対称)
        main_comp = np.bincount(lab[free]).argmax()
        main_comp_all = np.bincount(lab).argmax()
        print(f"[{island}] 母線 {nb}・枝 {nbr}・成分 {ncomp}(基準あり {int(comp_has_ref.sum())})・観測の線 {M} 本")

        zone_of = net.bus["zone"].reindex(buses).to_numpy()
        hours = [h for h in avail if any(h in obs[mm["id"]] for mm in mon)]
        F0, FO, SIG, F1, CLOS = [], [], [], [], []
        dc_check = []
        for h in hours:
            nt = copy.deepcopy(net)
            for z, hh in dem.items():
                tgt = hh.get(h)
                cur = float(zl0.get(z, 0) or 0)
                if not tgt or cur <= 0:
                    continue
                mask = nt.load.bus.map(nt.bus["zone"]) == z
                nt.load.loc[mask, "p_mw"] *= tgt / cur
            balance_by_zone(nt, cfg, use_zone_src=True)
            if fm:
                edf.apply_fuel_actuals(nt, fm["zones"], h, island=island)
                for pt in bnd_pts:
                    series = bnd_series.get(tuple(pt["pair"]))
                    if series and h < len(series) and series[h] is not None:
                        nt.sgen.at[pt["sgen"], "p_mw"] = float(series[h]) * pt["share"]
            P = np.zeros(nb); L = np.zeros(nb); G = np.zeros(nb)
            g = nt.gen[nt.gen.in_service]
            np.add.at(P, [pos[int(b)] for b in g.bus], g.p_mw.astype(float).to_numpy())
            np.add.at(G, [pos[int(b)] for b in g.bus], g.max_p_mw.astype(float).clip(lower=0).fillna(0).to_numpy())
            s = nt.sgen[nt.sgen.in_service]
            if len(s):
                np.add.at(P, [pos[int(b)] for b in s.bus], s.p_mw.astype(float).to_numpy())
            ld = nt.load[nt.load.in_service]
            np.add.at(P, [pos[int(b)] for b in ld.bus], -ld.p_mw.astype(float).to_numpy())
            np.add.at(L, [pos[int(b)] for b in ld.bus], ld.p_mw.astype(float).abs().to_numpy())
            f0 = H @ P[free]
            # 収支を観測に合わせる: 区域ごとに(発電 − 需要)= 観測の「域外へ」になるよう、発電機に配る
            P1 = P.copy()
            tgt = zone_export(h)
            clos = {}
            if tgt:
                inmain_ = (lab == main_comp_all)
                gz = g["bus"].map(nt.bus["zone"])
                if "zone_src" in g.columns:
                    src = g["zone_src"]
                    gz = gz.where(~(src.notna() & (src != "")), src)
                gpos = np.array([pos[int(b)] for b in g.bus])
                gp = g.p_mw.astype(float).to_numpy()
                gcap = g.max_p_mw.astype(float).clip(lower=0).fillna(0).to_numpy()
                gin = inmain_[gpos]
                lpos = np.array([pos[int(b)] for b in ld.bus])
                lz = ld.bus.map(nt.bus["zone"]).to_numpy()
                lp = ld.p_mw.astype(float).to_numpy()
                lin = inmain_[lpos]
                for z in sorted({z for z in zone_of[inmain_] if isinstance(z, str)}):
                    if z not in tgt:
                        continue
                    gm = gin & (gz.to_numpy() == z)
                    lm = lin & (lz == z)
                    cur = gp[gm].sum() - lp[lm].sum()
                    c = tgt[z] - cur
                    if c > 0:
                        head = np.maximum(gcap[gm] - gp[gm], 0.0)
                        tot = head.sum()
                        add = head * min(c / tot, 1.0) if tot > 0 else np.zeros(gm.sum())
                        rest = c - add.sum()
                        if rest > 1 and gcap[gm].sum() > 0:      # 容量を超える分は容量の比で(帳簿に残す)
                            add = add + gcap[gm] / gcap[gm].sum() * rest
                    else:
                        tot = gp[gm].sum()
                        add = gp[gm] * (c / tot) if tot > 0 else np.zeros(gm.sum())
                    np.add.at(P1, gpos[gm], add)
                    clos[z] = (float(cur), float(tgt[z]), float(c))
            f1 = H @ P1[free]
            F1.append(f1); CLOS.append(clos)
            if a.balance and h in (3, 12, 18) and clos:
                print("    観測に合わせる直し: " + " ".join(f"{z} {cur:+.0f}→{t:+.0f}" for z, (cur, t, c) in clos.items())
                      + f" / 直した後の基準の肩代わり {-(P1[inmain_].sum()):+.0f} MW")
            if a.balance and h in (3, 12, 18):
                inmain = (lab == main_comp_all)
                zs = {}
                for z in sorted({z for z in zone_of[inmain] if isinstance(z, str)}):
                    mk = inmain & (zone_of == z)
                    zs[z] = (float(P[mk].sum()), float(L[mk].sum()), float(P[mk].sum() + L[mk].sum()))
                refs = [buses[i] for i in np.where(is_ref & inmain)[0]]
                rn = [(str(nt.bus.at[b, "name"])[:24], nt.bus.at[b, "zone"], float(nt.bus.at[b, "vn_kv"])) for b in refs]
                print(f"  収支 h={h}: 主成分の注入の合計 {P[inmain].sum():+.0f} MW(負なら基準の母線が同じだけ出す)・基準 {rn}")
                for z, (net_, load_, gen_) in zs.items():
                    print(f"    {z:9s} 発電 {gen_:8.0f} − 需要 {load_:8.0f} = 域外へ {net_:+8.0f} MW")
            if h == hours[len(hours) // 2]:      # 1 時刻だけ pandapower の直流潮流と比べる(式の確かめ)
                try:
                    pp.rundcpp(nt)
                    ref = np.array([sum(mm["scale"] * sg * float(nt.res_line.p_from_mw.at[idx[row]])
                                        for row, sg in mm["rows"]) for mm in mon])
                    dc_check = [float(np.nanmax(np.abs(ref - f0))), float(np.nanmedian(np.abs(ref))),
                                float(np.corrcoef(ref, f0)[0, 1])]
                    print(f"  直流の式の確かめ(h={h}): 最大の差 {dc_check[0]:.2f} MW・|潮流|の中央値 {dc_check[1]:.0f} MW・相関 {dc_check[2]:.6f}")
                except Exception as ex:  # noqa: BLE001
                    print(f"  ! rundcpp 失敗: {ex}")
            fo = np.array([obs[mm["id"]].get(h, np.nan) for mm in mon])
            F0.append(f0); FO.append(fo); SIG.append((L[free], G[free]))
        F0, FO, F1 = np.array(F0), np.array(FO), np.array(F1)       # 時刻 × 線

        # 区域ごとの収支を変えない式(主成分の中だけ)
        zones = sorted({z for z in zone_of[free] if isinstance(z, str)})
        Z = np.array([(zone_of[free] == z).astype(float) for z in zones])

        def score_(X):
            out = []
            for m in range(M):
                ok = ~np.isnan(FO[:, m]) & ~np.isnan(X[:, m])
                if ok.sum() < 6:
                    continue
                o, x = FO[ok, m], X[ok, m]
                mo = float(np.mean(np.abs(o)))
                rmse = float(np.sqrt(np.mean((x - o) ** 2)))
                r = float(np.corrcoef(o, x)[0, 1]) if np.std(o) > 1e-6 and np.std(x) > 1e-6 else None
                out.append({"id": mon[m]["id"], "kv": mon[m]["kv"], "obs": mo, "rmse": rmse, "r": r,
                            "nrmse": rmse / mo if mo > 1 else None,
                            "ratio": float(np.mean(np.abs(x))) / mo if mo > 1 else None,
                            "sign": bool(np.mean(o) * np.mean(x) > 0)})
            return out

        def line_(tag, rows):
            if not rows:
                return
            md = lambda k: st.median([x[k] for x in rows if x[k] is not None])  # noqa: E731
            ratio = [x["ratio"] for x in rows if x["ratio"] is not None]
            print(f"  {tag:26s} n={len(rows):3d} 誤差/観測 {md('nrmse'):.2f}  r {md('r'):+.2f}  ×2内 {sum(1 for x in ratio if 0.5 <= x <= 2) / len(ratio):.0%}"
                  f"  ×1.25内 {sum(1 for x in ratio if 0.8 <= x <= 1.25) / len(ratio):.0%}  向き {sum(1 for x in rows if x['sign']) / len(rows):.0%}"
                  f"  ΣRMSE/Σ|観測| {sum(x['rmse'] for x in rows) / sum(x['obs'] for x in rows):.2f}")
        sA, sB = score_(F0), score_(F1)
        line_("事前(いまのモデル)", sA); line_("収支を観測に合わせた後", sB)
        for kv in sorted({x["kv"] for x in sA}, reverse=True):
            line_(f"  {kv:.0f}kV 事前", [x for x in sA if x["kv"] == kv]); line_(f"  {kv:.0f}kV 合わせた後", [x for x in sB if x["kv"] == kv])
        result.setdefault("closure", {})[island] = {"prior": sA, "closed": sB}
        if a.closure_only:
            continue
        if a.use_closed:
            F0 = F1

        rng = random.Random(20261110)
        order = list(range(M)); rng.shuffle(order)
        folds = [order[i::a.folds] for i in range(a.folds)]
        isl_out = {"n_lines": M, "hours": hours, "dc_check": dc_check, "alphas": {}}
        for alpha in a.alphas:
            pred = np.full_like(F0, np.nan)
            fit = np.full_like(F0, np.nan)
            dnorm = []
            for ti, h in enumerate(hours):
                Lh, Gh = SIG[ti]
                svar = (alpha * Lh) ** 2 + (alpha * Gh) ** 2
                for fi, test in enumerate(folds + [[]]):       # 最後は全部使う当てはめ(伏せない)
                    test_set = set(test)
                    tr = [m for m in range(M) if m not in test_set and not np.isnan(FO[ti, m])]
                    if not tr:
                        continue
                    A = np.vstack([H[tr], Z])
                    y = np.concatenate([FO[ti, tr] - F0[ti, tr], np.zeros(len(zones))])
                    rvar = np.concatenate([np.maximum(20.0, 0.05 * np.abs(FO[ti, tr])) ** 2, np.full(len(zones), 1.0)])
                    AS = A * svar
                    K = AS @ A.T + np.diag(rvar)
                    w = np.linalg.solve(K, y)
                    d = AS.T @ w
                    if test:
                        pred[ti, test] = F0[ti, test] + H[test] @ d
                    else:
                        fit[ti, :] = F0[ti, :] + H @ d
                        dnorm.append((float(np.abs(d).sum()) / 2, float(Lh.sum()),
                                      float(np.sum((d < -Lh - Gh) | (d > Lh + Gh)))))

            def score(X):
                out = []
                for m in range(M):
                    ok = ~np.isnan(FO[:, m]) & ~np.isnan(X[:, m])
                    if ok.sum() < 6:
                        continue
                    o, x = FO[ok, m], X[ok, m]
                    mo = float(np.mean(np.abs(o)))
                    rmse = float(np.sqrt(np.mean((x - o) ** 2)))
                    r = float(np.corrcoef(o, x)[0, 1]) if np.std(o) > 1e-6 and np.std(x) > 1e-6 else None
                    out.append({"id": mon[m]["id"], "kv": mon[m]["kv"], "area": mon[m]["area"], "obs": mo, "rmse": rmse, "r": r,
                                "nrmse": rmse / mo if mo > 1 else None,
                                "ratio": float(np.mean(np.abs(x))) / mo if mo > 1 else None,
                                "sign": bool(np.mean(o) * np.mean(x) > 0)})
                return out

            def summ(rows):
                def med(k):
                    v = [x[k] for x in rows if x[k] is not None]
                    return round(st.median(v), 3) if v else None
                ratio = [x["ratio"] for x in rows if x["ratio"] is not None]
                return {"n": len(rows), "nrmse_med": med("nrmse"), "r_med": med("r"),
                        "r_gt_05": round(sum(1 for x in rows if x["r"] is not None and x["r"] > 0.5) / max(len(rows), 1), 3),
                        "within2": round(sum(1 for x in ratio if 0.5 <= x <= 2) / max(len(ratio), 1), 3),
                        "within125": round(sum(1 for x in ratio if 0.8 <= x <= 1.25) / max(len(ratio), 1), 3),
                        "sign": round(sum(1 for x in rows if x["sign"]) / max(len(rows), 1), 3),
                        "sum_rmse_over_sum_obs": round(sum(x["rmse"] for x in rows) / max(sum(x["obs"] for x in rows), 1), 3)}
            s0, s1, s2 = score(F0), score(pred), score(fit)
            if a.dump and alpha == a.alphas[-1]:
                print(f"  {'線路':40s} kV  照合 観測の平均  事前  当てはめ  伏せて予測 | 観測の最小〜最大")
                for m in np.argsort(-np.nanmean(np.abs(FO - fit), axis=0)):
                    print(f"  {mon[m]['id'][:38]:40s} {mon[m]['kv']:.0f} {mon[m]['conf']} {np.nanmean(FO[:, m]):8.0f} {np.nanmean(F0[:, m]):7.0f}"
                          f" {np.nanmean(fit[:, m]):7.0f} {np.nanmean(pred[:, m]):8.0f} | {np.nanmin(FO[:, m]):6.0f}〜{np.nanmax(FO[:, m]):6.0f}"
                          f"  枝 {len(mon[m]['rows'])} 本 倍率 {mon[m]['scale']:.2f}")
            moved = st.median(x[0] for x in dnorm) if dnorm else None
            load = st.median(x[1] for x in dnorm) if dnorm else None
            isl_out["alphas"][str(alpha)] = {"prior": summ(s0), "heldout": summ(s1), "insample": summ(s2),
                                             "moved_mw_med": moved, "load_mw_med": load,
                                             "bound_viol_med": st.median(x[2] for x in dnorm) if dnorm else None,
                                             "heldout_rows": s1, "prior_rows": s0}
            p, q, w_ = summ(s0), summ(s1), summ(s2)
            print(f"  α={alpha}: 事前 誤差/観測 {p['nrmse_med']} r {p['r_med']} ×2内 {p['within2']} 向き {p['sign']} ΣRMSE/Σ|観測| {p['sum_rmse_over_sum_obs']}"
                  f" | 伏せた線 誤差/観測 {q['nrmse_med']} r {q['r_med']} ×2内 {q['within2']} ×1.25内 {q['within125']} 向き {q['sign']} ΣRMSE/Σ|観測| {q['sum_rmse_over_sum_obs']}"
                  f" | 当てはめ {w_['nrmse_med']} | 動かした注入 {moved:.0f} MW(需要 {load:.0f} MW)")
        result["islands"][island] = isl_out
    if a.out:
        a.out.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
