# リリースの要点 / Release highlights

README に載せていた各リリースの要点を、原文のまま移したものです（2026-09-21）。
全履歴は [CHANGELOG.md](../CHANGELOG.md)。リンクは README に置かれていたときの相対パスのままなので、
`docs/...` で始まるものはリポジトリ直下からの相対です。

### v1.7.0 — 2026-08-20

- 🔌 **Interconnector & converter layer corrected against primary sources /
  連系線・変換所層の正本化** (interventions #31/#32/#33). Synthetic straight-line
  ties de-energised (real geometries carry the flow; Anan–Kihoku DC got its actual
  submarine+overhead route), the 南福光 BTB no longer passes AC through, and
  `interconnections.yaml` is rebuilt from OCCTO published operating capacities with
  **direction-aware limits** (関門 850/2,850 MW). A UC formulation bug (regional
  balance as `>=` = free surplus disposal) was found and fixed with an explicit
  spill ledger — all 10 links now stay within capacity in all 24 hours.
  合成タイ非通電化・南福光BTB切断・OCCTO正本の方向別容量・UC収支等式化。
- 📄 **Disclosure-driven completion / 公表資料による網の補完.** 全10社の様式5
  (インピーダンス)正規化 1,009線/213変圧器 → 89 disclosed connections applied as
  pipeline steps; EGGC snaps disclosed codes to real OSM geometry only under an
  evidence gate; local grids (新潟154 kV・静岡77 kV・四日市77 kV) node-ified from
  disclosed diagrams. Point demand (#30) pins observed substation loads.
- 🏷️ **Sourced capacities / 出典付き容量の拡充.** GEM fill +194 records / 22.5 GW
  (provenance DB 354 rows, all verified); OCCTO interconnector operating
  capacities (14 links × 2 directions) as a sourced canon.
- 📊 **Live observability / 公表実績で動く可視化** (Pages, not in the bundles):
  24 h nodal flow map with date snapshots injected from area supply-demand
  actuals of 9/10 TSOs — nuclear outages propagate automatically from official
  actuals (zone net positions validated to 39–129 MW against the published
  interchange column).

### v1.6.0 — 2026-07-10

- ✅ **Interventions #19/#20/#21 now default ON / 介入3件の既定ON化**
  ([docs/reports/default_on_decision_2026-07-10.md](docs/reports/default_on_decision_2026-07-10.md)).
  Per-prefecture demand (#19), reactive compensation (#20) and bbox-duplicate dedup (#21) are the
  default model as of 2026-07-10 (owner-approved). Evidence: 4-island before/after probes (no
  solution regression, fragmentation improves everywhere — west 2,531→544 components), 44 gates
  PASS, numeric **Ybus canon v5.0.0** with fingerprint lineage. `--no-pref-demand
  --no-reactive-comp --no-dedup-nodes` reproduce the legacy behaviour exactly. East losses rise
  +31 % on the probe snapshot — that is the *correction* (double-counted boundary lines halved
  impedances before). 東の損失増は二重計上是正の方向であり改悪ではない。
- 📚 **Methodology consolidation & sourced compensation factor / 方法論統合と補償率の出典化.**
  Four pitfall classes of OSM-derived grid models + 5 diagnostic methods + a 12-item checklist
  ([osm_grid_pitfalls_methodology_2026-07-10.md](docs/reports/osm_grid_pitfalls_methodology_2026-07-10.md));
  intervention #20's factor 0.6 anchored to primary sources — Shikoku EGC 2024 measurements
  convert to ≈0.8 today / ≈0.05 in the 1990s, so 0.6 sits on the conservative side of the
  observed range ([reactive_comp_provenance_2026-07-10.md](docs/reports/reactive_comp_provenance_2026-07-10.md)).
- 🔌 **east full-scale AC solved — root cause was reactive power, not topology / east全規模ACの網側解明.**
  ([docs/reports/east_network_reactive_2026-07-09.md](docs/reports/east_network_reactive_2026-07-09.md)).
  Under honest demand geography the 6,222-bus east AC failed — but the DC angles are healthy
  (the angle-based prune ladder removes ~0 lines) so the breaker is **reactive power / voltage
  collapse**, not an angle bottleneck: ~19 GVar of load reactive demand had to flow through
  high-X radial 66 kV lines with **no local support**. Modelling the shunt capacitor banks that
  real distribution substations carry (`--reactive-comp`, intervention #20; default ON since
  2026-07-10) restores an honest full-scale AC solution — **98.2 % served, 98.4 % of buses in
  the 0.9–1.1 pu band** (vs the earlier fake 10.8 %). The remaining ~41 outlier buses (0.66 %)
  are the localized 66 kV detail left to refine.
- 🧾 **Model-intervention registry now at 20 entries** — #19 per-prefecture demand, #20 reactive
  compensation, each with basis / ledger / off-switch.
- 🗾 **All-island 24 h validation of `--pref-demand --reactive-comp`**
  ([docs/reports/allisland_24h_reactive_2026-07-09.md](docs/reports/allisland_24h_reactive_2026-07-09.md)).
  All four islands solve for all 24 hours: hokkaido & okinawa 24/24 AC with healthy voltages
  (0.77–1.01 / 0.82–1.00 pu), east 22/24 AC (98 % served) with 2 hours honestly falling back to
  DC, west DC by design (single-synchronous-island AC is known fake convergence — backbone
  handles its AC). Reactive compensation holds across every island and hour with no BLAS abort.
  Remaining gap: east's localized 66 kV voltage outliers (vm ceiling ≈1.70, one hour 2.78) — the
  next mesh-refinement target. (Both flags became default ON on 2026-07-10 — see the decision
  report above.)
- 🔀 **east vs west, diagnosed apart**
  ([docs/reports/east_vs_west_ac_2026-07-09.md](docs/reports/east_vs_west_ac_2026-07-09.md)).
  The "east AC / west DC" split hid the real story: applying east's exact diagnosis to west shows
  **both are reactive-limited, not different in kind** — west's DC angles are healthy too. The
  difference is fragmentation: east has 533 components (89 % of load in the main one) and reaches
  honest AC at 30 % compensation, robustly; west has **2,531 components (5×, only 69 % in the
  main)**, needs 90 % compensation, and even then converges only marginally (the operational CLI
  ordering fails). west's lower loss / cleaner voltages are a fragmentation by-product, not a
  better model. Conclusion: **"west = DC" is the right default** — west's real problem is
  topology (missing OSM ties / substation hubs), not reactive support; we won't force its AC.

### v1.5.0 — 2026-07-09

- 📦 **Ready-to-run dataset distribution / DLしてそのまま回るデータセット配布.**
  Self-contained bundles (core ≈13 MB / full ≈25 MB, SHA256 MANIFEST) on the GitHub Release,
  a [download page](https://lutelute.github.io/All-Japan-Grid/download.html), and `dataset/`
  tutorials: MATPOWER power flow (pandapower `solve_pf.py` / MATLAB `solve_pf.m`) and
  **Excel → 24 h unit commitment** (`make_template.py` → edit xlsx → `run_uc.py`).
  E2E-verified: real download → SHA256 match → fresh venv → both tutorials complete
  (MATLAB R2025a + MATPOWER 8.1 verified; `requirements.txt` matplotlib gap found by the
  fresh-venv test and fixed before shipping).
- 🧾 **Model-intervention registry / モデル介入台帳** ([docs/MODEL_INTERVENTIONS.md](docs/MODEL_INTERVENTIONS.md)).
  Every mechanism that makes the model *look* connected, solvable, or complete — nearest-neighbour
  generator attachment, synthetic load allocation, default capacities, per-component slacks,
  prune ladders (18 in total) — is now catalogued with its **basis, ledger (where it is disclosed),
  and off-switch**. Includes "how to read" rules: per-line flow values are composite estimates and
  must not be cited individually. Motivated by the phantom-tie incident (next bullet):
  *an internally consistent model can silently assert equipment that does not exist.*
  「専門知識がないと、つながったと信じ込んでしまう」— 盲信リスクへの恒久対応として、
  接続・値・配分を作る介入18件を根拠・帳簿・無効化の3点セットで台帳化。
- 🕵️ **Failure case study: the phantom tie / 失敗事例「幻の連系線」**
  ([docs/reports/case_study_phantom_tie_2026-07-07.md](docs/reports/case_study_phantom_tie_2026-07-07.md)).
  For ~a month the model asserted a non-existent Kyushu–Shikoku interconnector (445 MW) — actually
  two real Chugoku-EPCO lines in Yamaguchi mislabelled by overlapping extraction bboxes. Found only
  by reconciliation against external ground truth (OCCTO's real tie list). Fixed by
  **territory-based zone re-attribution** (coordinate → prefecture polygon → service area;
  physical connectivity untouched, frequency-boundary moves forbidden): multi-zone duplicate
  coordinates 1,623→10, the invisible Honshi tie restored, duplicate plant attachments removed.
- ⚖️ **Slack decomposed to physics / slackの完全分解.** With sourced okinawa fleet calibration
  (slack 47.3→3.7%), capacity bridging, and UC interconnection flows injected at the *actual*
  converter substations (Shin-Shinano FC, Kita-Hon), the east-island 24 h slack identity now closes
  at machine precision: **slack ≈ losses (residual +0.02 %)**
  ([docs/reports/east_slack_decomposition_2026-07-07.md](docs/reports/east_slack_decomposition_2026-07-07.md),
  [boundary_injection_2026-07-07.md](docs/reports/boundary_injection_2026-07-07.md)).
- 🛡 **Served-load guard against fake AC solutions / 見せかけAC解ガード.** A "converged" AC solve
  that silently disconnected 90 % of the network (6.2 of 57.4 GW served, 149 MW losses — physically
  impossible) is now rejected: AC solutions must serve ≥95 % of pre-solve load, and
  `served_frac` ships in every result JSON. *Convergence is not correctness.*
- 🔬 **Root cause of the east full-scale AC regression / A案回帰の原因確定**
  ([docs/reports/a_plan_east_ac_regression_2026-07-08.md](docs/reports/a_plan_east_ac_regression_2026-07-08.md)).
  A 7-variant probe (scripts + raw JSON archived alongside) shows the territory re-attribution
  itself is *correct* — the breaker is the coarse **demand allocation** (zone-uniform × voltage
  weights): relabelling ~350 nodes in the Niigata/Fukushima–North-Kanto belt to their true
  service areas shifts ~1 GW of demand (a 66 kV bus jumps 11.3⇄23.6 MW) and tips the marginal
  6,205-bus AC solve into non-convergence. Seikan island composition and plant dedup were
  cleared (identical topology still fails). **Consequently the earlier "east full-scale AC
  (99.0 % served)" claim stood on the old bbox-mislabelled demand geography** — treat it as a
  limit solution, not a validated operating point. Full-scale runs now honestly report
  `dc_fallback` (guard above); AC demonstrations live on the backbone model.
  **Follow-up (registry #19, `--pref-demand`, default ON since 2026-07-10)**: demand allocation refined to sourced
  per-prefecture shares (電力調査統計 FY2024) — metro Tokyo now carries a realistic
  ~50 MW/bus vs ~10 MW/bus rural. An early probe seemed to restore full-scale AC, but was
  traced to an enclave-weighting bug that dumped ~2.3 GW of Nagano demand at the Shin-Shinano
  FC corridor — the same accidental-ballast pattern this report exposes — and was rejected
  before shipping. With honest weights the full-scale AC stays infeasible: *the model, not
  the demand geography, is what needs fixing next* (metro 66 kV mesh representation).
- 🎬 **24 h power-flow animation / 潮流アニメーション**
  (`scripts/animate_powerflow_gif.py`): the UC dispatch flowing through the national grid,
  hour by hour — line width/shade = |P|, generation bubbles, FC/Kita-Hon transfers, honest
  DC labelling for west, and the intervention-registry caveat rendered on every frame.

### v1.4.0

- 📏 **Externally validated against utility ground truth — to our knowledge, a first for an OSM-extracted public grid.** The model is now scored
  against TEPCO's published per-line flow measurements and Kansai-TD's line disclosure:
  corridor-usage rank correlation (a capacity/topology proxy) **interior Spearman ρ = 0.721** (boundary-conditioned corridors excluded, p≈1e-09),
  while the AC power flow solved on synthetic loads correlates at **ρ ≈ 0.46 (interior) / 0.60 (trunk)**;
  substation recall 86%, attachment recall 55%. Every score ships as a JSON scorecard in
  [docs/reports/](docs/reports/) and the full source survey in
  [docs/VALIDATION_SOURCES.md](docs/VALIDATION_SOURCES.md). `ajgrid validate --topology` gives the KPIs.
  Line **voltage class** is independently cross-checked against Kansai-TD's official ≥154 kV
  trunk-line disclosure: **97 % agreement** (37/38 named lines; aggregate only — the utility's
  raw per-line values are not redistributed, see [scorecard](docs/reports/external_kansai_lines_voltage_2026-06-26.json)).
- ⚡ **AC convergence without demand scaling — all 10 regions, both models.** The FULL
  regional model (sub-grid included) now solves natively everywhere — kansai at its full
  22,833 MW (previously ×0.3-0.4 demand-scaled only) — and the `--backbone` reduction
  (region-aware cut: ≥154 kV mainland, 66 kV floor for hokkaido whose grid IS its 66 kV
  layer) gives the cleaner planning view with generator Q-limits enforced
  (`ajgrid solve <region> [--backbone]`). The interior corridor-usage rank correlation
  (a capacity/topology proxy, boundary corridors excluded) is **ρ = 0.721**; the AC flow
  solved on synthetic loads correlates at **ρ ≈ 0.46 (interior) / 0.60 (trunk)**.
- 📦 [Release v1.4.0](https://github.com/lutelute/All-Japan-Grid/releases/tag/v1.4.0):
  `all_japan_grid_cim_L2.zip` regenerated with this model — **kansai's CIM case improves
  from ×0.3 to ×0.8 demand**, 6 regions native + 4 at ×0.8, all 10 verified by `cim2pp`
  round-trip and strict CGMES validation (0 dangling references).
- 🏗 **Multi-voltage substations + evidence-based connectivity.** One bus per voltage class with
  intra-substation transformers (cross-voltage LINES are no longer swallowed — kansai recovers
  +759 real lines); OSM `circuits`/`cables` tags drive parallel counts; corridor voltage
  propagation types untagged segments (unknown-voltage branches: kansai 25→8%); every branch
  carries connection provenance (`conn=`, `circuits=`, `kv=`).
- 🔌 **Merit-order dispatch & boundary imports.** Fuel-specific capacity factors replace uniform
  scaling, and OCCTO interconnection flows are injected at regional boundaries (a regional slice
  is not an island) — both adopted because they measurably improved the TEPCO flow correlation.
- 🗄 **`data/*.geojson` are now DB-derived artifacts.** The unified database
  (`ajgrid db ingest` → `data/grid.db`) is the source of truth; the published GeoJSON is
  regenerated from it with per-field provenance markers (`"_src:capacity_mw": "p03_db"`),
  so authoritative values (国土数値情報 P03) ride in the public files WITHOUT breaking the
  mechanical-update loop — re-ingest preserves their sources (regression-pinned).
- 🧭 **OSM case studies** ([docs/reports/](docs/reports/2026-06-10_fable5_osm_case_studies.md)):
  kansai (map density ≠ electrical usability), hokuriku (attribute gaps break connectivity),
  tokyo (attachment correctness is the residual) — measured teaching examples for OSM-based
  grid modelling, with per-model improvement ledger in
  [docs/reports/IMPROVEMENT_LOG.md](docs/reports/IMPROVEMENT_LOG.md).

### v1.3.0

- ✅ **CIM / CGMES Level 2 — electrically faithful & more native solves.** Corrected parallel-circuit counting and unified voltage parsing make the cim2pp round-trip electrically identical to the solved network, and lift **chubu & kyushu to native convergence**: **8 of 10 regions now solve natively** (hokuriku x0.8, kansai x0.3 as balanced demand-scaled cases). All 10 verify OK.
- 🔧 **Power-flow pipeline promoted into `src/powerflow/`** — the reconstruction → solve pipeline (`build_and_solve`, topology builders, net transforms, solver) moved out of `examples/`/`scripts/` so the dependency flows the right way and the model is testable in CI.
- 📦 [Release v1.3.0](https://github.com/lutelute/All-Japan-Grid/releases/tag/v1.3.0): `all_japan_grid_cim_L1.zip` (31 MB) + `all_japan_grid_cim_L2.zip` (13 MB)

### v1.2.0

- 🆕 **CIM / CGMES standardization** — the whole dataset re-expressed as IEC 61970 CIM (CGMES 2.4.15 RDF/XML). **Level 1** catalogue (6,962 `Substation` / 40,077 `ACLineSegment` / 19,138 fuel-specific `GeneratingUnit`) + **Level 2** solvable power-flow case (EQ/TP/SSH/SV/GL), validated via pandapower `cim2pp`.
- 📄 Full mapping spec: [docs/CIM_MAPPING.md](docs/CIM_MAPPING.md)

### v1.1.0

- 🆕 [N-1 contingency analysis](https://github.com/lutelute/All-Japan-Grid/blob/main/scripts/run_n1_contingency.py) — 914 backbone lines tripped one-by-one across 9 regions, identifying pivotal lines whose loss breaks AC convergence in Tokyo / Kyushu.
- 🔧 Voltage standardization (`_clean_voltage`) — non-standard 22/25/30/33/100 kV snap to JP standard classes. **Hokkaido `vm_min` 0.30 → 0.81 pu**.
- ⚡ National-zonal power flow — east/Hokkaido/Okinawa AC + west DC, with **auto-DC mode** on the live map.
- 🗺 New compare tab with Ybus visualization (national / per-region / spy plot).
- 📄 [Release notes](https://github.com/lutelute/All-Japan-Grid/releases/tag/v1.1.0) / [Root-cause analysis](https://github.com/lutelute/All-Japan-Grid/blob/main/docs/WEST_AC_ANALYSIS.md)
