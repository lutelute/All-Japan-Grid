"""再現の手順書と再生成の STEPS が名指しするスクリプトは、どの clone でも動く(2026-10-26)。

docs/REPRODUCIBILITY.md が「各自で作る」と書いた地点需要の段(scripts/parse_point_demand.py)が、
所有者の絶対パスを読み書きしていて、clone した人の手元では作れなかった。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ["docs/REPRODUCIBILITY.md", "README.md", "docs/DATASET.md", "dataset/README.md",
        *[str(p.relative_to(ROOT)) for p in (ROOT / "dataset").rglob("README.md")]]


def _named() -> set[str]:
    out = set()
    for d in DOCS:
        p = ROOT / d
        if p.exists():
            t = p.read_text(encoding="utf-8")
            out |= set(re.findall(r"(scripts/[\w/]+\.(?:py|sh))", t))
            out |= {m.replace(".", "/") + ".py" for m in re.findall(r"-m (scripts\.[\w.]+)", t)}
    steps = (ROOT / "scripts/regenerate_all.py").read_text(encoding="utf-8")
    out |= set(re.findall(r'"(scripts/[^"]+\.py)"', steps))
    return out


def test_named_scripts_exist_and_have_no_owner_paths():
    named = _named()
    assert "scripts/parse_point_demand.py" in named and len(named) > 30
    missing = sorted(n for n in named if not (ROOT / n).exists())
    assert missing == []
    owner = sorted(n for n in named if re.search(r"/Users/[^/\s\"']+/", (ROOT / n).read_text(encoding="utf-8")))
    assert owner == []
