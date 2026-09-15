"""UFLS の表示用の変換(計算は変えない)。

動的カスケード(dynamics.FreqCore)は UFLS を「島の中のすべての母線から同じ割合ずつ需要を削る」形で解く。
周波数と遮断量(MW)はそれで合うが、実際の UFLS は指定された変電所の配電線を丸ごと切るので、
地図で「どこも少しずつ暗い」と見えるのは実際と違う。

ここでは遮断量を保ったまま、優先順位の高い母線から丸ごと消灯と表示する母線を選ぶ。
どの変電所が UFLS の対象かは非公表なので、優先順位は仮定(母線 id のハッシュで固定し、前提を切り替えても同じ母線が対象になる)。
遮断量が増えると、前の選択に母線を足していく(入れ子になるので、段が進んでも灯りがちらつかない)。
"""
from __future__ import annotations
import zlib
import numpy as np


def bus_priority(bus_ids) -> np.ndarray:
    """母線 id → 0..1 の固定の優先順位(小さいほど先に消灯)。"""
    return np.array([zlib.crc32(str(b).encode("utf-8")) / 2 ** 32 for b in bus_ids], float)


def ufls_off_mask(energized, island, load, priority, order=None) -> np.ndarray:
    """UFLS で丸ごと消灯と表示する母線(bool)。

    energized: 母線ごとの受電の割合(0..1、= 1 − UFLS の遮断の割合。受電していない母線は 0)
    island:    母線ごとの島の番号
    load:      母線ごとの需要 [MW]
    島ごとに、受電中の母線の遮断 MW の合計に届くまで、優先順位の順に母線の需要を足して消灯にする。
    足す前の累計が遮断量に届いていない母線までを消灯にするので、超えるのは最後の 1 母線ぶんまで。
    """
    e = np.asarray(energized, float); island = np.asarray(island); load = np.asarray(load, float)
    live = (e > 1e-3) & (load > 0)
    off = np.zeros(len(e), bool)
    if not live.any():
        return off
    shed_mw = np.where(live, (1.0 - e) * load, 0.0)
    if order is None:
        order = np.argsort(priority, kind="stable")
    ord_live = order[live[order]]
    isl_o = island[ord_live]
    for k in np.unique(isl_o):
        idx = ord_live[isl_o == k]
        target = shed_mw[idx].sum()
        if target <= 1e-6:
            continue
        before = np.cumsum(load[idx]) - load[idx]
        n = int(np.searchsorted(before, target, side="left"))
        off[idx[:n]] = True
    return off
