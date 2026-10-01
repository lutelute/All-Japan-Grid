"""radial.ReducedCascadeModel: ローカル系統を常時開路にしても平常時のつながりを壊さず、ローカル枝に潮流を流さない。"""
import numpy as np
import pytest
from nankai.grid import GridCase
from nankai.cascade import CascadeModel
from nankai.radial import ReducedCascadeModel


@pytest.mark.parametrize("island", ["east"])
def test_reduced_keeps_energized_load_and_zero_local_flows(island):
    c = GridCase.load(island)
    cm, rm = CascadeModel(c), ReducedCascadeModel(c)
    n = c.n_bus; ones = np.ones(n, bool); allb = np.ones(len(c.branch), bool)
    g = c.gen; gp = g.p_mw.to_numpy(); gb = g.b.to_numpy()

    def energized_load(model):
        lab = model._components(ones, allb); nc = lab.max() + 1
        G = np.bincount(lab[gb], weights=gp, minlength=nc)
        return float(model.load[G[lab] > 0].sum()), lab

    Lm, _ = energized_load(cm); Lr, lab = energized_load(rm)
    assert Lr >= 0.995 * Lm                       # 常時開路にしても平常時に受電する負荷はほぼ変わらない(切替送電で戻す)
    nc = lab.max() + 1
    L = np.bincount(lab, weights=rm.load, minlength=nc); G = np.bincount(lab[gb], weights=gp, minlength=nc)
    sc = np.where(G > 0, L / np.maximum(G, 1e-9), 0)
    pinj = np.bincount(gb, weights=gp * sc[lab[gb]], minlength=n) - rm.load
    fl = rm._dc_flows(lab, ones, allb, pinj, np.zeros(nc, bool))
    assert np.all(fl[rm.lv] == 0.0) and np.all(fl[rm.feed] == 0.0)   # 潮流は主幹系統の枝だけ
    assert np.abs(fl[rm.hv]).max() > 0


def test_restore_ties_reenergizes_dead_section():
    c = GridCase.load("east")
    rm = ReducedCascadeModel(c)
    ties = np.where(rm.op.open_mask)[0]
    assert len(ties) > 0
    k = ties[0]; a, b = rm.f[k], rm.t[k]
    bus_alive = np.ones(c.n_bus, bool); br = ~rm.op.open_mask
    en = np.ones(c.n_bus, bool); en[b] = False
    closed, _ = rm.op.restore_ties(bus_alive, br, en)
    assert k in closed
