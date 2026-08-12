#!/usr/bin/env python3
"""公表インピーダンス（observed）をAGJ建造モデルの枝に対応付ける。

出力は **crosswalk（対応表）** であって、モデルの書き換えではない。
observed を derived に流し込むのは介入なので、採用は docs/MODEL_INTERVENTIONS.md
への登録を経て別途行う（docs/OBSERVED_VS_DERIVED.md の規約）。

照合の段階（弱い順に降格していく。どの段で当たったかを match_level に残す）:
  1. exact      — 正規化名が完全一致
  2. paren      — 括弧併記を展開して一致（例 `新改開閉所（新改変電所）`）
  3. suffix     — 施設種別サフィックス（変電所/開閉所/発電所/変換所）を落として一致
  4. contains   — 一方が他方を含む（`坂出火力変電所` ⊃ `坂出`）
  未解決は理由を残す: tower(鉄塔番号) / anonymized(匿名化) / unknown

「両端が解決した公表線路」だけが、モデル枝へインピーダンスを移せる候補になる。
母数を黙って減らさないため、未解決も理由つきで全件出力する。

使い方:
    python scripts/match_impedance_to_model.py
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
NORM = ROOT / "data" / "external" / "system_disclosure" / "normalized"
BUILT = ROOT / "docs" / "data" / "built"

SUFFIX_RX = re.compile(r"(変電所|開閉所|発電所|変換所|switching|substation)$")
TOWER_RX = re.compile(r"(№|#|No\.?)\s*\d+|分岐鉄塔|鉄塔")
ANON_RX = re.compile(r"[□■○×]{2,}|^<\d+>|^\d+[^\d]")  # 九州の匿名化表記


def norm(s: str) -> str:
    """全角半角・空白・記号ゆれを吸収する。"""
    s = unicodedata.normalize("NFKC", str(s))
    s = re.sub(r"[\s　・,，]", "", s)
    return s


# 事業者は施設種別を略記する: 西島根(変) / 本川(開) / 阿南(変換)。
# 略記のままだと `西島根変電所` と一致しないので、展開した候補も作る。
ABBREV = {
    "(変)": "変電所", "(開)": "開閉所", "(発)": "発電所",
    "(変換)": "変換所", "(switching)": "開閉所",
}


def variants(s: str) -> list[str]:
    """1つの名前から照合候補を作る。"""
    n = norm(s)
    out = [n]
    # 略記の展開 `西島根(変)` → `西島根変電所` / `西島根`
    for ab, full in ABBREV.items():
        if n.endswith(ab):
            stem = n[: -len(ab)]
            out += [stem + full, stem]
    # 括弧併記 `新改開閉所（新改変電所）` → 両方を候補に
    m = re.match(r"^(.*?)[（(](.+?)[)）]$", n)
    if m:
        out += [m.group(1), m.group(2)]
    out += [SUFFIX_RX.sub("", v) for v in list(out)]
    return [v for v in dict.fromkeys(out) if v]


# モデル側に `変電所` `発電所` だけのノードが実在し、contains 照合で
# `変電所` ⊂ `新小野田変電所` が成立して 255km 先の別施設に誤爆した（実測 2026-08-11）。
# 施設種別そのものや短すぎるキーは照合の手掛かりにならないので index から除く。
GENERIC = {"変電所", "発電所", "開閉所", "変換所", "switchingstation", "substation", "powerplant"}
MIN_KEY_LEN = 3          # これ未満のキーは登録しない
MIN_CONTAINS_LEN = 4     # contains 照合は双方これ以上の長さを要求する


SUBSTATIONS = ROOT / "docs" / "data" / "substations.geojson"
_subs_cache: dict[str, list[dict]] | None = None


def _centroid(geom: dict) -> tuple[float, float] | None:
    """Point はそのまま、Polygon は外環の平均を代表点にする。"""
    g, c = geom.get("type"), geom.get("coordinates")
    if g == "Point":
        return c[0], c[1]
    ring = c[0] if g == "Polygon" else (c[0][0] if g == "MultiPolygon" else None)
    if not ring:
        return None
    return sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)


def _substations_by_region() -> dict[str, list[dict]]:
    """6,962件の変電所を地域別に索引する（1回だけ読む）。"""
    global _subs_cache
    if _subs_cache is not None:
        return _subs_cache
    _subs_cache = defaultdict(list)
    if SUBSTATIONS.exists():
        for f in json.loads(SUBSTATIONS.read_text(encoding="utf-8"))["features"]:
            p = f.get("properties") or {}
            name = p.get("name") or p.get("_display_name") or ""
            xy = _centroid(f.get("geometry") or {})
            if not name or not xy:
                continue
            _subs_cache[p.get("region") or ""].append(
                {"name": name, "lon": xy[0], "lat": xy[1],
                 "kv": p.get("voltage_kv"), "src": "substations"}
            )
    return _subs_cache


def load_model(region: str) -> tuple[dict[str, list], list[dict]]:
    """照合の母集団を作る。

    建造モデルのノードだけでは足りない（`西島根変電所` `中能登変電所` などが
    built に無く、四国500kV基幹すら引けなかった）。**6,962件の変電所レイヤも
    母集団に入れる**。built を先に登録するので、両方にある名前は built が勝つ
    （潮流計算の座標系と揃うため）。
    """
    index: dict[str, list] = defaultdict(list)
    edges: list[dict] = []

    path = BUILT / f"{region}.json"
    if path.exists():
        d = json.loads(path.read_text(encoding="utf-8"))
        edges = d["edges"]
        for n in d["nodes"]:
            name = n.get("name") or ""
            if not name or "junction" in name:
                continue
            for v in variants(name):
                if v in GENERIC or len(v) < MIN_KEY_LEN:
                    continue
                index[v].append(n)

    for s in _substations_by_region().get(region, []):
        for v in variants(s["name"]):
            if v in GENERIC or len(v) < MIN_KEY_LEN:
                continue
            index[v].append(s)

    return index, edges


def resolve(name: str, index: dict[str, list]) -> tuple[str, dict | None]:
    """名前をモデルノードへ解決し、(match_level, node) を返す。"""
    if ANON_RX.search(norm(name)):
        return "anonymized", None
    if TOWER_RX.search(str(name)):
        return "tower", None
    vs = variants(name)
    # 1. exact / 2. paren / 3. suffix — variants の順序がそのまま強さ
    for level, v in zip(["exact", "paren", "suffix", "suffix", "suffix"], vs):
        if v in index:
            return level, index[v][0]
    # 4. contains — 双方が十分長いときだけ。generic語の誤爆を防ぐ
    for v in vs:
        if len(v) < MIN_CONTAINS_LEN:
            continue
        for key, nodes in index.items():
            if len(key) < MIN_CONTAINS_LEN:
                continue
            if v in key or key in v:
                return "contains", nodes[0]
    return "unknown", None


def main() -> int:
    imp = pd.read_csv(NORM / "impedance_lines.csv")
    rows = []
    for utility, sub in imp.groupby("utility"):
        index, edges = load_model(utility)
        if not index:
            print(f"! モデル未発見: {utility}")
            continue
        for _, r in sub.iterrows():
            la, na = resolve(r["from_node"], index)
            lb, nb = resolve(r["to_node"], index)
            both = na is not None and nb is not None
            rows.append({
                "utility": utility,
                "voltage_kv": r["voltage_kv"],
                "line_name": r["name"],
                "from_node": r["from_node"],
                "to_node": r["to_node"],
                "R_pct": r["R_pct"], "X_pct": r["X_pct"], "B_half_pct": r["B_half_pct"],
                "base_mva": 1000,
                "from_match": la, "to_match": lb,
                "from_model": (na or {}).get("name", ""),
                "to_model": (nb or {}).get("name", ""),
                "from_lat": (na or {}).get("lat"), "from_lon": (na or {}).get("lon"),
                "to_lat": (nb or {}).get("lat"), "to_lon": (nb or {}).get("lon"),
                "both_resolved": both,
                "match_level": (
                    "both:" + ("exact" if la == lb == "exact" else f"{la}/{lb}")
                    if both else f"unresolved:{la}/{lb}"
                ),
                "layer": "observed",
                "source_file": r["source_file"],
            })
    out = pd.DataFrame(rows)
    dest = NORM / "crosswalk_impedance_to_model.csv"
    out.to_csv(dest, index=False, encoding="utf-8")

    print(f"公表線路 {len(out)} 本")
    print(f"両端解決 {int(out.both_resolved.sum())} 本 = {100*out.both_resolved.mean():.1f}%\n")
    print("=== 事業者別 ===")
    g = out.groupby("utility").agg(
        n=("both_resolved", "size"), resolved=("both_resolved", "sum")
    )
    g["rate_%"] = (100 * g.resolved / g.n).round(1)
    print(g.to_string())
    print("\n=== 未解決の理由（端点単位）===")
    reasons = pd.concat([
        out.loc[~out.both_resolved, "from_match"],
        out.loc[~out.both_resolved, "to_match"],
    ])
    print(reasons[reasons.isin(["tower", "anonymized", "unknown"])].value_counts().to_string())
    print(f"\n→ {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
