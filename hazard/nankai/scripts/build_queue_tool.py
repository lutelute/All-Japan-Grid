#!/usr/bin/env python3
"""南海トラフ 復旧の待ち行列卓(1 枚の HTML)を組み立てる。

    PYTHONPATH=hazard/nankai/src:hazard/nankai/scripts python3 hazard/nankai/scripts/build_queue_tool.py \
        --out hazard/nankai/reports/nankai_hazard_2026-09-13/tool/nankai_restoration_queue.html

- 代表サンプル・作業班の拠点・他社応援・待ち行列は make_restoration_ops.py の関数をそのまま使う(動画と同じ前提)。
- ブラウザ(hazard/nankai/tool_queue/model.js)は、要員と資機材の被災・応援の到着・エリアごとの待ち行列・
  電源とのつながりを計算し直す。優先順位の切り替え、修理の順番の入れ替え、応援の送り先の配分を画面で操作できる。
- 停電需要家: ブラウザは「電源とつながっているか」だけを数える(直流潮流の過負荷連鎖は解かない)。
  既定の優先順位で測った差(潮流あり − つながりだけ)を時刻ごとの補正として足す。補正の当てはまりは
  優先順位 5 通りで Python の潮流ありと突き合わせて reference.json に残す(tool_queue/test_model.mjs が JS と照合)。
- 送配電事業者の台帳の生値は入れない。埋め込むのは解析モデルの母線・枝・発電機の接続と、修理ジョブの属性だけ。
"""
from __future__ import annotations
import argparse, base64, json, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd, yaml

import make_restoration_ops as M
from nankai.aggregate import bus_prefecture

NANKAI = M.NANKAI; ROOT = M.ROOT; CONFIG = M.CONFIG
TOOL = os.path.join(NANKAI, "tool_queue")
CLASSES = ["0", "1", "2", "3", "4", "5弱", "5強", "6弱", "6強", "7"]
# 停電需要家を数える時刻[日](ブラウザも同じ時刻で数える)
T_EVAL = np.array(sorted(set([0.0, 0.25, 0.5, 0.75] + list(np.arange(1.0, 14.0, 0.5)) + list(np.arange(14.0, 31.0, 1.0))
                             + list(np.arange(32.0, 91.0, 2.0)))), float)

# 優先順位(待ち行列の並べ方)。model.js の POLICIES と同じキー・同じ順
POLICIES = {
    "kv_load": lambda x, c: (-float(x[1].get("kv", 0)), -float(x[1].get("load_mw", 0))),
    "load": lambda x, c: -float(x[1].get("load_mw", 0)),
    "cust_per_day": lambda x, c: -c[(x[0], x[1]["id"])] / float(x[1]["duration_d"]),
    "short": lambda x, c: float(x[1]["duration_d"]),
    "long": lambda x, c: -float(x[1]["duration_d"]),
}


def b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode("ascii")


def cust_out(I, OPS, times, run_pf):
    """make_restoration_ops.customers_out と同じ数え方。run_pf=False は電源とのつながりだけ。"""
    tot = np.zeros(len(times))
    for isl, D in I.items():
        sim, d = D["sim"], D["d"]; ds, dl = OPS[isl]
        for k, t in enumerate(times):
            ba = (~(ds > t))[sim.bus_site]; bra = ~(dl > t); go = ~(d.done_gen > t)
            sim.cm.load = sim.load0 * sim._load_factor(d, t)
            r = sim.cm.evaluate(ba, bra, sim._gen_cap(t, go), run_pf=run_pf)
            sim.cm.load = sim.load0
            phys = r.connected & ~(d.blackout_until > t)
            tot[k] += float(((~phys) * D["cust"]).sum())
    return tot


def site_name(case, sim, i):
    names = case.bus.name.to_numpy()[sim.bus_site == i]
    real = [n for n in names if isinstance(n, str) and "junction" not in n]
    return real[0] if real else f"{case.bus.zone.iloc[sim.site_rows[i]]} 変電所 #{i}"


def export_jobs(I):
    rows, cdir = [], {}
    for isl, D in I.items():
        sim, d, case = D["sim"], D["d"], D["case"]; pref = D["pref"]
        for j in d.jobs:
            kind, i = j["id"]
            if kind == "s":
                row = sim.site_rows[i]; la, lo = float(case.bus.lat.iloc[row]), float(case.bus.lon.iloc[row])
                name = site_name(case, sim, i); ts = int(sim.site_ts[i]); c = float(D["cust"][sim.bus_site == i].sum()); p = pref[row]
                cl = str(D["cls"][row])
            else:
                br = case.branch.iloc[i]; la, lo = float(br.mid_lat), float(br.mid_lon)
                if not (np.isfinite(la) and np.isfinite(lo)):
                    la = float((case.bus.lat.iloc[br.f] + case.bus.lat.iloc[br.t]) / 2); lo = float((case.bus.lon.iloc[br.f] + case.bus.lon.iloc[br.t]) / 2)
                name = str(br["name"]) if isinstance(br["name"], str) else f"線路 #{i}"; ts = int(sim.br_ts[i]); c = 0.0; p = pref[br.f]
                cl = str(max(D["cls"][br.f], D["cls"][br.t], key=CLASSES.index))
            cdir[(isl, j["id"])] = c
            rows.append(dict(island=isl, kind=kind, idx=int(i), zone=j["zone"], kv=float(j.get("kv", 0)), load_mw=float(j.get("load_mw", 0)),
                             dur=float(j["duration_d"]), lat=round(la, 4), lon=round(lo, 4), name=name, pref=p if isinstance(p, str) else "",
                             ts=ts, cls=cl, cust=c))                     # 並べ替えに使う値は丸めない(Python と同じ順にする)
    return rows, cdir


