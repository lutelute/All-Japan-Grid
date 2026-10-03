#!/usr/bin/env python3
"""観測潮流(公表実績の年統計)とモデルの潮流を、線ごとに突き合わせる(潮流マップの「観測と比べる」)。

    PYTHONPATH=. python scripts/export_obs_compare.py            # docs/data/flow_map/obs_compare.json
    PYTHONPATH=. python scripts/export_obs_compare.py --summary  # 書き出さずに照合の内訳だけ

観測(observed)と計算(derived)は混ぜない(docs/OBSERVED_VS_DERIVED.md)。このスクリプトは
どちらの原本も書き換えず、突き合わせの**第三のファイル**を作る。列は *_obs / *_uc / *_act と
ratio_* に分け、素の名前は作らない。

照合(観測の線 → モデルの線の経路):
  1. 観測の両端の変電所名を、インピーダンス照合と同じ解決器(match_impedance_to_model.resolve)で
     モデルの変電所の座標に解決する(exact → paren → suffix → contains → national の順に弱い)
  2. その座標から 3 km 以内で、観測の電圧に合うモデル母線を端点にする
  3. 同じ電圧の線だけをたどって両端の最短経路を求める。経路長が直線距離の 3 倍(+10 km)を
     超えるもの、40 区間を超えるものは別の線を拾っている恐れが高いので捨てる
  4. 経路上の線名に観測の線名が入っていれば A(名前と両端)、入っていなければ B(両端のみ)
  5. 片端しか解決できない(東京の公表は計測した変電所だけ・相手が「発電所」と伏せてある・
     鉄塔番号の分岐点)ときは C(片端+線名): その変電所につながる同じ電圧の線のうち、線名が
     一致するものがちょうど 1 方向に限られるときだけ採る。片端では符号の決まりが確かめられない
     ので、C は大きさ(p95)だけを比べ、向きは判定しない
  6. モデル側の値は、観測の起点側の最初の区間(平行線は合算)の潮流を、観測の from→to の向きに
     揃えて使う。観測が回線ごと(「1号線」)でモデルが複数回線をまとめているときは回線数で按分する

比べる統計: 平均(符号つき)・p95(絶対値)・最大(絶対値)。観測は 2024 年度の 1 時間値 8,760 点、
モデルは UC(fy2023)の代表日 24 時刻と、実績需要で解いた日別断面の全時刻。**同じ時刻どうしの
比較ではなく分布の規模の比較**(観測の生の時系列は公開できないため年統計を使う)。

公開範囲: 観測側は年統計 3 値だけ(2026-08-18 オーナー判断で公開可・obs_local.json と同じ)。
生の時系列(30 分値・1 時間値)は読まない・書かない。
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import warnings
from collections import defaultdict
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FM = ROOT / "docs" / "data" / "flow_map"
OBS = ROOT / "data/external/system_disclosure/normalized/line_observations.csv"
ISLAND_OF = {"hokkaido": "hokkaido", "tohoku": "east", "tokyo": "east", "chubu": "west",
             "hokuriku": "west", "kansai": "west", "chugoku": "west", "shikoku": "west",
             "kyushu": "west", "okinawa": "okinawa"}
FREQ = {"hokkaido": 50, "east": 50, "west": 60, "okinawa": 60}
SNAP_KM = 3.0
MAX_DETOUR, DETOUR_SLACK_KM, MAX_HOPS = 3.0, 10.0, 40
# 線名の裏付けが無い経路(B)は、別の線をたどった恐れが高いので短い経路だけ採る(標本の目視で
# 154 kV と誤記された 500 kV 幹線が 154 kV の別ルートを 100 km 超たどっていた 2026-10-03)
B_MAX_HOPS, B_DETOUR, B_SLACK_KM = 3, 1.6, 3.0


def hav_km(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def stats(xs: list[float]) -> dict | None:
    xs = [x for x in xs if x is not None]
    if len(xs) < 3:
        return None
    ab = sorted(abs(x) for x in xs)
    p95 = ab[min(len(ab) - 1, int(round(0.95 * (len(ab) - 1))))]
    return {"mean": round(sum(xs) / len(xs), 1), "p95": round(p95, 1), "max": round(ab[-1], 1),
            "n": len(xs)}


def clean_station(s: str) -> str:
    """「'能代変電所」「阿波根変電所/真壁変電所」「山崎開閉所（開4）」→ 照合しやすい 1 つの名前に。"""
    import re
    s = str(s or "").strip().lstrip("'’`").strip()
    s = re.split(r"[/／\n→]", s)[0]
    return re.sub(r"[（(][^）)]*[）)]", "", s).strip()


