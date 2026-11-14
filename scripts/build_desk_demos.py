#!/usr/bin/env python3
"""desk の「デモ」と io に出す、1 枚で完結するページを作る(正典のデータを埋め込む)。

    PYTHONPATH=. python scripts/build_desk_demos.py            # 2 枚とも
    PYTHONPATH=. python scripts/build_desk_demos.py assembly   # 全国の送電網が組み上がる
    PYTHONPATH=. python scripts/build_desk_demos.py recipe     # 正典の作り方(新潟の中越)

- 出力: docs/demos/grid_assembly.html・docs/demos/canon_recipe.html(一覧は docs/demos.json)
- 編集する正本: scripts/templates/demo_grid_assembly.src.html・demo_canon_recipe.src.html と、
  下の ENGINE(2 枚で共通の地図の描き方)
- desk の枠は sandbox="allow-scripts" で、fetch・XHR・外からの読み込みが使えない。データはページに埋め込み、
  外からは何も読まない(書体も端末の書体)
- 埋め込むのは公開しているものだけ: 正典(docs/data/built・docs/data/map)、OSM の線と変電所(data/*.geojson)、
  連系線の形(docs/data/flow_map/occto_lines.json)、県の形(国土地理院のデータを簡略化したもの)、介入台帳の題
- 介入 #61 の前の正典は、#61 の直前の main(7f0993b2)を git から読む
"""
from __future__ import annotations

import heapq
import json
import math
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import yaml
from shapely.geometry import LineString, box

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.export_occto_today import outline as japan_outline  # noqa: E402
from scripts.readme_numbers import numbers as readme_numbers  # noqa: E402

DATA = ROOT / "docs" / "data"
OUT = ROOT / "docs" / "demos"
TMPL = ROOT / "scripts" / "templates"
BEFORE_61 = "7f0993b2"   # 介入 #61(PR #175)の直前の main

REGIONS = ["hokkaido", "tohoku", "tokyo", "chubu", "hokuriku", "kansai", "chugoku", "shikoku", "kyushu", "okinawa"]
REGION_JA = {"hokkaido": "北海道", "tohoku": "東北", "tokyo": "東京", "chubu": "中部", "hokuriku": "北陸",
             "kansai": "関西", "chugoku": "中国", "shikoku": "四国", "kyushu": "九州", "okinawa": "沖縄"}
# 同期している系統(島)。北海道は直流だけで本州とつながり、東(50 Hz)と西(60 Hz)は周波数変換所だけでつながる
ISLAND = {"hokkaido": 0, "tohoku": 1, "tokyo": 1, "chubu": 2, "hokuriku": 2, "kansai": 2,
          "chugoku": 2, "shikoku": 2, "kyushu": 2, "okinawa": 3}
ISLAND_JA = ["北海道(50 Hz)", "東(50 Hz)", "西(60 Hz)", "沖縄(60 Hz)"]


# ---------------------------------------------------------------- 共通

def km(p, q) -> float:
    """経度・緯度の 2 点の距離(km、球面の近似)"""
    lon1, lat1, lon2, lat2 = map(math.radians, (p[0], p[1], q[0], q[1]))
    a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(a)))


def path_km(cs) -> float:
    return sum(km(a, b) for a, b in zip(cs, cs[1:]))


def enc(cs, scale: int = 10000) -> list:
    """[[lon, lat], …] を、scale 倍の整数の差分の平たい並びにする(ページの側で足し戻す)"""
    out, x0, y0 = [], 0, 0
    for lon, lat in cs:
        x, y = round(lon * scale), round(lat * scale)
        out += [x - x0, y - y0]
        x0, y0 = x, y
    return out


def simp(cs, tol: float):
    if len(cs) <= 2 or tol <= 0:
        return [tuple(c[:2]) for c in cs]
    s = LineString([c[:2] for c in cs]).simplify(tol, preserve_topology=False)
    return list(s.coords) if not s.is_empty else [tuple(cs[0][:2]), tuple(cs[-1][:2])]


def parts(geom) -> list:
    if geom is None:
        return []
    if geom["type"] == "LineString":
        return [geom["coordinates"]]
    if geom["type"] == "MultiLineString":
        return list(geom["coordinates"])
    return []


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def git_json(rev: str, rel: str):
    out = subprocess.run(["git", "-C", str(ROOT), "show", f"{rev}:{rel}"], capture_output=True, check=True).stdout
    return json.loads(out)


def outline_enc() -> list:
    """日本の形(県の形の外周を簡略化したもの)。小数 2 桁なので 100 倍の整数で"""
    return [enc(r, 100) for r in japan_outline()]


