#!/usr/bin/env python3
"""孤立変電所の実証接続 v2 — 公表線路・分岐タップ・変圧器実証・同一敷地同定。

v1 (apply_tepco_connections.py, 介入#28) は TEPCO東京10件+Wikipedia3件だった。
v2 は東北の系統情報公表（潮流実績 line/tr・3年分）と、監査から見つかった
**跨region重複**（同名・同電圧・至近距離で本系統側コピーと孤立コピーが併存）を扱う。

証拠クラス（disable フラグで個別に無効化できる＝③無効化）:
  C  disclosure_line   公表potential from-to（潮流正方向/様式5区間）の実線。プールを
                       直接読み、電圧階級の対応する側のノードに枝を付ける。
  E  disclosure_tap    公表の「◯◯線分岐」経由（分岐タップ）。線の端点へ接続し
                       via を記録（例: 東通→[162C線→大畑線分岐]→下北）。
  G  disclosure_trafo  変圧器潮流実績CSV（変電所名×一次/二次電圧）で実証される
                       同名・異電圧ノード間の変圧器タイ（例: 下北154-66）。
  F  same_site_identity 同名(正規化)・電圧一致・≤300m の本系統/孤立ペア＝同一変電所の
                       跨region二重登録。孤立コピーを本系統コピーへタイで同定し、
                       region が違えば本系統側の region に是正（島判定の前提）。
                       B判定（鉄道/自家用）は対象外。汎用名（tokyo_sub等）は距離以前に除外。

v1 で適用済みの枝は座標で重複検知してスキップする（冪等）。
ドライランが既定。--write は BAK を取り可逆（--revert で v2 適用直前に戻す）。
生の潮流値・R/X 等は一切収録しない（転載禁止・接続事実のみ）。
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
import math
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.powerflow.connectivity import compute_connectivity  # noqa: E402
from scripts.reconcile_isolated_multi import build_pool, norm  # noqa: E402

BUILT = ROOT / "docs" / "data" / "built" / "all.json"
BAK = ROOT / "docs" / "data" / "built" / "all.json.pre_v2.bak"
SUPPL = ROOT / "config" / "disclosure_supplement_nodes.yaml"


def load_supplements() -> list[dict]:
    """供給ノード台帳(判読で実在確定・モデル不在の変電所)を読む。"""
    if not SUPPL.exists():
        return []
    import yaml as _yaml
    out = []
    for m in (_yaml.safe_load(SUPPL.read_text(encoding="utf-8")) or {}).get("nodes", []):
        slug = re.sub(r"[^0-9A-Za-z一-龥ぁ-んァ-ン]", "", str(m["name"]))[:24]
        out.append({
            "id": f"suppl_{m.get('region','x')}_{slug}",
            "name": m["name"],
            "lat": round(float(m["lat"]), 5), "lon": round(float(m["lon"]), 5),
            "kv": float(m["kv"]) if m.get("kv") else 0.0,
            "region": m.get("region"), "sub": 1, "deg": 0,
            "supplement": True,
            "suppl_src": (f"OSM {m['osm']}" if m.get("osm") else "図位置近似")
                         + " / " + str(m.get("evidence", "")),
        })
    return out
AUDIT = ROOT / "data" / "external" / "system_disclosure" / "viz" / "audit_nodes.geojson"
TR_REG = ROOT / "data" / "external" / "system_disclosure" / "normalized" / "tohoku_tr_registry.csv"
OUT = ROOT / "docs" / "reports" / "disclosure_connection_worklist_v2.json"

GENERIC_NAME = re.compile(r"^[a-z]+_sub$")          # tokyo_sub_123 等の汎用名（norm後）
SAME_SITE_MAX_M = 300.0                              # 同一敷地とみなす距離
BRANCH_RX = re.compile(r"^(.+?)(線)?分岐$")


def hav_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    return 6371000 * 2 * math.asin(math.sqrt(
        math.sin((la2 - la1) / 2) ** 2
        + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2))


def _k5(la, lo):
    return (round(la, 5), round(lo, 5))


# ---------------------------------------------------------------------------
# ノード台帳（audit を参照系にする — 同名重複があるので id 基準）
# ---------------------------------------------------------------------------
class Frame:
    def __init__(self) -> None:
        feats = json.loads(AUDIT.read_text(encoding="utf-8"))["features"]
        self.nodes = []            # {id,name,latlon,cls,verdict,region,kv,sub}
        for f in feats:
            p = f["properties"]
            lon, lat = f["geometry"]["coordinates"][:2]
            self.nodes.append({
                "id": p.get("id"), "name": p.get("name") or "",
                "latlon": (lat, lon), "cls": p.get("cls"),
                "verdict": p.get("verdict"), "region": p.get("region"),
                "kv": p.get("kv") or 0, "sub": bool(p.get("sub")),
            })
        # 供給ノード(台帳)も参照系に足す — MAPS の相手として pick 可能にする
        for s in load_supplements():
            self.nodes.append({
                "id": s["id"], "name": s["name"],
                "latlon": (s["lat"], s["lon"]), "cls": "supplement",
                "verdict": None, "region": s.get("region"),
                "kv": s.get("kv") or 0, "sub": True,
            })
        self.by_norm: dict[str, list[dict]] = defaultdict(list)
        for n in self.nodes:
            k = norm(n["name"])
            if k and not GENERIC_NAME.match(k):
                self.by_norm[k].append(n)

    def isolated_subs(self) -> list[dict]:
        return [n for n in self.nodes if n["cls"] == "isolated_sub"]

    def variants(self, name: str) -> list[dict]:
        return self.by_norm.get(norm(name), [])

    def pick(self, name: str, kv: float | None, region: str | None,
             want_main: bool | None = None) -> dict | None:
        """名前（正規化）でノードを選ぶ。kv一致 > 高kv、region一致を優先。"""
        cands = self.variants(name)
        if region:
            reg = [c for c in cands if c["region"] == region]
            cands = reg or cands
        if want_main is not None:
            cands = [c for c in cands if (c["cls"] == "main") == want_main]
        if not cands:
            return None
        if kv:
            exact = [c for c in cands if abs((c["kv"] or 0) - kv) < 1]
            if exact:
                return exact[0]
            # 完全一致が無ければ最近接階級(対数比)。max(kv)既定だと77kV枝が
            # 275kV基幹バスへ張られる(駿河で実害 2026-08-17)。kv不明候補は除外
            with_kv = [c for c in cands if (c["kv"] or 0) > 0]
            if with_kv:
                import math
                return min(with_kv, key=lambda c: abs(math.log(c["kv"] / kv)))
        return max(cands, key=lambda c: c["kv"] or 0)


def load_tr_registry() -> set[str]:
    """東北 tr CSV から作った変圧器台帳 → 変電所名(正規化)の集合。"""
    names: set[str] = set()
    if TR_REG.exists():
        with TR_REG.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                k = norm(row.get("name", ""))
                if k:
                    names.add(k)
    return names


# ---------------------------------------------------------------------------
# worklist 構築
# ---------------------------------------------------------------------------
def build_worklist(frame: Frame) -> tuple[list[dict], list[dict], list[dict]]:
    """(edges, region_fixes, review) を返す。edges は適用候補、review は人間確認送り。"""
    edges: list[dict] = []
    region_fixes: list[dict] = []
    review: list[dict] = []
    seen_pairs: set[frozenset] = set()

    def add_edge(a: dict, b: dict, cls: str, kv, line, evidence, **extra):
        key = frozenset((_k5(*a["latlon"]), _k5(*b["latlon"])))
        if len(key) < 2 or key in seen_pairs:
            return
        seen_pairs.add(key)
        edges.append({
            "class": cls, "from_sub": a["name"], "to_sub": b["name"],
            "from_id": a["id"], "to_id": b["id"],
            "from_pt": list(a["latlon"]), "to_pt": list(b["latlon"]),
            "kv": kv, "line": line, "evidence": evidence, **extra,
        })

    # --- 東北: 公表プール直読（kv対応付けを report で失う前に使う） ---
    pool, _cov = build_pool({"tohoku"})
    ep_index: dict[str, list[dict]] = defaultdict(list)
    line_index: dict[str, list[dict]] = defaultdict(list)
    for x in pool:
        ep_index[norm(x["from"])].append(x)
        ep_index[norm(x["to"])].append(x)
        if x.get("line"):
            line_index[norm(x["line"])].append(x)

    tr_names = load_tr_registry()
    isos = frame.isolated_subs()
    iso_tohoku_A = [n for n in isos if n["region"] == "tohoku" and n["verdict"] == "A"]

    # C: 公表線路 — 孤立ノードの正規化名がプール端点にあり、他端がモデルに実在する
    done_norm: set[tuple[str, str]] = set()
    for iso in iso_tohoku_A:
        k = norm(iso["name"])
        for x in ep_index.get(k, []):
            other = x["to"] if norm(x["from"]) == k else x["from"]
            if norm(other) == k:
                continue
            kv = x.get("kv")
            # 電圧階級の対応する側の孤立ノードに付ける（154kV線は154kVノードへ）
            if kv and iso["kv"] and abs(iso["kv"] - kv) > 1:
                continue
            tgt = frame.pick(other, kv, "tohoku", want_main=True) \
                or frame.pick(other, kv, "tohoku", want_main=False)
            if tgt is None or tgt["id"] == iso["id"]:
                continue
            pair = (k, norm(other))
            if pair in done_norm:
                continue
            done_norm.add(pair)
            add_edge(iso, tgt, "disclosure_line", kv, x.get("line"),
                     "東北NW系統情報公表 潮流実績CSV「潮流正方向」", src=x.get("src"))

    # E: 分岐タップ — 相手端が「◯◯線分岐」のとき、その線の端点へ via 付きで繋ぐ
    for iso in iso_tohoku_A:
        k = norm(iso["name"])
        for x in ep_index.get(k, []):
            other = x["to"] if norm(x["from"]) == k else x["from"]
            m = BRANCH_RX.match(str(other).strip())
            if not m:
                continue
            trunk = m.group(1)
            for tx in line_index.get(norm(trunk), []) + line_index.get(norm(trunk + "線"), []):
                for end in (tx["from"], tx["to"]):
                    tgt = frame.pick(end, tx.get("kv"), "tohoku", want_main=True) \
                        or frame.pick(end, tx.get("kv"), "tohoku", want_main=False)
                    if tgt is None or tgt["id"] == iso["id"]:
                        continue
                    add_edge(iso, tgt, "disclosure_tap", x.get("kv"), x.get("line"),
                             "東北NW公表: 分岐タップ（公表 from-to の分岐点経由）",
                             via=f"{other}（{trunk}の分岐）")
                    break
                else:
                    continue
                break

    # M: 系統構成図の判読 — 台帳は config/disclosure_map_connections.yaml（外部化）。
    # 図PDF(転載禁止・data/external内)の判読で確認できた接続のみ。運用規約はyaml冒頭。
    map_yaml = ROOT / "config" / "disclosure_map_connections.yaml"
    if map_yaml.exists():
        import yaml as _yaml

        def pick_near(name, kv, reg, hint, want_main=None):
            """near ヒントがあれば同名候補から最寄り(≤50km)を選ぶ。同名別所の罠対策。"""
            if hint is None:
                return (frame.pick(name, kv, reg, want_main=want_main)
                        or frame.pick(name, kv, reg))
            cands = frame.variants(name)
            if not cands:
                # 無名ノード(tokyo_sub_1790等のビルド添字名)は罠10対処でindexから
                # 除外されている。frm_nearヒントがあるときだけ、指定名の一致を要求して
                # 純座標(≤300m)で拾う — 松本圏のtokyo/chubu二重登録の同定に必要
                same_id = [n for n in frame.nodes if n.get("name") == name]
                pool = same_id or [n for n in frame.nodes
                                   if hav_m(tuple(hint), n["latlon"]) <= 300]
                if not pool:
                    return None
                best = min(pool, key=lambda c: hav_m(tuple(hint), c["latlon"]))
                return best if hav_m(tuple(hint), best["latlon"]) <= 300 else None
            best = min(cands, key=lambda c: hav_m(tuple(hint), c["latlon"]))
            return best if hav_m(tuple(hint), best["latlon"]) <= 50_000 else None

        for m in (_yaml.safe_load(map_yaml.read_text(encoding="utf-8")) or {}).get(
                "connections", []):
            reg = m.get("region")
            kv = float(m["kv"]) if m.get("kv") else None
            a = pick_near(m["frm"], kv, reg, m.get("frm_near"), want_main=False)
            b = pick_near(m["to"], kv, reg, m.get("to_near"), want_main=True)
            if a is None or b is None:
                print(f"! disclosure_map 未解決ノード: {m['frm']} → {m['to']}（skip）")
                continue
            if a["id"] == b["id"]:
                continue
            # 距離ガード: 同名別所の誤pickが正典に届いた実害(小山_3=96km/八王子堀之内=184km)
            # への防壁。実在の長距離幹線は max_km で明示して通す(例: 大間幹線)。
            km = hav_m(a["latlon"], b["latlon"]) / 1000
            limit = float(m.get("max_km") or 60)
            if km > limit:
                print(f"! disclosure_map 距離ガード: {m['frm']}→{m['to']} {km:.0f}km"
                      f" > {limit:.0f}km（skip。実在ならyamlに max_km を明示）")
                continue
            add_edge(a, b, "disclosure_map", kv, m.get("line"),
                     f"系統図判読: {m.get('src','')}")
            # fix_region — 同一敷地同定のreview帯個体等で孤立側(frm)のregionを是正する。
            # true=本系統側(to)のregionへ / 文字列=そのregionへ明示(両側とも誤ラベルの
            # 場合に使う。例: 松本圏のtokyoラベル二重登録はchubuが正)。是正しないと
            # 周波数島ラベルが違うままタイが両島のどちらのグラフにも入らず無効になる
            fr = m.get("fix_region")
            if fr:
                target = fr if isinstance(fr, str) else b.get("region")
                if a.get("region") != target:
                    region_fixes.append({
                        "id": a["id"], "name": a["name"],
                        "from": a.get("region"), "to": target,
                        "evidence": f"disclosure_map fix_region指定: {m.get('src','')[:80]}",
                    })

    # G: 変圧器実証 — tr台帳にある変電所の、同名・異電圧の孤立/本系統ノード間タイ
    for k, fam in frame.by_norm.items():
        if k not in tr_names:
            continue
        fam_iso = [n for n in fam if n["cls"] == "isolated_sub" and n["verdict"] != "B"]
        fam_any = [n for n in fam if n["cls"] in ("main", "isolated_sub")]
        for iso in fam_iso:
            best = None
            for o in fam_any:
                if o["id"] == iso["id"] or abs((o["kv"] or 0) - (iso["kv"] or 0)) < 1:
                    continue
                d = hav_m(iso["latlon"], o["latlon"])
                if d <= 800 and (best is None or d < best[0]):
                    best = (d, o)
            if best:
                add_edge(iso, best[1], "disclosure_trafo",
                         min(iso["kv"], best[1]["kv"]) or None, None,
                         "東北NW変圧器潮流実績CSV（変電所名×一次/二次電圧）",
                         trafo=True, dist_m=round(best[0]))

    # F: 同一敷地同定 — 同名・電圧一致・≤300m の (孤立, 本系統) ペア
    for k, fam in frame.by_norm.items():
        fam_iso = [n for n in fam if n["cls"] == "isolated_sub"
                   and n["verdict"] in ("A", "?")]
        fam_main = [n for n in fam if n["cls"] == "main"]
        if not fam_iso or not fam_main:
            continue
        for iso in fam_iso:
            best = None
            for mn in fam_main:
                d = hav_m(iso["latlon"], mn["latlon"])
                if best is None or d < best[0]:
                    best = (d, mn)
            d, mn = best
            kv_ok = (not iso["kv"]) or (not mn["kv"]) or abs(iso["kv"] - mn["kv"]) < 1
            if d <= SAME_SITE_MAX_M and kv_ok:
                add_edge(iso, mn, "same_site_identity", iso["kv"] or mn["kv"] or None,
                         None, "同名(正規化)・同電圧・至近距離＝同一変電所の跨region二重登録",
                         same_site=True, dist_m=round(d))
                if iso["region"] != mn["region"]:
                    region_fixes.append({
                        "id": iso["id"], "name": iso["name"],
                        "from": iso["region"], "to": mn["region"],
                        "evidence": f"本系統側コピー({mn['name']}/{mn['region']})と同一敷地"
                                    f"（{round(d)}m）。島判定は本系統側が正",
                    })
            elif d <= SAME_SITE_MAX_M and not kv_ok:
                # 電圧違いの至近ペア: 同一敷地の別階級（変圧器で内部接続されるのが物理）
                add_edge(iso, mn, "same_site_identity", None, None,
                         "同名(正規化)・至近距離の異電圧ペア＝同一変電所の別電圧階級"
                         "（変電所内部は変圧器で接続されるのが物理）",
                         same_site=True, kv_pair=[iso["kv"], mn["kv"]], dist_m=round(d))
                if iso["region"] != mn["region"]:
                    region_fixes.append({
                        "id": iso["id"], "name": iso["name"],
                        "from": iso["region"], "to": mn["region"],
                        "evidence": f"本系統側コピー({mn['name']}/{mn['region']})と同一敷地"
                                    f"（{round(d)}m・異電圧階級）",
                    })
            elif d <= 800:
                review.append({"iso": iso["name"], "main": mn["name"],
                               "dist_m": round(d), "kv": [iso["kv"], mn["kv"]],
                               "regions": [iso["region"], mn["region"]],
                               "note": "300-800m: 同一敷地か要人間確認"})
    return edges, region_fixes, review


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="正典 all.json に適用（可逆）")
    ap.add_argument("--out", default=None,
                    help="適用結果をこのパスへ書く（正典は不変。影響測定・査読用）")
    ap.add_argument("--from-worklist", action="store_true",
                    help="worklistを再計算せず、コミット済みの帳簿"
                         "(docs/reports/disclosure_connection_worklist_v2.json)から適用する。"
                         "build（build_editor_data）が all.json を基底から再構築して介入を"
                         "消すため、regenerate_all のパイプラインステップとして使う（冪等）")
    ap.add_argument("--update-ledger", action="store_true",
                    help="帳簿(docs/reports/disclosure_connection_worklist_v2.json)を"
                         "今回の worklist で書き換える。既定では帳簿は不変"
                         "（適用済み状態でのドライランが帳簿を空にする事故の防止。"
                         "帳簿はパイプライン --from-worklist の入力=介入の正本）")
    ap.add_argument("--revert", action="store_true", help="v2適用直前に戻す")
    ap.add_argument("--disable", default="",
                    help="無効化する証拠クラス（カンマ区切り: disclosure_line,"
                         "disclosure_tap,disclosure_trafo,same_site_identity）")
    args = ap.parse_args()

    if args.revert:
        if BAK.exists():
            BUILT.write_text(BAK.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"復元: {BAK.name} → all.json（v2適用前に戻した）")
        else:
            print("v2バックアップが無い（未適用）")
        return 0

    disabled = {s.strip() for s in args.disable.split(",") if s.strip()}
    if args.from_worklist:
        # 帳簿から適用（audit不要・冪等・region fixesも帳簿のものを使う）
        wl = json.loads(OUT.read_text(encoding="utf-8"))
        edges = [e for e in wl["worklist"] if e["class"] not in disabled]
        region_fixes = [] if "same_site_identity" in disabled else wl["region_fixes"]
        review = wl.get("review_300_800m", [])
    else:
        frame = Frame()
        edges, region_fixes, review = build_worklist(frame)
        if disabled:
            edges = [e for e in edges if e["class"] not in disabled]
            if "same_site_identity" in disabled:
                region_fixes = []

    built = json.loads(BUILT.read_text(encoding="utf-8"))
    nodes, bedges = built["nodes"], built["edges"]

    # 供給ノード注入（判読で実在確定・モデル不在の変電所の補完。冪等・出典必須）
    if "supplement" not in disabled:
        have_ids = {n.get("id") for n in nodes}
        n_suppl = 0
        for s in load_supplements():
            if s["id"] not in have_ids:
                nodes.append(s)
                n_suppl += 1
        if n_suppl:
            print(f"供給ノード注入: {n_suppl}件（config/disclosure_supplement_nodes.yaml）")

    # 帳簿座標の現ノードスナップ（罠15の基底刷新版・2026-08-16）: OSMのway編集で
    # 変電所重心が数十mずれると、帳簿の固定座標が幽霊頂点になり適用済みエッジが
    # 誰とも繋がらない(OSM再抽出で162本中34箇所を実測)。from-worklist適用時に
    # 端点を最寄りの現ノード(≤500m)へスナップする。決定的なので冪等性は保たれる
    if args.from_worklist:
        node_keys = {}
        for n in nodes:
            node_keys[_k5(n["lat"], n["lon"])] = (n["lat"], n["lon"])
        from collections import defaultdict as _dd
        _grid = _dd(list)
        for k in node_keys:
            _grid[(int(k[0] * 200), int(k[1] * 200))].append(k)

        def _snap(p):
            k = _k5(*p)
            if k in node_keys:
                return p, 0.0
            best = None
            cx, cy = int(p[0] * 200), int(p[1] * 200)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for kk in _grid.get((cx + dx, cy + dy), []):
                        dm = hav_m(tuple(p), kk)
                        if best is None or dm < best[1]:
                            best = (kk, dm)
            if best and best[1] <= 500:
                return list(best[0]), best[1]
            return p, None

        n_snap = 0
        for e in edges:
            for side in ("from_pt", "to_pt"):
                newp, dm = _snap(e[side])
                if dm and dm > 0:
                    e[side] = newp
                    n_snap += 1
        if n_snap:
            print(f"帳簿端点スナップ: {n_snap}箇所を現ノードへ吸着（way編集による重心移動の追従）")

    # 青森箱のregion是正（大間の一般化）: 下北半島(lat<41.6, lon>140.6)にある
    # hokkaidoラベルは region bbox 重複の混入（下北・佐井・大畑・東通・東通村・
    # 岩屋 + junction 群を実測20ノード）。地理的に青森県＝tohoku(east島)が正。
    # 同一座標に tohoku コピーが併存し、島判定を汚染して東側の枝を殺していた。
    if "aomori_box" not in disabled:
        for n in nodes:
            if (n.get("region") == "hokkaido"
                    and n.get("lat") is not None
                    and n["lat"] < 41.6 and n["lon"] > 140.6):
                region_fixes.append({
                    "id": n.get("id"), "name": n.get("name") or "(無名)",
                    "from": "hokkaido", "to": "tohoku",
                    "evidence": "地理(下北半島=青森県)。大間是正(介入#28)と同じbbox混入。"
                                "同一座標にtohokuコピーが併存する完全重複を含む",
                })
    # 松前箱（青森箱の鏡像）: 松前半島(lat>41.35, lon<140.25)の tohoku ラベルは
    # 北海道側の混入（福山変電所=松前・福山城下）。青森の陸地はこの箱に入らない
    # （竜飛崎周辺は lon 140.30-140.35）。
    if "matsumae_box" not in disabled:
        for n in nodes:
            if (n.get("region") == "tohoku"
                    and n.get("lat") is not None
                    and n["lat"] > 41.35 and n["lon"] < 140.25):
                region_fixes.append({
                    "id": n.get("id"), "name": n.get("name") or "(無名)",
                    "from": "tohoku", "to": "hokkaido",
                    "evidence": "地理(松前半島=北海道)。福山=松前の旧称(福山城)。"
                                "青森箱の鏡像のbbox混入",
                })

    # v1 適用済み等の既存 disclosure 枝と重複する候補はスキップ（冪等）
    existing = set()
    for e in bedges:
        if e.get("disclosure") and e.get("a") and e.get("b"):
            existing.add(frozenset((_k5(*e["a"]), _k5(*e["b"]))))
    # OSM実線形吸着(route_disclosure_edges)でスタブ置換されたコードも適用済み扱い。
    # 置換後の正典にはコードが無いため、これを見ないと同じ対を直線で再追加し
    # スタブ+実線形と並列の偽回線を作ってしまう(ad-hoc実行に対する防波堤)。
    # ★ただし「正典に当該スタブが実在する」場合のみ。フレッシュ再構築(build直後)は
    #   スタブも消えているので、ここでスキップするとコードが二度と書かれず
    #   route も置換対象を失い接続自体が消える(2026-08-16の再構築で実害)。
    routed_report = ROOT / "docs/reports/routed_disclosure_edges.json"
    if routed_report.exists():
        rd = json.loads(routed_report.read_text(encoding="utf-8"))
        stub_anchors = {_k5(*e["a"]) for e in bedges if e.get("stub")} | \
                       {_k5(*e["b"]) for e in bedges if e.get("stub")}
        # スタブ0本置換(端点が断片頂点と完全一致)の対はスタブ実在で判定できない。
        # 両端点が正典エッジ頂点として実在=断片が直結済み、も「置換が生きている」証拠
        vert = set()
        for e in bedges:
            vert.add(_k5(*e["a"]))
            vert.add(_k5(*e["b"]))
        for r in rd.get("replaced", []):
            ka, kb = _k5(*r["a"]), _k5(*r["b"])
            if ka in stub_anchors or kb in stub_anchors or (ka in vert and kb in vert):
                existing.add(frozenset((ka, kb)))
    fresh = [e for e in edges
             if frozenset((_k5(*e["from_pt"]), _k5(*e["to_pt"]))) not in existing]

    # region fix を先に適用したコピーで連結性ドライラン
    id_fix = {rf["id"]: rf["to"] for rf in region_fixes}
    nodes_fixed = copy.deepcopy(nodes)
    n_relabel = 0
    for n in nodes_fixed:
        to = id_fix.get(n.get("id"))
        if to and n.get("region") != to:
            n["region"] = to
            n_relabel += 1

    cc0 = compute_connectivity(nodes, bedges)
    off0 = sum(1 for n in nodes if _k5(n["lat"], n["lon"]) not in cc0["main_keys"])
    new_edges = bedges + [{"a": e["from_pt"], "b": e["to_pt"]} for e in fresh]
    cc1 = compute_connectivity(nodes_fixed, new_edges)
    off1 = sum(1 for n in nodes_fixed
               if _k5(n["lat"], n["lon"]) not in cc1["main_keys"])

    joined = [e["from_sub"] for e in fresh
              if _k5(*e["from_pt"]) not in cc0["main_keys"]
              and _k5(*e["from_pt"]) in cc1["main_keys"]]

    from collections import Counter  # noqa: F401 (帳簿マージでも使用)
    by_cls = Counter(e["class"] for e in fresh)
    print(f"worklist v2: 候補 {len(edges)} → 新規 {len(fresh)}（既存重複スキップ {len(edges)-len(fresh)}）")
    print(f"  クラス別: {dict(by_cls)}")
    print(f"  region是正 {n_relabel} ノード / 人間確認送り(review) {len(review)} 件")
    print(f"本系統外ノード: 適用前 {off0} → 適用後 {off1} （{off0-off1} 減）")
    print(f"合流した孤立変電所 {len(joined)}")
    for e in fresh:
        kv = f"{e['kv']:>5.0f}kV" if e.get("kv") else "  —  "
        tag = {"disclosure_line": "線", "disclosure_tap": "岐",
               "disclosure_trafo": "変", "same_site_identity": "同",
               "disclosure_map": "図"}[e["class"]]
        print(f"  [{tag}] {kv} {e['from_sub']:<24} → {e['to_sub']}"
              + (f"  [{e['line']}]" if e.get("line") else "")
              + (f"  ({e['dist_m']}m)" if e.get("dist_m") is not None else ""))

    if not args.update_ledger:
        print("（帳簿は不変。書き換えるには --update-ledger を明示）")
    else:
        # 帳簿は**累積マージ**: 既存エントリを残し、新規(端点対が未登録)だけ足す。
        # 置き換えにすると適用済み分が帳簿から消え、パイプライン --from-worklist の
        # 入力が欠ける（帳簿=全実証接続の正本）。
        prev_wl, prev_rf = [], []
        if OUT.exists():
            prev = json.loads(OUT.read_text(encoding="utf-8"))
            prev_wl = prev.get("worklist", [])
            prev_rf = prev.get("region_fixes", [])
        # 同一性判定は**意味キー**(from_sub,to_sub,class,line)。座標(_k5)キーだと
        # OSM再抽出でノードが数m動いた後の再計算エントリが「別物」扱いになり、
        # 座標微差の重複が帳簿に蓄積→regenで同一接続が2本適用される
        # (2026-08-17 実害25組: 尼崎線・戸山線・大山日田線ほか。issue #42)。
        # 既登録の意味キーは座標を**新値に更新**(ノード移動への追従)。
        def _mkey(e):
            return (e.get("from_sub"), e.get("to_sub"), e.get("class"),
                    str(e.get("line")))
        prev_by_key = {}
        for e in prev_wl:
            prev_by_key.setdefault(_mkey(e), e)
        n_coord_upd = 0
        merged_wl = list(prev_by_key.values())
        for e in edges:
            k = _mkey(e)
            if k in prev_by_key:
                old = prev_by_key[k]
                if (old["from_pt"], old["to_pt"]) != (e["from_pt"], e["to_pt"]):
                    old["from_pt"], old["to_pt"] = e["from_pt"], e["to_pt"]
                    n_coord_upd += 1
            else:
                merged_wl.append(e)
                prev_by_key[k] = e
        if n_coord_upd:
            print(f"帳簿座標更新: {n_coord_upd}件（ノード移動への追従）")
        have_rf = {(r.get("id"), r.get("to")) for r in prev_rf}
        merged_rf = prev_rf + [r for r in region_fixes
                               if (r.get("id"), r.get("to")) not in have_rf]
        n_new_wl = len(merged_wl) - len(prev_wl)
        n_new_rf = len(merged_rf) - len(prev_rf)
        print(f"帳簿マージ: worklist +{n_new_wl}（計{len(merged_wl)}）"
              f" region_fixes +{n_new_rf}（計{len(merged_rf)}）")
        fresh = merged_wl               # 帳簿に書くのは累積の全量
        region_fixes = merged_rf
        by_cls = Counter(e["class"] for e in fresh)
        OUT.write_text(json.dumps({
        "note": ("実証接続 v2。公表線路/分岐タップ/変圧器実証（東北NW系統情報公表）と"
                 "同一敷地同定（跨region二重登録）。生の潮流値・R/X等は非収録。"
                 "--disable <class> で証拠クラス単位の無効化、--revert で全戻し。"),
        "classes": {
            "disclosure_line": "東北NW潮流実績CSV 潮流正方向（3年分・kikan+local01-07）",
            "disclosure_tap": "公表from-toの「◯◯線分岐」経由タップ",
            "disclosure_trafo": "変圧器潮流実績CSV（変電所名×一次/二次電圧）",
            "same_site_identity": "同名・同電圧・≤300mの本系統/孤立ペア＝同一変電所",
            "disclosure_map": "局所系統構成図PDF(転載禁止・external内)の人手判読・座標照合済のみ",
        },
        "map_reading_notes": [
            "東通変電所—162C線—北東岸の他社変電所(発電所310605連系)が図にあるが、"
            "AGJ候補が岩屋変電所(41.3795,141.4030)と東通村変電所(41.4106,141.4421)の"
            "2サイトあり判別不能→未追加。発電所番号⇔名称の対応表は非公表と確認"
            "(ju-sohai_01の凡例のみ・2026-08-15)=公表の範囲では確定不可",
            "孤立側の大間町変電所(41.4652,140.8900)は図の大間●(=main側_2〜_5クラスタ)と"
            "対応しない。佐井変電所の480m隣にあり素性不明→未解決のまま",
            "【負の証拠・目視確認済】新潟市街の青山一丁目/ときめき東一丁目/平五丁目/渋川、"
            "盛岡の門前寺、南相馬の原町区大谷は、公表66kV系統図(local02/06/07)にも"
            "潮流実績CSVにも**名前付き変電所として不在**(新潟市街詳細円は目視でも確認・"
            "該当位置には無名の他社変電所●のみ)→東北NW自社の66kV系統変電所でない"
            "(他社受電点=JR等 or 配電<66kV)。A判定の降格候補として人間確認待ち",
            "由利本荘市変電所/鳥海町下直根変電所(500m隣接の同一サイトペア)は、秋田66kV図の"
            "由利変電所配下・鳥海町方面66kV網(371系線)に対応する見込みだが、当該網の変電所名が"
            "番号のみ公表(3702〜3708)のため確定不可→未追加",
            "餅田変電所154kV(40.28,140.52=北秋田)は基幹図(275/154kV)のテキスト層に不在→要精査",
            "塩原2号/3号配電塔・黒磯変電所(栃木=TEPCO領)はtohoku/tokyo両コピーとも孤立。"
            "東北の公表対象外でTEPCO側CSV名にも無し(配電塔)→TEPCO詳細源での解決待ち",
        ],
        "dryrun_off_main_before": off0, "dryrun_off_main_after": off1,
        "n_new": len(fresh), "by_class": dict(by_cls),
        "region_fixes": region_fixes, "joined_subs": joined,
        "review_300_800m": review,
        "worklist": fresh,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n保存: {OUT.relative_to(ROOT)}")

    if args.write or args.out:
        if not fresh and not n_relabel:
            print("適用する新規なし")
            return 0
        if args.write and not BAK.exists():
            BAK.write_text(BUILT.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"バックアップ作成: {BAK.name}")
        maink = cc1["main_keys"]
        for n in nodes_fixed:
            n["main"] = _k5(n["lat"], n["lon"]) in maink
        applied = list(bedges)
        for e in fresh:
            ka, kb = tuple(e["from_pt"]), tuple(e["to_pt"])
            applied.append({
                "path": [list(e["from_pt"]), list(e["to_pt"])],
                "a": list(e["from_pt"]), "b": list(e["to_pt"]),
                "main": (ka in maink and kb in maink), "par": 1,
                "kv": e.get("kv") or 0,
                "name": e.get("line") or {"disclosure_trafo": "変圧器タイ(公表実証)",
                                          "same_site_identity": "同一敷地タイ(同定)",
                                          "disclosure_tap": "分岐タップ(公表)",
                                          }.get(e["class"], "公表接続"),
                "disclosure": e["evidence"], "conn_class": e["class"],
                **({"trafo": True} if e.get("trafo") else {}),
                **({"same_site": True} if e.get("same_site") else {}),
            })
        built["nodes"] = nodes_fixed
        built["edges"] = applied
        st = built.setdefault("stats", {})
        st["main_size"] = sum(1 for n in nodes_fixed if n["main"])
        st["n_island_nodes"] = sum(1 for n in nodes_fixed if not n["main"])
        st["n_components"] = sum(cc1["meta"]["components"].values())
        built.setdefault("disclosure_worklist_applied_v2", {}).update({
            "worklist": str(OUT.relative_to(ROOT)), "n_conn": len(fresh),
            "by_class": dict(by_cls), "region_fix_nodes": n_relabel,
            "off_main": st["n_island_nodes"],
            "note": "実証接続v2。--revert(apply_disclosure_v2)で戻せる。",
        })
        blob = json.dumps(built, ensure_ascii=False, separators=(",", ":"))
        if args.out:
            Path(args.out).write_text(blob, encoding="utf-8")
            print(f"適用結果を書き出し（正典は不変）: {args.out} "
                  f"（本系統外→{st['n_island_nodes']}）")
        if args.write:
            BUILT.write_text(blob, encoding="utf-8")
            print(f"★正典適用: all.json 更新（本系統外→{st['n_island_nodes']}）。"
                  f"--revert で戻せる。バックアップ={BAK.name}")
    else:
        print("（正典は不変。適用するなら --write / 戻すなら --revert）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
