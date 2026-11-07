"""OCCTO の当日の潮流実績(scripts/export_occto_today.py)と io のページ docs/occto_flow.html の検査。

取得はしない(OCCTO へのリクエストは毎時の処理だけ)。CSV の書き方は 2026-11-07 に実物で確かめたもの:
運用容量の表は線路名に注記(「（フェンス２）」「（他社）」)が付く・区間名だけ・同じ名前を向きで分ける・
「～」の字が違う・中国の 99999・矢印が「⇒」。連系線の 5 分値は 24:00 で日をまたぐ。
"""
from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import export_occto_today as ex  # noqa: E402

D0, D1 = dt.date(2026, 11, 6), dt.date(2026, 11, 7)
SLOTS = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)]


def _csv(head: list[str], rows: list[list]) -> bytes:
    lines = [",".join(head)] + [",".join("" if v is None else str(v) for v in r) for r in rows]
    return ("\r\n".join(lines) + "\r\n").encode("cp932")


def _flow(rows: list[tuple]) -> bytes:
    head = ["対象年月日", "対象エリア", "電圧", "送電線名", "潮流方向(正方向)"] + SLOTS
    out = []
    for day, area, kv, name, direction, vals in rows:
        out.append([day, area, kv, name, direction] + vals + [None] * (48 - len(vals)))
    return _csv(head, out)


def _cap(rows: list[tuple]) -> bytes:
    head = ["断面", "対象エリア", "対象年度／対象年月日", "送電線ＮＯ", "電圧", "送電線名", "潮流方向",
            "予想潮流値", "運用容量", "決定要因", "フェンスＮＯ", "フェンス名"]
    return _csv(head, [["実績", a, day, 1, 275, name, direction, None, cap, why, None, None]
                       for day, a, name, direction, cap, why in rows])


def test_flow_keeps_until_last_value_and_uses_area_codes():
    body = _flow([
        ("2026/11/06", "北海道", 275, "狩勝幹線", "北新得SS → 南早来SS", [-260] * 48),
        ("2026/11/07", "北海道", 275, "狩勝幹線", "北新得SS → 南早来SS", [-250, -240, -230]),
        ("2026/11/07", "中部", 500, "三岐幹線", "三重 → 岐阜", [100]),
        ("2026/11/05", "中部", 500, "三岐幹線", "三重 → 岐阜", [999] * 48),   # 範囲の外は読まない
    ])
    times, lines = ex.parse_flow(body, [D0, D1])
    assert times[0] == "2026-11-06 00:00" and times[-1] == "2026-11-07 01:00" and len(times) == 51
    k = "hokkaido|狩勝幹線|北新得SS → 南早来SS"
    assert lines[k]["kv"] == 275 and lines[k]["v"][-1] == -230 and len(lines[k]["v"]) == 51
    assert lines["chubu|三岐幹線|三重 → 岐阜"]["v"][48] == 100
    assert 999 not in lines["chubu|三岐幹線|三重 → 岐阜"]["v"]


