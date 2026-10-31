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
- 2026-10-21 更新: 介入#23(供用していない線を止める)を既定 ON。東 7 本・西 10 本を止め、東の損失 2.96→2.99%
- 2026-10-26 更新: 介入#54(issue #99・出力の目標を届く負荷に・予備率なし・損失を発電機へ配る)を既定 ON。
  主成分のスラックが余りを吸わなくなり(西 −6,251→±1 MW)、損失は 西 2.16→1.95%・東 2.99→3.06%・
  北海道 2.63→2.67%・沖縄 1.88→1.95%。西のバス 7,976→7,977・変圧器 996→997 はこの変更の前からの差
  (10-25 の #53 で敷地の結び先が変わった。網の規模は配分では変わらない)
- 2026-10-28 更新: 配布ケースの発電機の繋ぎ先を島別の既定(介入#41・西と北海道は capkv)にそろえた。
  それまでここだけ cap を書き込んでいた。網の規模は同じ。損失は 西 1.95→2.05%・北海道 2.67→2.50%
- 2026-10-28 更新: 介入#55(公表の接続で電圧が分かる大型機 21 機を台帳の電圧へ)を既定 ON。
  網の規模・vm は同じ。損失は 西 2.05→1.98%・北海道 2.50→2.48%
- 2026-10-29 更新: 介入#55 の追補(構内の点・碧南)と #44 の手動の 2 行(幸田碧南線・碧南岡崎線の回線数 1→2)。
  網の規模・vm は同じ。損失は 西 1.98→1.96%
- 2026-10-30 更新: 介入#55 の追補(台帳の全機を地図・空中写真で見直し、西名古屋火力を 154 kV の構内へ・
  敦賀・坂出・京極を構内の点へ)。網の規模は同じ。損失は 西 1.96→1.88%・北海道 2.48→2.50%
- 2026-10-29 更新: #55 の台帳に東の 3 機(姉崎・横浜・勿来)。東の繋ぎ先の規則は cap のまま(capkv は根拠が足りず見送り)。
  網の規模は同じ。東の vm の最小 0.8569→0.8566・損失 3.06→2.83%(枝のきれいな checkout で測った)。川崎の行は、
  入れると東が素朴 NR で解けなくなったので台帳に入れていない(docs/reports/attach_split_2026-10-29.md)
- 2026-10-29 更新: 出典付き容量の当て間違いを外した D 層(川崎火力の JR東日本の地物・敦賀原子力の 0.04 MW の地物)。
  東の vm の最小 0.8566→0.8559・損失 2.83→2.87%、西の vm の最小 0.7757→0.7759
- 2026-10-31 更新: 上の 2 行と、main の介入#55 の追補（2026-10-30）を合わせた網で測り直した。東 vm の最小 0.8559・損失 2.87%、西 vm の最小 0.7759・損失 1.88%、北海道 損失 2.50%
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
    "okinawa": (100, 96, 19, 0, 0.9746, 1.0038, 1.95),
    "hokkaido": (831, 858, 69, 0, 0.8604, 1.0035, 2.50),
    "east": (6245, 6443, 676, 0, 0.8559, 1.0229, 2.87),
    "west": (7977, 8110, 997, 6, 0.7759, 1.0379, 1.88),
}


@pytest.fixture(scope="module")
def built():
    return json.loads((ROOT / "docs" / "data" / "built" / "all.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("island", list(RECORD))
def test_canonical_island_solves_full_ac(island, built):
    from scripts.export_matpower_canonical import build_canonical_net, solve_canonical
    from scripts.run_full_powerflow_from_db import ISLAND_FREQ

    net0 = build_canonical_net(island, built["nodes"], built["edges"], ISLAND_FREQ[island],
                               point_demand=False)
    net, ok, how, red, spread = solve_canonical(net0)
    folded = red["n_removed"] if red else 0
    n_bus, n_line, n_trafo, n_fold, vm_lo, vm_hi, loss_pct = RECORD[island]
    assert ok and how in ("dc", "flat"), f"{island}: 素朴な NR で解けない({how})"
    got = (len(net.bus), len(net.line), len(net.trafo), folded)
    assert got == (n_bus, n_line, n_trafo, n_fold), f"{island}: 網の規模が記録と違う {got}(正典を変えたなら記録を更新)"
    vm = net.res_bus.vm_pu.dropna()
    assert vm.min() >= vm_lo - 0.02 and vm.max() <= vm_hi + 0.02, (island, vm.min(), vm.max())
    loss = net.res_line.pl_mw.sum() + net.res_trafo.pl_mw.sum()
    assert abs(100 * loss / net.res_load.p_mw.sum() - loss_pct) <= 0.3, (island, 100 * loss / net.res_load.p_mw.sum())
    # 介入#54(issue #99): 最大の成分のスラックに余り(架空の負荷)を残さない
    assert spread and spread["applied"] and abs(spread["slack_after_mw"]) < 50, (island, spread)
