#!/usr/bin/env python3
"""地図の Ybus / N-1 タブが読む N-1 の要約を、正典の N-1 スクリーニングの報告から書く.

2026-10-21 まで、このタブの N-1 の表は旧系譜(地域別のスナップ済みの網・scripts/run_n1_contingency.py・
2026-06-03・関西なし)だった。正典(docs/data/built)の 4 つの同期島で全枝を評価する
scripts/sensitivity/n1_screening.py の結果を出す(docs/reports/project_structure_2026-10-21.md の D3)。

入力: docs/reports/n1_screening_<date>.json のうち日付がいちばん新しいもの
出力: docs/data/n1_canon/summary.json(島ごとの指標・上位の停止・AC での解き直し・系統分離の上位)

    python3 scripts/export_n1_pages.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "docs" / "reports"
OUT = ROOT / "docs" / "data" / "n1_canon" / "summary.json"

ISLAND_KEYS = [
    "island", "n_bus", "n_bus_full", "n_branch", "n_outage_evaluated", "n_islanding", "min_kv",
    "n_monitor_physical", "base_n_over_physical", "base_max_loading_physical_pct",
    "n_outage_causing_new_over_physical", "n_outage_new_over_120_physical", "max_new_loading_physical_pct",
    "islanding_total_load_mw", "islanding_n_over_100mw",
]
TOP_KEYS = ["name", "kv", "class_label", "parallel", "cap_mw", "base_loading_pct",
            "post_max_new_loading_pct", "post_n_new_over"]
AC_KEYS = ["name", "ac_converged", "ac_served_frac", "dc_post_max_new_loading_pct",
           "ac_post_max_new_loading_pct", "ac_worst", "ac_n_new_over"]
TOP_N = 10


def latest_report() -> Path:
    reports = sorted(REPORTS.glob("n1_screening_????-??-??.json"))
    if not reports:
        raise SystemExit("docs/reports に n1_screening_<date>.json が無い(scripts/sensitivity/n1_screening.py で作る)")
    return reports[-1]


def _pick(d: dict, keys: list[str]) -> dict:
    return {k: d[k] for k in keys if k in d}


_TRAFO = re.compile(r"trafo_(\d+)/(\d+)kV")
_KV_TAIL = re.compile(r"\s*\d+(\.\d+)?\s*kV$")


def label(t: dict) -> str:
    """画面に出す名前。変圧器は内部の名前(trafo_500/275kV@pairmed@osm)ではなく「房総変電所の変圧器 500/275 kV」。"""
    name = t.get("name") or ""
    m = _TRAFO.match(name)
    if t.get("table") != "trafo" and not m:
        if name and name != "namebind":
            return name
        # 名前の無い枝(正典では name="namebind")は両端の変電所名で呼ぶ
        return f"{_site(t.get('from'))}〜{_site(t.get('to'))}(名前の無い線)"
    return f"{_site(t.get('from'))}の変圧器" + (f" {m.group(1)}/{m.group(2)} kV" if m else "")


def _site(end) -> str:
    """端点の表記(「房総変電所 500kV」「tokyo junction 35.2:138.4:66」)から場所の名前だけを取る。"""
    site = _KV_TAIL.sub("", str(end or ""))
    return "名前の無い分岐点" if not site or " junction " in site else site


def summarize(report: dict, src: Path) -> dict:
    islands = []
    for isl in report["islands"]:
        row = _pick(isl, ISLAND_KEYS)
        # AC での解き直しは名前しか持たないので、同じ要素(ppc_idx)の表示名を上位の表から引く
        labels = {t["ppc_idx"]: label(t) for k in ("top_physical", "top_synthetic_worst", "islanding_top")
                  for t in isl.get(k, []) if "ppc_idx" in t}
        row["top"] = []
        for t in isl.get("top_physical", [])[:TOP_N]:
            item = _pick(t, TOP_KEYS)
            item["label"] = label(t)
            w = t.get("worst") or {}
            item["worst"] = _pick(w, ["name", "kv", "class_label"])
            row["top"].append(item)
        row["ac_verify"] = [dict(_pick(a, AC_KEYS), label=labels.get(a.get("ppc_idx"), a.get("name")))
                            for a in isl.get("ac_verify", [])]
        row["islanding_top"] = [
            dict(_pick(t, ["name", "kv", "class_label", "isolated_n_bus", "isolated_load_mw", "isolated_gen_mw"]),
                 label=label(t))
            for t in isl.get("islanding_top", [])[:5]]
        islands.append(row)
    return {
        "date": report["date"],
        "git_head": report.get("git_head"),
        "source": src.relative_to(ROOT).as_posix(),
        "args": {k: report.get("args", {}).get(k) for k in ("min_kv", "cap_factor", "ac_verify", "no_single_circuit")},
        "islands": islands,
    }


def main() -> None:
    src = latest_report()
    out = summarize(json.loads(src.read_text(encoding="utf-8")), src)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{src.name} → {OUT.relative_to(ROOT)}  ({', '.join(i['island'] for i in out['islands'])})")


if __name__ == "__main__":
    main()
