#!/usr/bin/env python3
"""指定日の実績需要(でんき予報)で24時刻の全ノーダル潮流を計算し日付別断面を出力.

オーナー要望(2026-08-18): flow_mapで「日付を選択」できるように。
拡張(2026-08-19・手法(a)): エリア需給実績(燃料別)が取れるzoneは発電側も
実績で注入する — 原発停止等の時事が公表実績経由で自動反映される
(オーナー「そういう時事ネタは反映させる必要ありますか?」→「ちょっと整備して」)。

使い方: PYTHONPATH=. python3 scripts/export_day_flows.py --date 20260817
出力: docs/data/flow_map/days/<date>.json
  {hours, islands:{<isl>:{p:[線×24], ld:[線×24]}}, demand_src, note}
  線順は flows_<isl>.geojson と同一(同じbuild_island_net順・名前検証つき)。
  docs/data/flow_map/days/manifest.json に日付リストを保守。

需要の取得可能性(2026-08-18実測):
  日付URL6社(hokkaido/tohoku/hokuriku/chugoku/kyushu/okinawa)=過去〜当日
  shikoku=年次CSV(前日まで) / tokyo=juyo-result-j.csv(2日前まで)+当日はjuyo-d1
  chubu=keito_jisseki(当日のみ・30分kWh→MW平均) / kansai=未特定(TODO)
  取れないzoneはスケールせずfy2023既定需要のまま(noteに明示=誠実)。

燃料別実績(fetch_area_fuelmix.py): 9/10社(tohokuは約2か月遅れ・okinawa未特定)。
取れないzone/時刻は従来の容量比例balanceに自動フォールバック(帳簿に明示)。
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import re
import sys
import time
import urllib.request
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs/data/flow_map/days"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


def _get(url: str) -> str | None:
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("cp932", errors="replace")
    except Exception as ex:  # noqa: BLE001
        print(f"  ! {url.split('/')[-1]}: {ex}")
        return None


# 手法(a)の実装版。a2=太陽光不足分の需要側控除 / a3=島外zoneの帳簿除外 /
# a4=島間連系(FC・北本)のOCCTO計画潮流注入(いずれも2026-08-19)
FUEL_ACTUALS_METHOD = "a4"


def setup_day_boundary(net, island: str) -> list:
    """島間連系(FC・北本)の注入点sgenを変換所バスに用意する。

    重み・注入点は uc_to_pf_built.BOUNDARY_POINTS と共有(写し禁止)。
    day断面ではOCCTO kohyo_04の計画潮流実測値を注入する(UC値ではない)。
    """
    import pandapower as pp
    from scripts.uc_to_pf_built import BOUNDARY_POINTS
    pts = []
    for spec in BOUNDARY_POINTS.get(island, []):
        mask = net.bus.name.astype(str).str.contains(
            spec["name"], regex=False) & net.bus.in_service
        if not mask.any():
            continue
        b = int(net.bus.loc[mask, "vn_kv"].idxmax())
        pts.append({**spec, "bus": b,
                    "sgen": int(pp.create_sgen(
                        net, bus=b, p_mw=0.0, q_mvar=0.0,
                        name=f"day_boundary_{spec['name']}"))})
    for pt in pts:
        pw = sum(p["weight"] for p in pts if p["pair"] == pt["pair"])
        pt["share"] = pt["weight"] / pw if pw else 0.0
    return pts


def day_boundary_series(fm: dict, island: str) -> dict:
    """{pairタプル: [24h 島への正味輸入MW]} — kohyo_04計画潮流から。

    順方向の定義: fc=東京→中部(westへ+) / hokuhon=北海道→東北(eastへ+)。
    """
    ic = ((fm or {}).get("interconnectors") or {}).get("flows") or {}
    fc, hb = ic.get("fc"), ic.get("hokuhon")
    out = {}
    if fc:
        sign = {"west": 1.0, "east": -1.0}.get(island)
        if sign:
            out[("chubu", "tokyo")] = [None if v is None else sign * v
                                       for v in fc]
    if hb:
        sign = {"east": 1.0, "hokkaido": -1.0}.get(island)
        if sign:
            out[("hokkaido", "tohoku")] = [None if v is None else sign * v
                                           for v in hb]
    return out

# net.gen.type(OSM燃料) → エリア需給実績の燃料カテゴリ(合算)。
# pumped_hydro/batteryの正値(放電)はhydro/残余へ、負値(充電)は需要側に加算。
_GEN_FUEL_MAP = {
    "nuclear": ("nuclear",),
    "gas": ("lng", "thermal_other"),
    "coal": ("coal",),
    "oil": ("oil",),
    "hydro": ("hydro", "_pumped_pos"),
    "solar": ("solar",),
    "wind": ("wind",),
    "biomass": ("biomass",),
    "geothermal": ("geothermal",),
}


def apply_fuel_actuals(net, fm_zones: dict, h: int, island: str = None) -> dict:
    """エリア需給実績(燃料別)でzoneの発電を上書きする(手法(a))。

    balance_by_zone(容量比例)の後に呼ぶ。実績があるzoneのみ:
      - 燃料グループごとに実績MWを容量比例で配分(容量不足はclipして帳簿)
      - **太陽光の不足分は需要側から控除**: モデルはOSM由来の事業用太陽光のみで
        実績(屋根置き・推計込み)より大幅に小さい。分散太陽光は物理的に需要
        ノード側にあるので、載せられない分を負荷低減として扱う(ゾーン収支を
        実績に保つ。2026-08-19実走で東近江5,106MW等の歪みを検出して導入)
      - 実績カテゴリに対応しない燃料(unknown等)のgenは0化
      - 揚水/蓄電池の充電(負値)はzone負荷に加算(需要側計上)
    返り値 = zone別帳簿 {zone: {applied_mw, clipped_mw, solar_to_load_mw,
    unknown_zeroed_mw, charge_mw}}。実績が無いzone・この島に居ないzoneは
    触らない(=容量比例のまま)。
    """
    ledger = {}
    # zoneは本籍島でのみ適用する。bbox境界の帰属ノード(east網内のchubuラベル等)に
    # zone全量を適用すると、少数のgen/loadへ需給全体が載る(2026-08-19実走で
    # tokyo/chubuがh=48=二重適用+clip水増しになったのを検出)
    if island is not None:
        from scripts.run_full_powerflow_from_db import ISLAND_OF
        fm_zones = {z: v for z, v in fm_zones.items()
                    if ISLAND_OF.get(z, (None,))[0] == island}
    gz = net.gen["bus"].map(net.bus["zone"])
    if "zone_src" in net.gen.columns:
        src = net.gen["zone_src"]
        gz = gz.where(~(src.notna() & (src != "")), src)
    for zone, zdata in fm_zones.items():
        fuels = zdata.get("fuels") or {}
        def _at(key):
            arr = fuels.get(key) or []
            v = arr[h] if h < len(arr) else None
            return float(v) if v is not None else None
        if _at("demand") is None:
            continue          # この時刻の実績なし → balanceのまま
        pumped = _at("pumped_hydro") or 0.0
        battery = _at("battery") or 0.0
        targets = {}
        for gfuel, cats in _GEN_FUEL_MAP.items():
            tot, seen = 0.0, False
            for c in cats:
                if c == "_pumped_pos":
                    tot += max(pumped, 0.0)
                    continue
                v = _at(c)
                if v is not None:
                    tot += max(v, 0.0)
                    seen = True
            if seen:
                targets[gfuel] = tot
        if not targets:
            continue
        zmask = (gz == zone) & net.gen.in_service
        if not zmask.any():
            continue      # このzoneはこの島のnetに居ない(帳簿にも載せない)
        rep = {"applied_mw": 0.0, "clipped_mw": 0.0, "solar_to_load_mw": 0.0,
               "unknown_zeroed_mw": 0.0, "charge_mw": 0.0}
        for gfuel, tgt in targets.items():
            gm = zmask & (net.gen["type"] == gfuel)
            caps = net.gen.loc[gm, "max_p_mw"].astype(float).clip(lower=0.0) \
                if gm.any() else None
            cap_sum = float(caps.sum()) if caps is not None else 0.0
            short = max(tgt - cap_sum, 0.0)
            if cap_sum > 0:
                scale = min(tgt / cap_sum, 1.0)
                net.gen.loc[gm, "p_mw"] = caps * scale
                rep["applied_mw"] += min(tgt, cap_sum)
            if short > 0:
                if gfuel == "solar":
                    rep["solar_to_load_mw"] += short   # 需要側で後処理
                else:
                    rep["clipped_mw"] += short
        um = zmask & ~net.gen["type"].isin(_GEN_FUEL_MAP.keys())
        if um.any():
            rep["unknown_zeroed_mw"] = float(
                net.gen.loc[um, "p_mw"].astype(float).sum())
            net.gen.loc[um, "p_mw"] = 0.0
        # 需要側の調整: +充電(揚水/蓄電池) −太陽光不足分(分散太陽光の近似)。
        # 負荷を潰しすぎないよう下限5%でクランプ(超過分はclippedへ戻す)
        charge = max(-pumped, 0.0) + max(-battery, 0.0)
        delta = charge - rep["solar_to_load_mw"]
        lmask = net.load.bus.map(net.bus["zone"]) == zone
        cur = float(net.load.loc[lmask, "p_mw"].sum())
        if cur > 0 and abs(delta) > 1.0:
            sc = max((cur + delta) / cur, 0.05)
            over = (cur + delta) - sc * cur     # クランプで載らなかった負分
            if over < -1.0:
                rep["clipped_mw"] += -over
                rep["solar_to_load_mw"] -= -over
            net.load.loc[lmask, "p_mw"] *= sc
            net.load.loc[lmask, "q_mvar"] *= sc
            rep["charge_mw"] = charge
        ledger[zone] = {k: round(v, 1) for k, v in rep.items()}
    return ledger


def day_demand(date: dt.date) -> dict[str, dict[int, float]]:
    """{zone: {hour: MW}} — 取れたzoneのみ返す。"""
    D = date.strftime("%Y%m%d")
    ymd_slash = f"{date.year}/{date.month}/{date.day}"
    out: dict[str, dict[int, float]] = {}

    dated = {
        "hokkaido": f"https://denkiyoho.hepco.co.jp/area/data/juyo_01_{D}.csv",
        "tohoku": f"https://setsuden.nw.tohoku-epco.co.jp/common/demand/juyo_02_{D}.csv",
        "hokuriku": f"https://www.rikuden.co.jp/nw/denki-yoho/csv/juyo_05_{D}.csv",
        "chugoku": f"https://www.energia.co.jp/nw/jukyuu/sys/juyo_07_{D}.csv",
        "kyushu": f"https://www.kyuden.co.jp/td_power_usages/csv/juyo-hourly-{D}.csv",
        "okinawa": f"https://www.okiden.co.jp/denki2/juyo_10_{D}.csv",
    }
    for zone, url in dated.items():
        txt = _get(url)
        time.sleep(0.5)
        if not txt:
            continue
        hh = {}
        in_sec = False
        for ln in txt.splitlines():
            if re.match(r"DATE,TIME,当日実績", ln):
                in_sec = True
                continue
            if in_sec:
                ps = ln.split(",")
                if len(ps) < 3 or not re.match(r"20\d\d/", ps[0]):
                    if not ln.strip():
                        break
                    continue
                try:
                    h, v = int(ps[1].split(":")[0]), float(ps[2])
                except ValueError:
                    continue
                if v > 0:
                    hh[h] = v * 10.0
        if hh:
            out[zone] = hh

    # tokyo: 年度実績(2日前まで) or 当日ファイル
    txt = _get("https://www.tepco.co.jp/forecast/html/images/juyo-result-j.csv")
    if txt:
        hh = {}
        for ln in txt.splitlines():
            ps = ln.split(",")
            if len(ps) >= 4 and ps[0] == ymd_slash:
                try:
                    hh[int(ps[1].split(":")[0])] = float(ps[3]) * 10.0
                except ValueError:
                    pass
        if hh:
            out["tokyo"] = hh
    if "tokyo" not in out and date == dt.date.today():
        txt = _get("https://www.tepco.co.jp/forecast/html/images/juyo-d1-j.csv")
        if txt:
            hh = {}
            in_sec = False
            for ln in txt.splitlines():
                if re.match(r"DATE,TIME,当日実績", ln):
                    in_sec = True
                    continue
                if in_sec:
                    ps = ln.split(",")
                    if len(ps) >= 3 and re.match(r"20\d\d/", ps[0]):
                        try:
                            v = float(ps[2])
                            if v > 0:
                                hh[int(ps[1].split(":")[0])] = v * 10.0
                        except ValueError:
                            pass
            if hh:
                out["tokyo"] = hh

    # shikoku: 年次CSV(前日まで)
    txt = _get("https://www.yonden.co.jp/nw/denkiyoho/csv/juyo_shikoku_2026.csv")
    if txt:
        hh = {}
        tgt = f"{date.year}/{date.month:02d}/{date.day:02d}"
        for ln in txt.splitlines():
            ps = ln.split(",")
            if len(ps) >= 3 and ps[0] == tgt:
                try:
                    hh[int(ps[1].split(":")[0])] = float(ps[2]) * 10.0
                except ValueError:
                    pass
        if hh:
            out["shikoku"] = hh

    # chubu: keito_jisseki(当日のみ・30分kWh→時間平均MW)
    if date == dt.date.today():
        txt = _get("https://powergrid.chuden.co.jp/denki_yoho_content_data/"
                   "keito_jisseki_cepco003.csv")
        if txt:
            slot = {}
            for ln in txt.splitlines():
                ps = ln.split(",")
                if len(ps) >= 5 and re.match(r"20\d\d/", ps[0]):
                    try:
                        k, kwh = int(ps[1]), float(ps[4])
                    except ValueError:
                        continue
                    if kwh > 0:
                        slot[k] = kwh
            hh = {}
            for h in range(24):
                a, b = slot.get(2 * h + 1), slot.get(2 * h + 2)
                if a and b:
                    hh[h] = (a + b) / 1000.0  # kWh(30分)×2枠/1000 = 平均MW
            if hh:
                out["chubu"] = hh
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="YYYYMMDD")
    ap.add_argument("--fuel-actuals", action=argparse.BooleanOptionalAction,
                    default=True,
                    help="エリア需給実績(燃料別)で発電側も実績注入する(既定ON・"
                         "手法(a) 2026-08-19)。無効化=--no-fuel-actuals")
    ap.add_argument("--islands", nargs="+",
                    default=["hokkaido", "east", "west", "okinawa"],
                    help="計算する島(既定=全4島)。メモリ逼迫時は島ごとに"
                         "別プロセスで順に実行する(未計算の島は既存断面を保持)")
    args = ap.parse_args()
    date = dt.datetime.strptime(args.date, "%Y%m%d").date()
    dem = day_demand(date)
    fm = None
    if args.fuel_actuals:
        from scripts.fetch_area_fuelmix import ensure_fuelmix
        fm = ensure_fuelmix(args.date)
        if fm and fm.get("zones"):
            print(f"燃料別実績: {sorted(fm['zones'].keys())}")
            # 副産物: でんき予報で欠ける需要をエリア需給実績の「エリア需要」で
            # **時間単位で**補完する(同じ公表量)。zone単位skipだと、tokyoの
            # ように需要1hだけ取れた日に残り23hが既定需要のまま発電だけ実績
            # 注入され、zone収支が崩れる(2026-08-19実走で検出)
            for z, zd in fm["zones"].items():
                darr = (zd.get("fuels") or {}).get("demand") or []
                hh = dem.setdefault(z, {})
                added = 0
                for h, v in enumerate(darr):
                    if v is not None and h not in hh:
                        hh[h] = float(v)
                        added += 1
                if not hh:
                    dem.pop(z, None)
                elif added:
                    print(f"  需要補完: {z} +{added}h (エリア需給実績)")
        else:
            fm = None
    print(f"{date}: 需要取得 {len(dem)}zone "
          f"({', '.join(f'{z}:{len(v)}h' for z, v in sorted(dem.items()))})")
    if len(dem) < 5:
        print("取得zoneが少なすぎるため中止")
        return 1

    import src.powerflow.point_demand as pdm
    from scripts.run_full_powerflow_from_db import (
        add_per_component_slacks, allocate_loads, attach_generators,
        balance_by_zone, build_island_net, load_demand_config, solve_island)
    from src.powerflow.pref_demand import pref_zone_gwh
    built = json.loads((ROOT / "docs/data/built/all.json").read_text())
    nodes, edges = built["nodes"], built["edges"]
    cfg = load_demand_config()
    pref_gwh, _ = pref_zone_gwh(nodes)
    demand_pd = pdm.load_point_demand()

    # 実績需要が1zoneでもある時刻のみ計算(当日の増分更新に対応)
    avail = sorted({h for hh in dem.values() for h in hh})
    prev = None
    prev_path = OUT / f"{args.date}.json"
    if prev_path.exists():
        prev = json.loads(prev_path.read_text())
        # 手法が変わった既存断面(容量比例のみ・旧版手法等)の時刻を再利用すると
        # 新旧の混在断面になる — zone集合か手法版が違えば全時刻を計算し直す
        prev_fa = sorted(prev.get("fuel_actuals_zones") or [])
        cur_fa = sorted(fm["zones"]) if fm else []
        prev_m = prev.get("fuel_actuals_method")
        cur_m = FUEL_ACTUALS_METHOD if fm else None
        if prev_fa != cur_fa or prev_m != cur_m:
            print(f"燃料実績の構成が変化({prev_fa}/{prev_m} -> "
                  f"{cur_fa}/{cur_m}) — 全時刻を再計算")
            prev = None
    fa_zones = sorted(fm["zones"].keys()) if fm else []
    result = {"date": args.date, "hours": list(range(24)), "islands": {},
              "available_hours": avail,
              "demand_zones": sorted(dem.keys()),
              "fuel_actuals_zones": fa_zones,
              "fuel_actuals_method": FUEL_ACTUALS_METHOD if fm else None,
              "cross_island_mw": ((fm or {}).get("interconnectors") or {})
              .get("flows"),
              "note": ("実績需要(でんき予報/エリア需給実績)でzone負荷を時刻別スケール"
                       "した全ノーダルPF。"
                       + (f"発電側は燃料別実績注入(手法(a)・zones={','.join(fa_zones)}"
                          "・原発停止等の時事を公表実績経由で反映)、"
                          if fa_zones else "")
                       + "残りのzoneは容量比例balance(=需要断面の近似)。"
                         "未取得zoneはfy2023既定需要のまま")}
    # 対象外の島は既存断面(prevまたは同手法の既出力)から持ち越す
    if prev:
        for isl, dat in (prev.get("islands") or {}).items():
            if isl not in args.islands:
                result["islands"][isl] = dat
        if prev.get("fuel_actuals_ledger"):
            result["fuel_actuals_ledger"] = prev["fuel_actuals_ledger"]

    fa_ledger: dict = {}
    for island, freq in (("hokkaido", 50), ("east", 50), ("west", 60),
                         ("okinawa", 60)):
        if island not in args.islands:
            continue
        t0 = time.time()
        net, bus_of, _ = build_island_net(island, nodes, edges, freq, {})
        attach_generators(net, bus_of, nodes, island, attach_mode="cap",
                          stats=True)
        pinned, _ = pdm.match_buses(net, demand_pd)
        allocate_loads(net, cfg, pref_gwh=pref_gwh, point_demand=pinned)
        from src.powerflow.pipeline import add_reactive_compensation
        add_reactive_compensation(net, factor=cfg.get(
            "reactive_compensation_factor", 0.6))
        add_per_component_slacks(net)
        bnd_pts = setup_day_boundary(net, island) if fm else []
        bnd_series = day_boundary_series(fm, island) if fm else {}
        zl0 = net.load.groupby(net.load.bus.map(net.bus["zone"])).p_mw.sum()
        base = net
        P, LD = None, None
        names = None
        n_ok = 0
        prev_isl = (prev or {}).get("islands", {}).get(island)
        prev_avail = set((prev or {}).get("available_hours") or [])
        for h in range(24):
            if h not in avail:
                continue
            if prev_isl and h in prev_avail:
                # 既計算時刻は再利用(増分更新)
                if P is None:
                    n = len(prev_isl["p"])
                    P = [[None]*24 for _ in range(n)]
                    LD = [[None]*24 for _ in range(n)]
                    names = None
                for i in range(len(prev_isl["p"])):
                    P[i][h] = prev_isl["p"][i][h]
                    LD[i][h] = prev_isl["ld"][i][h]
                n_ok += 1
                continue
            nt = copy.deepcopy(base)
            for z, hh in dem.items():
                tgt = hh.get(h)
                cur = float(zl0.get(z, 0) or 0)
                if not tgt or cur <= 0:
                    continue
                sc = tgt / cur
                mask = nt.load.bus.map(nt.bus["zone"]) == z
                nt.load.loc[mask, "p_mw"] *= sc
                nt.load.loc[mask, "q_mvar"] *= sc
            balance_by_zone(nt, cfg, use_zone_src=True)
            if fm:
                fa_led = apply_fuel_actuals(nt, fm["zones"], h, island=island)
                if fa_led:
                    fa_ledger.setdefault(island, {})[h] = fa_led
                for pt in bnd_pts:
                    series = bnd_series.get(tuple(pt["pair"]))
                    if series and h < len(series) and series[h] is not None:
                        nt.sgen.at[pt["sgen"], "p_mw"] = \
                            float(series[h]) * pt["share"]
            net_dc, dc, net_ac, ac = solve_island(nt, max_ac_buses=99999)
            conv = bool(ac.get("converged"))
            nu = net_ac if conv else net_dc
            if not (conv or dc.get("converged")):
                continue
            live = nu.line[nu.line.in_service]
            if P is None:
                n = len(live)
                P = [[None] * 24 for _ in range(n)]
                LD = [[None] * 24 for _ in range(n)]
                names = [str(x) for x in live.name]
            for i, (pv, lv) in enumerate(zip(
                    nu.res_line.loc[live.index, "p_from_mw"],
                    nu.res_line.loc[live.index, "loading_percent"])):
                P[i][h] = None if pv != pv else round(float(pv), 1)
                LD[i][h] = None if lv != lv else round(float(lv), 1)
            n_ok += 1
        # 線順検証(flows geojsonと同一のはず)
        gj = json.loads((ROOT / f"docs/data/flow_map/flows_{island}.geojson")
                        .read_text())
        gj_names = [f["properties"].get("name") for f in gj["features"]]
        if names is None and P is not None and len(P) == len(gj_names):
            names = gj_names   # 全時刻再利用時(線数一致で検証)
        if names != gj_names:
            print(f"! {island}: 線順不一致 — 出力しない(要調査)")
            continue
        result["islands"][island] = {"p": P, "ld": LD}
        print(f"[{island}] {n_ok}/{len(avail)}時刻(実績あり) {time.time()-t0:.0f}s", flush=True)

    # 燃料実績注入の帳簿(コンパクト): zone別に適用時刻数と合計clip。
    # 島分割実行では既存帳簿(他島のzone)にマージする(zoneは島間で重複しない)
    if fa_ledger:
        summ: dict = dict(result.get("fuel_actuals_ledger") or {})
        for isl, hh in fa_ledger.items():
            for h, zl in hh.items():
                for z, rep in zl.items():
                    s = summ.setdefault(z, {"hours": 0, "clipped_mwh": 0.0,
                                            "charge_mwh": 0.0})
                    s["hours"] += 1
                    s["clipped_mwh"] += rep.get("clipped_mw", 0.0)
                    s["charge_mwh"] += rep.get("charge_mw", 0.0)
        result["fuel_actuals_ledger"] = {
            z: {k: round(v, 1) for k, v in s.items()} for z, s in summ.items()}

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{args.date}.json").write_text(json.dumps(
        result, ensure_ascii=False, separators=(",", ":")))
    mf = {"dates": []}
    mfp = OUT / "manifest.json"
    if mfp.exists():
        mf = json.loads(mfp.read_text())
    if args.date not in mf["dates"]:
        mf["dates"].append(args.date)
        mf["dates"].sort()
    mfp.write_text(json.dumps(mf, ensure_ascii=False))
    print(f"-> days/{args.date}.json (manifest {len(mf['dates'])}日)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
