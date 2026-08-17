#!/usr/bin/env python3
"""指定日の実績需要(でんき予報)で24時刻の全ノーダル潮流を計算し日付別断面を出力.

オーナー要望(2026-08-18): flow_mapで「日付を選択」できるように。

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
    args = ap.parse_args()
    date = dt.datetime.strptime(args.date, "%Y%m%d").date()
    dem = day_demand(date)
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

    result = {"date": args.date, "hours": list(range(24)), "islands": {},
              "demand_zones": sorted(dem.keys()),
              "note": ("実績需要(でんき予報)でzone負荷を時刻別スケールした全ノーダルPF。"
                       "未取得zoneはfy2023既定需要のまま。UCディスパッチでなく容量比例"
                       "balance(=需要断面の近似)")}
    for island, freq in (("hokkaido", 50), ("east", 50), ("west", 60),
                         ("okinawa", 60)):
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
        zl0 = net.load.groupby(net.load.bus.map(net.bus["zone"])).p_mw.sum()
        base = net
        P, LD = None, None
        names = None
        n_ok = 0
        for h in range(24):
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
        if names != gj_names:
            print(f"! {island}: 線順不一致 — 出力しない(要調査)")
            continue
        result["islands"][island] = {"p": P, "ld": LD}
        print(f"[{island}] {n_ok}/24時刻 {time.time()-t0:.0f}s", flush=True)

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
