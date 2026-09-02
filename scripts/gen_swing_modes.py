#!/usr/bin/env python3
"""電気機械モード帯の全島推定(G_DB第一歩の検証器・2026-08-17).

機械集約(src/dynamics/machine_agg)+内部ノードSchur縮約の古典モデルで、
各周波数島の動揺モード周波数帯を推定する。フラット運転点近似(帯の推定・
運転点込みは次段)。出力: docs/reports/swing_modes_<date>.json

実行: PYTHONPATH=. python3 scripts/gen_swing_modes.py
前提: dist/ybus/{island}.npz (gen_ybus_numeric出荷。基準は load_ybus_npz が吸収)

── 運転点込み(トラックC③ 2026-09-02) ──────────────────────────────────
  # ① west ピーク断面を uc_to_pf_built の本番経路そのままで解いて pickle(ロジック複製なし)
  PYTHONPATH=. python3 scripts/gen_swing_modes.py --solve-west /tmp/west_ac_net.pkl
  # ② フラット vs AC 運転点のモード比較 + 最大機解列の過渡 + 図 + 報告
  PYTHONPATH=. python3 scripts/gen_swing_modes.py --ac-op west \
      --net-pickle /tmp/west_ac_net.pkl --date 2026-09-02
出力: docs/reports/swing_modes_<island>_ac_<date>.{json,md}
      docs/assets/dynamics/<island>_trip_ac_<date>.png / <island>_modes_ac_<date>.png
注意: 引数なしの従来経路は build_classical_model の対角修正(2026-09-02)後の値を書くので、
      08-17 の JSON(旧式 K・legacy_diag=True 相当)とは一致しない(比較は --ac-op 報告に記載)。
"""
from __future__ import annotations

import json
import os
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np                     # noqa: E402
import scipy.sparse as sp              # noqa: E402

from scripts.run_full_powerflow_from_db import (  # noqa: E402
    build_island_net, attach_generators)
from scripts.gen_ybus_numeric import load_ybus_npz  # noqa: E402
from src.dynamics.machine_agg import (  # noqa: E402
    aggregate_machines, build_classical_model)

ISLANDS = (("hokkaido", 50), ("east", 50), ("west", 60), ("okinawa", 60))
OUT = ROOT / "docs/reports/swing_modes_2026-08-17.json"


def solve_west_peak(out_pkl: str, island: str = "west") -> int:
    """uc_to_pf_built.main() を **そのまま** 走らせ、solve_hour の返り値(解き済み net)を
    pickle に退避する。条件は docs/reports/uc_pf_built_<island>_sel_<date>.json と同一
    (scenario fy2023r2・島純需要ピーク時刻・既定の介入群)。ロジックは複製しない。"""
    import pickle
    import time
    argv_bak = sys.argv
    sys.argv = ["uc_to_pf_built.py", "--islands", island,
                "--out", str(Path(out_pkl).with_suffix(".sel.json"))]
    import scripts.uc_to_pf_built as m
    orig = m.solve_hour

    def _wrap(net_t, mode):
        t0 = time.monotonic()
        net_s, used = orig(net_t, mode)
        with open(out_pkl, "wb") as f:
            pickle.dump({"net": net_s, "used": used, "island": island,
                         "solve_s": time.monotonic() - t0}, f)
        print(f"[solve-west] used={used} converged={getattr(net_s, 'converged', None)} "
              f"-> {out_pkl}")
        return net_s, used

    m.solve_hour = _wrap
    try:
        return int(m.main() or 0)
    finally:
        m.solve_hour = orig
        sys.argv = argv_bak


def _zone_shape(shape, sync, M):
    """モード形を地域ごとに H(=M) 重み平均 → {zone: value}(符号=揺れの向き)。"""
    acc, w = {}, {}
    for k, s in enumerate(sync):
        z = s.get("zone") or "?"
        acc[z] = acc.get(z, 0.0) + float(shape[k]) * float(M[k])
        w[z] = w.get(z, 0.0) + float(M[k])
    return {z: round(acc[z] / w[z], 3) for z in sorted(acc)}


def _mode_row(m, sync, M):
    from src.dynamics.machine_agg import mode_band
    return {"f_hz": round(m["f_hz"], 4), "zeta": round(m["zeta"], 4),
            "band": mode_band(m["f_hz"]),
            "participants": [{"name": sync[i]["name"][:40], "zone": sync[i]["zone"],
                              "kv": sync[i]["vn_kv"], "S_mva": round(sync[i]["S_mva"]),
                              "pf": round(float(m["participation"][i]), 3)}
                             for i in m["participants"][:5]],
            "zone_shape": _zone_shape(m["shape"], sync, M)}


