#!/usr/bin/env python3
"""Load All-Japan-Grid into your own tools in ~1 line (Pillar 2: interop).

The point of publishing standards-based exchange formats (CIM/CGMES, MATPOWER)
is that *anyone* can pull a region of Japan's grid into a standard solver
without touching this repo's internals. This script demonstrates the two
verified pandapower import paths against the **published artifacts** and runs a
power flow to prove they load and solve.

Run it (no arguments needed → okinawa)::

    PYTHONPATH=. python3 examples/import_quickstart.py
    PYTHONPATH=. python3 examples/import_quickstart.py kansai

──────────────────────────────────────────────────────────────────────────────
One-line recipes (the whole point — copy/paste into your own code)
──────────────────────────────────────────────────────────────────────────────

pandapower ← CGMES / CIM Level 2  (profiles tracked in ``dist/cim_level2/``):

    from pandapower.converter.cim.cim2pp.from_cim import from_cim
    net = from_cim(file_list=[
        "dist/cim_level2/okinawa_L2_EQ.xml",
        "dist/cim_level2/okinawa_L2_TP.xml",
        "dist/cim_level2/okinawa_L2_SSH.xml",
        "dist/cim_level2/okinawa_L2_SV.xml",
        "dist/cim_level2/okinawa_L2_GL.xml",
        "dist/cim_level2/AllJapan_EQ_BD.xml",   # boundary set
        "dist/cim_level2/AllJapan_TP_BD.xml",
    ])

pandapower ← MATPOWER ``.mat``  (full sets via GitHub Releases):

    from pandapower.converter.matpower.from_mpc import from_mpc
    net = from_mpc("okinawa.mat")

MATLAB / Octave MATPOWER  (needs MATPOWER installed) — *not auto-tested here*:

    mpc = loadcase('okinawa.mat');   results = runpf(mpc);

PyPSA  (``pip install pypsa``) via the PYPOWER bridge — *documented, see
docs/INTEROP.md; not auto-tested here because pypsa is an optional dep*:

    import pypsa
    from pandapower.converter.pypower.to_ppc import to_ppc
    n = pypsa.Network(); n.import_from_pypower_ppc(to_ppc(net))

See docs/INTEROP.md for the full matrix (PSS/E, PowerFactory, etc.) and the
honest caveat: this is a *geographic topology with synthetic electrical
parameters* — trends and merit order are meaningful; individual-asset operation
is not. See docs/VISION.md §2.
"""
from __future__ import annotations

import os
import sys
import tempfile
import warnings

warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CIM_DIR = os.path.join(ROOT, "dist", "cim_level2")
MAT_DIR = os.path.join(ROOT, "output", "matpower_alljapan")
CGMES_PROFILES = ("EQ", "TP", "SSH", "SV", "GL")


def load_region_from_cgmes(region: str = "okinawa", cim_dir: str = CIM_DIR):
    """Load a region's published CIM Level 2 profile set into pandapower.

    Uses the boundary set (``AllJapan_{EQ,TP}_BD.xml``) the way a CGMES
    consumer is expected to. Returns a pandapower net.
    """
    from pandapower.converter.cim.cim2pp.from_cim import from_cim

    files = [os.path.join(cim_dir, f"{region}_L2_{p}.xml")
             for p in CGMES_PROFILES]
    files += [os.path.join(cim_dir, "AllJapan_EQ_BD.xml"),
              os.path.join(cim_dir, "AllJapan_TP_BD.xml")]
    missing = [f for f in files if not os.path.exists(f)]
    if missing:
        raise FileNotFoundError(
            f"missing CIM profiles for {region}: {missing[:2]}… — "
            f"regenerate with `ajgrid cim --regions {region}` "
            f"or download a Release.")
    return from_cim(file_list=files)


def load_region_from_matpower(region: str = "okinawa", mat_path: str | None = None):
    """Load a region's MATPOWER ``.mat`` into pandapower.

    Prefers the published ``output/matpower_alljapan/<region>.mat``; if it is
    not present (that directory is a build output, not tracked), the case is
    generated on the fly from the snapped topology into a temp file.
    """
    from pandapower.converter.matpower.from_mpc import from_mpc

    if mat_path is None:
        published = os.path.join(MAT_DIR, f"{region}.mat")
        mat_path = published if os.path.exists(published) \
            else _generate_matpower(region)
    return from_mpc(mat_path)


def _generate_matpower(region: str) -> str:
    """Build a MATPOWER case from the snapped topology → temp .mat path."""
    from examples.build_snapped_topology import build_network_snapped
    from src.matpower.exporter import build_matpower_case, save_case_to_matfile

    net = build_network_snapped(region)
    if net is None or not net.has_elements:
        raise RuntimeError(f"no network data for {region}")
    case = build_matpower_case(network=net)
    out = os.path.join(tempfile.gettempdir(), f"ajgrid_{region}.mat")
    return save_case_to_matfile(case, out)


def _summarise(net) -> str:
    n_gen = len(net.gen) + len(net.ext_grid)
    return (f"{len(net.bus)} buses, {len(net.line)} lines, "
            f"{len(net.trafo)} trafos, {n_gen} gens (incl. {len(net.ext_grid)} slack)")


def _run_pf(net) -> str:
    import pandapower as pp
    try:
        pp.runpp(net, max_iteration=100)
        return (f"AC converged, vmin={net.res_bus.vm_pu.min():.3f} / "
                f"vmax={net.res_bus.vm_pu.max():.3f} pu")
    except Exception as exc:  # noqa: BLE001
        try:
            pp.rundcpp(net)
            return f"AC failed ({type(exc).__name__}); DC OK"
        except Exception as exc2:  # noqa: BLE001
            return f"power flow failed: {type(exc2).__name__}"


def main(argv=None) -> int:
    region = (argv or sys.argv[1:] or ["okinawa"])[0]
    print(f"\n=== Loading '{region}' into pandapower from published formats ===\n")

    print("[1] CIM / CGMES Level 2  (dist/cim_level2/, standards-based)")
    try:
        net_cim = load_region_from_cgmes(region)
        print(f"    from_cim → {_summarise(net_cim)}")
        print(f"    {_run_pf(net_cim)}")
    except Exception as exc:  # noqa: BLE001
        print(f"    SKIP: {type(exc).__name__}: {str(exc)[:100]}")

    print("\n[2] MATPOWER .mat  (output/matpower_alljapan/ or generated)")
    try:
        net_mat = load_region_from_matpower(region)
        print(f"    from_mpc → {_summarise(net_mat)}")
        print(f"    {_run_pf(net_mat)}")
    except Exception as exc:  # noqa: BLE001
        print(f"    SKIP: {type(exc).__name__}: {str(exc)[:100]}")

    print("\nThat's the whole interop story: standard files → standard solver, "
          "no repo internals.\nSee docs/INTEROP.md for PyPSA / MATLAB / PSS-E.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