def test_capacity_name_variants_and_direction():
    lines = {ex.line_id(*k.split("|")): None for k in [
        "hokkaido|狩勝幹線|北新得SS → 南早来SS",                 # 容量の表は逆向き
        "kyushu|佐賀幹線|西九州ss → 中央ss",                     # 注記「（フェンス２）」
        "tokyo|新坂戸線|新新田 → 新坂戸",                        # 注記「（他社）」
        "hokkaido|十勝幹線(恵庭南札線)|南札幌SS → 恵庭SS",        # 容量の表は区間名だけ
        "hokkaido|名寄幹線（旭川嵐山～西名寄）|西名寄SS → 旭川嵐山SWS",   # 同じ名前を向きで分ける
        "kansai|北神線（北摂～４２Ｔ）|北摂変電所 → ４２T",        # 「～」の字が違う・「⇒」
        "chugoku|中国中幹線|日野（変） → 西島根（変）",            # 99999 は容量ではない
        "chugoku|日野幹線|新岡山（変） → 日野（変）",
    ]}
    body = _cap([
        ("2026/11/06", "北海道", "狩勝幹線 ", "南早来変電所 　→　北新得変電所", 949, "熱容量"),
        ("2026/11/06", "九州", "佐賀幹線（フェンス２）", "西九州ｓｓ→中央ｓｓ", 3201, "熱容量"),
        ("2026/11/06", "東京", "新坂戸線（他社）", "新新田　→　新坂戸", 6582, "熱容量"),
        ("2026/11/06", "北海道", "恵庭南札線 ", "恵庭変電所　→　南札幌変電所 ", 535, "熱容量"),
        ("2026/11/06", "北海道", "名寄幹線 ", "旭川嵐山開閉所　→　西名寄変電所", 361, "熱容量"),
        ("2026/11/06", "北海道", "名寄幹線 ", "西旭川変電所 　→　旭川嵐山開閉所", 261, "熱容量"),
        ("2026/11/06", "関西", "北神線（北摂〜４２Ｔ）", "北摂変電所⇒４２Ｔ", 4000, "熱容量"),
        ("2026/11/06", "中国", "中国中幹線（フェンス管理箇所）", "日野（変）→西島根（変）", 99999, "電圧"),
        ("2026/11/06", "中国", "日野幹線", "新岡山（変）→日野（変）", 3290, "熱容量"),
    ])
    cap = ex.parse_capacity(body, lines)["2026-11-06"]
    assert cap["hokkaido|狩勝幹線|北新得SS → 南早来SS"][:3] == [None, 949, 949]
    assert cap["kyushu|佐賀幹線|西九州ss → 中央ss"][:3] == [3201, None, 3201]
    assert cap["tokyo|新坂戸線|新新田 → 新坂戸"][0] == 6582
    assert cap["hokkaido|十勝幹線(恵庭南札線)|南札幌SS → 恵庭SS"][:3] == [None, 535, 535]
    # 括弧の前の名前で合わせるときは、向きの合う行だけ(西旭川 → 旭川嵐山 の 261 を混ぜない)
    assert cap["hokkaido|名寄幹線（旭川嵐山～西名寄）|西名寄SS → 旭川嵐山SWS"][:3] == [None, 361, 361]
    assert cap["kansai|北神線（北摂～４２Ｔ）|北摂変電所 → ４２T"][:3] == [4000, None, 4000]
    assert "chugoku|中国中幹線|日野（変） → 西島根（変）" not in cap
    assert cap["chugoku|日野幹線|新岡山（変） → 日野（変）"][0] == 3290


def test_interconnector_2400_moves_to_next_day():
    head = ["連系線", "対象日付", "対象時刻", "運用容量(順方向)", "運用容量(逆方向)", "広域調整枠(順方向)",
            "広域調整枠(逆方向)", "マージン(順方向)", "マージン(逆方向)", "空容量(順方向)", "空容量(逆方向)",
            "計画潮流(順方向)", "計画潮流(逆方向)", "潮流実績", "運用容量拡大分(順方向)", "運用容量拡大分(逆方向)"]
    pad = [0] * 8
    body = _csv(head, [
        ["北海道・本州間電力連系設備", "2026/11/06", "24:00", 600, -600] + pad + [120, 0, 0],
        ["北海道・本州間電力連系設備", "2026/11/07", "00:05", 600, -600] + pad + [130, 0, 0],
        ["北海道・本州間電力連系設備", "2026/11/07", "00:30", 600, -600] + pad + [140, 0, 0],
        ["北海道・本州間電力連系設備", "2026/11/07", "01:00", 600, -600] + pad + [None, 0, 0],   # まだ実績が無い
    ])
    times = [f"{d} {s}" for d in ("2026-11-06", "2026-11-07") for s in SLOTS][:51]
    ic = ex.parse_ic(body, times)["北海道・本州間電力連系設備"]
    assert ic[48] == [120, 600, -600]          # 11/06 24:00 = 11/07 00:00
    assert ic[49] == [140, 600, -600]
    assert ic[50] is None


def test_ends_normalise_station_names():
    assert ex.ends("西双葉SWS → 西野SS") == ex.ends("西双葉開閉所　→　西野変電所") == ("西双葉", "西野")
    assert ex.ends("日野（変）→西島根（変）") == ("日野", "西島根")
    assert ex.ends("西九州ｓｓ→中央ｓｓ") == ("西九州", "中央")
    assert ex.ends("西向き") is None


def test_simplify_keeps_ends():
    pts = [(0, 0), (1, 0.0001), (2, 0), (3, 1), (4, 0)]
    out = ex.simplify(pts, 0.01)
    assert out[0] == pts[0] and out[-1] == pts[-1] and (1, 0.0001) not in out and (3, 1) in out


# ---- 公開しているファイルとページ ----

FM = ROOT / "docs" / "data" / "flow_map"


def test_lines_file_matches_canon_and_has_unique_ids():
    d = json.loads((FM / "occto_lines.json").read_text(encoding="utf-8"))
    ids = [x["id"] for x in d["lines"]]
    assert len(ids) == len(set(ids))
    drawn = [x for x in d["lines"] if x["p"]]
    assert len(drawn) >= 300, "描ける線路が急に減った(照合か線の形を作り直すときに崩れた?)"
    for x in drawn:
        for path in x["p"]:
            assert all(122 < lon < 154 and 20 < lat < 46 for lon, lat in path)
    assert d["outline"], "日本の輪郭が無い"


