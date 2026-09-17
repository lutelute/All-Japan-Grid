#!/usr/bin/env python3
"""介入#35 — 偽断片のノード衛生(跨region二重登録の解消). オーナー承認 2026-08-26.

原則(捏造ゼロ): 接続を「作る」のではなく、**同一物理設備が2つのregionで
二重登録されて生じた幻の断片**を、双子側(別island本系統に接続済み)へ寄せて
解消する。screen_false_fragments.py の suspect(=候補列挙)を入力とし、
本スクリプトが確定判定+適用を行う。

根拠(①): docs/reports/satellite_photointerpretation_pilot_2026-08-20.md の c1 —
甲府近郊23ノード断片[west]は山梨の東電66kV背骨の region=chubu 二重登録だった。
c1深掘り(2026-08-26)で、完全双子11ノードに加え残12ノードも全て近傍(14〜117m)に
tokyo対応物(同名変電所/junction)を持つ=**23ノード全部が二重登録**と確認。

処理(断片単位・全ノード解消できる断片のみ適用=部分手術しない):
  1. 完全双子(同k5座標の双子が双子island側に存在) → ノード削除
     (座標グラフは不変: 双子が同座標に残るため連結性は減らない)
  2. 近傍双子(≤150m・kv一致(丸め等値)・名前ありなら基底名一致も要求)
     → 全edgesの当該端点座標を双子座標へリマップし、ノード削除
  3. 残余が無名junctionのみ → region を双子regionへ再帰属
     (リマップ済み隣接枝との線形連続性を双子island側で保つ)
  4. 名前つきノードが未解決で残る断片 → **断片ごとスキップ**(要人手レビュー)
  5. 影響ペアの余剰エッジdedup(同一無向k5ペアの重複オブジェクトを1本へ・
     path/name保持を優先)と、リマップで生じた自己ループ削除

無効化(③): docs/data/fragments/node_hygiene_ledger.json に削除ノード全量・
リマップ対・再帰属・削除エッジ全量を記録(逆再生で復元可能)。
再帰属ノードには hygiene="intervention35" マーカー。

冪等: 適用後の再実行では suspect が消えるため何もしない。regen(STEPS)組込前提。

介入#42(2026-09-02・混在県個別化): 同じ経路(--mixed-pref)で、混在県(長野・新潟・
静岡)の周波数跨ぎ候補ノードを境界資産+ホワイトリスト+切断ガードで再帰属する
(実装は src/powerflow/region_attribution.apply_mixed_pref_flips・ここは呼ぶだけ)。
帳簿=docs/data/fragments/mixed_pref_ledger.json(全フリップ・逆再生で復元可能)、
バックアップ=all.json.pre_mixed.bak、マーカー mixed_pref="intervention42"。冪等。

usage:
  PYTHONPATH=. python3 scripts/apply_node_hygiene.py           # 判定のみ
  PYTHONPATH=. python3 scripts/apply_node_hygiene.py --write   # 適用
  PYTHONPATH=. python3 scripts/apply_node_hygiene.py --mixed-pref --write   # #35+#42
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# build_fragment_worklist.py / screen_false_fragments.py と同一(変更禁止)
ISLAND_OF = {"hokkaido": "hokkaido", "tohoku": "east", "tokyo": "east",
             "chubu": "west", "hokuriku": "west", "kansai": "west",
             "chugoku": "west", "shikoku": "west", "kyushu": "west",
             "okinawa": "okinawa"}
MATCH_M = 150.0   # 近傍双子の許容距離(m)。c1実測: 名前つき最大117m・junction145m
# 介入#42 の既定。採用ゲート(docs/reports/mixed_pref_gate_2026-09-02.md)の結果で決める:
#   合格 → True(STEPS/Snakefile は明示 --mixed-pref も渡す) / 不合格 → False
MIXED_PREF_DEFAULT = True    # 採用 2026-09-02(ゲート全合格・west slack -291MW)


def k5(lat, lon):
    return (round(lat, 5), round(lon, 5))


def hav_m(a, b):
    la1, lo1 = a
    la2, lo2 = b
    dla = math.radians(la2 - la1)
    dlo = math.radians(lo2 - lo1)
    x = (math.sin(dla / 2) ** 2 + math.cos(math.radians(la1))
         * math.cos(math.radians(la2)) * math.sin(dlo / 2) ** 2)
    return 6371000.0 * 2 * math.asin(math.sqrt(x))


def norm_base(s):
    s = unicodedata.normalize("NFKC", str(s or "")).replace(" ", "")
    s = re.sub(r"(_\d+|\s*\d+kV)$", "", s)
    return s


def is_junction(n):
    return (not n.get("name")) or "junction" in str(n.get("name"))


def build_components(nodes, edges, island):
    regs = {r for r, i in ISLAND_OF.items() if i == island}
    keys = {}
    for n in nodes:
        if n.get("region") in regs:
            keys.setdefault(k5(n["lat"], n["lon"]), n)
    adj = defaultdict(set)
    for e in edges:
        if not (e.get("a") and e.get("b")):
            continue
        ka, kb = k5(*e["a"]), k5(*e["b"])
        if ka in keys and kb in keys:
            adj[ka].add(kb)
            adj[kb].add(ka)
    seen, comps = set(), []
    for k in keys:
        if k in seen:
            continue
        stack, comp = [k], set()
        while stack:
            c = stack.pop()
            if c in comp:
                continue
            comp.add(c)
            stack.extend(adj[c] - comp)
        seen |= comp
        comps.append(comp)
    comps.sort(key=len, reverse=True)
    return keys, comps


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--mixed-pref", action=argparse.BooleanOptionalAction,
                    default=MIXED_PREF_DEFAULT,
                    help="介入#42 混在県個別化(長野/新潟/静岡の跨ぎ候補を境界資産で"
                         "再帰属)。--no-mixed-pref で無効化(回帰比較用)")
    ap.add_argument("--freq-fix", action=argparse.BooleanOptionalAction,
                    default=True,
                    help="介入#38 の正典化(一意周波数県の跨ぎラベルを正典へ焼く)。"
                         "既定ON・--no-freq-fix で無効化(回帰比較用)")
    args = ap.parse_args()

    built = json.loads((ROOT / "docs/data/built/all.json").read_text())
    nodes, edges = built["nodes"], built["edges"]

    islands = ("hokkaido", "east", "west", "okinawa")
    keys_of, comps_of, main_of = {}, {}, {}
    for isl in islands:
        keys, comps = build_components(nodes, edges, isl)
        keys_of[isl], comps_of[isl] = keys, comps
        main_of[isl] = comps[0] if comps else set()

    # island → 全ノード索引(粗グリッド: 近傍双子探索用)
    isl_grid = {isl: defaultdict(list) for isl in islands}
    for isl in islands:
        regs = {r for r, i in ISLAND_OF.items() if i == isl}
        for n in nodes:
            if n.get("region") in regs:
                isl_grid[isl][(round(n["lat"], 2),
                               round(n["lon"], 2))].append(n)

    def near_twin(n, twin_isl):
        """近傍双子: ≤MATCH_M・kv丸め等値・名前ありなら基底名一致。"""
        k = k5(n["lat"], n["lon"])
        nkv = round(float(n.get("kv") or 0))
        nb = None if is_junction(n) else norm_base(n.get("name"))
        g = (round(k[0], 2), round(k[1], 2))
        best = None
        for dla in (-1, 0, 1):
            for dlo in (-1, 0, 1):
                for m in isl_grid[twin_isl].get(
                        (round(g[0] + dla / 100, 2),
                         round(g[1] + dlo / 100, 2)), []):
                    d = hav_m(k, (m["lat"], m["lon"]))
                    if d > MATCH_M or d == 0:
                        continue
                    if round(float(m.get("kv") or 0)) != nkv:
                        continue
                    if nb is not None and norm_base(m.get("name")) != nb:
                        continue
                    if best is None or d < best[0]:
                        best = (d, m)
        return best

    plans, skipped = [], []
    for isl in islands:
        keys, comps = keys_of[isl], comps_of[isl]
        for ci, comp in enumerate(comps[1:], 1):
            # 双子island: 完全双子(同k5)が最多の別island(本系統接続を要求)
            twin_cnt = Counter()
            for k in comp:
                for oisl in islands:
                    if oisl != isl and k in main_of[oisl]:
                        twin_cnt[oisl] += 1
            if not twin_cnt:
                continue
            twin_isl, n_exact = twin_cnt.most_common(1)[0]
            frac = n_exact / len(comp)
            # screen と同じ suspect ゲート(全ノード双子 or frac>=0.2&n>=2)
            if not (n_exact == len(comp) or (frac >= 0.2 and n_exact >= 2)):
                continue
            drops, remaps, reattrs, blocked = [], [], [], []
            for k in comp:
                n = keys[k]
                if k in main_of[twin_isl] or k in keys_of[twin_isl]:
                    drops.append(n)          # 完全双子 → 削除
                    continue
                tw = near_twin(n, twin_isl)
                if tw is not None:
                    remaps.append((n, tw[1], round(tw[0])))  # 近傍双子 → リマップ
                elif is_junction(n):
                    reattrs.append(n)        # 無名junction → 再帰属
                else:
                    blocked.append(n)        # 名前つき未解決 → 断片スキップ
            if blocked:
                skipped.append({
                    "island": isl, "comp": ci, "n_nodes": len(comp),
                    "reason": "named-unresolved",
                    "blocked": [{"name": b.get("name"), "kv": b.get("kv"),
                                 "lat": b["lat"], "lon": b["lon"]}
                                for b in blocked]})
                continue
            plans.append({"island": isl, "comp": ci, "twin_island": twin_isl,
                          "n_nodes": len(comp), "drops": drops,
                          "remaps": remaps, "reattrs": reattrs})

    n_d = sum(len(p["drops"]) for p in plans)
    n_r = sum(len(p["remaps"]) for p in plans)
    n_a = sum(len(p["reattrs"]) for p in plans)
    print(f"適用可能断片: {len(plans)}件 (削除{n_d} リマップ{n_r} 再帰属{n_a}ノード)"
          f" / スキップ: {len(skipped)}件(名前つき未解決)")
    for p in plans:
        print(f"  [{p['island']}] comp{p['comp']:>4} {p['n_nodes']:>3}ノード "
              f"→ {p['twin_island']}: drop={len(p['drops'])} "
              f"remap={len(p['remaps'])} reattr={len(p['reattrs'])}")
    for s in skipped:
        names = [b["name"] for b in s["blocked"]][:3]
        print(f"  SKIP [{s['island']}] comp{s['comp']} {s['n_nodes']}ノード "
              f"未解決: {names}")

    if not args.write:
        print("(判定のみ。適用は --write)")
    elif not plans:
        print("適用対象なし(冪等)")
    else:
        _apply_hygiene(built, nodes, edges, plans, isl_grid)

    # ── 介入#42: 混在県個別化(#35 と同じ正典適用経路・冪等) ──
    if args.mixed_pref:
        _mixed_pref_stage(built, write=args.write)
    if args.freq_fix:
        _uniform_freq_stage(built, write=args.write)
    return 0


def _uniform_freq_stage(built, write: bool) -> None:
    """介入#38 の正典化(2026-09-03) — 一意周波数県の跨ぎラベルを正典へ焼く。

    #38 は潮流を組むときだけ効いていて、正典のラベルは古いままだった。
    地図・エディタ・輸出は正典を直接読むので、群馬の設備が「中部」と着色される
    実害が残っていた。混在県は #42 の担当なので触らない。
    """
    from src.powerflow.region_attribution import (
        UNIFORM_FREQ_MARK, apply_uniform_freq_flips, plan_uniform_freq_flips)
    nodes, edges = built["nodes"], built["edges"]
    up = plan_uniform_freq_flips(nodes, edges)
    print(f"介入#38 正典化: フリップ計画{len(up['plan'])} {up['by_dir']} / "
          f"島跨ぎ枝 {up['cross_edges_before']} → {up['cross_edges_after']}")
    if not write:
        return
    if not up["plan"]:
        print("  適用対象なし(冪等)")
        return
    bak = ROOT / "docs/data/built/all.json.pre_freqfix.bak"
    bak.write_text(json.dumps(built, ensure_ascii=False))
    res = apply_uniform_freq_flips(nodes, edges)
    if not res["applied"]:
        print("  ★適用しない: 島跨ぎ枝が増える計画")
        return
    ledger = {"note": ("介入#38 の正典化(2026-09-03)。座標の県の周波数が一意で、"
                       "領土エリアの周波数と一致するノードだけを再属性する"
                       "(混在県は #42 の担当)。復元=本台帳 flips の to→from 逆再生 + "
                       "all.json.pre_freqfix.bak"),
              "marker": UNIFORM_FREQ_MARK,
              "by_dir": up["by_dir"],
              "cross_edges_before": up["cross_edges_before"],
              "cross_edges_after": up["cross_edges_after"],
              "flips": res["flips"]}
    (ROOT / "docs/data/built/all.json").write_text(
        json.dumps(built, ensure_ascii=False))
    dst = ROOT / "docs/data/fragments/uniform_freq_ledger.json"
    _merge_ledger(dst, ledger)
    print(f"★正典適用: 介入#38 フリップ{len(res['flips'])}ノード "
          f"(バックアップ={bak.name})")
    print(f"-> {dst.relative_to(ROOT)}")


def _merge_ledger(dst, new_ledger: dict) -> None:
    """帳簿を **追記マージ** する(2026-09-03).

    従来は毎回上書きしていたので、インクリメンタルに適用すると過去のフリップが
    帳簿から消え、**逆再生できなくなる**(regen は基底から作り直すので上書きでも
    成立するが、正典に対する追加適用では履歴が失われる)。id で重複排除しつつ
    既存の flips を保ち、適用の回数と日付を runs に残す。
    """
    import datetime as _dt
    prev = {}
    if dst.exists():
        try:
            prev = json.loads(dst.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            prev = {}
    merged = dict(prev)
    merged.update({k: v for k, v in new_ledger.items() if k != "flips"})
    seen, flips = set(), []
    for f in list(prev.get("flips", [])) + list(new_ledger.get("flips", [])):
        key = f.get("id") or (f.get("lat"), f.get("lon"))
        if key in seen:
            continue
        seen.add(key)
        flips.append(f)
    merged["flips"] = flips
    runs = list(prev.get("runs", []))
    runs.append({"at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
                 "added": len(new_ledger.get("flips", [])), "total": len(flips)})
    merged["runs"] = runs
    dst.write_text(json.dumps(merged, ensure_ascii=False, indent=1))


def _mixed_pref_stage(built, write: bool) -> None:
    from src.powerflow.region_attribution import (
        MIXED_PREF_MARK, apply_mixed_pref_flips, plan_mixed_pref_flips)
    nodes, edges = built["nodes"], built["edges"]
    mp = plan_mixed_pref_flips(nodes, edges)
    print(f"介入#42 混在県個別化: ガード対象{len(mp['guarded'])} → フリップ計画"
          f"{len(mp['plan'])} (WL拒否{len(mp['veto_whitelist'])}・切断ガード拒否"
          f"{len(mp['veto_crossing'])}・ガード維持{len(mp['kept'])}) / "
          f"既存跨ぎ{mp['pre_cross_edges']}・新規切断{mp['new_cross_edges']}")
    if not write:
        return
    if not mp["plan"]:
        print("  適用対象なし(冪等)")
        return
    if mp["new_cross_edges"] != 0:
        print("  ★適用しない: 切断ガードが収束せず新規跨ぎが残る")
        return
    bak = ROOT / "docs/data/built/all.json.pre_mixed.bak"
    bak.write_text(json.dumps(built, ensure_ascii=False))
    res = apply_mixed_pref_flips(nodes, edges)
    ledger = {"note": ("介入#42 混在県個別化(2026-09-02)。根拠=data/reference/"
                       "freq_boundary_mixed.geojson(出典つき境界)+freq_corridor_whitelist.json。"
                       "復元=本台帳 flips の to→from 逆再生 + all.json.pre_mixed.bak"),
              "marker": MIXED_PREF_MARK,
              "fixed": res["fixed"], "vetoed": res["vetoed"],
              "pre_cross_edges": res["plan"]["pre_cross_edges"],
              "new_cross_edges": res["plan"]["new_cross_edges"],
              "flips": res["flips"],
              "vetoed_whitelist": [
                  {"id": nodes[i].get("id"), "name": nodes[i].get("name"), "why": w}
                  for i, w in sorted(res["plan"]["veto_whitelist"].items())],
              "vetoed_crossing": [
                  {"id": nodes[i].get("id"), "name": nodes[i].get("name"), "cut_edge": w}
                  for i, w in sorted(res["plan"]["veto_crossing"].items())]}
    (ROOT / "docs/data/built/all.json").write_text(
        json.dumps(built, ensure_ascii=False))
    dst = ROOT / "docs/data/fragments/mixed_pref_ledger.json"
    _merge_ledger(dst, ledger)
    print(f"★正典適用: 介入#42 フリップ{len(res['flips'])}ノード {res['fixed']} "
          f"(バックアップ={bak.name})")
    print(f"-> {dst.relative_to(ROOT)}")


def _apply_hygiene(built, nodes, edges, plans, isl_grid) -> None:
    n_d = sum(len(p["drops"]) for p in plans)
    n_r = sum(len(p["remaps"]) for p in plans)
    n_a = sum(len(p["reattrs"]) for p in plans)
    bak = ROOT / "docs/data/built/all.json.pre_hygiene.bak"
    bak.write_text(json.dumps(built, ensure_ascii=False))

    drop_ids = set()
    coord_map = {}           # old_k5 → new (lat, lon)
    ledger = {"note": ("介入#35 ノード衛生(2026-08-26 オーナー承認)。"
                       "根拠=satellite_photointerpretation_pilot c1 + "
                       "false_fragment_screen。復元=本台帳の逆再生+"
                       "all.json.pre_hygiene.bak"),
              "params": {"match_m": MATCH_M},
              "fragments": [], "removed_edges": [], "self_loops_removed": 0}
    for p in plans:
        rec = {"island": p["island"], "comp": p["comp"],
               "twin_island": p["twin_island"],
               "dropped_nodes": [], "remapped": [], "reattributed": []}
        for n in p["drops"]:
            drop_ids.add(id(n))
            rec["dropped_nodes"].append(dict(n))
        for n, tw, dm in p["remaps"]:
            drop_ids.add(id(n))
            coord_map[k5(n["lat"], n["lon"])] = (tw["lat"], tw["lon"])
            rec["dropped_nodes"].append(dict(n))
            rec["remapped"].append({
                "from": {"name": n.get("name"), "region": n.get("region"),
                         "lat": n["lat"], "lon": n["lon"]},
                "to": {"name": tw.get("name"), "region": tw.get("region"),
                       "lat": tw["lat"], "lon": tw["lon"]},
                "dist_m": dm})
        twin_regs = sorted({r for r, i in ISLAND_OF.items()
                            if i == p["twin_island"]})
        # 再帰属先region: 双子ノードの多数決(完全双子+リマップ先)
        reg_cnt = Counter()
        for n, tw, _ in p["remaps"]:
            reg_cnt[tw.get("region")] += 1
        for n in p["drops"]:
            for m in isl_grid[p["twin_island"]].get(
                    (round(n["lat"], 2), round(n["lon"], 2)), []):
                if k5(m["lat"], m["lon"]) == k5(n["lat"], n["lon"]):
                    reg_cnt[m.get("region")] += 1
        new_reg = (reg_cnt.most_common(1)[0][0] if reg_cnt else twin_regs[0])
        for n in p["reattrs"]:
            # 介入#38ガード(2026-08-30): 周波数跨ぎ再帰属は、座標の県の周波数が
            # 一意で行き先と一致する場合のみ許可。混在県(長野等)では跨がない —
            # 本スクリプトが東信のtokyo junctionをchubuへ流し込みwest AC発散の
            # 一因になった実績があるため(docs/reports/west_ac_onset_full)
            from src.powerflow.region_attribution import (
                AREA_FREQ, UNIFORM_FREQ_PREFS, prefecture_of)
            f_from = AREA_FREQ.get(n.get("region"))
            f_to = AREA_FREQ.get(new_reg)
            if f_from is not None and f_to is not None and f_from != f_to:
                pref = prefecture_of(float(n["lat"]), float(n["lon"]))
                if UNIFORM_FREQ_PREFS.get(pref) != f_to:
                    rec["reattr_skipped_freq"] =                         rec.get("reattr_skipped_freq", 0) + 1
                    continue
            rec["reattributed"].append({
                "name": n.get("name"), "lat": n["lat"], "lon": n["lon"],
                "region_from": n.get("region"), "region_to": new_reg})
            n["region"] = new_reg
            n["hygiene"] = "intervention35"
        ledger["fragments"].append(rec)

    # ノード削除
    built["nodes"] = [n for n in nodes if id(n) not in drop_ids]

    # エッジのリマップ + 自己ループ除去 + 影響ペアdedup
    affected = set()
    remapped_ids = set()   # リマップで触った枝のみ自己ループ除去の対象
    for e in edges:
        if not (e.get("a") and e.get("b")):
            continue
        for side in ("a", "b"):
            kk = k5(*e[side])
            if kk in coord_map:
                new = coord_map[kk]
                e[side] = [new[0], new[1]]
                # path端点も追随(先頭/末尾が旧座標なら差し替え)
                pth = e.get("path")
                if pth:
                    if k5(*pth[0]) == kk:
                        pth[0] = [new[0], new[1]]
                    if k5(*pth[-1]) == kk:
                        pth[-1] = [new[0], new[1]]
                e.setdefault("hygiene", "intervention35")
                remapped_ids.add(id(e))
                affected.add(frozenset((k5(*e["a"]), k5(*e["b"]))))
    # 完全双子断片の内部ペアも dedup 対象(双子側と同一ペアの二重オブジェクト)
    for p in plans:
        dks = {k5(n["lat"], n["lon"]) for n in p["drops"]}
        for e in edges:
            if e.get("a") and e.get("b"):
                ka, kb = k5(*e["a"]), k5(*e["b"])
                if ka in dks and kb in dks:
                    affected.add(frozenset((ka, kb)))

    kept, removed, seen_pair = [], [], set()
    # path/name持ちを残す優先: 同一ペア内でスコアの高い1本を残す
    by_pair = defaultdict(list)
    for e in edges:
        if e.get("a") and e.get("b"):
            pair = frozenset((k5(*e["a"]), k5(*e["b"])))
            if len(pair) == 1:
                # 自己ループはリマップで生じた枝のみ除去。既存の同一座標エッジ
                # (intra-substation stub 2190本)は意図的な構造なので不可触
                if id(e) in remapped_ids:
                    ledger["self_loops_removed"] += 1
                    removed.append(e)
                else:
                    kept.append(e)
                continue
            if pair in affected:
                by_pair[pair].append(e)
                continue
        kept.append(e)
    for pair, es in by_pair.items():
        es.sort(key=lambda e: (bool(e.get("path")), bool(e.get("name")),
                               bool(e.get("disclosure"))), reverse=True)
        kept.append(es[0])
        removed.extend(es[1:])
    for e in removed:
        ledger["removed_edges"].append(
            {k: v for k, v in e.items() if k != "path"})
    built["edges"] = kept

    (ROOT / "docs/data/built/all.json").write_text(
        json.dumps(built, ensure_ascii=False))
    dst = ROOT / "docs/data/fragments/node_hygiene_ledger.json"
    dst.write_text(json.dumps(ledger, ensure_ascii=False, indent=1))
    print(f"★正典適用: 断片{len(plans)}件解消 — ノード削除{n_d + n_r} "
          f"(うちリマップ{n_r}) 再帰属{n_a} / 余剰エッジ削除{len(removed)}本 "
          f"(自己ループ{ledger['self_loops_removed']}) "
          f"(バックアップ={bak.name}・介入#35)")
    print(f"-> {dst.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(main())
