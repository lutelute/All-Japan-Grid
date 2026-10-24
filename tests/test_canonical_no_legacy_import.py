"""正典の書き出しと潮流が旧系譜を読み込まないこと(2026-10-24・B1)。

配布ケースの書き出し(export_net)と正典の潮流(full_from_built)は、座標を読む関数・
無効電力の補償・介入#37 のために、退役した scripts/export_powerflow_pages.py と
src/powerflow/pipeline.py(build_and_solve・reconstruction)を読み込んでいた。
src/converter/matpower_case.py と src/powerflow/compensation.py に移したので、
旧系譜のモジュールが sys.modules に入らないことを別のプロセスで確かめる。
旧来の import 先から同じ関数が使えることも確かめる。
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LEGACY = ("scripts.export_powerflow_pages", "scripts.run_national_powerflow",
          "src.powerflow.pipeline", "src.powerflow.snapped_topology",
          "src.powerflow.legacy_build", "src.reconstruction", "examples.build_snapped_topology")


def _loaded_after(stmt: str) -> list[str]:
    code = (f"import sys\n{stmt}\n"
            f"print('\\n'.join(k for k in sys.modules if k.startswith({LEGACY!r})))")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                         text=True, check=True, env={"PYTHONPATH": str(ROOT), "PATH": ""})
    return [x for x in out.stdout.split("\n") if x]


def test_canonical_export_and_pf_do_not_load_legacy():
    assert _loaded_after("import src.converter.matpower_case, src.powerflow.compensation, "
                         "src.powerflow.full_from_built") == []


def test_old_import_paths_still_work():
    from scripts.export_national_matpower import export_net
    from scripts.export_powerflow_pages import _parse_bus_coords
    from src.converter.matpower_case import export_net as e2, parse_bus_coords
    from src.powerflow.compensation import add_provisional_infeed as a2, add_reactive_compensation as r2
    from src.powerflow.pipeline import add_provisional_infeed, add_reactive_compensation
    assert export_net is e2 and _parse_bus_coords is parse_bus_coords
    assert add_reactive_compensation is r2 and add_provisional_infeed is a2
