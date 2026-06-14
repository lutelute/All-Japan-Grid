"""接続編集ログ — append専用 data/db/connection_edits.jsonl の読み書き。

設計: docs/CONNECTION_EDITOR_DESIGN.md。物理接続=真・捏造禁止・全編集を記録し検証して判定する。
action: connect / disconnect / add_point / set_attr。
status: pending → verified → adopted / rejected。

`enrichments.jsonl` と同じ append専用・git追跡・冪等の運用思想。本モジュールは編集の
記録(append)と一覧(list)のみを担い、モデルへの適用(supplement/cut/enrichment化)と
判定は edit_apply / verify 層(E8)が行う。
"""
import os
import json
import time
import hashlib

EDITS_PATH = os.path.join("data", "db", "connection_edits.jsonl")
ACTIONS = ("connect", "disconnect", "add_point", "set_attr")
STATUSES = ("pending", "verified", "adopted", "rejected")


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _gen_id(edit):
    anchor = edit.get("a") or edit.get("pt") or edit.get("feature_key") or ""
    base = (f"{edit.get('action')}|{edit.get('region')}|{edit.get('ts')}|"
            f"{json.dumps(anchor, sort_keys=True, ensure_ascii=False)}")
    return "e_" + hashlib.sha1(base.encode("utf-8")).hexdigest()[:10]


def validate(edit):
    """必須フィールドを検証。問題があれば理由(str)、妥当なら None。"""
    a = edit.get("action")
    if a not in ACTIONS:
        return f"action must be one of {ACTIONS}"
    if not edit.get("region"):
        return "region required"
    if a == "connect":
        if not (edit.get("a") and edit.get("b")):
            return "connect requires a and b (each {node?, lat, lon})"
    elif a == "disconnect":
        if not ((edit.get("a") and edit.get("b")) or edit.get("line_key")):
            return "disconnect requires a+b or line_key"
    elif a == "add_point":
        pt = edit.get("pt") or {}
        if "lat" not in pt or "lon" not in pt:
            return "add_point requires pt.lat and pt.lon"
    elif a == "set_attr":
        if not (edit.get("feature_key") and edit.get("field")):
            return "set_attr requires feature_key and field"
    return None


def append_edit(edit, path=None):
    """編集を1件追記。id/ts/status/user を補完した dict を返す。"""
    edit = dict(edit)
    edit.setdefault("ts", _now_iso())
    err = validate(edit)
    if err:
        raise ValueError(err)
    edit.setdefault("status", "pending")
    edit.setdefault("user", "anon")
    edit["id"] = edit.get("id") or _gen_id(edit)
    p = path or EDITS_PATH
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(edit, ensure_ascii=False) + "\n")
    return edit


def list_edits(region=None, status=None, path=None):
    """編集を読み出し region/status で絞る(append順)。"""
    p = path or EDITS_PATH
    if not os.path.exists(p):
        return []
    out = []
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if region and e.get("region") != region:
                continue
            if status and e.get("status") != status:
                continue
            out.append(e)
    return out


def counts(region=None, path=None):
    """status別の件数(ダッシュボード/検証用)。"""
    from collections import Counter
    return dict(Counter(e.get("status", "pending")
                        for e in list_edits(region=region, path=path)))
