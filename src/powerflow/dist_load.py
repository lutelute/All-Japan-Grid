"""介入#65(2026-11-17・既定 OFF): ajg-dist の配電の需要で、県の中の需要の配り方を決める.

AJG は県(北海道は全域が 1 県)の需要を、点の数 × 電圧の重みで一様に配る(`allocate_loads`)。
北海道では田舎の長い線に需要が載りすぎ、北の宗谷・名寄の電圧が下がった
(docs/reports/hokkaido_north_voltage_2026-11-15.md)。ajg-dist は国勢調査の世帯と建物の面積から
配電用変電所ごとの需要を下から積んでいる(`Store.load_set`)。その**割合だけ**を使い、県の需要の合計は
AJG のまま(地域のピーク × 負荷率 × 県別の実需要の割合)にする。

- 突き合わせは位置で行う。dist の `agj_bus`(正典の点の id)は、正典を作り直すと古くなる
  (2026-11-16: 母線の付いた 2,593 行のうち 654 行の id が今の正典に無い)。dist の一覧(catalog.csv)の
  起点の座標を使う
- dist の起点の需要は、半径 R km の中の需要の点(77 kV 以下の母線)へ、電圧の重み × ガウスの重みでならして配る
  (起点 1 つに載る需要が大きい所がある。dist 自身も標準の規模 60 MVA を超える起点を 562 か所と記録している)
- 観測の地点需要(介入#30)で固定した母線から 0.5 km 以内の起点は使わない(観測と二重に数えない)
- 使う起点は、網の区域(zone)と dist の地域(region)が同じものだけ。半径の中に需要の点が無い起点も使わない(数は帳簿)
- 量の目安にはしない(dist の北海道の合計は地域のピークの 1.28 倍で、住宅以外の分が大きい理由は未解明)

置き場の場所(研究室の場所は書かない): 環境変数 `AJG_DIST_ROOT`(既定はこのリポジトリの隣の ajg-dist)と
`AJG_DIST_STORE`(既定は `<root>/data/std`)。dist の Python は `<root>/.venv/bin/python` があればそれを使う。
"""
from __future__ import annotations

import csv
import io
import math
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NEAR_PINNED_KM = 0.5      # 観測の地点需要の母線からこの距離の中の起点は使わない
MAX_CAND_KV = 77.5        # 配る先: 77 kV 以下の需要の点


def dist_root() -> Path:
    return Path(os.environ.get("AJG_DIST_ROOT") or (ROOT.parent / "ajg-dist"))


def dist_store() -> Path:
    return Path(os.environ.get("AJG_DIST_STORE") or (dist_root() / "data" / "std"))


def _km(lat1, lon1, lat2, lon2) -> float:
    return math.hypot((lat1 - lat2) * 111.0, (lon1 - lon2) * 111.0 * math.cos(math.radians(lat1)))


def _dist_python() -> str:
    p = dist_root() / ".venv" / "bin" / "python"
    return str(p) if p.exists() else sys.executable


