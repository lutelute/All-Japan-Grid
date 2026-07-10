"""SQLAlchemy 2.0+ ORM schema for grid attribute storage.

Defines four tables:

- **generator_attributes** — Mutable generator properties (fuel type,
  capacity, cost parameters, storage characteristics).
- **substation_attributes** — Mutable substation/bus properties
  (tap ratio, voltage setpoint, zone assignment).
- **load_attributes** — Mutable load properties (load model type,
  power factor, scaling factors).
- **schema_version** — Tracks the current database schema version
  for lightweight migration support.

All tables use SQLAlchemy 2.0 ``DeclarativeBase`` with ``Mapped``
type annotations and ``mapped_column()`` column definitions.

Usage::

    from sqlalchemy import create_engine
    from src.db.schema import Base, GeneratorAttributes

    engine = create_engine("sqlite:///data/grid_attributes.db")
    Base.metadata.create_all(engine)
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 declarative base for all grid attribute tables."""

    pass


class GeneratorAttributes(Base):
    """Mutable attributes for a generator (発電所).

    Stores cost parameters, operational limits, and storage
    characteristics that may be updated independently of the static
    network topology extracted from GIS sources.

    Mirrors the editable subset of fields from
    :class:`src.model.generator.Generator`, enabling database-backed
    attribute overrides without rebuilding the full network.

    Attributes:
        id: Generator identifier matching ``Generator.id``.
        fuel_type: Fuel type string (e.g. ``'coal'``, ``'lng'``).
        capacity_mw: Rated generation capacity in megawatts.
        p_min_mw: Minimum generation output in megawatts.
        vm_pu: Voltage magnitude setpoint in per-unit.
        status: Operational status (e.g. ``'active'``).
        startup_cost: Start-up cost (currency units).
        shutdown_cost: Shut-down cost (currency units).
        min_up_time_h: Minimum on-time once started (hours).
        min_down_time_h: Minimum off-time once shut down (hours).
        ramp_up_mw_per_h: Maximum ramp-up rate (MW/h).
        ramp_down_mw_per_h: Maximum ramp-down rate (MW/h).
        fuel_cost_per_mwh: Fuel cost per MWh (currency units).
        labor_cost_per_h: Labor cost per hour of operation.
        no_load_cost: Fixed on-state cost regardless of output.
        storage_capacity_mwh: Energy storage capacity (MWh).
        charge_rate_mw: Maximum charge rate (MW).
        discharge_rate_mw: Maximum discharge rate (MW).
        charge_efficiency: Round-trip charge efficiency (0–1].
        discharge_efficiency: Round-trip discharge efficiency (0–1].
        updated_at: Timestamp of last modification (UTC).
    """

    __tablename__ = "generator_attributes"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    fuel_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    capacity_mw: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    p_min_mw: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vm_pu: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Unit commitment cost parameters
    startup_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    shutdown_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    min_up_time_h: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    min_down_time_h: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ramp_up_mw_per_h: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    ramp_down_mw_per_h: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    fuel_cost_per_mwh: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    labor_cost_per_h: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    no_load_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Storage parameters
    storage_capacity_mwh: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    charge_rate_mw: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    discharge_rate_mw: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    charge_efficiency: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    discharge_efficiency: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )

    # Metadata
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"GeneratorAttributes(id={self.id!r}, fuel_type={self.fuel_type!r}, "
            f"capacity_mw={self.capacity_mw})"
        )


class SubstationAttributes(Base):
    """Mutable attributes for a substation (変電所) / bus node.

    Stores voltage control parameters, tap ratios, and zone assignments
    that may be updated independently of the static GIS-sourced topology.

    Attributes:
        id: Substation identifier matching ``Substation.id``.
        voltage_setpoint_pu: Target voltage magnitude in per-unit.
        tap_ratio: Transformer tap ratio (1.0 = nominal).
        tap_min: Minimum tap ratio.
        tap_max: Maximum tap ratio.
        tap_step_percent: Tap step size as a percentage.
        zone: Zone assignment for multi-area studies.
        grid_class: Grid hierarchy classification
            (e.g. ``'backbone'``, ``'regional'``).
        status: Operational status (e.g. ``'active'``).
        updated_at: Timestamp of last modification (UTC).
    """

    __tablename__ = "substation_attributes"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    voltage_setpoint_pu: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    tap_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tap_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tap_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tap_step_percent: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    zone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    grid_class: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Metadata
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"SubstationAttributes(id={self.id!r}, "
            f"voltage_setpoint_pu={self.voltage_setpoint_pu}, "
            f"zone={self.zone!r})"
        )


