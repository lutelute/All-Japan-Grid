#!/usr/bin/env python3
"""事業者公表の3様式を「送電線No.」で結合し、線路ごとの観測レコードを作る。

    様式5 インピーダンス  → R(%) / X(%) / Y/2(%)          （1000MVAベース）
    空容量一覧            → 設備容量 / 運用容量 / 制約要因 / 予想潮流 / 空容量
    潮流実績              → 8,760時間の実潮流(MW) と潮流正方向(A変電所→B変電所)

3様式はいずれも同じ **(事業者, 系統区分, 送電線No.)** を主キーにしている。
系統区分(kikan / local01…)を跨ぐと No. が重複するので、必ず3つ組で突き合わせる。

出力は **observed 層**（docs/OBSERVED_VS_DERIVED.md）。AGJの潮流計算結果とは混ぜない。
負荷率は「実測潮流 ÷ **公表の運用容量**」であって、熱容量の理論値ではない。
運用容量には安定度限界で決まる線が実在し（四国500kV基幹は全てそれ）、
理論値で割ると3倍過大評価になるため、この区別が負荷率の正しさを決める。

使い方:
    python scripts/build_line_observations.py                 # 全社
    python scripts/build_line_observations.py --utility shikoku
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "external" / "system_disclosure"
NORM = SRC / "normalized"

ARROW_RX = re.compile(r"[→⇒]")


def scope_of(filename: str) -> str:
    """jisseki_kikan01_line_2025_08.csv → 'kikan01' / sys_capa_local20_line_… → 'local20'"""
    m = re.search(r"_((?:kikan|local)\d*)_", filename)
    return m.group(1) if m else "?"


def scope_family(scope: str) -> str:
    """kikan01 と kikan00 は同じ基幹系統を指す（社ごとに採番が違うだけ）。"""
    return "kikan" if scope.startswith("kikan") else scope


def read_flow(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """潮流実績CSVを (メタ, 時系列) に分ける。

    ヘッダは4行: 送電線No. / 電圧(kV) / 送電線名 / 潮流正方向。5行目以降が時刻×MW。
    """
    raw = pd.read_csv(path, encoding="cp932", header=None, dtype=str)
    hdr = {}
    for i in range(min(8, len(raw))):
        key = str(raw.iloc[i, 0]).strip()
        if "送電線No" in key:
            hdr["no"] = i
        elif key.startswith("電圧"):
            hdr["kv"] = i
        elif "送電線名" in key:
            hdr["name"] = i
        elif "潮流正方向" in key:
            hdr["dir"] = i
    if "no" not in hdr or "name" not in hdr:
        raise ValueError(f"ヘッダを特定できない: {path.name}")

    first_data = max(hdr.values()) + 1
    meta = []
    for c in range(1, raw.shape[1]):
        direction = str(raw.iloc[hdr["dir"], c]) if "dir" in hdr else ""
        frm = to = ""
        if ARROW_RX.search(direction):
            frm, to = [s.strip() for s in ARROW_RX.split(direction, 1)]
        meta.append({
            "col": c,
            "equipment_no": str(raw.iloc[hdr["no"], c]).strip(),
            "voltage_kv": pd.to_numeric(raw.iloc[hdr["kv"], c], errors="coerce")
            if "kv" in hdr else None,
            "name": str(raw.iloc[hdr["name"], c]).strip(),
            "flow_positive_from": frm,
            "flow_positive_to": to,
        })
    ts = raw.iloc[first_data:].reset_index(drop=True)
    return pd.DataFrame(meta), ts


def summarize_flow(ts: pd.DataFrame, col: int) -> dict:
    """1線路ぶんの潮流列を要約する。'―' 等の欠測は落とす。"""
    v = pd.to_numeric(ts.iloc[:, col].astype(str).str.replace(",", ""), errors="coerce").dropna()
    if v.empty:
        return {"n_obs": 0}
    return {
        "n_obs": int(len(v)),
        "flow_mean_mw": round(float(v.mean()), 1),
        "flow_p95_abs_mw": round(float(v.abs().quantile(0.95)), 1),
        "flow_max_abs_mw": round(float(v.abs().max()), 1),
        "reverse_share": round(float((v < 0).mean()), 3),
    }


def read_capacity(path: Path) -> pd.DataFrame:
    d = pd.read_csv(path, encoding="cp932", header=1)
    d.columns = [re.sub(r"\s", "", str(c)) for c in d.columns]
    cols = list(d.columns)

    def pick(*keys):
        for k in keys:
            for c in cols:
                if k in c:
                    return c
        return None

    num = lambda s: pd.to_numeric(  # noqa: E731
        pd.Series(s).astype(str).str.replace(",", "").str.strip(), errors="coerce"
    )
    out = pd.DataFrame({
        "equipment_no": d[cols[0]].astype(str).str.strip(),
        "name": d[pick("送電線名")].astype(str).str.strip() if pick("送電線名") else "",
        "circuits": num(d[pick("回線数")]) if pick("回線数") else None,
        "facility_mw": num(d[pick("設備容量")]) if pick("設備容量") else None,
        "operational_mw": num(d[pick("運用容量値", "運用容量")]) if pick("運用容量値", "運用容量") else None,
        "constraint": d[pick("制約要因")].astype(str).str.strip() if pick("制約要因") else "",
        "expected_flow_mw": num(d[pick("予想潮流")]) if pick("予想潮流") else None,
    })
    return out[out.equipment_no.notna() & (out.equipment_no != "nan")]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--utility")
    args = ap.parse_args()

    imp = pd.read_csv(NORM / "impedance_lines.csv")
    imp["scope_f"] = imp.scope.map(scope_family)
    imp["equipment_no"] = imp.equipment_no.astype(str).str.strip()

    rows: list[dict] = []
    for flow_path in sorted(SRC.glob("*/flow_actual/jisseki_*_line_*.csv")):
        utility = flow_path.parts[len(SRC.parts)]
        if args.utility and utility != args.utility:
            continue
        scope = scope_of(flow_path.name)
        year = re.search(r"_(\d{4})_\d{2}\.csv", flow_path.name)
        year = year.group(1) if year else "?"

        try:
            meta, ts = read_flow(flow_path)
        except Exception as exc:  # noqa: BLE001
            print(f"! {flow_path.name}: {exc}")
            continue

        # 同じ系統区分の空容量CSV（最新のもの）
        cap = pd.DataFrame()
        cands = sorted(SRC.glob(f"{utility}/capacity/sys_capa_{scope}*_line_*.csv"))
        if not cands:  # kikan00 と kikan01 の採番ゆれを吸収
            cands = sorted(SRC.glob(f"{utility}/capacity/sys_capa_{scope_family(scope)}*_line_*.csv"))
        if cands:
            try:
                cap = read_capacity(cands[-1])
            except Exception as exc:  # noqa: BLE001
                print(f"  (capacity読めず {cands[-1].name}: {exc})")

        sub_imp = imp[(imp.utility == utility) & (imp.scope_f == scope_family(scope))]

        for _, m in meta.iterrows():
            rec = {
                "utility": utility, "scope": scope, "year": year,
                "equipment_no": m.equipment_no, "name": m["name"],
                "voltage_kv": m.voltage_kv,
                "from_node": m.flow_positive_from, "to_node": m.flow_positive_to,
                "layer": "observed",
                "source_flow": str(flow_path.relative_to(ROOT)),
            }
            rec.update(summarize_flow(ts, m.col))

            if not cap.empty:
                c = cap[cap.equipment_no == m.equipment_no]
                if len(c):
                    c = c.iloc[0]
                    rec.update({
                        "circuits": c.circuits, "facility_mw": c.facility_mw,
                        "operational_mw": c.operational_mw, "constraint": c.constraint,
                        "expected_flow_mw": c.expected_flow_mw,
                    })

            i = sub_imp[sub_imp.equipment_no == m.equipment_no]
            if len(i):
                i0 = i.iloc[0]
                rec.update({
                    "R_pct": i0.R_pct, "X_pct": i0.X_pct, "B_half_pct": i0.B_half_pct,
                    "base_mva": 1000, "n_circuit_records": int(len(i)),
                })

            # 負荷率は「実測 ÷ 公表の運用容量」。理論熱容量では割らない。
            op = rec.get("operational_mw")
            if op and op > 0 and rec.get("flow_p95_abs_mw") is not None:
                rec["load_factor_p95"] = round(rec["flow_p95_abs_mw"] / op, 3)
            rows.append(rec)

    out = pd.DataFrame(rows)
    if out.empty:
        print("結合できるデータが無い")
        return 1

    NORM.mkdir(parents=True, exist_ok=True)
    dest = NORM / "line_observations.csv"
    out.to_csv(dest, index=False, encoding="utf-8")

    has = lambda c: int(out[c].notna().sum()) if c in out else 0  # noqa: E731
    summary = {
        "lines_total": int(len(out)),
        "with_flow": int((out.n_obs > 0).sum()),
        "with_capacity": has("operational_mw"),
        "with_impedance": has("X_pct"),
        "with_all_three": int(
            ((out.n_obs > 0) & out.get("operational_mw").notna() & out.get("X_pct").notna()).sum()
        ) if "operational_mw" in out and "X_pct" in out else 0,
        "with_direction": int((out.from_node != "").sum()),
        "by_utility": out.groupby("utility").size().to_dict(),
        "layer": "observed",
    }
    (NORM / "line_observations_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    print(f"線路レコード {summary['lines_total']}")
    print(f"  潮流実績あり   {summary['with_flow']}")
    print(f"  運用容量あり   {summary['with_capacity']}")
    print(f"  インピーダンス {summary['with_impedance']}")
    print(f"  3様式すべて    {summary['with_all_three']}")
    print(f"  向き(from→to)  {summary['with_direction']}")
    print(f"\n→ {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
