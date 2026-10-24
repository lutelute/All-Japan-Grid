"""scripts/ 直下の全スクリプト索引を作る(scripts/README.md の cog から呼ぶ)。

    cog -I . -r scripts/README.md

各ファイルの冒頭の説明(docstring かコメントの 1 行目)を用途別に並べる。Snakefile・CI・tests・src・
launchd から名前で参照されているもの(場所を動かすと壊れるもの)には 🔒 を付ける。

「状態」の欄(2026-10-24・全体構造の台帳 B2・C2・C5): 現役 / 旧系譜 / 退役 / 比較用 / 記録 / 起動不可。
現役・旧系譜・起動不可は機械で決め、退役・比較用・記録は scripts/script_status.yaml に理由つきで書く。
空欄は、どの入口からも呼ばれていない手で使う道具(未分類)。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import yaml

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


# 正典の入口(ここから呼ばれていれば「現役」)。ダッシュボードのカードは別に見る(旧系譜の道具にも
# 「旧系譜」と注記したカードがあるため、カードから呼ばれているだけでは現役としない)
ENTRY_FILES = ("scripts/regenerate_all.py", "scripts/realtime_cycle.sh", "scripts/realtime_publish.sh",
               "Snakefile", ".github/workflows/*.yml", "src/cli.py")
CARD_FILE = "docs/data/tools_catalog.json"
# 旧系譜の網を組む関数(tests/test_pages_dashboard.py の LEGACY_IMPORT と同じ判定)
LEGACY_IMPORT = re.compile(
    r"^\s*(?:from\s+\S+\s+)?import\s+.*\b(build_network_snapped|build_and_solve|ReconstructionConfig)\b", re.M)
STATUS_FILE = SCRIPTS / "script_status.yaml"


def entry_text() -> str:
    parts = []
    for pat in ENTRY_FILES:
        for f in ROOT.glob(pat):
            parts.append(f.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def card_text() -> str:
    f = ROOT / CARD_FILE
    return f.read_text(encoding="utf-8", errors="replace") if f.exists() else ""


def curated_status() -> dict[str, tuple[str, str]]:
    """{ファイル名: (状態, 理由)} — scripts/script_status.yaml。"""
    if not STATUS_FILE.exists():
        return {}
    d = yaml.safe_load(STATUS_FILE.read_text(encoding="utf-8")) or {}
    return {name: (label, why) for label, items in d.items() for name, why in (items or {}).items()}


def broken_imports(p: Path) -> list[str]:
    """import 先がリポジトリに無い scripts.* / src.* のモジュール。"""
    if p.suffix != ".py":
        return []
    try:
        tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return ["(構文エラー)"]
    mods = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.append(node.module)
        elif isinstance(node, ast.Import):
            mods += [a.name for a in node.names]
    out = []
    for m in mods:
        if m.split(".")[0] not in ("scripts", "src"):
            continue
        base = ROOT / Path(*m.split("."))
        if not (base.with_suffix(".py").exists() or (base / "__init__.py").exists() or base.is_dir()):
            out.append(m)
    return out


def status_of(p: Path, entries: str, curated: dict, cards: str = "") -> tuple[str, str]:
    """(状態, 理由)。起動不可 > 台帳(退役・比較用・記録) > 現役 > 旧系譜 > 空欄。"""
    bad = broken_imports(p)
    if bad:
        return "起動不可", "import 先が無い: " + ", ".join(sorted(set(bad))[:2])
    if p.name in curated:
        return curated[p.name]
    text = p.read_text(encoding="utf-8", errors="replace")
    legacy = bool(LEGACY_IMPORT.search(text))
    named = re.compile(rf"\b{re.escape(p.stem)}\b")
    if named.search(entries):
        return ("現役", "旧系譜の網も組める") if legacy else ("現役", "")
    on_card = bool(cards and named.search(cards))
    if legacy:
        return "旧系譜", "ダッシュボードのカードあり(旧系譜と注記)" if on_card else "旧系譜の網を組む関数を import"
    if on_card:
        return "現役", "ダッシュボードのカード"
    return "", ""


def group_of(name: str) -> str:
    for g, prefixes in GROUPS:
        if name.startswith(prefixes):
            return g
    return OTHER


def table() -> str:
    refs = referenced_names()
    entries, curated, cards = entry_text(), curated_status(), card_text()
    files = sorted(p for p in SCRIPTS.iterdir() if p.is_file() and p.suffix in EXTS and p.name != "__init__.py")
    by: dict[str, list[Path]] = {}
    for p in files:
        by.setdefault(group_of(p.name), []).append(p)
    st = {p.name: status_of(p, entries, curated, cards) for p in files}
    from collections import Counter
    cnt = Counter(s for s, _ in st.values())
    order = ["現役", "旧系譜", "比較用", "退役", "記録", "起動不可", ""]
    tally = "・".join(f"{s or '未分類'} {cnt[s]}" for s in order if cnt.get(s))
    out = [f"直下 {len(files)} 本(サブフォルダは上の各節)。🔒 = Snakefile・CI・tests・src・launchd が名前で参照(動かすなら参照元も直す)。\n",
           f"状態: {tally}。現役 = 正典の手順・毎時の処理・Snakefile・CI・CLI、または(旧系譜でない)ダッシュボードのカードが呼ぶ / "
           "旧系譜 = 旧系譜の網を組む関数を import / 退役・比較用・記録 = `scripts/script_status.yaml` / "
           "起動不可 = import 先が無い / 未分類 = 手で使う道具。どれも消さない。\n"]
    for g in [g for g, _ in GROUPS] + [OTHER]:
        if g not in by:
            continue
        out.append(f"\n<details><summary><b>{g}</b>({len(by[g])} 本)</summary>\n\n| スクリプト | 状態 | 説明 |\n|---|---|---|")
        for p in by[g]:
            lock = " 🔒" if re.search(rf"\b{re.escape(p.stem)}\b", refs) else ""
            s, why = st[p.name]
            cell = (f"{s}<br><sub>{why}</sub>" if why else s) if s else ""
            out.append(f"| `{p.name}`{lock} | {cell} | {summary(p)} |")
        out.append("\n</details>")
    return "\n".join(out) + "\n"