class LoadAttributes(Base):
    """Mutable attributes for a load element.

    Stores load model classification, power factors, and scaling factors
    that may be updated independently of the static network topology.

    Attributes:
        id: Load identifier (e.g. ``'{region}_load_{bus_id}'``).
        bus_id: Associated bus/substation identifier.
        load_model: Load model type
            (e.g. ``'constant_power'``, ``'constant_impedance'``,
            ``'zip'``).
        p_mw: Active power demand in megawatts.
        q_mvar: Reactive power demand in megavar.
        power_factor: Power factor (cos phi) in (0, 1].
        scaling_factor: Multiplier applied to base demand (default 1.0).
        in_service: Whether this load is active.
        source: Data source identifier for traceability.
        updated_at: Timestamp of last modification (UTC).
    """

    __tablename__ = "load_attributes"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    bus_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    load_model: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    p_mw: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    q_mvar: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    power_factor: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    scaling_factor: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    in_service: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, default=1
    )
    source: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # Metadata
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"LoadAttributes(id={self.id!r}, bus_id={self.bus_id!r}, "
            f"p_mw={self.p_mw}, load_model={self.load_model!r})"
        )


class Snapshot(Base):
    """A fetch/ingest event for one (region, layer) — R-layer provenance.

    Every refresh of raw data registers a snapshot row so the database
    records *when* and *from what source* each raw feature set came.
    See ``docs/DB_ARCHITECTURE.md`` (R layer).

    Attributes:
        snapshot_id: Unique id, e.g. ``'2026-06-08T12:00Z_okinawa_plants'``.
        region: Region name (``hokkaido`` … ``okinawa``).
        layer: ``substations`` | ``lines`` | ``plants``.
        fetched_at: ISO timestamp of the fetch/ingest.
        source: ``'overpass'`` for real fetches, ``'ingest-legacy'`` for
            the one-time decomposition of the pre-DB enriched GeoJSON.
        feature_count: Number of features in this snapshot.
    """

    __tablename__ = "snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    region: Mapped[str] = mapped_column(String(32), nullable=False)
    layer: Mapped[str] = mapped_column(String(32), nullable=False)
    fetched_at: Mapped[str] = mapped_column(String(40), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    feature_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    collection_meta: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc=(
            "JSON of the FeatureCollection's top-level keys other than "
            "'features' (e.g. name, crs) so exports reproduce the file "
            "envelope faithfully."
        ),
    )

    def __repr__(self) -> str:
        return (
            f"Snapshot(id={self.snapshot_id!r}, source={self.source!r}, "
            f"features={self.feature_count})"
        )


class RawFeature(Base):
    """One raw OSM feature — R layer (written only by fetch/ingest).

    ``tags`` holds the feature's properties verbatim (minus the fields
    extracted into :class:`Enrichment` rows at legacy ingest); curated
    values must never be written here.  ``feature_key`` is the stable
    identity: ``n/w/r{osm_id}`` when the OSM id is known, otherwise a
    provisional ``g:{sha1[:12]}`` of the normalized geometry (see
    ``src/db/geojson_sync.py:feature_key_for``).

    The primary key includes ``region`` because the per-region source
    files may legitimately contain the same physical element on both
    sides of a region boundary; faithful per-region round-trip wins
    until the osm-key migration enables cross-region dedup analysis.

    Attributes:
        layer: ``substations`` | ``lines`` | ``plants``.
        region: Region name.
        feature_key: Stable feature identity (see above).
        osm_type: ``node`` | ``way`` | ``relation`` when known.
        osm_id: OSM element id when known.
        tags: JSON text of raw properties.
        geometry: JSON text of the GeoJSON geometry (verbatim).
        seq: Original position in the source file (stable export order).
        first_seen / last_seen: ISO timestamps across snapshots.
        active: 1 while present in the latest snapshot, 0 once vanished.
        snapshot_id: Snapshot that last touched this row.
    """

    __tablename__ = "raw_features"

    layer: Mapped[str] = mapped_column(String(32), primary_key=True)
    region: Mapped[str] = mapped_column(String(32), primary_key=True)
    feature_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    osm_type: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    osm_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tags: Mapped[str] = mapped_column(Text, nullable=False)
    geometry: Mapped[str] = mapped_column(Text, nullable=False)
    seq: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    first_seen: Mapped[str] = mapped_column(String(40), nullable=False)
    last_seen: Mapped[str] = mapped_column(String(40), nullable=False)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    snapshot_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"RawFeature({self.layer}/{self.region}/{self.feature_key}, "
            f"osm={self.osm_type}/{self.osm_id})"
        )


