#!/usr/bin/env python3
"""OCCTO の当日の潮流実績を、io のページ「OCCTO 潮流実績」(docs/occto_flow.html)用の JSON にする.

2 つのファイルを書く:
  docs/data/flow_map/occto_lines.json   線路の一覧・線の形・日本の輪郭。照合
                                        (scripts/build_occto_line_crosswalk.py)を作り直したときだけ、手で作り直す
  docs/data/flow_map/occto_today.json   前日 0 時から今までの地内基幹送電線の潮流実績(30 分値)・運用容量の実績・
                                        連系線の潮流実績。毎時の処理(scripts/realtime_cycle.sh)が書き、
                                        realtime_publish.sh が io へ出す

取り方は scripts/fetch_occtonet_bulk.py と同じ(occtonet3 の「情報ダウンロード」、5 秒間隔)。1 回に 10 リクエストほど。
OCCTO は 2026-10-23 に「過度なアクセスはアクセス制限」と告知しているので、1 時間より詰めて回さない。
地内基幹の 30 分値は、02:14 の時点で 02:00 の値まで出ていた(2026-11-07 に確認)。

取得に失敗したとき(地内基幹の潮流が取れないとき)は、前の occto_today.json を残して終了コード 1 を返す。
運用容量と連系線は取れなかった回だけ空にする(潮流は出す)。

使い方:
    python3 scripts/export_occto_today.py today
    python3 scripts/export_occto_today.py today --flow-csv f.csv --cap-csv c.csv --ic-csv i.csv   # 手元の CSV から(試験用)
    python3 scripts/export_occto_today.py lines --crosswalk data/external/occto/occto_line_crosswalk.json
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import logging
import math
import os
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FM = ROOT / "docs" / "data" / "flow_map"
LINES_OUT = FM / "occto_lines.json"
TODAY_OUT = FM / "occto_today.json"
PREFS = ROOT / "data" / "reference" / "japan_prefectures_simplified.geojson"
JST = dt.timezone(dt.timedelta(hours=9))

AREA = {"北海道": "hokkaido", "東北": "tohoku", "東京": "tokyo", "中部": "chubu", "北陸": "hokuriku",
        "関西": "kansai", "中国": "chugoku", "四国": "shikoku", "九州": "kyushu", "沖縄": "okinawa"}
AREA_JA = {v: k for k, v in AREA.items()}
SOURCE = ("電力広域的運営推進機関「系統情報サービス」の地内基幹送電線潮流実績・"
          "地内基幹送電線運用容量実績・連系線潮流実績")

log = logging.getLogger("occto_today")


def text(s) -> str:
    """全角空白・連続する空白を半角 1 つにし、前後を落とす(統合 DB の occto_* 表と同じそろえ方)。"""
    return re.sub(r"\s+", " ", str(s or "")).strip()


def num(s):
    s = text(s).replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def line_id(area: str, line: str, direction: str) -> str:
    return f"{area}|{line}|{direction}"


# 向きの端の名前をそろえる(「北新得SS」「南早来変電所」「日野（変）」「三重」→ 語幹)。運用容量の表は
# 潮流の表と向きの書き方が違う(「西双葉SWS → 西野SS」と「西双葉開閉所　→　西野変電所」)
_ABBR = ("SWS", "S/S", "SS", "CS", "PS")
_KINDS = ("変電所", "開閉所", "変換所", "発電所")


def stem(s: str) -> str:
    s = re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))
    m = re.fullmatch(r"(.+?)\((?:変換|開閉|変|開|発)\)", s)
    if m:
        return m.group(1)
    up = s.upper()
    for a in _ABBR:
        if up.endswith(a) and len(s) > len(a):
            return s[:-len(a)]
    for k in _KINDS:
        if s.endswith(k) and len(s) > len(k):
            return s[:-len(k)]
    return s


def ends(direction: str) -> tuple[str, str] | None:
    parts = re.split(r"→|⇒|->", unicodedata.normalize("NFKC", direction))
    return (stem(parts[0]), stem(parts[1])) if len(parts) == 2 else None


def _rows(body: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(body.decode("cp932", "replace"))))


def _date(s: str) -> dt.date | None:
    try:
        return dt.datetime.strptime(text(s), "%Y/%m/%d").date()
    except ValueError:
        return None


def parse_flow(body: bytes, days: list[dt.date]) -> tuple[list[str], dict]:
    """地内基幹の 30 分値 → (時刻の列, {線路: {kv, v}})。時刻は値のある最後のコマまでで切る。"""
    rows = _rows(body)
    head = [text(h) for h in rows[0]]
    i_date, i_area, i_kv, i_line, i_dir = (head.index(c) for c in
                                           ("対象年月日", "対象エリア", "電圧", "送電線名", "潮流方向(正方向)"))
    slots = [(j, h) for j, h in enumerate(head) if re.fullmatch(r"\d{2}:\d{2}", h)]
    times = [f"{d:%Y-%m-%d} {h}" for d in days for _, h in slots]
    pos = {t: k for k, t in enumerate(times)}
    lines: dict[str, dict] = {}
    for r in rows[1:]:
        if len(r) < len(head):
            continue
        d = _date(r[i_date])
        if d not in days:
            continue
        area = AREA.get(text(r[i_area]), text(r[i_area]))
        ent = lines.setdefault(line_id(area, text(r[i_line]), text(r[i_dir])),
                               {"kv": int(num(r[i_kv]) or 0), "v": [None] * len(times)})
        for j, h in slots:
            v = num(r[j])
            if v is not None:
                ent["v"][pos[f"{d:%Y-%m-%d} {h}"]] = round(v)
    last = max((k for e in lines.values() for k, v in enumerate(e["v"]) if v is not None), default=-1)
    for e in lines.values():
        e["v"] = e["v"][:last + 1]
    return times[:last + 1], lines


# 運用容量の表の線路名は、潮流の表と書き方が少し違う(2026-11-07 に確かめた):
#   注記が付く「佐賀幹線（フェンス２）」「新坂戸線（他社）」「中国中幹線（フェンス管理箇所）」/ 区間だけ「恵庭南札線」
#   (潮流は「十勝幹線(恵庭南札線)」)/ 同じ名前を向きで分ける「名寄幹線」2 行(潮流は「名寄幹線（旭川嵐山～西名寄）」)/
#   「～」の字が違う / 中国の基幹線の 99999(決定要因「電圧」、フェンスで管理する印で線路の容量ではない)
_NOTE = re.compile(r"\((?:[^()]*(?:フェンス|他社|含む)[^()]*)\)$")
_PAREN = re.compile(r"^(.+?)\(([^()]+)\)$")
NO_LIMIT = 99999


def nname(s: str) -> str:
    s = re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(s or "")))
    return re.sub(r"[~〜～?\ufffd]", "~", s)


def parse_capacity(body: bytes, lines: dict) -> dict:
    """運用容量の実績 → {日付: {線路: [正方向, 逆方向, 最大, 正の決定要因, 逆の決定要因, 最大の決定要因]}}。

    運用容量の表は線路ごとに 1 行(片方の向き)のことが多く、潮流の正方向と逆に書かれた線もある
    (北海道の狩勝幹線は「南早来 → 北新得」)。ページは潮流の向きに合う値があればそれを、無ければ最大を使う。
    線路名の突き合わせ: (1) 同じ名前(注記を落としても可) (2) 括弧の中の区間名 (3) 括弧の前の名前で、向きの合う行だけ
    """
    rows = _rows(body)
    head = [text(h) for h in rows[0]]
    i_date = next(k for k, h in enumerate(head) if "対象年月日" in h)
    i_area, i_line, i_dir, i_cap, i_why = (head.index(c) for c in
                                           ("対象エリア", "送電線名", "潮流方向", "運用容量", "決定要因"))
    by: dict[tuple[str, str, str], list] = {}
    for r in rows[1:]:
        if len(r) <= max(i_cap, i_why):
            continue
        d = _date(r[i_date])
        cap = num(r[i_cap])
        n = nname(r[i_line])
        if d is None or cap is None or not n or abs(cap) >= NO_LIMIT:
            continue
        area = AREA.get(text(r[i_area]), text(r[i_area]))
        row = (ends(text(r[i_dir])), abs(cap), text(r[i_why]) or None)
        for k in {n, _NOTE.sub("", n)}:
            by.setdefault((f"{d:%Y-%m-%d}", area, k), []).append(row)
    days = sorted({d for d, _, _ in by})
    out: dict[str, dict] = {}
    for lid in lines:
        area, line, direction = lid.split("|", 2)
        e, n = ends(direction), nname(line)
        cands = [(n, False)]
        m = _PAREN.match(n)
        if m:
            cands += [(m.group(2), False), (m.group(1), True)]
        for day in days:
            for key, need_dir in cands:
                caps = by.get((day, area, key))
                if not caps:
                    continue
                fwd = next(((c, w) for en, c, w in caps if e and en == e), (None, None))
                rev = next(((c, w) for en, c, w in caps if e and en == (e[1], e[0])), (None, None))
                pool = [x for x in (fwd, rev) if x[0] is not None] if need_dir else [(c, w) for _, c, w in caps]
                if not pool:
                    continue
                mx = max(pool, key=lambda x: x[0])
                out.setdefault(day, {})[lid] = [fwd[0], rev[0], mx[0], fwd[1], rev[1], mx[1]]
                break
    return out


def parse_ic(body: bytes, times: list[str]) -> dict:
    """連系線の 5 分値 → {連系線: [[潮流, 運用容量(順), 運用容量(逆)] or None]}(地内基幹と同じ時刻の値)。"""
    rows = _rows(body)
    head = [text(h) for h in rows[0]]
    i_nm, i_date, i_hm, i_cf, i_cr, i_fl = (head.index(c) for c in
                                            ("連系線", "対象日付", "対象時刻", "運用容量(順方向)", "運用容量(逆方向)", "潮流実績"))
    pos = {t: k for k, t in enumerate(times)}
    out: dict[str, list] = {}
    for r in rows[1:]:
        if len(r) <= i_fl:
            continue
        d, hm = _date(r[i_date]), text(r[i_hm])
        if d is None:
            continue
        if hm == "24:00":
            d, hm = d + dt.timedelta(days=1), "00:00"
        k = pos.get(f"{d:%Y-%m-%d} {hm}")
        fl = num(r[i_fl])
        if k is None or fl is None:
            continue
        out.setdefault(text(r[i_nm]), [None] * len(times))[k] = [round(fl), round(num(r[i_cf]) or 0),
                                                                 round(num(r[i_cr]) or 0)]
    return out


def build_today(flow: bytes, cap: bytes | None, ic: bytes | None, days: list[dt.date], now: dt.datetime) -> dict:
    times, lines = parse_flow(flow, days)
    keep = {f"{d:%Y-%m-%d}" for d in days}
    caps = {d: v for d, v in (parse_capacity(cap, lines) if cap else {}).items() if d in keep}
    return {
        "made": now.isoformat(timespec="minutes"),
        "source": SOURCE,
        "days": [f"{d:%Y-%m-%d}" for d in days],
        "times": times,
        "lines": lines,
        "cap": caps,
        "ic": parse_ic(ic, times) if ic else {},
    }


def write_json(path: Path, data: dict):
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def _download_range(cli, spec, d0: dt.date, d1: dt.date) -> bytes | None:
    """d0〜d1 を月ごとに頼んでつなぐ(月をまたぐ範囲を画面が受けるかは確かめていない)。"""
    bodies = []
    d = d0
    while d <= d1:
        last = min(d1, (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1))
        b = cli.download(spec, (f"{d:%Y/%m/%d}", f"{last:%Y/%m/%d}"))
        if b:
            bodies.append(b)
        d = last + dt.timedelta(days=1)
    if not bodies:
        return None
    first, *rest = bodies
    if not first.endswith(b"\n"):
        first += b"\r\n"
    return first + b"".join(b.split(b"\n", 1)[1] if b"\n" in b else b"" for b in rest)


def cmd_today(a) -> int:
    now = dt.datetime.now(JST)
    days = [now.date() - dt.timedelta(days=1), now.date()]
    if a.flow_csv:
        flow = a.flow_csv.read_bytes()
        cap = a.cap_csv.read_bytes() if a.cap_csv else None
        ic = a.ic_csv.read_bytes() if a.ic_csv else None
        if a.day:
            d = dt.date.fromisoformat(a.day)
            days = [d - dt.timedelta(days=1), d]
    else:
        sys.path.insert(0, str(ROOT / "scripts"))
        import fetch_occtonet_bulk as ob   # noqa: E402  (requests が要るので、取得するときだけ読む)
        cli = ob.Client(a.sleep)
        try:
            flow = _download_range(cli, ob.SPECS["chinai_flow"], days[0], days[1])
        except Exception as e:  # noqa: BLE001
            log.error("地内基幹の潮流実績が取れなかった: %s", e)
            return 1
        if not flow:
            log.error("地内基幹の潮流実績が返らなかった")
            return 1
        cap = ic = None
        for key in ("chinai_capacity_result", "interconnector_flow"):
            # 連系線の 5 分値は「前日の 24:00」が当日の 0:00 にあたる。範囲の最初のコマ(前日 0:00)を埋めるため 1 日前から頼む
            d0 = days[0] - dt.timedelta(days=1) if key == "interconnector_flow" else days[0]
            try:
                b = _download_range(cli, ob.SPECS[key], d0, days[1])
            except Exception as e:  # noqa: BLE001
                log.warning("%s が取れなかった(この回は空にする): %s", key, e)
                b = None
            if key == "chinai_capacity_result":
                cap = b
            else:
                ic = b
    data = build_today(flow, cap, ic, days, now)
    if not data["times"]:
        log.error("値のある時刻が無い(前のファイルを残す)")
        return 1
    write_json(a.out, data)
    n_cap = sum(len(v) for v in data["cap"].values())
    log.info("%s: %s 〜 %s・線路 %d・運用容量 %d・連系線 %d・%d KB", a.out.relative_to(ROOT) if a.out.is_relative_to(ROOT) else a.out,
             data["times"][0], data["times"][-1], len(data["lines"]), n_cap, len(data["ic"]), a.out.stat().st_size // 1024)
    return 0


# ---- 線の形と輪郭(照合を作り直したときだけ) ----

def simplify(pts: list, tol: float) -> list:
    """Douglas–Peucker(shapely を使わない。毎時の処理の環境に無くても動くように)。"""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = pts[a], pts[b]
        dx, dy = bx - ax, by - ay
        l2 = dx * dx + dy * dy
        best, bi = -1.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
            ex, ey = ax + t * dx - px, ay + t * dy - py
            d = ex * ex + ey * ey
            if d > best:
                best, bi = d, i
        if bi > 0 and best > tol * tol:
            keep[bi] = True
            stack += [(a, bi), (bi, b)]
    return [p for p, k in zip(pts, keep) if k]


def _ring_area(r: list) -> float:
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(r, r[1:] + r[:1]))) / 2


def outline(path: Path = PREFS) -> list:
    out = []
    for ft in json.loads(path.read_text(encoding="utf-8"))["features"]:
        g = ft["geometry"]
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        for poly in polys:
            ring = simplify([tuple(p[:2]) for p in poly[0]], 0.01)
            if len(ring) >= 4 and _ring_area(ring) >= 0.0005:
                out.append([[round(x, 2), round(y, 2)] for x, y in ring])
    return out


def _km(p, q) -> float:
    dx = (p[0] - q[0]) * 111.32 * math.cos(math.radians((p[1] + q[1]) / 2))
    return math.hypot(dx, (p[1] - q[1]) * 110.57)


GAP_KM = 0.3   # これより離れた切れ目は点線でつなぐ(変電所の構内の大きさより小さい)


def chain(parts: list, a: list | None, b: list | None) -> tuple[list, list]:
    """モデルの線の切れ端を、変電所 a から b へ向けて並べ直す。(向きをそろえた切れ端, つなぎの点線)。

    切れ端は経路の区間ごとの線の形で、順番も向きもばらばら。いまの端にいちばん近い切れ端を、近い側から
    つないでいく。a・b が分からなければ、在る切れ端の端から始める。切れ目が GAP_KM より大きければ点線で結ぶ。
    b に着いたら、残りの切れ端(b の先へ延びる枝。南阿波幹線の阿南変換所の先の阿南発電所への 7 km)は描かない。
    """
    rest = [list(p) for p in parts if len(p) >= 2]
    solid, dash = [], []
    cur = a or (rest[0][0] if rest else None)
    far = a is not None and b is not None and _km(a, b) > GAP_KM
    while rest:
        if far and solid and _km(cur, b) <= GAP_KM:
            break
        d, i, rev = min((min((_km(cur, p[0]), j, False), (_km(cur, p[-1]), j, True)) for j, p in enumerate(rest)))
        p = rest.pop(i)
        if rev:
            p = p[::-1]
        if d > GAP_KM:
            dash.append([cur, p[0]])
        solid.append(p)
        cur = p[-1]
    if b and cur and _km(cur, b) > GAP_KM:
        dash.append([cur, b])
    return solid, dash


def branch_trunk(name: str) -> str | None:
    """端の名前が T 分岐(線の途中の点)なら、分岐する先の幹線の名前。「571T(西南多摩線)」→「西南多摩線」、
    「山口幹線」→「山口幹線」、「42T」→ None(幹線の名前が無い)。変電所の名前なら None。"""
    import unicodedata
    n = unicodedata.normalize("NFKC", str(name or "")).replace(" ", "")
    m = re.fullmatch(r"\d+T[(](.+?)[)]", n)
    if m:
        return m.group(1)
    if re.search(r"(線|幹線|連絡線|支線)$", n) and not re.search(r"(変電所|開閉所|発電所|変換所)", n):
        return n
    return None


def _nearest_on(paths: list, q: list) -> list | None:
    """線の形(折れ線の並び)の上で、点 q にいちばん近い点。"""
    best = None
    for path in paths:
        for (ax, ay), (bx, by) in zip(path, path[1:]):
            dx, dy = bx - ax, by - ay
            l2 = dx * dx + dy * dy
            t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((q[0] - ax) * dx + (q[1] - ay) * dy) / l2))
            pt = [ax + t * dx, ay + t * dy]
            d = _km(pt, q)
            if best is None or d < best[0]:
                best = (d, pt)
    return best[1] if best else None


def _nf(s: str) -> str:
    return unicodedata.normalize("NFKC", str(s or "")).replace(" ", "")


def t_key(area: str, line: str, name: str) -> tuple | None:
    """端の名前が T 分岐なら (エリア, 幹線, 番号)。変電所なら None。
    「571T(西南多摩線)」→ (…, 西南多摩線, 571)。番号だけの「42T」は、線路の名前「北神線（北摂～４２Ｔ）」の括弧の前を
    幹線とする → (…, 北神線, 42)。幹線の名前だけの「山口幹線」は番号 None。"""
    n = _nf(name)
    m = re.fullmatch(r"(\d+)T[(](.+?)[)]", n)
    if m:
        return (area, m.group(2), m.group(1))
    m = re.fullmatch(r"(\d+)T", n)
    if m:
        return (area, re.split(r"[(]", _nf(line))[0], m.group(1))
    t = branch_trunk(name)
    return (area, t, None) if t else None


def place_branches(lines: list) -> int:
    """T 分岐の端の位置を決める(位置は模式)。同じ T 分岐(幹線と番号が同じ)の端は 1 つの点にまとめる。

    1. 同じ T 分岐のどれかの端に位置が分かっていれば、それに合わせる。
    2. 分かっていなければ、分岐する先の幹線(同じエリアの、名前がその幹線で始まる線路)の描いた形の上で、
       分岐する側の線路のもう一方の端にいちばん近い点に置き、t で印を付ける(変電所の点は打たない)。
       幹線の形は実線(モデルの線)を使い、無ければ点線(模式)、それも無ければ幹線の両端の変電所を結ぶ直線。
    """
    by_area: dict[str, list] = {}
    for x in lines:
        by_area.setdefault(x["a"], []).append(x)
    groups: dict[tuple, list] = {}
    for x in lines:
        for i in (0, 1):
            k = t_key(x["a"], x["n"], x["d_ends"][i])
            if k:
                groups.setdefault(k, []).append((x, i))
    placed, changed = 0, []
    for (area, trunk, _no), members in groups.items():
        if all(x["s"][i] for x, i in members):
            continue
        known = [x["s"][i] for x, i in members if x["s"][i]]
        mark = not known
        if known:
            pt = known[0]
        else:
            fam = [y for y in by_area[area] if _nf(y["n"]).startswith(trunk)]

            def trunk_paths(skip=None):
                f = [y for y in fam if y is not skip]
                paths = [p for y in f for p in y["p"]] or [p for y in f for p in y["j"]]
                if not paths:
                    outer = []
                    for y in f:
                        for j in (0, 1):
                            q = y["s"][j]
                            if q and not t_key(area, y["n"], y["d_ends"][j]) and q not in outer:
                                outer.append(q)
                    paths = [outer[:2]] if len(outer) >= 2 else []
                return paths
            # 基準の点: 分岐する側(幹線の外)の線路のもう一方の端。分岐する側が無ければ(幹線が T 分岐で区間に
            # 分かれているだけ)、区間ごとに、その区間を除いた幹線の形の上で、その区間のもう一方の端にいちばん近い点
            tries = [(trunk_paths(), x["s"][1 - i]) for x, i in members
                     if not _nf(x["n"]).startswith(trunk) and x["s"][1 - i]]
            if not tries:
                tries = [(trunk_paths(x), x["s"][1 - i]) for x, i in members if x["s"][1 - i]]
            pt = next((q for q in (_nearest_on(p, r) for p, r in tries if p) if q), None)
            if pt:
                pt = [round(pt[0], 4), round(pt[1], 4)]
        if not pt:
            continue
        for x, i in members:
            if x["s"][i] is None:
                x["s"] = [pt if j == i else x["s"][j] for j in (0, 1)]
                if mark:
                    x.setdefault("t", [False, False])[i] = True
                placed += 1
                changed.append(x)
    for x in {id(x): x for x in changed}.values():
        fa, fb = x["s"]
        if x["p"]:
            x["p"], dash = chain(x["p"], fa, fb)
        else:
            dash = [[fa, fb]] if fa and fb else []
        x["j"] = [[[round(u, 3), round(v, 3)] for u, v in seg] for seg in dash]
    return placed


SHAPES = ROOT / "data" / "reference" / "occto_line_shapes.json"


def apply_shapes(lines: list, path: Path = SHAPES) -> tuple[int, int]:
    """モデルの線と照合できず点線になったところに、OSM か地理院の送電線の形を当てる(scripts/build_occto_line_shapes.py)。
    点線だけの線路は形を替え(g = 形の出どころ)、線路の中の切れ目の点線は形を足す(gf = 埋めた切れ目の数)。
    形の端が変電所の点から GAP_KM より離れていれば、そこだけ点線でつなぐ。照合を作り直して点線が変わったものには当てない。"""
    if not path.exists():
        return 0, 0
    items = json.loads(path.read_text(encoding="utf-8"))["items"]
    k3 = lambda q: (round(q[0], 3), round(q[1], 3))
    by = {(it["id"], it["kind"], k3(it["ends"][0]), k3(it["ends"][1])): it for it in items}
    n_line = n_gap = 0
    for x in lines:
        if not x["p"] and x["j"]:
            a, b = x["j"][0][0], x["j"][-1][-1]
            it = by.get((x["id"], "line", k3(a), k3(b)))
            if not it:
                continue
            c = it["coords"]
            x["p"] = [c]
            x["j"] = [[[round(u, 3), round(v, 3)] for u, v in seg] for seg in ([a, c[0]], [c[-1], b]) if _km(*seg) > GAP_KM]
            x["g"] = it["src"]
            n_line += 1
        elif x["p"] and x["j"]:
            keep, filled = [], 0
            for seg in x["j"]:
                it = by.get((x["id"], "gap", k3(seg[0]), k3(seg[1])))
                if not it:
                    keep.append(seg)
                    continue
                c = it["coords"]
                x["p"].append(c)
                keep += [[[round(u, 3), round(v, 3)] for u, v in s] for s in ([seg[0], c[0]], [c[-1], seg[1]]) if _km(*s) > GAP_KM]
                filled += 1
            if filled:
                x["j"], x["gf"] = keep, filled
                n_gap += filled
    return n_line, n_gap


IC_CONF = ROOT / "config" / "occto_interconnections.yaml"


CONV_KM = 0.5    # 連系線の端・経由点からこれより近い変換所は、その連系線の変換所とみなす


def interconnections(lines: list, path: Path = IC_CONF) -> tuple[list, list]:
    """連系線(エリアの間)と変換所。連系線の端は地内基幹の線路の端の点(エリアと名前の語幹で引く。T 分岐の点は使わない)か、
    台帳に書いた lon・lat。w = 端 → 経由する変換所 → 端 の点(線の形は区間ごとに apply_ic_shapes で当てる)。
    形を当てるまでは、各区間を結ぶ点線(模式)。"""
    import yaml
    conf = yaml.safe_load(path.read_text(encoding="utf-8"))
    pts: dict[tuple, list] = {}
    for x in lines:
        e = ends(x["d"])
        for i, nm in enumerate(e or ()):
            if x["s"][i] and not (x.get("t") or [False, False])[i]:
                pts.setdefault((x["a"], nm), x["s"][i])
    conv = [{"n": c["name"], "kind": c["kind"], "s": [c["lon"], c["lat"]], "ref": c["ref"], "note": c["note"], "links": []}
            for c in conf.get("converters") or []]
    cxy = {c["n"]: c["s"] for c in conv}
    out = []
    for r in conf["links"]:
        xy = [[e["lon"], e["lat"]] if "lon" in e else pts.get((e["area"], stem(e["name"]))) for e in r["ends"]]
        if None in xy:
            raise SystemExit(f"{path.name}: {r['name']} の端の位置が線路の一覧に無い: {r['ends']}")
        missing = [v for v in r.get("via") or [] if v not in cxy]
        if missing:
            raise SystemExit(f"{path.name}: {r['name']} の経由する変換所が converters に無い: {missing}")
        w = [xy[0]] + [cxy[v] for v in r.get("via") or []] + [xy[1]]
        osm = r.get("osm") or {}
        out.append({"k": r["ic"], "n": r["name"], "kind": r["kind"], "a": [e.get("area") for e in r["ends"]],
                    "s": xy, "w": w, "osm": {"kv": osm.get("kv") or [], "names": osm.get("names") or []},
                    "p": [], "j": [[a, b] for a, b in zip(w, w[1:])], "src": r["src"]})
        for c in conv:
            if any(_km(c["s"], q) < CONV_KM for q in w):
                c["links"].append(r["name"])
    return out, conv


def apply_ic_shapes(ics: list, path: Path = SHAPES) -> int:
    """連系線の区間(端 → 変換所 → 端)ごとに、OSM の送電線・ケーブルの形を当てる(scripts/build_occto_line_shapes.py)。
    形の無い区間は両端を結ぶ点線のまま。形の端が区間の端から GAP_KM より離れていれば、そこだけ点線でつなぐ。"""
    if not path.exists():
        return 0
    k3 = lambda q: (round(q[0], 3), round(q[1], 3))
    by = {(it["id"], k3(it["ends"][0]), k3(it["ends"][1])): it
          for it in json.loads(path.read_text(encoding="utf-8"))["items"] if it["kind"] == "ic"}
    n = 0
    for ic in ics:
        p, j = [], []
        for a, b in zip(ic["w"], ic["w"][1:]):
            it = by.get(("ic|" + ic["n"], k3(a), k3(b)))
            if not it:
                j.append([a, b])
                continue
            c = it["coords"]
            p.append(c)
            j += [s for s in ([a, c[0]], [c[-1], b]) if _km(*s) > GAP_KM]
            n += 1
        ic["p"], ic["j"] = p, j
        if p:
            ic["g"] = "osm"
    return n


BUILT = ROOT / "docs" / "data" / "built" / "all.json"
TOUCH_KM = 0.3    # 線の端がほかの線のこれより近くにあれば、つながっているとみなす
SNAP_KM = 1.0     # 変電所の点とモデルの節点を同じ所とみなす距離
MAIN_MIN = 20     # これより多くの線路を含む塊を本線とみなす(本土・沖縄)


def _seg_km(p, a, b) -> float:
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / l2))
    return _km(p, [ax + t * dx, ay + t * dy])


def _near_paths(p, paths, tol=TOUCH_KM) -> bool:
    return any(_seg_km(p, q[k], q[k + 1]) < tol for q in paths for k in range(len(q) - 1))


def bridges(lines: list, ics: list, built_path: Path = BUILT, tol: float = 0.002) -> list:
    """OCCTO の地内基幹の一覧だけではほかとつながらない所から、本線(大きな塊)の変電所までの、モデルの線の道筋。

    離れた所 = 線路が少ない塊(東上越幹線など、一覧につなぐ線路が無い)と、ほかの線に触れない変電所の点
    (線の描けない線路の端・連系線の端)。モデルの正典(built)の線を、電圧の低い線ほど遠いとみなして最短でたどる。
    地図ではつながりを見せるだけで、潮流の値は無い。"""
    import heapq
    items = [x["p"] + x["j"] for x in lines if x["p"] or x["j"]] + [(ic["p"] + ic["j"]) or [ic["s"]] for ic in ics]
    names = [x["n"] for x in lines if x["p"] or x["j"]] + [ic["n"] for ic in ics]
    ends = [[q[0] for q in it] + [q[-1] for q in it] for it in items]
    box = [(min(v[0] for q in it for v in q) - .01, max(v[0] for q in it for v in q) + .01,
            min(v[1] for q in it for v in q) - .01, max(v[1] for q in it for v in q) + .01) for it in items]
    par = list(range(len(items)))

    def find(i):
        while par[i] != i:
            par[i] = par[par[i]]
            i = par[i]
        return i
    for i, es in enumerate(ends):
        for j, it in enumerate(items):
            if i == j or find(i) == find(j):
                continue
            x0, x1, y0, y1 = box[j]
            if any(x0 <= e[0] <= x1 and y0 <= e[1] <= y1 and _near_paths(e, it) for e in es):
                par[find(i)] = find(j)
    comp: dict[int, list] = {}
    for i in range(len(items)):
        comp.setdefault(find(i), []).append(i)
    stations = [s for x in lines for i, s in enumerate(x["s"]) if s and not (x.get("t") or [False, False])[i]]
    main_pts, pieces = [], []
    for members in comp.values():
        pts = [e for i in members for e in ends[i]]
        own = [s for s in stations if any(_km(s, e) < TOUCH_KM for e in pts)]
        if len(members) >= MAIN_MIN:
            main_pts += own
        else:
            pieces.append(([names[i] for i in members], own + pts))
    drawn = [q for it in items for q in it]
    for x in lines:   # 線の描けない線路の端で、どの線にも触れない変電所
        if not (x["p"] or x["j"]):
            for s in x["s"]:
                if s and not _near_paths(s, drawn):
                    pieces.append(([x["n"]], [s]))
    for ic in ics:    # 連系線の端で、地内基幹の線に触れないもの(今別変換所)
        for s in ic["s"]:
            if not _near_paths(s, [q for x in lines for q in x["p"] + x["j"]]):
                pieces.append(([ic["n"]], [s]))
    if not pieces:
        return []
    # モデルの線の網(節点 = 座標。同じ変電所の電圧の違う母線は同じ座標)
    b = json.loads(built_path.read_text(encoding="utf-8"))
    key = lambda la, lo: (round(lo, 5), round(la, 5))
    adj: dict[tuple, list] = {}
    for k, e in enumerate(b["edges"]):
        u, v = key(*e["a"]), key(*e["b"])
        path = [[lo, la] for la, lo in (e.get("path") or [e["a"], e["b"]])]
        km = sum(_km(path[i], path[i + 1]) for i in range(len(path) - 1))
        kv = e.get("kv") or 0
        w = km * (1.0 if kv >= 187 else 1.3 if kv >= 154 else 2.5 if kv >= 66 else 5.0)
        adj.setdefault(u, []).append((v, w, k))
        adj.setdefault(v, []).append((u, w, k))
    nodes = list(adj)

    def near(p):
        return [n for n in nodes if abs(n[0] - p[0]) < .02 and abs(n[1] - p[1]) < .02 and _km(n, p) < SNAP_KM]
    targets = {n for p in main_pts for n in near(p)}
    out = []
    for for_names, pts in pieces:
        src = {n for p in pts for n in near(p)}
        if not src or src & targets:
            continue
        dist, prev, heap = {n: 0.0 for n in src}, {}, [(0.0, n) for n in src]
        heapq.heapify(heap)
        hit = None
        while heap:
            d, u = heapq.heappop(heap)
            if d > dist.get(u, 1e18):
                continue
            if u in targets:
                hit = u
                break
            if d > 150:
                break
            for v, w, k in adj.get(u, ()):
                if d + w < dist.get(v, 1e18):
                    dist[v], prev[v] = d + w, (u, k)
                    heapq.heappush(heap, (d + w, v))
        if not hit:
            log.warning("つなぐモデルの線が見つからない: %s", for_names)
            continue
        ks, u = [], hit
        while u in prev:
            u, k = prev[u]
            ks.append(k)
        es = [b["edges"][k] for k in reversed(ks)]
        paths = [[[round(x, 3), round(y, 3)] for x, y in simplify([(lo, la) for la, lo in (e.get("path") or [e["a"], e["b"]])], tol)]
                 for e in es if e["a"] != e["b"]]
        # 道筋の始まり(モデルの節点)が変電所の点から離れていれば、点から短い線でつなぐ
        p0 = min(pts, key=lambda q: _km(q, u))
        if _km(p0, u) > 0.05:
            paths.insert(0, [[round(p0[0], 4), round(p0[1], 4)], [round(u[0], 4), round(u[1], 4)]])
        # 見せる名前は OSM の線路名だけ(モデルの中の名前「namebind」「leadin」「tokyo_line_123」「会社名 220.0kV線」は除く)
        via = list(dict.fromkeys(n for e in es if e["a"] != e["b"] for n in [e.get("name") or ""]
                                 if n and not re.fullmatch(r"namebind|leadin|\w+_line_\d+|.*(ネットワーク|送配電|パワーグリッド|電力).*\d+(\.\d+)?kV線", n)))
        same = next((o for o in out if o["p"] == paths), None)
        if same:      # 同じ道筋(同じ変電所から出る線路の 2 本目)は 1 本にまとめる
            same["for"] += [n for n in for_names if n not in same["for"]]
            continue
        out.append({"for": for_names, "via": via, "kv": sorted({int(e.get("kv") or 0) for e in es if e["a"] != e["b"]} - {0}),
                    "km": round(sum(_km(q[i], q[i + 1]) for q in paths for i in range(len(q) - 1)), 1), "p": paths})
    return out


def cmd_lines(a) -> int:
    cw = json.loads(a.crosswalk.read_text(encoding="utf-8"))
    geom: dict[str, list] = {}
    for f in sorted(FM.glob("flows_now_*.geojson")):
        for ft in json.loads(f.read_text(encoding="utf-8"))["features"]:
            g, k = ft["geometry"], ft["properties"].get("k")
            parts = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"] if g["type"] == "MultiLineString" else []
            geom[k] = [[[round(x, 3), round(y, 3)] for x, y in simplify([tuple(p[:2]) for p in pt], a.tol)]
                       for pt in parts]
    lines = []
    for r in cw["lines"]:
        seen, paths = set(), []
        for seg in r.get("segs") or []:
            for k, _sign, _par in seg:
                if k in geom and k not in seen:
                    seen.add(k)
                    paths += geom[k]
        conf = r.get("conf")
        fa, fb = r.get("from_xy"), r.get("to_xy")
        if paths:
            paths, dash = chain(paths, fa, fb)
        else:
            # 形が無くても両端の変電所が分かれば、両端を結ぶ点線(位置は模式)
            dash = [[fa, fb]] if fa and fb else []
        rec = {"id": line_id(r["area"], r["line"], r["direction"]), "a": r["area"], "n": r["line"],
               "d": r["direction"], "kv": int(r["kv"]), "c": conf if conf in ("A", "B", "C") else None,
               "p": paths, "j": [[[round(x, 3), round(y, 3)] for x, y in seg] for seg in dash], "s": [fa, fb],
               "d_ends": [r.get("from"), r.get("to")]}
        lines.append(rec)
    n_branch = place_branches(lines)
    for x in lines:
        x.pop("d_ends")
    n_shape = (0, 0) if a.no_shapes else apply_shapes(lines)
    ics, conv = interconnections(lines)
    n_ic = 0 if a.no_shapes else apply_ic_shapes(ics)
    brs = bridges(lines, ics)
    data = {"made": dt.datetime.now(JST).isoformat(timespec="minutes"), "crosswalk_made": cw.get("made_at"),
            "built_sha256": cw.get("built_sha256"), "areas": AREA_JA, "outline": outline(), "lines": lines,
            "ics": ics, "converters": conv, "bridges": brs,
            "shapes": {"lines": n_shape[0], "gaps": n_shape[1], "ic_legs": n_ic,
                       "source": json.loads(SHAPES.read_text(encoding="utf-8"))["source"] if any(n_shape) or n_ic else None}}
    write_json(a.out, data)
    log.info("%s: 線路 %d(形あり %d・模式だけ %d・描けない %d)・つなぎの点線 %d・T 分岐の位置を決めた端 %d・OSM と地理院の形 線路 %d・切れ目 %d・連系線 %d(OSM の形の区間 %d・変換所 %d)・つなぎのモデルの線 %d・輪郭 %d 枚・%d KB",
             a.out, len(lines),
             sum(1 for x in lines if x["p"]), sum(1 for x in lines if not x["p"] and x["j"]),
             sum(1 for x in lines if not x["p"] and not x["j"]), sum(len(x["j"]) for x in lines if x["p"]),
             n_branch, *n_shape, len(ics), n_ic, len(conv), len(brs), len(data["outline"]), a.out.stat().st_size // 1024)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("today", help="前日 0 時から今までの値(毎時)")
    t.add_argument("--out", type=Path, default=TODAY_OUT)
    t.add_argument("--sleep", type=float, default=5.0, help="リクエストの間隔(秒)")
    t.add_argument("--flow-csv", type=Path, help="取得の代わりに読む地内基幹の潮流実績の CSV(cp932)")
    t.add_argument("--cap-csv", type=Path)
    t.add_argument("--ic-csv", type=Path)
    t.add_argument("--day", help="--flow-csv のときの「当日」(YYYY-MM-DD、既定は今日)")
    t.set_defaults(fn=cmd_today)
    li = sub.add_parser("lines", help="線路の一覧・線の形・輪郭(照合を作り直したとき)")
    li.add_argument("--crosswalk", type=Path, default=ROOT / "data" / "external" / "occto" / "occto_line_crosswalk.json")
    li.add_argument("--out", type=Path, default=LINES_OUT)
    li.add_argument("--tol", type=float, default=0.002, help="線の簡略化の許容(度)")
    li.add_argument("--no-shapes", action="store_true", help="OSM・地理院の形を当てない(build_occto_line_shapes.py の対象を出すとき)")
    li.set_defaults(fn=cmd_lines)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%F %T")
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