def test_chain_orders_pieces_from_station_and_bridges_gaps():
    """切れ端を変電所 a から b へ並べ直し、向きをそろえ、切れ目と両端の離れを点線で結ぶ。"""
    a, b = [135.0, 35.0], [135.2, 35.0]
    far = [[135.2, 35.0], [135.12, 35.0]]        # b 側の切れ端(逆向き)
    near = [[135.01, 35.0], [135.08, 35.0]]      # a の 1 km 先から始まる切れ端
    solid, dash = ex.chain([far, near], a, b)
    assert solid == [near, far[::-1]]
    assert dash == [[a, near[0]], [near[-1], far[-1]]]   # a からの 1 km と、切れ端どうしの 4 km
    # 両端が分からなければ、在る切れ端だけを並べる
    solid, dash = ex.chain([near], None, None)
    assert solid == [near] and dash == []


def test_branch_trunk_names():
    assert ex.branch_trunk("571T(西南多摩線)") == "西南多摩線"
    assert ex.branch_trunk("１０９T（泉南東大阪線）") == "泉南東大阪線"
    assert ex.branch_trunk("山口幹線") == "山口幹線"
    assert ex.branch_trunk("42T") is None          # 幹線の名前が無い
    assert ex.branch_trunk("南山口変電所") is None
    assert ex.branch_trunk("新三河") is None


def test_place_branches_puts_t_end_on_the_trunk():
    """T 分岐の端は、分岐する先の幹線の描いた形の上で、もう一方の端にいちばん近い点に置く。点は打たない(t)。"""
    trunk = {"a": "chugoku", "n": "山口幹線", "p": [[[131.0, 34.0], [132.0, 34.0]]], "j": [], "s": [None, None],
             "d_ends": ["X", "Y"]}
    br = {"a": "chugoku", "n": "南山口支線", "p": [], "j": [], "s": [None, [131.5, 34.1]],
          "d_ends": ["山口幹線", "南山口変電所"]}
    other = {"a": "kansai", "n": "山口幹線の別エリア", "p": [[[135.0, 34.1], [136.0, 34.1]]], "j": [],
             "s": [None, None], "d_ends": ["", ""]}
    assert ex.place_branches([trunk, br, other]) == 1
    assert br["s"][0] == [131.5, 34.0] and br["t"] == [True, False]
    assert br["j"] == [[[131.5, 34.0], [131.5, 34.1]]]      # 形が無いので、置いた点から変電所への点線
    assert "t" not in trunk


def test_lines_join_at_stations_and_stay_in_area():
    """線路の端は変電所の点(s)から始まり、点線のつなぎも含めて端どうしがつながる。位置はエリアの県の中。"""
    d = json.loads((FM / "occto_lines.json").read_text(encoding="utf-8"))
    for x in d["lines"]:
        a, b = (x.get("s") or [None, None])
        if x["p"] and a:
            # 描き始めは変電所の点(切れ端が離れていれば、変電所からの点線)。点線の座標は 3 桁に丸めてある
            starts = [x["p"][0][0]] + [seg[0] for seg in x["j"][:1]]
            assert min(ex._km(q, a) for q in starts) < 0.3, x["id"]
        for seg in x["j"]:
            assert ex._km(seg[0], seg[1]) < 250, f"{x['id']}: 点線が長すぎる(位置の取り違え?)"
    # 東北の福島変電所が北海道の福島町に当たっていた(2026-11-07)
    fuku = [x for x in d["lines"] if x["a"] == "tohoku" and "福島" in x["d"]]
    assert fuku and all(not s or s[1] < 39.5 for x in fuku for s in x["s"])


def test_today_file_shape():
    d = json.loads((FM / "occto_today.json").read_text(encoding="utf-8"))
    for k in ("made", "source", "days", "times", "lines", "cap", "ic"):
        assert k in d
    n = len(d["times"])
    assert n and all(len(e["v"]) == n for e in d["lines"].values())
    assert all(len(v) == n for v in d["ic"].values())
    assert "電力広域的運営推進機関" in d["source"]


def test_page_script_parses():
    node = shutil.which("node")
    if not node:
        pytest.skip("node が無い")
    html = (ROOT / "docs" / "occto_flow.html").read_text(encoding="utf-8")
    scripts = re.findall(r"<script>(.*?)</script>", html, flags=re.S)
    assert scripts
    for s in scripts:
        r = subprocess.run([node, "--check", "-"], input=s, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    # 読むデータの名前とページの出典の表示
    assert "occto_lines.json" in html and "occto_today.json" in html and "出典" in html
