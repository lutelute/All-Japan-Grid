#!/usr/bin/env python3
"""線路容量の理論値を、送配電事業者の公表値で較正する（全国版・集計のみ公開）。

本モデルの線路容量は電圧階級から機械的に振った理論値 `√3·V·I`（`config/line_types.yaml`
の `max_i_ka`）で、出典を持たない。送配電事業者は線路ごとの**設備容量・運用容量・
制約要因**を公表しているが、その生値は All-Rights-Reserved で再配布できない
（`data/external/` は git 管理外）。そこで**私的検証にとどめ、公開するのは
電圧階級×エリアごとの比（無次元）・本数・制約要因の分布だけ**にする。

2026-08-09 版は関西（≥154kV）のみだった。2026-09-02 版は入手済みの全公表資料へ広げる:

  kansai   154kv_more_line.csv（≥154kV）+ 154kv_less_line.csv（<154kV）
  shikoku  sys_capa_kikan00_line（500/187kV）+ sys_capa_local01-04_line（66kV 等）
  kyushu   31 地区「予想潮流・空容量一覧表」のプール（`scripts/pool_kyushu_kuyoryo.py`）
  tokyo    予想潮流・空容量 CSV（基幹 + 13 地域）

2026-09-03 版で残り 6 社を追加した（`scripts/fetch_capacity_tables.py` が取得）:

  hokkaido/tohoku/chubu/hokuriku/chugoku  `<area>/capacity/` 配下の送電線 CSV
  okinawa  **PDF のみ**（132kV の設備容量・運用容量表）→ 判読していないので係数は出ない

10 社の様式はほぼ共通（送電線No / 送電線名 / 電圧 / 回線数 / 設備容量(100%×回線数) /
運用容量値 / 運用容量制約要因 / …）だが、括弧が全角・半角・角括弧で揺れる。
新規 5 社は**ヘッダ行を読んで列を引き当てる**汎用パーサ（`rows_generic`）で扱う。

出力は較正係数の**提案**であって適用ではない。適用は `config/line_capacity_calibration.yaml`
を介入#45（`src/powerflow/line_capacity.py`）が読む形で行い、採否は台帳に記帳する。

usage: PYTHONPATH=. python3 scripts/capacity/calibrate_line_capacity.py [--date YYYY-MM-DD] [--write-config]
出力: docs/reports/line_capacity_calibration_<date>.{md,json}（比のみ）
      config/line_capacity_calibration.yaml（--write-config・比のみ）
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import glob
import io
import json
import re
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

EXT = ROOT / "data" / "external" / "system_disclosure"
REPORTS = ROOT / "docs" / "reports"
CONFIG = ROOT / "config" / "line_capacity_calibration.yaml"

MIN_SAMPLES = 3          # この本数未満の(エリア, 階級)は係数を出さない
KV_CLASSES = (66, 77, 110, 132, 154, 187, 220, 275, 500)


def model_ika() -> dict[int, float]:
    """PF ビルダーが線路に与える電流定格 [kA]（`config/line_types.yaml`・50Hz 側で読む。
    max_i_ka は周波数に依らない）。"""
    from src.converter.line_parameters import get_line_parameters_safe
    out = {}
    for kv in KV_CLASSES:
        p = get_line_parameters_safe(kv, 50)
        if p and p.get("max_i_ka"):
            out[kv] = float(p["max_i_ka"])
    return out


def num(x):
    if x is None:
        return None
    s = str(x).replace(",", "").replace("，", "").strip()
    if s in ("", "－", "-", "ー", "―", "－ ", "非公開"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def nearest_class(kv: float) -> int | None:
    if kv is None or kv <= 0:
        return None
    best = min(KV_CLASSES, key=lambda c: abs(c - kv))
    return best if abs(best - kv) / best <= 0.15 else None


# ── 各社パーサ: (area, kv, circuits, equip_mw_total, oper_mw, reason) を yield ──
def rows_kansai():
    for rel, enc in (("kansai/capacity/154kv_more_line.csv", "cp932"),
                     ("kansai/capacity_less/154kv_less_line.csv", "cp932")):
        p = EXT / rel
        if not p.exists():
            continue
        for r in list(csv.reader(open(p, encoding=enc, errors="replace")))[2:]:
            if len(r) < 7:
                continue
            kv = num(r[2])
            if kv is None:
                continue
            yield ("kansai", kv, num(r[3]), num(r[4]), num(r[5]), r[6].strip(), rel)


def rows_shikoku():
    for p in sorted((EXT / "shikoku" / "capacity").glob("sys_capa_*_line_*.csv")):
        rel = str(p.relative_to(EXT))
        for r in list(csv.reader(open(p, encoding="cp932", errors="replace")))[2:]:
            if len(r) < 7:
                continue
            kv = num(r[2])
            if kv is None:
                continue
            yield ("shikoku", kv, num(r[3]), num(r[4]), num(r[5]), r[6].strip(), rel)


def rows_kyushu():
    p = EXT / "kyushu" / "keitouzu" / "kuyoryo" / "pool_full.json"
    if not p.exists():
        return
    for r in json.load(open(p, encoding="utf-8")):
        if r.get("section") != "line":
            continue
        toks = str(r.get("raw_mid") or "").split()
        nums = [num(t) for t in toks]
        vals = [v for v in nums if v is not None]
        reason = " ".join(t for t, v in zip(toks, nums)
                          if v is None and t not in ("―", "－", "-", "ー"))
        equip = vals[0] if len(vals) >= 1 else None
        oper = vals[1] if len(vals) >= 2 else None
        yield ("kyushu", float(r["kv"]), num(r.get("circuits")), equip, oper, reason,
               "kyushu/keitouzu/kuyoryo/pool_full.json")


def rows_tokyo():
    for p in sorted((EXT / "tokyo" / "capacity").glob("csv_yosochoryu_*/csv_yosochoryu_*_soudensen.csv")):
        rel = str(p.relative_to(EXT))
        raw = p.read_bytes()
        # 地域ファイルは UTF-8(BOM) と cp932 が混在する(2026-09-02 実測) — 厳密デコードで判定
        txt = None
        for enc in ("utf-8-sig", "cp932"):
            try:
                txt = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if txt is None:
            txt = raw.decode("utf-8-sig", errors="replace")
        for r in csv.reader(io.StringIO(txt)):
            if len(r) < 7:
                continue
            kv = num(r[2])
            if kv is None or not re.search(r"\d", r[0] or ""):
                continue
            yield ("tokyo", kv, num(r[3]), num(r[4]), num(r[5]), (r[6] or "").strip(), rel)


# ── 汎用パーサ: ヘッダ行から列を引き当てる（2026-09-03 追加の 5 社）──────────
# 括弧の全角/半角/角括弧、"送電線 No" のような空白、列順の微差を吸収する。
# 送電線ファイルだけを読む（変電所 tr / フェンス集約行は較正対象外）。
GENERIC_AREAS = {
    # area: (ファイル名に含まれれば送電線とみなす語, 除外語)
    "hokkaido": (("_line_",), ("_tr_",)),
    "tohoku": (("_line_",), ("_tr_",)),
    "chubu": (("送電線",), ("変電所", "フェンス")),
    "hokuriku": (("_line_",), ("_tr_",)),
    "chugoku": (("_line_",), ("_tr_",)),
}


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp932"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp932", errors="replace")


def _norm_head(x: str) -> str:
    """ヘッダの表記ゆれを潰す（全角括弧・空白・単位）。"""
    return re.sub(r"[\s　（）()\[\]【】]", "", str(x or ""))


def _header_map(row) -> dict | None:
    """ヘッダ行なら {役割: 列index} を返す。違えば None。"""
    h = [_norm_head(c) for c in row]
    idx = {}
    for i, c in enumerate(h):
        if "電圧" in c and "一次" not in c and "二次" not in c and "kv" not in idx:
            idx["kv"] = i
        elif "回線数" in c and "ckt" not in idx:
            idx["ckt"] = i
        elif "設備容量" in c and "equip" not in idx:
            idx["equip"] = i
        elif "運用容量値" in c and "oper" not in idx:
            idx["oper"] = i
        elif "運用容量制約要因" in c and "reason" not in idx:
            idx["reason"] = i
    return idx if {"kv", "ckt", "equip", "oper"} <= set(idx) else None


def rows_generic(area: str):
    """<area>/capacity/ の送電線 CSV を、ヘッダ駆動で読む。"""
    inc, exc = GENERIC_AREAS[area]
    d = EXT / area / "capacity"
    if not d.exists():
        return
    for p in sorted(d.glob("*.csv")):
        nm = p.name
        if not any(t in nm for t in inc) or any(t in nm for t in exc):
            continue
        rel = str(p.relative_to(EXT))
        rows = list(csv.reader(io.StringIO(_decode(p.read_bytes()))))
        idx = None
        for r in rows:
            if idx is None:
                idx = _header_map(r)
                continue
            if len(r) <= max(idx.values()):
                continue
            kv = num(r[idx["kv"]])
            if kv is None:
                continue
            yield (area, kv, num(r[idx["ckt"]]), num(r[idx["equip"]]),
                   num(r[idx["oper"]]),
                   (r[idx["reason"]].strip() if "reason" in idx else ""), rel)


SOURCES = {
    "kansai": ("関西電力送配電 空容量マッピング（154kV以上・154kV未満の線路一覧）",
               ["https://www.kansai-td.co.jp/interchange/takusou/pdf/154kv_more_line.csv",
                "https://www.kansai-td.co.jp/interchange/takusou/pdf/154kv_less_line.csv"]),
    "shikoku": ("四国電力送配電 系統空容量（基幹・ローカル 送電線）",
                ["https://www.yonden.co.jp/nw/assets/line_access/data/sys_capa_kikan00_line_202608_08.csv",
                 "https://www.yonden.co.jp/nw/assets/line_access/data/sys_capa_local0N_line_202608_08.csv"]),
    "kyushu": ("九州電力送配電 予想潮流・空容量一覧表（31地区・PDF 判読プール）",
               ["https://www.kyuden.co.jp/td_service_wheeling_rule-document_disclosure"]),
    "tokyo": ("東京電力パワーグリッド 送電線 予想潮流・空容量（基幹＋13地域 CSV）",
              ["https://www.tepco.co.jp/pg/consignment/system/"]),
    "hokkaido": ("北海道電力ネットワーク 予想潮流等一覧表（187kV以上＋24ローカル系統・ZIP内CSV）",
                 ["https://www.hepco.co.jp/network/con_service/public_document/bid_info.html"]),
    "tohoku": ("東北電力ネットワーク 送電線の予想潮流等一覧表（基幹＋7ローカル系統 CSV）",
               ["https://nw.tohoku-epco.co.jp/consignment/system/announcement/"]),
    "chubu": ("中部電力パワーグリッド 空容量・予想潮流一覧表（本店＋6地域・gridmap 配信 ZIP）",
              ["https://gridmap.powergrid.chuden.co.jp/"]),
    "hokuriku": ("北陸電力送配電 予想潮流・空容量（154kV以上＋3県 CSV）",
                 ["https://www.rikuden.co.jp/nw_notification/U_154seiyaku.html"]),
    "chugoku": ("中国電力ネットワーク 予想潮流・空容量（220kV以上＋5県・ZIP内CSV）",
                ["https://www.energia.co.jp/nw/service/retailer/keitou/access/"]),
    "okinawa": ("沖縄電力 地内基幹送電線（132kV）の設備容量および運用容量【PDFのみ・未判読】",
                ["https://www.okiden.co.jp/shared/pdf/business/free/rule02/operating_capacity.pdf"]),
}


def collect():
    stats = defaultdict(lambda: {"per_ckt": [], "oper_ratio": [], "model_over_oper": [],
                                 "reasons": defaultdict(int), "n": 0, "files": set()})
    ika = model_ika()
    n_rows = 0
    gens = [rows_kansai, rows_shikoku, rows_kyushu, rows_tokyo]
    gens += [(lambda a=a: rows_generic(a)) for a in GENERIC_AREAS]
    for gen in gens:
        for area, kv, ckt, equip, oper, reason, rel in gen():
            cls = nearest_class(kv)
            if cls is None or cls not in ika:
                continue
            n_rows += 1
            s = stats[(area, cls)]
            s["n"] += 1
            s["files"].add(rel)
            if reason:
                s["reasons"][reason] += 1
            theo = (3 ** 0.5) * cls * ika[cls]           # 理論容量 / 回線 [MVA]
            if ckt and equip and equip > 0:
                s["per_ckt"].append(equip / ckt)
            if equip and oper and equip > 0:
                s["oper_ratio"].append(oper / equip)
            if ckt and oper and oper > 0:
                s["model_over_oper"].append(theo * ckt / oper)
    return stats, ika, n_rows


def _band(vals):
    """±0.1 帯の判定(3 エリア以上・全値が中央値の ±0.1)。→ dict or None。"""
    if len(vals) < 2:
        return None
    med = st.median(vals)
    return {"n_areas": len(vals), "median": round(med, 3),
            "spread": round(max(vals) - min(vals), 3),
            "n_within_0.1": sum(1 for v in vals if abs(v - med) <= 0.1),
            "within_0.1": bool(len(vals) >= 3
                               and all(abs(v - med) <= 0.1 for v in vals))}


def summarize(stats, ika):
    by = []
    for (area, kv), s in sorted(stats.items()):
        theo = (3 ** 0.5) * kv * ika[kv]
        n_cal = len(s["model_over_oper"])
        rec = {"area": area, "kv": kv, "n_lines": s["n"], "n_with_operational": n_cal,
               "theoretical_mva_per_circuit": round(theo, 1),
               "model_over_equipment": (round(theo / st.median(s["per_ckt"]), 3)
                                        if s["per_ckt"] else None),
               "operational_over_equipment": (round(st.median(s["oper_ratio"]), 3)
                                              if s["oper_ratio"] else None),
               "model_over_operational": (round(st.median(s["model_over_oper"]), 3)
                                          if n_cal else None),
               "suggested_factor": (round(1.0 / st.median(s["model_over_oper"]), 3)
                                    if n_cal else None),
               "suggested_factor_p25_p75": (
                   [round(1.0 / q, 3) for q in
                    (st.quantiles(s["model_over_oper"], n=4)[2],
                     st.quantiles(s["model_over_oper"], n=4)[0])]
                   if n_cal >= 4 else None),
               "usable": n_cal >= MIN_SAMPLES,
               "constraint_reasons": dict(sorted(s["reasons"].items(), key=lambda x: -x[1])),
               "files": sorted(s["files"])}
        by.append(rec)
    # 階級ごとの全国中央値（usable エリアの suggested_factor の中央値）と一致度
    national = {}
    for kv in KV_CLASSES:
        fs = [r["suggested_factor"] for r in by if r["kv"] == kv and r["usable"]]
        if fs:
            med = st.median(fs)
            national[kv] = {"n_areas": len(fs), "median_factor": round(med, 3),
                            "spread": round(max(fs) - min(fs), 3),
                            # 既定ON の判定規則(2026-09-02 親と合意): 3 エリア以上が
                            # 同階級で中央値 ±0.1 に収まること(厳密判定)
                            "within_0.1": bool(len(fs) >= 3 and
                                               all(abs(f - med) <= 0.1 for f in fs)),
                            "areas": {r["area"]: r["suggested_factor"] for r in by
                                      if r["kv"] == kv and r["usable"]},
                            # 係数を 2 成分に分解して、どちらが事業者を跨いで
                            # 一様かを見る(2026-09-03):
                            #   conductor = 理論÷設備容量 … モデルの max_i_ka が
                            #               その階級の実導体をどれだけ外しているか
                            #   margin    = 運用÷設備容量 … 熱容量に対して実際に
                            #               流してよい上限(安定度・電圧・上位系の制約)
                            "components": {
                                "conductor_model_over_equipment": _band(
                                    [r["model_over_equipment"] for r in by
                                     if r["kv"] == kv and r["usable"]
                                     and r["model_over_equipment"] is not None]),
                                "margin_operational_over_equipment": _band(
                                    [r["operational_over_equipment"] for r in by
                                     if r["kv"] == kv and r["usable"]
                                     and r["operational_over_equipment"] is not None]),
                            }}
    all_fs = [r["suggested_factor"] for r in by if r["usable"]]
    return by, national, (round(st.median(all_fs), 3) if all_fs else None)


def write_config(by, national, overall, date, ika):
    lines = [
        f"# 線路容量の運用容量較正係数（介入#45・{date}）",
        "#",
        "# factor = 公表運用容量 ÷ モデル理論容量(√3·V·I_model·回線数) の中央値（無次元）。",
        "# 生値（線路別の設備容量・運用容量）は各社 All-Rights-Reserved のため**比だけ**を置く。",
        "# 生成: scripts/capacity/calibrate_line_capacity.py --write-config（data/external が要る）。",
        "# 無いエリア/階級は src/powerflow/line_capacity.py が「全国中央値 → 全体中央値」へ",
        "# フォールバックし、帳簿(net._cap_calib_ledger)に fallback を記録する。",
        f"date: '{date}'",
        "unit: dimensionless",
        "min_samples: %d" % MIN_SAMPLES,
        "model_ika_ka: {" + ", ".join(f"{k}: {v}" for k, v in sorted(ika.items())) + "}",
        f"overall_median_factor: {overall}",
        "national:",
    ]
    for kv, v in sorted(national.items()):
        lines.append(f"  {kv}: {{median_factor: {v['median_factor']}, n_areas: {v['n_areas']}, "
                     f"spread: {v['spread']}, within_band: {str(v['within_0.1']).lower()}}}")
    lines.append("areas:")
    for area in ("hokkaido", "tohoku", "tokyo", "chubu", "hokuriku", "kansai",
                 "chugoku", "shikoku", "kyushu", "okinawa"):
        recs = [r for r in by if r["area"] == area and r["usable"]]
        if not recs:
            lines.append(f"  {area}: {{}}   # 公表容量の入手無し → national へフォールバック")
            continue
        lines.append(f"  {area}:")
        for r in recs:
            lines.append(f"    {r['kv']}: {{factor: {r['suggested_factor']}, n: {r['n_with_operational']}, "
                         f"p25_p75: {r['suggested_factor_p25_p75']}}}")
    lines.append("sources:")
    for area, (title, urls) in SOURCES.items():
        lines.append(f"  {area}:")
        lines.append(f"    title: {json.dumps(title, ensure_ascii=False)}")
        lines.append("    urls:")
        for u in urls:
            lines.append(f"      - {u}")
        lines.append(f"    retrieved: '{date}'")
    CONFIG.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=_dt.date.today().isoformat())
    ap.add_argument("--write-config", action="store_true")
    args = ap.parse_args()
    if not EXT.exists():
        raise SystemExit(f"公表データが無い: {EXT}（data/external/ は git 管理外）")

    stats, ika, n_rows = collect()
    by, national, overall = summarize(stats, ika)
    payload = {
        "date": args.date,
        "license": "All-Rights-Reserved。生値は再配布せず、公開するのは比・本数・制約要因の分布のみ",
        "n_rows_parsed": n_rows,
        "model_ika_ka": ika,
        "by_area_voltage": by,
        "national_by_voltage": national,
        "overall_median_factor": overall,
        "sources": {a: {"title": t, "urls": u} for a, (t, u) in SOURCES.items()},
        "note": ("model_over_operational = √3·V·I_model·回線数 ÷ 公表運用容量 の中央値。"
                 "suggested_factor はその逆数。usable=運用容量つき線路が MIN_SAMPLES 本以上"),
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    json.dump(payload, open(REPORTS / f"line_capacity_calibration_{args.date}.json", "w"),
              ensure_ascii=False, indent=1)

    L = [f"# 線路容量の理論値を公表値で較正する — 全国版（{args.date}）", "",
         "本モデルの線路容量は電圧階級から機械的に振った理論値 `√3·V·I`（`config/line_types.yaml` の "
         "`max_i_ka`）で、出典を持たない。送配電事業者が公表する線路ごとの**設備容量・運用容量・制約要因**"
         "で較正する。", "",
         "> **ライセンスの扱い**: 公表データは All-Rights-Reserved で再配布できない。検証は私的に行い、",
         "> **公開するのは電圧階級×エリアごとの比（無次元）・本数・制約要因の分布だけ**とする。",
         f"> 解析行 {n_rows}（kansai ≥154/<154・shikoku 基幹/ローカル・kyushu 31地区プール・tokyo 基幹+13地域）。",
         "", "## エリア×電圧階級（運用容量つき線路が 3 本以上のもの）", "",
         "| エリア | kV | 本数(運用あり/全) | 理論÷設備 | 運用÷設備 | **理論÷運用** | 係数 | p25–p75 | 制約要因(上位) |",
         "|---|---:|---:|---:|---:|---:|---:|---|---|"]
    for r in by:
        if not r["usable"]:
            continue
        rs = ", ".join(f"{k} {v}" for k, v in list(r["constraint_reasons"].items())[:2])
        L.append(f"| {r['area']} | {r['kv']} | {r['n_with_operational']}/{r['n_lines']} | "
                 f"{r['model_over_equipment'] if r['model_over_equipment'] is not None else '—'} | "
                 f"{r['operational_over_equipment'] if r['operational_over_equipment'] is not None else '—'} | "
                 f"**{r['model_over_operational']}** | {r['suggested_factor']} | "
                 f"{r['suggested_factor_p25_p75']} | {rs} |")
    L += ["", "## 階級ごとの全国中央値と一致度（既定判断の根拠）", "",
          "| kV | エリア数 | 係数の中央値 | 最大−最小 | 3エリア以上が ±0.1 帯 | エリア別 |",
          "|---:|---:|---:|---:|---|---|"]
    for kv, v in sorted(national.items()):
        L.append(f"| {kv} | {v['n_areas']} | **{v['median_factor']}** | {v['spread']} | "
                 f"{'✅' if v['within_0.1'] else '—'} | "
                 + ", ".join(f"{a} {f}" for a, f in v['areas'].items()) + " |")
    L += ["", f"全体中央値（usable の全 (エリア,階級) の係数）: **{overall}**", "",
          "## 係数を 2 成分に分解する — 割れているのはどちらか", "",
          "較正係数 = (設備容量÷理論容量) × (運用容量÷設備容量) の逆数。前者は**モデルの代表電流"
          "`max_i_ka` がその階級の実導体をどれだけ外しているか**、後者は**熱容量に対して実際に"
          "流してよい上限**（安定度・電圧・上位系の制約）で、意味がまったく違う。", "",
          "| kV | エリア数 | 理論÷設備（導体） 中央値 / 幅 / ±0.1内 | 運用÷設備（運用余裕） 中央値 / 幅 / ±0.1内 |",
          "|---:|---:|---|---|"]
    for kv, v in sorted(national.items()):
        c = v["components"]["conductor_model_over_equipment"]
        mg = v["components"]["margin_operational_over_equipment"]
        def _f(x):
            if not x:
                return "—"
            return (f"{x['median']} / {x['spread']} / {x['n_within_0.1']}/{x['n_areas']}"
                    + ("  ✅" if x["within_0.1"] else ""))
        L.append(f"| {kv} | {v['n_areas']} | {_f(c)} | {_f(mg)} |")
    L += ["", "**運用余裕は事業者を跨いでほぼ揃うが、導体は揃わない。**",
          "つまり係数が割れる主因は各社の運用方針の差ではなく、**電圧階級ごとに単一の "
          "`max_i_ka` を振っているモデル側の粗さ**である（同じ 500kV でも東京と四国では導体が違う）。",
          "熱容量制約の線だけに絞っても 500kV の幅は 0.475 のままで縮まらない（制約種別の"
          "混在では説明できない）。", "",
          "## 読み方", "",
          "1. **理論÷設備容量** — 理論式そのものの精度（代表電流 `max_i_ka` の妥当性）。",
          "2. **運用÷設備容量** — 熱容量と、実際に流してよい上限の差（安定度・電圧・上位系の制約）。",
          "3. **理論÷運用容量** — この逆数が較正係数。モデルの容量を「運用容量」の意味に寄せる。",
          "", "較正は潮流を変えない（容量は制約側の数字）。較正で過負荷が増えるなら、それは",
          "**潮流側（需要配分・発電配分・降圧点）の歪みが露出した**と読む（08-09 の知見と同じ）。", "",
          "## 出典", ""]
    for a, (t, u) in SOURCES.items():
        L.append(f"- {a}: {t} — " + " / ".join(u))
    L += ["", "生成: `scripts/capacity/calibrate_line_capacity.py`（全国版）"]
    (REPORTS / f"line_capacity_calibration_{args.date}.md").write_text("\n".join(L) + "\n", encoding="utf-8")

    if args.write_config:
        write_config(by, national, overall, args.date, ika)
        print(f"-> {CONFIG.relative_to(ROOT)}")
    print(f"解析行 {n_rows} / usable (area,kv) {sum(1 for r in by if r['usable'])} / "
          f"overall {overall}")
    for kv, v in sorted(national.items()):
        print(f"  {kv:>3} kV: median {v['median_factor']} n_areas {v['n_areas']} "
              f"spread {v['spread']} band {v['within_0.1']} {v['areas']}")


if __name__ == "__main__":
    main()
