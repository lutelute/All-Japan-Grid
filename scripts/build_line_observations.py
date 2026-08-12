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
import unicodedata
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "external" / "system_disclosure"
NORM = SRC / "normalized"

ARROW_RX = re.compile(r"[→⇒]")


def scope_of(filename: str) -> str:
    """jisseki_kikan01_line_2025_08.csv → 'kikan01' / sys_capa_local20_line_… → 'local20'

    東京は独自命名（jisseki_154kV03.csv 等）なので電圧表記をそのまま scope にする。
    """
    m = re.search(r"_((?:kikan|local)\d*)_", filename)
    if m:
        return m.group(1)
    # 東京は jisseki_154kV05.csv / jisseki_chiba01.csv のように
    # **電圧別と県別の連番ファイル**が混在する。ここを潰すと東京の設備IDは
    # 列位置なので `tokyo:?:c12` が別ファイルの列12と衝突し、
    # **別の線路の系列が混ざる**（運用容量の5.6倍という不可能な潮流が出た）。
    # 取りこぼしを作らないため、jisseki_ 以降をそのまま scope にする。
    m = re.search(r"jisseki_(.+?)\.csv$", filename)
    if m:
        return m.group(1)
    return re.sub(r"\.csv$", "", filename)


def scope_family(scope: str) -> str:
    """kikan01 と kikan00 は同じ基幹系統を指す（社ごとに採番が違うだけ）。"""
    return "kikan" if scope.startswith("kikan") else scope


TEPCO_COL_RX = re.compile(r"^(.+?)\s*[-−–]\s*(.+)$")
# `1B` `1･2･3･4B` は変圧器バンク。送電線ではないので落とす。
TEPCO_BANK_RX = re.compile(r"^[0-9０-９･・,\s]*[BＢ]$")


CIRCUIT_TAIL_RX = re.compile(r"[0-9０-９･・,、\s]*[LＬ]\s*$")


def norm_name(s: object) -> str:
    """線路名の照合キー。回線表記（1･2L / 2L）と記号ゆれを落とす。"""
    n = unicodedata.normalize("NFKC", str(s))
    n = re.sub(r"[\s　・･,，]", "", n)
    return CIRCUIT_TAIL_RX.sub("", n).strip()


def fy_from_stamp(stamp: object) -> str | None:
    """`2024年04月01日 00時` → "2024"（日本の年度は4月始まり。1〜3月は前年度）。"""
    m = re.search(r"(\d{4})\s*[年/\-.]\s*(\d{1,2})", str(stamp))
    if not m:
        return None
    y, mo = int(m.group(1)), int(m.group(2))
    return str(y - 1 if mo <= 3 else y)


def _tepco_voltage(path: Path) -> float | None:
    """東京はファイル名/フォルダ名でしか電圧が分からない。"""
    s = str(path)
    if "66kV" in s:
        return 66.0
    if "154kV" in s:
        return 154.0
    if "kikan" in s:
        return 275.0     # 基幹（500/275混在。低い方を採り過大評価を避ける）
    return None


