#!/usr/bin/env python3
"""線路観測（実測潮流＋運用容量＋インピーダンス）を地図用GeoJSONにする。

★照合は **線路名** を第一経路にする。
  OSM の送電線には正式名が入っている（四国は1,532本すべてに name があり、
  `四国中央中幹線` `松山幹線` が事業者公表名と完全一致する）。
  変電所名の突合より確実で、しかも **実線形が得られる**。
  第三者の可視化が端点直線で描いている所を、AGJは実際の線形で描ける。

  第2経路として端点（変電所）座標を結ぶ直線を使う。
  `geometry_kind` に "routed"（実線形）/ "straight"（端点直線）を必ず入れて、
  どちらで描かれた線かを地図側でも区別できるようにする。

入力: data/external/system_disclosure/normalized/line_observations.csv
      data/{region}_lines.geojson（OSM実線形）
      docs/data/substations.geojson ほか（端点フォールバック）
出力: data/external/system_disclosure/viz/flow_lines.geojson

★出力先は **gitignore 下**。docs/ に置くと GitHub Pages で公開され、
  事業者公表CSV（社によっては転載禁止）の再配布になってしまうため。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_line_observations import read_flow, scope_of  # noqa: E402
from scripts.match_impedance_to_model import load_model, resolve  # noqa: E402

NORM = ROOT / "data" / "external" / "system_disclosure" / "normalized"
OUT = ROOT / "data" / "external" / "system_disclosure" / "viz"

import math

# 端点直線の上限。実在の送電線区間はどんなに長くてもこの程度に収まる。
# これを超える直線は、同名の別施設を掴んだ誤対応（画面を斜めに横切る線になる）。
MAX_SPAN_KM = 120.0
# 同名 way を1本の線路にまとめるとき、離れすぎたセグメントは別の同名線路。
# つなげると地図上で飛び地になり「ブツギレ」に見える。**繋げずに落とす**
# （実データに無い接続を描くのは捏造なので、隙間は隙間のまま残す）。
SEGMENT_LINK_KM = 3.0


def haversine_km(a_lon, a_lat, b_lon, b_lat) -> float:
    r = 6371.0088
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


CIRCUIT_RX = re.compile(r"[0-9０-９]+\s*[LＬ]\s*$")
# `玄海幹線２Ｌ北線` のように回線番号のあとに方向が付く枝がある。
# OSM 側は本線名（玄海幹線）で登録されているので、この尾を落として寄せる。
BRANCH_RX = re.compile(r"[0-9０-９]+\s*[LＬ]\s*[東西南北][線]?\s*$")
PAREN_RX = re.compile(r"[（(][^）)]*[）)]")


def norm_line(s: str) -> str:
    """線路名を照合キーにする。回線サフィックス(1L/2L)と括弧注記を落とす。"""
    n = unicodedata.normalize("NFKC", str(s))
    n = PAREN_RX.sub("", n)
    n = re.sub(r"[\s　・,，]", "", n)
    n = BRANCH_RX.sub("", n)
    n = CIRCUIT_RX.sub("", n)
    return n.strip()


SUFFIX_RX = re.compile(r"(変電所|開閉所|発電所|変換所|変|開)$")


def clean(v: object):
    """pandas の NaN を None に落とす。

    NaN を残すと json.dumps が JSON として不正な `NaN` を書き、
    ブラウザ側の JSON.parse が丸ごと失敗する（データが1件も出ない）。
    """
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    if isinstance(v, str) and v.strip().lower() in ("nan", ""):
        return None
    return v


def stem_of(name: object) -> str:
    """`阿波変電所` → `阿波` / `西島根(変)` → `西島根`。端点照合の語幹。"""
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return ""
    n = unicodedata.normalize("NFKC", str(name))
    n = PAREN_RX.sub("", n)
    n = re.sub(r"[\s　・,，]", "", n)
    return SUFFIX_RX.sub("", n).strip()


def load_osm_lines(region: str) -> dict[str, list[dict]]:
    """OSM送電線を線路名で索引する。同名の way は1本の線路の分割とみなす。"""
    path = ROOT / "data" / f"{region}_lines.geojson"
    index: dict[str, list[dict]] = defaultdict(list)
    if not path.exists():
        return index
    for f in json.loads(path.read_text(encoding="utf-8"))["features"]:
        p = f.get("properties") or {}
        raw = p.get("name") or ""
        if not raw:
            continue
        geom = f.get("geometry") or {}
        if geom.get("type") != "LineString":
            continue
        # `西通線;上天神線` のような併記は両方の候補にする
        for part in str(raw).split(";"):
            key = norm_line(part)
            if len(key) >= 3:
                index[key].append({"coords": geom["coordinates"], "props": p})
    return index


_MODEL_GRAPH = None


def model_graph():
    """built正典の枝から頂点グラフを作る(観測の端点直線をOSM実線形へ寄せる用)。

    オーナー指示(2026-08-16)「東北がかなり直線多い。幹線の接続をちゃんとOSMに
    寄せたい」「全国その判定やってほしい」。OSM名照合に失敗した観測でも、両端の
    変電所はモデル上で実線形の枝で結ばれていることが多い。Dijkstraで実経路を
    復元して geometry にする(kind=routed_graph)。実証コード(直線)は経路に使わない。
    """
    global _MODEL_GRAPH
    if _MODEL_GRAPH is not None:
        return _MODEL_GRAPH
    built = json.loads((ROOT / "docs/data/built/all.json").read_text(encoding="utf-8"))
    adj: dict = defaultdict(list)
    grid: dict = defaultdict(list)
    for e in built["edges"]:
        if e.get("disclosure") and not e.get("stub"):
            continue      # 実証コードは直線なので経路に使わない(スタブは物理)
        ka = (round(e["a"][0], 5), round(e["a"][1], 5))
        kb = (round(e["b"][0], 5), round(e["b"][1], 5))
        pts = e.get("path") or [e["a"], e["b"]]
        km = sum(haversine_km(pts[i][1], pts[i][0], pts[i + 1][1], pts[i + 1][0])
                 for i in range(len(pts) - 1))
        rec = {"km": max(km, 0.001), "kv": e.get("kv") or 0, "path": pts}
        adj[ka].append((kb, rec))
        adj[kb].append((ka, rec))
    for v in adj:
        grid[(int(v[0] / 0.02), int(v[1] / 0.02))].append(v)
    _MODEL_GRAPH = (adj, grid)
    return _MODEL_GRAPH


def graph_route(na: dict, nb: dict, kv) -> list | None:
    """変電所na→nbのモデル枝経路。成功時は[lon,lat]列を返す(from→to向き)。"""
    adj, grid = model_graph()

    def near(lat, lon, r_km=1.5):
        cx, cy = int(lat / 0.02), int(lon / 0.02)
        out = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for v in grid.get((cx + dx, cy + dy), []):
                    d = haversine_km(lon, lat, v[1], v[0])
                    if d <= r_km:
                        out.append((d, v))
        return sorted(out)[:8]

    starts = near(na["lat"], na["lon"])
    goals = near(nb["lat"], nb["lon"])
    if not starts or not goals:
        return None
    chord = haversine_km(na["lon"], na["lat"], nb["lon"], nb["lat"])
    limit = max(chord * 2.5, chord + 10)
    gd = {v: d for d, v in sorted(goals, reverse=True)}

    def w(rec) -> float:
        # 電圧不適合ペナルティ: 275kV観測を66kV網へ迂回させない(逆は緩め)
        if kv and rec["kv"]:
            if rec["kv"] < kv * 0.7:
                return rec["km"] * 4
            if rec["kv"] > kv * 2.2:
                return rec["km"] * 2
        return rec["km"]

    import heapq
    dist: dict = {}
    prev: dict = {}
    seq = 0
    pq = []
    for d, v in starts:
        pq.append((d, seq, v, None, None))
        seq += 1
    heapq.heapify(pq)
    hit = None
    while pq:
        dcur, _, v, pv, rec = heapq.heappop(pq)
        if v in dist:
            continue
        dist[v] = dcur
        prev[v] = (pv, rec)
        if dcur > limit:
            break
        if v in gd:
            hit = v
            break
        for u, r in adj[v]:
            if u not in dist:
                seq += 1
                heapq.heappush(pq, (dcur + w(r), seq, u, v, r))
    if hit is None:
        return None
    # 経路復元: goal→startへ辿り、各枝pathを向きを揃えて連結
    chain = []
    v = hit
    while prev.get(v) and prev[v][0] is not None:
        pv, rec = prev[v]
        pts = list(rec["path"])
        # 現在頂点vに近い端が末尾に来る向きへ
        if haversine_km(pts[0][1], pts[0][0], v[1], v[0]) < \
           haversine_km(pts[-1][1], pts[-1][0], v[1], v[0]):
            pts.reverse()
        chain.append(pts)
        v = pv
    chain.reverse()
    coords = [[na["lon"], na["lat"]]]
    for pts in chain:
        coords.extend([[p[1], p[0]] for p in pts])
    coords.append([nb["lon"], nb["lat"]])
    return coords


def keep_main_cluster(parts: list[list]) -> list[list]:
    """端点が近いセグメントだけを1本の線路とみなし、最大の塊を返す。

    同名 way には別地域の同名線路が混ざる（実測で最大135kmの飛びがあった）。
    近接グラフの連結成分に分け、**最も総延長が長い成分だけ**を採る。
    落とした分は繋がない — 無い接続を描くより、描かない方がよい。
    """
    n = len(parts)
    if n <= 1:
        return parts
    ends = [(p[0], p[-1]) for p in parts]

    def near(i, j) -> bool:
        return min(haversine_km(a[0], a[1], b[0], b[1])
                   for a in ends[i] for b in ends[j]) <= SEGMENT_LINK_KM

    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n):
        for j in range(i + 1, n):
            if near(i, j):
                parent[find(i)] = find(j)

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)

    def length(idx_list) -> float:
        t = 0.0
        for i in idx_list:
            c = parts[i]
            for k in range(len(c) - 1):
                t += haversine_km(c[k][0], c[k][1], c[k + 1][0], c[k + 1][1])
        return t

    best = max(groups.values(), key=length)
    return [parts[i] for i in best]


def line_id(utility: str, scope: str, no: object) -> str:
    return f"{utility}:{scope}:{no}"


def build_series(df: pd.DataFrame, wanted: set[str], n_steps: int) -> dict:
    """必要な線路だけ時系列を切り出す。

    GeoJSON に埋め込むと1本あたり8,760値で数MBになるので**別ファイルに分ける**。
    地図は幾何を先に描き、系列は後から読めばよい。
    """
    series: dict[str, list] = {}
    t0 = None
    for path_str, sub in df.groupby("source_flow"):
        path = ROOT / path_str
        if not path.exists():
            continue
        try:
            meta, ts = read_flow(path)
        except Exception:  # noqa: BLE001
            continue
        utility = path.parts[len(ROOT.parts) + 3]
        scope = scope_of(path.name)
        if len(ts):
            # t0=時間軸の起点ラベル。社ごとfallbackで年度が混在しうるので、
            # 最も古い年度の4/1を代表にする（各系列は先頭位置=年度第1週で揃う）
            cand = str(ts.iloc[0, 0])
            try:
                if t0 is None or pd.to_datetime(cand) < pd.to_datetime(t0):
                    t0 = cand
            except Exception:  # noqa: BLE001
                t0 = t0 or cand
        col_of = {str(m.equipment_no): int(m.col) for _, m in meta.iterrows()}
        for _, r in sub.iterrows():
            lid = line_id(utility, scope, r.equipment_no)
            if lid not in wanted or lid in series:
                continue
            c = col_of.get(str(r.equipment_no))
            if c is None:
                continue
            v = pd.to_numeric(
                ts.iloc[:n_steps, c].astype(str).str.replace(",", ""), errors="coerce"
            )
            series[lid] = [None if pd.isna(x) else round(float(x), 1) for x in v]
    return {"t0": t0, "step_min": 60, "n_steps": n_steps, "series": series}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--min-obs", type=int, default=1)
    ap.add_argument("--steps", type=int, default=168,
                    help="時系列に出す断面数（既定168=1週間の1時間値）")
    ap.add_argument("--fy", default="2024",
                    help="対象年度。社ごとに公表年度が違うため揃えないと"
                         "別の年の値を同じ時刻軸に重ねることになる")
    args = ap.parse_args()

    df = pd.read_csv(NORM / "line_observations.csv")
    df = df[df.n_obs.fillna(0) >= args.min_obs]

    # 年度を揃える。東京は2024年度・四国は2025年度…と公表年度がまちまちで、
    # 揃えずに1本のスライダーで動かすと「異なる年の断面」を同時刻として
    # 並べてしまう。年度で絞り、落ちた社は明示する。
    if args.fy and "year" in df.columns:
        # 社ごとに公表年度が違う（中国/沖縄は2025のみ等）。指定年度が無い社は
        # その社の最新年度へフォールバックし、featureのfy注記で開示する。
        # 時系列は各ファイルの先頭からの位置合わせ＝「年度第1週」同士の比較になる。
        keep = []
        for utility, sub in df.groupby("utility"):
            years = sorted(sub.year.astype(str).unique())
            use = str(args.fy) if str(args.fy) in years else years[-1]
            if use != str(args.fy):
                print(f"年度{args.fy}が無い {utility} は {use} を使用（fy注記つき）")
            keep.append(sub[sub.year.astype(str) == use])
        df = pd.concat(keep, ignore_index=True)

    # 東京は相手端を公表しない（to が空）が、**同じ線路名が両端の変電所に
    # 別々の列として現れる**（`釜無白根(変) - 天竜南線` と `新富士(変) - 天竜南線`）。
    # 同名を持つ変電所がちょうど2つなら、その2点を結べば線になる。
    # 3つ以上（分岐や同名別線）は一意に決まらないので採らない。
    endpoint_pairs: dict[tuple[str, str], list[str]] = defaultdict(list)
    for _, r in df.iterrows():
        # clean() を通さないと NaN が str() で "nan" になり、
        # 「相手端あり」と誤判定されてペア復元の分岐に入らない
        frm = str(clean(r.get("from_node")) or "").strip()
        to = str(clean(r.get("to_node")) or "").strip()
        if frm and not to:
            key = (r["utility"], norm_line(r["name"]))
            if frm not in endpoint_pairs[key]:
                endpoint_pairs[key].append(frm)

    features = []
    stat = defaultdict(int)
    for utility, sub in df.groupby("utility"):
        osm = load_osm_lines(utility)
        node_index, _ = load_model(utility)
        for _, r in sub.iterrows():
            key = norm_line(r["name"])
            geometry = None
            kind = None

            hits = osm.get(key)
            if not hits and "/" in key:
                # 沖縄の複合列（例: 阿波根線/真壁線＝直列区間の合算計測）。
                # 直列区間には同一潮流が流れるので、各構成線のOSM線形を合併して置く。
                part_hits = []
                for part in key.split("/"):
                    part_hits.extend(osm.get(norm_line(part)) or [])
                if part_hits:
                    hits = part_hits
                    stat["composite_parts"] += 1
            if not hits:
                # 第2経路: 端点ペア。OSM側に `阿波変電所~讃岐変電所線` のような
                # 端点由来の名前が入っているため、両端の語幹を含む線路を探す。
                # 公表側が `阿波幹線` と呼ぶ線が OSM では端点名になっている事例が多い。
                a = stem_of(r.get("from_node"))
                b = stem_of(r.get("to_node"))
                if len(a) >= 2 and len(b) >= 2:
                    cand = [
                        h for name, hl in osm.items()
                        if a in name and b in name
                        for h in hl
                    ]
                    if cand:
                        hits = cand
                        stat["by_endpoints"] += 1

            oriented = False
            if hits:
                kind = "routed"
                stat["routed"] += 1
                if len(hits) == 1:
                    coords = list(hits[0]["coords"])
                    # 線形の描画方向を「潮流の正方向(from→to)」に揃える。
                    # こうしておくと地図側の流れるアニメーションが物理的に正しい向きになる。
                    _, na = resolve(str(r.get("from_node") or ""), node_index)
                    if na and len(coords) >= 2:
                        d_head = (coords[0][0]-na["lon"])**2 + (coords[0][1]-na["lat"])**2
                        d_tail = (coords[-1][0]-na["lon"])**2 + (coords[-1][1]-na["lat"])**2
                        if d_tail < d_head:      # 終点の方が from に近い = 逆向き
                            coords.reverse()
                        oriented = True
                        stat["oriented"] += 1
                    geometry = {"type": "LineString", "coordinates": coords}
                else:
                    # 複数way に分割された線路。セグメントの並び順までは決められないので
                    # 向きは保証しない（oriented=False のまま）。
                    parts = keep_main_cluster([h["coords"] for h in hits])
                    if len(parts) < len(hits):
                        stat["dropped_far_segments"] += len(hits) - len(parts)
                    geometry = ({"type": "LineString", "coordinates": parts[0]}
                                if len(parts) == 1
                                else {"type": "MultiLineString", "coordinates": parts})
            else:
                frm = str(clean(r.get("from_node")) or "")
                to = str(clean(r.get("to_node")) or "")
                # 沖縄の複合端点（阿波根変電所/真壁変電所）は先頭区間の相手で近似
                if "/" in frm:
                    frm = frm.split("/")[0]
                if "/" in to:
                    to = to.split("/")[0]
                if frm and not to:
                    # 相手端が非公開の社（東京）。同名線路が現れる変電所が
                    # ちょうど2つのときだけ、その相手を to とみなす。
                    peers = endpoint_pairs.get((utility, norm_line(r["name"])), [])
                    if len(peers) == 2:
                        to = peers[1] if peers[0] == frm else peers[0]
                        stat["paired_endpoints"] += 1
                if frm and to:
                    _, na = resolve(frm, node_index)
                    _, nb = resolve(to, node_index)
                    if na and nb:
                        span = haversine_km(na["lon"], na["lat"], nb["lon"], nb["lat"])
                        # まずモデル枝グラフの実経路を試す(幹線をOSM線形へ寄せる)。
                        # 実経路が見つかれば span>120km でも実在の長距離線として採用
                        routed = graph_route(
                            na, nb, float(r.voltage_kv) if pd.notna(r.voltage_kv) else None)
                        if routed:
                            kind = "routed_graph"
                            stat["routed_graph"] += 1
                            oriented = True
                            geometry = {"type": "LineString", "coordinates": routed}
                        elif span > MAX_SPAN_KM:
                            # 同名の別施設を掴んだ誤対応。地図を斜めに横切る線になるので捨てる
                            stat["rejected_span"] += 1
                        else:
                            kind = "straight"
                            stat["straight"] += 1
                            oriented = True   # from→to の順で作るので向きは定義どおり
                            geometry = {"type": "LineString",
                                        "coordinates": [[na["lon"], na["lat"]],
                                                        [nb["lon"], nb["lat"]]]}
            if geometry is None:
                stat["unplaced"] += 1
                continue

            props = {
                "line_id": line_id(utility, r.get("scope", "?"), r.equipment_no),
                "utility": utility, "line": r["name"],
                "kv": None if pd.isna(r.voltage_kv) else float(r.voltage_kv),
                "from": clean(r.get("from_node")), "to": clean(r.get("to_node")),
                "geometry_kind": kind, "layer": "observed",
                "oriented": oriented,   # 線形の向き＝潮流正方向 に揃えたか
                "n_obs": int(r.n_obs),
                "osm_segments": len(hits) if hits else 0,
                "fy": str(r.get("year") or ""),   # 社ごとfallbackで年度が違いうるため開示
            }
            for k in ("flow_mean_mw", "flow_p95_abs_mw", "flow_max_abs_mw", "reverse_share",
                      "operational_mw", "facility_mw", "constraint", "circuits",
                      "load_factor_p95", "R_pct", "X_pct", "B_half_pct"):
                props[k] = clean(r.get(k))
            features.append({"type": "Feature", "properties": props, "geometry": geometry})

    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / "flow_lines.geojson"
    # allow_nan=False: NaN が混じったら書き出し時点で落とす。
    # Python の json は既定で NaN を書けてしまうが、それは JSON として不正で
    # ブラウザの JSON.parse が丸ごと失敗する（データが1件も出ないのに無言で通る）。
    dest.write_text(json.dumps({
        "type": "FeatureCollection", "features": features,
        "metadata": {
            "layer": "observed",
            "source": "一般送配電事業者 系統情報の公表（様式5 / 空容量 / 潮流実績）+ OSM実線形",
            "note": "生値の再配布不可。私的検証用。負荷率は公表の運用容量ベース",
        },
    }, ensure_ascii=False, allow_nan=False), encoding="utf-8")

    # ビューア本体はコード（commit対象）なので scripts/viz/ が正本。
    # データは gitignore 下なので、実行のたびにデータの隣へ写して同一オリジンで開けるようにする。
    src_html = ROOT / "scripts" / "viz" / "observed_flow.html"
    if src_html.exists():
        (OUT / "index.html").write_text(src_html.read_text(encoding="utf-8"), encoding="utf-8")

    # 地図に載った線だけ時系列を切り出す（載らない線の系列は要らない）
    wanted = {f["properties"]["line_id"] for f in features}
    ser = build_series(df, wanted, args.steps)
    sdest = OUT / "flow_series.json"
    sdest.write_text(json.dumps(ser, ensure_ascii=False, allow_nan=False), encoding="utf-8")

    n_cap = sum(1 for f in features if f["properties"].get("operational_mw"))
    n_imp = sum(1 for f in features if f["properties"].get("X_pct"))
    print(f"時系列 {len(ser['series'])} 本 × {args.steps} 断面 "
          f"(t0={ser['t0']}) → {sdest.relative_to(ROOT)} {sdest.stat().st_size:,}B")
    print(f"features {len(features)}")
    print(f"  実線形 routed   {stat['routed']}")
    print(f"  端点直線 straight {stat['straight']}")
    print(f"  枝グラフ経路復元 routed_graph {stat['routed_graph']}  (端点直線をOSM実線形へ)")
    print(f"  複合列の分割照合  {stat['composite_parts']}  (沖縄 阿波根線/真壁線 等)")
    print(f"  距離超過で棄却    {stat['rejected_span']}  (>{MAX_SPAN_KM:.0f}km)")
    print(f"  飛び地セグメント除去 {stat['dropped_far_segments']}  (>{SEGMENT_LINK_KM:.0f}km離れ)")
    print(f"  配置できず       {stat['unplaced']}")
    print(f"  運用容量つき {n_cap} / インピーダンスつき {n_imp}")
    print(f"→ {dest.relative_to(ROOT)}  {dest.stat().st_size:,}B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
