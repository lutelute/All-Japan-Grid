# All-Japan-Grid 再現DAG(Snakemake) — 2026-09-02
#
# 目的: 国際ベンチマーク(docs/reports/international_benchmark_2026-06-27.md)で
# 自認した劣位「raw OSM→成果物のワンコマンドDAG無し」の解消。PyPSA-Eur が
# Snakemake+lock で持つ再現性の軸に、本リポジトリの既存パイプライン
# (scripts/regenerate_all.py の STEPS)をファイル依存として宣言し直したもの。
#
# 設計方針:
#   - 各ルールは既存スクリプトを shell で呼ぶだけ(ロジックの再実装はしない)。
#     正典の生成順序・冪等性の議論は regenerate_all.py のコメントが正。
#   - 介入適用群(#28/#29/#34/#35/#36 等)は docs/data/built/all.json を
#     **in-place で変異**させる。ファイル時刻では依存が表現できないため、
#     .stamps/ 配下のセンチネルで順序を固定する(Snakemake の標準手法)。
#   - 重い段(run_full_powerflow / matpower / cim)は既定の `all` に含むが、
#     軽い再現は `snakemake light` で editor+static のみ。
#
# 使い方(uv 環境・依存追加なしで走る):
#   uv run --with snakemake snakemake -n            # dry-run(実行計画の確認)
#   uv run --with snakemake snakemake --cores 1     # 全再生成(重い・数十分)
#   uv run --with snakemake snakemake light --cores 1
#   uv run --with snakemake snakemake --dag | dot -Tsvg > docs/figures/dag.svg
#
# 既知の限界(正直に):
#   - raw OSM の再取得(Overpass)は DAG に含めない。data/osm_raw/ の断面
#     (2026-06-15、scripts/record_osm_snapshot.py が刻印)を基底とする。
#     再取得は明示操作(取得スクリプト)であり、黙って上書きしない設計。
#   - in-place 変異段はセンチネル依存のため、`--forcerun` 単体では中間状態に
#     ならないよう、変異チェーンの途中だけの再実行は非推奨(all.json を
#     build_editor_data から作り直すのが正)。

PY = "PYTHONPATH=. python3"
STAMP = ".stamps"

# ── 基底(コミット済み入力) ─────────────────────────────────────
REGIONS = ["hokkaido", "tohoku", "tokyo", "chubu", "hokuriku",
           "kansai", "chugoku", "shikoku", "kyushu", "okinawa"]
BASE_GEOJSON = expand("data/{r}_lines.geojson", r=REGIONS)


rule all:
    input:
        f"{STAMP}/capacity_sources.done",
        "docs/editor.html",
        "docs/data/MODEL_VERSION.json",
        f"{STAMP}/matpower.done",
        f"{STAMP}/cim.done",


rule light:
    input:
        f"{STAMP}/capacity_sources.done",
        "docs/editor.html",


# ── ① built(all.json)の構築と介入チェーン ────────────────────────
rule build_editor_data:
    input: BASE_GEOJSON
    output: touch(f"{STAMP}/01_build_editor_data.done")
    shell: f"{PY} scripts/build_editor_data.py"


rule apply_disclosure_v1:
    input: f"{STAMP}/01_build_editor_data.done"
    output: touch(f"{STAMP}/02_disclosure_v1.done")
    shell: f"{PY} scripts/apply_tepco_connections.py --write"


rule apply_disclosure_v2:
    input: f"{STAMP}/02_disclosure_v1.done"
    output: touch(f"{STAMP}/03_disclosure_v2.done")
    shell: f"{PY} scripts/apply_disclosure_v2.py --from-worklist --write"


rule route_disclosure:
    input: f"{STAMP}/03_disclosure_v2.done"
    output: touch(f"{STAMP}/04_route_disclosure.done")
    shell: f"{PY} scripts/route_disclosure_edges.py --write"


rule fragment_recovery:
    input: f"{STAMP}/04_route_disclosure.done"
    output: touch(f"{STAMP}/05_fragment_recovery.done")
    shell: f"{PY} scripts/hunt_fragment_osm_bridges.py --write"


