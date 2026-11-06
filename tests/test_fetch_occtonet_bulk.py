"""scripts/fetch_occtonet_bulk.py の「取り溜めを減らさない決まり」の確認(通信しない)。"""
from __future__ import annotations

import datetime as dt
import json
import os

from scripts import fetch_occtonet_bulk as fb

SPEC = fb.SPECS["chinai_flow"]          # 1 か月 1 本の種類
DAY = fb.SPECS["frequency_50hz"]        # 1 日 1 本の種類


class FakeClient:
    """download() が決めた中身を返すだけの Client。呼ばれた単位を記録する。"""

    def __init__(self, bodies: dict[str, bytes]):
        self.bodies = bodies
        self.calls: list[tuple[str, ...]] = []
        self.sleep = 0
        self.defaults = None

    def download(self, spec, values):
        self.calls.append(values)
        return self.bodies.get(values[0], b"")


def _csv(n: int, mark: str = "a") -> bytes:
    return ("h\n" + "".join(f"{mark},{i}\n" for i in range(n))).encode()


def test_save_rules(tmp_path):
    p = tmp_path / "chinai_flow" / "2025" / "chinai_flow_202504.csv"
    assert fb.save(p, _csv(3)) == "new"
    t0 = p.stat().st_mtime
    os.utime(p, (t0 - 86400 * 3, t0 - 86400 * 3))
    assert fb.save(p, _csv(3)) == "same"                       # 同じ中身は書かない
    assert p.stat().st_mtime == t0 - 86400 * 3                 # 更新時刻も変えない
    assert fb.save(p, _csv(5)) == "grown"
    assert p.read_bytes() == _csv(5)
    assert fb.save(p, _csv(2)) == "kept"                       # 減る応答では上書きしない
    assert p.read_bytes() == _csv(5)
    vdir = p.parent.parent / "_versions"
    assert (vdir / "chinai_flow_202504.shorter.csv").read_bytes() == _csv(2)
    old_day = dt.date.fromtimestamp(p.stat().st_mtime)
    assert fb.save(p, _csv(5, "b")) == "revised"               # 値の改訂は前の版を残す
    assert p.read_bytes() == _csv(5, "b")
    assert (vdir / f"chinai_flow_202504.{old_day:%Y%m%d}.csv").read_bytes() == _csv(5)


def test_unit_end():
    assert fb.unit_end(SPEC, "202502") == dt.date(2025, 2, 28)
    assert fb.unit_end(DAY, "20260105") == dt.date(2026, 1, 5)


def test_run_refetches_unfinished_month(tmp_path):
    """前月が途中のまま(台帳の to が月末に届かない)なら、backfill で取り直す。"""
    today = dt.date.today()
    prev_end = today.replace(day=1) - dt.timedelta(days=1)
    prev = prev_end.replace(day=1)
    tag = f"{prev:%Y%m}"
    p = fb.path_for(tmp_path, SPEC, tag)
    fb.save(p, _csv(3))
    man = {tag: {"to": str(prev_end - dt.timedelta(days=4)), "at": "x"}}
    fb.write_manifest(tmp_path, SPEC, man)
    cli = FakeClient({f"{prev:%Y/%m/%d}": _csv(8)})
    got, skip, miss = fb.run(cli, tmp_path, SPEC, prev, prev_end, set(), 0, refetch_open=False)
    assert (got, skip, miss) == (1, 0, 0)
    assert p.read_bytes() == _csv(8)
    man = json.loads((tmp_path / "chinai_flow" / fb.MANIFEST).read_text())
    assert man[tag]["to"] == str(prev_end)
    # もう一度回しても取りに行かない
    cli2 = FakeClient({})
    assert fb.run(cli2, tmp_path, SPEC, prev, prev_end, set(), 0, refetch_open=False) == (0, 1, 0)
    assert cli2.calls == []


def test_run_bootstrap_and_open_month(tmp_path):
    """台帳の無い既存ファイルは取った日の前日まで覆ったとみなす。当月は backfill では取り直さない。"""
    today = dt.date.today()
    first = today.replace(day=1)
    old = (first - dt.timedelta(days=40)).replace(day=1)
    old_end = fb.unit_end(SPEC, f"{old:%Y%m}")
    fb.save(fb.path_for(tmp_path, SPEC, f"{old:%Y%m}"), _csv(3))     # 締まった月を今日取った
    cur = fb.path_for(tmp_path, SPEC, f"{first:%Y%m}")
    fb.save(cur, _csv(2))                                              # 当月を今日取った
    cli = FakeClient({})
    got, skip, miss = fb.run(cli, tmp_path, SPEC, old, today, set(), 0, refetch_open=False)
    assert cli.calls == [] or all(v[0] != f"{old:%Y/%m/%d}" for v in cli.calls)
    man = json.loads((tmp_path / "chinai_flow" / fb.MANIFEST).read_text())
    assert man[f"{old:%Y%m}"]["to"] == str(old_end)
    assert man[f"{old:%Y%m}"]["note"] == "台帳より前"
    assert cur.read_bytes() == _csv(2)


def test_kept_does_not_advance_manifest(tmp_path):
    today = dt.date.today()
    prev_end = today.replace(day=1) - dt.timedelta(days=1)
    prev = prev_end.replace(day=1)
    tag = f"{prev:%Y%m}"
    p = fb.path_for(tmp_path, SPEC, tag)
    fb.save(p, _csv(9))
    fb.write_manifest(tmp_path, SPEC, {tag: {"to": str(prev_end - dt.timedelta(days=2)), "at": "x"}})
    cli = FakeClient({f"{prev:%Y/%m/%d}": _csv(4)})
    fb.run(cli, tmp_path, SPEC, prev, prev_end, set(), 0)
    assert p.read_bytes() == _csv(9)
    man = json.loads((tmp_path / "chinai_flow" / fb.MANIFEST).read_text())
    assert man[tag]["to"] == str(prev_end - dt.timedelta(days=2))
