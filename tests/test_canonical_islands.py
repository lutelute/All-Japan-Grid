"""正典の 4 つの同期島を全規模で AC 潮流に解く(週次・AJGRID_SLOW_TESTS=1).

2026-10-21 まで、正典(docs/data/built/all.json と build_island_net)を全規模の AC で解く pytest は
1 本も無かった。週次で測っていたのは旧系譜(地域別のスナップ済みの網)の sweep だけで、それも
6 月から赤のままだった(tests/test_topology_metrics.py・docs/reports/project_structure_2026-10-21.md の A7)。

ここでは配布ケース(dist/matpower_national・scripts/export_matpower_canonical.py)と同じ網を、同じ
素朴な NR(既定の許容誤差・緩めない)で解く。解けない島は配布物と同じく、降下の大きい 66 kV の木から
畳む(介入#52)。CI には地点需要の CSV(data/external・git の外)が無いので point_demand=False で組む
(10-21 実測: 配布値との差は損失 0.05pt・vm 0.003pu 以内、バス数と畳む数は同じ)。

記録は 2026-10-21 の正典。正典を変えたら、測り直して理由つきで更新する。
- 2026-10-21 更新: 正典を再生成の手順の出力に置き換えた(docs/reports/regenerate_reproducibility_2026-10-21.md)。
  東 6,253→6,245 バス・西 7,979→7,976 バス、北海道の vm 上限 1.0218→1.0036。損失はほぼ同じ
"""
import json
import os
from pathlib import Path

import pytest

pytest.importorskip("pandapower")

ROOT = Path(__file__).resolve().parents[1]

pytestmark = [
    pytest.mark.slow,
    pytest.mark.canonical,
    pytest.mark.skipif(not os.environ.get("AJGRID_SLOW_TESTS"),
                       reason="正典 4 島の全規模 AC(週次・AJGRID_SLOW_TESTS=1)"),
]

# 島: (バス, 線, 変圧器, 畳んだバス, vm の最小, vm の最大, 損失 %)
RECORD = {
    "okinawa": (100, 96, 19, 0, 0.9746, 1.0038, 1.88),
    "hokkaido": (831, 858, 69, 0, 0.8604, 1.0036, 2.63),
    "east": (6245, 6443, 676, 0, 0.8578, 1.0229, 2.96),
    "west": (7976, 8110, 996, 6, 0.7755, 1.0365, 2.16),
}


@pytest.fixture(scope="module")
def built():
    return json.loads((ROOT / "docs" / "data" / "built" / "all.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("island", list(RECORD))
def test_canonical_island_solves_full_ac(island, built):
    from scripts.export_matpower_canonical import build_canonical_net, try_ac
    from scripts.run_full_powerflow_from_db import ISLAND_FREQ
    from src.powerflow.reduce_antenna import fold_until

    net0 = build_canonical_net(island, built["nodes"], built["edges"], ISLAND_FREQ[island],
                               point_demand=False)
    net, ok, how = try_ac(net0)
    folded = 0
    if not ok:
        fnet, red = fold_until(net0, lambda n: try_ac(n)[1])
        if fnet is not None:
            net, ok, how = try_ac(fnet)
            folded = red["n_removed"]
    n_bus, n_line, n_trafo, n_fold, vm_lo, vm_hi, loss_pct = RECORD[island]
    assert ok and how in ("dc", "flat"), f"{island}: 素朴な NR で解けない({how})"
    got = (len(net.bus), len(net.line), len(net.trafo), folded)
    assert got == (n_bus, n_line, n_trafo, n_fold), f"{island}: 網の規模が記録と違う {got}(正典を変えたなら記録を更新)"
    vm = net.res_bus.vm_pu.dropna()
    assert vm.min() >= vm_lo - 0.02 and vm.max() <= vm_hi + 0.02, (island, vm.min(), vm.max())
    loss = net.res_line.pl_mw.sum() + net.res_trafo.pl_mw.sum()
    assert abs(100 * loss / net.res_load.p_mw.sum() - loss_pct) <= 0.3, (island, 100 * loss / net.res_load.p_mw.sum())
