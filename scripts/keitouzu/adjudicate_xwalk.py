#!/usr/bin/env python3
"""keitouzu crosswalk の ajg 対応の地理整合裁定（スクリーニング）。

判定則: AGJ ノード座標が、keitouzu 側の発行 region の地理 bbox
（docs/data/built/regions_bbox.json ＋バッファ0.3°）に入るか。

tier:
  confirmed  — 沖縄跨ぎ（独立系統ゆえ物理的に不可能）
  likely     — home bbox から 1.0° 超逸脱（同名異地の可能性が濃厚）
  borderline — 1.0° 以内の逸脱（bbox 越境・境界付近の変電所・他社エリア内自社設備の可能性）
  ok         — bbox+バッファ内

※ AGJ ノードの接頭辞 region は OSM 抽出 bbox であり越境スピルオーバーを含む。
  接頭辞不一致だけでは誤マッチと断定できない（例: 東京図の鬼怒川→tohoku接頭辞=栃木県内の実在変電所、
  四国の松山187kV→chugoku接頭辞。187kVは四国固有の電圧階級）。座標で判定する。
※ これはスクリーニング。最終裁定・crosswalk修正の上流報告は人間判断。

出力: docs/reports/keitouzu_xwalk_adjudication_<date>.{md,json}
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KZ = ROOT / "data" / "external" / "keitouzu"
BUILT = ROOT / "docs" / "data" / "built" / "all.json"
BBOX = ROOT / "docs" / "data" / "built" / "regions_bbox.json"
REPORTS = ROOT / "docs" / "reports"

BUFFER = 0.3   # bbox外縁の許容(度)
LIKELY = 1.0   # これを超える逸脱は「同名異地」濃厚


def bbox_excess(lat: float, lon: float, bb: dict) -> float:
    """bbox からの逸脱量(度)。内側なら 0。"""
    dlat = max(bb["lat_min"] - lat, lat - bb["lat_max"], 0.0)
    dlon = max(bb["lon_min"] - lon, lon - bb["lon_max"], 0.0)
    return max(dlat, dlon)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = args.date or subprocess.run(["date", "+%Y-%m-%d"], capture_output=True, text=True).stdout.strip()

    bboxes = json.load(open(BBOX))["regions"]
    built = json.load(open(BUILT))
    base2node: dict[str, dict] = {}
    for n in built["nodes"]:
        base2node.setdefault(n["id"].split("@")[0], n)

    subs = {r["uuid"]: r for r in csv.DictReader(open(KZ / "substations.csv"))}
    xw = [r for r in csv.DictReader(open(KZ / "crosswalk.csv")) if r["target_system"] == "ajg"]

    rows = []
    for c in xw:
        s = subs.get(c["uuid"])
        if not s:
            continue
        node = base2node.get(c["target_id"].split("@")[0])
        if node is None:
            continue
        home = bboxes.get(s["region"])
        exc = bbox_excess(node["lat"], node["lon"], home) if home else None
        if s["region"] == "okinawa" and exc and exc > BUFFER:
            tier = "confirmed"   # 独立系統: 県外対応は物理的に不可能
        elif exc is None:
            tier = "unknown"
        elif exc <= BUFFER:
            tier = "ok"
        elif exc - BUFFER > LIKELY:
            tier = "likely"
        else:
            tier = "borderline"
        rows.append({
            "keitouzu_uuid": c["uuid"],
            "keitouzu_name": s["name_official"],
            "keitouzu_region": s["region"],
            "ajg_target": c["target_id"],
            "ajg_name": node.get("name", ""),
            "ajg_lat": node["lat"],
            "ajg_lon": node["lon"],
            "bbox_excess_deg": round(exc, 2) if exc is not None else None,
            "match_method": c["match_method"],
            "confidence": c["confidence"],
            "tier": tier,
        })

    tiers = defaultdict(list)
    for r in rows:
        tiers[r["tier"]].append(r)

    # ---------- エッジ文脈裁定: 直線2°超の辺の「どちらの端点対応が誤りか」 ----------
    # 判定則: 端点の対応座標が、その変電所の他の keitouzu 隣接変電所(ok tier対応のみ)の
    # 対応座標の中央値から 1.0° 超離れていれば、その側の対応を誤りと判定。
    # bbox内の同名異地(例: 横浜の高田→上越の高田)もこの規則で捕れる。
    routes = [r for r in csv.DictReader(open(KZ / "routes.csv")) if r["status"] == "active"]
    coords_by_uuid: dict[str, list[tuple[float, float, str]]] = defaultdict(list)
    ok_coords_by_uuid: dict[str, list[tuple[float, float]]] = defaultdict(list)
    tier_by_pair = {}
    for r in rows:
        coords_by_uuid[r["keitouzu_uuid"]].append((r["ajg_lat"], r["ajg_lon"], r["ajg_target"]))
        tier_by_pair[(r["keitouzu_uuid"], r["ajg_target"])] = r["tier"]
        if r["tier"] == "ok":
            ok_coords_by_uuid[r["keitouzu_uuid"]].append((r["ajg_lat"], r["ajg_lon"]))
    nbrs: dict[str, set[str]] = defaultdict(set)
    for r in routes:
        nbrs[r["from_substation"]].add(r["to_substation"])
        nbrs[r["to_substation"]].add(r["from_substation"])

    def median_ctx(uuid: str) -> tuple[float, float] | None:
        pts = [p for nb in nbrs[uuid] for p in ok_coords_by_uuid.get(nb, ())]
        if not pts:
            return None
        lats, lons = sorted(p[0] for p in pts), sorted(p[1] for p in pts)
        return lats[len(lats) // 2], lons[len(lons) // 2]

    edge_verdicts = []
    for r in routes:
        fu, tu = r["from_substation"], r["to_substation"]
        fpts, tpts = coords_by_uuid.get(fu), coords_by_uuid.get(tu)
        if not fpts or not tpts:
            continue
        span = min(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 for a in fpts for b in tpts)
        if span <= 2.0:
            continue
        verdict = {"line": r.get("name_official", ""), "voltage_kv": r["voltage_kv"],
                   "region": r["region"], "span_deg": round(span, 2), "culprits": []}
        for side, u, pts in (("from", fu, fpts), ("to", tu, tpts)):
            ctx = median_ctx(u)
            for lat, lon, tid in pts:
                d = ((lat - ctx[0]) ** 2 + (lon - ctx[1]) ** 2) ** 0.5 if ctx else None
                if d is not None and d > 1.0:
                    verdict["culprits"].append({
                        "side": side, "keitouzu_uuid": u,
                        "keitouzu_name": subs[u]["name_official"],
                        "ajg_target": tid, "ctx_dist_deg": round(d, 2),
                        "tier": tier_by_pair.get((u, tid)),
                    })
        edge_verdicts.append(verdict)

    # 除外推奨 = confirmed/likely の対応 ＋ エッジ文脈で有罪の対応
    excluded = {(r["keitouzu_uuid"], r["ajg_target"]) for r in rows if r["tier"] in ("confirmed", "likely")}
    for v in edge_verdicts:
        for c in v["culprits"]:
            excluded.add((c["keitouzu_uuid"], c["ajg_target"]))

    out_json = REPORTS / f"keitouzu_xwalk_adjudication_{date}.json"
    out_md = REPORTS / f"keitouzu_xwalk_adjudication_{date}.md"
    json.dump({"date": date, "buffer_deg": BUFFER, "likely_deg": LIKELY,
               "counts": {k: len(v) for k, v in tiers.items()},
               "mappings": rows,
               "edge_verdicts": edge_verdicts,
               "excluded_mappings": sorted([list(p) for p in excluded])},
              open(out_json, "w"), ensure_ascii=False, indent=1)

    def table(rs):
        out = ["| keitouzu (region) | → ajg対応 | 座標 | 逸脱° | method |", "|---|---|---|---:|---|"]
        for r in sorted(rs, key=lambda x: -(x["bbox_excess_deg"] or 0)):
            out.append(f"| {r['keitouzu_name']} ({r['keitouzu_region']}) | {r['ajg_name']} `{r['ajg_target']}` | "
                       f"{r['ajg_lat']:.2f},{r['ajg_lon']:.2f} | {r['bbox_excess_deg']} | {r['match_method']} |")
        return out

    lines = [
        f"# keitouzu crosswalk 地理整合裁定（スクリーニング） — {date}",
        "",
        "AGJ ノード座標 vs keitouzu 発行 region の bbox（+0.3°バッファ）による機械裁定。",
        "**接頭辞 region の不一致だけでは誤マッチと断定できない**（OSM抽出bboxの越境スピルオーバー、",
        "他社エリア内の自社設備がある）ため、座標で判定する。最終裁定は人間判断。",
        "",
        f"- 対応総数: {len(rows)}（ok {len(tiers['ok'])} ／ borderline {len(tiers['borderline'])} ／ "
        f"likely {len(tiers['likely'])} ／ **confirmed {len(tiers['confirmed'])}**）",
        "",
        "## confirmed — 沖縄跨ぎ（独立系統ゆえ物理的に不可能）",
        "",
        *table(tiers["confirmed"]),
        "",
        "## likely — home bbox から 1.0° 超逸脱（同名異地の可能性濃厚）",
        "",
        *table(tiers["likely"]),
        "",
        "## borderline — 1.0° 以内の逸脱（境界付近の変電所・越境設備の可能性。個別確認推奨）",
        "",
        *table(tiers["borderline"]),
        "",
        "## エッジ文脈裁定 — 直線2°超の辺の有罪端点",
        "",
        "その変電所の他の keitouzu 隣接変電所の対応座標中央値から 1.0° 超離れた端点対応を有罪と判定。",
        "bbox 内の同名異地（例: 横浜の高田→上越の高田）もこの規則で捕捉。",
        "",
        "| 辺 | kV | region | 直線° | 有罪端点 → 誤対応 | 文脈乖離° |",
        "|---|---|---|---:|---|---:|",
        *[f"| {v['line'] or '(無名)'} | {v['voltage_kv']} | {v['region']} | {v['span_deg']} | "
          + ("; ".join(f"{c['keitouzu_name']}→`{c['ajg_target']}`" for c in v["culprits"]) or "判定不能(文脈なし)")
          + " | " + ("; ".join(str(c["ctx_dist_deg"]) for c in v["culprits"]) or "-") + " |"
          for v in edge_verdicts],
        "",
        f"**除外推奨対応（confirmed/likely + エッジ有罪の和集合）: {len(excluded)} 件** — 機械可読は JSON の `excluded_mappings`。",
        "crosswalk の上流修正報告・crosscheck からの除外に使う。**採用系の裁定（80断絶の原図照合）とは別物**。",
        "",
        "---",
        "生成: `scripts/keitouzu/adjudicate_xwalk.py`",
        "",
    ]
    out_md.write_text("\n".join(lines), encoding="utf-8")

    print(f"対応 {len(rows)} 件: ok={len(tiers['ok'])} borderline={len(tiers['borderline'])} "
          f"likely={len(tiers['likely'])} confirmed={len(tiers['confirmed'])}")
    print(f"→ {out_md.relative_to(ROOT)}")
    print(f"→ {out_json.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