class Enrichment(Base):
    """One curated field value — C layer (enrich/audit/manual writes).

    Raw features are never mutated; every completion, correction or
    external match lands here keyed by the feature's stable identity,
    so re-fetching OSM re-applies curation automatically.

    ``source`` values are taken verbatim from the legacy markers
    (``endpoint_matching`` / ``nominatim`` / ``geocode_promotion`` /
    ``p03`` / ``overpass`` / ``jrp_lite`` / ``legacy_marker``) plus the
    new ``manual`` and ``audit_fix``.  Resolution priority lives in
    ``src/db/geojson_sync.py:SOURCE_PRIORITY``.

    The ``source`` column is only a short provenance *label*.  The
    citable provenance an owner can verify — the ``source_url`` and the
    ``quote`` (verbatim excerpt that backs the value) — lives in the four
    nullable columns added in migration v5 (Phase 1-B 出典伝播).  They
    carry the same captation-prevention contract as the
    ``*_provenance.py`` source DBs (URL + quote or the value is REJECTed
    upstream); here they are nullable so legacy marker rows without a
    citation remain valid.  They are *not* part of the primary key, so a
    citation never forks a row away from its ``(…, field, source)`` slot.

    Attributes:
        layer / region / feature_key: Identity of the enriched feature.
        field: Property name (``name``, ``operator``, ``fuel_type``, …;
            ``_``-prefixed legacy meta fields are stored verbatim).
        value: JSON-encoded value.
        source: Provenance label (see above).
        confidence: Optional 0–1 confidence score.
        run_id: Optional id of the enrichment run that wrote this.
        source_url: Optional citable http(s) URL backing the value.
        quote: Optional verbatim excerpt from the source that supports
            the value (the human-verifiable evidence).
        retrieved_at: Optional ISO date the source was retrieved.
        collected_by: Optional collector id (model name or person).
        updated_at: ISO timestamp of last update.
    """

    __tablename__ = "enrichments"

    layer: Mapped[str] = mapped_column(String(32), primary_key=True)
    region: Mapped[str] = mapped_column(String(32), primary_key=True)
    feature_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    field: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    run_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Citable provenance (migration v5, Phase 1-B) — nullable so legacy
    # marker rows stay valid; never part of the PK.
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    quote: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retrieved_at: Mapped[Optional[str]] = mapped_column(
        String(40), nullable=True
    )
    collected_by: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )

    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)

    def __repr__(self) -> str:
        return (
            f"Enrichment({self.layer}/{self.region}/{self.feature_key}."
            f"{self.field} <- {self.source})"
        )


