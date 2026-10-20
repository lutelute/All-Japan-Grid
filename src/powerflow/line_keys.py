"""計算ネットワークの線に、作り直しても変わりにくい鍵を付ける。

潮流マップ(docs/flow_map.html)の線は、これまで「書き出したときの並び順」でしか値と
対応づけられなかった。線名は一意でない(leadin など)ので、モデルを作り直すと並びがずれ、
日別断面(export_day_flows.py)は「線順不一致」で島ごと出力されなくなっていた
(2026-08-27〜10-03、北海道・東・西が欠落)。

鍵 = 両端バスの座標(小数 5 桁)・電圧・向き(from→to)・同じ両端の平行線の通し番号。
潮流の符号は from→to なので、向きは鍵に含める(向きが入れ替わった線は別の線として扱う)。
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter

import pandas as pd


def _coord(geo) -> tuple[float, float] | None:
    try:
        lon, lat = json.loads(geo)["coordinates"][:2]
        return round(float(lat), 5), round(float(lon), 5)
    except Exception:  # noqa: BLE001  座標の無いバス(合成バス等)
        return None


def line_keys(net) -> pd.Series:
    """net.line の各行(index 順)に鍵を返す。座標の無い線は空文字。"""
    geo = {b: _coord(g) for b, g in net.bus["geo"].items()} if "geo" in net.bus else {}
    vn = net.bus["vn_kv"].to_dict()
    seen: Counter = Counter()
    out = {}
    for li, fb, tb in zip(net.line.index, net.line.from_bus, net.line.to_bus):
        a, b = geo.get(int(fb)), geo.get(int(tb))
        if a is None or b is None:
            out[li] = ""
            continue
        base = f"{a[0]:.5f},{a[1]:.5f}|{b[0]:.5f},{b[1]:.5f}|{float(vn.get(int(fb), 0)):g}"
        seen[base] += 1
        out[li] = hashlib.sha1(f"{base}#{seen[base]}".encode()).hexdigest()[:10]
    return pd.Series(out, dtype=object)


def keys_signature(keys) -> str:
    """鍵の並び全体の署名。基準データと日別断面が同じ線構成かを照合する。"""
    return hashlib.sha1("\n".join(keys).encode()).hexdigest()[:12]
