# Changelog

All notable changes to All-Japan-Grid are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.6.0] - 2026-07-10

Tagged in git as `v1.6.0`. Theme: **the corrected canon becomes the default** —
interventions #19/#20/#21 flipped to default ON (owner-approved), numeric Ybus canon
v5.0.0, canonical power-flow regenerated, the compensation factor anchored to primary
sources, and the 07-07〜09 diagnosis campaign consolidated into a reusable methodology.

### Changed
- **Interventions #19 (per-prefecture demand) / #20 (reactive compensation) / #21 (bbox
  dedup) are now DEFAULT ON** across `run_full_powerflow_from_db.py`, `uc_to_pf_built.py`
  and `gen_ybus_numeric.py` (`build_island_net(dedup_nodes=True)`). `--no-pref-demand` /
  `--no-reactive-comp` / `--no-dedup-nodes` reproduce the legacy behaviour exactly.
  Decision package: 4-island before/after probes (no solution regression; fragmentation
  improves everywhere — west 2,531 → 544 components), 44 gates PASS (2 regression pins
  intentionally updated), Ybus fingerprint lineage —
  `docs/reports/default_on_decision_2026-07-10.md`. East losses rise on the probe
  snapshot (+31 %): that is the *correction* (bbox-duplicated boundary lines had halved
  impedances before).
- **Numeric Ybus canon v5.0.0** (`dist/ybus/`): first regeneration since territory
  re-attribution (07-07) + dedup; buses hokkaido 836 → 802 / east 6,205 → 6,002 /
  west 10,193 → 8,204 / okinawa 99 → 98; dedup instrumentation stamped into `meta.json`;
  machine-precision gates PASS on all islands.
- **Canonical `docs/data/powerflow_full` regenerated** under the new defaults
  (east 6,002-bus AC; west honest DC by design).
- Intervention #20's factor 0.6 upgraded from "median setting" to **anchored on primary
  sources**: Shikoku EGC 2024 measurements convert to ≈0.8 today / ≈0.05 in the 1990s,
  so 0.6 sits on the conservative side (sending-end pf ≈0.991). Raising to 0.8 is a
  future re-sweep-gated change. Research with URLs + verbatim quotes:
  `docs/reports/reactive_comp_provenance_2026-07-10.md`.

### Added
- **Methodology consolidation** (`docs/reports/osm_grid_pitfalls_methodology_2026-07-10.md`):
  four pitfall classes of OSM-derived grid models, five diagnostic methods
  (variant probes, process isolation + raw JSON, served_frac guard, DC-angle triage,
  before/after invariants), a 12-item checklist for other projects, and the negative
  results recorded honestly — data-paper material.
- **Citation infrastructure**: `.zenodo.json` + `docs/ZENODO_DOI.md` (concept/version DOI
  via the GitHub–Zenodo integration; the single manual toggle is documented).
- **bbox double-extraction dedup** (intervention registry #21; shipped default ON — see
  *Changed*): removes the
  duplicates that overlapping regional bboxes create — **(a) nodes** at identical coordinate+voltage
  and **(b) edges** with identical bus-pair+path (keeping max `par`). Verified as *removal*, not a
  forced connection: 飛騨変換所 has the same osm_id in both chubu & hokuriku extracts; 98.6 % of
  cross-region node-duplicate groups share the base name; 99.6 % of the 1,837 duplicate-edge groups
  have byte-identical paths (same OSM way). Genuine parallel circuits (represented as `par>1` on a
  single edge, 8,898 of them) are untouched, and **no self-loops** are created. Cuts west
  fragmentation 2,531 → 544 components (main 69 → 86 %; east 532 → 312) and removes the line
  double-counting (west 9,793 → 8,353 lines; east AC loss 6,415 → 6,781 MW, i.e. +5.7 % toward a
  realistic value as the artificial impedance-halving is undone). Report:
  `docs/reports/west_fragmentation_rootcause_2026-07-09.md`. Landed opt-in OFF on 07-09/10;
  flipped to default ON in this release with the accompanying Ybus/power-flow regeneration
  (see *Changed*). dedup fixes fragmentation but is not a cure for west full-scale AC.
- **All-island 24 h validation** of `--pref-demand --reactive-comp`
  (`docs/reports/allisland_24h_reactive_2026-07-09.md`): all 4 islands solve for all 24 hours
  (hokkaido & okinawa 24/24 AC with healthy voltages, east 22/24 AC + 2 honest dc_fallback,
  west DC by design). Compensation is robust across islands/hours (no BLAS abort). Documents the
  remaining east localized voltage outliers as the next mesh-refinement target. (Both flags
  became default ON in this release — see *Changed*.)
