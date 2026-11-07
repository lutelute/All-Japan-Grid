#!/usr/bin/env python3
"""公開する GeoJSON に出典の表示と透かしを入れる / 他所のデータに AJG 由来の印があるかを調べる。

使い方
    python scripts/publish_stamp.py stamp docs/            # Pages に上げる直前に (deploy-pages.yml)
    python scripts/publish_stamp.py verify 疑わしいファイル...  # 他所のデータを調べる

stamp がすること (正典 data/ と git にコミットされた docs/ は変えない。CI の中で公開する写しだけを変える)
  1. 各 FeatureCollection の先頭に "attribution" を足す (ODbL の表示: OSM と All-Japan-Grid)。
  2. 鍵 (環境変数 AJG_WATERMARK_KEY) があれば、geometry の座標を小数 7 桁にそろえ、
     7 桁目を「鍵と、その点の 6 桁までの値」から決まる 1〜9 の数字にする。
     - 6 桁目までの数字は元のまま (切り捨て)。ずれは 1e-6 度 (約 10 cm) 未満で、
       toFixed(5) 以下で丸めた値は元と同じ。地図の JS の突き合わせ (grid_map.js・ybus_sim.js・
       editor.html の座標の鍵) は透かしを入れていない built/all.json などとも合ったまま。
     - 同じ点は、どのファイルでも同じ値になる (点の値だけで決まるため)。線と変電所の端の一致は崩れない。
     - 鍵が無ければ 2 は飛ばす (fork や手元での実行)。
  一度 stamp したファイルは attribution.stamp を見て二度目は触らない。

verify が見るもの
  A. 鍵の要らない手がかり: AJG が自分で付けた名前 (住所から付けた「〜丁目変電所」、
     「〇〇送電線_番号」、「A変電所~B変電所線」)。OSM には無い名前なので、含まれていれば AJG 由来。
     座標を丸められても残る。
  B. 鍵の印: 小数 7 桁の座標の 7 桁目が鍵の数字と一致する割合。偶然なら約 1/9。
     鍵は AJG_WATERMARK_KEY か、macOS のキーチェーン (サービス名 ajg-watermark) から読む。
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import hmac
import json
import math
import os
import re
import subprocess
from decimal import Decimal
import sys
from pathlib import Path

STAMP_VERSION = "ajg-stamp-1"
ATTRIBUTION = {
    "dataset": "All-Japan-Grid",
    "url": "https://github.com/lutelute/All-Japan-Grid",
    "license": "ODbL-1.0 (data) / MIT (code)",
    "attribution": "© OpenStreetMap contributors; All-Japan-Grid (R. Shigenobu, University of Fukui)",
    "notice": "Derived database under ODbL-1.0: keep this attribution and share alike.",
}
KEYCHAIN_SERVICE = "ajg-watermark"
REPO = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- key

def load_key(required: bool = False) -> bytes | None:
    k = os.environ.get("AJG_WATERMARK_KEY", "").strip()
    if not k and sys.platform == "darwin":
        try:
            k = subprocess.run(
                ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            k = ""
    if not k:
        if required:
            sys.exit("鍵がありません (AJG_WATERMARK_KEY かキーチェーンの ajg-watermark)")
        return None
    return k.encode()


# ---------------------------------------------------------------- fingerprint

def _digit(key: bytes, qlon: int, qlat: int, axis: str) -> int:
    """6 桁までの点の値 (整数化) から 1〜9 の数字を決める。0 は末尾で消えるので使わない。"""
    mac = hmac.new(key, f"{qlon},{qlat},{axis}".encode(), hashlib.sha256).digest()
    return mac[0] % 9 + 1


def _base6(v: float) -> int:
    """7 桁目を付ける土台 (小数 6 桁までの値を整数にしたもの、符号つき)。

    基本は 10 進の表記を 6 桁で切り捨てる (四捨五入しない)。6 桁目までの数字が元のまま残るので、
    toFixed(k) (k<=5) の丸めが元と変わらない (地図の JS は toFixed(4)/(5) を突き合わせの鍵に使う)。
    例外は 138.24695 のように表記が丸め位置のちょうど半分で終わる値。浮動小数の中身が半分より
    わずかに下 (138.2469499999…) なら元は切り下がるので、土台を 1 つ下げて透かしの値も半分の下に置く。
    """
    v = float(v)
    s = repr(v)
    if "e" in s or "E" in s:
        s = f"{v:.10f}".rstrip("0")
    neg = s.startswith("-")
    ip, _, fp = s.lstrip("-").partition(".")
    q = int(ip) * 1_000_000 + int((fp + "000000")[:6])
    if 2 <= len(fp) <= 6 and fp.endswith("5") and q > 0 and abs(Decimal(v)) < Decimal(s.lstrip("-")):
        q -= 1
    return -q if neg else q


def _compose(q: int, d: int) -> float:
    """6 桁までの値 q (符号つき) の後ろに 7 桁目 d を付けた数。"""
    a = abs(q) * 10 + d
    return (-a if q < 0 else a) / 1e7


def stamp_point(key: bytes, lon: float, lat: float, cache: dict) -> tuple[float, float]:
    hit = cache.get((lon, lat))
    if hit is None:
        qlon, qlat = _base6(lon), _base6(lat)
        hit = (_compose(qlon, _digit(key, qlon, qlat, "x")), _compose(qlat, _digit(key, qlon, qlat, "y")))
        cache[(lon, lat)] = hit
    return hit


def _is_pos(x) -> bool:
    return (isinstance(x, list) and len(x) >= 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in x[:2]))


def _map_coords(coords, fn):
    if _is_pos(coords):
        lon, lat = fn(float(coords[0]), float(coords[1]))
        return [lon, lat, *coords[2:]]
    if isinstance(coords, list):
        return [_map_coords(c, fn) for c in coords]
    return coords


def _map_geometry(geom, fn):
    if not isinstance(geom, dict):
        return geom
    if geom.get("type") == "GeometryCollection":
        geom["geometries"] = [_map_geometry(g, fn) for g in geom.get("geometries", [])]
    elif "coordinates" in geom:
        geom["coordinates"] = _map_coords(geom["coordinates"], fn)
    return geom


def stamp_collection(fc: dict, key: bytes | None, cache: dict) -> bool:
    """FeatureCollection を書き換える。すでに stamp 済みなら False。"""
    if isinstance(fc.get("attribution"), dict) and fc["attribution"].get("stamp"):
        return False
    if key is not None:
        fn = lambda lon, lat: stamp_point(key, lon, lat, cache)  # noqa: E731
        for ft in fc.get("features", []):
            if isinstance(ft, dict):
                _map_geometry(ft.get("geometry"), fn)
    attribution = dict(ATTRIBUTION, stamp=STAMP_VERSION if key is not None else STAMP_VERSION + "-nokey")
    # attribution を先頭に置く (ファイルを開いた人の目に入るように)
    rest = {k: v for k, v in fc.items() if k != "attribution"}
    fc.clear()
    fc["type"] = rest.pop("type", "FeatureCollection")
    fc["attribution"] = attribution
    fc.update(rest)
    return True


def cmd_stamp(args) -> int:
    key = load_key()
    if key is None:
        print("[stamp] 鍵が無いので出典の表示だけ入れます (座標の印は飛ばす)")
    files = sorted({p for root in args.paths for p in
                    (glob.glob(os.path.join(root, "**", "*.geojson"), recursive=True)
                     if os.path.isdir(root) else [root])})
    cache: dict = {}
    n_done = n_skip = 0
    before = after = 0
    for f in files:
        raw = Path(f).read_bytes()
        try:
            fc = json.loads(raw)
        except ValueError as e:
            print(f"[stamp] 読めないので飛ばす: {f} ({e})")
            n_skip += 1
            continue
        if not (isinstance(fc, dict) and fc.get("type") == "FeatureCollection"):
            n_skip += 1
            continue
        if not stamp_collection(fc, key, cache):
            n_skip += 1
            continue
        out = json.dumps(fc, ensure_ascii=False, separators=(",", ":")).encode()
        if not args.dry_run:
            Path(f).write_bytes(out)
        before += len(raw)
        after += len(out)
        n_done += 1
    print(f"[stamp] {n_done} files stamped, {n_skip} skipped, "
          f"{before / 1e6:.1f} MB -> {after / 1e6:.1f} MB, {len(cache):,} distinct points"
          f"{' (dry run)' if args.dry_run else ''}")
    return 0


# ---------------------------------------------------------------- verify

_FALLBACK_RE = re.compile(r"(?:北海道|東北|東京|中部|北陸|関西|中国|四国|九州|沖縄)送電線_\d+")


def ajg_generated_names() -> dict[str, set[str]]:
    """AJG が自分で付けた (OSM には無い) 名前を正典 data/ から集める。"""
    out = {"丁目の変電所名 (住所から)": set(), "両端の変電所名をつないだ線名": set()}
    for f in glob.glob(str(REPO / "data" / "*_substations.geojson")):
        for ft in json.load(open(f, encoding="utf-8"))["features"]:
            p = ft.get("properties") or {}
            n = p.get("name")
            # 「1丁目変電所」のような短い名前は他所の文字列にも紛れるので、町名の付いたものだけ
            if (n and p.get("_name_source") == "geocoded" and "丁目" in n
                    and not re.match(r"^[0-9０-９一二三四五六七八九十]+丁目", n)):
                out["丁目の変電所名 (住所から)"].add(n)
    for f in glob.glob(str(REPO / "data" / "*_lines.geojson")):
        for ft in json.load(open(f, encoding="utf-8"))["features"]:
            p = ft.get("properties") or {}
            n = p.get("name")
            if (n and p.get("_name_source") == "endpoints" and "~" in n
                    and not re.match(r"^[0-9０-９一二三四五六七八九十]+丁目", n)):
                out["両端の変電所名をつないだ線名"].add(n)
    return out


def keyed_match(text: str, key: bytes) -> tuple[int, int]:
    """[lon, lat] の組で 7 桁の座標を拾い、7 桁目が鍵の数字と合う数を数える。"""
    pair = re.compile(r"\[\s*(-?\d{1,3}\.\d{7})\s*,\s*(-?\d{1,3}\.\d{7})(?!\d)")
    def split(s: str) -> tuple[int, int]:
        a = int(s.lstrip("-").replace(".", ""))  # 7 桁目までの絶対値
        q = a // 10
        return (-q if s.startswith("-") else q), a % 10

    n = hit = 0
    for m in pair.finditer(text):
        (qlon, dlon), (qlat, dlat) = split(m.group(1)), split(m.group(2))
        n += 2
        hit += (dlon == _digit(key, qlon, qlat, "x")) + (dlat == _digit(key, qlon, qlat, "y"))
    return n, hit


def cmd_verify(args) -> int:
    names = ajg_generated_names()
    key = load_key()
    for f in args.files:
        text = Path(f).read_text(encoding="utf-8", errors="replace")
        print(f"== {f}")
        print("  A. AJG が付けた名前 (鍵なし)")
        total = 0
        for label, ns in names.items():
            found = sorted(n for n in ns if n in text)
            total += len(found)
            print(f"     {label}: {len(found)} / {len(ns)}" + (f"  例: {', '.join(found[:3])}" if found else ""))
        fb = sorted(set(_FALLBACK_RE.findall(text)))
        total += len(fb)
        print(f"     地域名_番号の線名: {len(fb)}" + (f"  例: {', '.join(fb[:3])}" if fb else ""))
        print(f"     → {'AJG 由来の名前を含む' if total else '見つからない'}")
        if key is None:
            print("  B. 鍵の印: 鍵が無いので飛ばす")
            continue
        n, hit = keyed_match(text, key)
        if n == 0:
            print("  B. 鍵の印: 小数 7 桁の座標が無い (丸められているか、別のデータ)")
            continue
        p0 = 1 / 9
        rate = hit / n
        z = (hit - n * p0) / math.sqrt(n * p0 * (1 - p0))
        verdict = "AJG の印と一致" if (rate > 0.5 and z > 10) else ("偶然の範囲" if z < 4 else "一部一致 (要確認)")
        print(f"  B. 鍵の印: {hit:,} / {n:,} 桁が一致 ({rate:.1%}、偶然なら約 11%、z={z:.1f}) → {verdict}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("stamp", help="公開する GeoJSON に出典と透かしを入れる")
    s.add_argument("paths", nargs="+", help="フォルダ (中の *.geojson 全部) かファイル")
    s.add_argument("--dry-run", action="store_true", help="書き込まずに件数と大きさだけ出す")
    s.set_defaults(fn=cmd_stamp)
    v = sub.add_parser("verify", help="他所のデータに AJG 由来の印があるか調べる")
    v.add_argument("files", nargs="+")
    v.set_defaults(fn=cmd_verify)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
