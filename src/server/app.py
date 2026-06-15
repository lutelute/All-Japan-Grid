"""FastAPI web server for the Japan Power Grid interactive map.

Serves an interactive Leaflet.js map with OSM GeoJSON overlays,
power flow computation APIs, and MATPOWER export.

Usage::

    PYTHONPATH=. uvicorn src.server.app:app --host 0.0.0.0 --port 8080 --reload
"""

import glob
import json
import os
import traceback
from typing import Optional, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from src.server import geojson_loader

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(
    title="Japan Power Grid Map",
    description="Interactive grid map with power flow analysis",
    version="1.0.0",
)

# Static files and templates
app.mount("/static", StaticFiles(directory=os.path.join(_BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(_BASE_DIR, "templates"))

# Preload GeoJSON data on startup
_pf_results: dict = {}  # region -> powerflow results


@app.on_event("startup")
async def startup_load():
    """Load all GeoJSON data into memory at startup."""
    geojson_loader.load_all()


# ─── Pages ────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve the main map page."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/editor", response_class=HTMLResponse)
async def editor(request: Request):
    """接続編集プラットフォーム(全OSM点選択+接続/切断/点追加/属性編集→/api/edits)。"""
    return templates.TemplateResponse("editor.html", {"request": request})


# ─── GeoJSON API ──────────────────────────────────────────────────────

@app.get("/api/regions")
async def get_regions():
    """Return summary info for all available regions."""
    return geojson_loader.get_regions_summary()


@app.get("/api/geojson/all/{layer}")
async def get_all_geojson(layer: str, min_kv: float = 0):
    """Return lightweight merged GeoJSON for all regions.

    Uses simplified geometry and stripped properties for fast loading.
    """
    if layer not in ("substations", "lines"):
        raise HTTPException(400, "layer must be 'substations' or 'lines'")
    return geojson_loader.get_all_geojson_light(layer, min_voltage_kv=min_kv)


@app.get("/api/geojson/{region}/{layer}")
async def get_geojson(region: str, layer: str):
    """Return GeoJSON FeatureCollection for a region and layer.

    Args:
        region: Region id (e.g. "hokkaido").
        layer: "substations" or "lines".
    """
    if layer not in ("substations", "lines"):
        raise HTTPException(400, "layer must be 'substations' or 'lines'")

    data = geojson_loader.get_geojson(region, layer)
    if data is None:
        raise HTTPException(404, f"No data for region '{region}', layer '{layer}'")
    return data


# ─── Connection edit log (editor platform) ───────────────────────────
# 設計: docs/CONNECTION_EDITOR_DESIGN.md。人間の接続編集を append専用ログに記録し、
# E8の検証(潮流/DB)で判定する。物理接続=真・捏造禁止。


class EditIn(BaseModel):
    action: str                       # connect | disconnect | add_point | set_attr
    region: str
    a: Optional[dict] = None          # {node?, lat, lon}
    b: Optional[dict] = None
    pt: Optional[dict] = None         # add_point: {lat, lon}
    line_key: Optional[str] = None    # disconnect: line id (a/b の代替)
    feature_key: Optional[str] = None  # set_attr 対象
    field: Optional[str] = None
    value: Optional[Any] = None
    kv: Optional[float] = None
    user: Optional[str] = "anon"
    evidence: Optional[str] = None
    note: Optional[str] = None


@app.post("/api/edits")
async def post_edit(edit: EditIn):
    """接続編集(connect/disconnect/add_point/set_attr)をappend専用ログに記録。"""
    from src.server import edit_log

    payload = {k: v for k, v in edit.model_dump().items() if v is not None}
    try:
        rec = edit_log.append_edit(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "id": rec["id"], "status": rec["status"]}


@app.get("/api/edits/{region}")
async def get_edits(region: str, status: Optional[str] = None):
    """記録済み編集の一覧(status で絞り込み可)。地図への色分け表示用。

    submitted=issue送信済みの edit id(取消不可・色分け用)も返す。
    """
    from src.server import edit_log, issue_submit

    return {
        "region": region,
        "edits": edit_log.list_edits(region, status),
        "counts": edit_log.counts(region),
        "submitted": sorted(issue_submit.submitted_edit_ids(region)),
    }


@app.delete("/api/edits/{region}/{edit_id}")
async def delete_edit(region: str, edit_id: str):
    """保留編集を1件取消(undo/反映前の切断)。issue送信済みは取消不可。"""
    from src.server import edit_log, issue_submit

    submitted = issue_submit.submitted_edit_ids(region)
    if edit_id in submitted:
        raise HTTPException(400, "issue送信済みの編集は取消できません(issue側で対応)")
    removed = edit_log.remove_edit_by_id(region, edit_id, exclude_ids=submitted)
    if removed is None:
        raise HTTPException(404, "該当する保留編集が見つかりません")
    return {"ok": True, "removed": removed}


@app.post("/api/verify/{region}")
async def verify_edits(region: str):
    """pending編集をモデルに一時適用→島数before/after(検証→判定材料・E8)。"""
    from src.server import edit_apply

    try:
        return edit_apply.verify(region)
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(500, f"verify failed: {exc}")


_built_cache: dict = {}  # region -> built_view result(再構築は重い〜2秒なのでキャッシュ)


class IssueIn(BaseModel):
    memo: Optional[str] = None
    verify: Optional[dict] = None   # 直近の検証結果(島A/B)をそのまま本文に載せる
    dry_run: Optional[bool] = False


@app.post("/api/issue/{region}")
async def post_issue(region: str, body: IssueIn):
    """pending接続をまとめて GitHub issue 化(レビュー・メモ・OSM還元の単位)。

    粒度=まとめて1 issue(オーナー選択)。`connection`+`data-quality` ラベル。
    送信済みは data/db/connection_submissions.jsonl に記録し二重送信を防ぐ。
    """
    from src.server import issue_submit

    try:
        result = issue_submit.submit_issue(
            region, memo=body.memo, verify=body.verify, dry_run=bool(body.dry_run),
        )
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(500, f"issue submit failed: {exc}")
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "issue submit failed"))
    return result


