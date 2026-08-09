#!/usr/bin/env python3
"""接続規則を変えると「どの発電所がどこへ繋ぎ変わるか」を名前で出す。

`repair_search.py` は集計（110kV 以下に載る容量の割合など）で効果を示すが、
集計は「本当にその接続が変なのか」を読者に確かめさせない。ここでは**大型機を名指しで**
現行と修復後の接続電圧を並べる。姉崎火力 3,600MW が 66kV に繋がっているという主張は、
名前と数字が並んで初めて検証可能になる。

潮流は解かない（接続先の決定だけを見る）ので速い。

usage: python3 scripts/capacity/gen_attach_diff.py --islands east west --mode cap
出力: docs/reports/gen_attach_diff_<date>.{json,md}
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
REPORTS = ROOT / "docs" / "reports"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def gen_rows(net) -> list[tuple[str, float, float]]:
    """発電機を**作成順**で (名前, 出力MW, 接続バスの kV) に落とす。

    名前で突き合わせてはいけない — east は 8,235 機が 2,930 の一意名に潰れ、
    繋ぎ替え 167 件のうち 130 件が消えて「37 件」に見えた（2026-08-09 に実際に踏んだ）。
    `attach_generators` と `attach_generators_variant` は同じ feats を同じ順で回し
    同じ条件で skip するので、**添字が同一発電所を指す**。それを使う。
    """
    return [(str(r["name"]), float(r["max_p_mw"]),
             round(float(net.bus.at[int(r["bus"]), "vn_kv"]), 1))
            for _i, r in net.gen.iterrows()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--islands", nargs="*", default=["east", "west"])
    ap.add_argument("--mode", default="cap", choices=["site", "cap", "kvfit"])
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = args.date or subprocess.run(["date", "+%Y-%m-%d"], capture_output=True,
                                       text=True).stdout.strip()

    rs = _load(ROOT / "scripts" / "capacity" / "repair_search.py", "rs_diff")
    pf, wgv, _wsd = rs.load_modules()
    with open(pf.BUILT, encoding="utf-8") as f:
        db = json.load(f)
    nodes, edges = db["nodes"], db["edges"]

    result: dict[str, list[dict]] = {}
    for island in args.islands:
        net_a, bus_of, _ = pf.build_island_net(
            island, nodes, edges, pf.ISLAND_FREQ[island], {},
            dedup_nodes=True, site_trafos=False, deenergize_unbuilt=False)
        pf.attach_generators(net_a, bus_of, nodes, island)
        before = gen_rows(net_a)

        net_b, bus_of_b, _ = pf.build_island_net(
            island, nodes, edges, pf.ISLAND_FREQ[island], {},
            dedup_nodes=True, site_trafos=False, deenergize_unbuilt=False)
        info = wgv.attach_generators_variant(pf, net_b, bus_of_b, nodes, island, args.mode)
        after = gen_rows(net_b)
        if len(before) != len(after):
            raise SystemExit(f"{island}: 機数が一致しない "
                             f"({len(before)} vs {len(after)}) — 添字対応が壊れている")

        rows = []
        for (nm, p, kv0), (nm2, p2, kv1) in zip(before, after):
            if nm != nm2 or abs(p - p2) > 1e-6:
                raise SystemExit(f"{island}: 添字 {len(rows)} で発電所が食い違う "
                                 f"({nm}/{p} vs {nm2}/{p2})")
            rows.append({"name": nm, "p_mw": round(p, 1), "kv_before": kv0, "kv_after": kv1})
        n_moved_ref = int(info.get("n_moved") or 0)
        n_moved_here = sum(1 for r in rows if r["kv_after"] != r["kv_before"])
        # 電圧が変わらない繋ぎ替え（同階級の別バスへ）もあるので here <= ref が正しい関係
        if n_moved_here > n_moved_ref:
            raise SystemExit(f"{island}: 電圧が変わった機数 {n_moved_here} が "
                             f"繋ぎ替え総数 {n_moved_ref} を超えている")
        rows.sort(key=lambda r: -r["p_mw"])
        result[island] = {"rows": rows, "n_gen": len(rows), "n_moved": n_moved_ref,
                          "moved_mw": info.get("moved_mw")}
        moved = [r for r in rows if r["kv_after"] != r["kv_before"]]
        up = [r for r in moved if r["kv_after"] > r["kv_before"]]
        print(f"[{island}] {len(rows):,} 機中 繋ぎ替え {n_moved_ref:,}"
              f"（{info.get('moved_mw'):,.0f}MW）/ うち接続電圧が変わった {len(moved):,}"
              f"（昇圧 {len(up):,}・{sum(r['p_mw'] for r in up):,.0f}MW）", flush=True)
        for r in rows[:args.top]:
            flag = "→" if r["kv_after"] != r["kv_before"] else "  "
            print(f"   {r['p_mw']:8,.0f}MW  {r['kv_before']:5.0f}kV {flag} "
                  f"{r['kv_after']:5.0f}kV  {r['name'][:40]}", flush=True)

    (REPORTS / f"gen_attach_diff_{date}.json").write_text(
        json.dumps({"date": date, "mode": args.mode, "islands": result},
                   ensure_ascii=False, indent=1), encoding="utf-8")

    L = [f"# 接続規則を変えると大型機はどこへ繋がるか（{date}・mode={args.mode}）", "",
         "集計だけでは「その接続が変だ」を読者が確かめられないので、**大型機を名指しで**",
         "現行（最寄りの変電所バス）と修復後の接続電圧を並べる。", ""]
    for island, res in result.items():
        rows = res["rows"]
        moved = [r for r in rows if r["kv_after"] != r["kv_before"]]
        up_mw = sum(r["p_mw"] for r in moved if r["kv_after"] > r["kv_before"])
        L += [f"## {island}", "",
              f"{res['n_gen']:,} 機中 **{res['n_moved']:,} 機**（{res['moved_mw']:,.0f} MW）が"
              f"別のバスへ繋ぎ替わり、うち接続電圧が変わったのは {len(moved):,} 機、"
              f"昇圧は {up_mw:,.0f} MW ぶん。", "",
              "| 出力 | 現行の接続電圧 | 修復後 | 発電所 |", "|---:|---:|---:|---|"]
        for r in rows[:args.top]:
            arrow = " → " if r["kv_after"] != r["kv_before"] else " = "
            L.append(f"| {r['p_mw']:,.0f} MW | {r['kv_before']:.0f} kV |{arrow}"
                     f"{r['kv_after']:.0f} kV | {r['name'][:48]} |")
        L.append("")
    L += ["---",
          "**未適用**。生成: `scripts/capacity/gen_attach_diff.py`（潮流は解いていない）", ""]
    (REPORTS / f"gen_attach_diff_{date}.md").write_text("\n".join(L), encoding="utf-8")
    print(f"→ docs/reports/gen_attach_diff_{date}.md")


if __name__ == "__main__":
    main()
