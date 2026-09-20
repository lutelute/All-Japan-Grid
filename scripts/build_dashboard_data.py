#!/usr/bin/env python3
"""Pages ダッシュボード(docs/index.html)が読む要約 docs/data/dashboard.json を生成する.

ダッシュボードの数字(版・ノード数・介入件数・最新レポート)をHTMLへ直書きすると、
モデルを更新するたびにページだけが古くなる。ここでリポジトリの現物から集計し、
deploy-pages ワークフローで毎回作り直すことで、表示と実体のずれを無くす。

標準ライブラリのみ(Pages ビルドは pyyaml しか入れない)。

    python scripts/build_dashboard_data.py            # docs/data/dashboard.json を更新
    python scripts/build_dashboard_data.py --check    # 書かずに要約だけ表示
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
OUT = DOCS / "data" / "dashboard.json"

_DATE = re.compile(r"(20\d\d-\d\d-\d\d)")
N_RECENT = 12


def _first_heading(path: Path) -> str:
    """Markdown の最初の見出しを題名として返す(無ければファイル名)。"""
    try:
        with path.open(encoding="utf-8") as f:
            for _ in range(40):
                line = f.readline()
                if not line:
                    break
                if line.startswith("#"):
                    return line.lstrip("#").strip()
    except OSError:
        pass
    return path.stem


def _html_title(path: Path) -> str:
    try:
        head = path.open(encoding="utf-8", errors="replace").read(8192)
    except OSError:
        return path.parent.name
    m = re.search(r"<title>(.*?)</title>", head, re.S | re.I)
    return m.group(1).strip() if m else path.parent.name


def collect_reports() -> dict:
    """docs/reports 直下の日付つき Markdown を新しい順に。日付はファイル名から取る。"""
    rep = DOCS / "reports"
    dated = []
    for p in rep.glob("*.md"):
        m = _DATE.findall(p.name)
        if m:
            dated.append((m[-1], p))
    dated.sort(key=lambda t: (t[0], t[1].name), reverse=True)
    recent = [{"date": d, "title": _first_heading(p), "path": f"docs/reports/{p.name}"}
              for d, p in dated[:N_RECENT]]
    return {"total": len(list(rep.glob("*.md"))), "dated": len(dated), "recent": recent}


def collect_bundles() -> list[dict]:
    """ブラウザで開ける成果物(docs/reports/<dir>/index.html)。Pages 上の相対URLで返す。"""
    out = []
    for idx in sorted((DOCS / "reports").glob("*/index.html")):
        d = idx.parent.name
        m = _DATE.findall(d)
        out.append({"dir": d, "date": m[-1] if m else None, "title": _html_title(idx),
                    "href": f"reports/{d}/index.html"})
    out.sort(key=lambda b: b["date"] or "", reverse=True)
    return out


def count_interventions() -> int:
    """介入台帳の表のうち、先頭セルが番号(#n / n / n-a)の行を数える。"""
    path = DOCS / "MODEL_INTERVENTIONS.md"
    if not path.exists():
        return 0
    ids = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*#?(\d+)[a-z\-]*\s*\|", line)
        if m:
            ids.add(int(m.group(1)))
    return len(ids)


def collect_model() -> dict:
    """正典 built の規模(index.json の all)と、生成時のモデル版・OSM 断面。"""
    model: dict = {}
    idx = DOCS / "data" / "built" / "index.json"
    if idx.exists():
        regions = json.loads(idx.read_text(encoding="utf-8")).get("regions", [])
        allr = next((r for r in regions if r.get("id") == "all"), None)
        if allr:
            model.update(allr.get("stats", {}))
        model["n_regions"] = sum(1 for r in regions if r.get("id") != "all")
    mv = DOCS / "data" / "MODEL_VERSION.json"
    if mv.exists():
        v = json.loads(mv.read_text(encoding="utf-8"))
        model["model_version"] = v.get("model_version")
        model["generated_at"] = v.get("generated_at")
        model["osm_newest"] = (v.get("osm_snapshot") or {}).get("newest")
    return model


def read_versions() -> dict:
    """リリース版(CITATION.cff)と配布データセット版(VERSION)。

    両者は別物: v1.8.0 は手法リリースで配布バンドルを伴わず、データセットは v1.7.0 のまま。
    片方だけ見せると「最新版のデータが落とせない」誤解を生むので両方返す。
    """
    dataset = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    release = dataset
    cff = ROOT / "CITATION.cff"
    if cff.exists():
        m = re.search(r"^version:\s*['\"]?([0-9][^'\"\s]*)", cff.read_text(encoding="utf-8"), re.M)
        if m:
            release = m.group(1)
    return {"release": release, "dataset": dataset}


def build() -> dict:
    versions = read_versions()
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "version": versions["release"],
        "dataset_version": versions["dataset"],
        "model": collect_model(),
        "interventions": count_interventions(),
        "reports": collect_reports(),
        "bundles": collect_bundles(),
        "n_scripts": len(list((ROOT / "scripts").glob("*.py"))),
        "n_test_files": len(list((ROOT / "tests").glob("test_*.py"))),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="書き込まず要約だけ表示する")
    args = ap.parse_args()
    data = build()
    m = data["model"]
    print(f"release v{data['version']} / dataset v{data['dataset_version']}  nodes={m.get('n_nodes')} edges={m.get('n_edges')} "
          f"interventions={data['interventions']} reports={data['reports']['total']} "
          f"bundles={len(data['bundles'])}")
    if args.check:
        return
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"-> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
