"""再生成の記録(trace.jsonl)から、手順の入力を分類する。

入力 = その実行の中で、書く前に読んだファイル。分類:
  tracked   git が追跡している
  ignored   git の外(clone しただけでは無い)
  missing   読もうとしたが無かった(省略可能な入力)
  outside   worktree の外の絶対パス(本体のチェックアウトなど)を直接読んでいる
"""
import hashlib
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

W = Path(sys.argv[1]).resolve()
TRACE = Path(sys.argv[2])
OUT = Path(sys.argv[3])
MAIN = os.path.expanduser("~")

tracked = set(subprocess.run(["git", "ls-files"], cwd=W, capture_output=True, text=True).stdout.split("\n"))
events = [json.loads(l) for l in TRACE.open(encoding="utf-8")]
first: dict[str, dict] = {}
written = set()
readers = defaultdict(set)
dirs_listed = defaultdict(set)
outside = defaultdict(set)
for e in events:
    p = os.path.realpath(e["p"]) if e["p"].startswith(str(W)) is False and os.path.exists(e["p"]) else e["p"]
    script = os.path.relpath(e["s"], W) if e["s"].startswith(str(W)) else e["s"]
    if not e["p"].startswith(str(W) + "/"):
        if e["p"].startswith(MAIN) or e["p"].startswith("/Users/"):
            outside[e["p"]].add(script)
        continue
    rel = e["p"][len(str(W)) + 1:]
    if e["k"] in ("d", "g"):
        dirs_listed[rel].add(script)
        continue
    if e["w"]:
        written.add(rel)
    else:
        readers[rel].add(script)
    first.setdefault(rel, e)

inputs = {}
for rel, e in first.items():
    if e["w"] or rel in written and first[rel]["w"]:
        continue
    if rel.startswith(("docs/data/MODEL_VERSION", ".git/")):
        pass
    if rel in tracked:
        cls = "tracked"
    elif (W / rel).exists():
        cls = "ignored"
    else:
        cls = "missing"
    rec = {"class": cls, "readers": sorted(readers.get(rel, ())), "also_written": rel in written}
    if cls == "ignored" and (W / rel).is_file():
        b = (W / rel).read_bytes()
        rec["bytes"] = len(b)
        rec["sha256"] = hashlib.sha256(b).hexdigest()
    inputs[rel] = rec


def group(rel: str) -> str:
    parts = rel.split("/")
    if parts[0] == "data" and len(parts) > 2 and parts[1] in ("external",):
        return "/".join(parts[:4]) if len(parts) > 4 else "/".join(parts[:3])
    return "/".join(parts[:2]) if len(parts) > 2 else rel


summary = defaultdict(lambda: {"n": 0, "bytes": 0, "readers": set(), "files": []})
for rel, r in inputs.items():
    if r["class"] != "ignored":
        continue
    g = summary[group(rel)]
    g["n"] += 1
    g["bytes"] += r.get("bytes", 0)
    g["readers"] |= set(r["readers"])
    g["files"].append(rel)

out = {
    "worktree_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=W, capture_output=True, text=True).stdout.strip(),
    "counts": {c: sum(1 for r in inputs.values() if r["class"] == c) for c in ("tracked", "ignored", "missing")},
    "ignored_groups": {g: {"n": v["n"], "bytes": v["bytes"], "readers": sorted(v["readers"]),
                           "files": sorted(v["files"])[:40]} for g, v in sorted(summary.items())},
    "missing": {rel: r["readers"] for rel, r in sorted(inputs.items()) if r["class"] == "missing"},
    "outside_reads": {p: sorted(s) for p, s in sorted(outside.items())},
    "ignored_files": {rel: {k: r[k] for k in ("bytes", "sha256", "readers", "also_written") if k in r}
                      for rel, r in sorted(inputs.items()) if r["class"] == "ignored"},
    "ignored_dirs_listed": {d: sorted(s) for d, s in sorted(dirs_listed.items())
                            if d not in tracked and not any(t.startswith(d + "/") for t in ())},
}
OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(out["counts"]))
for g, v in out["ignored_groups"].items():
    print(f"{v['n']:5d} {v['bytes']/1e6:9.1f} MB  {g}   <- {', '.join(x.split('/')[-1] for x in v['readers'][:4])}")
print("missing:", len(out["missing"]), " outside:", len(out["outside_reads"]))
for p, s in list(out["outside_reads"].items())[:15]:
    print("  OUTSIDE", p, s[:2])
