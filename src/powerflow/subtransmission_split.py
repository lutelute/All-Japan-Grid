"""介入#56: 154 kV 網の分割運用の推定 — 降圧点ごとに分け、境の線を常時開放とみなす.

背景(moshimo の what-if・`docs/reports/attach_split_2026-10-29.md`):
正典は開閉器の状態を持たず、154 kV(100〜160 kV)の網を全部つないだまま解いている。実系統は
短絡電流を遮断器の定格(多くは 50〜63 kA)に収めるため、154 kV 以下を上位の変電所ごとに分けて
運用する(常時開放の連絡線)。全部つないだままだと、154 kV 級の短絡電流は東で 63 kA 超が 214 母線・
最大 139 kA(昇圧変圧器 0.14 pu 込み)になり、現実の桁から外れる。

開閉器の状態は公表されていないので、**推定**で分ける:

    1. 降圧点 = 275 kV 以上 → 154 kV 級の変圧器の二次側の母線
    2. 154 kV 級の各母線を、線の x(Ω)を重みにした多始点の最短路で、電気的に最も近い降圧点へ割り当てる
    3. 違う降圧点の受け持ちどうしをつなぐ線を in_service=False にする(どの降圧点からも届かない母線の線は触らない)

各受け持ちは自分の降圧点(上位へつながる変圧器)を含むので、分けても網は切れない(新しい孤立片は出ない)。
同じ変電所に二次側の母線が 2 つあり短い線で結ばれている場合も、その線を開く(母線連絡の常時開放と同じ扱い)。

**開閉器の実データではない**。どの線が開いているかは推定で、個々の線の開閉を引用してはいけない。
帳簿(戻り値)に開いた線を全件出す。無効化 = 呼ばない(モデル既定は `SPLIT_154_DEFAULT`=OFF)。
"""
from __future__ import annotations

from typing import Dict, List

import numpy as np

KV_LO, KV_HI = 100.0, 160.0      # 154 kV 級(110・132・154 kV)
SRC_HV_MIN = 250.0               # 降圧点の一次側(275・500 kV)


def split_subtransmission(net, kv_lo: float = KV_LO, kv_hi: float = KV_HI,
                          src_hv_min: float = SRC_HV_MIN, apply: bool = True) -> Dict:
    """154 kV 級の網を降圧点ごとに分け、境の線を常時開放とみなす。

    apply=False は開く線を数えるだけ(網は変えない)。戻り値は帳簿:
    ``{"n_opened", "n_sources", "n_buses", "n_unowned", "kv_band", "opened": [...]}``。
    ``opened`` の各行は線の index・名前・電圧・両端のバス名・両端の受け持ちの降圧点のバス名。
    """
    import scipy.sparse as sp
    from scipy.sparse.csgraph import dijkstra

    led = {"kv_band": [kv_lo, kv_hi], "src_hv_min": src_hv_min,
           "n_opened": 0, "n_sources": 0, "n_buses": 0, "n_unowned": 0, "opened": []}
    vn = net.bus["vn_kv"].astype(float)
    band = net.bus.index[(vn >= kv_lo) & (vn <= kv_hi) & net.bus["in_service"].astype(bool)]
    pos = {int(b): i for i, b in enumerate(band)}
    n = len(pos)
    led["n_buses"] = n
    if n == 0:
        return led
    src = set()
    for _, t in net.trafo.iterrows():
        if not bool(t["in_service"]):
            continue
        hv, lv = int(t["hv_bus"]), int(t["lv_bus"])
        if float(net.bus.at[hv, "vn_kv"]) >= src_hv_min and lv in pos:
            src.add(pos[lv])
    led["n_sources"] = len(src)
    if not src:
        return led
    L = net.line[net.line["in_service"].astype(bool)]
    fb = L["from_bus"].map(pos)
    tb = L["to_bus"].map(pos)
    m = fb.notna() & tb.notna()
    L = L[m]
    fb = fb[m].astype(int).to_numpy()
    tb = tb[m].astype(int).to_numpy()
    par = L["parallel"].clip(lower=1) if "parallel" in L.columns else 1
    x = (L["x_ohm_per_km"] * L["length_km"] / par).to_numpy(dtype=float)
    x = np.maximum(np.nan_to_num(x, nan=1e-4), 1e-4)
    G = sp.coo_matrix((np.r_[x, x], (np.r_[fb, tb], np.r_[tb, fb])), shape=(n, n)).tocsr()
    srcs = np.array(sorted(src))
    dist, _pred, owner = dijkstra(G, directed=False, indices=srcs, min_only=True,
                                  return_predecessors=True)
    own = np.where(np.isfinite(dist), owner, -1)
    led["n_unowned"] = int((own < 0).sum())
    cut = (own[fb] >= 0) & (own[tb] >= 0) & (own[fb] != own[tb])
    idx = L.index[cut]
    inv = {i: b for b, i in pos.items()}

    def _nm(b):
        return str(net.bus.at[int(b), "name"])

    rows: List[Dict] = []
    for li, a, b in zip(idx, fb[cut], tb[cut]):
        rows.append({"line": int(li), "name": str(net.line.at[li, "name"]),
                     "kv": round(float(net.bus.at[inv[int(a)], "vn_kv"]), 1),
                     "from_bus": _nm(inv[int(a)]), "to_bus": _nm(inv[int(b)]),
                     "from_source": _nm(inv[int(own[a])]), "to_source": _nm(inv[int(own[b])])})
    if apply and len(idx):
        net.line.loc[idx, "in_service"] = False
    led["n_opened"] = len(rows)
    led["opened"] = rows
    return led


def describe(led: Dict) -> str:
    """実行ログの 1 行(帳簿の要約)。"""
    if not led:
        return "介入#56 split-154: 無効"
    return (f"介入#56 split-154(推定): {led['kv_band'][0]:.0f}〜{led['kv_band'][1]:.0f} kV の "
            f"{led['n_buses']} 母線を降圧点 {led['n_sources']} か所に割り当て、境の線 "
            f"{led['n_opened']} 本を常時開放とみなした(届かない母線 {led['n_unowned']})")
