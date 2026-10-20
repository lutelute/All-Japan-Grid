"""docs/reports/ の索引 INDEX.md を作り直す(月ごと・新しい順)。

    python3 scripts/build_reports_index.py          # docs/reports/INDEX.md を書く
    python3 scripts/build_reports_index.py --check  # 索引が古ければ終了コード 1

レポートの md ごとに、ファイル名の日付・見出し(最初の ``# ``)・改善台帳(IMPROVEMENT_LOG.md)から
参照されているかを並べる。日付はファイル名の ``YYYY-MM-DD``(無ければ git の最初のコミット日)。
レポートを足したらこれを実行する。手で INDEX.md を編集しない。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "docs/reports"
SKIP = {"README.md", "INDEX.md", "IMPROVEMENT_LOG.md"}
DATE = re.compile(r"(20\d{2}-\d{2}-\d{2})")


def first_commit_date(path: Path) -> str:
    try:
        out = subprocess.run(["git", "log", "--diff-filter=A", "--format=%cs", "--", str(path)],
                             cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
        return out[-1] if out else ""
    except (OSError, subprocess.CalledProcessError):
        return ""


def title_of(path: Path) -> str:
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def entries():
    log = (REPORTS / "IMPROVEMENT_LOG.md").read_text(encoding="utf-8")
    out = []
    for p in sorted(REPORTS.glob("*.md")):
        if p.name in SKIP:
            continue
        m = DATE.search(p.name)
        d = m.group(1) if m else first_commit_date(p)
        out.append({"date": d, "name": p.name, "title": title_of(p), "in_log": p.name in log})
    for p in sorted(REPORTS.glob("*/README.md")) + sorted(REPORTS.glob("*/REVIEW.md")):
        m = DATE.search(str(p.relative_to(REPORTS)))
        name = str(p.relative_to(REPORTS))
        out.append({"date": m.group(1) if m else first_commit_date(p), "name": name,
                    "title": title_of(p), "in_log": p.parent.name in log})
    return sorted(out, key=lambda e: (e["date"], e["name"]), reverse=True)


def render(es) -> str:
    by_month = defaultdict(list)
    for e in es:
        by_month[e["date"][:7] or "日付なし"].append(e)
    n_log = sum(e["in_log"] for e in es)
    lines = [
        "# レポート索引 / Reports index",
        "",
        "<!-- scripts/build_reports_index.py が生成する。手で編集しない -->",
        "",
        f"`docs/reports/` の判断・検証レポート {len(es)} 本(新しい順)。",
        f"台帳 [IMPROVEMENT_LOG.md](IMPROVEMENT_LOG.md) から参照されているものに ● を付けた({n_log} 本)。",
        "書き方の約束は [README.md](README.md)。",
        "",
    ]
    for month in sorted(by_month, reverse=True):
        lines += [f"## {month}", "", "| 日付 | レポート | 台帳 |", "|---|---|:---:|"]
        for e in by_month[month]:
            t = e["title"].replace("|", "\\|")
            lines.append(f"| {e['date'][5:] or '—'} | [{t}]({e['name']}) | {'●' if e['in_log'] else ''} |")
        lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    text = render(entries())
    dst = REPORTS / "INDEX.md"
    if a.check:
        ok = dst.exists() and dst.read_text(encoding="utf-8") == text
        print("INDEX.md is up to date" if ok else "INDEX.md is stale: run scripts/build_reports_index.py")
        return 0 if ok else 1
    dst.write_text(text, encoding="utf-8")
    print(f"-> {dst.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
