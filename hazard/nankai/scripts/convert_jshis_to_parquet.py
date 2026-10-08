#!/usr/bin/env python3
"""J-SHIS 250m メッシュ CSV → 軽量 parquet 変換.

入力 (hazard/nankai/data/external/jshis/ 配下の zip をそのまま読む; 本スクリプトは scripts/ に置く=追跡対象):
  * C-V3-ANNKI-AN177.zip  … 条件付超過確率地図データ
        AN177/MAP/C-V3-ANNKI-AN177-MAP-CASE1.csv
        列: CODE, AVE_SI, I45_PS, I50_PS, I55_PS, I60_PS
  * Z-V4-JAPAN-AMP-VS400_M250.zip … 表層地盤データ (全国)
        列: CODE, JCODE, AVS, ARV

出力 (hazard/nankai/data/derived/):
  * jshis_nankai_intensity.parquet
        [meshcode, lat, lon, jma_intensity, p_ge_5lower, p_ge_5upper,
         p_ge_6lower, p_ge_6upper, scenario_id, source_file]
  * jshis_amp_vs400.parquet
        [meshcode, lat, lon, amp, avs30, jcode]  (lon 129-142, lat 30-37.5 に限定)
  * jshis_an177_fault_points.parquet
        [sub_event, magnitude_mw, depth_rep_km, region_no, point_no, lon, lat, depth_km]

メッシュコード → 緯度経度 (JIS X 0410 ベースの 250m = 1/4 地域メッシュ, 10 桁):
  digits: pp uu q v r w d1 d2
    lat_sw = pp/1.5 + q/12 + r/120 + ((d1-1)//2)/240 + ((d2-1)//2)/480
    lon_sw = 100 + uu + v/8 + w/80 + ((d1-1)%2)/160 + ((d2-1)%2)/320
  中心 = 南西隅 + (1/960 deg, 1/640 deg)  (= 7.5" × 11.25" の半分)
  世界測地系 (JGD2000/WGS84 相当; J-SHIS 表記「世界測地系」).

使い方:
  python3 convert_jshis_to_parquet.py [--intensity] [--amp] [--fault]
  (引数なし = すべて)
"""
from __future__ import annotations

import argparse
import io
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent               # .../data/external/jshis
DERIVED = HERE.parent.parent / "derived"             # .../data/derived

INTENSITY_ZIP = HERE / "C-V3-ANNKI-AN177.zip"
INTENSITY_MEMBER = "AN177/MAP/C-V3-ANNKI-AN177-MAP-CASE1.csv"
FAULT_MEMBER = "AN177/FAULT/C-V3-ANNKI-AN177-FAULT-CASE1.csv"
AMP_ZIP = HERE / "Z-V4-JAPAN-AMP-VS400_M250.zip"

SCENARIO_ID = "JSHIS_C-V3-ANNKI-AN177-CASE1"
AMP_BBOX = dict(lon_min=129.0, lon_max=142.0, lat_min=30.0, lat_max=37.5)


