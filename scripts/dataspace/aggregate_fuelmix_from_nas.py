#!/usr/bin/env python3
"""研究室 NAS の電源種別実績を、エリア別の電源構成に集約する（源泉側で実行）。

`docs/DATA_SPACE.md` の zero-copy 原則にもとづき、NAS をマウントしたサーバー側で走らせ、
10 社 × 数年分の 30 分/1 時間値（数百MB）を **エリア × 電源種別の要約**（数十KB）に畳む。

用途: モデルの発電構成が実態とどれだけずれているかの検証。特に**太陽光**は
モデルが 6,274MW（OSM 由来のメガソーラーのみ・屋根置きは載らない）しか持たないのに対し、
実系統では正午に大きな出力を出す。この差が潮流の形を左右する
（`docs/reports/demand_validation_*.md` で需要側は無罪と分かっている）。

各社の CSV は方言がある（CP932・ヘッダ2行・列名の揺れ）ので、
**列名を日本語キーワードで拾う**方式にして社ごとの分岐を避ける。

usage（NAS をマウントしたサーバー上で）:
    python3 aggregate_fuelmix_from_nas.py --src /mnt/nas03/demand_raw \
        --out /tmp/fuelmix_by_area.csv --peak-out /tmp/fuelmix_peaks.csv
"""
from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path

# 列名に含まれるキーワード → 正規化した電源種別
FUEL_KEYS = [
    ("エリア需要", "demand"),
    ("原子力", "nuclear"),
    ("火力", "thermal"),
    ("水力", "hydro"),
    ("地熱", "geothermal"),
    ("バイオマス", "biomass"),
    ("揚水", "pumped"),
    ("連系線", "interconnector"),
    ("蓄電池", "battery"),
]
# ファイル名の規約は社ごとにバラバラ（202308.csv / year_2024.csv / H29_Q2.csv）。
# 名前で絞らず**中身で判定**する: 太陽光の列があり HTML でない CSV だけを採る。