- **Reactive compensation** (opt-in `--reactive-comp`, intervention registry #20): shunt
  capacitor banks at load buses, modelling what real distribution substations carry but OSM
  omits. Diagnosis (`docs/reports/east_network_reactive_2026-07-09.md`) showed the east
  full-scale AC non-convergence under honest demand geography is a **reactive/voltage-collapse**
  problem, not an angle bottleneck: DC angles are healthy (prune removes ~0 lines) yet ~19 GVar
  of load reactive demand had to flow through high-X radial 66 kV lines with no local support.
  Compensation restores an honest full-scale AC solution (98.2 % served, 98.4 % of buses in
  0.9–1.1 pu). Config `reactive_compensation_factor` (default 0.6); wired into both
  `uc_to_pf_built.py` and `run_full_powerflow_from_db.py`; ledger in the result JSON.
  (Default ON as of this release — see *Changed*.)

## [1.5.0] - 2026-07-09

Tagged in git as `v1.5.0`. Theme: **ready-to-run dataset distribution** (download page,
self-contained bundles, MATPOWER / Excel-UC tutorials) and **honesty infrastructure**
(model-intervention registry, fake-AC guard, failure case studies), on top of a
numerically verified Ybus export line and sourced transformer nameplates.

### Added
- **Dataset distribution** — `dataset/` tutorials (`01_matpower_powerflow` `solve_pf.py`
  pandapower / `solve_pf.m` MATPOWER `runpf`; `02_uc_from_excel` Excel → 24 h unit
  commitment with xlsx/png output), self-contained bundle generator
  (`scripts/make_dataset_bundle.py`: core ≈13 MB / full ≈25 MB, `src`+`config`+data
  included, SHA256 MANIFEST), GitHub Release assets and a download page
  (`docs/download.html`). **E2E-verified**: real download → SHA256 match → fresh venv →
  both tutorials complete; `solve_pf.m` verified on MATLAB R2025a + MATPOWER 8.1
  (`bus_name`/`ext2int` crash worked around in the shipped case reader).
- **Numeric Ybus export line v1→v4** (`scripts/gen_ybus_numeric.py` → `dist/ybus/`):
  pandapower-canonical Ybus for the 4 asynchronous islands (17,333 buses,
  machine-precision symmetry / textbook cross-check p99 = 1.8e-16), branch matrices
  Yf/Yt + branch table (exact reconstruction identity), DC Bbus, Kron-reduced ≥154 kV
  backbone verified against a dense Schur complement, version stamps + sha256
  fingerprints in `.mat`/`.npz`/CSV; v4 wires sourced transformer nameplates into the
  matrices.
- **Transformer provenance DB** (`data/transformer_sources.jsonl`, 602 records / verify
  0 bad): existing nameplates (utility annual reports 有報「主要変電設備」 as the
  systematic source + society journals) and planned units from the grid-development
  plans of all 9 TSOs; nameplate propagation into build (`@nameplate`-tagged trafos).
- **Model-intervention registry** (`docs/MODEL_INTERVENTIONS.md`) — all 19 mechanisms
  that make the model *look* connected/solvable/complete (nearest-neighbour generator
  attachment, synthetic load allocation, default capacities, per-component slacks,
  prune ladders, …), each with basis / ledger / off-switch, plus rules for quoting
  results.
- **Territory-based zone re-attribution (A案)** (`src/powerflow/region_attribution.py`,
  default ON): coordinate → prefecture polygon → service area; kills the phantom
  Kyushu–Shikoku tie, restores the invisible Honshi tie, removes duplicate plant
  attachments; frequency-boundary moves forbidden. Failure case study:
  `docs/reports/case_study_phantom_tie_2026-07-07.md`.
- **Boundary injection + slack decomposition**: UC interconnection flows injected at the
  actual converter substations (Shin-Shinano FC, Kita-Hon); the east-island 24 h slack
  identity closes at machine precision (**slack ≈ losses, residual +0.02 %**); okinawa
  fleet calibrated with sourced capacities (slack 47.3 → 3.7 %).
- **Served-load guard against fake AC solutions**: AC solutions must serve ≥95 % of
  pre-solve load; `served_frac` ships in every result JSON. *Convergence is not
  correctness.*
- **Per-prefecture demand allocation** (registry #19, opt-in `--pref-demand`): zone
  totals split by sourced prefecture demand shares (METI/ANRE 電力調査統計 3-(2)
  FY2024, shipped as datapackage resource `data/reference/pref_demand_fy2024.json`
  with URL/quotes/checksum); cross-zone prefectures (Shizuoka Fujikawa split,
  frequency-guard enclaves) prorated by substation-node counts with a full ledger.
- **24 h power-flow animation** (`scripts/animate_powerflow_gif.py`): UC dispatch over
  the real OSM line paths, honest DC labelling, intervention-registry caveat on every
  frame.
- Sourced-capacity provenance DB grown 45 → 160 plants
  (`data/generator_capacity_sources.jsonl`), every value with source URL + verbatim
  quote; OSM/P03 capacity errors corrected (Kashiwazaki-Kariwa → 8212 MW, Soga solar
  1440 → 1.99 MW); decommissioned plants recorded as `0`; surfaced in map popups.
- `NOTICE` (third-party data attributions), `SECURITY.md` (trust boundary), Kansai-TD
  line-voltage external validation scorecard (97 % agreement on 38 named ≥154 kV trunk
  lines; aggregates only), `uv.lock`, `docs/ROADMAP_ASSET.md`, formal multi-agent
  review record (`docs/reports/formal_review_2026-06-26.md`).

### Changed
- **"east full-scale AC (99.0 % served)" re-interpreted**: a 7-variant probe
  (`docs/reports/a_plan_east_ac_regression_2026-07-08.md`, scripts + raw JSON archived)
  proved the claim stood on bbox-mislabelled demand geography — the sole breaker is the
  coarse spatial demand allocation, not Seikan island composition or plant dedup. With
  honest geography the full-scale AC is infeasible and is reported honestly as
  `dc_fallback`; AC demonstrations live on the backbone model. An early "recovery"
  under `--pref-demand` was traced to an enclave-weighting bug (accidental ~2.3 GW
  ballast at the Shin-Shinano corridor) and rejected before shipping.
- Legacy west "AC" artifacts (fake convergence) deleted; pages show the honest DC label.
- README correlation honesty: ρ = 0.721 labelled a capacity/topology proxy with the
  measured AC correlations alongside; "a first" hedged to "to our knowledge".
- CI / regeneration: `apply_capacity_sources` runs **after** `build_static_site`,
  fixing sourced-capacity overlay loss on deploy.
- CITATION.cff declares both MIT (code) and ODbL-1.0 (data).

### Fixed
- `requirements.txt` was missing `matplotlib` while the UC tutorial imports it
  unguarded — found by fresh-venv E2E, bundle re-shipped, plot now degrades gracefully.
- pandapower `from_mpc` mishandles multi-slack (multi-component) islands (negative
  losses); documented as a converter limitation — the distributed `.mat` is healthy and
  MATLAB/MATPOWER solves those islands correctly (hokkaido AC, loss +3.5 %).
- `apply_capacity_sources.py` ZeroDivisionError on sourced capacity `0`;
  `.gitignore` protects the redistribution-restricted `k_line.csv`.

### Known issues
- **east full-scale AC is infeasible under honest demand geography** (next lever: metro
  66 kV mesh representation — parallel circuits, transformer capacities, reactive
  support). Backbone model is the supported AC demonstration path.
- Sourced-capacity corrections are display-only for the map; the power-flow builder
  still reads `capacity_mw` (capacity bridge `--bridge` covers the UC/PF path).
- `papers/ieee-openaccess.tex` substation count (8,164 in prose) disagrees with its own
  table / the data (6,962).
- No DOI / Zenodo archive yet; the OSM snapshot timestamp is not embedded in
  distributed files.

## [1.4.0] - 2026-06-11

Tagged in git as `v1.4.0`.

### Added
- External validation against utility ground truth (TEPCO per-line flows, Kansai-TD line disclosure): corridor-usage rank correlation and substation/attachment recall, shipped as JSON scorecards.
- CIM / CGMES Level 2 power-flow case (EQ/TP/SSH/SV/GL) for all 10 regions, verified by pandapower `cim2pp` round-trip and strict CGMES validation (0 dangling references).

### Changed
- Full-model AC power flow solves across all 10 regions (kansai at full demand); the unified DB is the source of truth and the published GeoJSON is regenerated from it with per-field provenance markers.

## [1.3.0] - 2026-06-09

Tagged in git as `v1.3.0`.

### Changed
- **CIM/CGMES Level 2 regenerated — 8 of 10 regions now solve natively.**
  With the corrected parallel-circuit counting and unified voltage parsing
  (below), **chubu and kyushu** now converge natively instead of shipping as
  demand-scaled cases; only hokuriku (x0.8) and kansai (x0.3) remain balanced
  demand-scaled. All 10 verify OK on the boundary-aware cim2pp + runpp
  round-trip.

### Fixed
- **Vertex-snap parallel-circuit counting** (`examples`→`src/powerflow/
  snapped_topology`): a single OSM way that zig-zags across a node pair no
  longer inflates the parallel count, and the degree-2 chain contraction now
  carries the circuit multiplicity through instead of resetting it to 1 — so
  same-tower double circuits keep their restored capacity. Guarded by
  `tests/test_snapped_parallel.py`.
- **OSM voltage parsing unified** onto `src.utils.voltage`: a multi-voltage
  tag resolves to its highest level (`"66000;154000"` → 154 kV, not 66), and
  `","` is a value separator (no more `"77000,6600"` → 770006.6 kV concat).
  Six copies with two incompatible semantics collapsed to one.
- `_verify` now uses the same solver budget (`_try_runpp`: 100 iters +
  iwamoto fallback) as the solvability judgment, so a region judged native is
  not spuriously reported as `runpp-FAIL` (kyushu).

### Added
- **Power-flow pipeline promoted into `src/powerflow/`** (Phase C): the
  reconstruction → solve pipeline — `build_and_solve` (`pipeline`), the
  topology builders (`legacy_build`, `snapped_topology`), the net transforms
  (`transforms`) and the batch solver (`batch_solve`) — moved out of
  `examples/`/`scripts/` so no module under `src/` imports from `examples/`
  any more. The example/script entry points are thin re-export shims, so all
  import sites are unchanged. End-to-end pinned by `tests/test_pipeline_smoke.py`.
- **Single canonical region registry** `src/regions.py` (from
  `config/regions.yaml`) replacing ~25 hard-coded copies; `src/utils/voltage.py`;
  Haversine consolidated onto `src/utils/geo_utils`.
- **DB unification** (`docs/DB_ARCHITECTURE.md`): SQLite R/C/D layers with
  `scripts/db/{ingest,export,curate,enrich}.py`; the endpoint line-naming and
  audit Category-C enrichers now write to the DB so curation survives an OSM
  re-fetch. Curation backed up as the tracked `data/db/enrichments.jsonl`.

## [1.2.1] - 2026-06-08

Tagged in git as `v1.2.1`.

### Fixed
- **CIM/CGMES Level 2 export — electrical fidelity** (full-project review
  2026-06-08, commits `557fbe1` / `658fd2c`). The cim2pp round-trip is now
  electrically identical to the solved network (regression-tested, vm diff
  < 1e-4 pu): parallel circuits/transformer banks export their effective
  bundle values (previously up to 4x impedance), `in_service` switching
  states propagate via `ACDCTerminal.connected` (previously pruned lines and
  disabled loads re-energized on import), `Conductor.length` is km
  (previously metres, round-tripping 1000x), demand-scaled cases redispatch
  generation to `load x 1.05` (kansai previously shipped 3.5x generation
  with the slack absorbing 72%), and the SV profile is re-solved on the
  exported network (kansai previously shipped zero `SvVoltage`).
- Solve modes are now honest: 6 regions native; chubu/hokuriku/kyushu x0.8
  and kansai x0.3 as balanced demand-scaled cases (chubu/kyushu previously
  reported "native" because the buggy round-trip happened to converge).
- A `--regions` subset export no longer regenerates the boundary/index from
  only that run (which dangled every other region's `BaseVoltage`
  references); the boundary voltage set is unioned and the index merged.
- Level-1 EQ no longer defines `BaseVoltage` inline (duplicate rdf:IDs vs
  the shared boundary set); `export_cim.py` now ships the boundary files.
- MATPOWER export folds `num_parallel` into BR_R/BR_X/BR_B and RATE_A,
  matching the pandapower validation path.
- Restored `scripts/audit_data_quality.py` (deleted in `1f78a2868` while
  still imported by the test suite and invoked by `enrich_all.py`).
- `fetch_subdivided.py` preserves OSM element ids (`osm_type`/`osm_id`)
  through the tile merge — previously dropped by `ignore_index`, leaving
  substations/lines GeoJSON with no stable identity.

### Added
- **Unified grid database (R/C/D layers)** per `docs/DB_ARCHITECTURE.md`:
  `scripts/db/ingest.py` decomposes the per-region GeoJSON into immutable
  raw features and provenance-tracked enrichments (SQLite, schema v2);
  `scripts/db/export.py --verify` round-trips the database back to GeoJSON
  with semantic equality across all 30 region/layer files. The curation
  layer (232,139 rows) is backed up as the tracked, diff-readable
  `data/db/enrichments.jsonl`.
- CGMES round-trip regression tests (`tests/test_cim_level2.py`) and
  DB round-trip tests (`tests/test_db_geojson_sync.py`).

## [1.2.0] - 2026-06

Tagged in git as `v1.2.0`.

### Added
- **CIM / CGMES export** (`src/cim/`, `scripts/export_cim.py`): the dataset is
  now published as IEC 61970 CIM (CGMES 2.4.15) RDF/XML — EQ (Equipment) + GL
  (Geographical Location) profiles. Substations, lines and plants map to
  standards-conformant CIM objects (`Substation`, `ACLineSegment`, fuel-specific
  `{Thermal,Hydro,Wind,Solar,Nuclear}GeneratingUnit`, `SynchronousMachine`, …)
  with deterministic UUIDv5 mRIDs and WGS84 `PositionPoint` geometry.
  6,962 / 40,077 / 19,138 objects across all 10 regions, 0 dangling references,
  validated against pandapower `cim2pp` (independent CGMES parser).
  See `docs/CIM_MAPPING.md`.
- **CIM Level 2 — solvable CGMES power-flow case** (`src/cim/level2.py`,
  `scripts/export_cim_level2.py`): exports the solved pandapower network as
  EQ + TP + SSH + SV + GL with shared ConnectivityNodes, TopologicalNodes,
  PowerTransformer (+magnetizing g/b), EnergyConsumer loads, PV
  SynchronousMachines (voltage RegulatingControl) and a slack
  ExternalNetworkInjection (referencePriority). Round-trips through pandapower
  `cim2pp` and **`runpp` converges** (okinawa: 81 buses, 16 gens, vmin 0.941).
- **CGMES boundary set** (`src/cim/boundary.py`): `BaseVoltage` objects factored
  into a shared EQ_BD/TP_BD boundary (`AllJapan_EQ_BD.xml` + `AllJapan_TP_BD.xml`)
  referenced by mRID — CGMES convention for interoperability with PowerFactory /
  CIMverter. Boundary-aware `cim2pp` + `runpp` converges in all 10 regions
  (8 native; kansai/hokuriku demand-scaled per Ybus analysis, see CIM_MAPPING).
- **National Level-2 power-flow figures** (`docs/assets/figs/fig_cim_national_pf.png`,
  `fig_cim_okinawa_pf.png`): geographic voltage maps from CGMES round-trip.
- **Dataset distribution foundation**: unified property schema
  (`config/data_schema.yaml` + `docs/DATA_SCHEMA.json`), `DATA_DICTIONARY.md`,
  `DATA_CATALOG.md`, `CITATION.cff`, this changelog and `VERSION`.

### Fixed
- Number consistency across docs: substation total corrected to the measured
  6,962 (the README summary table previously read 7,962).

## [1.1.0] - 2026-06

Tagged in git as `v1.1.0`.

### Added
- N-1 contingency analysis across the nationwide 500/275 kV system (Kron-reduced
  generator-bus equivalent), extended through N-x cascade screening.
- Comparison tab in the live map UI with a satellite imagery layer for visual
  positional verification of substations and lines.
- Interactive Ybus and N-1 views surfaced inside the comparison tab.
- Automatic DC power flow for the national zonal solve.

### Changed
- Voltage standardization: `_clean_voltage` now snaps non-standard voltages
  (e.g. 22 / 25 / 30 / 33 / 100 kV) onto the standard Japanese voltage classes
  (66 / 110 / 154 / 275 / 500 kV).
- Regenerated all island/region datasets with the new standardized voltages.

### Fixed
- Hokkaido voltage-magnitude lower bound (`vm_min`) raised from 0.30 to 0.81,
  improving power-flow conditioning for the region.

## [1.0.0] - 2026-03

Tagged in git as `v1.0.0`. Initial release.

### Added
- Open Japanese power grid model automatically constructed from OpenStreetMap.
- 10 regions covering Japan's dual-frequency (50/60 Hz) system: 40,000+ lines
  and 7,000+ substations.
- GeoJSON data layers (substations, lines, plants) with voltage and operator
  metadata.
- Seven-stage attribute completion pipeline, sparse Ybus construction, AC power
  flow, and MILP unit commitment with inter-regional interconnection constraints.

[1.3.0]: https://github.com/lutelute/All-Japan-Grid/releases/tag/v1.3.0
[1.2.1]: https://github.com/lutelute/All-Japan-Grid/releases/tag/v1.2.1
[1.2.0]: https://github.com/lutelute/All-Japan-Grid/releases/tag/v1.2.0
[1.1.0]: https://github.com/lutelute/All-Japan-Grid/releases/tag/v1.1.0
[1.0.0]: https://github.com/lutelute/All-Japan-Grid/releases/tag/v1.0.0