def line_base(name: str) -> tuple[str, int | None]:
    """観測の線名 → (回線の表記を除いた名前, 観測が表す回線数)。「奥秩父線1･2L」→(奥秩父線, 2)。

    回線の表記は「・」を消す前に読む(norm は「・」を消すので「1･2L」が「12L」= 1 回線に化ける)。
    """
    import re
    import unicodedata
    n = re.sub(r"[（(][^）)]*[）)]", "", str(name or "").lstrip("'’`"))  # 「関西幹線（犬山～新奈良）」
    n = unicodedata.normalize("NFKC", n).strip()
    if re.search(r"線[／/;・]", n):          # 「阿波根線／真壁線」→ 最初の線
        n = re.split(r"[／/;・]", n)[0]
    m = re.search(r"((?:\d+[・･,、]?)+)L$", n)
    if m:
        return norm(n[:m.start()]), len(re.findall(r"\d+", m.group(1)))
    m = re.search(r"(\d+)号線$", n)
    if m:
        return norm(n[:m.start()]) + "線", 1
    return norm(n), None


def station_stem(s: str) -> str:
    """「天童変電所」「新改SS」「奥秩父(変)」→ 天童 / 新改 / 奥秩父(線名との突き合わせ用)。"""
    import re
    n = norm(clean_station(s))
    return re.sub(r"(変電所|開閉所|変換所|発電所|分岐所|SS|変)$", "", n)


def model_tokens(name: str) -> list[str]:
    import re
    return [norm(t) for t in re.split(r"\s*/\s*|;", str(name or "")) if t.strip()]


def kv_ok(model_kv: float, obs_kv: float) -> bool:
    return obs_kv > 0 and abs(model_kv - obs_kv) <= 0.12 * obs_kv


def load_obs() -> list[dict]:
    rows = []
    with OBS.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                mean = float(r["flow_mean_mw"])
                p95 = float(r["flow_p95_abs_mw"])
                kv = float(r["voltage_kv"] or "nan")
            except (ValueError, KeyError):
                continue
            if mean != mean or p95 != p95:
                continue
            mx = float(r["flow_max_abs_mw"]) if r.get("flow_max_abs_mw") not in ("", None) else None
            rows.append({"util": r["utility"], "name": r["name"], "kv": kv,
                         "from": r["from_node"], "to": r["to_node"], "n": int(float(r["n_obs"] or 0)),
                         "obs": {"mean": round(mean, 1), "p95": round(p95, 1),
                                 "max": None if mx is None or mx != mx else round(mx, 1)}})
    return rows


def island_graph(island: str, built: dict):
    """島の計算ネットワークから、母線の座標・電圧と、線(鍵つき)のグラフを作る。"""
    import networkx as nx
    from scripts.run_full_powerflow_from_db import build_island_net
    from src.powerflow.line_keys import line_keys
    net, _, _ = build_island_net(island, built["nodes"], built["edges"], FREQ[island], {})
    keys = line_keys(net)
    pos, vn = {}, net.bus["vn_kv"].to_dict()
    for b, g in net.bus["geo"].items():
        try:
            lon, lat = json.loads(g)["coordinates"][:2]
            pos[int(b)] = (float(lat), float(lon))
        except Exception:  # noqa: BLE001
            pass
    g = nx.Graph()
    for li in net.line.index[net.line.in_service]:
        fb, tb = int(net.line.at[li, "from_bus"]), int(net.line.at[li, "to_bus"])
        k = keys.get(li, "")
        if not k or fb not in pos or tb not in pos:
            continue
        w = float(net.line.at[li, "length_km"] or hav_km(pos[fb], pos[tb]) or 0.01)
        par = int(net.line.at[li, "parallel"] or 1)
        nm = str(net.line.at[li, "name"] or "")
        # 平行線は 1 本の辺にまとめ、各線の鍵・向き・回線数は全部持つ(潮流は合算して読む)
        if g.has_edge(fb, tb):
            d = g[fb][tb]
            d["lines"].append((k, fb, par))
            d["w"] = min(d["w"], w)
            d["names"].update(model_tokens(nm))
            continue
        g.add_edge(fb, tb, w=w, lines=[(k, fb, par)], names=set(model_tokens(nm)),
                   kv=float(vn.get(fb, 0)))
    return g, pos, vn