def parse_header(rows: list[list[str]]) -> tuple[int, dict[int, str]]:
    """ヘッダを解いて 列index → 電源種別 の対応を返す。

    社ごとに形式が違うので、**ヘッダらしい行を先頭数行から探す**方式にする:
      - 関西型: 2行ヘッダ（上段に太陽光/風力のグループ名、下段に実績/抑制量）
      - 北海道型: 1行に「太陽光発電実績」「太陽光出力制御量」まで畳んだ列名
      - 需要のみの社（東北の `実績(万kW)` 等）は太陽光列が無いので呼び出し側で弾く
    """
    if not rows:
        return 0, {}
    # ヘッダ行の判定。中部のように**説明文**が先頭に数行入る社があり
    # （「太陽光の自家消費分は…」）、単に「太陽光」を含む行を採ると文章を掴む。
    # そこで「日付列らしきものがあり、かつ太陽光列がある」行だけをヘッダとみなす。
    DATE_KEYS = ("DATE", "日付", "年月日", "dt")
    hdr_i = None
    for i, r in enumerate(rows[:8]):
        cells = [(c or "").strip() for c in r]
        has_date = any(any(k in c.upper() or k in c for k in DATE_KEYS) for c in cells[:2])
        has_solar = any("太陽光" in c for c in cells)
        if has_date and has_solar:
            hdr_i = i
            break
    if hdr_i is None:
        # 関西型は上段がグループ名なので、下段に DATE_TIME がある形も許す
        for i, r in enumerate(rows[:8]):
            if any("DATE_TIME" in (c or "").upper() for c in r):
                if any("太陽光" in (c or "") for c in (rows[i - 1] if i else [])):
                    hdr_i = i
                    break
    if hdr_i is None:
        return 0, {}
    hdr = rows[hdr_i]
    top = rows[hdr_i - 1] if hdr_i > 0 else []
    colmap: dict[int, str] = {}
    for i, c in enumerate(hdr):
        c = (c or "").strip()
        grp = (top[i] if i < len(top) else "").strip()
        if "太陽光" in c:
            # 「エリア風力・太陽光発電量」のような**合算列**は太陽光単独ではないので採らない
            # （中部の keito_jisseki 系ファイルに混在。単位も別で 2,391,000 という
            #   桁違いの値になり、9434% という異常な太陽光比率を生んでいた）
            if "風力" in c:
                continue
            colmap[i] = "solar_curtailed" if ("制御" in c or "抑制" in c) else "solar"
            continue
        if "風力" in c:
            colmap[i] = "wind_curtailed" if ("制御" in c or "抑制" in c) else "wind"
            continue
        if "太陽光" in grp:                     # 関西型（上段がグループ名）
            colmap[i] = "solar" if "実績" in c else "solar_curtailed"
            continue
        if "風力" in grp:
            colmap[i] = "wind" if "実績" in c else "wind_curtailed"
            continue
        for kw, name in FUEL_KEYS:
            if kw in c:
                colmap[i] = name
                break
    return hdr_i + 1, colmap


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=Path("/mnt/nas03/demand_raw"))
    ap.add_argument("--out", type=Path, required=True, help="エリア×電源の要約")
    ap.add_argument("--peak-out", type=Path, default=None, help="太陽光ピークの時刻別分布")
    ap.add_argument("--since", default="2023",
                    help="この年以降のデータのみ（DATE_TIME 列の先頭4桁で判定）")
    args = ap.parse_args()

    # area -> fuel -> [values]
    agg: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    # area -> hour -> [solar]
    by_hour: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    n_files = n_rows = 0

    for area_dir in sorted(p for p in args.src.iterdir() if p.is_dir()):
        area = area_dir.name
        for f in sorted(area_dir.glob("*.csv")):
            try:
                with open(f, encoding="cp932", errors="replace", newline="") as fh:
                    rows = list(csv.reader(fh))
            except Exception:
                continue
            if len(rows) < 3 or "<!DOCTYPE" in "".join(rows[0])[:40].upper():
                continue          # 取得失敗の HTML が紛れている
            start, colmap = parse_header(rows)
            if "solar" not in colmap.values():
                continue          # 需要のみの社はここで落ちる
            # 単位の方言: 「万kW」表記は MW に直す（1万kW = 10MW）
            unit_scale = 10.0 if any("万kW" in (c or "") for r0 in rows[:6] for c in r0) else 1.0
            n_files += 1
            for r in rows[start:]:
                if not r or not r[0].strip():
                    continue
                ym = re.match(r"(\d{4})", r[0].strip().replace("/", "-"))
                if ym and ym.group(1) < args.since:
                    continue          # 期間の絞り込みは中身の日付で行う
                n_rows += 1
                hour = None
                joined = " ".join(r[:2])          # DATE,TIME に分かれる社もある
                m = re.search(r"(?:\s|^)(\d{1,2}):\d{2}", joined)
                if m:
                    hour = int(m.group(1))
                for i, fuel in colmap.items():
                    if i >= len(r):
                        continue
                    try:
                        v = float(str(r[i]).replace(",", "").strip())
                    except ValueError:
                        continue
                    v *= unit_scale
                    agg[area][fuel].append(v)
                    if fuel == "solar" and hour is not None:
                        by_hour[area][hour].append(v)

    fuels = sorted({f for m in agg.values() for f in m})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["area", "fuel", "n", "mean_mwh", "median_mwh", "max_mwh", "p95_mwh"])
        for area in sorted(agg):
            for fuel in fuels:
                v = sorted(agg[area].get(fuel, []))
                if not v:
                    continue
                n = len(v)
                w.writerow([area, fuel, n,
                            round(sum(v) / n, 1), round(v[n // 2], 1), round(v[-1], 1),
                            round(v[int(n * 0.95)], 1)])

    if args.peak_out:
        with open(args.peak_out, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["area", "hour", "n", "mean_solar_mwh", "max_solar_mwh"])
            for area in sorted(by_hour):
                for h in sorted(by_hour[area]):
                    v = by_hour[area][h]
                    w.writerow([area, h, len(v), round(sum(v) / len(v), 1), round(max(v), 1)])

    print(f"ファイル {n_files} / 行 {n_rows:,} を集約 → {args.out}")
    print("エリア: " + " ".join(sorted(agg)))
    for area in sorted(agg):
        s = agg[area].get("solar", [])
        d = agg[area].get("demand", [])
        if s and d:
            print(f"  {area:10s} 太陽光 最大 {max(s):8,.0f} MWh / 需要 最大 {max(d):8,.0f} MWh "
                  f"（太陽光ピーク比 {max(s)/max(d):5.1%}）")


if __name__ == "__main__":
    main()