def interventions() -> list:
    """介入台帳の表の行(番号・題・種別・リスク)。count_interventions と同じく、番号の整数でまとめる"""
    rows: dict = {}
    for line in (ROOT / "docs" / "MODEL_INTERVENTIONS.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*#?(\d+)([a-z\-]*)\s*\|([^|]*)\|([^|]*)\|([^|]*)\|", line)
        if not m:
            continue
        n = int(m.group(1))
        cell = m.group(3)
        b = re.search(r"\*\*(.+?)\*\*", cell)
        title = re.sub(r"[`*]", "", b.group(1) if b else cell).strip()
        title = title if len(title) <= 90 else title[:88] + "…"
        r = rows.setdefault(n, {"n": n, "t": [], "c": m.group(4).strip(), "s": m.group(5).strip().count("★")})
        r["t"].append((m.group(1) + m.group(2)) + " " + title)
    return [{"n": r["n"], "t": " / ".join(r["t"]), "c": r["c"], "s": r["s"]} for _, r in sorted(rows.items())]


def canon_totals() -> dict:
    n = readme_numbers()
    mv = load(DATA / "MODEL_VERSION.json")
    return {"nodes": n["nodes"], "edges": n["edges"], "interventions": n["interventions"],
            "osm_lines": n["lines"], "release": n["release"],
            "model_version": str(mv.get("model_version") or mv.get("version") or "")[:12]}


def render(name: str, data: dict) -> Path:
    src = (TMPL / f"demo_{name}.src.html").read_text(encoding="utf-8")
    js = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    out = src.replace("/*__ENGINE__*/", ENGINE.strip()).replace("/*__DATA__*/null", js)
    assert "/*__" not in out, "テンプレートの差し込み口が残っている"
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.html"
    path.write_text(out, encoding="utf-8")
    return path


# ---------------------------------------------------------------- 全国の送電網が組み上がる

def dijkstra(adj: dict, seeds: list) -> dict:
    dist = {s: 0.0 for s in seeds}
    pq = [(0.0, s) for s in seeds]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, math.inf):
            continue
        for v, w in adj[u]:
            nd = d + w
            if nd < dist.get(v, math.inf):
                dist[v] = nd
                heapq.heappush(pq, (nd, v))
    return dist


def components(adj: dict) -> list:
    seen, comps = set(), []
    for s in adj:
        if s in seen:
            continue
        stack, comp = [s], []
        seen.add(s)
        while stack:
            u = stack.pop()
            comp.append(u)
            for v, _ in adj[u]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        comps.append(comp)
    return comps


def grow_times(lines: list, members: list, seeds0: set) -> None:
    """members の線を、seeds0(無ければ成分ごとにいちばん枝の多い点)から道のりの順に伸ばす時刻を付ける。
    線ごとに t0(伸び始め)・t1(伸び終わり)を 0〜1 で、近い端から伸びるように並びの向きをそろえる"""
    key = lambda c: (round(c[0], 3), round(c[1], 3))
    adj = defaultdict(list)
    for i in members:
        a, b = key(lines[i]["cs"][0]), key(lines[i]["cs"][-1])
        adj[a].append((b, lines[i]["km"]))
        adj[b].append((a, lines[i]["km"]))
    seeds = [s for s in adj if s in seeds0]
    for comp in components(adj):
        if not any(s in seeds0 for s in comp):
            seeds.append(max(comp, key=lambda u: (len(adj[u]), u)))
    dist = dijkstra(adj, seeds)
    for i in members:
        ln = lines[i]
        a, b = key(ln["cs"][0]), key(ln["cs"][-1])
        da, db = dist.get(a, 0.0), dist.get(b, 0.0)
        if db < da:
            ln["cs"].reverse()
            da, db = db, da
        ln["d0"] = da
        ln["d1"] = da + ln["km"]
    # 道のりのままだと、長い 1 本の鎖が終わるまで待つ形になる。道のりの順は保ったまま、
    # 線が同じ割合で現れるように、道のりを順位(全体の何割目か)に置き換える
    vals = sorted({round(lines[i][k], 3) for i in members for k in ("d0", "d1")})
    rank = {v: j / max(1, len(vals) - 1) for j, v in enumerate(vals)}
    for i in members:
        lines[i]["t0"] = round(rank[round(lines[i]["d0"], 3)], 4)
        lines[i]["t1"] = round(rank[round(lines[i]["d1"], 3)], 4)


