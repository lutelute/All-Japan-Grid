"""ツールダッシュボード(:8088/tools) — ツール実行・データ/MATLAB を開く.

オーナー要望(2026-07-02): 「ダッシュボードからツール等(MATLAB等)を実行、
開く、データを開くもできるように」。GitHub Pages は静的なので、ローカル
バックエンドを持つ :8088 に用途別ビュー(ビュー分離の原則: edit≠tools)として
実装する。

SECURITY(ローカル専用・認証なし前提の多層防御):
  - ツール実行は**固定レジストリのみ**(任意コマンド不可)。パラメータは
    region ホワイトリスト / name サニタイズで検証し、subprocess は
    shell=False のリスト引数のみ。
  - ファイル配信・open(Finder/MATLAB/既定アプリ)は realpath が許可ルート
    (プロジェクト内 + /tmp/agj_tools)配下の実在ファイルに限定。
  - SECURITY.md のとおり 127.0.0.1 バインドで使うこと。
"""

import json
import os
import re
import subprocess
import sys
import time
from typing import Optional

import matplotlib
matplotlib.use("Agg")

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from src.regions import REGIONS, REGION_JA

router = APIRouter()

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.realpath(os.path.join(_BASE_DIR, "..", ".."))
_TOOLS_TMP = "/tmp/agj_tools"
# NOTE: macOS では /tmp → /private/tmp のシンボリックリンクのため、許可ルート側も
# realpath で正規化しないと _safe_path の前方一致が全て弾かれる(実UI駆動で発覚)。
_ALLOWED_ROOTS = tuple(os.path.realpath(p) for p in
                       (_PROJECT_ROOT, _TOOLS_TMP, "/tmp/agj_sld"))

# データブラウザのルート(エイリアス → 実ディレクトリ・任意の拡張子フィルタ)
_BROWSE_ROOTS = {
    "structures": ("data/structures", None, "変電所内部構造(node-breaker)"),
    "built": ("docs/data/built", (".json",), "正典トポロジ(built)"),
    "geojson": ("data", ("_lines.geojson", "_substations.geojson",
                         "_plants.geojson"), "OSM抽出 GeoJSON"),
    "cim": ("dist/cim_level2", (".xml",), "CIM/CGMES Level2"),
    "matpower": ("dist/matpower_national", (".mat", ".csv"),
                 "MATPOWER(国全体・島別)"),
    "reports": ("docs/reports", (".md", ".json", ".png"), "レポート/診断"),
    "ybus": ("dist/ybus", (".mat", ".npz", ".csv", ".json"),
             "数値Ybus(島別・MATLAB対応)"),
}


def _safe_path(p: str) -> str:
    """許可ルート配下の実パスのみ通す(realpath でリンク越え防止)。"""
    rp = os.path.realpath(p)
    for root in _ALLOWED_ROOTS:
        if rp == root or rp.startswith(root + os.sep):
            return rp
    raise HTTPException(400, "path is outside allowed roots")


def _check_region(region: str) -> str:
    if region not in REGIONS:
        raise HTTPException(400, f"unknown region '{region}'")
    return region


def _check_name(name: str) -> str:
    name = (name or "").strip()
    if not name or len(name) > 64 or re.search(r"[/\\\0.]{2,}|[/\\\0]", name):
        raise HTTPException(400, "invalid substation name")
    return name


# ─── ツールレジストリ(固定・ホワイトリスト) ──────────────────────────