def _git_head(path: Path) -> str | None:
    try:
        return subprocess.run(["git", "-C", str(path), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=10).stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None


def parse_points(load_set_csv: str, catalog_rows: list[dict]) -> list[dict]:
    """load_set の CSV(文字列)と一覧の行から、起点ごとの {lat, lon, p_mw, region, osm_keys} を作る。

    load_set の 1 行は同じ母線に付く起点をまとめた行(`osm_keys` を ; でつなぐ)。座標は起点の平均。
    一覧に座標の無い行は使わない(数は呼ぶ側が数える)。"""
    pos = {r["osm_key"]: (float(r["lat"]), float(r["lon"])) for r in catalog_rows
           if r.get("lat") and r.get("lon")}
    out = []
    for r in csv.DictReader(io.StringIO(load_set_csv)):
        keys = [k for k in (r.get("osm_keys") or "").split(";") if k]
        ll = [pos[k] for k in keys if k in pos]
        p = float(r.get("p_mw") or 0.0)
        if not ll or p <= 0:
            continue
        out.append({"lat": sum(a for a, _ in ll) / len(ll), "lon": sum(b for _, b in ll) / len(ll),
                    "p_mw": p, "region": r.get("region"), "osm_keys": ";".join(keys)})
    return out


@lru_cache(maxsize=1)
def load_points() -> tuple[tuple, dict]:
    """dist の置き場から起点の需要を読む。読めなければ例外(切り替えを入れたのに読めないのは止める)。"""
    store = dist_store()
    cat = store / "catalog.csv"
    if not cat.exists():
        raise FileNotFoundError(f"ajg-dist の置き場が無い: {store}(AJG_DIST_ROOT・AJG_DIST_STORE で指す)")
    with open(cat, encoding="utf-8") as f:
        catalog = list(csv.DictReader(f))
    pts = []
    n_rows = 0
    import tempfile
    for area in ("50hz", "60hz"):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / f"load_set_{area}.csv"
            r = subprocess.run([_dist_python(), "-m", "ajg_dist", "--store", str(store), "load-set",
                                "--area", area, "--out", str(out)],
                               capture_output=True, text=True, cwd=str(dist_root()), timeout=600)
            if r.returncode != 0 or not out.exists():
                raise RuntimeError(f"ajg-dist の load-set が失敗: {r.stderr[-400:]}")
            text = out.read_text(encoding="utf-8")
        n_rows += max(text.count("\n") - 1, 0)
        pts += parse_points(text, catalog)
    meta = {"store": store.name, "dist_git": _git_head(dist_root()), "n_rows": n_rows,
            "n_points": len(pts), "p_total_mw": round(sum(p["p_mw"] for p in pts), 1)}
    return tuple(tuple(sorted(p.items())) for p in pts), meta


def bus_weights(net, points, radius_km: float = 20.0, pinned=None, vweight=None,
                lonlat=None) -> tuple[dict, dict]:
    """起点の需要を母線へならして配り、{母線: 重み(MW 相当)} と帳簿を返す。

    points: [{lat, lon, p_mw, ...}]。pinned: 観測で固定した母線の集合(その 0.5 km の中の起点は使わない)。
    vweight(b): 電圧の重み(allocate_loads と同じ)。lonlat(net, b) → (lon, lat)。
    返す重みは「割合」としてだけ使う(allocate_loads が県・区域の需要の合計に合わせる)。"""
    pinned = set(pinned or ())
    is_sub = net.bus["type"] != "n"
    zones = {str(z) for z in net.bus["zone"].dropna().unique()}
    cand, pin_xy = [], []
    for b in net.bus.index:
        if not (is_sub.get(b, False) and net.bus.at[b, "in_service"]):
            continue
        x, y = lonlat(net, b)
        if x is None:
            continue
        if b in pinned:
            pin_xy.append((y, x))
            continue
        if float(net.bus.at[b, "vn_kv"]) <= MAX_CAND_KV:
            cand.append((y, x, b, vweight(b)))
    w: dict = {}
    n_used = n_pinned = n_far = n_other = 0
    sigma = max(radius_km / 2.0, 1e-6)
    for pt in points:
        la, lo, p = pt["lat"], pt["lon"], pt["p_mw"]
        if pt.get("region") and pt["region"] not in zones:
            n_other += 1                       # ほかの島の起点
            continue
        if any(_km(la, lo, a, b) <= NEAR_PINNED_KM for a, b in pin_xy):
            n_pinned += 1
            continue
        if not cand:
            break
        near = [(b, vw, _km(la, lo, y, x)) for (y, x, b, vw) in cand
                if abs(y - la) * 111.0 <= radius_km]
        near = [(b, vw, d) for b, vw, d in near if d <= radius_km]
        if not near:
            # 半径の中に需要の点が無い起点は使わない(網の外・島の端。数だけ残す)
            n_far += 1
            continue
        ks = [(b, vw * math.exp(-(d / sigma) ** 2)) for b, vw, d in near]
        tk = sum(k for _, k in ks) or 1.0
        for b, k in ks:
            w[b] = w.get(b, 0.0) + p * k / tk
        n_used += 1
    ledger = {"radius_km": radius_km, "n_points": len(points) - n_other, "n_points_used": n_used,
              "n_points_near_pinned": n_pinned, "n_points_outside_radius": n_far,
              "n_bus_weighted": len(w), "p_used_mw": round(sum(w.values()), 1)}
    return w, ledger
