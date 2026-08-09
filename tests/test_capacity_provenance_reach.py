"""発電容量の出典が下流に届いているかのゲート。

出典必須DBは「値と出典をセットで持つ」ことを保証するが、**その値が成果物に
届いているか**は保証しない。2026-08-09 の監査で二つの穴が見つかったので、
状況が変わったら気づけるようにする。

現状（既知の穴）を assert で固定するのではなく、**穴が塞がったら失敗する**形にして
ある。塞いだ人がテストを更新する動線になる。
"""
from __future__ import annotations

import glob
import json
import re
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GEN_DB = ROOT / "data" / "generator_capacity_sources.jsonl"
APPLIED = ROOT / "docs" / "data" / "generators.geojson"
CIM_INPUT = sorted(glob.glob(str(ROOT / "data" / "*_plants.geojson")))
CIM_OUT = sorted(glob.glob(str(ROOT / "dist" / "cim" / "*_EQ.xml")))


def _gen_source_urls() -> set[str]:
    if not GEN_DB.exists():
        return set()
    return {json.loads(l)["source_url"] for l in open(GEN_DB, encoding="utf-8")
            if l.strip() and "source_url" in l}


def _sourced_by_plant() -> dict[str, list[tuple[float, float]]]:
    by: dict[str, list[tuple[float, float]]] = defaultdict(list)
    if not APPLIED.exists():
        return by
    for ft in json.load(open(APPLIED))["features"]:
        p = ft["properties"]
        s = p.get("capacity_mw_sourced")
        if s not in (None, "", 0):
            by[str(p.get("name") or "?")].append((float(p.get("capacity_mw") or 0), float(s)))
    return by


@pytest.mark.skipif(not APPLIED.exists(), reason="generators.geojson が無い")
def test_sourced_values_are_plant_level_not_unit_level():
    """出典値は発電所全体の値で、号機単位レコードに重複して載る。

    → **レコード単位で合計してはいけない**。この性質が変わった（号機按分された）なら
    このテストが落ちるので、合計してよくなったことに気づける。
    """
    by = _sourced_by_plant()
    multi = {k: v for k, v in by.items() if len(v) > 1}
    if not multi:
        pytest.fail("複数レコードを持つ発電所が無くなった。"
                    "出典値が号機単位に按分されたなら、合計禁止の制約を見直せる")
    # 同じ発電所のレコードは同じ出典値を持つ（＝発電所全体の値が複製されている）
    for name, vals in multi.items():
        sourced = {round(s, 3) for _, s in vals}
        assert len(sourced) == 1, f"{name}: 出典値がレコードごとに違う {sourced}"
    naive = sum(s for v in by.values() for _, s in v)
    per_plant = sum(v[0][1] for v in by.values())
    assert naive > per_plant, "多重計上が消えている（想定と違う）"


@pytest.mark.skipif(not APPLIED.exists(), reason="generators.geojson が無い")
def test_no_consumer_sums_sourced_capacity():
    """出典値を合計しているコードが増えていないか。

    合計は 73% 過大になるので、`sum(...capacity_mw_sourced...)` のような
    書き方が現れたら気づけるようにする。
    """
    pat = re.compile(r"sum\([^)]*capacity_mw_sourced|capacity_mw_sourced[^\n]{0,40}\.sum\(")
    offenders = []
    for f in glob.glob(str(ROOT / "scripts" / "**" / "*.py"), recursive=True) + \
             glob.glob(str(ROOT / "src" / "**" / "*.py"), recursive=True):
        if "audit_capacity_provenance_reach" in f:
            continue          # 監査スクリプト自身は合計してよい（過大を示すのが目的）
        s = open(f, encoding="utf-8", errors="replace").read()
        if pat.search(s):
            offenders.append(Path(f).relative_to(ROOT).as_posix())
    assert not offenders, ("出典値を合計しているコードがある（73%過大になる）: "
                           + ", ".join(offenders))


@pytest.mark.skipif(not CIM_INPUT, reason="CIM入力の plants geojson が無い")
def test_cim_input_lacks_capacity_provenance_is_known_gap():
    """CIM が読む plants geojson に出典欄が無い（既知の穴）。

    `apply_capacity_sources.py` の対象は docs/data/ の4ファイルのみで、
    CIM 入力の data/*_plants.geojson は対象外。**塞がったらこのテストが落ちる**ので、
    そのとき CGMES 側の期待値も更新する。
    """
    n_sourced = 0
    for f in CIM_INPUT:
        try:
            d = json.load(open(f))
        except Exception:
            continue
        n_sourced += sum(1 for ft in d.get("features", [])
                         if ft["properties"].get("capacity_mw_sourced") not in (None, "", 0))
    if n_sourced:
        pytest.fail(f"CIM入力に出典が入った（{n_sourced}件）。"
                    "出典がCGMESまで届くようになったので、期待値を更新すること")


@pytest.mark.skipif(not CIM_OUT, reason="CGMES出力が無い")
def test_capacity_provenance_does_not_reach_cgmes_yet():
    """CGMES に届いている出典URLは変圧器由来のみ（既知の穴）。

    発電容量DBのURLが CGMES に現れたら伝播が繋がったということなので、
    このテストを更新する。
    """
    urls: set[str] = set()
    for f in CIM_OUT:
        s = open(f, encoding="utf-8", errors="replace").read()
        urls |= set(re.findall(r"IdentifiedObject\.description>(https?://[^<]+)", s))
    from_gen = urls & _gen_source_urls()
    if from_gen:
        pytest.fail(f"発電容量の出典がCGMESに届いた（{len(from_gen)}種）。"
                    "Phase 1-B 出典伝播が完成したので期待値を更新すること")
    # 変圧器側は届いている＝経路自体は生きている、という対比を固定する
    assert urls, "CGMES に出典URLが1件も無い（変圧器側の伝播まで壊れた可能性）"
