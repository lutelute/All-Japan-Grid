#!/usr/bin/env python3
"""連結性監査で出た「孤立変電所」を A/繋ぐべき・B/除外・?/不明 に振り分ける。

連結性監査(scripts/build_connectivity_audit.py)は built/all.json から
「本系統に載らない変電所(isolated_sub)」を705件抽出する。それを2026-06-16 の
島変電所調査(docs/reports/island_substation_research_2026-06-16.md +
island_calibration_2026-06-16.json)の判定基準で分類し、**「本当に繋ぐべき赤」と
「繋がなくて正しい赤(鉄道/配電/自家用)」を分離**して直す優先順位を出す。

判定の優先順（研究と同じ基準・[[project_agj_island_classify]]）:
  1. 上位60件の Web検証済み判定(.md 表)があればそれを最優先(A/B)
  2. 鉄道き電(operator/名称が鉄道系, calibration operator_kind) → B(別系統・正しく孤立)
  3. 公称 ≥66kV → A(要連系＝繋ぐべき。配電でもHV方針でA)
  4. kv=0/不明 → ?(配電寄りと推定・要個別確認)

出力:
  data/external/system_disclosure/viz/audit_nodes.geojson を上書きし、
    isolated_sub ノードに verdict(A/B/?)を付ける(ビューアが色分けに使う)
  docs/reports/isolated_sub_triage_<date は付けず>.json は作らない(散文回避)。
  代わりに標準出力に要約を出す(検算しやすいスクリプト方針)。
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILT = ROOT / "docs" / "data" / "built" / "all.json"
CALIB = ROOT / "docs" / "reports" / "island_calibration_2026-06-16.json"
RESEARCH_MD = ROOT / "docs" / "reports" / "island_substation_research_2026-06-16.md"
VIZ = ROOT / "data" / "external" / "system_disclosure" / "viz"
OVERRIDES = ROOT / "config" / "isolated_verdict_overrides.yaml"


def load_overrides() -> tuple[dict, int]:
    """(name,region)→verdict の承認済み上書きと、未承認提案の数を返す。"""
    if not OVERRIDES.exists():
        return {}, 0
    import yaml
    d = yaml.safe_load(OVERRIDES.read_text(encoding="utf-8")) or {}
    approved, proposed = {}, 0
    for o in d.get("overrides", []):
        if o.get("approved"):
            approved[(o.get("name"), o.get("region"))] = str(o.get("verdict"))
        else:
            proposed += 1
    return approved, proposed

RAIL_WORDS = ("鉄道", "電鉄", "ＪＲ", "JR", "軌道", "き電", "饋電", "traction", "Railway")
# 企業自家用の明確なマーカー(工場・製造業・ブランド名)。これらは需要家側の
# 私設変電所で「送電網に繋ぐべきA」ではなく別系統B。過検出を避け明確語のみ。
PRIVATE_WORDS = ("製作所", "製鉄", "製鋼", "製紙", "化学", "工場", "製造", "精機", "チエイン",
                 "セメント", "硝子", "ガラス", "電線", "アルミ", "金属", "製薬", "食品",
                 "株式会社", "(株)", "㈱", "ＮＥＣ", "NEC", "東芝", "日立", "三菱", "住友",
                 "新日鐵", "ＪＦＥ", "JFE", "神戸製鋼", "パナソニック", "キヤノン", "トヨタ")


def norm_name(s: str) -> str:
    return re.sub(r"[\s　_]", "", str(s or "")).replace("変電所", "").replace("き電区分所", "")


def is_railway(name: str, operator: str, operator_kind: str) -> bool:
    blob = f"{name} {operator} {operator_kind}"
    return any(w in blob for w in RAIL_WORDS) or (operator_kind or "").lower() == "railway"


def is_private(name: str, operator: str) -> bool:
    blob = f"{name} {operator}"
    return any(w in blob for w in PRIVATE_WORDS)


def load_verified() -> dict:
    """.md の上位60件表から name→verdict(A/B) を取る(Web検証済みの権威)。"""
    out = {}
    if not RESEARCH_MD.exists():
        return out
    for ln in RESEARCH_MD.read_text(encoding="utf-8").splitlines():
        if not ln.startswith("|"):
            continue
        c = [x.strip() for x in ln.strip().strip("|").split("|")]
        if len(c) < 8 or not c[0].isdigit():
            continue
        v = c[7].strip()[:1].upper()
        if v in ("A", "B"):
            out[norm_name(c[2])] = v
    return out


def load_calib_index() -> dict:
    """calibration islands を 座標キー(round4)→{operator,operator_kind,name} で索引。"""
    idx = {}
    if not CALIB.exists():
        return idx
    d = json.loads(CALIB.read_text(encoding="utf-8"))
    for x in d.get("islands", []):
        lat, lon = x.get("lat"), x.get("lon")
        if lat is None or lon is None:
            continue
        idx[(round(lat, 4), round(lon, 4))] = {
            "operator": x.get("operator") or "",
            "operator_kind": x.get("operator_kind") or "",
            "name": x.get("name") or "",
        }
    return idx


def main() -> int:
    if not BUILT.exists():
        print(f"{BUILT} が無い")
        return 1
    verified = load_verified()
    calib = load_calib_index()

    # 母集合は監査 geojson の isolated_sub を単一の真実とする（あれば）。
    # built の main フラグは古い計算（島判定バグ修正前の --write）で焼かれている
    # ことがあり、build_connectivity_audit --recompute の結果とズレるため。
    audit_f = VIZ / "audit_nodes.geojson"
    subs = None
    if audit_f.exists():
        feats = json.loads(audit_f.read_text(encoding="utf-8"))["features"]
        subs = [{"name": f["properties"].get("name"),
                 "kv": f["properties"].get("kv"),
                 "lat": f["geometry"]["coordinates"][1],
                 "lon": f["geometry"]["coordinates"][0],
                 "id": f["properties"].get("id"),
                 "region": f["properties"].get("region")}
                for f in feats if f["properties"].get("cls") == "isolated_sub"]
        print(f"母集合: audit_nodes.geojson の isolated_sub {len(subs)} 件"
              "（built の main フラグは不使用）")
    if subs is None:
        nodes = json.loads(BUILT.read_text(encoding="utf-8")).get("nodes", [])
        subs = [n for n in nodes if n.get("sub") and not n.get("main")]

    overrides, n_proposed = load_overrides()
    verdicts = {}   # id -> A/B/?
    reason = Counter()
    by_region = {}
    a_list = []
    for n in subs:
        name = n.get("name") or ""
        kv = n.get("kv") or 0
        lat, lon = n.get("lat"), n.get("lon")
        c = calib.get((round(lat, 4), round(lon, 4)), {}) if lat is not None else {}
        op, opk, cname = c.get("operator", ""), c.get("operator_kind", ""), c.get("name", "")
        # 1) Web検証済み
        v = verified.get(norm_name(name)) or verified.get(norm_name(cname))
        if v:
            reason["verified"] += 1
        # 2) 鉄道
        elif is_railway(name or cname, op, opk):
            v = "B"; reason["railway→B"] += 1
        # 2b) 企業自家用(工場・製造業)は繋ぐべきAでなく別系統B
        elif is_private(name or cname, op):
            v = "B"; reason["private→B"] += 1
        # 3) 高圧
        elif kv >= 66:
            v = "A"; reason["kv>=66→A"] += 1
        # 4) 不明
        else:
            v = "?"; reason["kv0→?"] += 1
        # 0) 承認済みオーバーライド（config/isolated_verdict_overrides.yaml）が最優先
        ov = overrides.get((name, n.get("region")))
        if ov:
            v = ov; reason["override"] += 1
        verdicts[n.get("id")] = v
        by_region.setdefault(n.get("region"), Counter())[v] += 1
        if v == "A":
            a_list.append((kv, n.get("region"), name, round(lat, 4), round(lon, 4)))

    total = Counter(verdicts.values())
    print(f"孤立変電所 {len(subs)} 件の振り分け:")
    print(f"  A 繋ぐべき   {total['A']:4}  (直す優先。うち高圧ほど優先)")
    print(f"  B 除外(正)   {total['B']:4}  (鉄道/別系統＝繋がなくて正しい赤)")
    print(f"  ? 不明       {total['?']:4}  (配電寄り推定・要個別確認)")
    print(f"  判定根拠: {dict(reason)}")
    if n_proposed:
        print(f"  ⚠ 未承認の上書き提案 {n_proposed} 件"
              f"（config/isolated_verdict_overrides.yaml で approved: true にすると適用）")
    print("\n地域別 A/B/?:")
    for r, c in sorted(by_region.items(), key=lambda kv: -kv[1]["A"]):
        print(f"  {r:9} A={c['A']:3} B={c['B']:3} ?={c['?']:3}")
    print("\n繋ぐべき A の高圧トップ20(直す最優先):")
    for kv, r, name, la, lo in sorted(a_list, reverse=True)[:20]:
        print(f"  {kv:>5.0f}kV {r:9} {name}  ({la},{lo})")

    # ビューア用: audit_nodes.geojson の isolated_sub に verdict を付ける
    nf = VIZ / "audit_nodes.geojson"
    if nf.exists():
        gj = json.loads(nf.read_text(encoding="utf-8"))
        for f in gj["features"]:
            if f["properties"].get("cls") == "isolated_sub":
                f["properties"]["verdict"] = verdicts.get(f["properties"].get("id"), "?")
        nf.write_text(json.dumps(gj, ensure_ascii=False, allow_nan=False,
                                 separators=(",", ":")), encoding="utf-8")
        print(f"\naudit_nodes.geojson に verdict を付与 → {nf.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
