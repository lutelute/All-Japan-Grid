"""OCCTO の潮流マップの点線(モデルの線の形が無いところ)を、OSM と地理院の送電線の形で埋める台帳を作る。

点線は 2 種類ある。両端の変電所を結んだだけの線路(点線だけの線路)と、モデルの線の切れ目をつないだ点線。
どちらも「モデルの線と照合できなかった」だけで、送電線が無いという意味ではない(2026-11-07 オーナー指摘)。
連系線(config/occto_interconnections.yaml)も、端 → 変換所 → 端 の区間ごとに OSM の線(直流の線・海底ケーブルを含む)の
形を当てる(2026-11-08 オーナー「直流や変換所や連系線は線と点が無いのか」「地形に合っていないから変に見える」)。

手順:
1. 形を当てる前の線路の一覧から対象を出す:
     python3 scripts/export_occto_today.py lines --crosswalk <照合> --no-shapes --out /tmp/lines_noshape.json
     python3 scripts/build_occto_line_shapes.py targets /tmp/lines_noshape.json targets.json
2. OSM(Geofabrik の 2026-11-05 の抽出を tw_japan_t0.json にしたもの)と照らす: scripts/match_occto_osm.py → out_osm.json
3. OSM で見つからなかったものを地理院の送電線で照らす:
     python3 scripts/build_occto_line_shapes.py remaining targets.json out_osm.json targets_gsi.json
     python3 scripts/match_occto_gsi.py targets_gsi.json out_gsi.json
4. まとめる: python3 scripts/build_occto_line_shapes.py merge targets.json out_osm.json out_gsi.json
   → data/reference/occto_line_shapes.json。export_occto_today.py lines がこれを読んで点線を形に替える。

形は地図に描くためだけに使う(モデルの正典・照合は変えない)。
出典: © OpenStreetMap contributors(ODbL 1.0)・国土地理院 ベクトルタイル(地理院地図Vector、送電線 = 地物コード 8202)。
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from export_occto_today import JST, simplify  # noqa: E402

OUT = ROOT / "data" / "reference" / "occto_line_shapes.json"
TOL = 0.0005     # 形の簡略化の許容(度、約 50 m)


def targets(lines_p: str, out_p: str):
    d = json.loads(Path(lines_p).read_text(encoding="utf-8"))
    out = []
    for x in d["lines"]:
        if not x["p"] and x["j"]:
            out.append({"id": x["id"], "kind": "line", "n": x["n"], "kv": x["kv"], "s": [x["j"][0][0], x["j"][-1][-1]]})
        elif x["p"]:
            out += [{"id": x["id"], "kind": "gap", "gap": k, "n": x["n"], "kv": x["kv"], "s": seg} for k, seg in enumerate(x["j"])]
    for ic in d.get("ics") or []:      # 連系線の区間(電圧と OSM の線の名前は台帳の osm)
        kvs = ic["osm"]["kv"] or [0]
        out += [{"id": "ic|" + ic["n"], "kind": "ic", "gap": k, "n": ic["n"], "kv": kvs[0], "kvs": kvs,
                 "names": ic["osm"]["names"], "s": [a, b]} for k, (a, b) in enumerate(zip(ic["w"], ic["w"][1:]))]
    Path(out_p).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    n = lambda k: sum(t["kind"] == k for t in out)
    print(f"対象 {len(out)}(点線だけの線路 {n('line')}・切れ目 {n('gap')}・連系線の区間 {n('ic')})")


def remaining(targets_p: str, osm_p: str, out_p: str):
    found = {(r["id"], r["kind"], r.get("gap")) for r in json.loads(Path(osm_p).read_text(encoding="utf-8"))
             if r["found"] or r.get("why", "").startswith("短い")}
    rest = [t for t in json.loads(Path(targets_p).read_text(encoding="utf-8"))
            if t["kind"] == "line" and (t["id"], t["kind"], t.get("gap")) not in found]
    Path(out_p).write_text(json.dumps(rest, ensure_ascii=False), encoding="utf-8")
    print(f"OSM で見つからない点線だけの線路 {len(rest)}")


def merge(targets_p: str, osm_p: str, gsi_p: str, out_p: str = str(OUT)):
    ends = {(t["id"], t["kind"], t.get("gap")): t["s"] for t in json.loads(Path(targets_p).read_text(encoding="utf-8"))}
    items, tg = [], {}
    for src, p in (("osm", osm_p), ("gsi", gsi_p)):
        for r in json.loads(Path(p).read_text(encoding="utf-8")):
            if not r.get("found"):
                continue
            # OSM の形は、道の半分以上が電圧か名前の合う線で、way の切れ目を飛んだ長さが 3 割以下のものだけ採る
            if src == "osm" and (max(r["kv_frac"], r["named_frac"]) < 0.5 or r["jump_km"] > max(0.5, 0.3 * r["length_km"])):
                continue
            k = (r["id"], r["kind"], r.get("gap"))
            if k in tg:
                continue
            it = {"id": r["id"], "kind": r["kind"], "src": src, "length_km": r["length_km"], "straight_km": r["straight_km"],
                  "coords": [[round(x, 4), round(y, 4)] for x, y in simplify([tuple(c) for c in r["coords"]], TOL)]}
            it["ends"] = ends[k]       # 点線の両端(切れ目はこの 2 点で線路の中の点線を引く)
            if src == "osm":
                it.update(named_frac=r["named_frac"], kv_frac=r["kv_frac"], names=r["names"][:6], ways=r["ways"][:40])
            tg[k] = it
            items.append(it)
    out = {"made": dt.datetime.now(JST).isoformat(timespec="minutes"),
           "source": "© OpenStreetMap contributors(ODbL 1.0、Geofabrik japan 2026-11-05)・国土地理院 ベクトルタイル(地理院地図Vector、送電線 8202)",
           "method": "scripts/build_occto_line_shapes.py(照らし方は scripts/match_occto_osm.py・match_occto_gsi.py)",
           "items": items}
    Path(out_p).write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    n = lambda s, k: sum(1 for i in items if i["src"] == s and i["kind"] == k)
    print(f"{out_p}: 点線だけの線路 OSM {n('osm', 'line')}・地理院 {n('gsi', 'line')}、切れ目 OSM {n('osm', 'gap')}・地理院 {n('gsi', 'gap')}、"
          f"連系線の区間 OSM {n('osm', 'ic')}")


if __name__ == "__main__":
    cmd, *args = sys.argv[1:]
    {"targets": targets, "remaining": remaining, "merge": merge}[cmd](*args)