CELL = 0.05  # 度(約 5 km)。3 km 以内を探すので周囲 3×3 マスで足りる


def grid_index(pos: dict) -> dict:
    gi = defaultdict(list)
    for b, (la, lo) in pos.items():
        gi[(int(la // CELL), int(lo // CELL))].append(b)
    return gi


def snap(pt, pos, vn, kv, gi) -> list[int]:
    ci, cj = int(pt[0] // CELL), int(pt[1] // CELL)
    out = []
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            for b in gi.get((ci + di, cj + dj), ()):
                if kv_ok(float(vn.get(b, 0)), kv):
                    d = hav_km(pt, pos[b])
                    if d <= SNAP_KM:
                        out.append((d, b))
    return [b for _, b in sorted(out)][:3]


def norm(s: str) -> str:
    import re
    import unicodedata
    return re.sub(r"[\s・()（）]", "", unicodedata.normalize("NFKC", str(s or "")))


def _seg(g, u, v) -> list[list]:
    """辺 u→v を通るときの各線の [鍵, 向き(+1=その線の from→to と同じ), 回線数]。"""
    return [[k, 1 if fb == u else -1, par] for k, fb, par in g[u][v]["lines"]]


def match_all(obs: list[dict], built: dict) -> tuple[list[dict], dict]:
    import networkx as nx
    from scripts.match_impedance_to_model import load_model, resolve
    by_isl = defaultdict(list)
    for o in obs:
        if o["util"] in ISLAND_OF:
            by_isl[ISLAND_OF[o["util"]]].append(o)
    out, tally = [], defaultdict(lambda: defaultdict(int))
    idx_cache: dict = {}
    for island, rows in by_isl.items():
        print(f"[{island}] 観測 {len(rows)} 本 — ネットワークを組み立て中", flush=True)
        g, pos, vn = island_graph(island, built)
        gi = grid_index(pos)
        subs: dict = {}      # 観測の電圧 → その電圧の線だけのグラフ(使い回す)
        res_cache: dict = {}

        def res(util, name):
            key = (util, name)
            if key not in res_cache:
                idx = idx_cache.get(util) or idx_cache.setdefault(util, load_model(util)[0])
                nm = clean_station(name)
                res_cache[key] = resolve(nm, idx) if nm else ("empty", None)
            return res_cache[key]

        for o in rows:
            t = tally[o["util"]]
            t["observed"] += 1
            base, n_circ = line_base(o["name"])
            sub = subs.get(o["kv"])
            if sub is None:
                sub = subs[o["kv"]] = g.edge_subgraph(
                    [(u, v) for u, v, d in g.edges(data=True) if kv_ok(d["kv"], o["kv"])])
            (lv_a, na), (lv_b, nb) = res(o["util"], o["from"]), res(o["util"], o["to"])
            pa = (float(na["lat"]), float(na["lon"])) if na else None
            pb = (float(nb["lat"]), float(nb["lon"])) if nb else None
            ca = snap(pa, pos, vn, o["kv"], gi) if pa else []
            cb = snap(pb, pos, vn, o["kv"], gi) if pb else []
            rec = None
            # --- A/B: 両端が解決したら同じ電圧の最短経路 ---
            if ca and cb:
                best = None
                for x in ca:
                    for y in cb:
                        if x == y or x not in sub or y not in sub:
                            continue
                        try:
                            L, path = nx.single_source_dijkstra(sub, x, y, weight="w")
                        except nx.NetworkXNoPath:
                            continue
                        if best is None or L < best[0]:
                            best = (L, path)
                if best is not None:
                    L, path = best
                    straight = hav_km(pa, pb)
                    if L <= MAX_DETOUR * straight + DETOUR_SLACK_KM and len(path) - 1 <= MAX_HOPS:
                        segs = [_seg(g, u, v) for u, v in zip(path, path[1:])]
                        sa, sb = station_stem(o["from"]), station_stem(o["to"])

                        def named(tk):  # 観測の線名か、両端の変電所名で付いたモデルの線名
                            return bool((base and (tk == base or tk.startswith(base)))
                                        or (len(sa) >= 2 and len(sb) >= 2 and sa in tk and sb in tk))
                        n_named = sum(1 for u, v in zip(path, path[1:])
                                      if any(named(tk) for tk in g[u][v]["names"]))
                        conf = "A" if n_named * 2 >= len(segs) else "B"
                        if conf == "B" and (len(segs) > B_MAX_HOPS
                                            or L > B_DETOUR * straight + B_SLACK_KM):
                            t["b_rejected_long"] += 1
                        else:
                            rec = {"conf": conf, "path_km": round(L, 1),
                                   "straight_km": round(straight, 1), "segs": segs}
                    else:
                        t["detour_rejected"] += 1
            # --- C: 片端+線名(東京の片端公表・相手が「発電所」・鉄塔番号の分岐点) ---
            if rec is None and base and (ca or cb):
                st = ca or cb
                hits = {}
                for x in st:
                    if x not in sub:
                        continue
                    for y in sub.neighbors(x):
                        if any(tk == base or tk.startswith(base) for tk in g[x][y]["names"]):
                            hits[y] = (x, y)
                if len(hits) == 1:
                    x, y = next(iter(hits.values()))
                    # 起点側(from)が解決していれば x は from。to 側しか無ければ向きを反転して読む
                    rec = {"conf": "C", "segs": [_seg(g, x, y)] if ca else [_seg(g, y, x)],
                           "single_ended": True}
                elif len(hits) > 1:
                    t["ambiguous_name"] += 1
            if rec is None:
                if not (na or nb):
                    t["unresolved_station"] += 1
                elif not (ca or cb):
                    t["no_bus_at_voltage"] += 1
                else:
                    t["no_path_or_name"] += 1
                continue
            t[f"matched_{rec['conf']}"] += 1
            out.append({**o, "island": island, "line_base": base, "n_circ_obs": n_circ, **rec})
    return out, {u: dict(v) for u, v in tally.items()}


def model_series(island: str) -> tuple[dict, dict]:
    """鍵 → UC 24 時刻の潮流 / 鍵 → 実績需要で解いた日別断面の全時刻の潮流。"""
    base = json.loads((FM / f"flows_{island}.geojson").read_text())
    gk = [f["properties"].get("k", "") for f in base["features"]]
    uc = {f["properties"].get("k"): f["properties"].get("p24") for f in base["features"]}
    sig = json.loads((FM / "meta.json").read_text()).get(island, {}).get("sig")
    act: dict[str, list] = defaultdict(list)
    for p in sorted((FM / "days").glob("2*.json")):
        d = json.loads(p.read_text())
        D = (d.get("islands") or {}).get(island)
        if not D or D.get("base_sig") != sig:
            continue
        # 空欄(None)も残して全線の長さを揃える(平行線を時刻ごとに合算するため)
        for k, row in zip(gk, D["p"]):
            if k:
                act[k].extend(row if row else [None] * 24)
    return uc, act


def compare(matched: list[dict]) -> list[dict]:
    series = {isl: model_series(isl) for isl in {m["island"] for m in matched}}
    out = []
    for m in matched:
        uc, act = series[m["island"]]
        seg0 = m["segs"][0]
        tot_par = sum(par for _, _, par in seg0)
        # 観測が回線ごと(「1号線」)で、モデルがそれより多い回線をまとめて持つときは按分する
        scale = (m["n_circ_obs"] / tot_par) if m["n_circ_obs"] and tot_par > m["n_circ_obs"] else 1.0

        def oriented(src, n):
            vals = []
            for i in range(n):
                v, ok = 0.0, False
                for k, sg, _ in seg0:
                    row = src.get(k)
                    if row is not None and i < len(row) and row[i] is not None:
                        v += sg * row[i]
                        ok = True
                vals.append(round(v * scale, 1) if ok else None)
            return vals
        n_act = max((len(act.get(k, [])) for k, _, _ in seg0), default=0)
        rec = {k: m[k] for k in ("util", "name", "kv", "from", "to", "island", "conf")}
        rec.update({k: m[k] for k in ("path_km", "straight_km", "single_ended") if k in m})
        rec["keys"] = [[k, sg] for seg in m["segs"] for k, sg, _ in seg]
        if scale != 1.0:
            rec["circuit_scale"] = round(scale, 3)
        rec["obs"] = m["obs"]
        for tag, vals in (("uc", oriented(uc, 24)), ("act", oriented(act, n_act))):
            st = stats(vals)
            rec[tag] = st
            if st and m["obs"]["p95"] > 0:
                rec[f"ratio_p95_{tag}"] = round(st["p95"] / m["obs"]["p95"], 3)
                # 片端(C)は符号の決まりが確かめられない。観測の平均がほぼ 0 の線も向きは判定しない
                if (m["conf"] != "C" and abs(m["obs"]["mean"]) >= 0.1 * m["obs"]["p95"]
                        and abs(st["mean"]) >= 1):
                    rec[f"dir_{tag}"] = (st["mean"] > 0) == (m["obs"]["mean"] > 0)
        out.append(rec)
    return out


def scorecard(recs: list[dict], tally: dict, n_obs: int) -> dict:
    def summ(rs, tag):
        rr = [r[f"ratio_p95_{tag}"] for r in rs if r.get(f"ratio_p95_{tag}")]
        dd = [r[f"dir_{tag}"] for r in rs if f"dir_{tag}" in r]
        if not rr:
            return None
        lg = sorted(math.log2(x) for x in rr)
        return {"n": len(rr), "within_x2": round(sum(1 for x in rr if 0.5 <= x <= 2) / len(rr), 3),
                "within_x1_5": round(sum(1 for x in rr if 1 / 1.5 <= x <= 1.5) / len(rr), 3),
                "median_ratio": round(2 ** lg[len(lg) // 2], 3),
                "dir_agree": round(sum(dd) / len(dd), 3) if dd else None, "n_dir": len(dd)}
    groups = {"all": recs}
    for r in recs:
        groups.setdefault(f"island:{r['island']}", []).append(r)
        groups.setdefault(f"kv:{int(r['kv'])}", []).append(r)
        groups.setdefault(f"conf:{r['conf']}", []).append(r)
    return {"n_observed_with_stats": n_obs, "n_matched": len(recs), "match_tally": tally,
            "groups": {g: {"uc": summ(rs, "uc"), "act": summ(rs, "act")} for g, rs in groups.items()}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--summary", action="store_true", help="照合の内訳だけ出して書き出さない")
    a = ap.parse_args()
    if not OBS.exists():
        sys.exit(f"{OBS} が無い(非公開データ。手元のチェックアウトで実行する)")
    obs = load_obs()
    built = json.loads((ROOT / "docs/data/built/all.json").read_text())
    matched, tally = match_all(obs, built)
    print(f"観測(統計あり) {len(obs)} 本 → 照合 {len(matched)} 本")
    for u, t in sorted(tally.items()):
        print(f"  {u:9s} " + " ".join(f"{k}={v}" for k, v in sorted(t.items())))
    if a.summary:
        return 0
    recs = compare(matched)
    sc = scorecard(recs, tally, len(obs))
    out = {"note": ("観測(公表実績の年統計・2024 年度)とモデル(UC 代表日 / 実績需要で解いた日別断面)の"
                    "線ごとの突き合わせ。同時刻の比較ではなく分布の規模の比較。観測は年統計 3 値のみ"
                    "(生の時系列は収録しない)。出典=各一般送配電事業者 系統情報公表(潮流実績)。"),
           "method": "scripts/export_obs_compare.py の docstring", "scorecard": sc, "lines": recs}
    (FM / "obs_compare.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    g = sc["groups"]["all"]
    print(f"-> {FM / 'obs_compare.json'}  UC: {g['uc']}  実績需要: {g['act']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
