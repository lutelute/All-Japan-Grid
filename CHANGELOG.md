# Changelog

All notable changes to All-Japan-Grid are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
  CIMverter. Boundary-aware `cim2pp` + `runpp` converges in 9/10 regions.
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