def ac_operating_point_report(island: str, net_pickle: str, date: str,
                              D_mb: float | None = None) -> int:
    import pickle
    import time
    from src.dynamics.machine_agg import (
        D_MB_DEFAULT, _internal_bus_index, build_classical_model_ac,
        electromechanical_modes, mode_band)
    from src.dynamics.swing_solver import SwingModel, run_transient

    D_mb = D_MB_DEFAULT if D_mb is None else D_mb
    freq = dict(ISLANDS)[island]
    d = pickle.load(open(net_pickle, "rb"))
    net, used = d["net"], d["used"]
    if used != "ac":
        print(f"× {island}: 断面が AC 解でない(used={used}) — 運転点込みモデルは組めない")
        return 1

    # ── フラット(同一 net の内部 Ybus・負荷なし・E=1∠0)— 旧式/修正式/運転中機のみ ──
    lookup, V, Y, base = _internal_bus_index(net)
    agg = aggregate_machines(net)
    agg["sync"] = [dict(s, bus=int(lookup[s["bus"]])) for s in agg["sync"]
                   if 0 <= int(lookup[s["bus"]]) < Y.shape[0]]
    f_flat_legacy, _M1, _K1, _s1 = build_classical_model(Y, agg, base, freq, legacy_diag=True)
    f_flat_all, M_fa, K_fa, sync_fa = build_classical_model(Y, agg, base, freq)

    t0 = time.monotonic()
    cm = build_classical_model_ac(net, freq, committed_only=True,
                                  slack_mode="admittance", D_mb=D_mb)
    t_build = time.monotonic() - t0
    st = cm["stats"]
    sync = cm["sync"]
    committed_buses = {s["bus"] for s in sync}
    agg_c = {"sync": [dict(s, bus=int(lookup[s["bus"]])) for s in aggregate_machines(net)["sync"]
                      if s["bus"] in committed_buses]}
    f_flat_c, M_fc, K_fc, sync_fc = build_classical_model(Y, agg_c, base, freq)
    # フラット(運転中機)のモード形も同じ機械集合で(D は同じ仮定・単位で付ける)
    D_fc = np.array([D_mb * s["S_mva"] / base / (2 * np.pi * freq) for s in sync_fc])
    sync_fc_named = []
    by_int = {s["i"]: s for s in sync}
    for s in sync_fc:
        s2 = dict(s)
        src = by_int.get(int(s["bus"]))
        s2["name"] = src["name"] if src else str(s["bus"])
        s2["zone"] = src["zone"] if src else None
        s2["vn_kv"] = src["vn_kv"] if src else None
        sync_fc_named.append(s2)
    modes_flat = electromechanical_modes(M_fc, K_fc, D_fc)
    modes_ac = electromechanical_modes(cm["M"], cm["K"], cm["D"])

    def band_stats(freqs):
        f = np.asarray(freqs, float)
        return {"n_modes": int(len(f)),
                "f_min_hz": round(float(f.min()), 4) if len(f) else None,
                "f_median_hz": round(float(np.median(f)), 4) if len(f) else None,
                "f_max_hz": round(float(f.max()), 4) if len(f) else None,
                "n_inter_area_0.1_0.8": int(((f >= 0.1) & (f < 0.8)).sum()),
                "n_local_0.8_2.5": int(((f >= 0.8) & (f <= 2.5)).sum()),
                "n_out_of_band": int(((f < 0.1) | (f > 2.5)).sum())}

    fa = np.array([m["f_hz"] for m in modes_ac])
    ff = np.array([m["f_hz"] for m in modes_flat])
    sig_ac = np.array([m["sigma"] for m in modes_ac])
    # 非振動(実固有値)の不安定根の有無 — M⁻¹K の負固有値
    lam_ac = np.linalg.eigvals(np.diag(1.0 / cm["M"]) @ cm["K"])
    n_neg_ac = int((lam_ac.real < -1e-8).sum())

    # ── 過渡: N-1 解列 ──
    #   ケースA: 最大単独発電所(バスに 1 発電所だけ載る機械のうち P 最大)= 現実的な N-1
    #   ケースB: 最大集約バス(同一バスに複数発電所が集約された最大の P)= 母線事故相当(参考)
    #   各ケースで失歩機(COI 相対で 180° を超えた機械)を検出し、失歩機を定アドミタンスに
    #   置換して再計算(「残りの同期系」が第一波を保つか)。
    def _run_case(cm_, idx, label):
        model = SwingModel.from_classical(cm_)
        sync_ = cm_["sync"]
        t0 = time.monotonic()
        res = run_transient(model, t_end=10.0, fault="disconnect", fault_bus=idx,
                            t_fault=1.0, dt=0.01)
        t_sim = time.monotonic() - t0
        H = np.array([g.H for g in model.generators])
        keep = np.ones(len(sync_), bool); keep[idx] = False
        w = H * keep / (H * keep).sum()
        coi_f = (w @ res.omega) / (2 * np.pi)
        # 失歩判定は COI 相対でなく**残存機の角度中央値**相対で行う: 1 台でも大慣性機が
        # 暴走すると COI が引きずられ全機が「失歩」に見える(2026-09-02 west で実際に起きた)。
        # 中央値は少数の暴走機に影響されない
        med = np.median(res.delta[keep], axis=0)
        relm = res.delta - med[None, :]
        dev = np.abs(relm - relm[:, [0]]).max(axis=1); dev[idx] = 0.0
        slipped = [i for i in range(len(sync_)) if keep[i] and dev[i] > np.pi]
        ok = keep.copy(); ok[slipped] = False
        # COI(周波数・図)は失歩機を除いた残存機で取る
        if ok.sum() >= 1:
            w = H * ok / (H * ok).sum()
            coi_f = (w @ res.omega) / (2 * np.pi)
            coi_delta = w @ res.delta
            rel = res.delta - coi_delta[None, :]
        sep_ok = (res.delta[ok].max(axis=0) - res.delta[ok].min(axis=0)) if ok.sum() > 1 else np.zeros_like(res.t)
        zones_ = sorted({s_["zone"] for s_ in sync_ if s_["zone"]})
        zf = {}
        for z in zones_:
            mk = np.array([s_["zone"] == z for s_ in sync_]) & keep
            if mk.any():
                wz = H * mk / (H * mk).sum()
                zf[z] = round(float((wz @ res.omega)[-1] / (2 * np.pi)), 4)
        post = res.t >= 1.0
        swing = np.degrees(rel[:, post].max(axis=1) - rel[:, post].min(axis=1)); swing[idx] = 0.0
        return {
            "label": label,
            "slip_criterion": "残存機の角度中央値に対する相対角の変化が 180° 超(COI 基準は暴走機に引きずられるため不採用)",
            "tripped": {"name": sync_[idx]["name"][:60], "zone": sync_[idx]["zone"],
                        "kv": sync_[idx]["vn_kv"], "P_mw": round(sync_[idx]["P_mw"], 1),
                        "S_mva": round(sync_[idx]["S_mva"])},
            "n_machines": int(len(sync_)),
            "stable_first_swing_all": bool(res.stable),
            "max_angle_sep_deg": round(float(np.degrees(res.max_angle_sep)), 1),
            "t_first_180deg_s": (round(float(res.t[np.argmax(np.degrees(res.delta[keep].max(axis=0) - res.delta[keep].min(axis=0)) > 180)]), 2)
                                 if not res.stable else None),
            "slipped_machines": [{"name": sync_[i]["name"][:40], "zone": sync_[i]["zone"],
                                  "kv": sync_[i]["vn_kv"], "S_mva": round(sync_[i]["S_mva"]),
                                  "P_mw": round(sync_[i]["P_mw"], 1),
                                  "K_ii_per_S": round(float(cm_["K"][i, i] / sync_[i]["S_mva"]), 3)}
                                 for i in slipped],
            "stable_excluding_slipped": bool(sep_ok.max() < np.pi) if ok.sum() > 1 else None,
            "max_angle_sep_excluding_slipped_deg": round(float(np.degrees(sep_ok.max())), 1) if ok.sum() > 1 else None,
            "coi_freq_dev_hz": {"min": round(float(coi_f.min()), 4), "end": round(float(coi_f[-1]), 4)},
            "zone_freq_dev_end_hz": zf,
            "top_swing_machines": [{"name": sync_[i]["name"][:40], "zone": sync_[i]["zone"],
                                    "S_mva": round(sync_[i]["S_mva"]), "swing_deg": round(float(swing[i]), 1)}
                                   for i in np.argsort(-swing)[:5]],
            "sim_s": round(t_sim, 2),
            "_res": res, "_keep": keep, "_coi_f": coi_f, "_rel": rel, "_H": H, "_sync": sync_,
        }

    # 単独発電所バス: net.gen の行が 1 つだけのバス(集約でない)
    n_rows = net.gen.groupby("bus").size().to_dict()
    single = [k for k, s_ in enumerate(sync) if n_rows.get(s_["bus"], 0) == 1]
    idxA = int(max(single, key=lambda k: sync[k]["P_mw"])) if single else int(np.argmax([s_["P_mw"] for s_ in sync]))
    idxB = int(np.argmax([s_["P_mw"] for s_ in sync]))
    cases = [_run_case(cm, idxA, "A: 最大単独発電所の解列(N-1 gen)")]
    if idxB != idxA:
        cases.append(_run_case(cm, idxB, "B: 最大集約バスの解列(母線事故相当・参考)"))
    # 失歩機を外した「残りの同期系」の再評価(ケースA)
    slipped_buses = {sync[i]["bus"] for i in range(len(sync))
                     if any(m["name"] == sync[i]["name"][:40] for m in cases[0]["slipped_machines"])}
    cases_excl = []
    if slipped_buses:
        cm_x = build_classical_model_ac(net, freq, committed_only=True, slack_mode="admittance",
                                        D_mb=D_mb, exclude_buses=slipped_buses)
        nameA = sync[idxA]["name"]
        hit = [k for k, s_ in enumerate(cm_x["sync"]) if s_["name"] == nameA]
        if len(cm_x["sync"]) >= 3 and hit:
            cases_excl.append(_run_case(cm_x, hit[0], f"A': 失歩機 {len(slipped_buses)} 台を定アドミタンス化した残りの同期系で A を再計算"))
    # 失歩機を外した残りの同期系のモード(最低モードが弱連系機の局所モードでないことの確認)
    modes_x_rows = []
    if slipped_buses and len(cm_x["sync"]) >= 3:
        modes_x = electromechanical_modes(cm_x["M"], cm_x["K"], cm_x["D"])
        modes_x_rows = [_mode_row(m, cm_x["sync"], cm_x["M"]) for m in modes_x[:4]]
    primary = cases[0]
    res, keep, coi_f, rel, H = primary["_res"], primary["_keep"], primary["_coi_f"], primary["_rel"], primary["_H"]
    big = sync[idxA]; idx = idxA
    zones = sorted({s_["zone"] for s_ in sync if s_["zone"]})
    zone_f_end = primary["zone_freq_dev_end_hz"]
    top_swing = primary["top_swing_machines"]
    t_sim = primary["sim_s"]
    res_trip = run_transient(SwingModel.from_classical(cm), t_end=10.0, fault="trip",
                             fault_bus=idx, t_fault=1.0, dt=0.01)

    def _pub(c):
        return {k: v for k, v in c.items() if not k.startswith("_")}

    report = {
        "date": date, "island": island, "freq_hz": freq,
        "net_source": {"pickle": os.path.basename(net_pickle), "used": used,
                       "scenario_meta": "uc_to_pf_built 本番経路(fy2023r2・ピーク時刻・既定介入群)",
                       "n_bus": int(len(net.bus)), "n_bus_main": st["n_bus_main"],
                       "base_mva": base},
        "assumptions": {
            "machine_model": "古典機(E'一定・xd''背後)。H/xd'' は型式別典型値(machine_agg.TYPE_PARAMS)",
            "D_mb": D_mb,
            "D_note": "D は AVR/PSS/ガバナ/負荷周波数依存の総和の代理(仮定値)。減衰比 ζ は帯の目安で実測ではない",
            "loads": "運転点の定アドミタンス(y=conj(S)/|V|²)。IBR gen・sgen・容量ゼロ gen・停止機の Q・銘板超過機・slack も同様",
            "slack": f"主成分 slack {st['slack_mw']:.0f}MW を定アドミタンス(負性負荷)に — 無限大母線では無い",
            "network": "内部順序 Ybus(シャント込み・pandapower 内部行列)= 潮流と同一の網",
            "committed_only": "運転中(|P|≥0.5MW)の同期機のみ。停止機は Q を定アドミタンスで残す",
            "capability_check": "|P+jQ| > 銘板 S の機械(Q制限なし PF の artifact)は古典機から外し定アドミタンス",
            "fragments": "最大連結成分の機械のみ(断片は別同期系・注入は定アドミタンス)",
        },
        "classical_model": {k: st[k] for k in sorted(st)},
        "equilibrium_check_pu": st["pe_pm_mismatch_pu_max"],
        "build_s": round(t_build, 1),
        "flat_vs_ac": {
            "flat_legacy_all_machines(08-17式・対角にB_ii余分)": band_stats(f_flat_legacy),
            "flat_fixed_all_machines": band_stats(f_flat_all),
            "flat_fixed_committed": band_stats(ff),
            "ac_operating_point_committed": band_stats(fa),
            "n_machines": {"all": len(sync_fa), "committed": len(sync)},
            "published_2026-08-17": {"flat_npz_ybus_all_machines_f_min_hz": 0.375,
                                     "gen_swing_map_ac_no_load_admittance_f0_hz": 0.434},
        },
        "ac_modes": {
            "n_unstable_oscillatory(sigma>0)": int((sig_ac > 1e-9).sum()),
            "n_negative_real_eigen_of_MinvK": n_neg_ac,
            "zeta_min": round(float(np.min([m["zeta"] for m in modes_ac])), 4) if modes_ac else None,
            "zeta_median_interarea": (round(float(np.median([m["zeta"] for m in modes_ac
                                                             if mode_band(m["f_hz"]) == "inter-area"])), 4)
                                      if any(mode_band(m["f_hz"]) == "inter-area" for m in modes_ac) else None),
            "lowest_8": [_mode_row(m, sync, cm["M"]) for m in modes_ac[:8]],
            "excluding_slipped_lowest_4": modes_x_rows,
            "excluding_slipped_note": "過渡で失歩した弱連系機を定アドミタンス化した残りの同期系(A' と同じ機械集合)の最低モード",
        },
        "flat_modes_committed": {"lowest_8": [_mode_row(m, sync_fc_named, M_fc) for m in modes_flat[:8]]},
        "transient_disconnect": {
            "t_fault_s": 1.0, "t_end_s": 10.0, "solver": "RK45 rtol1e-6",
            "method": "解列=内部ノードの Kron 消去(swing_solver.run_transient fault='disconnect')。"
                      "失歩機=COI 相対角の変化が 180° を超えた機械",
            "cases": [_pub(c) for c in cases] + [_pub(c) for c in cases_excl],
            "note": "負荷=定アドミタンス・ガバナ無し・D のみ → 解列後は周波数が単調低下(一次周波数応答は未モデル)。第一波の同期維持のみ判定",
        },
        "transient_legacy_trip_Pm0": {
            "case": "A と同じ機械", "stable": bool(res_trip.stable),
            "max_angle_sep_deg": round(float(np.degrees(res_trip.max_angle_sep)), 1),
            "note": "旧 'trip'(Pm→0・機械は同期網に残る)。解列とは物理が異なる — 後方互換で残す",
        },
    }
    out_json = ROOT / f"docs/reports/swing_modes_{island}_ac_{date}.json"
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── 図 ──
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.family"] = ["Hiragino Sans", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    figdir = ROOT / "docs/assets/dynamics"
    figdir.mkdir(parents=True, exist_ok=True)
    zcol = {"kyushu": "#d62728", "chugoku": "#ff7f0e", "shikoku": "#bcbd22",
            "kansai": "#2ca02c", "hokuriku": "#17becf", "chubu": "#1f77b4"}
    fig, axes = plt.subplots(3, 1, figsize=(11, 12), dpi=140)
    ax = axes[0]
    order = np.argsort(-np.array([s["S_mva"] for s in sync]))
    shown = [i for i in order if i != idx][:14]
    for i in shown:
        ax.plot(res.t, np.degrees(rel[i]) - np.degrees(rel[i, 0]),
                color=zcol.get(sync[i]["zone"], "gray"), lw=1.0,
                label=f"{sync[i]['name'][:14]}({sync[i]['zone']})")
    ax.axvline(1.0, color="k", ls=":", lw=0.8)
    ax.set_ylabel("δ − δ_COI の変化 [deg]")
    ax.set_title(f"{island} 最大単独発電所の解列(ケースA): {big['name'][:24]}({big['zone']} {big['P_mw']:.0f}MW) "
                 f"@t=1s — 第一波{'安定' if res.stable else '不安定'}・最大角差 "
                 f"{np.degrees(res.max_angle_sep):.1f}°(容量上位14機・地域色)", fontsize=10)
    ax.legend(fontsize=6, ncol=4, loc="upper left")
    ax.grid(alpha=0.3)
    ax = axes[1]
    ax.plot(res.t, coi_f, "k", lw=1.5, label="COI(H加重)")
    for z in zones:
        mk = np.array([s["zone"] == z for s in sync]) & keep
        if mk.any():
            wz = H * mk / (H * mk).sum()
            ax.plot(res.t, (wz @ res.omega) / (2 * np.pi), color=zcol.get(z, "gray"), lw=0.9, label=z)
    ax.axvline(1.0, color="k", ls=":", lw=0.8)
    ax.set_ylabel("周波数偏差 [Hz]")
    ax.set_title("地域別 H 加重の周波数偏差(ガバナ無し・負荷=定アドミタンス → 単調低下は仕様)", fontsize=10)
    ax.legend(fontsize=7, ncol=4)
    ax.grid(alpha=0.3)
    ax = axes[2]
    sep = np.degrees(res.delta[keep].max(axis=0) - res.delta[keep].min(axis=0))
    ax.plot(res.t, sep, "b", lw=1.2, label="解列(disconnect)")
    sep2 = np.degrees(res_trip.delta.max(axis=0) - res_trip.delta.min(axis=0))
    ax.plot(res_trip.t, sep2, "gray", lw=0.9, ls="--", label="旧 trip(Pm→0・同期網に残留)")
    ax.axhline(180.0, color="r", ls=":", lw=0.8, label="180°(失歩判定)")
    ax.set_xlabel("t [s]"); ax.set_ylabel("最大角差 [deg]")
    ax.legend(fontsize=7); ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(figdir / f"{island}_trip_ac_{date}.png", bbox_inches="tight")
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2), dpi=140)
    ax = axes[0]
    bins = np.linspace(0, max(3.5, float(max(fa.max(), ff.max()))), 40)
    ax.hist(ff, bins=bins, alpha=0.55, label=f"フラット(運転中{len(sync_fc)}機)", color="gray")
    ax.hist(fa, bins=bins, alpha=0.55, label=f"AC運転点(運転中{len(sync)}機)", color="#1f77b4")
    ax.axvspan(0.1, 0.8, color="orange", alpha=0.08); ax.axvspan(0.8, 2.5, color="green", alpha=0.06)
    ax.set_xlabel("モード周波数 [Hz]"); ax.set_ylabel("モード数")
    ax.set_title(f"モード分布: 最低 {ff.min():.3f}→{fa.min():.3f} Hz(フラット→AC)", fontsize=10)
    ax.legend(fontsize=8); ax.grid(alpha=0.3)
    ax = axes[1]
    zs = np.array([m["zeta"] for m in modes_ac])
    cols = ["orange" if mode_band(f) == "inter-area" else ("green" if mode_band(f) == "local" else "gray") for f in fa]
    ax.scatter(fa, zs * 100, c=cols, s=12, alpha=0.8)
    ax.set_xlabel("f [Hz]"); ax.set_ylabel("減衰比 ζ [%]")
    ax.set_title(f"AC運転点の f–ζ(D_mb={D_mb} 仮定・橙=inter-area 緑=local)", fontsize=10)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(figdir / f"{island}_modes_ac_{date}.png", bbox_inches="tight")
    plt.close(fig)

    # ── Markdown ──
    def _fmt_modes(rows):
        lines = ["| f [Hz] | ζ | 帯 | 参加率上位(地域) | 地域別モード形(H加重) |", "|---|---|---|---|---|"]
        for r in rows:
            parts = ", ".join(f"{p['name'][:16]}({p['zone']},{p['pf']:.2f})" for p in r["participants"][:3])
            zs_ = " ".join(f"{z}:{v:+.2f}" for z, v in r["zone_shape"].items())
            lines.append(f"| {r['f_hz']:.3f} | {r['zeta']:.3f} | {r['band']} | {parts} | {zs_} |")
        return "\n".join(lines)

    fv = report["flat_vs_ac"]
    _case_rows = "\n".join(
        f"| {c['label']} | {c['tripped']['name'][:22]}({c['tripped']['zone']} {c['tripped']['kv']:.0f}kV {c['tripped']['P_mw']:.0f}MW) | "
        f"{c['n_machines']} | {'安定' if c['stable_first_swing_all'] else '**不安定**'} | {c['max_angle_sep_deg']:.0f}° | "
        f"{c['t_first_180deg_s'] if c['t_first_180deg_s'] is not None else '—'} s | "
        f"{', '.join(m['name'][:14] + '(' + m['zone'] + ' ' + f"{m['kv']:.0f}kV" + ' K/S=' + f"{m['K_ii_per_S']:.2f}" + ')' for m in c['slipped_machines']) or 'なし'} | "
        f"{('安定' if c['stable_excluding_slipped'] else '不安定') if c['stable_excluding_slipped'] is not None else '—'}"
        f"({c['max_angle_sep_excluding_slipped_deg']}°) | {c['coi_freq_dev_hz']['end']:+.3f} Hz |"
        for c in report["transient_disconnect"]["cases"])
    md = f"""# {island} 多機動揺モデルの AC 運転点化 — フラット vs 運転点込み・最大機解列({date})

- 断面: uc_to_pf_built 本番経路(fy2023r2・{island} 純需要ピーク時刻・既定介入群 #37/#41 込み)の
  **AC 収束解**(`{os.path.basename(net_pickle)}`・used={used})。網={report['net_source']['n_bus']}バス
  (主成分 {st['n_bus_main']})・base={base:g} MVA
- モデル: 古典機(型式別典型 H/xd″)。**運転点で Pe(δ0)=Pm が機械精度で成立**
  (最大不整合 {st['pe_pm_mismatch_pu_max']:.1e} pu)。実装 `src/dynamics/machine_agg.build_classical_model_ac`
- 仮定(必ず添える): D_mb={D_mb}(減衰は仮定値・ζ は帯の目安)。負荷・IBR・slack({st['slack_mw']:.0f}MW)は
  運転点の定アドミタンス。停止機 {st['n_gen_off_excluded']} 台は Q のみ定アドミタンスで残置。
  銘板超過(|S|>S_mva・Q制限なし PF の artifact)で外した機械 {st['n_over_capability_excluded']} 台
  ({st.get('over_capability_mvar', 0):.0f} MVar)。断片の機械 {st['n_gen_fragment_excluded']} 台は別同期系。
  容量ゼロ gen {st.get('n_zero_cap_gen', 0)} 台の Q({st.get('zero_cap_gen_mvar', 0):.0f} MVar)も定アドミタンス

## 1. 何が変わったか(フラット → AC 運転点)

| モデル | 機械数 | モード数 | 最低 [Hz] | 中央値 [Hz] | inter-area(0.1–0.8) | local(0.8–2.5) | 帯外 |
|---|---|---|---|---|---|---|---|
| フラット・旧式(08-17 の K・対角に −B_ii 余分) | {fv['n_machines']['all']} | {fv['flat_legacy_all_machines(08-17式・対角にB_ii余分)']['n_modes']} | {fv['flat_legacy_all_machines(08-17式・対角にB_ii余分)']['f_min_hz']} | {fv['flat_legacy_all_machines(08-17式・対角にB_ii余分)']['f_median_hz']} | {fv['flat_legacy_all_machines(08-17式・対角にB_ii余分)']['n_inter_area_0.1_0.8']} | {fv['flat_legacy_all_machines(08-17式・対角にB_ii余分)']['n_local_0.8_2.5']} | {fv['flat_legacy_all_machines(08-17式・対角にB_ii余分)']['n_out_of_band']} |
| フラット・修正式(全同期機) | {fv['n_machines']['all']} | {fv['flat_fixed_all_machines']['n_modes']} | {fv['flat_fixed_all_machines']['f_min_hz']} | {fv['flat_fixed_all_machines']['f_median_hz']} | {fv['flat_fixed_all_machines']['n_inter_area_0.1_0.8']} | {fv['flat_fixed_all_machines']['n_local_0.8_2.5']} | {fv['flat_fixed_all_machines']['n_out_of_band']} |
| フラット・修正式(運転中機のみ) | {fv['n_machines']['committed']} | {fv['flat_fixed_committed']['n_modes']} | {fv['flat_fixed_committed']['f_min_hz']} | {fv['flat_fixed_committed']['f_median_hz']} | {fv['flat_fixed_committed']['n_inter_area_0.1_0.8']} | {fv['flat_fixed_committed']['n_local_0.8_2.5']} | {fv['flat_fixed_committed']['n_out_of_band']} |
| **AC 運転点(運転中機・負荷込み)** | {fv['n_machines']['committed']} | {fv['ac_operating_point_committed']['n_modes']} | **{fv['ac_operating_point_committed']['f_min_hz']}** | {fv['ac_operating_point_committed']['f_median_hz']} | {fv['ac_operating_point_committed']['n_inter_area_0.1_0.8']} | {fv['ac_operating_point_committed']['n_local_0.8_2.5']} | {fv['ac_operating_point_committed']['n_out_of_band']} |

公表済み参考値(2026-08-17): フラット(npz Ybus・全機・旧式 K) 最低 0.375 Hz / gen_swing_map(AC E∠δ・負荷アドミタンス無し) 0.434 Hz。

**フラット経路の対角項の誤りを修正した**(`build_classical_model`): 旧式は K = −B + diag(ΣB − B_ii) で
対角に −B_ii が余分に乗り、剛体回転モードが消えて周波数が上振れしていた(2 機系のテストで固定・
`legacy_diag=True` で旧式を再現可)。08-17 の帯はこの旧式の値である。

AC 運転点の固有値: 振動モードの不安定根(σ>0) {report['ac_modes']['n_unstable_oscillatory(sigma>0)']} /
M⁻¹K の負の実固有値 {n_neg_ac}(負の同期化トルク=運転点が非物理な機械。0 なら全機が同期化トルク正)。
ζ 最小 {report['ac_modes']['zeta_min']}・inter-area 帯の ζ 中央値 {report['ac_modes']['zeta_median_interarea']}(D_mb={D_mb} の仮定に比例)。

### AC 運転点の最低 8 モード
{_fmt_modes(report['ac_modes']['lowest_8'])}

### フラット(運転中機・同じ機械集合)の最低 8 モード
{_fmt_modes(report['flat_modes_committed']['lowest_8'])}

### 失歩機(弱連系)を外した残りの同期系の最低 4 モード(A' と同じ機械集合)
{_fmt_modes(report['ac_modes']['excluding_slipped_lowest_4']) if report['ac_modes']['excluding_slipped_lowest_4'] else '(失歩機なし)'}

最低モードの参加率が 1 機に集中している場合、それは系統の長軸振動でなく**その機械の弱連系(局所)モード**である。
残りの同期系の最低モードの地域別モード形が、系統本来の inter-area(西側⇔東側の逆位相)を表す。

図: `docs/assets/dynamics/{island}_modes_ac_{date}.png`

## 2. 過渡: N-1 解列(disconnect)

解列は内部ノードの Kron 消去(`swing_solver.run_transient(fault="disconnect")`・新設。旧 'trip' は
Pm→0 で機械が同期網に残る別物理・後方互換で残置)。失歩機 = **残存機の角度中央値**に対する相対角の変化が
180° を超えた機械(COI 基準は 1 台の暴走で全機が失歩に見えるため不採用)。
ガバナ無し・負荷=定アドミタンスなので解列後の周波数は単調低下(一次周波数応答は未モデル)。

| ケース | 解列機 | 機械数 | 第一波(全機) | 最大角差 | 180°到達 | 失歩機 | 失歩機を除く残りの同期 | COI Δf(10s) |
|---|---|---|---|---|---|---|---|---|
{_case_rows}

失歩機の共通点: **`K_ii/S`(容量あたり同期化トルク)が桁違いに小さい** = 弱い連系(66kV 接続の大型機など、
接続点の artifact)。失歩は機械の特性でなく**接続先の弱さ**が原因で、介入#41(capkv)後もなお残る接続の課題として開示する。
地域別 10 s 時点の周波数偏差(ケースA): {' / '.join(f'{z} {v:+.3f}' for z, v in zone_f_end.items())} Hz。
揺れの大きい機械(ケースA・COI 相対振幅上位): {'; '.join(f"{r['name'][:18]}({r['zone']}) {r['swing_deg']:.0f}°" for r in top_swing[:4])}。
計算 {t_sim:.1f} s / ケース(右辺ベクトル化・{len(sync)} 機)。旧 trip(Pm→0)では最大角差 {np.degrees(res_trip.max_angle_sep):.0f}°。

図(ケースA): `docs/assets/dynamics/{island}_trip_ac_{date}.png`

## 3. 限界(誠実性)

1. 古典機モデル(E' 一定・AVR/PSS/ガバナ無し)。減衰 D は仮定値 → ζ の絶対値は使えない(相対比較まで)
2. H・xd″ は型式別典型値(個別実測なし)。同一バス集約は容量加重・並列合成
3. 網の R/X は合成値(電圧階級別標準)+様式5照合済みの範囲。負荷は定アドミタンス(ZIP 未導入)
4. Q 制限なしの PF が小型機に数百 MVar を負わせる artifact は本段で「外して開示」した。根本は PF 側の
   Q 制限(介入候補)
5. 断面は 1 時刻(ピーク)。運転点依存なので他時刻では帯が動く(24 断面化は次段)
"""
    out_md = ROOT / f"docs/reports/swing_modes_{island}_ac_{date}.md"
    out_md.write_text(md, encoding="utf-8")
    print(f"{island}: AC運転点 {len(sync)}機 モード{len(fa)} 最低{fa.min():.3f}Hz "
          f"(フラット運転中機 {ff.min():.3f}Hz) ζmin={report['ac_modes']['zeta_min']} "
          f"negK={n_neg_ac} | 解列A {big['name'][:16]} {big['P_mw']:.0f}MW → "
          f"{'安定' if res.stable else '不安定'} 最大角差{np.degrees(res.max_angle_sep):.0f}° "
          f"失歩{len(primary['slipped_machines'])}機 残り{'安定' if primary['stable_excluding_slipped'] else '不安定'} "
          f"COI Δf(10s)={coi_f[-1]:+.3f}Hz")
    print(f"→ {out_json.relative_to(ROOT)} / {out_md.relative_to(ROOT)}")
    return 0


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--solve-west", metavar="PKL",
                    help="west ピーク断面を uc_to_pf_built 本番経路で解いて pickle")
    ap.add_argument("--ac-op", metavar="ISLAND", help="運転点込み報告(要 --net-pickle)")
    ap.add_argument("--net-pickle", metavar="PKL")
    ap.add_argument("--date", default=None)
    ap.add_argument("--d-mb", type=float, default=None, help="減衰係数の仮定(機械ベース pu)")
    args = ap.parse_args()
    if args.solve_west:
        return solve_west_peak(args.solve_west)
    if args.ac_op:
        if not args.net_pickle:
            ap.error("--ac-op には --net-pickle が要る(--solve-west で作る)")
        import datetime as _dt
        return ac_operating_point_report(args.ac_op, args.net_pickle,
                                         args.date or _dt.date.today().isoformat(),
                                         D_mb=args.d_mb)
    return main_flat()


