"""TEPCO per-line flow disclosure vs the built model: topology ground truth.

TEPCO publishes hourly flow time series for the trunk grid (275 kV+) whose
CSV **column names alone** are a topology ground truth: each column is
"<substation>(変) - <equipment>", e.g. ``京浜(変) - 東京南線1･2L`` — an
official statement that 東京南線 terminates at 京浜変電所. From the header
we extract:

- the official substation set (88 sites, 2024 file),
- the official line set (179 named trunk lines),
- the official (substation, line) attachment pairs (286) — the strongest
  per-edge connectivity truth available for the Tokyo area.

This module scores the BUILT model (not raw OSM) against those pairs,
which is why the snapped builder carries OSM line names onto its branches.
Match tiers: exact (NFKC, suffix-stripped) and loose (containment, e.g.
TEPCO 港北線 vs OSM 横浜港北線 counts as loose only).

Data drop (not redistributable — TEPCO terms; data/external/ is
gitignored)::

    curl -A "Mozilla/5.0" -o data/external/tepco/tyouryu_kikan.zip \\
      https://www.tepco.co.jp/pg/consignment/system/pdf/tyouryu_kikan.zip
    # extract jisseki_kikan.csv (zip member names are CP932)

CLI::

    python -m src.validation.external_tepco \\
        --csv data/external/tepco/jisseki_kikan.csv [--region tokyo] [--missing]

The flow VALUES in the same CSV are the next validation layer (model DC
flow vs measured MW per named line) — see docs/VALIDATION_SOURCES.md.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict

sys.path.insert(0, os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_COL_PAT = re.compile(r"^(.+?)\((変|開|開閉所)\)\s*-\s*(.+)$")
_CIRCUIT_SUFFIX = re.compile(r"[0-9０-９･・,，]+L$")


_CLASS_SUFFIX = re.compile(r"\s*(\d+(\.\d+)?kV|\(untyped\))$")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s))
    s = _CLASS_SUFFIX.sub("", s)   # multi-voltage builder bus-name suffixes
    s = s.replace("NT", "ニュータウン")   # 千葉NT線 = 千葉ニュータウン線
    for suf in ("変電所", "開閉所", "発電所"):
        s = s.replace(suf, "")
    return "".join(s.split())


# trailing metering-section qualifier on disclosure line names:
# 佐久間東幹線(中)/(山)/(里) are sections of ONE corridor
_PAREN_QUAL = re.compile(r"[（(][^（()）]{1,4}[)）]$")

# model-side circuit suffixes: 3・4L (as on the CSV side) plus the
# spelled-out 3,4号線 / 3・4号 forms OSM mappers use
_MODEL_CIRCUIT = re.compile(r"[0-9０-９･・,，]+(L|号線?)$")


def _model_name_keys(raw: str) -> list[str]:
    """Match keys for one OSM line name, most-specific first.

    OSM names diverge from the disclosure's by composition, not just
    spelling: compounds (北葛飾線/野田線, 大倉山線1・2L、北島線),
    circuit suffixes (中沢線3・4L, 京浜線3,4号線), from~to segment
    naming (小山町~北駿線 = TEPCO's 北駿線) and parenthetical aliases
    (坂戸川越線(只見幹線)). Yield the normalised variants so the flow
    matcher can land on the disclosure key; the class-band restriction
    still guards against homonyms at other voltages.
    """
    parts = []
    for chunk in str(raw).replace(" / ", ";").replace("/", ";").split(";"):
        parts.extend(chunk.split("、"))
    keys: list[str] = []

    def _add(c: str):
        k = _norm(c)
        if k and k not in keys:
            keys.append(k)

    for part in parts:
        part = part.strip()
        if not part:
            continue
        cands = [part]
        m = re.search(r"[（(]([^（()）]+)[)）]", part)
        if m:                                   # alias in parentheses
            cands.append(re.sub(r"[（(][^（()）]*[)）]", "", part))
            cands.append(m.group(1))
        for c in list(cands):
            stripped = _MODEL_CIRCUIT.sub("", c).strip()
            if stripped and stripped != c:
                cands.append(stripped)
        for c in list(cands):
            for sep in ("~", "〜", "～"):
                if sep in c:
                    tail = c.split(sep)[-1].strip()
                    if tail:
                        cands.append(tail)
        for c in cands:
            _add(c)
    return keys


def parse_tepco_header(csv_path: str) -> dict:
    """Extract (substations, lines, attachment pairs) from the column names."""
    with io.open(csv_path, encoding="cp932", newline="") as f:
        header = next(csv.reader(f))
    subs, lines, pairs = set(), set(), set()
    for col in header[1:]:
        m = _COL_PAT.match(col.strip())
        if not m:
            continue
        sub = m.group(1).strip()
        eq = m.group(3).strip()
        subs.add(sub)
        if eq.endswith("L") and "線" in eq:
            line = _CIRCUIT_SUFFIX.sub("", eq).strip()
            if line:
                lines.add(line)
                pairs.add((sub, line))
    return {"subs": subs, "lines": lines, "pairs": pairs}


def parse_tepco_headers_banded(csv_path, csv154=None, csv66=None) -> dict:
    """Merged attachment truth with a kv-class floor per line/pair.

    Bands: trunk file -> 200, 154 kV files -> 140, prefecture 66 kV
    files -> 60. Same-named lines in different bands stay separate
    truths (matched only against model lines of their own band).
    """
    import glob as _glob

    def _paths(x):
        if not x:
            return []
        xs = [x] if isinstance(x, str) else list(x)
        out = []
        for p_ in xs:
            out.extend(sorted(_glob.glob(p_)) or [p_])
        return out

    truth = {"subs": set(), "lines": {}, "pairs": {}}
    for floor, paths in ((200.0, _paths(csv_path)),
                         (140.0, _paths(csv154)),
                         (60.0, _paths(csv66))):
        for p_ in paths:
            t = parse_tepco_header(p_)
            truth["subs"] |= t["subs"]
            for ln in t["lines"]:
                truth["lines"].setdefault(ln, floor)
            for pair in t["pairs"]:
                truth["pairs"].setdefault(pair, floor)
    return truth


_RAILWAY_PAT = re.compile(r"旅客鉄道|JR|新幹線|鉄道|Railway", re.IGNORECASE)


def _load_operators(region: str, data_dir: str | None = None) -> dict:
    """normalised line name -> set of operator strings (from raw OSM)."""
    from src.powerflow.snapped_topology import DATA_DIR

    path = os.path.join(data_dir or DATA_DIR, f"{region}_lines.geojson")
    ops = defaultdict(set)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for ft in data.get("features", []):
        p = ft.get("properties", {})
        name, op = p.get("name"), p.get("operator")
        if name and op:
            for part in str(name).split(";"):
                ops[_norm(part)].add(op)
    return dict(ops)


def _is_railway_only(name_key: str, operators: dict) -> bool:
    """True when every known operator for this line name is a railway —
    a railway feeder that shares naming conventions with grid lines and
    would otherwise be a false positive against TSO ground truth."""
    ops = operators.get(name_key)
    if not ops:
        return False
    return all(_RAILWAY_PAT.search(o) for o in ops)


def _model_inventory(region: str, data_dir: str | None = None):
    """Built-model inventories: substation names/positions and, per line
    name: endpoint sub names, endpoint positions (subs AND junctions —
    for the positional attachment tier), and max voltage class."""
    from src.powerflow.snapped_topology import build_network_snapped

    net = build_network_snapped(region, data_dir=data_dir)
    if net is None:
        raise FileNotFoundError(f"no data for region {region}")
    sub_name = {}       # real substation id -> normalised name
    pos = {}            # any bus id (sub or junction) -> (lat, lon)
    sub_pos = defaultdict(list)   # normalised name -> [(lat, lon)]
    for s in net.substations:
        pos[s.id] = (s.latitude, s.longitude)
        if "_jct_" not in s.id:
            sub_name[s.id] = _norm(s.name)
            sub_pos[_norm(s.name)].append((s.latitude, s.longitude))
    sub_names = set(sub_name.values())

    line_info = {}   # name key -> {"ends": set, "pos": list, "kv": float}
    for ln in net.transmission_lines:
        if "_xfmr_" in ln.id or not ln.name or ln.name.startswith(f"{region}_line_"):
            continue
        for part in str(ln.name).split(";"):
            key = _norm(part)
            if not key:
                continue
            info = line_info.setdefault(key, {"ends": set(), "pos": [], "kv": 0.0})
            info["kv"] = max(info["kv"], float(ln.voltage_kv or 0))
            for end in (ln.from_substation_id, ln.to_substation_id):
                if end in sub_name:
                    info["ends"].add(sub_name[end])
                if end in pos:
                    info["pos"].append(pos[end])
    return net, sub_names, dict(sub_pos), line_info


def match_tepco(region: str, csv_path: str, data_dir: str | None = None,
                min_kv: float = 200.0, pos_km: float = 1.5,
                csv154=None, csv66=None) -> dict:
    """Score the built model against TEPCO's substation-line attachments.

    Matching guards (added after the failure-mode taxonomy, 2026-06-10):

    - **railway exclusion**: line names operated solely by railways (JR
      feeders share grid naming conventions) are not match candidates;
    - **class consistency**: the disclosure covers the 275 kV+ trunk, so
      a same-named model line whose class is below ``min_kv`` is a name
      collision, not a match;
    - **positional attachment tier**: TEPCO facility names and OSM names
      disagree for adjacent/identical yards (西北線 ends at OSM 稲城 =
      TEPCO 北多摩, 1.1 km apart), so an endpoint within ``pos_km`` of
      the official substation counts as attached-by-position.
    """
    from src.powerflow.snapped_topology import _haversine_km

    truth = parse_tepco_headers_banded(csv_path, csv154=csv154, csv66=csv66)
    _net, sub_names, sub_pos, line_info = _model_inventory(region, data_dir=data_dir)
    operators = _load_operators(region, data_dir=data_dir)

    eligible = {k: v for k, v in line_info.items()
                if not _is_railway_only(k, operators)}
    n_railway_excluded = len(line_info) - len(eligible)
    line_keys = list(eligible.keys())

    def _band(floor):
        ceil = 1e9 if floor >= 200.0 else 200.0 if floor >= 140.0 else 140.0
        return floor, ceil

    def find_line(official: str, floor: float):
        lo, hi = _band(floor)
        key = _norm(official)
        cands = ([key] if key in eligible else
                 [k for k in line_keys if key in k or k in key])
        if not cands:
            return None, None, False
        in_band = [k for k in cands if lo <= eligible[k]["kv"] < hi]
        if in_band:
            return in_band[0], ("exact" if in_band[0] == key else "loose"), True
        return cands[0], ("exact" if cands[0] == key else "loose"), False

    sub_hit = sum(1 for s in truth["subs"] if _norm(s) in sub_names)

    line_exact = line_loose = 0
    missing_lines = []
    for ln in sorted(truth["lines"]):
        _key, tier, _trunk = find_line(ln, truth["lines"][ln])
        if tier == "exact":
            line_exact += 1
        elif tier == "loose":
            line_loose += 1
        else:
            missing_lines.append(ln)

    pair_name = pair_pos = pair_class = pair_un = 0
    band_tot = defaultdict(int)
    band_ok = defaultdict(int)
    missing_pairs = []
    for sub, ln in sorted(truth["pairs"]):
        floor = truth["pairs"][(sub, ln)]
        key, _tier, trunk_class = find_line(ln, floor)
        if key is None:
            missing_pairs.append(f"{sub} - {ln} (line missing)")
            continue
        info = eligible[key]
        bname = "trunk" if floor >= 200 else ("154" if floor >= 140 else "66")
        band_tot[bname] += 1
        if _norm(sub) in info["ends"]:
            pair_name += 1
            band_ok[bname] += 1
            continue
        spots = sub_pos.get(_norm(sub), [])
        d = min((_haversine_km(la, lo, ela, elo)
                 for (la, lo) in spots for (ela, elo) in info["pos"]),
                default=float("inf"))
        if d <= pos_km:
            pair_pos += 1
            band_ok[bname] += 1
        elif not trunk_class:
            # only a sub-trunk-class line carries this name -> collision
            pair_class += 1
            missing_pairs.append(f"{sub} - {ln} (only <{min_kv:.0f}kV name match)")
        else:
            pair_un += 1
            missing_pairs.append(f"{sub} - {ln} (line present, not attached; "
                                 f"nearest end {d:.1f}km)" if d < float("inf")
                                 else f"{sub} - {ln} (sub position unknown)")

    n_subs, n_lines, n_pairs = (len(truth["subs"]), len(truth["lines"]),
                                len(truth["pairs"]))
    # truth["pairs"]に入らなかった(line missing)分もband_totへ計上
    for (sub, ln), floor in truth["pairs"].items():
        bname = "trunk" if floor >= 200 else ("154" if floor >= 140 else "66")
        if find_line(ln, floor)[0] is None:
            band_tot[bname] += 1
    attached = pair_name + pair_pos
    band_recall = {b: round(band_ok[b] / band_tot[b], 4)
                   for b in band_tot if band_tot[b]}
    return {
        "pair_recall_by_band": band_recall,
        "pair_total_by_band": dict(band_tot),
        "region": region,
        "min_kv": min_kv,
        "pos_km": pos_km,
        "truth": {"subs": n_subs, "lines": n_lines, "pairs": n_pairs},
        "n_railway_name_excluded": n_railway_excluded,
        "sub_recall": round(sub_hit / n_subs, 4) if n_subs else 0.0,
        "line_recall_exact": round(line_exact / n_lines, 4) if n_lines else 0.0,
        "line_recall_loose": round((line_exact + line_loose) / n_lines, 4) if n_lines else 0.0,
        "pair_attached_name": pair_name,
        "pair_attached_position": pair_pos,
        "pair_class_collision": pair_class,
        "pair_unattached": pair_un,
        "pair_recall_name": round(pair_name / n_pairs, 4) if n_pairs else 0.0,
        "pair_recall": round(attached / n_pairs, 4) if n_pairs else 0.0,
        "missing_lines": missing_lines,
        "missing_pairs": missing_pairs,
    }


def tepco_flow_stats(csv_path, q: float = 0.95) -> dict:
    """Per-line measured-flow statistic from the full hourly time series.

    Columns for the same (substation, line) are circuit groups (1･2L,
    3･4L) and are SUMMED per timestamp (total line flow at that end);
    the two ends of a line are separate (sub, line) groups and the
    larger-statistic end is taken (ends differ only by losses).

    Returns {normalised line name: q-quantile of |total flow| in MW}.
    The quantile (default 0.95) is robust against metering glitches while
    still representing "how heavily this corridor is actually used".
    """
    import glob as _glob

    import pandas as pd

    paths = ([csv_path] if isinstance(csv_path, str) else list(csv_path))
    expanded = []
    for p_ in paths:
        expanded.extend(sorted(_glob.glob(p_)) or [p_])
    frames = [pd.read_csv(p_, encoding="cp932", na_values=["-", ""])
              for p_ in expanded]
    df = frames[0] if len(frames) == 1 else pd.concat(
        [f.set_index(f.columns[0]) for f in frames], axis=1).reset_index()
    groups = defaultdict(list)   # (sub, line) -> [column, ...]
    for col in df.columns[1:]:
        m = _COL_PAT.match(col.strip())
        if not m:
            continue
        eq = m.group(3).strip()
        if eq.endswith("L") and "線" in eq:
            line = _CIRCUIT_SUFFIX.sub("", eq).strip()
            if line:
                groups[(m.group(1).strip(), line)].append(col)

    stats: dict[str, float] = {}
    for (sub, line), cols in groups.items():
        total = df[cols].apply(pd.to_numeric, errors="coerce").sum(axis=1)
        val = float(total.abs().quantile(q))
        # metering sections 佐久間東幹線(中)/(山)/(里) collapse to the
        # corridor; max keeps the loaded section, as across (sub, line)
        key = _norm(_PAREN_QUAL.sub("", line.strip()))
        stats[key] = max(stats.get(key, 0.0), val)
    return stats


def match_flows(region: str, csv_path, backbone_kv: float | None = 154.0,
                q: float = 0.95, data_dir: str | None = None,
                load_spatial: str = "none", csv154=None, csv66=None) -> dict:
    """Flow-level validation: model DC flows vs TEPCO measured flows.

    Caveat by construction: the model solves ONE synthetic snapshot
    (OCCTO peak x load factor, synthetic allocation), the measurement is
    a year of actuals — so the defensible comparison is *ordinal*: does
    the model route power on the right corridors? Reported as Spearman
    rank correlation over name-matched lines, plus the magnitude ratio
    distribution and the largest mismatches (named, actionable).
    """
    from scipy.stats import spearmanr

    from src.powerflow.load_estimator import load_demand_config
    from src.powerflow.pipeline import build_and_solve

    # measured sets are class-tagged: the trunk disclosure covers 275 kV+,
    # the 154 kV files cover the 140-200 kV layer — matching is restricted
    # within each class band so same-named lines at other voltages stay
    # name collisions instead of becoming false pairs.
    measured_cls = {k: (v, 200.0) for k, v in tepco_flow_stats(csv_path, q=q).items()}
    if csv154:
        for k, v in tepco_flow_stats(csv154, q=q).items():
            measured_cls.setdefault(k, (v, 140.0))
    if csv66:
        for k, v in tepco_flow_stats(csv66, q=q).items():
            measured_cls.setdefault(k, (v, 60.0))
    measured = {k: v for k, (v, _c) in measured_cls.items()}

    typical = tepco_flow_stats(csv_path, q=0.5)

    def _solve(boundary_util=None):
        result = build_and_solve(region, load_demand_config(),
                                 topology="snapped", reconnect=True,
                                 backbone_kv=backbone_kv,
                                 load_spatial=load_spatial,
                                 boundary_util=boundary_util,
                                 boundary_stats=typical)
        if result is None:
            raise FileNotFoundError(f"no network for region {region}")
        net_dc, dc_res, *_ = result
        if not dc_res.get("converged"):
            raise RuntimeError("DC did not converge")
        return net_dc

    def _boundary_corridors(net_dc):
        """Names of trunk lines that touch a boundary-injection bus."""
        if len(net_dc.sgen) == 0:
            return set()
        bdry = set(net_dc.sgen.loc[
            net_dc.sgen["name"].astype(str).str.startswith("boundary_"),
            "bus"].astype(int))
        out = set()
        for idx in net_dc.line.index:
            raw = str(net_dc.line.at[idx, "name"] or "")
            if not raw or raw.startswith(f"{region}_line_"):
                continue
            if int(net_dc.line.at[idx, "from_bus"]) in bdry or \
               int(net_dc.line.at[idx, "to_bus"]) in bdry:
                out.update(_model_name_keys(raw))
        return out

    # Pass 1 (planning utilisation): identify which measured lines are the
    # boundary corridors themselves. Their MEASURED median flow then sets
    # the interconnection's injected total — measured boundary conditions,
    # standard practice. Since those corridors are thereby pinned to data,
    # they are EXCLUDED from the correlation (interior-only validation).
    net_dc = _solve()
    corridors = _boundary_corridors(net_dc)
    calib_util = None
    matched_corridors = sorted(c for c in corridors if c in measured)
    if matched_corridors:
        total = sum(typical.get(c, 0.0) for c in matched_corridors)
        from src.powerflow.boundary import (
            TYPICAL_UTILISATION, load_interconnections)
        for ic in load_interconnections():
            if region == ic.get("to_region") and ic.get("type") == "AC":
                cap = float(ic.get("capacity_mw", 0) or 0)
                if cap > 0 and total > 0:
                    sign = 1.0 if TYPICAL_UTILISATION.get(ic["id"], 0) >= 0 else -1.0
                    calib_util = {ic["id"]: sign * min(total / cap, 1.0)}
        if calib_util:
            net_dc = _solve(boundary_util=calib_util)

    operators = _load_operators(region, data_dir=data_dir)
    model: dict[str, float] = {}
    flows = net_dc.res_line["p_from_mw"].abs()
    vn = net_dc.bus["vn_kv"]
    for idx in net_dc.line.index:
        raw = str(net_dc.line.at[idx, "name"] or "")
        if not raw or raw.startswith(f"{region}_line_"):
            continue
        line_kv = float(vn.get(net_dc.line.at[idx, "from_bus"], 0))
        p = float(flows.get(idx, 0.0))
        for key in _model_name_keys(raw):   # compound/suffix/segment variants
            if _is_railway_only(key, operators):
                continue
            # class-banded matching: a measured trunk (275 kV+) name only
            # accepts >=200 kV model lines; a 154-file name accepts the
            # 140-200 kV band — other-class homonyms stay collisions
            mc = measured_cls.get(key)
            if mc is not None:
                floor = mc[1]
                ceil = (1e9 if floor >= 200.0 else
                        200.0 if floor >= 140.0 else 140.0)
                if not (floor <= line_kv < ceil):
                    continue
            elif line_kv < 60.0:
                continue
            # series segments carry the same flow -> max is the
            # corridor's loaded section
            model[key] = max(model.get(key, 0.0), p)

    common = sorted(set(measured) & set(model))
    # interior = matched lines that did NOT receive measured boundary
    # conditions; only they constitute an honest test of the model
    interior = [k for k in common if k not in corridors]
    out = {
        "region": region,
        "backbone_kv": backbone_kv,
        "load_spatial": load_spatial,
        "quantile": q,
        "n_measured_lines": len(measured),
        "n_model_named_lines": len(model),
        "n_matched": len(common),
        "boundary_corridors_excluded": matched_corridors,
        "boundary_calibration": calib_util,
    }

    def _score(keys, prefix):
        if len(keys) < 5:
            return
        meas_v = [measured[k] for k in keys]
        model_v = [model[k] for k in keys]
        rho, pval = spearmanr(meas_v, model_v)
        ratios = sorted(m / x for x, m in zip(meas_v, model_v) if x > 1.0)
        out[f"{prefix}spearman_rho"] = round(float(rho), 3)
        out[f"{prefix}spearman_p"] = float(f"{pval:.2e}")
        out[f"{prefix}median_model_over_measured"] = (
            round(ratios[len(ratios) // 2], 2) if ratios else None)

    _score(common, "")            # all matched (back-compat)
    _score(interior, "interior_")  # the honest metric
    # per-class breakdown: the 275 kV+ trunk is the established headline;
    # the 154 kV layer is a NEW, separately-reported measurement
    trunk_keys = [k for k in interior if measured_cls[k][1] >= 200.0]
    sub_keys = [k for k in interior if 140.0 <= measured_cls[k][1] < 200.0]
    kv66_keys = [k for k in interior if measured_cls[k][1] < 140.0]
    _score(trunk_keys, "trunk_")
    _score(sub_keys, "kv154_")
    _score(kv66_keys, "kv66_")
    out["n_interior_trunk"] = len(trunk_keys)
    out["n_interior_154"] = len(sub_keys)
    out["n_interior_66"] = len(kv66_keys)
    diffs = sorted(interior, key=lambda k: abs(model[k] - measured[k]),
                   reverse=True)
    out["top_mismatches"] = [
        {"line": k, "measured_p95_mw": round(measured[k], 0),
         "model_dc_mw": round(model[k], 0)} for k in diffs[:10]]
    return out


def render_flows(m: dict) -> str:
    lines = [
        f"{m['region']} flow-level vs TEPCO (q={m['quantile']}, "
        f"backbone>={m['backbone_kv']}kV): "
        f"matched {m['n_matched']} lines "
        f"(measured {m['n_measured_lines']}, model-named {m['n_model_named_lines']})",
    ]
    if m.get("boundary_calibration"):
        lines.append(
            f"  boundary calibration : {m['boundary_calibration']} from measured "
            f"medians of {m['boundary_corridors_excluded']}")
    if "interior_spearman_rho" in m:
        lines.append(
            f"  INTERIOR Spearman   : {m['interior_spearman_rho']} "
            f"(p={m['interior_spearman_p']:g}; boundary-conditioned corridors excluded)")
        if "trunk_spearman_rho" in m:
            lines.append(
                f"    trunk 275kV+ ({m['n_interior_trunk']}): rho={m['trunk_spearman_rho']}"
                + (f" | 154kV ({m['n_interior_154']}): rho={m['kv154_spearman_rho']}"
                   if "kv154_spearman_rho" in m else "")
                + (f" | 66kV ({m['n_interior_66']}): rho={m['kv66_spearman_rho']}"
                   if "kv66_spearman_rho" in m else ""))
        lines.append(
            f"  interior median model/measured : {m['interior_median_model_over_measured']}")
    if "spearman_rho" in m:
        lines.append(
            f"  all-matched Spearman: {m['spearman_rho']} (p={m['spearman_p']:g})")
    if m.get("top_mismatches"):
        lines.append("  largest interior mismatches (measured p95 vs model DC, MW):")
        for t in m["top_mismatches"][:5]:
            lines.append(f"    {t['line']:12s} {t['measured_p95_mw']:>8.0f} vs "
                         f"{t['model_dc_mw']:>8.0f}")
    return "\n".join(lines)


def render_tepco(m: dict) -> str:
    t = m["truth"]
    return "\n".join([
        f"{m['region']} vs TEPCO trunk disclosure "
        f"({t['subs']} subs / {t['lines']} lines / {t['pairs']} attachments; "
        f"{m['n_railway_name_excluded']} railway-only names excluded):",
        f"  substation recall : {100 * m['sub_recall']:.1f}%",
        f"  line recall       : {100 * m['line_recall_exact']:.1f}% exact, "
        f"{100 * m['line_recall_loose']:.1f}% incl. loose",
        f"  attachment recall : {100 * m['pair_recall']:.1f}% "
        f"(name {m['pair_attached_name']} + position {m['pair_attached_position']} "
        f"of {t['pairs']}; class-collision {m['pair_class_collision']}, "
        f"unattached {m['pair_unattached']})",
        f"  by band           : " + "  ".join(
            f"{b}={100*r:.1f}%({m['pair_total_by_band'][b]})"
            for b, r in sorted(m.get("pair_recall_by_band", {}).items())),
    ])


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Match the built model against TEPCO's per-line flow "
                    "disclosure header (topology ground truth)")
    ap.add_argument("--csv", default="data/external/tepco/jisseki_kikan.csv")
    ap.add_argument("--region", default="tokyo")
    ap.add_argument("--json", help="write the full scorecard")
    ap.add_argument("--missing", action="store_true", help="list missing items")
    ap.add_argument("--flows", action="store_true",
                    help="flow-level validation (model DC vs measured MW)")
    ap.add_argument("--csv66",
                    default="data/external/tepco/jisseki_[cfgikmnsty]*.csv",
                    help="glob of the per-prefecture 66 kV flow CSVs ('' to disable)")
    ap.add_argument("--csv154", default="data/external/tepco/jisseki_154kV0*.csv",
                    help="glob of the 154 kV flow CSVs (extends the measured "
                         "set; pass '' to disable)")
    ap.add_argument("--backbone", type=float, default=154.0)
    args = ap.parse_args(argv)

    if not os.path.exists(args.csv):
        print(f"no CSV at {args.csv} — fetch it first (see module docstring)")
        return 2
    if args.flows:
        import glob as _g
        csv154 = args.csv154 if args.csv154 and _g.glob(args.csv154) else None
        csv66 = args.csv66 if args.csv66 and _g.glob(args.csv66) else None
        m = match_flows(args.region, args.csv, backbone_kv=args.backbone,
                        csv154=csv154, csv66=csv66)
        print(render_flows(m))
        if args.json:
            with open(args.json, "w", encoding="utf-8") as f:
                json.dump(m, f, indent=1, ensure_ascii=False)
            print(f"\nscorecard -> {args.json}")
        return 0
    import glob as _g2
    m = match_tepco(
        args.region, args.csv,
        csv154=(args.csv154 if args.csv154 and _g2.glob(args.csv154) else None),
        csv66=(args.csv66 if args.csv66 and _g2.glob(args.csv66) else None))
    print(render_tepco(m))
    if args.missing:
        print("\nofficial trunk lines absent from the model (work list):")
        for ln in m["missing_lines"]:
            print(f"  - {ln}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(m, f, indent=1, ensure_ascii=False)
        print(f"\nscorecard -> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
