"""CIM/CGMES Level 2 を正典(docs/data/built)から書き出し、cim2pp で読み戻して解ける(2026-10-21).

それまで CIM は地域別のスナップ済みの網(旧系譜)からしか書けなかった
(docs/reports/project_structure_2026-10-21.md の D4)。--topology canonical は配布ケースと同じ
正典の網を 4 島ごとに組む。CI では沖縄(100 バス)だけを往復させる。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("pandapower")

ROOT = Path(__file__).resolve().parents[1]


def test_canonical_okinawa_round_trips(tmp_path):
    out = tmp_path / "cim"
    r = subprocess.run([sys.executable, "scripts/export_cim_level2.py", "--topology", "canonical",
                        "--regions", "okinawa", "--out-dir", str(out), "--verify"],
                       cwd=ROOT, capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(ROOT)},
                       timeout=600)
    assert r.returncode == 0, r.stderr[-2000:]
    assert "okinawa    OK" in r.stdout, r.stdout[-1500:]
    idx = json.loads((out / "cim_level2_index.json").read_text(encoding="utf-8"))
    row = idx["regions"][0]
    assert row["region"] == "okinawa" and row["buses"] == 100
    assert row["lineage"].startswith("canonical")


def test_tracked_canonical_sample_is_present():
    """リポジトリに置く見本(沖縄)は正典の網から書いたもの。"""
    d = ROOT / "dist" / "cim_canonical"
    for p in ("EQ", "TP", "SSH", "SV", "GL"):
        assert (d / f"okinawa_L2_{p}.xml").is_file(), p
    idx = json.loads((d / "cim_level2_index.json").read_text(encoding="utf-8"))
    assert all(r.get("lineage", "").startswith("canonical") for r in idx["regions"])
