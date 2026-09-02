# Changelog

All notable changes to All-Japan-Grid are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Intervention #43a — implicit step-down transformers at class-mismatched line endpoints**
  (`src/powerflow/stepdown_gap.py`, default ON): where a 66 kV line was attached straight to a 275 kV busbar
  (Shin-Yodo line into Shinjuku, Nishi-Shinjuku, Nishi-Sugamo …), a same-site low-voltage bus and a step-down
  transformer are inserted — the equipment must exist for the connection to be physical. 26 sites in east,
  35 in west; east static AC vm_min 0.819→0.857 pu, real-line overloads 353→342, N-1 outages causing new
  overloads 222→166. Capacities are estimates on all 71 sites and are labelled as such. `#43b` (ledgered
  aggregation of transformer-less 66/77 kV subnets) ships default OFF.
- **Intervention #44 — circuit counts from published sources** (`scripts/apply_circuit_sources.py`,
  `data/reference/circuit_counts.jsonl`): 4,913 records from the utilities' published capacity tables,
  impedance sheets and open-keitouzu were matched to canonical branches and applied in the increase-only
  direction — 421 branches, including the Honshu–Shikoku 500 kV interconnector (1→2 circuits) and the
  Ueno / Ueno-Suidobashi 275 kV lines (1→3). West N-1 outages causing new overloads 425→187, islanded load
  37.1→31.8 GW; east worst new loading 503.6→232.2 %.
- **Intervention #45 — line capacity calibrated to published operating limits** (`--cap-calib`, default OFF):
  nationwide ratios (operating ÷ theoretical √3·V·I) per area and voltage class in
  `config/line_capacity_calibration.yaml`, ratios only — no redistributed capacity values. 154 kV agrees
  across Kansai and Tokyo (0.679 / 0.678) but 500 kV spans 0.37–0.95, so the default stays off.
