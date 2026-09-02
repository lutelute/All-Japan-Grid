#!/usr/bin/env python3
"""Snakemake の --rulegraph / --dag 出力(DOT テキスト)を、graphviz の `dot` 無しで
SVG に描く(networkx + matplotlib)。CI と手元の両方で `dot` を要求しないため。

    uv run --with snakemake --no-project snakemake --rulegraph --cores 1 \
        | PYTHONPATH=. python3 scripts/ci/render_rulegraph.py --out docs/figures/dag.svg

DOT の完全パーサではない: Snakemake が出す `N[label = "rule"]` と `A -> B` の 2 形式だけを読む
(それ以外の行は無視)。レイアウトは位相順の世代(topological generations)で段組みし、
入力側(build_editor_data)を上・`all` を下に置く。
"""
from __future__ import annotations

import argparse
import re
import sys

NODE_RE = re.compile(r'^\s*(\d+)\s*\[\s*label\s*=\s*"([^"]+)"')
EDGE_RE = re.compile(r'^\s*(\d+)\s*->\s*(\d+)')


def parse_dot(text: str):
    nodes, edges = {}, []
    for line in text.splitlines():
        m = NODE_RE.match(line)
        if m:
            nodes[m.group(1)] = m.group(2)
            continue
        m = EDGE_RE.match(line)
        if m:
            edges.append((m.group(1), m.group(2)))
    return nodes, edges


def render(nodes: dict, edges: list, out: str, title: str = "") -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import networkx as nx

    g = nx.DiGraph()
    for k, lab in nodes.items():
        g.add_node(k, label=lab)
    g.add_edges_from(edges)
    gens = list(nx.topological_generations(g))
    pos = {}
    for gi, gen in enumerate(gens):
        gen = sorted(gen, key=lambda k: nodes[k])
        n = len(gen)
        for j, k in enumerate(gen):
            pos[k] = ((j - (n - 1) / 2.0) * 2.6, -gi * 1.0)
    w = max(6.0, 2.6 * max(len(gn) for gn in gens) + 2.0)
    h = max(4.0, 0.9 * len(gens) + 1.0)
    fig, ax = plt.subplots(figsize=(w, h))
    nx.draw_networkx_edges(g, pos, ax=ax, arrows=True, arrowsize=12,
                           edge_color="#9aa0a6", width=1.4,
                           connectionstyle="arc3,rad=0.05", min_target_margin=18)
    for k, (x, y) in pos.items():
        ax.text(x, y, nodes[k], ha="center", va="center", fontsize=8.5,
                bbox=dict(boxstyle="round,pad=0.35", fc="#eef3ff", ec="#3c6dd9", lw=1.2))
    if title:
        ax.set_title(title, fontsize=10)
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(out)          # 形式は拡張子から(svg/png)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="All-Japan-Grid reproduction DAG (Snakefile rulegraph)")
    ap.add_argument("--dot", default="-", help="DOT テキストのファイル(省略時は stdin)")
    args = ap.parse_args(argv)
    text = sys.stdin.read() if args.dot == "-" else open(args.dot, encoding="utf-8").read()
    nodes, edges = parse_dot(text)
    if not nodes:
        print("DOT からノードを読めなかった(入力が空か形式違い)", file=sys.stderr)
        return 2
    render(nodes, edges, args.out, args.title)
    print(f"-> {args.out} ({len(nodes)} rules, {len(edges)} deps)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
