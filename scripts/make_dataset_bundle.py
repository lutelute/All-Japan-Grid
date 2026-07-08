#!/usr/bin/env python3
"""All-Japan-Grid — 配布用データセットバンドル (.zip) を生成する。

外部の利用者が「DL して回す」ための自己完結セットを 1 つの zip にまとめます。
中身は datapackage.json (Frictionless 記述子) のリソース + MATPOWER 配布ケース +
正典 built モデル + チュートリアル (dataset/) で、SHA256 の MANIFEST も同梱します。

プロファイル:
  core  MATPOWER 潮流 (dataset/01) と UC (dataset/02) が回る最小セット
        (datapackage / dataset / dist/matpower_national / docs/data/built / 主要文書)
  full  core に Ybus 一式・主要 GeoJSON を追加した拡張セット

使い方::

    python scripts/make_dataset_bundle.py                 # core
    python scripts/make_dataset_bundle.py --profile full
    python scripts/make_dataset_bundle.py --profile core --out dist/bundle

出力:
  dist/bundle/all-japan-grid-dataset-v<VERSION>-<profile>.zip
  dist/bundle/all-japan-grid-dataset-v<VERSION>-<profile>.MANIFEST.sha256

公開手順 (実行はオーナー) は dataset/BUNDLE.md を参照。
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# バンドルから常に除外するパターン
EXCLUDE = ("*.DS_Store", "__pycache__", "*.pyc", "uc_result.xlsx", "uc_result.png",
           "*_res_bus.csv")

# 明示的に含めるパス (ファイル or ディレクトリ)。datapackage.json のリソースは別途自動追加。
CORE_PATHS = [
    "datapackage.json",
    "README.md", "LICENSE", "NOTICE", "CITATION.cff",
    "DATA_DICTIONARY.md", "DATA_CATALOG.md",
    "pyproject.toml", "requirements.txt", "VERSION",
    "src",                          # UC ソルバ・モデル (バンドル単体で UC を回すため)
    "config",                       # UC 既定値 (uc_config.yaml) / シナリオ (fy2023.yaml)
    "dataset",                      # チュートリアル (01_matpower / 02_uc_from_excel)
    "dist/matpower_national",       # runpf 用ケース (.mat + CSV) + meta.json
    "docs/data/built",              # 正典 built モデル (all.json ほか)
]
FULL_EXTRA = [
    "dist/ybus",                    # 数値 Ybus (.mat/.npz/CSV + README)
    "docs/data/lines_all.geojson",
    "docs/data/substations.geojson",
    "docs/data/subs_all.geojson",
    "docs/data/plants_all.geojson",
]


def _read_version() -> str:
    vf = ROOT / "VERSION"
    return vf.read_text(encoding="utf-8").strip() if vf.exists() else "0.0.0"


def _excluded(rel: str) -> bool:
    return any(fnmatch.fnmatch(Path(rel).name, pat) or pat.strip("*") in rel for pat in EXCLUDE)


def _datapackage_paths() -> list[str]:
    """datapackage.json の resources[].path を拾う (存在するもののみ)。"""
    import json

    dp = ROOT / "datapackage.json"
    if not dp.exists():
        return []
    data = json.loads(dp.read_text(encoding="utf-8"))
    out = []
    for res in data.get("resources", []):
        p = res.get("path")
        if p and (ROOT / p).exists():
            out.append(p)
    return out


def _collect(paths: list[str]) -> list[tuple[Path, str]]:
    """(絶対パス, zip 内相対パス) のリストへ展開。ディレクトリは再帰。"""
    seen: dict[str, Path] = {}
    for rel in paths:
        abs_p = ROOT / rel
        if not abs_p.exists():
            print(f"  [skip] not found: {rel}", file=sys.stderr)
            continue
        if abs_p.is_dir():
            for f in sorted(abs_p.rglob("*")):
                if f.is_file():
                    r = f.relative_to(ROOT).as_posix()
                    if not _excluded(r):
                        seen[r] = f
        else:
            r = abs_p.relative_to(ROOT).as_posix()
            if not _excluded(r):
                seen[r] = abs_p
    return sorted(seen.items(), key=lambda kv: kv[0])  # (rel, abs) sorted by rel


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(profile: str, out_dir: Path) -> int:
    version = _read_version()
    paths = list(CORE_PATHS)
    if profile == "full":
        paths += FULL_EXTRA
    # datapackage 記述のリソースも取り込む (重複は _collect が排除)
    paths += _datapackage_paths()

    items = _collect(paths)  # [(rel, abs), ...]
    if not items:
        sys.exit("[ERROR] バンドル対象が 1 つもありません。ルートで実行していますか?")

    prefix = f"all-japan-grid-dataset-v{version}"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"{prefix}-{profile}.zip"
    manifest_path = out_dir / f"{prefix}-{profile}.MANIFEST.sha256"

    # zip 内はトップに <prefix>-<profile>/ を付けて展開時に散らからないようにする
    top = f"{prefix}-{profile}"
    total_bytes = 0
    lines = []
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for rel, abs_p in items:
            digest = _sha256(abs_p)
            size = abs_p.stat().st_size
            total_bytes += size
            lines.append(f"{digest}  {rel}")
            zf.write(abs_p, arcname=f"{top}/{rel}")
        # MANIFEST も zip 内に含める
        manifest_text = (
            f"# All-Japan-Grid dataset bundle v{version} ({profile})\n"
            f"# {len(items)} files, {total_bytes/1e6:.1f} MB uncompressed\n"
            f"# sha256  path\n" + "\n".join(lines) + "\n"
        )
        zf.writestr(f"{top}/MANIFEST.sha256", manifest_text)

    manifest_path.write_text(manifest_text, encoding="utf-8")
    zsize = zip_path.stat().st_size

    print(f"profile: {profile}")
    print(f"files:   {len(items)}  ({total_bytes/1e6:.1f} MB uncompressed)")
    print(f"zip:     {zip_path}  ({zsize/1e6:.1f} MB)")
    print(f"manifest:{manifest_path}")
    print(f"sha256(zip): {_sha256(zip_path)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", choices=("core", "full"), default="core", help="バンドル内容 (既定 core)")
    ap.add_argument("--out", default=str(ROOT / "dist" / "bundle"), help="出力ディレクトリ")
    args = ap.parse_args()
    return build(args.profile, Path(args.out))


if __name__ == "__main__":
    raise SystemExit(main())
