#!/usr/bin/env python3
"""既定ON化(#19/#20/#21)判断パッケージ: old(従来既定=全OFF) vs new(新既定=ON) の機械比較。

出力: compare.json(生値) + stdout(markdown表・レポート貼り付け用)。
判定はここで機械的に出す(「収束」単独を成果としない: ac_converged と併せて
vm帯・成分数・損失の方向を確認する)。
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ISLANDS = ["hokkaido", "east", "west", "okinawa"]
FIELDS = ["n_bus", "n_line", "n_trafo", "n_components", "n_dedup_merged",
          "n_edge_dup_removed", "n_gen", "total_load_mw",
          "ac_converged", "ac_solver", "dc_converged",
          "ac_vm_min", "ac_vm_max", "ac_total_loss_mw", "solve_seconds"]


def load(mode, island):
    p = os.path.join(HERE, mode, island, "summary.json")
    with open(p, encoding="utf-8") as f:
        return json.load(f)["islands"][island]


def fmt(v):
    if isinstance(v, float):
        return f"{v:,.1f}" if abs(v) >= 100 else f"{v:.4f}"
    return str(v)


def main():
    out = {}
    lines = ["| 島 | 指標 | old(従来既定) | new(新既定) | 差 |",
             "|---|---|---|---|---|"]
    for isl in ISLANDS:
        o, n = load("old", isl), load("new", isl)
        out[isl] = {"old": {k: o.get(k) for k in FIELDS},
                    "new": {k: n.get(k) for k in FIELDS}}
        for k in FIELDS:
            ov, nv = o.get(k), n.get(k)
            if ov == nv and k not in ("ac_converged", "dc_converged"):
                continue
            d = ""
            if isinstance(ov, (int, float)) and isinstance(nv, (int, float)) \
                    and not isinstance(ov, bool):
                d = f"{nv - ov:+,.1f}" if isinstance(ov, float) else f"{nv - ov:+d}"
            lines.append(f"| {isl} | {k} | {fmt(ov)} | {fmt(nv)} | {d} |")

    with open(os.path.join(HERE, "compare.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print("\n".join(lines))

    # 機械判定
    print("\n機械判定:")
    ok = True
    for isl in ISLANDS:
        o, n = out[isl]["old"], out[isl]["new"]
        conv_o = o["ac_converged"] or o["dc_converged"]
        conv_n = n["ac_converged"] or n["dc_converged"]
        regress = conv_o and not conv_n
        frag_better = (n["n_components"] or 0) <= (o["n_components"] or 0)
        print(f"  {isl}: 解成立 old={conv_o} new={conv_n} "
              f"{'FAIL(退行)' if regress else 'OK'} / "
              f"成分数 {o['n_components']}→{n['n_components']} "
              f"{'OK(改善/同等)' if frag_better else 'WARN(増加)'}")
        ok = ok and not regress and frag_better
    print(f"総合: {'OK' if ok else 'FAIL'}")


if __name__ == "__main__":
    main()