def _run_subscope(params: dict) -> dict:
    region = _check_region(params.get("region", ""))
    name = _check_name(params.get("name", ""))
    os.makedirs(_TOOLS_TMP, exist_ok=True)
    scripts_dir = os.path.join(_PROJECT_ROOT, "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from substation_scope import scope
    a, b, model = scope(region, name, _TOOLS_TMP)
    lines = [f"{kv}kV: {', '.join(fs) if fs else '(引込なし)'}"
             for kv, fs in model.items()]
    return {"output": "導出モデル(電圧→引込線)\n" + "\n".join(lines),
            "artifacts": [{"path": a, "kind": "png", "label": "OSM実構造図"},
                          {"path": b, "kind": "png", "label": "単線結線図(SLD)"}]}


def _run_structure(params: dict) -> dict:
    region = _check_region(params.get("region", ""))
    name = _check_name(params.get("name", ""))
    os.makedirs(_TOOLS_TMP, exist_ok=True)
    from dataclasses import asdict
    from scripts.build_substation_structure import (build_structure,
                                                    render_figure)
    structure, ways, poly = build_structure(region, name)
    # 単発抽出は点検用 → /tmp。正典は build_structures_batch の地域ファイル
    # (data/structures/{region}.json)のみ = 資産ディレクトリの純度を守る。
    out_json = os.path.join(_TOOLS_TMP, f"{structure.site.site_id}.json")
    with open(out_json, "w") as f:
        json.dump(asdict(structure), f, ensure_ascii=False, indent=1)
    out_png = os.path.join(_TOOLS_TMP, f"structure_{region}_{name}_nb.png")
    render_figure(structure, ways, poly, out_png)
    return {"output": json.dumps(structure.summary(), ensure_ascii=False,
                                 indent=1),
            "artifacts": [{"path": out_png, "kind": "png",
                           "label": "node-breaker 検証図"},
                          {"path": out_json, "kind": "json",
                           "label": "構造JSON(第一級データ)"}]}


def _run_structures_region(params: dict) -> dict:
    region = _check_region(params.get("region", ""))
    from scripts.build_structures_batch import generate
    lines = []
    _reports, gate_fail = generate([region], log=lines.append)
    out = "\n".join(lines)
    if gate_fail:
        raise HTTPException(500, f"quality gate failed:\n{out[-1500:]}")
    path = os.path.join(_PROJECT_ROOT, "data", "structures", f"{region}.json")
    return {"output": out,
            "artifacts": [{"path": path, "kind": "json",
                           "label": f"構造DB {region}.json(正典)"}]}


def _run_structures_all(params: dict) -> dict:
    from scripts.build_structures_batch import generate
    from src.regions import REGIONS as _ALL
    lines = []
    _reports, gate_fail = generate(list(_ALL), log=lines.append)
    out = "\n".join(lines)
    if gate_fail:
        raise HTTPException(500, f"quality gate failed:\n{out[-1500:]}")
    path = os.path.join(_PROJECT_ROOT, "data", "structures", "summary.json")
    return {"output": out,
            "artifacts": [{"path": path, "kind": "json",
                           "label": "全国カタログ summary.json"}]}


def _run_island_classify(params: dict) -> dict:
    region = _check_region(params.get("region", ""))
    env = {**os.environ, "PYTHONPATH": _PROJECT_ROOT,
           "MPLBACKEND": "Agg"}
    proc = subprocess.run(
        [sys.executable, os.path.join(_PROJECT_ROOT, "scripts",
                                      "island_classify.py"),
         "--region", region],
        capture_output=True, text=True, timeout=600, cwd=_PROJECT_ROOT,
        env=env, shell=False)
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    if proc.returncode != 0:
        raise HTTPException(500, f"island_classify failed:\n{out[-2000:]}")
    return {"output": out[-4000:], "artifacts": []}


TOOLS = {
    "subscope": {
        "label": "SubScope 変電所構造図",
        "desc": "OSM実構造図 + 単線結線図(SLD)を生成",
        "params": ["region", "name"],
        "runner": _run_subscope,
    },
    "structure": {
        "label": "内部構造抽出 (node-breaker)",
        "desc": "母線/ベイ/端子/変圧器を第一級データ(JSON)化 + 検証図",
        "params": ["region", "name"],
        "runner": _run_structure,
    },
    "island_classify": {
        "label": "島分類診断",
        "desc": "地域の未接続島を A/B/C(osm_gap/幽霊/鉄道等)に分類",
        "params": ["region"],
        "runner": _run_island_classify,
    },
    "structures_region": {
        "label": "構造DB 再生成(選択地域)",
        "desc": "変電所内部構造+接続レコードを再生成し正典を更新(品質ゲート付)",
        "params": ["region"],
        "runner": _run_structures_region,
    },
    "structures_all": {
        "label": "構造DB 全国一括生成",
        "desc": "全10地域+全国カタログ(summary)+地域重複alias を再生成(約4秒)",
        "params": [],
        "runner": _run_structures_all,
    },
    "ybus_numeric": {
        "label": "数値Ybus 全4島生成",
        "desc": "built正典→検証済みアドミタンス行列(.mat/.npz/バス表。約50秒)",
        "params": [],
        "runner": None,   # set below (forward reference)
    },
}


def _run_ybus_numeric(params: dict) -> dict:
    import json as _json
    from scripts.gen_ybus_numeric import ISLANDS, export_island
    from scripts.run_full_powerflow_from_db import BUILT
    out_dir = os.path.join(_PROJECT_ROOT, "dist", "ybus")
    os.makedirs(out_dir, exist_ok=True)
    built = _json.load(open(BUILT))
    lines = []
    metas = {}
    for island, freq in ISLANDS:
        meta = export_island(island, freq, built["nodes"], built["edges"],
                             out_dir)
        metas[island] = meta
        c = meta["checks"]
        lines.append(
            f"[{island}] bus={meta['n_bus']} nnz={meta['nnz']} "
            f"trafo={meta['n_trafo']} sym={c['symmetry_max_abs_err']:.0e} "
            f"offdiag_p99={c['offdiag_rel_err_p99']:.1e} "
            f"gate={'PASS' if meta['gate']['pass'] else 'FAIL'}")
    from datetime import date
    with open(os.path.join(out_dir, "meta.json"), "w") as f:
        _json.dump({"generated": date.today().isoformat(), "source": BUILT,
                    "islands": metas}, f, ensure_ascii=False, indent=1)
    return {"output": "\n".join(lines),
            "artifacts": [{"path": os.path.join(out_dir, "meta.json"),
                           "kind": "json", "label": "Ybus品質メタ(meta.json)"}]}


TOOLS["ybus_numeric"]["runner"] = _run_ybus_numeric


# ─── API ──────────────────────────────────────────────────────────────


class RunRequest(BaseModel):
    tool: str
    params: dict = {}


class OpenRequest(BaseModel):
    path: str
    app: str = "default"      # default | finder | matlab


@router.get("/api/tools/registry")
def tools_registry():
    return {
        "tools": [{"id": k, "label": v["label"], "desc": v["desc"],
                   "params": v["params"]} for k, v in TOOLS.items()],
        "regions": [{"id": r, "ja": REGION_JA.get(r, r)} for r in REGIONS],
        "browse_roots": [{"id": k, "label": v[2]}
                         for k, v in _BROWSE_ROOTS.items()],
        "platform": sys.platform,
    }


@router.post("/api/tools/run")
def tools_run(req: RunRequest):
    tool = TOOLS.get(req.tool)
    if tool is None:
        raise HTTPException(404, f"unknown tool '{req.tool}'")
    t0 = time.time()
    try:
        result = tool["runner"](req.params or {})
    except HTTPException:
        raise
    except Exception as exc:   # noqa: BLE001
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"{req.tool} failed: {exc}")
    result["elapsed_s"] = round(time.time() - t0, 1)
    return result


