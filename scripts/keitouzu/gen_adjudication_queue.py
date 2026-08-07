#!/usr/bin/env python3
"""keitouzu 食い違い候補の人間裁定キューを生成する。

crosscheck の食い違い候補（crosswalk 誤マッチ裁定後）を優先度順に並べ、
原図 PDF（manifest の archive_url）への直リンクを付けた「裁定の作業台」を出力する。

優先度: A=完全断絶(別成分) を電圧降順 → B=hop7+ → C=hop5-6
verdict 欄は空欄で出力し、人間の裁定結果を JSON に記入して育てる
（採用は docs/MODEL_INTERVENTIONS.md 記帳が必須）。

usage: python3 scripts/keitouzu/gen_adjudication_queue.py [--date YYYY-MM-DD]
出力: docs/reports/keitouzu_adjudication_queue_<date>.{md,json}
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KZ = ROOT / "data" / "external" / "keitouzu"
REPORTS = ROOT / "docs" / "reports"

VERDICTS = ["adopt_candidate", "built_missing_confirmed", "keitouzu_error", "undecided"]


def kv_rank(v: str) -> float:
    if v in ("DC", "FC"):
        return 999.0
    try:
        return float(v)
    except ValueError:
        return 0.0


def source_links() -> dict[str, list[str]]:
    """source_ref → 原図の archive_url リスト（document 欄の .pdf トークンで manifest と照合）。"""
    man = {Path(m["local_file"]).name: m for m in csv.DictReader(open(KZ / "manifest.csv"))}
    links: dict[str, list[str]] = {}
    for s in csv.DictReader(open(KZ / "sources.csv")):
        toks = re.findall(r"[\w\-]+\.pdf", s["document"] + " " + s["local_path"])
        urls = []
        for t in dict.fromkeys(toks):
            m = man.get(t)
            if m and m.get("archive_url"):
                urls.append(m["archive_url"])
        if not urls:  # PDF以外(CSV群等)は landing_page で代替
            pref = s["source_ref"].split("-")[0]
            urls = [m["landing_page"] for f, m in man.items()
                    if f.startswith(pref) and m.get("landing_page")][:1]
        links[s["source_ref"]] = urls
    return links


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = args.date or subprocess.run(["date", "+%Y-%m-%d"], capture_output=True, text=True).stdout.strip()

    cc = sorted(REPORTS.glob("keitouzu_crosscheck_*.json"))[-1]
    report = json.load(open(cc))
    links = source_links()

    def prio(c: dict) -> tuple:
        h = c["built_hops"]
        group = 0 if h is None else (1 if h >= 7 else 2)
        return (group, -kv_rank(c["voltage_kv"]))

    queue = []
    for c in sorted(report["divergent_candidates"], key=prio):
        h = c["built_hops"]
        queue.append({
            "group": "A_断絶" if h is None else ("B_hop7+" if h >= 7 else "C_hop5-6"),
            "keitouzu_uuid": c["keitouzu_uuid"],
            "line": c["line"],
            "voltage_kv": c["voltage_kv"],
            "region": c["region"],
            "from": (c["from"]["aliases"] or [c["from"]["name"]])[0],
            "to": (c["to"]["aliases"] or [c["to"]["name"]])[0],
            "ajg_from": c["from"]["ajg"],
            "ajg_to": c["to"]["ajg"],
            "built_hops": h,
            "confidence": c["confidence"],
            "evidence": c["evidence"],
            "source_ref": c["source_ref"],
            "source_urls": links.get(c["source_ref"], []),
            "verdict": "",       # 人間が記入: adopt_candidate / built_missing_confirmed / keitouzu_error / undecided
            "verdict_note": "",
        })

    out_json = REPORTS / f"keitouzu_adjudication_queue_{date}.json"
    out_md = REPORTS / f"keitouzu_adjudication_queue_{date}.md"
    json.dump({"date": date, "source_report": cc.name, "verdict_enum": VERDICTS,
               "queue": queue}, open(out_json, "w"), ensure_ascii=False, indent=1)

    ng = {g: [q for q in queue if q["group"] == g] for g in ("A_断絶", "B_hop7+", "C_hop5-6")}
    lines = [
        f"# keitouzu 食い違い裁定キュー — {date}",
        "",
        f"元データ: `{cc.name}`（crosswalk 誤マッチ裁定後の食い違い {len(queue)} 本）。",
        "各行の原図リンク（Internet Archive）で公式系統図に当たり、verdict を JSON に記入する。",
        "**採用（builtへの接続追加）は人間判断＋`docs/MODEL_INTERVENTIONS.md` 記帳が必須。**",
        "",
        f"- **A: 完全断絶（別成分） {len(ng['A_断絶'])} 本** — builtに経路が全く無い。最優先",
        f"- B: 遠距離接続 hop7+ {len(ng['B_hop7+'])} 本",
        f"- C: 近距離 hop5-6 {len(ng['C_hop5-6'])} 本 — 粒度差の可能性も残る",
        "",
    ]
    for g, title in (("A_断絶", "A: 完全断絶"), ("B_hop7+", "B: hop7+"), ("C_hop5-6", "C: hop5-6")):
        lines += [f"## {title}（{len(ng[g])}本）", "",
                  "| ☐ | kV | 線名 | from — to | region | hops | 原図 |",
                  "|---|---|---|---|---|---:|---|"]
        for q in ng[g]:
            url = f"[原図]({q['source_urls'][0]})" if q["source_urls"] else q["source_ref"]
            lines.append(f"| ☐ | {q['voltage_kv']} | {q['line'] or '—'} | {q['from']} — {q['to']} | "
                         f"{q['region']} | {q['built_hops'] if q['built_hops'] is not None else '断絶'} | {url} |")
        lines.append("")
    lines += ["---", "生成: `scripts/keitouzu/gen_adjudication_queue.py`", ""]
    out_md.write_text("\n".join(lines), encoding="utf-8")

    print(f"裁定キュー {len(queue)} 本 (A={len(ng['A_断絶'])} B={len(ng['B_hop7+'])} C={len(ng['C_hop5-6'])})")
    print(f"→ {out_md.relative_to(ROOT)}")
    print(f"→ {out_json.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
