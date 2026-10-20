"""scripts/ 直下の全スクリプト索引を作る(scripts/README.md の cog から呼ぶ)。

    cog -I . -r scripts/README.md

各ファイルの冒頭の説明(docstring かコメントの 1 行目)を用途別に並べる。Snakefile・CI・tests・src・
launchd から名前で参照されているもの(場所を動かすと壊れるもの)には 🔒 を付ける。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
EXTS = {".py", ".sh", ".mjs", ".m"}

# 接頭辞 → 用途。上から順に当てる
GROUPS = [
    ("取得 / fetch", ("fetch_", "download_", "osm")),
    ("エンリッチ・適用 / enrich & apply", ("enrich_", "apply_", "complement_", "fix_", "migrate_", "merge_", "record_")),
    ("監査・検証 / audit & validate", ("audit_", "validate_", "verify_", "check_", "cross_validate", "compare_", "match_", "reconcile")),
    ("構築・解析 / build & solve", ("build_", "gen_", "run_", "solve_", "calc_", "compute_", "analyze_", "hunt_", "route_", "rebuild_")),
    ("UC / unit commitment", ("uc_",)),
    ("書き出し・公開 / export & publish", ("export_", "make_", "publish_", "slim_", "realtime_", "regenerate_")),
    ("診断・調査 / diagnostics", ("diag_", "diagnose_", "probe_", "screen_", "trial_", "investigate_")),
    ("図・動画 / figures", ("plot_", "fig_", "draw_", "render_", "animate_", "capture_")),
]
OTHER = "その他 / other"


def summary(p: Path) -> str:
    text = p.read_text(encoding="utf-8", errors="replace")
    line = ""
    if p.suffix == ".py":
        try:
            doc = ast.get_docstring(ast.parse(text))
        except SyntaxError:
            doc = None
        if doc:
            line = doc.strip().splitlines()[0]
    if not line:
        for raw in text.splitlines()[:15]:
            s = raw.strip()
            if s.startswith(("#!", "#!/")) or not s:
                continue
            m = re.match(r"^(?:#|//|%|\*|/\*\*?)\s*(.+)", s)
            if m and len(m.group(1)) > 3:
                line = m.group(1)
                break
    line = line.replace("|", "\\|").strip()
    return line[:110] + ("…" if len(line) > 110 else "")


def referenced_names() -> str:
    """場所を動かすと壊れる参照元(Snakefile・CI・tests・src・launchd)の本文をまとめて返す。"""
    parts = []
    for pat in ("Snakefile", ".github/workflows/*.yml", "tests/**/*.py", "src/**/*.py", "scripts/*.plist"):
        for f in ROOT.glob(pat):
            parts.append(f.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def group_of(name: str) -> str:
    for g, prefixes in GROUPS:
        if name.startswith(prefixes):
            return g
    return OTHER


def table() -> str:
    refs = referenced_names()
    files = sorted(p for p in SCRIPTS.iterdir() if p.is_file() and p.suffix in EXTS and p.name != "__init__.py")
    by: dict[str, list[Path]] = {}
    for p in files:
        by.setdefault(group_of(p.name), []).append(p)
    out = [f"直下 {len(files)} 本(サブフォルダは上の各節)。🔒 = Snakefile・CI・tests・src・launchd が名前で参照(動かすなら参照元も直す)。\n"]
    for g in [g for g, _ in GROUPS] + [OTHER]:
        if g not in by:
            continue
        out.append(f"\n<details><summary><b>{g}</b>({len(by[g])} 本)</summary>\n\n| スクリプト | 説明 |\n|---|---|")
        for p in by[g]:
            lock = " 🔒" if re.search(rf"\b{re.escape(p.stem)}\b", refs) else ""
            out.append(f"| `{p.name}`{lock} | {summary(p)} |")
        out.append("\n</details>")
    return "\n".join(out) + "\n"
