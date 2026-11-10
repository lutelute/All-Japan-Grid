#!/usr/bin/env python3
"""同時刻の採点: OCCTO の地内基幹送電線の潮流実績(30 分値)と、モデルの日別断面(1 時間値)を同じ時刻で比べる.

これまでの観測との比べ(scripts/export_obs_compare.py)は年統計どうしの規模の比較で、時刻をそろえていなかった。
OCCTO の当日分(docs/data/flow_map/occto_today.json、前日 0 時〜、毎時の処理が更新)が入ったので、
同じ日の日別断面(docs/data/flow_map/days/<日付>.json)と線路ごと・時刻ごとに突き合わせられる。

読むもの(書くのは --out だけ):
  --today      観測。地内基幹の 30 分値(時刻の印は瞬時値とみなし、台形で 1 時間の平均にする)
  --days-dir   モデル。名前=フォルダ の形で複数渡すと並べて採点する(例: 前=…/days 後=…/days_closed)
  --crosswalk  OCCTO の線路 → モデルの線の鍵(scripts/build_occto_line_crosswalk.py の出力。git の外)。
               無ければ --build-crosswalk で、当日分の線路の一覧から作る

線路ごとの物差し(時刻をそろえた系列どうし):
  比       |モデル|の平均 ÷ |観測|の平均
  時間の相関  観測とモデルの系列の相関係数(1 日の動きを追えているか)
  向き      平均の符号が合うか(照合 A・B だけ。C は片端の照合で向きを決めていないので、大きさだけ比べる)
  誤差      RMSE。観測の|平均|で割った値と、運用容量で割った値

使い方:
    PYTHONPATH=. python3 scripts/score_sync_flows.py --build-crosswalk
    PYTHONPATH=. python3 scripts/score_sync_flows.py --days-dir 前=docs/data/flow_map/days 後=/tmp/days_closed \\
        --out docs/reports/sync_scoreboard_2026-11-10.json

出典: 電力広域的運営推進機関「系統情報サービス」地内基幹送電線潮流実績・運用容量実績。線路ごとの値は --rows で
別のファイルに書く(報告に載せるのは集計)。
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import os
import statistics as st
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.powerflow.zone_closure import hourly_instant  # noqa: E402

FM = ROOT / "docs" / "data" / "flow_map"
DEFAULT_CW = ROOT / "data" / "external" / "occto" / "occto_line_crosswalk.json"
MIN_HOURS = 6          # これより少ない時刻しか重ならない線路は採点しない
QUIET_MW = 5.0         # 観測もモデルもこれ未満なら、向きは合っているとみなす


def pearson(x: list, y: list) -> float | None:
    n = len(x)
    if n < MIN_HOURS:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sx = math.sqrt(sum((a - mx) ** 2 for a in x))
    sy = math.sqrt(sum((b - my) ** 2 for b in y))
    if sx < 1e-9 or sy < 1e-9:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy)


def observed_hourly(today: dict) -> dict:
    """{線路 id: {(日付, 時): MW}}。30 分ごとの印を瞬時値とみなし、台形で 1 時間の平均にする。"""
    times = [dt.datetime.strptime(t, "%Y-%m-%d %H:%M") for t in today["times"]]
    days = [dt.date.fromisoformat(d) for d in today["days"]]
    out = {}
    for lid, v in today["lines"].items():
        stamps = {t: float(x) for t, x in zip(times, v["v"]) if x is not None}
        got = {}
        for day in days:
            for h, x in enumerate(hourly_instant(stamps, day)):
                if x is not None:
                    got[(day.isoformat(), h)] = x
        out[lid] = got
    return out


def capacity_of(today: dict, lid: str) -> float | None:
    """その線路の運用容量(当日分に入っている日の最大)。無ければ None。"""
    best = None
    for per_day in (today.get("cap") or {}).values():
        for x in per_day.get(lid) or []:
            if isinstance(x, (int, float)) and x and x < 90000:      # 99999 はフェンスで管理する印
                best = max(best or 0.0, float(x))
    return best


def model_hourly(days_dir: Path, days: list[str], base_dir: Path = FM) -> tuple[dict, list]:
    """{島: {線の鍵: {(日付, 時): MW}}} と、使った日付。線構成の署名が基準と違う島は使わない。"""
    meta = json.loads((base_dir / "meta.json").read_text(encoding="utf-8"))
    keys_of = {}
    model: dict = defaultdict(lambda: defaultdict(dict))
    used = []
    for day in days:
        p = days_dir / (day.replace("-", "") + ".json")
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        used.append(day)
        for isl, D in (d.get("islands") or {}).items():
            if D.get("base_sig") != meta.get(isl, {}).get("sig"):
                print(f"  ! {day} {isl}: 線構成の署名が基準と違う → 使わない")
                continue
            if isl not in keys_of:
                base = json.loads((base_dir / f"flows_{isl}.geojson").read_text(encoding="utf-8"))
                keys_of[isl] = [f["properties"].get("k", "") for f in base["features"]]
            for k, row in zip(keys_of[isl], D["p"]):
                if not k or not row:
                    continue
                for h, x in enumerate(row):
                    if x is not None:
                        model[isl][k][(day, h)] = float(x)
    return model, used


def model_value(rec: dict, model: dict, key_t) -> float | None:
    """照合の最初の区間(平行する線の束)を、OCCTO の正方向にそろえて合算する。平行線をまとめた線は回線数で按分。"""
    seg0 = rec["segs"][0]
    tot_par = sum(par for _, _, par in seg0)
    nco = rec.get("n_circ_obs")
    scale = (nco / tot_par) if nco and tot_par > nco else 1.0
    v, ok = 0.0, False
    for k, sg, _ in seg0:
        mv = model[rec["island"]].get(k, {}).get(key_t)
        if mv is not None:
            v += sg * mv
            ok = True
    return v * scale if ok else None


def line_score(obs: list, mod: list, single_ended: bool) -> dict | None:
    """時刻をそろえた系列どうしの物差し。single_ended(向きを決めていない照合)は大きさだけ比べる。"""
    if len(obs) < MIN_HOURS:
        return None
    xs, ys = ([abs(x) for x in obs], [abs(y) for y in mod]) if single_ended else (obs, mod)
    mo, mm = st.mean(abs(x) for x in obs), st.mean(abs(y) for y in mod)
    err = [y - x for x, y in zip(xs, ys)]
    rmse = math.sqrt(sum(e * e for e in err) / len(err))
    return {
        "n": len(obs), "obs_absmean": mo, "mod_absmean": mm,
        "ratio": (mm / mo) if mo > 1 else None,
        "r_time": pearson(xs, ys),
        "sign_ok": None if single_ended else (
            st.mean(obs) * st.mean(mod) > 0 or (abs(st.mean(obs)) < QUIET_MW and abs(st.mean(mod)) < QUIET_MW)),
        "rmse": rmse, "bias": st.mean(err),
        "nrmse_obs": (rmse / mo) if mo > 1 else None,
    }


def score(today: dict, cw: dict, days_dir: Path, base_dir: Path = FM) -> tuple[list, list]:
    obs = observed_hourly(today)
    model, used = model_hourly(days_dir, today["days"], base_dir)
    rows = []
    for r in cw["lines"]:
        if not r.get("conf"):
            continue
        lid = f"{r['area']}|{r['line']}|{r['direction']}"
        xs, ys = [], []
        for key_t, ov in sorted((obs.get(lid) or {}).items()):
            mv = model_value(r, model, key_t)
            if mv is not None:
                xs.append(ov)
                ys.append(mv)
        single = bool(r.get("single_ended")) or r["conf"] == "C"
        s = line_score(xs, ys, single)
        if not s:
            continue
        cap = capacity_of(today, lid)
        rows.append({"id": lid, "area": r["area"], "island": r["island"], "kv": r["kv"], "conf": r["conf"],
                     **s, "cap": cap, "nrmse_cap": (s["rmse"] / cap) if cap else None})
    return rows, used


def summarize(rows: list) -> dict:
    def med(k):
        v = [x[k] for x in rows if x.get(k) is not None]
        return round(st.median(v), 3) if v else None

    def share(k, f):
        v = [x[k] for x in rows if x.get(k) is not None]
        return round(sum(1 for x in v if f(x)) / len(v), 3) if v else None

    tot_obs = sum(x["obs_absmean"] for x in rows)
    return {
        "n": len(rows),
        "ratio_med": med("ratio"),
        "within_x2": share("ratio", lambda x: 0.5 <= x <= 2),
        "within_x125": share("ratio", lambda x: 0.8 <= x <= 1.25),
        "r_time_med": med("r_time"),
        "r_time_gt05": share("r_time", lambda x: x > 0.5),
        "sign_ok": share("sign_ok", lambda x: x),
        "nrmse_obs_med": med("nrmse_obs"),
        "nrmse_cap_med": med("nrmse_cap"),
        "sum_rmse_over_sum_obs": round(sum(x["rmse"] for x in rows) / tot_obs, 3) if tot_obs > 0 else None,
    }


def groups(rows: list) -> dict:
    out = {"全体": summarize(rows)}
    for kv in sorted({x["kv"] for x in rows}, reverse=True):
        out[f"{kv:.0f} kV"] = summarize([x for x in rows if x["kv"] == kv])
    for c in "ABC":
        sub = [x for x in rows if x["conf"] == c]
        if sub:
            out[f"照合 {c}"] = summarize(sub)
    for isl in sorted({x["island"] for x in rows}):
        out[f"島 {isl}"] = summarize([x for x in rows if x["island"] == isl])
    for ar in sorted({x["area"] for x in rows}):
        out[f"エリア {ar}"] = summarize([x for x in rows if x["area"] == ar])
    return out


def build_crosswalk(today: dict, out: Path) -> None:
    """当日分に入っている線路の一覧から、対応表を作る(scripts/build_occto_line_crosswalk.py を呼ぶ)。"""
    with tempfile.TemporaryDirectory() as td:
        lines = Path(td) / "occto_lines.csv"
        with open(lines, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["area", "voltage_kV", "line", "direction"])
            for lid, v in today["lines"].items():
                area, name, direction = lid.split("|", 2)
                w.writerow([area, v["kv"], name, direction])
        subprocess.run([sys.executable, str(ROOT / "scripts" / "build_occto_line_crosswalk.py"),
                        "--lines", str(lines), "--out", str(out)], check=True, cwd=ROOT,
                       env={**os.environ, "PYTHONPATH": str(ROOT)})


def _fmt(x, pct=False, sign=False):
    if x is None:
        return "  –  "
    if pct:
        return f"{x:5.0%}"
    return f"{x:+5.2f}" if sign else f"{x:5.2f}"


def print_table(label: str, g: dict) -> None:
    print(f"\n[{label}]")
    print(f"  {'':16s}   本   比    ×2内 ×1.25内  時間の相関  r>0.5   向き  誤差/観測 誤差/容量 ΣRMSE/Σ|観測|")
    for name, s in g.items():
        print(f"  {name:16s} {s['n']:4d} ×{_fmt(s['ratio_med'])} {_fmt(s['within_x2'], True)}  {_fmt(s['within_x125'], True)}"
              f"     {_fmt(s['r_time_med'], sign=True)}  {_fmt(s['r_time_gt05'], True)}  {_fmt(s['sign_ok'], True)}"
              f"     {_fmt(s['nrmse_obs_med'])}    {_fmt(s['nrmse_cap_med'])}       {_fmt(s['sum_rmse_over_sum_obs'])}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--today", type=Path, default=FM / "occto_today.json")
    ap.add_argument("--days-dir", nargs="+", default=[f"いま={FM / 'days'}"], help="名前=フォルダ(複数可)")
    ap.add_argument("--crosswalk", type=Path, default=DEFAULT_CW)
    ap.add_argument("--build-crosswalk", action="store_true", help="対応表を当日分の線路の一覧から作り直す")
    ap.add_argument("--out", type=Path, help="集計を書く JSON")
    ap.add_argument("--rows", type=Path, help="線路ごとの行を書く JSON(git に入れない場所へ)")
    a = ap.parse_args()

    today = json.loads(a.today.read_text(encoding="utf-8"))
    if a.build_crosswalk or not a.crosswalk.exists():
        if not a.build_crosswalk:
            print(f"対応表 {a.crosswalk} が無い → --build-crosswalk を付けて作る")
            return 1
        build_crosswalk(today, a.crosswalk)
    cw = json.loads(a.crosswalk.read_text(encoding="utf-8"))
    out = {"note": "同時刻の採点(観測 = OCCTO 地内基幹送電線潮流実績の 30 分値を 1 時間の平均にしたもの、"
                   "モデル = 日別断面)。集計だけ。出典: 電力広域的運営推進機関 系統情報サービス",
           "method": "scripts/score_sync_flows.py", "today_made": today.get("made"),
           "crosswalk_built_sha256": cw.get("built_sha256"), "runs": {}}
    all_rows = {}
    for spec in a.days_dir:
        label, _, path = spec.partition("=")
        if not path:
            label, path = "いま", spec
        rows, used = score(today, cw, Path(path))
        if not rows:
            print(f"[{label}] 重なる日が無い({path})")
            continue
        g = groups(rows)
        print(f"\n日 = {used} / 突き合わせた線路 {len(rows)} 本(1 本あたりの時刻の中央値 {st.median(x['n'] for x in rows):.0f})")
        print_table(label, g)
        out["runs"][label] = {"days": used, "groups": g}
        all_rows[label] = rows
    if a.out:
        a.out.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"\n-> {a.out}")
    if a.rows:
        a.rows.write_text(json.dumps(all_rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"-> {a.rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