def meshcode_to_center(code: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """10 桁 250m メッシュコード (int64) → 中心緯度経度."""
    c = code.to_numpy(dtype=np.int64)
    d2 = c % 10
    d1 = (c // 10) % 10
    w = (c // 100) % 10
    r = (c // 1000) % 10
    v = (c // 10000) % 10
    q = (c // 100000) % 10
    uu = (c // 1_000_000) % 100
    pp = c // 100_000_000
    lat_sw = pp / 1.5 + q / 12.0 + r / 120.0 + ((d1 - 1) // 2) / 240.0 + ((d2 - 1) // 2) / 480.0
    lon_sw = 100.0 + uu + v / 8.0 + w / 80.0 + ((d1 - 1) % 2) / 160.0 + ((d2 - 1) % 2) / 320.0
    return lat_sw + 1.0 / 960.0, lon_sw + 1.0 / 640.0


def _read_member(zpath: Path, member: str) -> bytes:
    with zipfile.ZipFile(zpath) as z:
        return z.read(member)


def _clean_code(s: pd.Series) -> pd.Series:
    # 規約上 %10-11c (末尾に 'N' が付く版がある) → 数字だけ残す
    return s.astype(str).str.strip().str.replace(r"\D", "", regex=True).astype(np.int64)


def convert_intensity() -> Path:
    raw = _read_member(INTENSITY_ZIP, INTENSITY_MEMBER)
    df = pd.read_csv(
        io.BytesIO(raw), comment="#", header=None,
        names=["CODE", "AVE_SI", "I45_PS", "I50_PS", "I55_PS", "I60_PS"],
        dtype={"CODE": str},
    )
    df["meshcode"] = _clean_code(df.pop("CODE"))
    lat, lon = meshcode_to_center(df["meshcode"])
    out = pd.DataFrame({
        "meshcode": df["meshcode"].astype("int64"),
        "lat": lat.astype("float64"),
        "lon": lon.astype("float64"),
        "jma_intensity": df["AVE_SI"].astype("float32"),
        "p_ge_5lower": df["I45_PS"].astype("float32"),
        "p_ge_5upper": df["I50_PS"].astype("float32"),
        "p_ge_6lower": df["I55_PS"].astype("float32"),
        "p_ge_6upper": df["I60_PS"].astype("float32"),
    })
    out["scenario_id"] = SCENARIO_ID
    out["source_file"] = f"{INTENSITY_ZIP.name}!{INTENSITY_MEMBER}"
    out["scenario_id"] = out["scenario_id"].astype("category")
    out["source_file"] = out["source_file"].astype("category")
    DERIVED.mkdir(parents=True, exist_ok=True)
    p = DERIVED / "jshis_nankai_intensity.parquet"
    out.to_parquet(p, index=False, compression="zstd")
    print(f"[intensity] rows={len(out):,} -> {p} ({p.stat().st_size/1e6:.1f} MB)")
    print(out.describe().T.to_string())
    return p


def convert_amp() -> Path:
    with zipfile.ZipFile(AMP_ZIP) as z:
        members = [n for n in z.namelist() if n.lower().endswith(".csv")]
        assert len(members) == 1, members
        member = members[0]
        raw = z.read(member)
    # V4 (2020年版〜) は V3 規約の 4 列に AVS_EB, AVS_REF が追加された 6 列
    df = pd.read_csv(
        io.BytesIO(raw), comment="#", header=None,
        names=["CODE", "JCODE", "AVS", "ARV", "AVS_EB", "AVS_REF"],
        dtype={"CODE": str, "AVS_EB": str}, na_values={"AVS_EB": ["-"]},
        skipinitialspace=True,
    )
    df["meshcode"] = _clean_code(df.pop("CODE"))
    lat, lon = meshcode_to_center(df["meshcode"])
    df["lat"], df["lon"] = lat, lon
    n_all = len(df)
    b = AMP_BBOX
    m = (df.lon >= b["lon_min"]) & (df.lon <= b["lon_max"]) & (df.lat >= b["lat_min"]) & (df.lat <= b["lat_max"])
    n_bbox = int(m.sum())
    # JCODE=0 / ARV=0 は海域・欠測 (地盤モデル無し) → 落とす
    m &= (df["JCODE"] > 0) & (df["ARV"] > 0)
    df = df[m]
    out = pd.DataFrame({
        "meshcode": df["meshcode"].astype("int64"),
        "lat": df["lat"].astype("float64"),
        "lon": df["lon"].astype("float64"),
        "amp": df["ARV"].astype("float32"),
        "avs30": df["AVS"].astype("float32"),
        "jcode": df["JCODE"].astype("int8"),
        "avs_eb": pd.to_numeric(df["AVS_EB"], errors="coerce").astype("float32"),
        "avs_ref": df["AVS_REF"].astype("int8"),
    }).reset_index(drop=True)
    DERIVED.mkdir(parents=True, exist_ok=True)
    p = DERIVED / "jshis_amp_vs400.parquet"
    out.to_parquet(p, index=False, compression="zstd")
    print(f"[amp] member={member} rows_all={n_all:,} rows_bbox={n_bbox:,} rows_valid={len(out):,} -> {p} ({p.stat().st_size/1e6:.1f} MB)")
    print(out.describe().T.to_string())
    return p


def convert_fault() -> Path:
    """C-V3-ANNKI-AN177-FAULT-CASE1.csv (構成地震ブロック + 構成点ブロック) → 点列."""
    text = _read_member(INTENSITY_ZIP, FAULT_MEMBER).decode("cp932")
    lines = [l for l in text.splitlines() if l.strip() and not l.startswith("#")]
    hdr = [x.strip() for x in lines[0].split(",")]          # PLE_ANNKI, AN177, n_sub
    n_sub = int(hdr[2])
    rows = []
    i = 1
    for _ in range(n_sub):
        sub, mag, dep, npts, region = [x.strip() for x in lines[i].split(",")]
        i += 1
        mag = float(mag)
        for _ in range(int(npts)):
            k, lon_tky, lat_tky, lon_w, lat_w, depth = [x.strip() for x in lines[i].split(",")]
            i += 1
            rows.append((int(sub), abs(mag), float(dep), int(region), int(k), float(lon_w), float(lat_w), float(depth)))
    out = pd.DataFrame(rows, columns=[
        "sub_event", "magnitude_mw", "depth_rep_km", "region_no", "point_no", "lon", "lat", "depth_km"])
    out["scenario_id"] = SCENARIO_ID
    p = DERIVED / "jshis_an177_fault_points.parquet"
    out.to_parquet(p, index=False)
    print(f"[fault] eq={hdr[0]} pattern={hdr[1]} sub_events={n_sub} points={len(out)} -> {p}")
    print(out.describe().T.to_string())
    return p


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--intensity", action="store_true")
    ap.add_argument("--amp", action="store_true")
    ap.add_argument("--fault", action="store_true")
    a = ap.parse_args(argv)
    do_all = not (a.intensity or a.amp or a.fault)
    if a.intensity or do_all:
        convert_intensity()
    if a.fault or do_all:
        convert_fault()
    if a.amp or do_all:
        convert_amp()


if __name__ == "__main__":
    sys.exit(main())
