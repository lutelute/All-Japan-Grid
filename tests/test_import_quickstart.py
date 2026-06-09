"""Guards the interop recipes documented in docs/INTEROP.md.

The whole value of publishing CIM/CGMES + MATPOWER is that an outside user can
load a region in ~1 line. These tests pin (a) the exact pandapower import paths
the docs tell people to use — if pandapower renames them, the docs are wrong and
this fails — and (b) that the tracked Level-2 profile set actually loads into a
solvable pandapower network.
"""

import os

import pytest

pp = pytest.importorskip("pandapower")

from examples.import_quickstart import (  # noqa: E402
    CIM_DIR,
    load_region_from_cgmes,
)

_HAS_OKINAWA_CIM = os.path.exists(os.path.join(CIM_DIR, "okinawa_L2_EQ.xml"))


def test_documented_import_paths_exist():
    """The one-line recipes in docs/INTEROP.md must stay importable."""
    from pandapower.converter.cim.cim2pp.from_cim import from_cim  # noqa: F401
    from pandapower.converter.matpower.from_mpc import from_mpc  # noqa: F401
    from pandapower.converter.pypower.to_ppc import to_ppc  # noqa: F401


@pytest.mark.skipif(not _HAS_OKINAWA_CIM, reason="okinawa L2 profiles absent")
def test_load_okinawa_from_cgmes_is_solvable():
    """from_cim on the tracked profile set yields a runnable network."""
    net = load_region_from_cgmes("okinawa")
    assert len(net.bus) > 0
    assert len(net.line) > 0
    assert len(net.ext_grid) >= 1, "CGMES import must carry a slack"
    pp.runpp(net, max_iteration=100)
    assert net.converged
    # Synthetic-but-physical: voltages stay in a sane band.
    assert 0.5 < net.res_bus.vm_pu.min() <= net.res_bus.vm_pu.max() < 1.5