- **Intervention #42 — mixed-prefecture frequency-boundary attribution** (`src/powerflow/region_attribution.plan_mixed_pref_flips`,
  `scripts/apply_node_hygiene.py --mixed-pref`, `data/reference/freq_boundary_mixed.geojson`, `freq_corridor_whitelist.json`):
  the 243 nodes in Nagano/Niigata/Shizuoka that the frequency guard (#6/#38) kept wholesale are now re-attributed by
  sourced boundary polygons + a cross-border trunk/FC whitelist + a cut guard that structurally forbids new
  cross-island cuts. 108 flips, 0 new cuts, cross-frequency edges 127→99, west peak-hour AC slack −291 MW.
- **Intervention #41 — island-specific generator attachment default** (`ISLAND_ATTACH_DEFAULT`): hokkaido/west use
  `capkv` (bus capacity ∧ required voltage class), east/okinawa stay on `cap`. Fixes the 318 % Hokkaido DC overload
  (Kyogoku 400 MW on a 66 kV bus); west solves AC 24/24 hours with no DC fallback.
- **Screening CLIs**: N-1 line-outage screening (`src/powerflow/contingency.py`, `scripts/sensitivity/n1_screening.py`),
  IBR hosting capacity by short-circuit ratio (`src/powerflow/short_circuit.py`, `scripts/sensitivity/ibr_hosting_scr.py`),
  multi-machine swing model at the AC operating point (`src/dynamics/machine_agg.build_classical_model_ac`,
  `scripts/gen_swing_modes.py --ac-op`). See README → Analysis Tools → Screening CLIs.
- **Reproduction DAG + verify-matrix CI** (`Snakefile`, `.github/workflows/verify.yml`,
  `scripts/ci/verify_matrix.py`, `scripts/ci/render_rulegraph.py`, `docs/figures/dag.svg`,
  `tests/test_repro_dag.py`): the regenerate pipeline is declared as a 21-rule Snakemake DAG
  (sentinel-ordered in-place intervention chain), and every push now solves the okinawa and
  hokkaido peak-hour full AC power flow from the canonical `all.json` and gates on
  convergence / vm_min / slack / served fraction. OSM snapshot timestamps
  (2026-06-15T13:35–14:25Z, 76/78 raw files) are stamped into `MODEL_VERSION.json`
  and `datapackage.json`.
- **Intervention #40 (experimental, default OFF) — census-mesh population
  tilt for intra-prefecture load allocation** (`allocate_loads(pop_tilt=)`,
  `--pop-tilt`): multiplies the voltage-class weights by a bounded tilt
  (0.5+0.5·pop/mean) from the e-Stat 1 km census mesh (Voronoi-assigned to
  nearest delivery bus). Default OFF after the validation matrix showed the
  on-disk mesh covers only the Kanto/Chubu tiles: the target Etajima pocket
  (outside coverage) was unchanged while the partial tilt distorted covered
  areas enough to regress east and west full-scale AC to dc_fallback. To be
  re-judged once nationwide mesh tiles are acquired; ledger and run-log
  disclosure included. Registry: `docs/MODEL_INTERVENTIONS.md` #40.
- **Intervention #39 — name-asserted region-fix application**
  (`scripts/apply_disclosure_v2.py`): the disclosure-v2 ledger's region fixes
  were applied by node ID alone, but the ledger contains stale pre-renumbering
  IDs (wave-7 audit), so fixes landed on unrelated nodes that now hold those
  IDs (e.g. the "Koumi-machi" fix hit the Tsukuno-cho substation in Kanagawa).
  Application now requires the normalized name at that ID to match the ledger
  entry; stale entries are resolved by name+from-region when unique (rescuing
  previously unreached fixes) or dropped with a disclosed count, and collateral
  stamps (name mismatch but region==to) are reverted to territory. Canon
  `all.json` repaired via `--from-worklist --write`: **22 reverts, 11 rescues,
  73 stale entries dropped**; west/east full AC and west backbone AC all
  regression-free.
- **Intervention #37 wave-8 refinement — downstream-exclusive load accounting**
  (`add_provisional_infeed`): cluster load now includes the net load of
  source-less components that become isolated when the cluster is removed
  (load whose only supply path runs through the cluster). Motivation: the
  Osaka Mikuni pattern — the Ajifu/Nishi-Mikuni 154 kV pair (own load 39 MW,
  under the 100 MW threshold) exclusively feeds a 118 MW 77 kV subnetwork and
  was being back-fed through two series 100 MVA transformers (vm 0.73).
  Detected now as 158 MW (118 MW downstream) with no threshold change; west
  full gains 3 links (9→12, one 44 km candidate capped to ledger-only), AC
  unchanged and the t=12 daytime snapshot now converges in 3 NR iterations.
  Ledger rows carry `downstream_mw`.
- **Intervention #38 — frequency-crossing reattribution refinement**
  (`src/powerflow/region_attribution.py` `UNIFORM_FREQ_PREFS` +
  `reattribute_node_regions(freq_fix=True)`, `--freq-fix-reattr` on both
  drivers, default ON; same guard added to `apply_node_hygiene.py` (#35)).
  Wave-6 diagnosis pinned the west full-scale AC divergence epicenter to the
  eastern-Nagano / Gunma 66-77 kV pocket: extraction-bbox spillover left
  Kantō-territory equipment labelled `region=chubu` (Tsumagoi 77 kV strings,
  the JR-East Jimbohara substation, Haruna-area 275/500 kV junctions,
  Kamonomiya, the Chuo-Shinkansen Tsuru substation …), and the blanket
  frequency-crossing guard prevented the territory reattribution from ever
  correcting them, while #35 (no guard) leaked 8 tokyo junctions into chubu.
  The guard's real purpose is protecting **mixed-frequency prefectures**
  (Nagano/Niigata/Shizuoka enclaves and cross-border 50 Hz trunks); for
  prefectures with a single frequency (Kantō + Yamanashi = 50 Hz, Aichi and
  westward + Hokuriku = 60 Hz) the correction is now allowed. Dry run:
  275 nodes fixed (chubu→tokyo 266, tokyo→chubu 9); Nagano's 50 Hz assets
  (143 nodes) stay guarded. Physical connectivity untouched. Also
  `add_provisional_infeed` gained `max_dist_km=40`: a nearest-upper-bus
  farther than that is ledgered (`capped: true`) instead of sewn — the
  Jimbohara 44 km mis-suture pattern surfaces in the ledger rather than the
  electrical model. Registry: `docs/MODEL_INTERVENTIONS.md` #38.
- **Intervention #37 — provisional metro infeed ((仮)都心給電の必然接続)**
  (`src/powerflow/pipeline.add_provisional_infeed`, `--provisional-infeed`
  on `run_full_powerflow_from_db.py` / `uc_to_pf_built.py`, default ON;
  owner-approved 2026-08-30). Load clusters ≥100 MW at 60–274 kV with **no
  transformer to the upper grid** get one provisional transformer to the
  nearest ≥275 kV bus. Rationale mirrors the inferred-busbar argument: a load
  that is actually served proves an upper-grid path **exists**; only the
  existence is claimed — path, voltage and rating are explicitly **provisional
  and may not be factual** (「(仮)・実経路未確認」 is stamped into every
  transformer name, and the full ledger — cluster, MW, chosen upper bus,
  distance, rating — is exported in result JSON as `provisional_infeed`).
  Root cause it addresses: the west AC non-convergence epicenter is the Osaka
  metro 154 kV cluster whose 275 kV underground network is missing from OSM
  (`docs/reports/west_ac_probe2_2026-08-30.md`), and Kansai's disclosed
  single-line diagrams are anonymized, so a #28-style source recovery is
  impossible. Effect: **first-ever AC solution on the west backbone**
  (7 provisional links → mode=ac, served 96.5 %, vm∈[0.941, 1.037];
  `docs/reports/west_ac_infeed_probe_2026-08-30.md`). To be replaced by real
  routes if ever published; `--no-provisional-infeed` restores the old
  behaviour for regression comparison. Registry: `docs/MODEL_INTERVENTIONS.md`
  #37.
- **AGC layer — the operations chain UC → power flow → AGC now closes on the
  dataset** (`src/dynamics/agc.py`, `scripts/run_agc_from_uc.py`,
  `tests/test_agc.py`). Multi-area LFC per synchronous island following the
  **IEEJ AGC30 standard model (技術報告 第1386号)** in a simplified per-class
  2nd-order form: AGC30 droop / governor-free width / LFC ramp-rate constants
  per plant class, TBC/FFC secondary control (KP=1.0, KI=0.003 s⁻¹, 10 MW AR
  deadband) and a continuous approximation of the 5-minute EDC layer. The UC
  solution supplies online inertia and regulation headroom; the inter-area tie
  stiffness T_ab = SΣ1/x is **measured from the extracted network**, not
  assumed. Two disturbance scenarios: a 2 % load step (LFC benchmark) and the
  largest-online-plant trip (plant-granularity upper bound of unit N-1, with a
  3-step typical-value **latching** UFLS — relays shed and stay shed; the first
  non-latching draft made frequency sit unphysically at the shed boundary and
  was caught by the owner). An animated map of the Tomato-atsuma trip
  (`scripts/gen_agc_map_anim.py` → `docs/slides/ajg/assets/agc_hokkaido_trip.gif`)
  shows the event geographically: grid color = frequency, shed amount from the
  simulation (which substations to shed is not public — marked as staging).
- **Multi-machine swing co-simulation (AGC30 → AGC-N)**
  (`scripts/run_multimachine_hokkaido.py`): every UC-committed plant becomes its
  own machine (AGC30 class governor + per-fuel H/Xd′) on the **Kron-reduced Ybus
  of the extracted network** — classical swing + governor + LFC + latching UFLS
  (integration events switch precomputed reduced matrices). Hokkaido
  Tomato-atsuma trip: 54 machines, exact initialisation against the AC power-flow
  solution (max |Pe(δ0)−P_PF| = 0.0 MW), inter-machine oscillations ±40° visible,
  UFLS stages at 1.6/2.0/2.7 s. Two disclosed calibration gaps vs the COI layer
  (constant-Z loads, GF-width implementation) leave the multi-machine nadir
  slightly deeper (−3.0 vs −2.5 Hz). Root-caused en route: ppc baseMVA=1 vs the
  100 MVA system base (Ybus rescaling), and res_bus↔ppc index ordering.
- **…generalised to all four islands** (`scripts/run_multimachine_national.py`,
  replacing the hokkaido-only script): 542 machines total (hokkaido 53 /
  east 182 / west 302 / okinawa 5) with sparse-LU Kron reduction (west 8,183
  buses). West is initialised from the DC snapshot (V=1 pu approximation,
  disclosed — full-AC infeasibility is canon) with self-consistent Pm=Pe(δ0).
  Two new honesty devices: an **out-of-step protection** event (|Δ(δ−δ_COI)|
  > 180° trips the machine and re-reduces the network — 7 weakly-coupled small
  units across east/west, all logged) and a **capacity-suspect guard**
  (rating > 10× operating point and +500 MW falls back to operating-point
  base; caught 奥吉野 97 MW/1,206 MW and 奥多々良木 155 MW/1,932 MW pumped-storage
  entries, disclosed not edited). East rides through its largest plant loss at
  −0.45 Hz with all machines visibly swinging; west shows ±0.3 Hz inter-machine
  oscillation decaying over ~10 s. Deck slide 18 (全国・全機の動揺) added.
- **24-hour frequency-security profile** (`scripts/gen_agc_24h_profile.py` →
  `fig_agc_24h.png`, deck slide 19): every hourly UC commitment becomes a
  snapshot — online inertia, largest online plant, trip RoCoF and nadir per
  island per hour. Night-time inertia drops ~30 % on the large islands; on
  Hokkaido the worst hour is 3 am (nadir −7.1 Hz, beyond the 3-step UFLS) —
  the same hour of night as the actual 2018 blackout (3:08), stated as a
  structural correspondence, not a reproduction.
- **Electromechanical wave-propagation animation**
  (`scripts/gen_swing_wave_anim.py` → `agc_east_wave.gif`, deck slide 19):
  the Futtsu trip replayed on the map with每-machine local frequency as
  color — the disturbance visibly propagates over the real network impedance
  (Kanto reddens within ~200 ms while northern Tohoku is still blue), with a
  synchronized all-machine strip chart + time cursor. Trace dumps
  (`mm_traces_*.npz`, gitignored) added to the multimachine runner, which now
  also captures machine coordinates via the pandapower-3 `bus.geo` API (the
  old `bus_geodata` path silently returned none).
- **West full-AC canonisation campaign, probe wave 1**
  (`scripts/probe_west_ac.py` → `docs/reports/west_ac_probe_2026-08-29.*`):
  site_trafos (#22), reactive-comp 0.8, hourly shunts and combinations all
  fall back to DC at the west peak snapshot — and #22 only creates 22
  site-transformer links on west (vs the 57 % T-gap), so the site-name
  matching itself is the prime suspect for wave 2. Canon unchanged. All dynamic parameters carry provenance
  labels; results are structural demonstrations, not operational predictions.
  Outputs: `docs/data/agc/agc_chain.json`, `papers/figs/fig_agc.pdf`,
  `docs/assets/figs/fig_agc_national.png`.
- `papers/ieee-openaccess.tex`: new AGC subsection (§VI) + AGC30 reference;
  the long-standing substation-count typo fixed (prose 8,164 → measured 6,962,
  matching the paper's own table — was a Known Issue since v1.5.0).

### Fixed
- **Sourced-capacity name matching painted thermal/nuclear capacities onto same-named solar features**
  (`scripts/apply_capacity_sources.py`): a fuel-type gate now rejects incompatible name matches unless the record
  only lowers the capacity. Removes 13.6 GW of phantom "solar" in east (Takasaki "高浜発電所" ← Takahama nuclear
  3,392 MW) and 6.1 GW in west (Himeji No.2 / Matsuura neighbours); the real Takahama nuclear feature now carries the
  official source.
- **Classical swing model flat path** (`machine_agg.build_classical_model`): the synchronising-torque matrix carried an
  extra −B_ii on the diagonal, losing the rigid-body mode and biasing frequencies upward (`legacy_diag=True` reproduces).

## [1.8.0] - 2026-08-27

Tagged in git as `v1.8.0`. Theme: **the visible substation（SubSLD法）** — the model now
looks *inside* substations. A three-stage pipeline (GridStitch P2 extraction → property
aggregation → evidence-paired rendering) turns OSM evidence into per-substation
single-line diagrams for every site in Japan, with every drawn element traceable to a
witness and every estimate marked as such.

### Added
- **SubSLD法 (Evidence-Paired Substation Single-Line Diagramming)** — method doc
  `docs/SUBSLD_METHOD.md`, academic slide deck, and formal framing (evidence-closure
  operator, lexicographic binding, certified lower-bound circuit estimator, three-valued
  direction inference with explicit abstention ⊥).
- **Substation property layer** (`scripts/build_substation_properties.py`):
  circuits / conductor-bundle / cable counts aggregated per substation×voltage-level
  from OSM line tags (evidence and estimate kept separate; lower-bound guarantee).
  Attached to built sub nodes as `sub_props` (9,139 nodes).
- **Evidence-pair figures for all 7,239 sites**: batch generator
  (`scripts/build_subsld_batch.py`, resumable, GSI tile cache) rendered the full country
  (searchable PNG gallery, NAS-backed), and a **Pages viewer** `docs/subsld.html`
  (compact JSON 3.2 MB + raw way overlay 4.4 MB) draws GeoPane (GSI photo/std-map
  toggle, site outline, real way geometry, binding markers ●■▲) and SLDPane
  (busbar sections, circuit strokes, direction arrows, dashed leadin, transformers,
  through-voltage annotation) live in the browser.
- **Inferred busbars** (`inferred-topology`, +2,669 nationally): voltage levels with ≥2
  strongly-bound terminals and no busbar way get a logical busbar, drawn dashed and
  labeled 推定 in both PNG and Pages renderers (issue #49 design).
- **Fragment campaign interventions #35 & #36**: node hygiene resolved 55 false
  fragments / 139 nodes from cross-region double registration (east components
  230→196, west 433→412); the satellite-evidence connection class applied its first
  link (Ojiya 66 kV, `recovery="satellite"`), with Yuzawa held after voltage-bus review
  (the substation is `traction`).
- **False-fragment screening** (`scripts/screen_false_fragments.py`) and the satellite
  photointerpretation pilot report (4 gaps, 3 corridor-confirmed, one revealed as a
  registration artifact).
- **issue #49 measurements**: busbar-way coverage 14.2 % (Point-type 3.2 %), terminal
  binding distribution (vertex 15.7 / polygon 29.3 / leadin 55.0 %), direction
  abstention 39.4 % of 18,851 line groups; 14-site satellite review (64 % mappable
  omissions) and an OSM edit candidate list (10 entries,
  `docs/reports/osm_edit_candidates_2026-08-27.md`).

- **CIM/CGMES export of the node-breaker layer** (`src/cim/exporter.py`):
  `BusbarSection` (4,743 nationally; 2,289 of them inferred and flagged in
  `IdentifiedObject.description`), `Bay` (8,475; couplers disclosed by name),
  and per-site `VoltageLevel` now reach CGMES EQ alongside the existing
  `PowerTransformer` mapping — the SubSLD structure is consumable by standard
  power-system tooling, caveats included.

### Changed
- Structure DB regenerated against enrichment-updated extracts — site-id matching now
  100 % (was 363 unmatched); okinawa regression pin deliberately moved to 60/167/59.
- `regenerate_all.py` STEPS extended with `node_hygiene`, `satellite_connections`,
  `substation_properties`, `subsld_pages`, `subsld_ways` — the whole 1.8 layer is
  one-command reproducible (verified with a full `--light` pass).

### Fixed
- Cross-region duplicate registrations no longer masquerade as island fragments
  (the c1 "Kofu 66 kV backbone" class); the voltage-consistency gate remains untouched.


## [1.7.0] - 2026-08-20

Tagged in git as `v1.7.0`. Theme: **the disclosed grid** — official disclosure data
(様式5 impedance sheets, point-demand records, OCCTO interconnector capacities, area
supply-demand actuals) is now wired into the canon, and the interconnector/converter
layer is corrected against primary sources.

### Interconnectors & converters (interventions #31/#32/#33)

- **#31 — synthetic tie de-energisation.** The 7 straight-line OCCTO ties (kv=0
  inheriting 500 kV) double-counted the real interconnector geometries and are now
  built `in_service=False` (kept for connectivity/display; exception: 東北東京間連系線
  stays live until the 340 m 南いわき stitch). The Anan–Kihoku DC trunk got its real
  OSM geometry (submarine 46 km + overhead 50.6 km) and 由良開閉所's dead-end fixed.
- **#32 — Minami-Fukumitsu BTB split.** Chubu–Hokuriku is a back-to-back DC link;
  the model had an AC pass-through carrying 575–1,210 MW (vs the 300 MW rating).
  The bus is now split (`--no-btb-split` to disable). A/B: pass-through → 0,
  AC convergence and vm_min unchanged.
- **#33 — `interconnections.yaml` rebuilt from OCCTO published capacities**
  (28 sourced records): direction-aware capacities (関門 850/2,850 MW — the old
  symmetric 2,780 overstated the forward direction 3.3×), ic_005 corrected to the
  南福光 BTB 300 MW (the old "加賀–越前 1,900 MW" conflated an intra-Hokuriku line
  with the Hokuriku–Kansai corridor), ic_010 (越前嶺南線) added, 関西四国 typed HVDC.
  Legacy file preserved as `interconnections_legacy_2024.yaml`.
- **UC formulation fix.** Regional balance was an inequality (`>=`) allowing free
  disposal of surplus — Kyushu could "generate" 5.7 GW above its scheduled export
  and the resulting phantom flow showed up as a 2× capacity violation on 関門.
  Now an equality with an explicit penalised spill variable
  (`UCResult.regional_spill_mw`); pumped-storage charging is counted on the demand
  side and intra-island DC schedules are injected at the converter buses. Verified:
  every region balances to 0.0 MW and all 10 links stay within direction-aware
  capacity in all 24 hours.

### Disclosure-driven network completion

- **Disclosed connections (interventions #28/#29, 89 edges)** from the 様式5
  impedance sheets of all 10 TSOs (normalization: 1,009 lines / 213 transformers),
  re-applied as pipeline steps so regeneration can no longer silently drop them.
  Isolated substations: 本系統外 → 1,780 nodes (was 2,000 before v2 apply).
- **EGGC** (evidence-gated grid conflation): disclosed codes snap to real OSM
  geometry only when the fragment *is* the disclosed line (off-main ratio ≥ 0.7);
  14 routed edges ledgered, no fabricated geometry.
- **Map-read nodes**: 新潟154 kV (新飯田・下田ほか)・中越 backbone・静岡77 kV・
  四日市77 kV local grids read from disclosed single-line diagrams and connected
  with per-edge provenance.
- **Point demand (intervention #30, default ON)**: L_DB observed per-substation
  demand pins ~30 buses; zone totals unchanged.

### Capacity & provenance

- **GEM capacity fill shipped**: 194 sourced records / 22.5 GW appended to the
  provenance-first capacity DB (354 rows, verify all-PASS), applied to the
  distributed GeoJSONs with source URLs.
- OCCTO interconnector operating capacities (14 links × 2 directions) established
  as a sourced canon (`data/interconnector_capacity_sources.jsonl`).

### Observability (GitHub Pages, not part of the dataset bundles)

- Live flow map (`flow_map.html`): 24 h nodal flows, comet-style direction-true
  animation, date snapshots driven by published demand actuals, and — new —
  **fuel-wise actual injection** (area supply-demand actuals of 9/10 TSOs):
  nuclear outages and fuel mix propagate from official actuals into the daily
  snapshots automatically, with zone net positions matching the published
  interchange column to 39–129 MW in validation.

### Ledger hygiene

- Issue #42: 25 coordinate-jitter duplicate pairs in the disclosed-connection
  ledger purged; merges are now keyed semantically, not by coordinates.
- Ybus export now excludes de-energised branches (post-#31 consistency) and the
  numeric Ybus set is regenerated from the current canon.

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
