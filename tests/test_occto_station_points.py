"""OCCTO の線路の端の位置の台帳(config/occto_station_points.yaml)の点検。

台帳は潮流マップの表示だけに使う。点がエリアの外にある・出典が書かれていない・鍵が OCCTO の端の名前と
合わない(書き損じ)と、地図に誤った線を引くか、何も引かない。
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts import build_occto_line_crosswalk as cw  # noqa: E402

POINTS = yaml.safe_load((ROOT / "config" / "occto_station_points.yaml").read_text(encoding="utf-8"))["points"]
LINES = json.loads((ROOT / "docs" / "data" / "flow_map" / "occto_lines.json").read_text(encoding="utf-8"))["lines"]


def test_points_are_inside_their_area():
    polys = cw._pref_polys()
    for p in POINTS:
        pref = cw.pref_of([p["lon"], p["lat"]], polys)
        assert pref in cw.allowed_prefs(p["area"]), f"{p['area']} {p['name']}: {pref} はエリアの外"


def test_points_have_open_sources_and_unique_keys():
    keys = Counter((p["area"], p["name"]) for p in POINTS)
    assert not [k for k, n in keys.items() if n > 1], "同じ端が 2 回ある"
    for p in POINTS:
        assert re.fullmatch(r"osm:(node|way|relation)/\d+|gsi:(注記|記号|住所|写真)", p["ref"]), p
        if p["ref"] in ("gsi:住所", "gsi:写真", "gsi:記号") and p["conf"] != "低":
            assert p.get("src") or "OSM" in p["basis"], f"{p['name']}: 住所や名前の出典(src)が無い"
        assert not re.search(r"renewable-ei|arcgis|akiyouryou|空き?容量", str(p.get("src", "")), re.I), p   # REI・空き容量マップ
        assert p["conf"] in ("高", "中", "低"), p
        assert p["basis"].strip(), p
        # 空き容量マップ(REI を含む)は All Rights Reserved なので座標の出典にしない
        assert not re.search(r"REI|空き?容量", p["ref"]), p


def test_keys_are_occto_end_names():
    """鍵は OCCTO の向きの欄をそろえた名前。書き損じると、その端には位置が付かない。"""
    ends = set()
    for x in LINES:
        e = cw.split_direction(x["d"])
        if e:
            ends |= {(x["a"], e[0]), (x["a"], e[1])}
    missing = [(p["area"], p["name"]) for p in POINTS if (p["area"], p["name"]) not in ends]
    assert not missing, f"OCCTO の線路の端に無い名前: {missing}"


def test_ledger_points_reach_the_map():
    """台帳の位置が潮流マップの線路の端(s)に入っている(照合を作り直したあと、occto_lines.json も作り直したか)。"""
    ledger = cw.ledger_points()
    got = {}
    for x in LINES:
        e = cw.split_direction(x["d"])
        if e:
            for name, s in zip(e, x.get("s") or [None, None]):
                got.setdefault((x["a"], name), s)
    for k, pt in ledger.items():
        assert got.get(k) == pt, f"{k}: 地図の端 {got.get(k)} が台帳 {pt} と違う"


def test_end_points_prefer_the_ledger():
    obs = [{"util": "tohoku", "name": "吾妻幹線", "direction": "a", "from_occto": "福島", "to_occto": "X",
            "from": "福島変電所", "to": ""}]
    xy = {("tohoku", "福島変電所"): [140.25, 41.5]}           # 解決器が引いた北海道の福島
    ledger = {("tohoku", "福島"): [140.4228, 37.676]}
    assert cw.end_points(obs, xy, ledger)[("tohoku", "吾妻幹線", "a")] == ([140.4228, 37.676], None)
    assert cw.end_points(obs, xy, {})[("tohoku", "吾妻幹線", "a")] == ([140.25, 41.5], None)
