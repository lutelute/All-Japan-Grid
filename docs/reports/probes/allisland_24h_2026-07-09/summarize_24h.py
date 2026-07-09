#!/usr/bin/env python3
"""全島24h検証結果の集計 — 各島のJSONから収束率・電圧・損失・slack・注入問題を集計."""
import json
import os
import sys

OUT = ("/private/tmp/claude-501/-Users-shigenoburyuto-Documents-GitHub-"
       "project-Hayashi-All-Japan-Grid/78bb2546-5e61-4e06-97de-a53fe1953ee0/"
       "scratchpad/allisland24h")


def main():
    islands = ["hokkaido", "east", "west", "okinawa"]
    rows = []
    for isl in islands:
        p = os.path.join(OUT, f"{isl}.json")
        if not os.path.exists(p):
            rows.append({"island": isl, "status": "NO_JSON"})
            continue
        d = json.load(open(p))
        e = d["islands"].get(isl, {})
        hours = e.get("hours", {})
        n = len(hours)
        n_conv = sum(1 for h in hours.values() if h.get("converged"))
        modes = {}
        vmins, vmaxs, losses, served, slacks = [], [], [], [], []
        n_clip = 0
        for h in hours.values():
            modes[h.get("solver")] = modes.get(h.get("solver"), 0) + 1
            if h.get("vm_min") is not None:
                vmins.append(h["vm_min"])
            if h.get("vm_max") is not None:
                vmaxs.append(h["vm_max"])
            if h.get("loss_mw") is not None:
                losses.append(h["loss_mw"])
            if h.get("served_frac") is not None:
                served.append(h["served_frac"])
            if h.get("slack_abs_mw") is not None:
                slacks.append(h["slack_abs_mw"])
            if h.get("injection_issues"):
                n_clip += 1
        rc = e.get("reactive_comp")
        rows.append({
            "island": isl,
            "mode": e.get("mode"),
            "n_bus": e.get("n_bus"),
            "n_hours": n, "n_converged": n_conv,
            "all_converged": e.get("all_converged"),
            "solver_hist": modes,
            "served_min": round(min(served), 4) if served else None,
            "served_mean": round(sum(served)/len(served), 4) if served else None,
            "vm_min": round(min(vmins), 3) if vmins else None,
            "vm_max": round(max(vmaxs), 3) if vmaxs else None,
            "loss_mean_mw": round(sum(losses)/len(losses), 1) if losses else None,
            "slack_mean_mw": round(sum(slacks)/len(slacks), 1) if slacks else None,
            "reactive_comp": rc,
            "hours_with_inj_issues": n_clip,
        })
    print(json.dumps(rows, ensure_ascii=False, indent=1))
    # コンパクト表
    print("\n=== SUMMARY ===")
    print(f"{'island':10} {'mode':4} {'bus':6} {'conv':7} "
          f"{'served_min':10} {'vm':16} {'loss_mean':10} {'shunt':6}")
    for r in rows:
        if r.get("status") == "NO_JSON":
            print(f"{r['island']:10} NO_JSON")
            continue
        rc = r.get("reactive_comp") or {}
        vm = f"[{r.get('vm_min')},{r.get('vm_max')}]"
        print(f"{r['island']:10} {str(r.get('mode')):4} {str(r.get('n_bus')):6} "
              f"{r['n_converged']}/{r['n_hours']:<5} "
              f"{str(r.get('served_min')):10} {vm:16} "
              f"{str(r.get('loss_mean_mw')):10} {rc.get('n_shunt','-')}")


if __name__ == "__main__":
    main()
