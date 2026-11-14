#!/usr/bin/env python3
"""試し(正典は変えない): 相馬双葉幹線の 2026-06 の接続変更を網に入れたら、福島の線路の潮流は観測に近づくか。

OCCTO 運用容量検討会 2026 年度 第 2 回 資料 3 の 12 枚目(変更前)・13 枚目(変更後〜第二連系線の運開前)の系統図:
変更後は、相馬双葉幹線が南いわき開閉所に入らず、福島山幹線につながって新いわき開閉所へ行く。
正典(OSM 由来)は変更前の形(南相馬変電所~南いわき開閉所線 500 kV)。その枝の南いわきの端を新いわきへ移す。
scripts/export_day_flows.py をそのまま呼び、網を組む関数だけ差し替える。
"""
import copy
import sys

import src.powerflow.full_from_built as impl

S_IWAKI = (37.3811, 140.8056)    # 南いわき開閉所
N_IWAKI = (37.1422, 140.7223)    # 新いわき開閉所
_orig = impl.build_island_net


def _is(pt, ref):
    return abs(pt[0] - ref[0]) < 2e-4 and abs(pt[1] - ref[1]) < 2e-4


def patched(island, nodes, edges, *a, **k):
    if island == "east":
        new, n = [], 0
        for e in edges:
            if "南相馬" in str(e.get("name") or "") and "南いわき" in str(e.get("name") or "") and float(e.get("kv") or 0) == 500:
                e = copy.deepcopy(e)
                if _is(e["a"], S_IWAKI):
                    e["a"] = list(N_IWAKI)
                if _is(e["b"], S_IWAKI):
                    e["b"] = list(N_IWAKI)
                e["path"] = [e["a"], e["b"]]
                n += 1
            new.append(e)
        print(f"  [試し] 相馬双葉幹線(南相馬~南いわき)の南いわきの端を新いわきへ: {n} 本")
        edges = new
    return _orig(island, nodes, edges, *a, **k)


impl.build_island_net = patched
import scripts.export_day_flows as edf  # noqa: E402

sys.exit(edf.main())