def export_bases(I, bases):
    out = []
    for B in bases:
        D = I[B["island"]]; idx = B["idx"]
        out.append(dict(island=B["island"], zone=B["zone"], pref=B["pref"], lat=round(B["lat"], 4), lon=round(B["lon"], 4), crews_nom=B["crews_nom"],
                        cls=b64(np.array([CLASSES.index(str(c)) for c in D["cls"][idx]], np.uint8)),
                        ts=b64((D["sim"].bus_ts[idx] >= 1).astype(np.uint8)), w=b64(np.asarray(B["w"], np.float64))))
    return out


def export_grid(I):
    out = {}
    for isl, D in I.items():
        sim, d, case = D["sim"], D["d"], D["case"]; cm = sim.cm
        ng = len(sim.gb); ok = np.ones(ng, bool)
        ce, cl = sim._gen_cap(0.0, ok), sim._gen_cap(1.0, ok)              # 1 日未満 / 1 日以降の出力上限(停止機は done_gen で落とす)
        ginf = sim.gslack & cm.base_is_fragment[sim.gb]                     # 基底でフラグメントだった成分の仮想供給(無限扱い)
        keep = (ce > 0) | (cl > 0) | ginf                                   # 一度も電源にならない機は省く(つながり判定に効かない)
        n_site = len(sim.site_rows)
        out[isl] = dict(n_bus=int(case.n_bus), n_site=int(n_site), n_br=int(len(sim.bf)),
                        bus_site=b64(sim.bus_site.astype(np.int32)), cust=b64(np.asarray(D["cust"], np.float64)),
                        bo_until=b64(np.asarray(d.blackout_until, np.float64)),
                        f=b64(sim.bf.astype(np.int32)), t=b64(sim.bt.astype(np.int32)),
                        gb=b64(sim.gb[keep].astype(np.int32)), cap_e=b64(ce[keep].astype(np.float64)), cap_l=b64(cl[keep].astype(np.float64)),
                        ginf=b64(ginf[keep].astype(np.uint8)), done_gen=b64(np.asarray(d.done_gen, np.float64)[keep]), n_gen=int(keep.sum()))
    return out