class MeasuredLineStat(Base):
    """One measured-flow aggregate per disclosure corridor — the
    calibration layer (written only by ``scripts/db/calibrate.py``).

    The raw disclosure CSVs (TEPCO jisseki etc.) are NOT redistributable
    and live outside git in ``data/external/``; the DB keeps only the
    derived per-corridor aggregates with source citation. Consumers
    (boundary injection, the flow validator's ``--from-db`` mode) read
    these rows first and fall back to parsing the CSVs.

    Attributes:
        region: Model region the disclosure covers (``tokyo``).
        line_key: Normalised line name (``external_tepco._norm`` of the
            disclosure column) — the same key the flow matcher uses.
        kv_floor: Class-band floor in kV (200 trunk / 140 / 60); the
            band assignment mirrors the matcher's trunk-first rule.
        source: Disclosure family (``tepco_jisseki``).
        q50_mw / p95_mw: Median and 0.95 quantile of |flow| over the
            window (circuit groups summed per timestamp, larger line
            end taken — see ``external_tepco.tepco_flow_stats``).
        window: Data window as ``<first>..<last>`` timestamps.
        updated_at: ISO timestamp of the calibrate run.
    """

    __tablename__ = "measured_line_stats"

    region: Mapped[str] = mapped_column(String(32), primary_key=True)
    line_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    kv_floor: Mapped[float] = mapped_column(Float, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    q50_mw: Mapped[float] = mapped_column(Float, nullable=False)
    p95_mw: Mapped[float] = mapped_column(Float, nullable=False)
    window: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)

    def __repr__(self) -> str:
        return (
            f"MeasuredLineStat({self.region}/{self.line_key}"
            f"@{self.kv_floor:g}kV q50={self.q50_mw:.0f})"
        )


class MeasuredBusLoad(Base):
    """One measured per-substation demand — M3's placement truth
    (written only by ``scripts/db/calibrate.py``).

    Source instrument (``method``):

    - ``busbar``: |sum of the sub's 母線 columns| in the per-prefecture
      66 kV disclosure — at a distribution substation the busbar
      through-power is the yard's offtake (primary, ~1,200 subs);
    - ``terminal_line``: single-attachment radial ends' line inflow
      (secondary; small population and prone to metering-side false
      positives at FC/EHV yards).

    Attributes:
        region / sub_key: Normalised substation name key.
        source: Disclosure family (``tepco_jisseki``).
        method: Instrument as above.
        q50_mw / p95_mw: Median and 0.95 quantile of |MW|.
        n_cols: Number of disclosure columns aggregated.
        window: Data window as ``<first>..<last>`` timestamps.
        updated_at: ISO timestamp of the calibrate run.
    """

    __tablename__ = "measured_bus_loads"

    region: Mapped[str] = mapped_column(String(32), primary_key=True)
    sub_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    q50_mw: Mapped[float] = mapped_column(Float, nullable=False)
    p95_mw: Mapped[float] = mapped_column(Float, nullable=False)
    n_cols: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    window: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)

    def __repr__(self) -> str:
        return (
            f"MeasuredBusLoad({self.region}/{self.sub_key} "
            f"q50={self.q50_mw:.1f} via {self.method})"
        )


class UCScenario(Base):
    """UC scenario definition — machine-queryable mirror of the YAML.

    The git-tracked ``config/uc_scenarios/{scenario_id}.yaml`` remains the
    source of truth (owner decision 2026-06-11: generator selection is
    scenario-dependent, so scenarios are first-class and DB-backed).
    This table is written by ``scripts/db/ingest_uc_scenarios.py`` so that
    downstream tooling can resolve scenarios without touching the repo
    config tree.

    Attributes:
        scenario_id: Scenario name (e.g. ``'fy2023'``).
        fiscal_year: Fiscal year of the snapshot, when applicable.
        description: Human-readable description.
        config_json: Full scenario definition as JSON (verbatim mirror of
            the YAML content).
        updated_at: ISO timestamp of last ingest.
    """

    __tablename__ = "uc_scenarios"

    scenario_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    fiscal_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    config_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)

    def __repr__(self) -> str:
        return (
            f"UCScenario(scenario_id={self.scenario_id!r}, "
            f"fiscal_year={self.fiscal_year})"
        )


