"""トラックA(信頼性)のゲート — 再現 DAG(Snakefile)・OSM 断面時刻・検証行列の形を固定する。

国際ベンチマーク(docs/reports/international_benchmark_2026-06-27.md)で自認した劣位
「raw OSM→成果物のワンコマンド DAG 無し」「OSM 断面時刻未記録」の解消を、
消えないようにテストで押さえる。重い計算はしない(テキスト検査と小さな走査だけ)。
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SNAKEFILE = ROOT / "Snakefile"
MODEL_VERSION = ROOT / "docs" / "data" / "MODEL_VERSION.json"
DATAPACKAGE = ROOT / "datapackage.json"
RECORD = ROOT / "scripts" / "record_osm_snapshot.py"
VERIFY = ROOT / "scripts" / "ci" / "verify_matrix.py"
WORKFLOW = ROOT / ".github" / "workflows" / "verify.yml"

# regenerate_all の STEPS を写した介入チェーン(順序が正典)。ここが崩れると
# 「in-place 変異段の順序」が壊れ、regen で介入が消える事故(2026-08-15)が再発する。
CHAIN = ["build_editor_data", "apply_disclosure_v1", "apply_disclosure_v2",
         "route_disclosure", "fragment_recovery", "fragment_recovery_chains",
         "node_hygiene", "satellite_connections", "substation_properties",
         "built_ready"]
EXPORTS = ["subsld_pages", "map_tiers", "gen_sld", "full_powerflow",
           "national_overview", "matpower", "cim", "static_site",
           "capacity_sources", "pages_editor", "version_stamp", "all", "light"]


def _rules(text: str) -> dict[str, str]:
    """rule 名 → 本文(次の rule まで)。"""
    out, names = {}, [m for m in re.finditer(r"^rule (\w+):", text, re.M)]
    for i, m in enumerate(names):
        end = names[i + 1].start() if i + 1 < len(names) else len(text)
        out[m.group(1)] = text[m.end():end]
    return out


def test_snakefile_declares_every_rule():
    text = SNAKEFILE.read_text(encoding="utf-8")
    rules = _rules(text)
    for r in CHAIN + EXPORTS:
        assert r in rules, f"Snakefile に rule {r} が無い"


def test_intervention_chain_is_sentinel_linked_in_order():
    """介入チェーンは .stamps センチネルで**一列に**繋がっていること。"""
    rules = _rules(SNAKEFILE.read_text(encoding="utf-8"))
    for prev, cur in zip(CHAIN[:-1], CHAIN[1:]):
        body = rules[cur]
        m_in = re.search(r"input:\s*f?\"\{STAMP\}/(\S+?)\.done\"", body)
        assert m_in, f"rule {cur} の input がセンチネルでない"
        prev_out = re.search(r"output:\s*touch\(f?\"\{STAMP\}/(\S+?)\.done\"\)", rules[prev])
        assert prev_out, f"rule {prev} の output がセンチネルでない"
        assert m_in.group(1) == prev_out.group(1), \
            f"{prev} -> {cur} の依存が繋がっていない ({prev_out.group(1)} != {m_in.group(1)})"


def test_exports_depend_on_built_ready():
    rules = _rules(SNAKEFILE.read_text(encoding="utf-8"))
    for r in ("subsld_pages", "map_tiers", "gen_sld", "full_powerflow", "cim"):
        assert "built_ready.done" in rules[r], f"rule {r} が built_ready に依存していない"


def test_snakefile_parses_with_snakemake_if_available():
    exe = shutil.which("snakemake")
    if exe is None:
        pytest.skip("snakemake が PATH に無い(uv run --with snakemake で手動確認)")
    p = subprocess.run([exe, "-n", "--cores", "1", "-s", str(SNAKEFILE)],
                       cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stderr[-2000:]
    assert "rule all" in p.stdout or "Job stats" in p.stdout


def test_record_osm_snapshot_scan_shape():
    if not (ROOT / "data" / "osm_raw").exists():
        pytest.skip("data/osm_raw が無い(生レスポンスは gitignore)")
    spec = importlib.util.spec_from_file_location("record_osm_snapshot", RECORD)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    snap = m.scan()
    assert isinstance(snap, dict)
    for k in ("oldest", "newest", "n_files_with_timestamp", "n_files_without",
              "coverage_note", "by_region"):
        assert k in snap, f"scan() に {k} が無い"
    if snap["n_files_with_timestamp"]:
        assert snap["oldest"] <= snap["newest"]
        assert snap["by_region"], "地域別内訳が空"


def test_osm_snapshot_is_stamped_in_model_version_and_datapackage():
    """刻印済みであること(2026-06-15T13:35〜14:25Z・76/78 ファイル)。"""
    for path in (MODEL_VERSION, DATAPACKAGE):
        d = json.loads(path.read_text(encoding="utf-8"))
        snap = d.get("osm_snapshot")
        assert snap, f"{path.name} に osm_snapshot が無い"
        assert re.match(r"\d{4}-\d{2}-\d{2}T", str(snap.get("oldest") or "")), snap
        assert snap["oldest"] <= snap["newest"]
        assert snap["n_files_with_timestamp"] >= 1
        assert "coverage_note" in snap, "被覆の注意書き(基底 geojson の抽出時刻ではない)が要る"


def test_verify_matrix_gate_passes_on_committed_reports_and_fails_on_regression(tmp_path):
    """検証行列ゲートは committed の実測で PASS し、非収束や電圧崩壊で FAIL すること。"""
    spec = importlib.util.spec_from_file_location("verify_matrix", VERIFY)
    vm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vm)
    hok = json.loads((ROOT / "docs/reports/uc_pf_built_hokkaido_sel_2026-09-02.json")
                     .read_text(encoding="utf-8"))
    oki = json.loads((ROOT / "docs/reports/uc_pf_built_okinawa_sel_2026-09-02.json")
                     .read_text(encoding="utf-8"))
    merged = {"meta": hok["meta"], "islands": {**hok["islands"], **oki["islands"]}}
    good = tmp_path / "good.json"
    good.write_text(json.dumps(merged), encoding="utf-8")
    assert vm.main(["--report", str(good)]) == 0

    bad = json.loads(json.dumps(merged))
    h = next(iter(bad["islands"]["hokkaido"]["hours"].values()))
    h["solver"] = "dc_fallback"
    badp = tmp_path / "bad.json"
    badp.write_text(json.dumps(bad), encoding="utf-8")
    assert vm.main(["--report", str(badp)]) == 1, "dc_fallback を見逃した"

    bad2 = json.loads(json.dumps(merged))
    next(iter(bad2["islands"]["okinawa"]["hours"].values()))["vm_min"] = 0.80
    bad2p = tmp_path / "bad2.json"
    bad2p.write_text(json.dumps(bad2), encoding="utf-8")
    assert vm.main(["--report", str(bad2p)]) == 1, "電圧崩壊を見逃した"

    assert vm.main(["--report", str(tmp_path / "missing.json")]) == 2


def test_verify_workflow_is_light_and_gated():
    """verify.yml は east/west フルを載せず、ゲートスクリプトを必ず通ること。"""
    yaml = pytest.importorskip("yaml")
    d = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = d["jobs"]["full-ac-light"]["steps"]
    runs = "\n".join(s.get("run", "") for s in steps)
    assert "scripts/uc_to_pf_built.py" in runs and "--islands hokkaido okinawa" in runs
    assert "scripts/ci/verify_matrix.py" in runs
    assert "--islands east" not in runs and "--islands west" not in runs, \
        "east/west フルは重いので verify.yml に載せない"
    assert d["jobs"]["full-ac-light"]["timeout-minutes"] <= 40
