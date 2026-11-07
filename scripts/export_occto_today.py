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
            try:
                b = _download_range(cli, ob.SPECS[key], days[0], days[1])
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
        lines.append({"id": line_id(r["area"], r["line"], r["direction"]), "a": r["area"], "n": r["line"],
                      "d": r["direction"], "kv": int(r["kv"]), "c": conf if conf in ("A", "B", "C") else None,
                      "p": paths})
    data = {"made": dt.datetime.now(JST).isoformat(timespec="minutes"), "crosswalk_made": cw.get("made_at"),
            "built_sha256": cw.get("built_sha256"), "areas": AREA_JA, "outline": outline(), "lines": lines}
    write_json(a.out, data)
    log.info("%s: 線路 %d(描ける %d)・輪郭 %d 枚・%d KB", a.out, len(lines), sum(1 for x in lines if x["p"]),
             len(data["outline"]), a.out.stat().st_size // 1024)
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
    li.set_defaults(fn=cmd_lines)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%F %T")
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