class UCScenarioGenerator(Base):
    """Per-generator scenario entry (availability / storage / capacity).

    Row-level mirror of the scenario reference lists so generator selection
    can be queried per scenario:

    - ``kind='nuclear_status'``: operational reactor sites for the snapshot
      (entries from ``data/reference/nuclear_status.yaml``)
    - ``kind='pumped_storage'``: pumped-storage plants with storage hours
      (``data/reference/pumped_storage.yaml``)
    - ``kind='capacity_patch'``: individual capacity corrections for
      capacity-missing plants (``data/reference/capacity_patches.yaml``)

    Attributes:
        scenario_id: Owning scenario.
        kind: Entry kind (see above).
        gen_key: Stable key within the kind (plant name / match string).
        payload_json: Full entry as JSON (capacity_mw, region, note, …).
        updated_at: ISO timestamp of last ingest.
    """

    __tablename__ = "uc_scenario_generators"

    scenario_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    gen_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)

    def __repr__(self) -> str:
        return (
            f"UCScenarioGenerator({self.scenario_id}/{self.kind}/"
            f"{self.gen_key})"
        )


class UCRun(Base):
    """UC execution history — machine-queryable index of run results.

    The report JSON under ``docs/reports/`` remains the source of truth
    (same owner decision as scenarios: DB mirrors, files are canonical).
    One row per produced report; re-running upserts by ``report_path`` so
    the index never duplicates. Written best-effort by
    :mod:`src.uc.run_recorder` — absence of the DB never fails a run.

    Attributes:
        report_path: Repo-relative path of the canonical report JSON
            (primary key — one report, one row).
        kind: Run kind (``'benchmark' | 'annual' | 'pf_link' |
            'pf_national'``).
        run_date: ISO date of the run.
        git_head: Short commit hash the run was produced at.
        scenario_id: UC scenario name (e.g. ``'fy2023r2'``).
        scenario_sha256: Scenario definition fingerprint (reproducibility
            chain, when recorded).
        demand_profile_sha: Fetched measured-demand fingerprint (when the
            scenario resolves a profile_ref).
        status: Solver status (``'Optimal'`` …) or PF outcome.
        total_cost_jpy: Objective value for solve runs.
        solve_time_s: Wall-clock solve time.
        l1_total_pp: L1 deviation vs reference fuel shares (pp), when
            evaluated.
        summary_json: Compact KPI summary (JSON), shape depends on kind.
        created_at: ISO timestamp of (last) recording.
    """

    __tablename__ = "uc_runs"

    report_path: Mapped[str] = mapped_column(String(256), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    run_date: Mapped[str] = mapped_column(String(10), nullable=False)
    git_head: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    scenario_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    scenario_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    demand_profile_sha: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    total_cost_jpy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    solve_time_s: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    l1_total_pp: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    summary_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)

    def __repr__(self) -> str:
        return (
            f"UCRun({self.kind}/{self.scenario_id} {self.run_date} "
            f"{self.status} -> {self.report_path})"
        )


class MeasuredAreaStat(Base):
    """One OCCTO-published area/interconnector aggregate — written only
    by ``scripts/db/calibrate.py --occto`` (M10 reconciliation layer).

    ``metric``: ``demand_mw`` (area demand) or ``ic_flow_mw`` (planned
    interconnector flow; ``signed_q50_mw`` keeps the OCCTO forward-
    direction sign). Raw CSVs stay in data/external/occto (gitignored,
    ~14-month API retention); the DB keeps citable aggregates.
    """

    __tablename__ = "measured_area_stats"

    area: Mapped[str] = mapped_column(String(64), primary_key=True)
    metric: Mapped[str] = mapped_column(String(32), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    q50_mw: Mapped[float] = mapped_column(Float, nullable=False)
    p95_mw: Mapped[float] = mapped_column(Float, nullable=False)
    signed_q50_mw: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    window: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)

    def __repr__(self) -> str:
        return f"MeasuredAreaStat({self.area}/{self.metric} q50={self.q50_mw:.0f})"


class SchemaVersion(Base):
    """Schema version tracking for lightweight migrations.

    Each row records a migration that has been applied to the database.
    The highest ``version`` number represents the current schema state.

    Attributes:
        version: Monotonically increasing schema version number.
        description: Human-readable description of the migration.
        applied_at: Timestamp when the migration was applied (UTC).
    """

    __tablename__ = "schema_version"

    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    applied_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"SchemaVersion(version={self.version}, "
            f"description={self.description!r})"
        )
