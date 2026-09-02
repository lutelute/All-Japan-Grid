#!/usr/bin/env python3
"""回線数(並列回線 `par`)の出典補完 — 介入#44 候補(2026-09-02).

背景: 正典 `docs/data/built/all.json` の枝の `par` は OSM の `circuits`/`cables` タグ由来で、
タグが無い線は 1 回線扱いになる。C① の N-1 スクリーニングで、本四連系(菰池二丁目~福江町
三丁目 500kV・実系統 2 回線)がモデル上 1 回線=橋になり、開放すると四国 467 バスが分離する
など、回線数の欠落が N-1 の結論を歪めていた。

本スクリプトは、一般送配電事業者の公表資料に載る**回線数という構造事実**をモデル線へ引き当てる。

出典(すべて data/external 配下・git 管理外。本スクリプトは quote/URL/取得日を台帳に残す):
  S1 関西電力送配電 空容量マッピング CSV(≥154kV・<154kV)      … 送電線名・電圧・回線数
  S2 東京電力PG 予想潮流・空容量 CSV(基幹+13エリア)              … 送電線名・電圧・回線数・潮流方向(端点)
  S3 四国電力送配電 系統容量 CSV(基幹+local01〜04)               … 送電線名・電圧・回線数
  S4 open-keitouzu routes.csv(CC BY 4.0)の n_circuits            … 線名・電圧・端点変電所(uuid→名前)
  S5 系統情報公表インピーダンス表の回線別行(播磨線1L/2L 等)     … 同一線名の回線トークン数 = 回線数の下限
  S6 normalized/line_observations.csv の n_circuit_records(S5 未収載の事業者)

照合(2経路・増やす方向のみ):
  route  端点変電所の両方がモデルの変電所ノード(名前正規化+地域+電圧階級)に解決できたとき、
         同階級の枝だけを辿る最短経路(迂回係数 ≤1.6・途中に別の同階級変電所を含まない)の
         全枝へ回線数を当てる。線名が OSM で区間ごとに違っていても(本四連系の橋区間など)届く。
  name   線名の正規化一致(NFKC・空白除去・回線トークン除去・括弧除去)+地域+電圧階級。
         端点が片方でも解決できたときは「枝の端点が解決先から 3km 以内」を要求(同名別線の誤爆防止)。
  複数出典が同じ枝に違う回線数を出したら高 confidence を優先し、食い違いを帳簿に残す。
  **par は増やす方向にしか変えない**(出典 n > 現 par のときだけ更新)。

使い方:
  PYTHONPATH=. python3 scripts/apply_circuit_sources.py            # ドライラン(台帳・レポート生成)
  PYTHONPATH=. python3 scripts/apply_circuit_sources.py --write    # 正典 par を更新(all.json.pre_circuits.bak)
出力: data/reference/circuit_counts.jsonl / docs/reports/circuit_sources_<date>.{json,md}
無効化: 枝の `par_src=="circuit_sources"` を `par_prev` に戻す / .bak 復元 / git revert
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import glob
import json
import math
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from src.powerflow.region_attribution import AREA_FREQ  # noqa: E402

BUILT = ROOT / "docs" / "data" / "built" / "all.json"
LEDGER = ROOT / "data" / "reference" / "circuit_counts.jsonl"
REPORTS = ROOT / "docs" / "reports"
EXT = ROOT / "data" / "external"
DISC = EXT / "system_disclosure"

CONF_RANK = {"high": 3, "medium": 2, "low": 1}
KV_CLASS = {66.0: "66", 77.0: "66", 110.0: "110", 132.0: "132", 154.0: "154",
            187.0: "154", 220.0: "220", 275.0: "275", 500.0: "500"}
DETOUR_MAX = 1.6
NAME_ENDPOINT_KM = 3.0
MAX_PAR = 8            # これ以上の回線数は OSM でも稀。出典値がこれを超えたら帳簿に残して適用しない

UTILITY_URL = {
    "tokyo": "https://www.tepco.co.jp/pg/consignment/system/",
    "kansai": "https://www.kansai-td.co.jp/interchange/takusou/",
    "shikoku": "https://www.yonden.co.jp/nw/line_access/",
}
NEIGHBORS = {
    "hokkaido": {"tohoku"}, "tohoku": {"hokkaido", "tokyo"}, "tokyo": {"tohoku", "chubu"},
    "chubu": {"tokyo", "hokuriku", "kansai"}, "hokuriku": {"chubu", "kansai"},
    "kansai": {"chubu", "hokuriku", "chugoku", "shikoku"}, "chugoku": {"kansai", "shikoku", "kyushu"},
    "shikoku": {"kansai", "chugoku"}, "kyushu": {"chugoku"}, "okinawa": set(),
}


# ── 正規化 ──────────────────────────────────────────────────────────────
def nfkc(s) -> str:
    return "".join(unicodedata.normalize("NFKC", str(s or "")).split())


_PAREN = re.compile(r"[（(][^（）()]*[）)]")
_CIRC_TOK = [
    re.compile(r"(\d+(?:[・,、/]\d+)*)\s*L$"),         # 播磨線1L / 東葛線1・2L
    re.compile(r"(\d+)号線$"),                          # 三岐幹1号線 → 三岐幹線
    re.compile(r"(\d+)号$"),
    re.compile(r"(\d+)回線$"),
    re.compile(r"[NnＮ][Oo]\.?\s*\d+$"),
]


def norm_line(name) -> str:
    """線名の基底(回線トークン・括弧・空白を除く)。"""
    s = nfkc(name)
    s = _PAREN.sub("", s)
    s = s.replace("(", "").replace(")", "")
    for i, pat in enumerate(_CIRC_TOK):
        m = pat.search(s)
        if m:
            s = s[:m.start()]
            if i == 1:                    # n号線 → 線
                s = s + "線"
            break
    return s


_SUB_SUFFIX = re.compile(r"(変電所|開閉所|発電所|変換所|電力所|連系所|給電所|変電|開閉)$")
_SUB_DROP = re.compile(r"(東京電力パワーグリッド|東京電力|関西電力送配電|関西電力|中部電力パワーグリッド|中部電力|"
                       r"東北電力ネットワーク|東北電力|北海道電力ネットワーク|北海道電力|北陸電力送配電|北陸電力|"
                       r"中国電力ネットワーク|中国電力|四国電力送配電|四国電力|九州電力送配電|九州電力|"
                       r"沖縄電力|電源開発|J-POWER|JR東日本|JR西日本|株式会社|\(株\))")


def norm_sub(name) -> str:
    s = nfkc(name)
    s = re.sub(r"\s*\d+(?:\.\d+)?kV$", "", s)         # モデルの「〜 500kV」サフィックス
    s = re.sub(r"_\d+$", "", s)                        # 〜_2
    s = _PAREN.sub("", s)
    s = s.replace("(開)", "").replace("(発)", "").replace("(変)", "")
    s = _SUB_DROP.sub("", s)
    s = s.replace("(", "").replace(")", "")
    s = _SUB_SUFFIX.sub("", s)
    return s


def kv_class(kv) -> str | None:
    try:
        kv = float(kv)
    except (TypeError, ValueError):
        return None
    if kv <= 0:
        return None
    if kv in KV_CLASS:
        return KV_CLASS[kv]
    nearest = min(KV_CLASS, key=lambda k: abs(k - kv))
    return KV_CLASS[nearest] if abs(nearest - kv) / nearest <= 0.15 else None


def kv_ok(kv_src, kv_edge) -> bool:
    if not kv_edge:
        return True                                    # 電圧不明の枝は許す(帳簿に残す)
    a, b = kv_class(kv_src), kv_class(kv_edge)
    return a is not None and a == b


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def k5(lat, lon):
    return (round(float(lat), 5), round(float(lon), 5))


# ── 出典ローダ ───────────────────────────────────────────────────────────
def _provenance() -> dict:
    out = {}
    p = DISC / "provenance.jsonl"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["file"]] = r
    return out


def _read_csv_any(path: Path):
    for enc in ("cp932", "utf-8-sig", "utf-8"):
        try:
            with open(path, encoding=enc, newline="") as f:
                return list(csv.reader(f))
        except (UnicodeDecodeError, LookupError):
            continue
    return []


def _int(x):
    try:
        return int(float(str(x).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def _float(x):
    try:
        return float(str(x).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _rec(**kw) -> dict:
    base = {"region": None, "name": "", "kv": None, "n": None, "from_sub": "", "to_sub": "",
            "source_type": "official", "source_file": "", "source_url": "", "quote": "",
            "retrieved": "", "confidence": "high", "kind": ""}
    base.update(kw)
    return base


def load_capacity_csvs(prov: dict) -> list[dict]:
    """S1 関西 / S2 東京 / S3 四国 — 「送電線名・電圧・回線数」列を持つ公表 CSV。"""
    recs = []
    files = []
    files += [(p, "kansai") for p in sorted(glob.glob(str(DISC / "kansai" / "capacity*" / "*line*.csv")))]
    files += [(p, "tokyo") for p in sorted(glob.glob(str(DISC / "tokyo" / "capacity" / "csv_yosochoryu_*" / "*soudensen*.csv")))]
    files += [(p, "shikoku") for p in sorted(glob.glob(str(DISC / "shikoku" / "capacity" / "sys_capa_*_line_*.csv")))]
    for path, region in files:
        rows = _read_csv_any(Path(path))
        if not rows:
            continue
        updated = next((c for r in rows[:3] for c in r if "更新" in c), "")
        updated = re.sub(r"[<＜].*?[>＞]", "", updated).strip()
        hi = next((i for i, r in enumerate(rows) if any("送電線名" in c for c in r)), None)
        if hi is None:
            continue
        header = rows[hi]
        try:
            ci_name = next(i for i, c in enumerate(header) if "送電線名" in c)
            ci_kv = next(i for i, c in enumerate(header) if "電圧" in c)
            ci_n = next(i for i, c in enumerate(header) if "回線数" in c)
        except StopIteration:
            continue
        rel = os.path.relpath(path, ROOT)
        pv = prov.get(rel, {})
        url = pv.get("source_url") or UTILITY_URL.get(region, "")
        retrieved = (pv.get("retrieved") or "")[:10]
        for r in rows[hi + 1:]:
            if len(r) <= ci_n:
                continue
            name = r[ci_name].strip()
            kv, n = _float(r[ci_kv]), _int(r[ci_n])
            if not name or name in ("送電線", "-", "－", "―") or kv is None or n is None or n <= 0:
                continue
            # 潮流方向 "A→B"(1セル) または [from, "→", to](3セル)
            fr = to = ""
            if "→" in r:
                j = r.index("→")
                fr, to = r[j - 1].strip(), r[j + 1].strip() if j + 1 < len(r) else ""
            else:
                for c in r[ci_n + 1:]:
                    if "→" in c:
                        fr, to = [x.strip() for x in c.split("→", 1)]
                        break
            if fr in ("-", "－", "―"):
                fr = ""
            if to in ("-", "－", "―", "需要家分岐"):
                to = ""
            # 匿名コード(変2/BD/北A 等)は端点として使わない
            if re.fullmatch(r"(変|発|開|送)?[0-9A-Za-z]{1,4}", fr or "x"):
                fr = ""
            if re.fullmatch(r"(変|発|開|送)?[0-9A-Za-z]{1,4}", to or "x"):
                to = ""
            recs.append(_rec(region=region, name=name, kv=kv, n=n, from_sub=fr, to_sub=to,
                             source_type="official", source_file=rel, source_url=url,
                             quote=f"送電線名「{name}」/ 電圧 {kv:g}kV / 回線数 {n}"
                                   + (f" / 潮流方向 {fr}→{to}" if fr and to else "")
                                   + (f"（{updated}）" if updated else ""),
                             retrieved=retrieved, confidence="high", kind="capacity_csv"))
    return recs


def load_keitouzu() -> list[dict]:
    """S4 open-keitouzu(CC BY 4.0)。n_circuits が入っている route のみ。"""
    d = EXT / "keitouzu"
    if not (d / "routes.csv").exists():
        return []
    subs = {s["uuid"]: s for s in csv.DictReader(open(d / "substations.csv", encoding="utf-8"))}
    srcs = {s["source_ref"]: s for s in csv.DictReader(open(d / "sources.csv", encoding="utf-8"))}
    recs = []
    for r in csv.DictReader(open(d / "routes.csv", encoding="utf-8")):
        n = _int(r.get("n_circuits"))
        kv = _float(r.get("voltage_kv"))
        if not n or n <= 0 or kv is None:
            continue
        fr = subs.get(r.get("from_substation"), {}).get("name_official", "")
        to = subs.get(r.get("to_substation"), {}).get("name_official", "")
        name = r.get("name_official") or ""
        if re.fullmatch(r"\d+", name):
            name = ""                                   # 送電線番号だけ=名前なし
        src = srcs.get(r.get("source_ref"), {})
        conf = {"verified": "high", "extracted": "medium", "inferred": "low"}.get(r.get("confidence"), "medium")
        recs.append(_rec(region=r.get("region") or None, name=name, kv=kv, n=n, from_sub=fr, to_sub=to,
                         source_type="open-keitouzu(CC BY 4.0)", source_file="data/external/keitouzu/routes.csv",
                         source_url="https://github.com/lutelute/open-keitouzu",
                         quote=(f"route {r.get('uuid','')[:8]} {name or '(番号のみ)'} {kv:g}kV n_circuits={n} "
                                f"{fr}→{to}; {src.get('document','')} {src.get('published_date','')}; "
                                + (r.get("notes") or "")[:160]),
                         retrieved=(src.get("retrieved_date") or r.get("updated_at") or "")[:10],
                         confidence=conf, kind="keitouzu"))
    return recs


def load_impedance_tokens(prov: dict) -> list[dict]:
    """S5 インピーダンス表の回線別行 → 同一線の回線トークン数(≥2 のみ)。"""
    p = DISC / "normalized" / "impedance_lines.csv"
    if not p.exists():
        return []
    groups: dict[tuple, dict] = {}
    for r in csv.DictReader(open(p, encoding="utf-8")):
        nm = nfkc(r.get("name"))
        m = re.search(r"(\d+)(?:L|号線|号)$", nm)
        if not m:
            continue
        base = norm_line(nm)
        key = (r["utility"], base, _float(r.get("voltage_kv")), nfkc(r.get("from_node")), nfkc(r.get("to_node")))
        g = groups.setdefault(key, {"tokens": set(), "names": [], "file": r.get("source_file", "")})
        g["tokens"].add(m.group(1))
        g["names"].append(r.get("name"))
    recs = []
    for (util, base, kv, fr, to), g in groups.items():
        n = len(g["tokens"])
        if n < 2 or kv is None:
            continue
        rel = g["file"]
        pv = prov.get(rel, {})
        recs.append(_rec(region=util, name=base, kv=kv, n=n, from_sub=fr, to_sub=to,
                         source_type="official(impedance table)", source_file=rel,
                         source_url=pv.get("source_url", ""),
                         quote=f"回線別行 {', '.join(g['names'][:6])} → 回線数 {n}(下限) / {fr}→{to}",
                         retrieved=(pv.get("retrieved") or "")[:10], confidence="high", kind="impedance_tokens"))
    return recs


def load_line_observations(prov: dict, covered: set) -> list[dict]:
    """S6 normalized/line_observations.csv の n_circuit_records(≥2)。S5 で未収載の線のみ。"""
    p = DISC / "normalized" / "line_observations.csv"
    if not p.exists():
        return []
    recs, seen = [], set()
    for r in csv.DictReader(open(p, encoding="utf-8")):
        n = _int(r.get("n_circuit_records"))
        kv = _float(r.get("voltage_kv"))
        if not n or n < 2 or kv is None:
            continue
        key = (r["utility"], norm_line(r.get("name")), kv, nfkc(r.get("from_node")), nfkc(r.get("to_node")))
        if key in covered or key in seen:
            continue
        seen.add(key)
        rel = r.get("source_flow") or ""
        pv = prov.get(rel, {})
        recs.append(_rec(region=r["utility"], name=r.get("name"), kv=kv, n=n,
                         from_sub=r.get("from_node"), to_sub=r.get("to_node"),
                         source_type="official(flow records)", source_file=rel,
                         source_url=pv.get("source_url", ""),
                         quote=f"潮流実績の回線別記録 n_circuit_records={n} / {r.get('name')} {kv:g}kV "
                               f"{r.get('from_node')}→{r.get('to_node')}",
                         retrieved=(pv.get("retrieved") or "")[:10], confidence="medium", kind="flow_records"))
    return recs


def load_kyushu_pool() -> list[dict]:
    """S7 九州電力送配電 地区別「予想潮流・空容量一覧表」(31地区 PDF→txt→pool_full.json)。

    `scripts/pool_kyushu_kuyoryo.py` が作った pool(#29 追補4 と同じ資産)。行に 回線数(circuits)・
    端点(frm/to・地区内の略称)を持つ。
    """
    p = DISC / "kyushu" / "keitouzu" / "kuyoryo" / "pool_full.json"
    if not p.exists():
        return []
    recs = []
    for r in json.loads(p.read_text(encoding="utf-8")):
        if r.get("section") != "line":
            continue
        n, kv = _int(r.get("circuits")), _float(r.get("kv"))
        if not n or kv is None:
            continue
        name = str(r.get("line") or "")
        if re.fullmatch(r"[□■\s]*線?", name) or name in ("送電線", ""):
            name = ""                                   # 匿名化された線名
        # 端点は「68苓北」のように表No.が前置される → 数字を落とす。「17発電所」等の匿名は捨てる
        def _ep(x):
            x = re.sub(r"^\d+", "", str(x or "")).strip()
            return "" if re.fullmatch(r"(発電所|変電所|開閉所|―|-)?", x) else x
        recs.append(_rec(region="kyushu", name=name, kv=kv, n=n,
                         from_sub=_ep(r.get("frm")), to_sub=_ep(r.get("to")),
                         source_type="official(district capacity table)",
                         source_file=f"data/external/system_disclosure/kyushu/keitouzu/kuyoryo/td_{r.get('district')}_260730.pdf",
                         source_url="https://www.kyuden.co.jp/td_service_wheeling_rule-document_disclosure_index.html",
                         quote=f"{r.get('district')} No.{r.get('no')} {r.get('line')} {kv:g}kV 回線数 {n} {r.get('frm')}→{r.get('to')}（2026-07-30 版）",
                         retrieved="2026-08-16", confidence="high", kind="kyushu_pool"))
    return recs


MANUAL = ROOT / "data" / "reference" / "circuit_counts_manual.jsonl"


def load_manual() -> list[dict]:
    """S8 手動収集の公式記録(git 追跡・quote/URL 必須)。公表 CSV に載らない連系線など。"""
    if not MANUAL.exists():
        return []
    recs = []
    for line in MANUAL.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        r = json.loads(line)
        if not (r.get("quote") and r.get("source_url") and r.get("n_circuits")):
            continue                                    # quote/URL の無い記録は使わない
        recs.append(_rec(region=r.get("region"), name=r.get("line", ""), kv=_float(r.get("kv")),
                         n=_int(r.get("n_circuits")), from_sub=r.get("from_sub", ""), to_sub=r.get("to_sub", ""),
                         source_type=r.get("source_type", "official"), source_file="data/reference/circuit_counts_manual.jsonl",
                         source_url=r["source_url"], quote=r["quote"], retrieved=r.get("retrieved", ""),
                         confidence=r.get("confidence", "high"), kind="manual"))
    return recs


def load_all_sources() -> list[dict]:
    prov = _provenance()
    recs = (load_capacity_csvs(prov) + load_keitouzu() + load_impedance_tokens(prov)
            + load_kyushu_pool() + load_manual())
    covered = {(r["region"], norm_line(r["name"]), r["kv"], nfkc(r["from_sub"]), nfkc(r["to_sub"]))
               for r in recs if r["kind"] == "impedance_tokens"}
    recs += load_line_observations(prov, covered)
    for i, r in enumerate(recs):
        r["rid"] = i
        r["name_norm"] = norm_line(r["name"]) if r["name"] else ""
        r["from_norm"] = norm_sub(r["from_sub"]) if r["from_sub"] else ""
        r["to_norm"] = norm_sub(r["to_sub"]) if r["to_sub"] else ""
    return recs


# ── モデル索引 ───────────────────────────────────────────────────────────
class Model:
    def __init__(self, built: dict):
        self.nodes = built["nodes"]
        self.edges = built["edges"]
        self.by_xy: dict[tuple, list[int]] = defaultdict(list)
        for i, n in enumerate(self.nodes):
            self.by_xy[k5(n["lat"], n["lon"])].append(i)
        self.sub_index: dict[str, list[int]] = defaultdict(list)
        for i, n in enumerate(self.nodes):
            if n.get("sub") and n.get("name") and "junction" not in str(n["name"]):
                self.sub_index[norm_sub(n["name"])].append(i)
        self.edge_regions: list[set] = []
        self.edge_names: list[set] = []
        self.edge_len: list[float] = []
        for e in self.edges:
            regs = set()
            for end in ("a", "b"):
                for ni in self.by_xy.get(k5(*e[end]), []):
                    if self.nodes[ni].get("region"):
                        regs.add(self.nodes[ni]["region"])
            self.edge_regions.append(regs)
            names = set()
            for part in str(e.get("name") or "").split(";"):
                b = norm_line(part)
                if b:
                    names.add(b)
            self.edge_names.append(names)
            self.edge_len.append(max(haversine_km(e["a"][0], e["a"][1], e["b"][0], e["b"][1]), 0.01))
        self.name_index: dict[str, list[int]] = defaultdict(list)
        for i, names in enumerate(self.edge_names):
            for nm in names:
                self.name_index[nm].append(i)
        self._graphs: dict[str, nx.MultiGraph] = {}

    # 同階級(または電圧不明)の枝だけの多重グラフ
    def graph(self, kv_src) -> nx.MultiGraph:
        cls = kv_class(kv_src) or "?"
        if cls not in self._graphs:
            g = nx.MultiGraph()
            for i, e in enumerate(self.edges):
                if not e.get("main", True):
                    continue
                if kv_ok(kv_src, e.get("kv")):
                    g.add_edge(k5(*e["a"]), k5(*e["b"]), idx=i, weight=self.edge_len[i])
            self._graphs[cls] = g
        return self._graphs[cls]

    def region_ok(self, i: int, region) -> bool:
        if not region or region == "inter":
            return True
        regs = self.edge_regions[i]
        if not regs:
            return True
        return region in regs or bool(regs & NEIGHBORS.get(region, set()))

    def resolve_sub(self, name_norm: str, region, kv) -> list[int]:
        cands = self.sub_index.get(name_norm, [])
        out = []
        for ni in cands:
            n = self.nodes[ni]
            if region and region != "inter" and n.get("region") not in ({region} | NEIGHBORS.get(region, set())):
                continue
            if not kv_ok(kv, n.get("kv")):
                continue
            out.append(ni)
        # 同地域優先
        if region and region != "inter":
            same = [ni for ni in out if self.nodes[ni].get("region") == region]
            if same:
                out = same
        return out

    def is_named_sub_key(self, key, kv) -> bool:
        for ni in self.by_xy.get(key, []):
            n = self.nodes[ni]
            if n.get("sub") and "junction" not in str(n.get("name", "")) and kv_ok(kv, n.get("kv")):
                return True
        return False

    def route_edges(self, from_ids: list[int], to_ids: list[int], kv) -> tuple[list[int] | None, dict]:
        """端点候補の全組合せで最短経路を探し、迂回係数が最小のものを返す。"""
        g = self.graph(kv)
        best, info = None, {}
        for fi in from_ids:
            for ti in to_ids:
                fk = k5(self.nodes[fi]["lat"], self.nodes[fi]["lon"])
                tk = k5(self.nodes[ti]["lat"], self.nodes[ti]["lon"])
                if fk == tk or fk not in g or tk not in g:
                    continue
                straight = haversine_km(*fk, *tk)
                if straight < 0.3:
                    continue
                # 途中に別の同階級変電所を含まない: それらを除いたビューで探索。
                # 見つからなければ「経由あり」で再探索(ケーブルヘッド等の名前付き端子を通る
                # 本四連系線のような線)。その場合は迂回係数をより厳しく(≤1.3)取り、経由名を帳簿に残す。
                blocked = {k for k in g.nodes if k not in (fk, tk) and self.is_named_sub_key(k, kv)}
                sub = nx.subgraph_view(g, filter_node=lambda k, _b=blocked: k not in _b)
                via = []
                try:
                    path = nx.shortest_path(sub, fk, tk, weight="weight")
                except (nx.NetworkXNoPath, nx.NodeNotFound):
                    try:
                        path = nx.shortest_path(g, fk, tk, weight="weight")
                    except (nx.NetworkXNoPath, nx.NodeNotFound):
                        continue
                    via = [self._sub_name_at(k) for k in path[1:-1] if k in blocked]
                    # 経由ありを許すのは基幹(≥187kV: ケーブルヘッド・端子局を名前付き変電所として
                    # 持つ)か、経由 1 箇所以内の短い線だけ。配電階級で多数の変電所を跨ぐ経路は
                    # 別線の区間を巻き込む恐れがあるので棄却
                    if not ((kv_class(kv) in ("154", "220", "275", "500")) or len(via) <= 1):
                        continue
                edge_ids, length = [], 0.0
                for u, v in zip(path[:-1], path[1:]):
                    # 多重辺は全て(並列区間のどれか一本だけ回線数が違うのは不自然)
                    ds = g.get_edge_data(u, v)
                    for d in ds.values():
                        edge_ids.append(d["idx"])
                    length += min(d["weight"] for d in ds.values())
                detour = length / straight
                if detour > (1.3 if via else DETOUR_MAX):
                    continue
                if best is None or detour < info["detour"]:
                    best = edge_ids
                    info = {"detour": round(detour, 3), "straight_km": round(straight, 2),
                            "path_km": round(length, 2), "n_hops": len(path) - 1,
                            "from": self.nodes[fi].get("name"), "to": self.nodes[ti].get("name")}
                    if via:
                        info["via_named_subs"] = via[:6]
        return best, info

    def _sub_name_at(self, key) -> str:
        for ni in self.by_xy.get(key, []):
            if self.nodes[ni].get("sub"):
                return str(self.nodes[ni].get("name"))
        return "?"

    def name_edges(self, name_norm: str, region, kv) -> list[int]:
        return [i for i in self.name_index.get(name_norm, [])
                if kv_ok(kv, self.edges[i].get("kv")) and self.region_ok(i, region)]

    def near_any(self, edge_ids: list[int], node_ids: list[int], km: float) -> bool:
        pts = [(self.nodes[ni]["lat"], self.nodes[ni]["lon"]) for ni in node_ids]
        for i in edge_ids:
            e = self.edges[i]
            for end in ("a", "b"):
                for la, lo in pts:
                    if haversine_km(e[end][0], e[end][1], la, lo) <= km:
                        return True
        return False


# ── 照合 ─────────────────────────────────────────────────────────────────
def match_all(model: Model, recs: list[dict]) -> list[dict]:
    out = []
    for r in recs:
        res = {"rid": r["rid"], "method": None, "edges": [], "note": ""}
        from_ids = model.resolve_sub(r["from_norm"], r["region"], r["kv"]) if r["from_norm"] else []
        to_ids = model.resolve_sub(r["to_norm"], r["region"], r["kv"]) if r["to_norm"] else []
        if from_ids and to_ids:
            eids, info = model.route_edges(from_ids, to_ids, r["kv"])
            if eids:
                res.update(method="route", edges=eids, note=json.dumps(info, ensure_ascii=False))
        if not res["edges"] and r["name_norm"]:
            eids = model.name_edges(r["name_norm"], r["region"], r["kv"])
            if eids:
                anchors = from_ids + to_ids
                if anchors and not model.near_any(eids, anchors, NAME_ENDPOINT_KM):
                    res["note"] = f"name-match rejected: {len(eids)} edges none within {NAME_ENDPOINT_KM}km of resolved endpoints"
                else:
                    res.update(method="name+endpoint" if anchors else "name", edges=eids)
        if not res["edges"] and not res["note"]:
            res["note"] = ("unresolved endpoints" if (r["from_norm"] or r["to_norm"]) else "no name") \
                if not r["name_norm"] or not model.name_index.get(r["name_norm"]) else "name found but kv/region mismatch"
        out.append(res)
    return out


def aggregate(model: Model, recs: list[dict], matches: list[dict]):
    """枝ごとに提案を集約。高 confidence 優先・食い違いは帳簿へ。"""
    per_edge: dict[int, list[tuple]] = defaultdict(list)
    for r, m in zip(recs, matches):
        for i in m["edges"]:
            per_edge[i].append((CONF_RANK.get(r["confidence"], 1), r["n"], r["rid"], m["method"]))
    decisions, conflicts = {}, []
    for i, props in per_edge.items():
        props.sort(key=lambda t: (-t[0], -t[1]))
        top_conf = props[0][0]
        top = [p for p in props if p[0] == top_conf]
        routes = [p for p in top if p[3] == "route"]
        if routes:
            # 経路照合は枝特定的 — 経路提案の最大
            n = max(p[1] for p in routes)
        else:
            # 名前照合だけで食い違う(同じ線名の区間ごとに回線数が違う公表)ときは保守的に最小
            ns = {p[1] for p in top}
            n = min(ns) if len(ns) > 1 else next(iter(ns))
        if len({p[1] for p in props}) > 1:
            conflicts.append({"edge": i, "name": model.edges[i].get("name"), "kv": model.edges[i].get("kv"),
                              "par": model.edges[i].get("par"),
                              "proposals": [{"n": p[1], "conf": p[0], "rid": p[2], "method": p[3]} for p in props]})
        decisions[i] = {"n": n, "rids": [p[2] for p in props if p[1] == n], "method": props[0][3]}
    return decisions, conflicts


def flagged_status(model: Model) -> dict:
    """C① が指摘した 3 線の現状(レポート用)。"""
    out = {}
    pats = {"本四連系(菰池二丁目~福江町三丁目 500kV)": ("菰池二丁目変電所~福江町三丁目変電所線", 500.0),
            "上野線 275kV": ("上野線", 275.0), "上野水道橋線 275kV": ("上野水道橋線", 275.0),
            "山代~久原 500kV": ("山代変電所~久原変電所線", 500.0)}
    for label, (nm, kv) in pats.items():
        pars = [e.get("par") for e in model.edges if e.get("name") == nm and e.get("kv") == kv]
        out[label] = {"n_edges": len(pars), "par": sorted(set(pars))}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--built", default=str(BUILT))
    ap.add_argument("--write", action="store_true", help="正典 par を更新(バックアップ .pre_circuits.bak)")
    ap.add_argument("--date", default=_dt.date.today().isoformat())
    ap.add_argument("--ledger", default=str(LEDGER))
    ap.add_argument("--out-dir", default=str(REPORTS))
    args = ap.parse_args(argv)

    built = json.loads(Path(args.built).read_text(encoding="utf-8"))
    model = Model(built)
    recs = load_all_sources()
    print(f"出典レコード {len(recs)}: " + ", ".join(f"{k}={v}" for k, v in Counter(r['kind'] for r in recs).items()))
    matches = match_all(model, recs)
    decisions, conflicts = aggregate(model, recs, matches)
    before = flagged_status(model)

    # 適用計画(増やす方向のみ)
    plan, skipped_cap = [], []
    for i, dcs in decisions.items():
        e = model.edges[i]
        par = int(e.get("par") or 1)
        if dcs["n"] > MAX_PAR:
            skipped_cap.append({"edge": i, "name": e.get("name"), "n": dcs["n"], "par": par})
            continue
        if dcs["n"] > par:
            plan.append((i, par, dcs["n"], dcs["rids"], dcs["method"]))
    by_kv = Counter(); by_method = Counter(); by_kind = Counter(); by_region = Counter()
    for i, par, n, rids, method in plan:
        by_kv[str(model.edges[i].get("kv"))] += 1
        by_method[method] += 1
        for rid in rids:
            by_kind[recs[rid]["kind"]] += 1
        for rg in sorted(model.edge_regions[i]) or ["?"]:
            by_region[rg] += 1

    # 帳簿 jsonl: 出典レコード単位(照合結果と適用枝)
    edge_plan = {i: (par, n) for i, par, n, _r, _m in plan}
    ledger_rows = []
    for r, m in zip(recs, matches):
        if not m["edges"]:
            continue
        applied = [[model.edges[i]["a"], model.edges[i]["b"]] for i in m["edges"] if i in edge_plan and r["rid"] in decisions[i]["rids"]]
        ledger_rows.append({
            "date": args.date, "region": r["region"], "line": r["name"], "kv": r["kv"], "n_circuits": r["n"],
            "from_sub": r["from_sub"], "to_sub": r["to_sub"], "source_type": r["source_type"],
            "source_file": r["source_file"], "source_url": r["source_url"], "quote": r["quote"],
            "retrieved": r["retrieved"], "confidence": r["confidence"], "match_method": m["method"],
            "match_note": m["note"], "n_model_edges": len(m["edges"]),
            "model_edge_names": sorted({model.edges[i].get("name") for i in m["edges"]})[:6],
            "n_edges_updated": len(applied), "edges_updated": applied,
        })
    args.ledger = str(Path(args.ledger).resolve())
    Path(args.ledger).parent.mkdir(parents=True, exist_ok=True)
    with open(args.ledger, "w", encoding="utf-8") as f:
        for row in ledger_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    unmatched = [{"region": r["region"], "line": r["name"], "kv": r["kv"], "n": r["n"],
                  "from": r["from_sub"], "to": r["to_sub"], "kind": r["kind"], "note": m["note"]}
                 for r, m in zip(recs, matches) if not m["edges"]]
    rep = {
        "date": args.date, "purpose": "介入#44 候補: 回線数(par)の出典補完",
        "n_sources": len(recs), "sources_by_kind": dict(Counter(r["kind"] for r in recs)),
        "n_matched_sources": sum(1 for m in matches if m["edges"]),
        "match_methods": dict(Counter(m["method"] for m in matches if m["edges"])),
        "n_edges_proposed": len(decisions), "n_edges_to_update": len(plan),
        "updates_by_kv": dict(by_kv), "updates_by_region": dict(by_region),
        "updates_by_method": dict(by_method), "updates_by_source_kind": dict(by_kind),
        "par_transitions": dict(Counter(f"{par}->{n}" for _i, par, n, _r, _m in plan)),
        "n_conflicts": len(conflicts), "conflicts": conflicts[:200],
        "skipped_over_max_par": skipped_cap,
        "n_unmatched": len(unmatched), "unmatched_by_kind": dict(Counter(u["kind"] for u in unmatched)),
        "unmatched_by_note": dict(Counter(u["note"][:40] for u in unmatched)),
        "unmatched_major": sorted([u for u in unmatched if (u["kv"] or 0) >= 154], key=lambda u: (-(u["kv"] or 0), str(u["region"])))[:120],
        "flagged_before": before, "written": False,
        "flagged_sources": {lab: [{"region": r["region"], "line": r["name"], "kv": r["kv"], "n": r["n"],
                                   "from": r["from_sub"], "to": r["to_sub"], "kind": r["kind"],
                                   "method": m["method"], "n_edges": len(m["edges"]), "note": m["note"][:100]}
                                  for r, m in zip(recs, matches)
                                  if any(t in (r["name"] + r["from_sub"] + r["to_sub"]) for t in toks)]
                            for lab, toks in {"本四連系": ("本四", "讃岐", "東岡山"), "上野線": ("上野線",),
                                              "上野水道橋線": ("上野水道橋",), "山代~久原": ("山代", "久原")}.items()},
    }

    if args.write:
        bak = Path(args.built).with_name(Path(args.built).name + ".pre_circuits.bak")
        bak.write_text(json.dumps(built, ensure_ascii=False), encoding="utf-8")
        n_nodes, n_edges = len(built["nodes"]), len(built["edges"])
        for i, par, n, rids, method in plan:
            e = built["edges"][i]
            e["par_prev"] = par
            e["par"] = n
            e["par_src"] = "circuit_sources"
            e["par_note"] = f"介入#44 {args.date} {method}: " + "; ".join(
                f"{recs[rid]['region']}:{recs[rid]['name'] or recs[rid]['from_sub']+'→'+recs[rid]['to_sub']}({recs[rid]['kind']})"
                for rid in rids[:3])
        assert len(built["nodes"]) == n_nodes and len(built["edges"]) == n_edges
        Path(args.built).write_text(json.dumps(built, ensure_ascii=False), encoding="utf-8")
        rep["written"] = True
        rep["flagged_after"] = flagged_status(Model(built))
        print(f"★正典適用: {len(plan)} 枝の par を更新(バックアップ={bak.name})")

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    jp = out_dir / f"circuit_sources_{args.date}.json"
    jp.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / f"circuit_sources_{args.date}.md").write_text(render_md(rep, model, recs, matches), encoding="utf-8")
    print(f"照合 {rep['n_matched_sources']}/{len(recs)} 出典 → 提案枝 {len(decisions)} / 更新対象 {len(plan)} "
          f"(kv別 {dict(by_kv)}) / 食い違い {len(conflicts)} / 未照合 {len(unmatched)}")
    print(f"-> {os.path.relpath(jp, ROOT)} / {os.path.relpath(args.ledger, ROOT)}")
    return 0


def render_md(rep: dict, model: Model, recs: list[dict], matches: list[dict]) -> str:
    L = [f"# 回線数(par)の出典補完 — 介入#44 候補({rep['date']})", "",
         f"- 状態: {'**正典適用済み**' if rep['written'] else 'ドライラン(正典不変)'}",
         f"- 出典レコード {rep['n_sources']}(種別: {rep['sources_by_kind']})、照合 {rep['n_matched_sources']}"
         f"(方法: {rep['match_methods']})、提案枝 {rep['n_edges_proposed']}、**更新 {rep['n_edges_to_update']} 枝**(増やす方向のみ)",
         f"- 更新の kv 別: {rep['updates_by_kv']}", f"- 更新の地域別: {rep['updates_by_region']}",
         f"- 更新の照合方法別: {rep['updates_by_method']} / 出典種別: {rep['updates_by_source_kind']}",
         f"- par 遷移: {rep['par_transitions']}",
         f"- 食い違い(同一枝に別の回線数): {rep['n_conflicts']} / 上限 {MAX_PAR} 超で保留: {len(rep['skipped_over_max_par'])}",
         f"- 未照合の出典: {rep['n_unmatched']}({rep['unmatched_by_kind']})", "",
         "## C① が指摘した線の現状", "", "| 線 | 枝数 | par(前) | par(後) |", "|---|---:|---|---|"]
    after = rep.get("flagged_after", {})
    for k, v in rep["flagged_before"].items():
        L.append(f"| {k} | {v['n_edges']} | {v['par']} | {after.get(k, {}).get('par', '—')} |")
    L += ["", "## 指摘線に関係する出典レコード", ""]
    for lab, rows in rep.get("flagged_sources", {}).items():
        L.append(f"- **{lab}**: " + ("; ".join(f"{x['region']} {x['line'] or x['from']+'→'+x['to']} {x['kv']:g}kV n={x['n']} [{x['kind']}/{x['method'] or '未照合'}:{x['n_edges']}枝]" for x in rows[:8]) or "該当なし"))
    L += ["", "## 食い違い(上位)", "", "| 枝 | kV | par | 提案 |", "|---|---:|---:|---|"]
    for c in rep["conflicts"][:25]:
        L.append(f"| {c['name']} | {c['kv']} | {c['par']} | " + ", ".join(f"n={p['n']}(conf{p['conf']},{p['method']})" for p in c["proposals"]) + " |")
    L += ["", "## 未照合の主要線(≥154kV・上位)", "", "| 地域 | 線名 | kV | n | from→to | 種別 | 理由 |", "|---|---|---:|---:|---|---|---|"]
    for u in rep["unmatched_major"][:60]:
        L.append(f"| {u['region']} | {u['line']} | {u['kv']:g} | {u['n']} | {u['from']}→{u['to']} | {u['kind']} | {u['note']} |")
    L += ["", "## 読み方・限界", "",
          "- 回線数は**構造事実**として公表資料の quote 付きで台帳化した(`data/reference/circuit_counts.jsonl`)。容量値はコミットしない(All-Rights-Reserved 方針)",
          "- `route` 照合は端点変電所間の同階級最短経路(迂回 ≤1.6・途中に別の同階級変電所なし)に当てるため、OSM の区間名が違っても届く。"
          "経路が実線形と違う可能性は残る(帳簿の n_hops/detour で点検)",
          "- `name` 照合は線名+地域+電圧階級。端点が解決できた場合は 3km 以内の枝であることを要求",
          "- 増やす方向のみ。OSM の `circuits` が出典より大きい枝はそのまま(食い違いとして帳簿)",
          "- インピーダンス表の回線トークン数は**下限**(表に載る回線だけ)"]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