# 電圧の段(各社で 500 kV の下の基幹の電圧が違うので、級でまとめる)。2026-11-15 先生「275 kV が埋めるのところで、
# 中国・四国・九州が 500 しかない。北海道もない」「33 kV もあるなら載せるといい」。前は 275 kV 以上だけを描いていた
TIERS = [
    {"id": "t500", "label": "500 kV", "lo": 500, "tol": 0.0012},
    {"id": "trunk", "label": "275・220・187 kV", "lo": 187, "tol": 0.0012},
    {"id": "region", "label": "154・132・110 kV", "lo": 100, "tol": 0.0016},
    {"id": "local", "label": "77・66 kV(電圧不明を含む)", "lo": 0, "tol": 0.002},
    {"id": "osm_low", "label": "22・33 kV(OSM)", "lo": None, "tol": 0.002},
]
# OSM の 66 kV 未満の線のうち載せる電圧。25・20 kV は短い線ばかりで鉄道のき電線とみられるので載せない
OSM_LOW_KV = {22, 30, 33, 44}
_RAIL = re.compile(r"鉄道|旅客|JR|railway|Railway|RAILWAY")


def tier_of(kv: int) -> int:
    for g, t in enumerate(TIERS[:4]):
        if kv >= t["lo"]:
            return g
    return 3


def osm_low_lines() -> list:
    """OSM の 22・33 kV などの線(正典には 66 kV より低い級が無い)。沖縄と鉄道は外す"""
    out, seen = [], set()
    for r in REGIONS:
        if r == "okinawa":
            continue
        for f in load(ROOT / "data" / f"{r}_lines.geojson")["features"]:
            p = f["properties"]
            oid = p.get("osm_id")
            if oid in seen:
                continue
            kv = _kv(p.get("voltage"))
            if kv not in OSM_LOW_KV or _RAIL.search(" ".join(str(p.get(k) or "") for k in ("operator", "name", "line"))):
                continue
            seen.add(oid)
            for cs in parts(f["geometry"]):
                if len(cs) >= 2:
                    out.append({"cs": [tuple(c[:2]) for c in cs], "kv": kv, "r": r, "g": 4,
                                "n": str(p.get("name") or ""), "km": path_km(cs)})
    return out


def assembly_data() -> dict:
    feats = load(DATA / "map" / "lines_all.geojson")["features"]
    lines = []
    for f in feats:
        p = f["properties"]
        r = p.get("_region", "")
        if r not in REGIONS or r == "okinawa":
            continue
        kv = int(round(float(p.get("_voltage_kv") or 0)))
        for cs in parts(f["geometry"]):
            if len(cs) < 2:
                continue
            lines.append({"cs": [tuple(c[:2]) for c in cs], "kv": kv, "r": r, "g": tier_of(kv),
                          "n": p.get("_display_name") or "", "km": path_km(cs)})
    lines += osm_low_lines()
    # 段ごとに、上の段の網の点から外へ伸ばす(上の段に届かない成分は、その中の枝の多い点から)
    key = lambda c: (round(c[0], 3), round(c[1], 3))
    above: set = set()
    for g in range(len(TIERS)):
        members = [i for i, ln in enumerate(lines) if ln["g"] == g]
        if members:
            grow_times(lines, members, set(above))
            above |= {key(lines[i]["cs"][j]) for i in members for j in (0, -1)}

    out_lines, lab = [], defaultdict(lambda: [0.0, 0.0, 0.0])
    for ln in lines:
        s = simp(ln["cs"], TIERS[ln["g"]]["tol"])
        r = ln["r"]
        out_lines.append({"g": ln["g"], "v": ln["kv"], "r": REGIONS.index(r) if r in REGIONS else 0, "q": enc(s),
                          "t0": ln["t0"], "t1": ln["t1"], "n": ln["n"][:40], "km": round(ln["km"], 1)})
        if ln["g"] <= 2:                     # 地域の名前の位置は上の 3 段で決める(下の段の多い所に引っぱられない)
            for c in ln["cs"]:
                lab[r][0] += c[0]
                lab[r][1] += c[1]
                lab[r][2] += 1.0
    labels = [{"r": REGIONS.index(r), "ja": REGION_JA[r], "lon": round(v[0] / v[2], 3), "lat": round(v[1] / v[2], 3)}
              for r, v in lab.items() if v[2] and r in REGIONS]

    occ = load(DATA / "flow_map" / "occto_lines.json")
    ics = []
    for ic in occ["ics"]:
        ps = ic.get("p") or ([ic["w"]] if ic.get("w") else [ic["s"]])
        ics.append({"n": ic.get("n") or ic.get("k") or "", "k": ic.get("kind", ""),
                    "a": [REGIONS.index(x) for x in ic.get("a", []) if x in REGIONS],
                    "q": [enc(simp(pp, 0.001)) for pp in ps if len(pp) >= 2]})
    conv = [{"n": c["n"], "k": c["kind"], "lon": c["s"][0], "lat": c["s"][1]} for c in occ["converters"]]

    stat = {"tiers": [{"id": t["id"], "label": t["label"], "n": sum(1 for ln in lines if ln["g"] == g),
                       "km": round(sum(ln["km"] for ln in lines if ln["g"] == g)),
                       "kv": sorted({ln["kv"] for ln in lines if ln["g"] == g}, reverse=True)}
                      for g, t in enumerate(TIERS)],
            # 段ごと・地域ごとの電圧と km(説明文で、どの会社がどの電圧かを数から言う)
            "by_region": {REGION_JA[r]: {str(g): {str(kv): round(sum(ln["km"] for ln in lines
                                                                   if ln["r"] == r and ln["g"] == g and ln["kv"] == kv))
                                                  for kv in sorted({ln["kv"] for ln in lines if ln["r"] == r and ln["g"] == g})}
                                         for g in range(len(TIERS))}
                          for r in REGIONS if r != "okinawa"}}
    return {"made": canon_totals(), "stat": stat, "regions": [REGION_JA[r] for r in REGIONS],
            "island_of": [ISLAND[r] for r in REGIONS], "islands": ISLAND_JA,
            "outline": outline_enc(), "lines": out_lines, "labels": labels, "ics": ics, "conv": conv}


