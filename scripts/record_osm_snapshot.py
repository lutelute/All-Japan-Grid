#!/usr/bin/env python3
"""OSM断面時刻(osm3s)の記録 — 国際ベンチマーク劣位「OSM時刻未記録」の解消。

data/osm_raw/*.json は Overpass API の生レスポンスで、`osm3s.timestamp_osm_base`
に「そのレスポンスが写した OSM データベースの断面時刻」が入っている。本スクリプトは
在庫全ファイルを走査して断面時刻の範囲(最古〜最新)と地域別内訳を集計し、

  - docs/data/MODEL_VERSION.json の "osm_snapshot" キー
  - datapackage.json の "osm_snapshot" キー(Frictionless カスタムプロパティ)

に刻む。既存キーは保持(マージ)。ネットワークアクセスなし・冪等。

正直な限界(重要):
  - ここで拾えるのはリポジトリに残っている生レスポンスの断面時刻であって、
    基底 data/*_lines.geojson 等が抽出された瞬間の時刻そのものではない。
    geojson への変換時に osm3s は落ちており、過去の抽出時刻は復元できない。
  - したがって "coverage" に「何ファイル中何ファイルから時刻が取れたか」を明記する。
  - 次回以降の OSM 再取得では、取得スクリプトが生レスポンスを data/osm_raw/ に
    保存してから変換する運用(既にそうなっている)を守れば、本スクリプトの再実行だけで
    断面時刻が更新される。

Usage:
  python scripts/record_osm_snapshot.py            # 走査して両ファイルに刻む
  python scripts/record_osm_snapshot.py --check    # 走査結果の表示のみ(書き込みなし)
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_GLOBS = ["data/osm_raw/*.json"]
MODEL_VERSION = os.path.join(ROOT, "docs", "data", "MODEL_VERSION.json")
DATAPACKAGE = os.path.join(ROOT, "datapackage.json")


def scan() -> dict:
    stamps: list[tuple[str, str]] = []      # (relpath, iso timestamp)
    unknown: list[str] = []
    # Overpass レスポンスは osm3s がファイル先頭(elements より前)に来るため、
    # 先頭 8KB の正規表現読みで足りる。全 json.load は数百MB級ファイルで
    # 数分かかるため行わない(見つからなければ unknown に正直に計上)。
    ts_re = re.compile(r'"timestamp_osm_base"\s*:\s*"([^"]+)"')
    for pat in RAW_GLOBS:
        for path in sorted(glob.glob(os.path.join(ROOT, pat))):
            rel = os.path.relpath(path, ROOT)
            try:
                with open(path, encoding="utf-8", errors="ignore") as f:
                    head = f.read(8192)
                m = ts_re.search(head)
                if m:
                    stamps.append((rel, m.group(1)))
                else:
                    unknown.append(rel)
            except Exception:               # noqa: BLE001 — 集計目的・個別スキップ
                unknown.append(rel)
    by_region: dict[str, list[str]] = {}
    for rel, ts in stamps:
        m = re.search(r"power_nodes_([a-z_]+?)_t\d+\.json$", rel)
        key = m.group(1) if m else os.path.basename(rel)
        by_region.setdefault(key, []).append(ts)
    return {
        "oldest": min(ts for _r, ts in stamps) if stamps else None,
        "newest": max(ts for _r, ts in stamps) if stamps else None,
        "n_files_with_timestamp": len(stamps),
        "n_files_without": len(unknown),
        "coverage_note": (
            "在庫のOverpass生レスポンス(data/osm_raw/)から読めた断面時刻の範囲。"
            "基底geojsonの抽出時刻そのものではない(変換時にosm3sが落ちるため)。"
            "時刻の取れないファイルは n_files_without に計上。"
        ),
        "by_region": {k: {"oldest": min(v), "newest": max(v), "n": len(v)}
                      for k, v in sorted(by_region.items())},
        "files_without_timestamp": unknown[:20],
    }


def merge_write(path: str, key: str, value: dict) -> None:
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    d[key] = value
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="表示のみ(書き込みなし)")
    args = ap.parse_args(argv)
    snap = scan()
    print(f"OSM断面時刻: {snap['oldest']} 〜 {snap['newest']} "
          f"({snap['n_files_with_timestamp']}ファイル / "
          f"時刻なし{snap['n_files_without']})")
    for k, v in snap["by_region"].items():
        print(f"  {k:14s} {v['oldest']} 〜 {v['newest']} (n={v['n']})")
    if args.check:
        return 0
    # by_region は MODEL_VERSION のみ(datapackage は要約に留める)
    merge_write(MODEL_VERSION, "osm_snapshot", snap)
    merge_write(DATAPACKAGE, "osm_snapshot",
                {k: snap[k] for k in ("oldest", "newest",
                                      "n_files_with_timestamp",
                                      "n_files_without", "coverage_note")})
    print(f"-> {os.path.relpath(MODEL_VERSION, ROOT)} / "
          f"{os.path.relpath(DATAPACKAGE, ROOT)} に刻印")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
