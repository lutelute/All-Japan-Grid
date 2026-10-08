#!/usr/bin/env python3
"""1 サンプルのトレースを組み込んだ「1手ずつ」ビューア HTML を作る。

    PYTHONPATH=hazard/nankai/src python3 hazard/nankai/scripts/build_steps_viewer.py <out.html> [--island west] [--seed 7]
"""
from __future__ import annotations
import argparse, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from nankai.grid import GridCase
from nankai.montecarlo import Simulator
from nankai.trace import trace_sample


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("out"); ap.add_argument("--island", default="west"); ap.add_argument("--seed", type=int, default=7); a = ap.parse_args()
    case = GridCase.load(a.island); sim = Simulator(case)
    tr = trace_sample(sim, seed=a.seed)
    here = os.path.dirname(os.path.abspath(__file__))
    tpl = open(os.path.join(here, "templates", "steps_viewer.html"), encoding="utf-8").read()
    css = open(os.path.join(here, "templates", "leaflet-1.9.4.min.css"), encoding="utf-8").read()
    js = json.dumps(tr, ensure_ascii=False, separators=(",", ":"))
    html = tpl.replace("/*__LEAFLET_CSS__*/", css.replace("</style", "<\\/style")).replace("/*__DATA__*/null", js)
    open(a.out, "w", encoding="utf-8").write(html)
    print("steps", len(tr["steps"]), "html MB", round(len(html.encode()) / 1e6, 2))


if __name__ == "__main__":
    main()