# ---------------------------------------------------------------- 正典の作り方(新潟の中越)

WIN = {"lat_min": 36.95, "lat_max": 37.80, "lon_min": 138.20, "lon_max": 139.30}
CLIP = 0.06   # 窓の外へこれだけ(度)はみ出した所までは残す


def _in(lat, lon, m=0.0) -> bool:
    return (WIN["lat_min"] - m <= lat <= WIN["lat_max"] + m) and (WIN["lon_min"] - m <= lon <= WIN["lon_max"] + m)


def _clip_cs(cs):
    """窓(少し広げた)で線を切る。窓に掛からなければ空"""
    if not any(_in(c[1], c[0]) for c in cs):
        return []
    g = LineString([c[:2] for c in cs]).intersection(
        box(WIN["lon_min"] - CLIP, WIN["lat_min"] - CLIP, WIN["lon_max"] + CLIP, WIN["lat_max"] + CLIP))
    geoms = [g] if g.geom_type == "LineString" else list(getattr(g, "geoms", []))
    return [list(x.coords) for x in geoms if x.geom_type == "LineString" and len(x.coords) >= 2]


def _kv(v) -> int:
    best = 0
    for s in str(v or "").replace(",", ";").split(";"):
        try:
            best = max(best, int(round(float(s) / 1000)))
        except ValueError:
            pass
    return best


def _disclosure_class(e: dict) -> str | None:
    """正典の枝の出どころ(公表の資料・OSM の線の回収など)を、ページで色分けする区分にまとめる"""
    if e.get("recovery"):
        return "recovery"
    c = str(e.get("conn_class") or "")
    t = str(e.get("disclosure") or "")
    if c.startswith("disclosure") or t.startswith("系統図判読") or "様式" in t:
        return "disclosure"
    if t.startswith("同名"):
        return "same_name"
    if t.startswith("OSM実線"):
        return "recovery"
    return "other" if t else None


def _canon_window(b: dict) -> tuple[list, list]:
    nodes, edges = [], []
    for n in b["nodes"]:
        if _in(n["lat"], n["lon"], CLIP):
            nd = {"lon": round(n["lon"], 5), "lat": round(n["lat"], 5), "kv": int(round(float(n.get("kv") or 0))),
                  "s": int(n.get("sub") or 0)}
            if nd["s"]:
                nm = str(n.get("name") or "")
                # 自動の名前(tohoku_sub_987 500kV など)は出さない。会社の名前の前置きと、ローマ字の添え書きは外す
                nm = re.sub(r"\s*\([A-Za-z][^)]*\)", "", nm)
                nm = re.sub(r"^(東北電力ネットワーク\s*[\(（]株[\)）]|東北電力ネットワーク株式会社|東北電力|東京電力パワーグリッド)\s*", "", nm)
                nd["n"] = "" if re.match(r"^\w+_(sub|substation)_\d+(\s+\d+kV)?$", nm) else nm[:24]
            if n.get("supplement"):
                nd["sup"] = 1
            nodes.append(nd)
    for e in b["edges"]:
        cs = [(p[1], p[0]) for p in (e.get("path") or [e["a"], e["b"]])]
        for piece in _clip_cs(cs):
            ed = {"kv": int(round(float(e.get("kv") or 0))), "q": enc(simp(piece, 0.00008)),
                  "k": [round(e["a"][0], 4), round(e["a"][1], 4), round(e["b"][0], 4), round(e["b"][1], 4)]}
            c = _disclosure_class(e)
            if c:
                ed["c"] = c
            edges.append(ed)
    return nodes, edges


def _nearest_km(nodes: list, lon: float, lat: float) -> tuple[float, dict]:
    best = min(nodes, key=lambda n: km((n["lon"], n["lat"]), (lon, lat)))
    return round(km((best["lon"], best["lat"]), (lon, lat)), 2), {"lon": best["lon"], "lat": best["lat"], "kv": best["kv"]}


