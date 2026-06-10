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
    for suf in ("変電所", "開閉所", "発電所"):
        s = s.replace(suf, "")
    return "".join(s.split())


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
                min_kv: float = 200.0, pos_km: float = 1.5) -> dict:
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

    truth = parse_tepco_header(csv_path)
    _net, sub_names, sub_pos, line_info = _model_inventory(region, data_dir=data_dir)
    operators = _load_operators(region, data_dir=data_dir)

    eligible = {k: v for k, v in line_info.items()
                if not _is_railway_only(k, operators)}
    n_railway_excluded = len(line_info) - len(eligible)
    line_keys = list(eligible.keys())

    def find_line(official: str):
        key = _norm(official)
        cands = ([key] if key in eligible else
                 [k for k in line_keys if key in k or k in key])
        if not cands:
            return None, None, False
        trunk = [k for k in cands if eligible[k]["kv"] >= min_kv]
        if trunk:
            return trunk[0], ("exact" if trunk[0] == key else "loose"), True
        return cands[0], ("exact" if cands[0] == key else "loose"), False

    sub_hit = sum(1 for s in truth["subs"] if _norm(s) in sub_names)

    line_exact = line_loose = 0
    missing_lines = []
    for ln in sorted(truth["lines"]):
        _key, tier, _trunk = find_line(ln)
        if tier == "exact":
            line_exact += 1
        elif tier == "loose":
            line_loose += 1
        else:
            missing_lines.append(ln)

    pair_name = pair_pos = pair_class = pair_un = 0
    missing_pairs = []
    for sub, ln in sorted(truth["pairs"]):
        key, _tier, trunk_class = find_line(ln)
        if key is None:
            missing_pairs.append(f"{sub} - {ln} (line missing)")
            continue
        info = eligible[key]
        if _norm(sub) in info["ends"]:
            pair_name += 1
            continue
        spots = sub_pos.get(_norm(sub), [])
        d = min((_haversine_km(la, lo, ela, elo)
                 for (la, lo) in spots for (ela, elo) in info["pos"]),
                default=float("inf"))
        if d <= pos_km:
            pair_pos += 1
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
    attached = pair_name + pair_pos
    return {
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


def tepco_flow_stats(csv_path: str, q: float = 0.95) -> dict:
    """Per-line measured-flow statistic from the full hourly time series.

    Columns for the same (substation, line) are circuit groups (1･2L,
    3･4L) and are SUMMED per timestamp (total line flow at that end);
    the two ends of a line are separate (sub, line) groups and the
    larger-statistic end is taken (ends differ only by losses).

    Returns {normalised line name: q-quantile of |total flow| in MW}.
    The quantile (default 0.95) is robust against metering glitches while
    still representing "how heavily this corridor is actually used".
    """
    import pandas as pd

    df = pd.read_csv(csv_path, encoding="cp932", na_values=["-", ""])
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
        key = _norm(line)
        stats[key] = max(stats.get(key, 0.0), val)
    return stats


def match_flows(region: str, csv_path: str, backbone_kv: float | None = 154.0,
                q: float = 0.95, data_dir: str | None = None,
                load_spatial: str = "none") -> dict:
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

    measured = tepco_flow_stats(csv_path, q=q)

    result = build_and_solve(region, load_demand_config(), topology="snapped",
                             reconnect=True, backbone_kv=backbone_kv,
                             load_spatial=load_spatial)
    if result is None:
        raise FileNotFoundError(f"no network for region {region}")
    net_dc, dc_res, _net_ac, _ac_res, _info, _geom = result
    if not dc_res.get("converged"):
        raise RuntimeError("DC did not converge")

    operators = _load_operators(region, data_dir=data_dir)
    model: dict[str, float] = {}
    flows = net_dc.res_line["p_from_mw"].abs()
    vn = net_dc.bus["vn_kv"]
    for idx in net_dc.line.index:
        raw = str(net_dc.line.at[idx, "name"] or "")
        if not raw or raw.startswith(f"{region}_line_"):
            continue
        # trunk-class only (the disclosure covers 275 kV+) — a same-named
        # 154 kV line is a different physical line
        if float(vn.get(net_dc.line.at[idx, "from_bus"], 0)) < 200.0:
            continue
        p = float(flows.get(idx, 0.0))
        for part in raw.split(";"):           # OSM compound names
            key = _norm(part)
            if key and not _is_railway_only(key, operators):
                # series segments carry the same flow -> max is the
                # corridor's loaded section
                model[key] = max(model.get(key, 0.0), p)

    common = sorted(set(measured) & set(model))
    pairs = [(measured[k], model[k]) for k in common]
    out = {
        "region": region,
        "backbone_kv": backbone_kv,
        "load_spatial": load_spatial,
        "quantile": q,
        "n_measured_lines": len(measured),
        "n_model_named_lines": len(model),
        "n_matched": len(common),
    }
    if len(common) >= 5:
        meas_v = [p[0] for p in pairs]
        model_v = [p[1] for p in pairs]
        rho, pval = spearmanr(meas_v, model_v)
        ratios = sorted(m / x for x, m in zip(meas_v, model_v) if x > 1.0)
        out.update({
            "spearman_rho": round(float(rho), 3),
            "spearman_p": float(f"{pval:.2e}"),
            "median_model_over_measured": round(ratios[len(ratios) // 2], 2) if ratios else None,
        })
        diffs = sorted(common, key=lambda k: abs(model[k] - measured[k]), reverse=True)
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
    if "spearman_rho" in m:
        lines.append(
            f"  Spearman rank corr : {m['spearman_rho']} (p={m['spearman_p']:g})")
        lines.append(
            f"  median model/measured magnitude : {m['median_model_over_measured']}")
        lines.append("  largest mismatches (measured p95 vs model DC, MW):")
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
    ap.add_argument("--backbone", type=float, default=154.0)
    args = ap.parse_args(argv)

    if not os.path.exists(args.csv):
        print(f"no CSV at {args.csv} — fetch it first (see module docstring)")
        return 2
    if args.flows:
        m = match_flows(args.region, args.csv, backbone_kv=args.backbone)
        print(render_flows(m))
        if args.json:
            with open(args.json, "w", encoding="utf-8") as f:
                json.dump(m, f, indent=1, ensure_ascii=False)
            print(f"\nscorecard -> {args.json}")
        return 0
    m = match_tepco(args.region, args.csv)
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