@router.get("/api/tools/browse")
def tools_browse(root: str):
    spec = _BROWSE_ROOTS.get(root)
    if spec is None:
        raise HTTPException(404, f"unknown browse root '{root}'")
    rel, suffixes, _label = spec
    d = os.path.join(_PROJECT_ROOT, rel)
    if not os.path.isdir(d):
        return {"dir": d, "files": []}
    files = []
    for fn in sorted(os.listdir(d)):
        p = os.path.join(d, fn)
        if not os.path.isfile(p):
            continue
        if suffixes and not any(fn.endswith(s) for s in suffixes):
            continue
        st = os.stat(p)
        files.append({"name": fn, "path": p, "size": st.st_size,
                      "mtime": int(st.st_mtime)})
    return {"dir": d, "files": files}


@router.get("/api/tools/file")
def tools_file(path: str):
    rp = _safe_path(path)
    if not os.path.isfile(rp):
        raise HTTPException(404, "file not found")
    return FileResponse(rp)


@router.post("/api/tools/open")
def tools_open(req: OpenRequest):
    """ファイル/フォルダをローカルで開く(macOS `open`)。"""
    if sys.platform != "darwin":
        raise HTTPException(501, "open is only supported on macOS host")
    rp = _safe_path(req.path)
    if not os.path.exists(rp):
        raise HTTPException(404, "path not found")
    if req.app == "finder":
        cmd = ["open", "-R", rp] if os.path.isfile(rp) else ["open", rp]
    elif req.app == "matlab":
        import glob as _glob
        apps = sorted(_glob.glob("/Applications/MATLAB*.app"), reverse=True)
        if not apps:
            raise HTTPException(404, "MATLAB.app not found in /Applications")
        cmd = ["open", "-a", apps[0], rp]
    elif req.app == "default":
        cmd = ["open", rp]
    else:
        raise HTTPException(400, f"unknown app '{req.app}'")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                          shell=False)
    if proc.returncode != 0:
        raise HTTPException(500, f"open failed: {proc.stderr.strip()}")
    return {"ok": True, "opened": rp, "app": req.app}


@router.get("/tools", response_class=HTMLResponse)
def tools_page(request: Request):
    from fastapi.templating import Jinja2Templates
    templates = Jinja2Templates(
        directory=os.path.join(_BASE_DIR, "templates"))
    return templates.TemplateResponse("tools.html", {"request": request})
