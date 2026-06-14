"""E8: 編集ログをモデルに適用して検証する(connect/add_point → supplement)。

pending編集を一時 data_dir に適用し、`build_network_snapped` で島数 before/after を出す。
物理接続=真・捏造禁止: 検証で島削減(将来はρ/AC維持も)が確認できた編集のみ adopt 候補。

適用先(設計 docs/CONNECTION_EDITOR_DESIGN.md):
  connect   → {region}_lines_supplement.geojson に LineString追記(builderが取込)
  add_point → {region}_substations_supplement.geojson に Point追記
  disconnect→ builderのcut機構(E8b・未実装)が要るのでここではskip(件数のみ報告)
  set_attr  → enrichments.jsonl(別経路・skip)
"""
import os
import json
import tempfile
import shutil

import networkx as nx

from src.server import edit_log


def _island_count(region, data_dir=None):
    from src.powerflow.snapped_topology import build_network_snapped
    net = build_network_snapped(region, data_dir=data_dir)
    g = nx.Graph()
    g.add_nodes_from(s.id for s in net.substations)
    for ln in net.transmission_lines:
        g.add_edge(ln.from_substation_id, ln.to_substation_id)
    comps = sorted(nx.connected_components(g), key=len, reverse=True)
    return len(comps), (len(comps[0]) if comps else 0)


def _connect_feature(e):
    a, b = e["a"], e["b"]
    return {"type": "Feature",
            "geometry": {"type": "LineString",
                         "coordinates": [[a["lon"], a["lat"]], [b["lon"], b["lat"]]]},
            "properties": {"power": "line", "voltage": e.get("kv"),
                           "name": "manual_connection", "source": "manual",
                           "supplement_source": "editor", "edit_id": e.get("id")}}


def _point_feature(e):
    pt = e["pt"]
    at = e.get("attrs", {}) or {}
    return {"type": "Feature",
            "geometry": {"type": "Point", "coordinates": [pt["lon"], pt["lat"]]},
            "properties": {"power": at.get("power", "substation"), "name": at.get("name"),
                           "voltage": at.get("voltage"), "source": "manual",
                           "edit_id": e.get("id")}}


def apply_to_dir(region, edits, base="data"):
    """edits を一時 data_dir に適用(connect/add_point→supplement)。(tmp_path, applied) を返す。"""
    tmp = tempfile.mkdtemp(prefix="agj_edit_")
    for fn in os.listdir(base):
        if (fn.startswith(region + "_") and fn.endswith(".geojson")
                and not fn.endswith("_lines_supplement.geojson")
                and not fn.endswith("_substations_supplement.geojson")):
            os.symlink(os.path.abspath(os.path.join(base, fn)), os.path.join(tmp, fn))

    def _load(fn):
        p = os.path.join(base, fn)
        if os.path.exists(p):
            return json.load(open(p, encoding="utf-8"))
        return {"type": "FeatureCollection", "features": []}

    lsupp = _load(f"{region}_lines_supplement.geojson")
    ssupp = _load(f"{region}_substations_supplement.geojson")
    applied = {"connect": 0, "add_point": 0, "disconnect_skipped": 0, "set_attr_skipped": 0}
    for e in edits:
        act = e.get("action")
        if act == "connect" and e.get("a") and e.get("b"):
            lsupp["features"].append(_connect_feature(e))
            applied["connect"] += 1
        elif act == "add_point" and e.get("pt"):
            ssupp["features"].append(_point_feature(e))
            applied["add_point"] += 1
        elif act == "disconnect":
            applied["disconnect_skipped"] += 1
        elif act == "set_attr":
            applied["set_attr_skipped"] += 1
    with open(os.path.join(tmp, f"{region}_lines_supplement.geojson"), "w", encoding="utf-8") as fh:
        json.dump(lsupp, fh, ensure_ascii=False)
    with open(os.path.join(tmp, f"{region}_substations_supplement.geojson"), "w", encoding="utf-8") as fh:
        json.dump(ssupp, fh, ensure_ascii=False)
    return tmp, applied


def verify(region, statuses=("pending", "verified"), base="data"):
    """pending(+verified)編集を適用して島数A/Bを返す(検証→判定材料)。"""
    edits = [e for e in edit_log.list_edits(region=region) if e.get("status") in statuses]
    nb, mb = _island_count(region)
    tmp, applied = apply_to_dir(region, edits, base=base)
    try:
        na, ma = _island_count(region, data_dir=tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {
        "region": region, "n_edits": len(edits), "applied": applied,
        "islands_before": nb, "islands_after": na, "delta_islands": na - nb,
        "main_before": mb, "main_after": ma,
        "note": "connect/add_pointの島削減を検証。disconnect→builder cut(E8b)・set_attr→enrichmentは別経路で反映",
    }
