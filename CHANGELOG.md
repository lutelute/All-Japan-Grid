# Changelog

All notable changes to All-Japan-Grid are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[1.2.0]: https://github.com/lutelute/All-Japan-Grid/releases/tag/v1.2.0
[1.1.0]: https://github.com/lutelute/All-Japan-Grid/releases/tag/v1.1.0
[1.0.0]: https://github.com/lutelute/All-Japan-Grid/releases/tag/v1.0.0
