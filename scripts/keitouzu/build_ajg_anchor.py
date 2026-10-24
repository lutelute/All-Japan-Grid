#!/usr/bin/env python3
"""open-keitouzu の対応表が指す AGJ の id を、その版の正典での座標・kV・地域・名前と一緒に書く.

対応表の ajg 行は版の決まった id(``target_version``、今は ajg-v1.6.0)を指す。id は OSM を
取り直すと振り直されるので、引くときは座標で今の正典へ引き直す(``src/topology/keitouzu_ids.py``)。
その座標の元になる表をここで作る。版の正典は git のタグ(v1.6.0 なら ``v1.6.0``)から読む。

    python3 scripts/keitouzu/build_ajg_anchor.py            # 対応表にある版を全部
出力: data/reference/keitouzu_ajg_anchor_<版>.csv
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.topology.keitouzu_ids import anchor_path  # noqa: E402

CROSSWALK = ROOT / "data" / "external" / "keitouzu" / "crosswalk.csv"


def tag_of(version: str) -> str:
    return version.removeprefix("ajg-")  # ajg-v1.6.0 → v1.6.0


def main() -> int:
    ids = defaultdict(set)
    for r in csv.DictReader(CROSSWALK.open(encoding="utf-8")):
        if r["target_system"] == "ajg":
            ids[r["target_version"]].add(r["target_id"])
    for version, want in sorted(ids.items()):
        built = json.loads(subprocess.run(
            ["git", "show", f"{tag_of(version)}:docs/data/built/all.json"],
            cwd=ROOT, capture_output=True, check=True).stdout)
        nodes = {n["id"]: n for n in built["nodes"]}
        rows = [{"target_id": t, "lat": nodes[t]["lat"], "lon": nodes[t]["lon"],
                 "kv": nodes[t].get("kv") or "", "region": nodes[t].get("region", ""),
                 "name": nodes[t].get("name", "")} for t in sorted(want) if t in nodes]
        missing = sorted(want - nodes.keys())
        out = anchor_path(version)
        with out.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["target_id", "lat", "lon", "kv", "region", "name"],
                               lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
        print(f"{version}: {len(rows)} 件 → {out.relative_to(ROOT)}"
              + (f"(その版にも無い id {len(missing)} 件: {missing[:5]})" if missing else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
