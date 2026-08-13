#!/usr/bin/env python3
"""発電所マスタDBを組む（observed層）。

二層構造:
  大規模電源 — OCCTO ユニット別発電実績（scripts/fetch_hks.py 取得済み）。
               発電所コード・名前・エリア・燃種・**実出力30分値**を持つ権威データ。
               原子力/火力/大水力など、系統に直接つながる電源。
  再エネ設備 — FIT/FIP 事業計画認定情報（scripts/fetch_fit.py 取得）。
               20kW以上の再エネを設備ID・出力・所在地つきで網羅。

両者は性質が違うので**混ぜず、source列で区別**して1つのマスタに積む。
AGJの発電所DB(plants_all)の穴（例: 柏崎刈羽=issue #37）を埋めるのは大規模電源側。

出典: 各レコードに source（occto_hks / fit_portal）と取得元を必ず残す。
      個人情報（事業者の氏名・住所・電話）はマスタに載せない — 施設情報のみ。
出力: data/external/system_disclosure/normalized/generator_master.csv（observed層・gitignore下）

使い方:
    python scripts/build_generator_master.py
"""
from __future__ import annotations

import glob
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
HKS = ROOT / "data" / "external" / "occto" / "hks"
FIT = ROOT / "data" / "external" / "fit"
NORM = ROOT / "data" / "external" / "system_disclosure" / "normalized"


def read_any(path: Path) -> pd.DataFrame:
    for enc in ("utf-8-sig", "cp932"):
        try:
            return pd.read_csv(path, encoding=enc, dtype=str)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"decode failed: {path}")


def from_occto() -> pd.DataFrame:
    """OCCTO ユニット別発電実績 → 発電所単位の大規模電源マスタ。"""
    files = sorted(HKS.glob("hks_*.csv"))
    if not files:
        return pd.DataFrame()
    df = pd.concat([read_any(f) for f in files], ignore_index=True)
    # 発電所コード単位に畳む（ユニットは束ねる）
    rows = []
    for code, g in df.groupby("発電所コード"):
        r0 = g.iloc[0]
        rows.append({
            "gen_id": f"occto:{code}",
            "name": str(r0.get("発電所名") or ""),
            "area": str(r0.get("エリア") or ""),
            "fuel": str(r0.get("発電方式・燃種") or ""),
            "n_units": g["ユニット名"].nunique(),
            "capacity_mw": None,          # OCCTOは定格を持たない。供給計画/GEMで後補完
            "scale": "large",
            "source": "occto_hks",
            "source_note": "OCCTO ユニット別発電実績公開システム（速報値）",
            "layer": "observed",
        })
    return pd.DataFrame(rows)


def from_fit() -> pd.DataFrame:
    """FIT 認定情報 → 再エネ設備マスタ（個人情報は落とす）。"""
    files = sorted(glob.glob(str(FIT / "*.xlsx")))
    if not files:
        return pd.DataFrame()
    rows = []
    for f in files:
        pref = re.search(r"\d+\.(.+?)_\d+\.xlsx", Path(f).name)
        pref = pref.group(1) if pref else ""
        try:
            d = pd.read_excel(f, sheet_name="認定設備", header=2, dtype=str)
        except Exception:  # noqa: BLE001
            continue
        d = d[d["設備ID"].notna()]
        for _, r in d.iterrows():
            mw = pd.to_numeric(str(r.get("発電出力（kW）") or "").replace(",", ""),
                               errors="coerce")
            rows.append({
                "gen_id": f"fit:{r['設備ID']}",
                "name": "",                       # FITは施設名を持たない
                "area": pref,                      # 都道府県（供給エリアではない）
                "fuel": str(r.get("発電設備区分") or ""),
                "n_units": 1,
                "capacity_mw": None if pd.isna(mw) else round(mw / 1000, 4),
                "location": str(r.get("発電設備の所在地") or ""),  # 施設所在地（個人住所ではない）
                "scale": "fit",
                "source": "fit_portal",
                "source_note": "再生可能エネルギー事業計画認定情報（資源エネルギー庁）",
                "layer": "observed",
            })
    return pd.DataFrame(rows)


def main() -> int:
    occto = from_occto()
    fit = from_fit()
    parts = [x for x in (occto, fit) if not x.empty]
    if not parts:
        print("ソースが無い。先に fetch_hks.py / fetch_fit.py を実行する")
        return 1
    master = pd.concat(parts, ignore_index=True)
    NORM.mkdir(parents=True, exist_ok=True)
    dest = NORM / "generator_master.csv"
    master.to_csv(dest, index=False, encoding="utf-8")

    print(f"発電所マスタ {len(master)} 件 → {dest.relative_to(ROOT)}")
    print(f"  大規模(OCCTO) {len(occto)} 発電所")
    print(f"  再エネ(FIT)   {len(fit)} 設備")
    if not fit.empty:
        cap = fit.capacity_mw.dropna()
        print(f"    FIT出力: 中央値 {cap.median():.3f}MW / 1MW以上 {(cap>=1).sum()} / 10MW以上 {(cap>=10).sum()}")
    summary = {
        "total": int(len(master)),
        "large_occto": int(len(occto)),
        "fit": int(len(fit)),
        "by_fuel": master.groupby("fuel").size().sort_values(ascending=False).head(12).to_dict(),
        "layer": "observed",
    }
    (NORM / "generator_master_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