def read_flow_tepco(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """東京電力PGの潮流実績。標準様式と違い **ヘッダ1行** で、
    列名が `京浜(変) - 東京南線1･2L`（変電所 - 設備名）という独自形式。

    変圧器バンクと送電線が同じ表に混在するので、送電線だけ拾う。
    相手側変電所は列名からは分からない（to は空になる）。
    線路名は OSM の name と直接照合できるので、地図には載せられる。
    """
    raw = pd.read_csv(path, encoding="cp932", header=None, dtype=str)
    kv = _tepco_voltage(path)
    meta = []
    for c in range(1, raw.shape[1]):
        col = str(raw.iloc[0, c]).strip()
        m = TEPCO_COL_RX.match(col)
        if not m:
            continue
        sub, tail = m.group(1).strip(), m.group(2).strip()
        if TEPCO_BANK_RX.match(tail):
            continue                     # 変圧器バンクは対象外
        meta.append({
            "col": c,
            "equipment_no": f"c{c}",     # 東京は設備番号が無いので列位置で代用
            "voltage_kv": kv,
            "name": tail,
            "flow_positive_from": sub,
            "flow_positive_to": "",      # 相手端は非公開
        })
    ts = raw.iloc[1:].reset_index(drop=True)
    return pd.DataFrame(meta), ts


def read_flow(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """潮流実績CSVを (メタ, 時系列) に分ける。

    標準様式はヘッダ4行: 送電線No. / 電圧(kV) / 送電線名 / 潮流正方向。
    東京だけ独自形式（ヘッダ1行）なので自動で振り分ける。
    """
    raw = pd.read_csv(path, encoding="cp932", header=None, dtype=str)
    if str(raw.iloc[0, 0]).strip() in ("日時", "年月日時"):
        return read_flow_tepco(path)
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


def _read_any(path: Path) -> pd.DataFrame:
    """社によって CP932 と UTF-8(BOM) が混在するので順に試す。

    東京の空容量CSVは UTF-8 BOM、潮流実績は CP932。決め打ちすると片方で落ちる。
    """
    last: Exception | None = None
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            return pd.read_csv(path, encoding=enc, header=None, dtype=str)
        except UnicodeDecodeError as exc:
            last = exc
    raise last or ValueError(f"decode failed: {path}")


def read_capacity(path: Path) -> pd.DataFrame:
    """空容量一覧を読む。

    ヘッダが1行の社（四国）と、`送電線名 / 電圧 / 回線数…` が2〜3行に
    分かれる社（東京）がある。**「送電線名」を含む行を起点に、続く行を
    縦に連結して1つの列名**にすることで両方を同じ形に均す。
    """
    raw = _read_any(path)
    hrow = None
    for i in range(min(12, len(raw))):
        if any("送電線名" in str(v) for v in raw.iloc[i]):
            hrow = i
            break
    if hrow is None:
        raise ValueError(f"ヘッダ行が見つからない: {path.name}")

    # ヘッダは最大3行ぶん縦に連結（"運用"+"容量値"+"(MW)" → "運用容量値(MW)"）
    span = min(3, len(raw) - hrow)
    names = []
    for c in range(raw.shape[1]):
        parts = [str(raw.iloc[hrow + k, c]) for k in range(span)]
        parts = [re.sub(r"\s", "", p) for p in parts if p and p != "nan"]
        names.append("".join(parts))
    d = raw.iloc[hrow + span:].reset_index(drop=True)
    d.columns = names
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
    # 標準様式（社共通の命名）＋ 東京の独自配置（ZIP展開したサブフォルダ）
    flow_paths = (sorted(SRC.glob("*/flow_actual/jisseki_*_line_*.csv"))
                  + sorted(SRC.glob("tokyo/flow_actual/*/*/*.csv")))
    for flow_path in flow_paths:
        utility = flow_path.parts[len(SRC.parts)]
        if args.utility and utility != args.utility:
            continue
        scope = scope_of(flow_path.name)
        year = re.search(r"_(\d{4})_\d{2}\.csv", flow_path.name)
        year = year.group(1) if year else None

        try:
            meta, ts = read_flow(flow_path)
        except Exception as exc:  # noqa: BLE001
            print(f"! {flow_path.name}: {exc}")
            continue

        # 東京はファイル名に年度が入らない（jisseki_154kV03.csv）。
        # 年度をハードコードすると翌年に黙って古い値を指すので、
        # **データ自身の最初の日時**から年度を決める（4月始まり）。
        if year is None:
            year = fy_from_stamp(ts.iloc[0, 0]) if len(ts) else None
        year = year or "?"

        # 同じ系統区分の空容量CSV（最新のもの）
        cap = pd.DataFrame()
        if utility == "tokyo":
            # 東京の潮流実績は「電圧別（154kV/kikan）」と「県別（chiba01…）」が混在する。
            # **県別ファイルはその県の空容量だけで照合する** — 同名線路が複数県に
            # 実在する（小北線=埼玉126MW/栃木1131MW）ため、全県を混ぜると誤マッチする。
            pref = re.sub(r"\d+$", "", scope)          # chiba01 → chiba
            pats = ([f"tokyo/capacity/csv_yosochoryu_{pref}/*soudensen*.csv"]
                    if pref not in ("154kV", "kikan", "")
                    else ["tokyo/capacity/*/*soudensen*.csv"])
            frames = []
            for pat in pats:
                for path in sorted(SRC.glob(pat)):
                    try:
                        frames.append(read_capacity(path))
                    except Exception:  # noqa: BLE001
                        continue
            if frames:
                cap = pd.concat(frames, ignore_index=True)
        else:
            cands = sorted(SRC.glob(f"{utility}/capacity/sys_capa_{scope}*_line_*.csv"))
            if not cands:  # kikan00 と kikan01 の採番ゆれを吸収
                cands = sorted(SRC.glob(
                    f"{utility}/capacity/sys_capa_{scope_family(scope)}*_line_*.csv"))
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
                rec["capacity_match"] = "by_no" if len(c) else None
                if not len(c) and m["name"]:
                    # 東京は潮流実績側に設備番号が無い（列位置を代用している）ため
                    # 番号では突き合わない。**線路名**で結ぶ。
                    key = norm_name(m["name"])
                    c = cap[cap["name"].map(norm_name) == key]
                    if len(c) > 1:
                        # 同名の線路が複数県に実在する（小北線=埼玉126MW/栃木1131MW 等、
                        # 1,057本中159本が重複）。東京の潮流実績には県の情報が無いので
                        # **名前だけでは一意に決まらない**。誤った容量で負荷率を出すより、
                        # 容量を付けない方がよい。
                        rec["capacity_match"] = "ambiguous"
                        c = c.iloc[0:0]
                    elif len(c):
                        rec["capacity_match"] = "by_name"
                if len(c):
                    c = c.iloc[0]
                    rec.update({
                        "circuits": c.circuits, "facility_mw": c.facility_mw,
                        "operational_mw": c.operational_mw, "constraint": c.constraint,
                        "expected_flow_mw": c.expected_flow_mw,
                    })
                    # 実測が**設備容量(100%×回線数)**を超えるのは物理的にありえない。
                    # 起きているなら別設備に結んでいる。容量を外して負荷率を出さない。
                    # 判定は p95 ではなく **最大値**で行う。p95 だと 1 断面でも
                    # 設備容量を超える明確な誤マッチを取りこぼす（66kV で多発した）。
                    fac = rec.get("facility_mw")
                    peak = rec.get("flow_max_abs_mw")
                    if fac and peak and peak > fac:
                        rec["capacity_match"] = "rejected_over_facility"
                        for k in ("circuits", "facility_mw", "operational_mw",
                                  "constraint", "expected_flow_mw"):
                            rec.pop(k, None)

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
