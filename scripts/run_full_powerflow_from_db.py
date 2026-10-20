#!/usr/bin/env python3
"""全規模の潮流計算(正典の 4 つの同期島)の入口 — 実体は src/powerflow/full_from_built.py.

2026-10-21 に網づくりの核(build_island_net ほか)を src/ へ移した(docs/reports/project_structure_2026-10-21.md
の E1)。このパスで import すると同じモジュールそのものが返る(sys.modules を差し替える)ので、定数の
差し替え(monkeypatch)も実体に効く。ファイルのパスで読み込む(importlib の spec_from_file_location)と
実体の写しになるので、写しが要るときは src/powerflow/full_from_built.py のパスを読む。

    PYTHONPATH=. python3 scripts/run_full_powerflow_from_db.py [--islands ...]   # = ajgrid pf
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.powerflow.full_from_built as _impl  # noqa: E402

if __name__ == "__main__":
    _impl.main()
else:
    # パスで読み込まれたとき(spec_from_file_location)は返るのがこの殻なので、実体の名前を写しておく
    globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__")})
    sys.modules[__name__] = _impl
