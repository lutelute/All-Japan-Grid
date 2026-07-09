#!/usr/bin/env python3
"""dedup が線に与える影響を検査 — 自己ループ/見かけの複線(二重抽出)/複線潰し.

検査:
  A. 自己ループ: dedup後に from_bus==to_bus の線が生じていないか
  B. 見かけの複線: dedup後にバス対あたりの線数が増える(=境界跨ぎ線の二重抽出が
     並列に見える)分がどれだけか。実複線と二重抽出を長さ/pathで区別。
  C. 複線潰し: 実在の並列回線(par>1 or 複数edge)がdedupで失われていないか
  .venv/bin/python check_dedup_lines.py <island> <out.json>
"""
import json, os, sys
from collections import Counter, defaultdict
REPO = "/Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid"
sys.path.insert(0, REPO); os.chdir(REPO)
from scripts.run_full_powerflow_from_db import BUILT, build_island_net
from scripts.uc_to_pf_built import ISLAND_FREQ


def analyze(net):
    self_loops = 0
    pair_lines = defaultdict(list)   # (min,max bus) -> [line idx]
    for li in net.line.index:
        fb, tb = int(net.line.at[li, "from_bus"]), int(net.line.at[li, "to_bus"])
        if fb == tb:
            self_loops += 1
            continue
        pair_lines[(min(fb, tb), max(fb, tb))].append(li)
    # 並列多重度分布
    mult = Counter(len(v) for v in pair_lines.values())
    n_par_pairs = sum(1 for v in pair_lines.values() if len(v) > 1)
    return {"n_line": int(len(net.line)), "self_loops": self_loops,
            "n_bus_pairs": len(pair_lines),
            "n_parallel_pairs": n_par_pairs,
            "multiplicity_hist": dict(sorted(mult.items())),
            "pair_lines": pair_lines}


def main():
    island = sys.argv[1]; out_path = sys.argv[2]
    built = json.load(open(BUILT))
    freq = ISLAND_FREQ[island]
    net0, bo0, s0 = build_island_net(island, built["nodes"], built["edges"], freq, {}, dedup_nodes=False)
    net1, bo1, s1 = build_island_net(island, built["nodes"], built["edges"], freq, {}, dedup_nodes=True)
    a0 = analyze(net0); a1 = analyze(net1)

    # 見かけの複線を分類: dedup後に多重になったバス対で、線の長さがほぼ同一(二重抽出)か
    #  異なる(実複線 or 別ルート)か
    susp_dup = []   # 二重抽出疑い(長さほぼ同一)
    real_par = []   # 実並列(長さ相応)
    for pair, lis in a1["pair_lines"].items():
        if len(lis) < 2:
            continue
        lens = sorted(round(float(net1.line.at[li, "length_km"]), 3) for li in lis)
        names = [str(net1.line.at[li, "name"]) for li in lis]
        # 長さが相互に1%以内で一致するペアが在れば二重抽出疑い
        dup_like = any(abs(lens[i]-lens[i+1]) <= max(0.02, 0.01*lens[i+1])
                       for i in range(len(lens)-1))
        rec = {"pair": list(pair), "n": len(lis), "lengths_km": lens,
               "names": names[:4]}
        (susp_dup if dup_like else real_par).append(rec)

    rep = {"island": island,
           "dedup_off": {k: a0[k] for k in a0 if k != "pair_lines"},
           "dedup_on": {k: a1[k] for k in a1 if k != "pair_lines"},
           "delta_bus": s0["n_bus"] if False else int(len(net0.bus)-len(net1.bus)),
           "n_suspected_double_extract_pairs": len(susp_dup),
           "n_real_parallel_pairs": len(real_par),
           "examples_double_extract": susp_dup[:12],
           "examples_real_parallel": real_par[:8]}
    json.dump(rep, open(out_path, "w"), ensure_ascii=False, indent=1)
    print(f"[{island}] 線: OFF {a0['n_line']} / ON {a1['n_line']}")
    print(f"  自己ループ: OFF {a0['self_loops']} / ON {a1['self_loops']}")
    print(f"  並列バス対: OFF {a0['n_parallel_pairs']} / ON {a1['n_parallel_pairs']}")
    print(f"  多重度分布 ON: {a1['multiplicity_hist']}")
    print(f"  ON多重の内訳: 二重抽出疑い(長さ一致){len(susp_dup)} / 実並列{len(real_par)}")
    print("  二重抽出疑い例:")
    for r in susp_dup[:8]:
        print(f"    pair={r['pair']} n={r['n']} len={r['lengths_km']} {r['names']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