@app.get("/api/island_class/{region}")
async def get_island_class(region: str):
    """島変電所の分類(railway/osm_gap/vsplit/reachable/isolated)。

    `scripts/island_classify.py` が出力した最新JSONを配信(編集ツールの島色分け用)。
    未生成なら404+生成コマンドを返す。自動束縛は捏造になるため「どの島を人間が繋ぐか」の提示材料。
    """
    files = sorted(glob.glob(os.path.join("data", "db", f"island_classify_{region}_*.json")))
    if not files:
        raise HTTPException(404, f"island_classify未生成: PYTHONPATH=. python scripts/island_classify.py --region {region} --out data/db --stamp <date>")
    with open(files[-1], encoding="utf-8") as fh:
        return json.load(fh)


@app.get("/api/built/{region}")
async def get_built(region: str, fresh: int = 0):
    """系統モデル(build後)の接続状態。OSMと並列表示し『繋がっているか』を確認する(E10)。

    節点を島/本系統で色分け+モデルが実際に張った接続線(実OSM幾何)を返す。OSMでは
    線が見えるのにモデルでは島(=未接続)、という乖離をエディタ上で可視化するためのレイヤ。
    再構築は重いのでregion単位でメモリキャッシュ(`?fresh=1`で強制再構築・検証後の更新用)。
    """
    from src.server import built_view

    if not fresh and region in _built_cache:
        return _built_cache[region]
    try:
        result = built_view.built_view(region)
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(500, f"built_view failed: {exc}")
    if result is None:
        raise HTTPException(404, f"No built model for region '{region}'")
    _built_cache[region] = result
    return result


# ─── Power Flow API ──────────────────────────────────────────────────


class PowerFlowRequest(BaseModel):
    region: str
    mode: str = "dc"
    load_factor: Optional[float] = None


@app.post("/api/powerflow/run")
async def run_powerflow_api(req: PowerFlowRequest):
    """Run power flow on a region.

    Returns summary with convergence status, losses, and loading.
    """
    from src.server import powerflow_service

    sub_fc = geojson_loader.get_geojson(req.region, "substations")
    line_fc = geojson_loader.get_geojson(req.region, "lines")
    if sub_fc is None or line_fc is None:
        raise HTTPException(404, f"No data for region '{req.region}'")

    try:
        result = powerflow_service.run_powerflow_for_region(
            sub_fc, line_fc, req.region,
            mode=req.mode,
            load_factor=req.load_factor,
        )
        # Cache for subsequent result queries
        _pf_results[req.region] = result
        return result["summary"]
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(500, f"Power flow failed: {exc}")


@app.get("/api/powerflow/results/{region}/buses")
async def get_bus_results(region: str):
    """Return bus results as GeoJSON (vm_pu, p_mw per bus)."""
    from src.server import powerflow_service

    cached = _pf_results.get(region)
    if cached is None:
        raise HTTPException(404, f"No power flow results for '{region}'. Run /api/powerflow/run first.")

    return powerflow_service.results_to_bus_geojson(
        cached["net"], cached["grid_network"], cached["build_result"], cached["pf_result"],
    )


@app.get("/api/powerflow/results/{region}/lines")
async def get_line_results(region: str):
    """Return line results as GeoJSON (loading_percent per line)."""
    from src.server import powerflow_service

    cached = _pf_results.get(region)
    if cached is None:
        raise HTTPException(404, f"No power flow results for '{region}'. Run /api/powerflow/run first.")

    return powerflow_service.results_to_line_geojson(
        cached["net"], cached["grid_network"], cached["build_result"], cached["pf_result"],
    )


# ─── MATPOWER Export ──────────────────────────────────────────────────


class MatpowerExportRequest(BaseModel):
    region: str


@app.post("/api/matpower/export")
async def export_matpower(req: MatpowerExportRequest):
    """Export a region to MATPOWER .mat file."""
    from src.server import powerflow_service

    sub_fc = geojson_loader.get_geojson(req.region, "substations")
    line_fc = geojson_loader.get_geojson(req.region, "lines")
    if sub_fc is None or line_fc is None:
        raise HTTPException(404, f"No data for region '{req.region}'")

    try:
        mat_path = powerflow_service.export_matpower(sub_fc, line_fc, req.region)
        if mat_path and os.path.exists(mat_path):
            return FileResponse(
                mat_path,
                media_type="application/octet-stream",
                filename=f"{req.region}.mat",
            )
        raise HTTPException(500, "MATPOWER export failed")
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(500, f"Export failed: {exc}")


# ─── AC Methods ───────────────────────────────────────────────────────

@app.get("/api/ac-methods")
async def get_ac_methods():
    """Return list of available AC power flow methods."""
    try:
        from src.ac_powerflow.methods import get_all_methods
        methods = get_all_methods()
        return [
            {
                "id": m.id,
                "name": m.name,
                "category": m.category,
                "description": m.description,
            }
            for m in methods
        ]
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(500, f"Failed to load AC methods: {exc}")