def recipe_data() -> dict:
    # 1. OSM の線(way)と変電所。way の番号の順は、OSM に描かれた順のおおよそ
    ways, subs = [], []
    for r in ["tohoku", "tokyo", "chubu", "hokuriku"]:
        for f in load(ROOT / "data" / f"{r}_lines.geojson")["features"]:
            p = f["properties"]
            for cs in parts(f["geometry"]):
                for piece in _clip_cs(cs):
                    ways.append({"id": int(p.get("osm_id") or 0), "kv": _kv(p.get("voltage")),
                                 "add": 1 if p.get("_added_by") else 0, "cs": piece})
        for f in load(ROOT / "data" / f"{r}_substations.geojson")["features"]:
            g = f["geometry"]
            if g is None:
                continue
            pts = g["coordinates"] if g["type"] == "Point" else None
            if pts is None:
                ring = g["coordinates"][0] if g["type"] == "Polygon" else g["coordinates"][0][0]
                pts = [sum(c[0] for c in ring) / len(ring), sum(c[1] for c in ring) / len(ring)]
            if _in(pts[1], pts[0]):
                subs.append({"lon": round(pts[0], 5), "lat": round(pts[1], 5),
                             "kv": _kv(f["properties"].get("voltage")), "add": 1 if f["properties"].get("_added_by") else 0})
    # 同じ way が 2 つの地域の取り出しに入っていれば 1 つに
    seen, uniq = set(), []
    for w in sorted(ways, key=lambda w: (w["id"], w["cs"][0])):
        k = (w["id"], round(w["cs"][0][0], 5), round(w["cs"][0][1], 5))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(w)
    ways = uniq
    # 端がほかの way の頂点に触れているか(25 m 以内)。触れていない端は、変電所の敷地で終わるものも含む
    cell = defaultdict(list)
    for wi, w in enumerate(ways):
        for c in w["cs"]:
            cell[(round(c[0] * 1000), round(c[1] * 1000))].append((wi, c))
    def touches(wi, c):
        cx, cy = round(c[0] * 1000), round(c[1] * 1000)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for wj, d in cell.get((cx + dx, cy + dy), ()):
                    if wj != wi and km(c, d) <= 0.025:
                        return True
        return False
    out_ways, n_loose = [], 0
    for wi, w in enumerate(ways):
        loose = [0 if touches(wi, w["cs"][0]) else 1, 0 if touches(wi, w["cs"][-1]) else 1]
        if not _in(w["cs"][0][1], w["cs"][0][0]):
            loose[0] = 0   # 窓で切った端は数えない
        if not _in(w["cs"][-1][1], w["cs"][-1][0]):
            loose[1] = 0
        n_loose += sum(loose)
        out_ways.append({"kv": w["kv"], "add": w["add"], "e": loose, "q": enc(simp(w["cs"], 0.00008))})

    # 2. 正典(いま)と #61 の前
    now = load(DATA / "built" / "all.json")
    before = git_json(BEFORE_61, "docs/data/built/all.json")
    n_now, e_now = _canon_window(now)
    n_old, e_old = _canon_window(before)
    old_keys = {tuple(e["k"]) for e in e_old} | {(e["k"][2], e["k"][3], e["k"][0], e["k"][1]) for e in e_old}
    for e in e_now:
        if tuple(e["k"]) not in old_keys:
            e["new"] = 1
    old_pts = {(n["lon"], n["lat"]) for n in n_old}
    for n in n_now:
        if (n["lon"], n["lat"]) not in old_pts:
            n["new"] = 1
    for e in e_now + e_old:
        e.pop("k", None)

    # 柏崎刈羽(発電所の一覧から)と、いちばん近い正典の点
    kk = None
    for f in load(ROOT / "data" / "tohoku_plants.geojson")["features"]:
        nm = str(f["properties"].get("name") or "")
        if "柏崎刈羽" in nm and f["geometry"]:
            g = f["geometry"]
            if g["type"] == "Point":
                kk = g["coordinates"][:2]
            else:
                ring = g["coordinates"][0] if g["type"] == "Polygon" else g["coordinates"][0][0]
                kk = [sum(c[0] for c in ring) / len(ring), sum(c[1] for c in ring) / len(ring)]
            break
    kk_info = None
    if kk:
        full_old = [{"lon": n["lon"], "lat": n["lat"], "kv": int(round(float(n.get("kv") or 0)))} for n in before["nodes"]]
        full_now = [{"lon": n["lon"], "lat": n["lat"], "kv": int(round(float(n.get("kv") or 0)))} for n in now["nodes"]]
        d_old, p_old = _nearest_km(full_old, *kk)
        d_now, p_now = _nearest_km(full_now, *kk)
        kk_info = {"lon": round(kk[0], 4), "lat": round(kk[1], 4), "before_km": d_old, "before": p_old,
                   "after_km": d_now, "after": p_now}

    # #61 の前の外接矩形(config/regions.yaml)
    old_cfg = yaml.safe_load(subprocess.run(["git", "-C", str(ROOT), "show", f"{BEFORE_61}:config/regions.yaml"],
                                            capture_output=True, check=True).stdout)
    cfg_regions = old_cfg.get("regions", old_cfg)
    boxes = []
    for r in ["tohoku", "tokyo", "chubu", "hokuriku"]:
        bb = (cfg_regions.get(r) or {}).get("bbox") or (cfg_regions.get(r) or {}).get("bounding_box")
        if bb:
            boxes.append({"r": REGION_JA[r], "lat_min": bb["lat_min"], "lat_max": bb["lat_max"],
                          "lon_min": bb["lon_min"], "lon_max": bb["lon_max"]})

    nat = []
    for f in load(DATA / "map" / "lines_275kv.geojson")["features"]:
        if float(f["properties"].get("_voltage_kv") or 0) >= 500:
            for cs in parts(f["geometry"]):
                nat.append(enc(simp(cs, 0.004), 1000))

    cls = defaultdict(int)
    for e in e_now:
        if e.get("c"):
            cls[e["c"]] += 1
    stat = {"ways": len(out_ways), "ways_added": sum(w["add"] for w in out_ways), "loose": n_loose,
            "subs_osm": len(subs), "subs_added": sum(s["add"] for s in subs),
            "nodes": sum(1 for n in n_now if _in(n["lat"], n["lon"])),
            "subs": sum(1 for n in n_now if n["s"] and _in(n["lat"], n["lon"])),
            "edges": len(e_now), "nodes_before": sum(1 for n in n_old if _in(n["lat"], n["lon"])),
            "subs_before": sum(1 for n in n_old if n["s"] and _in(n["lat"], n["lon"])),
            "edges_before": len(e_old), "edges_new": sum(1 for e in e_now if e.get("new")),
            "nodes_new": sum(1 for n in n_now if n.get("new") and _in(n["lat"], n["lon"])),
            "sup": sum(1 for n in n_now if n.get("sup") and _in(n["lat"], n["lon"])), "cls": dict(cls)}
    return {"made": canon_totals(), "win": WIN, "stat": stat, "outline": outline_enc(), "nat500": nat,
            "ways": out_ways, "subs": subs, "now": {"nodes": n_now, "edges": e_now},
            "before": {"nodes": n_old, "edges": e_old}, "kk": kk_info, "boxes": boxes,
            "band": {"lat_min": 37.0, "lat_max": WIN["lat_max"] + 1, "lon_min": 137.9, "lon_max": 139.0},
            "ledger": interventions()}