def main_flat() -> int:
    built = json.loads((ROOT / "docs/data/built/all.json").read_text(encoding="utf-8"))
    nodes, edges = built["nodes"], built["edges"]
    res = {}
    for island, freq in ISLANDS:
        Y, base, z = load_ybus_npz(ROOT / f"dist/ybus/{island}.npz")
        Y = Y.tocsc()   # pu@base(共有ローダがv5.0.0以前の表記バグを吸収)
        net, bus_of, _ = build_island_net(island, nodes, edges, freq, {})
        attach_generators(net, bus_of, nodes, island)
        pos = {b: i for i, b in enumerate(np.asarray(z["bus_pp"]))}
        agg = aggregate_machines(net)
        agg["sync"] = [dict(s, bus=pos[s["bus"]]) for s in agg["sync"]
                       if s["bus"] in pos]
        freqs, M, K, sync = build_classical_model(Y, agg, base, freq)
        st = agg["stats"]
        band = freqs[(freqs >= 0.2) & (freqs <= 2.5)]
        res[island] = {
            **st,
            "f_min_hz": round(float(freqs.min()), 3) if len(freqs) else None,
            "f_median_hz": round(float(np.median(freqs)), 3) if len(freqs) else None,
            "f_max_hz": round(float(freqs.max()), 3) if len(freqs) else None,
            "n_modes": int(len(freqs)),
            "n_electromech_band": int(len(band)),
        }
        print(f"{island}: 同期集約{st['n_sync_buses']}バス/IBR{st['S_ibr_mva']}MVA "
              f"モード {res[island]['f_min_hz']}〜{res[island]['f_max_hz']}Hz "
              f"(電気機械帯 {len(band)}/{len(freqs)})")
    OUT.write_text(json.dumps({
        "note": "古典モデル(機械集約・容量加重H・xd''並列合成・フラット近似)の"
                "モード周波数帯。inter-area最低モード: west 0.37Hz / east 0.57Hz",
        "typical_params": "IEEJ/教科書帯の型式別典型値(machine_agg.TYPE_PARAMS)",
        "islands": res,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