def targets_all(I):
    """応援の到着目標(mutual_aid と同じ規則): 修理総量で重み付けした被災変電所の重心に最も近い被災変電所。全エリアぶん。"""
    pts = {}
    for isl, D in I.items():
        sim = D["sim"]
        for j in D["d"].jobs:
            kind, i = j["id"]
            if kind == "s":
                row = sim.site_rows[i]
                pts.setdefault(j["zone"], []).append((float(D["case"].bus.lat.iloc[row]), float(D["case"].bus.lon.iloc[row]), j["duration_d"]))
    out = {}
    for z, p in pts.items():
        P_ = np.array(p); w = P_[:, 2] / P_[:, 2].sum(); cla, clo = (w * P_[:, 0]).sum(), (w * P_[:, 1]).sum()
        m = np.argmin(M.gc_km(cla, clo, P_[:, 0], P_[:, 1])); out[z] = [float(P_[m, 0]), float(P_[m, 1])]
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); a = ap.parse_args()
    t0 = time.time()
    cfg = yaml.safe_load(open(os.path.join(CONFIG, "restoration_ops_scenario.yaml"), encoding="utf-8"))
    RP = yaml.safe_load(open(os.path.join(CONFIG, "restoration_default.yaml"), encoding="utf-8"))
    CB = RP["crews"]["base"]
    cust_c = yaml.safe_load(open(os.path.join(CONFIG, "customers.yaml"), encoding="utf-8"))["contracts_thousand"]
    I = M.build_islands(cfg)
    for D in I.values():
        D["pref"] = bus_prefecture(D["case"])
    bases = M.build_bases(I, cfg, CB)
    jbz = {}
    for D in I.values():
        for j in D["d"].jobs:
            jbz.setdefault(j["zone"], []).append(j)
    aid = M.mutual_aid(I, cfg, CB, jbz)
    jobs, cdir = export_jobs(I)
    print(f"代表サンプル {({k: D['seed'] for k, D in I.items()})}・修理 {len(jobs)} 件・拠点 {len(bases)}・応援の送り手 {list(aid['senders'])}", flush=True)

    # 既定の優先順位で補正(潮流あり − つながりだけ)を測り、他の優先順位で当てはまりを検算する
    ref = dict(t_eval=T_EVAL.tolist(), policies={})
    offset = None
    for name, kf in POLICIES.items():
        Q = M.run_queues(I, bases, cfg, aid, CB, key=lambda x, kf=kf: kf(x, cdir))
        OPS = M.ops_done_arrays(I, Q)
        full = cust_out(I, OPS, T_EVAL, True); conn = cust_out(I, OPS, T_EVAL, False)
        if offset is None:
            offset = full - conn
        corr = conn + offset
        end = {f"{isl}:{k}:{i}": float(en) for R in Q.values() for (isl, (k, i)), en in R["done"].items()}
        ref["policies"][name] = dict(full=full.round(1).tolist(), conn=conn.round(1).tolist(),
                                     resid_max=round(float(np.abs(corr - full).max()), 1), end=end,
                                     t_clear={z: R["t_clear"] for z, R in Q.items()})
        print(f"  {name:13s} 30日 潮流あり {full[T_EVAL == 30][0] / 1e4:6.1f}万・補正つき {corr[T_EVAL == 30][0] / 1e4:6.1f}万"
              f"・残差の最大 {np.abs(corr - full).max() / 1e4:.1f}万  ({time.time() - t0:.0f}s)", flush=True)

    val = M.val; P = cfg["personnel"]; E = cfg["equipment"]; A = cfg["mutual_aid"]
    params = dict(
        patrol_d=float(val(cfg["patrol_d"])),
        personnel=dict(unavailable_by_class=val(P["unavailable_by_class"]), tsunami_unavailable=float(val(P["tsunami_unavailable"])),
                       tau_shake_d=float(val(P["tau_shake_d"])), tau_tsunami_d=float(val(P["tau_tsunami_d"])), permanent_share=float(val(P["permanent_share"]))),
        equipment=dict(loss_if_inundated=float(val(E["loss_if_inundated"])), loss_by_class=val(E["loss_by_class"]), resupply_d=float(val(E["resupply_d"]))),
        aid=dict(crews_per_million=float(val(A["crews_per_million_customers"])), horizon_d=float(val(A["own_damage_horizon_d"])),
                 receiver_threshold_r=float(val(A["receiver_threshold_r"])), decision_d=float(val(A["decision_delay_d"])), mobilization_d=float(val(A["mobilization_d"])),
                 detour=float(val(A["detour_factor"])), speed_kmh=float(val(A["convoy_speed_kmh"])), drive_h=float(val(A["drive_h_per_day"])),
                 in_area_d=float(val(A["in_area_delay_d"])), return_d=float(val(A["return_after_clear_d"])),
                 waves=dict(offsets=[float(x) for x in A["waves"]["offsets_d"]], shares=[float(x) for x in A["waves"]["shares"]]),
                 ferry=dict(port_from=A["hokkaido_ferry"]["port_from"], port_to=A["hokkaido_ferry"]["port_to"], sea_d=float(A["hokkaido_ferry"]["sea_d"]),
                            waypoints=A["hokkaido_ferry"].get("sea_waypoints") or []),
                 excluded=list((A.get("excluded") or {}).keys())),
        horizon_d=400.0, dt_d=1 / 24)
    companies = dict(keys=list(cust_c.keys()), ja=[M.JA[z] for z in cust_c], contracts_thousand=[float(cust_c[z]) for z in cust_c],
                     crews_base=[float(CB.get(z, 10)) for z in cust_c], hq=[list(A["headquarters"]["coords"].get(z, [None, None, ""])) for z in cust_c])
    from build_scenario_tool import japan_outline
    data = dict(generated=time.strftime("%Y-%m-%d %H:%M"), classes=CLASSES, islands=list(I.keys()),
                seeds={k: int(D["seed"]) for k, D in I.items()}, jobs=jobs, bases=export_bases(I, bases), companies=companies,
                targets=targets_all(I), grid=export_grid(I), params=params, t_eval=T_EVAL.tolist(), offset=offset.round(1).tolist(),
                ref_default=dict(full=ref["policies"]["kv_load"]["full"]), outline=japan_outline())
    os.makedirs(TOOL, exist_ok=True)
    js = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    open(os.path.join(TOOL, "data.json"), "w", encoding="utf-8").write(js)
    json.dump(ref, open(os.path.join(TOOL, "reference.json"), "w"), ensure_ascii=False, separators=(",", ":"))
    if not os.path.exists(os.path.join(TOOL, "index.template.html")):
        print("tool_queue/index.template.html が無いので data.json と reference.json だけ書いた"); return
    tpl = open(os.path.join(TOOL, "index.template.html"), encoding="utf-8").read()
    html = (tpl.replace("/*__STYLE__*/", open(os.path.join(TOOL, "style.css"), encoding="utf-8").read())
               .replace("/*__MODEL__*/", open(os.path.join(TOOL, "model.js"), encoding="utf-8").read())
               .replace("/*__APP__*/", open(os.path.join(TOOL, "app.js"), encoding="utf-8").read())
               .replace("/*__DATA__*/", "window.QUEUE_DATA=" + js + ";"))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    open(a.out, "w", encoding="utf-8").write(html)
    print("html MB", round(os.path.getsize(a.out) / 1e6, 2), f"({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