# ---------------------------------------------------------------- 2 枚で共通の地図の描き方(ページに差し込む)

ENGINE = r"""
const MERC = lat => 180 / Math.PI * Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360));
/** 差分の整数の並び → 投影した座標の Float32Array [x0, y0, x1, y1, …](x=経度、y=メルカトルの緯度) */
function decode(a, s) {
  const out = new Float32Array(a.length); let x = 0, y = 0;
  for (let i = 0; i < a.length; i += 2) { x += a[i]; y += a[i + 1]; out[i] = x / s; out[i + 1] = MERC(y / s); }
  return out;
}
/** 道のりの累積(線を途中まで描くため) */
function cumlen(P) {
  const c = new Float32Array(P.length / 2); let t = 0;
  for (let i = 2; i < P.length; i += 2) { t += Math.hypot(P[i] - P[i - 2], P[i + 1] - P[i - 1]); c[i / 2] = t; }
  return c;
}
function bboxOf(P) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (let i = 0; i < P.length; i += 2) { const x = P[i], y = P[i + 1]; if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
  return [x0, y0, x1, y1];
}
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const ease = t => t < .5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
const fmt = n => Math.round(n).toLocaleString('ja-JP');

/** 地図の視点(中心と倍率)。ドラッグで動かす、ホイールで拡大、0 で戻す */
class View {
  constructor(canvas, onChange) {
    this.c = canvas; this.ctx = canvas.getContext('2d'); this.cx = 137; this.cy = MERC(37); this.k = 30;
    this.user = false; this.onChange = onChange; this.anim = null;
    const ro = new ResizeObserver(() => this.resize()); ro.observe(canvas); this.resize();
    let drag = null;
    canvas.addEventListener('pointerdown', e => { drag = { x: e.clientX, y: e.clientY, cx: this.cx, cy: this.cy }; canvas.setPointerCapture(e.pointerId); });
    canvas.addEventListener('pointermove', e => {
      if (!drag) return;
      this.cx = drag.cx - (e.clientX - drag.x) / this.k; this.cy = drag.cy + (e.clientY - drag.y) / this.k;
      if (Math.abs(e.clientX - drag.x) + Math.abs(e.clientY - drag.y) > 3) { this.user = true; this.anim = null; }
      this.onChange();
    });
    canvas.addEventListener('pointerup', () => { drag = null; });
    canvas.addEventListener('wheel', e => {
      e.preventDefault();
      const r = canvas.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
      const [wx, wy] = this.inv(mx, my), f = Math.exp(-e.deltaY * 0.0015);
      this.k = clamp(this.k * f, 4, 20000);
      this.cx = wx - (mx - this.w / 2) / this.k; this.cy = wy + (my - this.h / 2) / this.k;
      this.user = true; this.anim = null; this.onChange();
    }, { passive: false });
  }
  resize() {
    const d = window.devicePixelRatio || 1, r = this.c.getBoundingClientRect();
    this.w = Math.max(1, r.width); this.h = Math.max(1, r.height); this.dpr = d;
    this.c.width = Math.round(this.w * d); this.c.height = Math.round(this.h * d);
    if (this.fitBox && !this.user) this.fit(this.fitBox, this.fitPad);
    this.onChange && this.onChange();
  }
  /** 経度・緯度の範囲 [lon0, lat0, lon1, lat1] が入る視点(pad は左・上・右・下の余白 px) */
  target(b, pad) {
    const [l, t, r, bt] = pad || [20, 20, 20, 20];
    const x0 = b[0], x1 = b[2], y0 = MERC(b[1]), y1 = MERC(b[3]);
    const k = Math.min((this.w - l - r) / (x1 - x0), (this.h - t - bt) / (y1 - y0));
    const cx = (x0 + x1) / 2 - (l - r) / 2 / k, cy = (y0 + y1) / 2 + (t - bt) / 2 / k;
    return { cx, cy, k: Math.max(1, k) };
  }
  fit(b, pad) { this.fitBox = b; this.fitPad = pad; Object.assign(this, this.target(b, pad)); }
  flyTo(b, pad, ms) {
    if (this.user) return;
    this.fitBox = b; this.fitPad = pad;
    const to = this.target(b, pad), from = { cx: this.cx, cy: this.cy, k: this.k };
    this.anim = { from, to, t0: performance.now(), ms };
  }
  step(now) {
    if (!this.anim) return false;
    const a = this.anim, u = clamp((now - a.t0) / a.ms, 0, 1), e = ease(u);
    const lk = Math.log(a.from.k) + (Math.log(a.to.k) - Math.log(a.from.k)) * e;
    this.k = Math.exp(lk); this.cx = a.from.cx + (a.to.cx - a.from.cx) * e; this.cy = a.from.cy + (a.to.cy - a.from.cy) * e;
    if (u >= 1) this.anim = null;
    return true;
  }
  sx(x) { return (x - this.cx) * this.k + this.w / 2; }
  sy(y) { return -(y - this.cy) * this.k + this.h / 2; }
  inv(px, py) { return [(px - this.w / 2) / this.k + this.cx, -(py - this.h / 2) / this.k + this.cy]; }
  begin(bg) {
    const g = this.ctx; g.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    g.globalCompositeOperation = 'source-over'; g.globalAlpha = 1; g.fillStyle = bg; g.fillRect(0, 0, this.w, this.h);
    return g;
  }
  /** 線を frac(0〜1)まで描く。C は cumlen の結果 */
  path(g, P, C, frac) {
    const n = P.length / 2; if (n < 2) return null;
    const total = C[n - 1], stop = frac >= 1 ? total : total * frac;
    g.moveTo(this.sx(P[0]), this.sy(P[1]));
    for (let i = 1; i < n; i++) {
      if (C[i] <= stop) { g.lineTo(this.sx(P[2 * i]), this.sy(P[2 * i + 1])); continue; }
      const seg = C[i] - C[i - 1], u = seg > 0 ? (stop - C[i - 1]) / seg : 1;
      const x = P[2 * i - 2] + (P[2 * i] - P[2 * i - 2]) * u, y = P[2 * i - 1] + (P[2 * i + 1] - P[2 * i - 1]) * u;
      g.lineTo(this.sx(x), this.sy(y)); return [this.sx(x), this.sy(y)];
    }
    return [this.sx(P[2 * n - 2]), this.sy(P[2 * n - 1])];
  }
  ring(g, P) {
    for (let i = 0; i < P.length; i += 2) { const x = this.sx(P[i]), y = this.sy(P[i + 1]); i ? g.lineTo(x, y) : g.moveTo(x, y); }
    g.closePath();
  }
  /** 画面上の点 (px, py) から線 P までの距離(px) */
  dist(P, px, py) {
    let best = Infinity;
    for (let i = 2; i < P.length; i += 2) {
      const ax = this.sx(P[i - 2]), ay = this.sy(P[i - 1]), bx = this.sx(P[i]), by = this.sy(P[i + 1]);
      const dx = bx - ax, dy = by - ay, L = dx * dx + dy * dy;
      const u = L ? clamp(((px - ax) * dx + (py - ay) * dy) / L, 0, 1) : 0;
      const d = Math.hypot(ax + dx * u - px, ay + dy * u - py); if (d < best) best = d;
    }
    return best;
  }
}

/** 場面の再生(時刻のつまみ・再生と停止・場面の札)。scenes = [{id, label, dur}] */
class Player {
  constructor(scenes, onTime) {
    this.scenes = scenes; this.onTime = onTime; this.T = 0; this.playing = false;
    this.starts = []; let t = 0; for (const s of scenes) { this.starts.push(t); t += s.dur; } this.total = t;
    this.btn = document.getElementById('play'); this.range = document.getElementById('time'); this.chips = document.getElementById('chips');
    this.range.max = String(Math.round(this.total * 100));
    this.btn.addEventListener('click', () => this.toggle());
    this.range.addEventListener('input', () => { this.pause(); this.seek(Number(this.range.value) / 100); });
    scenes.forEach((s, i) => {
      const b = document.createElement('button'); b.className = 'chip'; b.type = 'button';
      b.innerHTML = `<span class="num">${i + 1}</span><span class="lab">${s.label}</span>`; b.title = s.label;
      b.addEventListener('click', () => this.go(i)); this.chips.appendChild(b);
    });
    window.addEventListener('keydown', e => {
      if (e.target && /INPUT|TEXTAREA/.test(e.target.tagName) && e.target.type !== 'range') return;
      if (e.code === 'Space') { e.preventDefault(); this.toggle(); }
      else if (e.key === 'ArrowRight') { e.preventDefault(); this.go(Math.min(this.scenes.length - 1, this.scene() + 1)); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); this.go(Math.max(0, this.scene() - (this.local() < .15 ? 1 : 0))); }
      else if (e.key === 'Home') { this.go(0); }
    });
  }
  scene(T = this.T) { let i = 0; while (i + 1 < this.starts.length && T >= this.starts[i + 1] - 1e-9) i++; return i; }
  local(T = this.T) { const i = this.scene(T), d = this.scenes[i].dur; return d ? clamp((T - this.starts[i]) / d, 0, 1) : 1; }
  go(i) { this.seek(this.starts[i] + 1e-6); if (!this.playing && this.scenes[i].dur) this.play(); }
  seek(T) { this.T = clamp(T, 0, this.total); this.sync(); this.onTime(this.T); }
  sync() {
    this.range.value = String(Math.round(this.T * 100)); const i = this.scene();
    [...this.chips.children].forEach((c, j) => { c.classList.toggle('on', j === i); c.classList.toggle('done', j < i); });
    this.btn.textContent = this.playing ? '❚❚' : '▶'; this.btn.setAttribute('aria-label', this.playing ? '止める' : '再生');
  }
  play() { if (this.T >= this.total - 1e-3) this.T = 0; this.playing = true; this.last = performance.now(); this.sync(); }
  pause() { this.playing = false; this.sync(); }
  toggle() { this.playing ? this.pause() : this.play(); }
  tick(now) {
    if (!this.playing) return false;
    const dt = Math.min(.1, (now - this.last) / 1000); this.last = now; this.T += dt;
    if (this.T >= this.total) { this.T = this.total; this.playing = false; }
    this.sync(); this.onTime(this.T); return true;
  }
}

/** 色の組(?theme=light で明るい地図) */
function themeOf() {
  const q = new URLSearchParams(location.search).get('theme');
  return q === 'light' ? 'light' : 'dark';
}
function applyTheme(t) { document.documentElement.dataset.theme = t; }
/** 説明の札を畳む(幅の狭い枠では畳んで始める) */
function setupPanel() {
  const p = document.getElementById('panel'), b = document.getElementById('fold');
  const narrow = () => window.innerWidth <= 880 || window.innerHeight <= 560;
  const q = new URLSearchParams(location.search).get('embed');
  if ((q === '1' || narrow()) && q !== '0') p.classList.add('folded');
  b.addEventListener('click', () => p.classList.toggle('folded'));
}
"""


def main(argv: list[str]) -> int:
    which = argv[1:] or ["assembly", "recipe"]
    for w in which:
        if w == "assembly":
            path = render("grid_assembly", assembly_data())
        elif w == "recipe":
            path = render("canon_recipe", recipe_data())
        else:
            print(f"知らない名前: {w}(assembly か recipe)", file=sys.stderr)
            return 2
        print(f"{path.relative_to(ROOT)}  {path.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