rule fragment_recovery_chains:
    input: f"{STAMP}/05_fragment_recovery.done"
    output: touch(f"{STAMP}/06_fragment_chains.done")
    shell: f"{PY} scripts/hunt_fragment_osm_chains.py --write"


rule node_hygiene:
    input: f"{STAMP}/06_fragment_chains.done"
    output: touch(f"{STAMP}/07_node_hygiene.done")
    shell: f"{PY} scripts/apply_node_hygiene.py --write"


rule satellite_connections:
    input: f"{STAMP}/07_node_hygiene.done"
    output: touch(f"{STAMP}/08_satellite.done")
    shell: f"{PY} scripts/apply_satellite_connections.py --write"


rule substation_properties:
    input: f"{STAMP}/08_satellite.done"
    output: touch(f"{STAMP}/09_sub_props.done")
    shell: f"{PY} scripts/build_substation_properties.py --attach"


# built 完成の目印(以降の輸出はここに依存)
rule built_ready:
    input: f"{STAMP}/09_sub_props.done"
    output: touch(f"{STAMP}/built_ready.done")


# ── ② built からの輸出群 ───────────────────────────────────────
rule subsld_pages:
    input: f"{STAMP}/built_ready.done"
    output: touch(f"{STAMP}/subsld_pages.done")
    shell:
        f"{PY} scripts/export_subsld_pages.py && "
        f"{PY} scripts/export_subsld_ways.py && "
        f"{PY} scripts/export_loops.py"


rule map_tiers:
    input: f"{STAMP}/built_ready.done"
    output: touch(f"{STAMP}/map_tiers.done")
    shell: f"{PY} scripts/export_map_tiers_from_built.py"


rule gen_sld:
    input: f"{STAMP}/built_ready.done"
    output: touch(f"{STAMP}/gen_sld.done")
    shell: f"{PY} scripts/gen_sld_from_built.py"


rule full_powerflow:
    input: f"{STAMP}/built_ready.done"
    output: touch(f"{STAMP}/full_powerflow.done")
    shell: f"{PY} scripts/run_full_powerflow_from_db.py --max-ac-buses 20000"


rule national_overview:
    input: f"{STAMP}/full_powerflow.done"
    output: touch(f"{STAMP}/national_overview.done")
    shell: f"{PY} scripts/gen_national_overview_from_full.py"


rule matpower:
    input: f"{STAMP}/full_powerflow.done"
    output: touch(f"{STAMP}/matpower.done")
    shell: f"{PY} scripts/export_national_matpower.py"


rule cim:
    input: f"{STAMP}/built_ready.done"
    output: touch(f"{STAMP}/cim.done")
    shell: f"{PY} scripts/export_cim.py"


# ── ③ サイトと出典再適用(順序が正典: capacity は static の後) ──────
rule static_site:
    input:
        f"{STAMP}/map_tiers.done",
        f"{STAMP}/gen_sld.done",
        f"{STAMP}/subsld_pages.done",
    output: touch(f"{STAMP}/static_site.done")
    shell: f"{PY} scripts/build_static_site.py"


rule capacity_sources:
    input: f"{STAMP}/static_site.done"
    output: touch(f"{STAMP}/capacity_sources.done")
    shell: f"{PY} scripts/apply_capacity_sources.py"


rule pages_editor:
    input: f"{STAMP}/capacity_sources.done"
    output: "docs/editor.html"
    shell: f"{PY} scripts/build_pages_editor.py --out docs/editor.html"


# ── ④ 版刻印(git HEAD + OSM断面時刻) ─────────────────────────────
rule version_stamp:
    input:
        f"{STAMP}/capacity_sources.done",
        "docs/editor.html",
    output: "docs/data/MODEL_VERSION.json"
    shell:
        f"{PY} scripts/regenerate_all.py --stamp-only && "
        f"{PY} scripts/record_osm_snapshot.py"
