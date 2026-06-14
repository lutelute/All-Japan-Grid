"""E12: 接続編集を GitHub issue として送信する(レビュー・メモ・多ユーザーの土台)。

オーナー方針(2026-06-14): 接続編集は GitHub issue として送り、メモを添えてレビュー・採用・
OSM 還元の単位にする。粒度は「pending接続をまとめて1 issue」。`gh` CLI を使用。

物理接続=真・計算は検証器。issue 本文に各接続(OSM根拠つき)をチェックリスト化し、検証(島A/B)
結果も載せる。送信済み edit は data/db/connection_submissions.jsonl に記録し二重送信を防ぐ。
edit_log(append専用)は不変のまま、送信は別台帳で管理する。
"""
import os
import json
import time
import subprocess

from src.server import edit_log

SUBMISSIONS_PATH = os.path.join("data", "db", "connection_submissions.jsonl")


def _submissions(path=None):
    p = path or SUBMISSIONS_PATH
    if not os.path.exists(p):
        return []
    out = []
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def submitted_edit_ids(region=None, path=None):
    """既に issue 送信済みの edit id 集合(二重送信防止)。"""
    ids = set()
    for s in _submissions(path=path):
        if region is None or s.get("region") == region:
            ids.update(s.get("edit_ids", []))
    return ids


def pending_connections(region, path=None, sub_path=None):
    """まだ issue 化していない pending な connect 編集。"""
    done = submitted_edit_ids(region, path=sub_path)
    rows = edit_log.list_edits(region=region, status="pending", path=path)
    return [e for e in rows
            if e.get("action") == "connect" and e.get("id") not in done]


def _osm_link(lat, lon):
    try:
        return f"https://www.openstreetmap.org/#map=18/{float(lat):.5f}/{float(lon):.5f}"
    except (TypeError, ValueError):
        return ""


def _kv_str(kv):
    if not kv:
        return "?kV"
    try:
        return f"{float(kv) / 1000:.0f}kV"
    except (TypeError, ValueError):
        return "?kV"


def build_issue(region, edits, memo=None, verify=None):
    """issue の title と body(Markdown)を組み立てる。"""
    n = len(edits)
    title = f"[接続提案] {region} {n}件"
    L = []
    L.append("## 接続提案 (物理接続=OSM実在線を根拠・計算は検証器)")
    L.append("")
    L.append(f"- 地域: `{region}`")
    L.append(f"- 提案者: {edits[0].get('user', 'anon') if edits else 'anon'}")
    if verify:
        L.append(
            f"- 検証(島A/B): 島 {verify.get('islands_before')}→{verify.get('islands_after')} "
            f"(Δ{verify.get('delta_islands')}) / 本系統 "
            f"{verify.get('main_before')}→{verify.get('main_after')}"
        )
    L.append("")
    L.append("### 接続一覧(各行=1接続・物理/潮流で確認したらチェック)")
    for e in edits:
        a = e.get("a", {}) or {}
        b = e.get("b", {}) or {}
        link = _osm_link(a.get("lat"), a.get("lon"))
        linkmd = f" [OSM]({link})" if link else ""
        L.append(
            f"- [ ] `{a.get('lat')},{a.get('lon')}` ↔ `{b.get('lat')},{b.get('lon')}` "
            f"({_kv_str(e.get('kv'))}, ev={e.get('evidence', '?')}){linkmd} "
            f"<sub>{e.get('id', '')}</sub>"
        )
    L.append("")
    if memo:
        L.append("### メモ")
        L.append(memo)
        L.append("")
    L.append("---")
    L.append("_接続編集プラットフォーム(`/editor`)から自動生成。採用時は `data/{region}_lines_supplement.geojson` に統合し、OSM(ODbL)へ還元する。_")
    L.append("🤖 Generated with [Claude Code](https://claude.com/claude-code)")
    return title, "\n".join(L)


def ensure_label():
    """connection ラベルを冪等に用意(--force で存在時も成功)。"""
    subprocess.run(
        ["gh", "label", "create", "connection",
         "--description", "系統の接続提案(OSM根拠・要検証)",
         "--color", "1f6feb", "--force"],
        check=False, capture_output=True, text=True,
    )


def submit_issue(region, memo=None, verify=None, dry_run=False, path=None, sub_path=None):
    """pending接続をまとめて1 GitHub issue 化。dry_run は本文だけ返す。"""
    edits = pending_connections(region, path=path, sub_path=sub_path)
    if not edits:
        return {"ok": False, "error": "送信対象のpending接続がありません(既送信を除く)"}
    title, body = build_issue(region, edits, memo=memo, verify=verify)
    if dry_run:
        return {"ok": True, "dry_run": True, "title": title, "body": body, "n": len(edits)}

    ensure_label()
    res = subprocess.run(
        ["gh", "issue", "create", "--title", title, "--body", body,
         "--label", "connection", "--label", "data-quality"],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        return {"ok": False, "error": (res.stderr or "gh issue create failed").strip()}

    url = (res.stdout or "").strip().splitlines()[-1] if res.stdout.strip() else ""
    number = url.rstrip("/").split("/")[-1] if url else ""
    rec = {
        "issue_number": number, "issue_url": url, "region": region,
        "edit_ids": [e.get("id") for e in edits], "memo": memo,
        "n": len(edits), "created_at": _now_iso(),
    }
    p = sub_path or SUBMISSIONS_PATH
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return {"ok": True, "issue_url": url, "issue_number": number, "n": len(edits)}


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
