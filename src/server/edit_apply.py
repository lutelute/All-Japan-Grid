"""E8: 編集ログをモデルに適用して検証する(connect/add_point → supplement)。

pending編集を一時 data_dir に適用し、`build_network_snapped` で島数 before/after を出す。
物理接続=真・捏造禁止: 検証で島削減(将来はρ/AC維持も)が確認できた編集のみ adopt 候補。

適用先(設計 docs/CONNECTION_EDITOR_DESIGN.md):
  connect   → {region}_lines_supplement.geojson に LineString追記(builderが取込)
  add_point → {region}_substations_supplement.geojson に Point追記
  disconnect→ {region}_cuts.json に端点座標を追記(E8b・builderが自動読込し該当枝を生成しない)
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


def _cut_entries(edits):
    """disconnect編集(a+b 座標)を切断エントリへ。座標がある誤接続のみ(捏造の逆=抑制)。

    line_keyのみの disconnect は端点座標が無いため現状skip(builderは座標で枝を照合する)。
    """
    out = []
    for e in edits:
        if e.get("action") != "disconnect":
            continue
        a, b = e.get("a"), e.get("b")
        if a and b and "lat" in a and "lon" in a and "lat" in b and "lon" in b:
            out.append({"a": {"lat": a["lat"], "lon": a["lon"]},
                        "b": {"lat": b["lat"], "lon": b["lon"]},
                        "edit_id": e.get("id")})
    return out


def _load_base_cuts(base, region, drop_editor=True):
    """data/{region}_cuts.json を読む(editor由来=edit_id付きは drop_editor 時に除外し再構築)。"""
    p = os.path.join(base, f"{region}_cuts.json")
    if not os.path.exists(p):
        return []
    try:
        d = json.load(open(p, encoding="utf-8"))
        cuts = d.get("cuts", d) if isinstance(d, dict) else d
    except (OSError, ValueError):
        return []
    if drop_editor:
        cuts = [c for c in cuts if not c.get("edit_id")]
    return cuts


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
    applied = {"connect": 0, "add_point": 0, "disconnect": 0, "set_attr_skipped": 0}
    for e in edits:
        act = e.get("action")
        if act == "connect" and e.get("a") and e.get("b"):
            lsupp["features"].append(_connect_feature(e))
            applied["connect"] += 1
        elif act == "add_point" and e.get("pt"):
            ssupp["features"].append(_point_feature(e))
            applied["add_point"] += 1
        elif act == "set_attr":
            applied["set_attr_skipped"] += 1
    # disconnect → 切断キュレーション(builderが {region}_cuts.json を自動読込し枝を生成しない)
    cuts = _load_base_cuts(base, region) + _cut_entries(edits)
    applied["disconnect"] = len(_cut_entries(edits))
    with open(os.path.join(tmp, f"{region}_lines_supplement.geojson"), "w", encoding="utf-8") as fh:
        json.dump(lsupp, fh, ensure_ascii=False)
    with open(os.path.join(tmp, f"{region}_substations_supplement.geojson"), "w", encoding="utf-8") as fh:
        json.dump(ssupp, fh, ensure_ascii=False)
    with open(os.path.join(tmp, f"{region}_cuts.json"), "w", encoding="utf-8") as fh:
        json.dump({"cuts": cuts}, fh, ensure_ascii=False)
    return tmp, applied


def adopt(region, statuses=("pending", "verified"), base="data"):
    """connect/add_point編集を実supplementに**永続適用**し、再構築後の島数を返す(=反映)。

    edit由来(properties.edit_id)を一旦除去して現在の編集で作り直す**同期**方式:
    冪等で、編集を取消(removeEdit)してから再度adoptすればsupplementからも消える(可逆)。
    editor以外がキュレートしたsupplement(edit_id無し)は温存する。
    これがE8の「adopted接続のsupplement統合」=モデルへの反映。
    """
    lpath = os.path.join(base, f"{region}_lines_supplement.geojson")
    spath = os.path.join(base, f"{region}_substations_supplement.geojson")
    cpath = os.path.join(base, f"{region}_cuts.json")

    def _load(p):
        if os.path.exists(p):
            return json.load(open(p, encoding="utf-8"))
        return {"type": "FeatureCollection", "features": []}

    lsupp = _load(lpath)
    ssupp = _load(spath)
    # editor由来(edit_id付き)を除去 → 現在の編集で作り直す(同期=可逆)
    lsupp["features"] = [f for f in lsupp["features"]
                         if not (f.get("properties") or {}).get("edit_id")]
    ssupp["features"] = [f for f in ssupp["features"]
                         if not (f.get("properties") or {}).get("edit_id")]
    edits = [e for e in edit_log.list_edits(region=region)
             if e.get("status") in statuses]
    applied = {"connect": 0, "add_point": 0, "disconnect": 0, "set_attr_skipped": 0}
    for e in edits:
        act = e.get("action")
        if act == "connect" and e.get("a") and e.get("b"):
            lsupp["features"].append(_connect_feature(e))
            applied["connect"] += 1
        elif act == "add_point" and e.get("pt"):
            ssupp["features"].append(_point_feature(e))
            applied["add_point"] += 1
        elif act == "set_attr":
            applied["set_attr_skipped"] += 1
    # disconnect → {region}_cuts.json(builder自動読込で枝を生成しない・editor由来は同期で再構築)
    cuts = _load_base_cuts(base, region) + _cut_entries(edits)
    applied["disconnect"] = len(_cut_entries(edits))
    os.makedirs(base, exist_ok=True)
    with open(lpath, "w", encoding="utf-8") as fh:
        json.dump(lsupp, fh, ensure_ascii=False)
    with open(spath, "w", encoding="utf-8") as fh:
        json.dump(ssupp, fh, ensure_ascii=False)
    if cuts or os.path.exists(cpath):     # 空でも既存があれば書く(最後の切断の取消=可逆)
        with open(cpath, "w", encoding="utf-8") as fh:
            json.dump({"cuts": cuts}, fh, ensure_ascii=False)
    nb, mb = _island_count(region)   # supplement+cut書込後の実モデル=反映後
    return {"region": region, "applied": applied, "n_edits": len(edits),
            "lines_supplement": len(lsupp["features"]),
            "subs_supplement": len(ssupp["features"]), "cuts": len(cuts),
            "islands_now": nb, "main_now": mb,
            "note": "connect/add_point→supplement・disconnect→cuts.jsonに反映(可逆・同期)。set_attrは別経路"}


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
        "note": "connect/add_point(島削減)とdisconnect(誤接続の切断=builder cut)を一時適用して検証。set_attr→enrichmentは別経路",
    }
