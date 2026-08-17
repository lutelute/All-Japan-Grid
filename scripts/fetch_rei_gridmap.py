#!/usr/bin/env python3
"""自然エネルギー財団「洋上風力開発エリア&送電線マップ」のArcGIS層を取得する.

出典: 公益財団法人 自然エネルギー財団 洋上風力開発エリア&送電線マップ(β版)
  https://www.renewable-ei.org/statistics/offshoremap/
  背後の FeatureServer (services6.arcgis.com/sHqbS37vOcgCANsO) を匿名クエリ。

ライセンス注意(external_grid_resources_2026-08-17.md):
  REI自体は出典表記で利用可だが、線路属性の原典は各一般送配電事業者の
  空容量情報(All-Rights-Reserved)。**取得物は data/external(untracked)に留め、
  生値はリポジトリに再配布しない**(k_line.csv と同じ扱い)。

礼儀的レート(0.4s/リクエスト)・resultOffsetページング・リトライ付き。
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "external" / "rei_gridmap"
BASE = "https://services6.arcgis.com/sHqbS37vOcgCANsO/arcgis/rest/services"
UA = {"User-Agent": "Mozilla/5.0 (research; contact: lutebass@gmail.com)"}
SLEEP = 0.4
PAGE = 1000

PREFIXES = ("PowerLine", "Powerline", "Substation", "PwrPlnt")


def get_json(url: str, tries: int = 3) -> dict:
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as ex:  # noqa: BLE001
            if i == tries - 1:
                raise
            print(f"  retry {i+1}: {ex}", flush=True)
            time.sleep(2.0 * (i + 1))
    return {}


def fetch_layer(service: str, layer_id: int) -> dict | None:
    feats = []
    offset = 0
    while True:
        q = urllib.parse.urlencode({
            "where": "1=1", "outFields": "*", "f": "geojson",
            "resultOffset": offset, "resultRecordCount": PAGE,
            "outSR": 4326,
        })
        url = f"{BASE}/{service}/FeatureServer/{layer_id}/query?{q}"
        d = get_json(url)
        page = d.get("features", [])
        feats.extend(page)
        time.sleep(SLEEP)
        if len(page) < PAGE:
            break
        offset += PAGE
    if not feats:
        return None
    return {"type": "FeatureCollection", "features": feats}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    svcs = get_json(f"{BASE}?f=json").get("services", [])
    targets = [s["name"] for s in svcs
               if s["type"] == "FeatureServer"
               and s["name"].startswith(PREFIXES)]
    print(f"対象サービス {len(targets)}/{len(svcs)}", flush=True)
    manifest = {"fetched": time.strftime("%Y-%m-%d %H:%M:%S"),
                "source": "REI offshoremap ArcGIS (services6.arcgis.com/sHqbS37vOcgCANsO)",
                "license_note": "原典=各社空容量情報(All-Rights-Reserved)。untracked・再配布禁止",
                "layers": {}}
    n_feat_total = 0
    for name in sorted(targets):
        info = get_json(f"{BASE}/{name}/FeatureServer?f=json")
        time.sleep(SLEEP)
        layers = info.get("layers", [])
        for ly in layers:
            lid = ly["id"]
            key = f"{name}__{lid}"
            path = OUT / f"{key}.geojson"
            if path.exists():
                fc = json.loads(path.read_text())
                manifest["layers"][key] = {"n": len(fc.get("features", [])),
                                           "name": ly.get("name"), "cached": True}
                n_feat_total += len(fc.get("features", []))
                print(f"skip(既存) {key} n={len(fc.get('features', []))}", flush=True)
                continue
            try:
                fc = fetch_layer(name, lid)
            except Exception as ex:  # noqa: BLE001
                print(f"! {key} 取得失敗: {ex}", flush=True)
                manifest["layers"][key] = {"error": str(ex), "name": ly.get("name")}
                continue
            if fc is None:
                manifest["layers"][key] = {"n": 0, "name": ly.get("name")}
                print(f"  {key} n=0", flush=True)
                continue
            path.write_text(json.dumps(fc, ensure_ascii=False,
                                       separators=(",", ":")))
            n = len(fc["features"])
            n_feat_total += n
            manifest["layers"][key] = {"n": n, "name": ly.get("name")}
            print(f"  {key} n={n}", flush=True)
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1))
    print(f"done: {len(manifest['layers'])}レイヤ / {n_feat_total:,}フィーチャ -> {OUT}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
