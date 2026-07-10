"""Phase 1-B 出典伝播の golden test — 出典が下流(CIM/DB)まで貫通することの回帰保証.

ROADMAP_ASSET.md:68 が要求する「出典が CIM に乗る golden test」の第一弾。
捏造防止規約(値には必ず URL+quote)を **表示だけでなく CIM/DB まで** 届ける第一段:

- 発電所 feature の出典付き容量(capacity_mw_sourced + capacity_source_url)が
  CGMES(Level-1 EQ)の GeneratingUnit.ratedP と IdentifiedObject.description=URL
  として現れること。
- Enrichment(C層)に出典4列を足す migration v5 が、fresh DB(create_all 済)でも
  pre-v5 DB(ALTER 必要)でも冪等に効くこと。
- 発電容量/変圧器の2系統が同一の汎用バリデータ(scripts/provenance)を通ること。
"""
import json

from sqlalchemy import create_engine, inspect, text

from src.cim.exporter import export_region
from src.db.migrations import MIGRATIONS, MigrationManager


# ======================================================================
# CIM: 出典付き容量とURLが CGMES に現れる(golden)
# ======================================================================


def _write_plants(data_dir, region, props):
    """1発電所だけの plants geojson を書いて export_region に食わせる。"""
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": props,
                "geometry": {"type": "Point", "coordinates": [130.0, 31.0]},
            }
        ],
    }
    path = data_dir / f"{region}_plants.geojson"
    path.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")


def test_cim_export_carries_sourced_capacity_and_url(tmp_path):
    """出典付き容量(890)がCGMESに乗り、URLが description に貫通する。

    生の capacity_mw(500)ではなく capacity_mw_sourced(890)が ratedP になり、
    出典URLが IdentifiedObject.description として XML に現れる。
    """
    region = "okinawa"
    data_dir = tmp_path / "data"
    out_dir = tmp_path / "cim"
    data_dir.mkdir()
    _write_plants(
        data_dir,
        region,
        {
            "name": "テスト原子力発電所",
            "fuel_type": "nuclear",
            "capacity_mw": 500,  # 生のOSM/P03値(過小)
            "capacity_mw_sourced": 890.0,  # 出典付きの一次資料値
            "capacity_source_url": "https://example.com/plant",
            "capacity_source_type": "official",
            "capacity_source_conf": "high",
        },
    )

    summary = export_region(region, str(data_dir), str(out_dir))
    eq = (out_dir / f"{region}_EQ.xml").read_text(encoding="utf-8")

    assert summary["counts"]["plants"] == 1
    # 出典値(890)が容量として乗る — 生の500ではない
    assert "<cim:GeneratingUnit.ratedP>890.0</cim:GeneratingUnit.ratedP>" in eq
    assert "<cim:GeneratingUnit.ratedP>500" not in eq
    # 出典URLが description として貫通
    assert (
        "<cim:IdentifiedObject.description>https://example.com/plant"
        "</cim:IdentifiedObject.description>" in eq
    )
    # 回転機の定格容量も出典値に追従(nuclear は SynchronousMachine を持つ)
    assert "<cim:RotatingMachine.ratedS>890.0</cim:RotatingMachine.ratedS>" in eq


def test_cim_export_without_source_falls_back_and_no_description(tmp_path):
    """出典が無ければ従来通り capacity_mw を使い、description は付かない(退行防止)。"""
    region = "okinawa"
    data_dir = tmp_path / "data"
    out_dir = tmp_path / "cim"
    data_dir.mkdir()
    _write_plants(
        data_dir,
        region,
        {"name": "無出典火力", "fuel_type": "lng", "capacity_mw": 500},
    )

    export_region(region, str(data_dir), str(out_dir))
    eq = (out_dir / f"{region}_EQ.xml").read_text(encoding="utf-8")

    assert "<cim:GeneratingUnit.ratedP>500</cim:GeneratingUnit.ratedP>" in eq
    assert "IdentifiedObject.description" not in eq


# ======================================================================
# migration v5: Enrichment 出典列(fresh / pre-v5 の両方で冪等)
# ======================================================================


def test_migration_v5_registered():
    """v5 が MIGRATIONS に登録されている。"""
    assert any(m.version == 5 for m in MIGRATIONS)


def test_fresh_db_has_enrichment_source_columns():
    """fresh :memory: DB は ensure_schema 後、enrichments に出典4列を持つ。

    create_all が ORM から4列を作った上で v5 の ADD COLUMN が冪等スキップされ、
    version が5に到達すること(create_all と ALTER の共存=冪等性の実証)。
    """
    engine = create_engine("sqlite:///:memory:")
    version = MigrationManager(engine).ensure_schema()
    assert version >= 5

    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("enrichments")}
    for c in ("source_url", "quote", "retrieved_at", "collected_by"):
        assert c in cols, f"enrichments に {c} 列が無い"

    # 出典4列は PK ではない(citation が行を分岐させない)
    pk_cols = set(
        inspector.get_pk_constraint("enrichments")["constrained_columns"]
    )
    for c in ("source_url", "quote", "retrieved_at", "collected_by"):
        assert c not in pk_cols


def test_migration_v5_adds_columns_to_pre_v5_db():
    """pre-v5 の enrichments(出典列なし)に v5 が ALTER で4列を追加する。"""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE enrichments ("
            "layer TEXT, region TEXT, feature_key TEXT, field TEXT, "
            "source TEXT, value TEXT, confidence REAL, run_id TEXT, "
            "updated_at TEXT, "
            "PRIMARY KEY (layer, region, feature_key, field, source))"
        ))
        conn.execute(text(
            "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, "
            "description TEXT, applied_at TIMESTAMP)"
        ))
        conn.execute(text(
            "INSERT INTO schema_version (version, description) "
            "VALUES (4, 'pre-v5 fixture')"
        ))

    manager = MigrationManager(engine)
    before = {c["name"] for c in inspect(engine).get_columns("enrichments")}
    assert "source_url" not in before  # 事前条件: 列は無い

    v5 = next(m for m in MIGRATIONS if m.version == 5)
    manager._apply(v5)

    cols = {c["name"] for c in inspect(engine).get_columns("enrichments")}
    for c in ("source_url", "quote", "retrieved_at", "collected_by"):
        assert c in cols
    assert manager.get_current_version() == 5


def test_migration_v5_apply_is_idempotent():
    """v5 を2回当てても(列が既にあっても)エラーにならず版のみ進む。"""
    engine = create_engine("sqlite:///:memory:")
    manager = MigrationManager(engine)
    manager.ensure_schema()  # ここで v5 まで到達(列は create_all 済)

    v5 = next(m for m in MIGRATIONS if m.version == 5)
    manager._apply(v5)  # 再適用: ADD COLUMN は冪等スキップされる(例外なし)

    cols = {c["name"] for c in inspect(engine).get_columns("enrichments")}
    assert {"source_url", "quote", "retrieved_at", "collected_by"} <= cols


def test_enrichment_source_columns_persist_value():
    """出典4列に実際に URL/quote を書いて読み戻せる(nullable・PK外)。"""
    from src.db.schema import Enrichment
    from src.db.grid_db import GridDatabase

    db = GridDatabase(":memory:")
    now = "2026-07-10T00:00:00Z"
    with db.session_factory() as s:
        s.add(Enrichment(
            layer="plants", region="okinawa", feature_key="w123",
            field="capacity_mw", source="manual", value="890.0",
            source_url="https://example.com/plant",
            quote="定格出力 89万kW", retrieved_at="2026-07-10",
            collected_by="test", updated_at=now,
        ))
        s.commit()
    with db.session_factory() as s:
        row = s.get(Enrichment, {
            "layer": "plants", "region": "okinawa", "feature_key": "w123",
            "field": "capacity_mw", "source": "manual"})
        assert row.source_url == "https://example.com/plant"
        assert row.quote == "定格出力 89万kW"
        assert row.retrieved_at == "2026-07-10"
        assert row.collected_by == "test"


# ======================================================================
# 汎用バリデータ: 2系統が同一の捏造防止規約を通ること
# ======================================================================


def test_both_provenance_dbs_share_the_validator():
    """発電容量/変圧器の validate_record が同一の scripts.provenance.validate。

    URL欠落/非URLは両系統で同じ理由(hyphen区切り)で REJECT され、捏造防止の核心が
    1実装に一本化されていることを行動で確認する。
    """
    from scripts.capacity_provenance import validate_record as v_cap
    from scripts.transformer_provenance import validate_record as v_tr

    cap_good = {
        "plant_key": "p03:test", "name": "テスト発電所", "field": "capacity_mw",
        "value": 1780, "unit": "MW", "source_type": "official",
        "source_url": "https://example.com/p", "source_title": "公式",
        "quote": "89万kW×2基", "retrieved_at": "2026-06-20",
        "confidence": "high", "collected_by": "test",
    }
    tr_good = {
        "site_key": "kansai:テスト変電所", "name": "テスト変電所",
        "field": "sn_mva", "value": 750, "unit": "MVA",
        "source_type": "official", "source_url": "https://example.com/x",
        "source_title": "公式", "quote": "各 750MVA",
        "retrieved_at": "2026-07-02", "confidence": "high",
        "collected_by": "test", "status": "existing",
    }
    assert v_cap(cap_good)[0]
    assert v_tr(tr_good)[0]

    # URL欠落 → 両系統とも同一の missing-source_url で REJECT
    assert v_cap({**cap_good, "source_url": ""}) == (False, ["missing-source_url"])
    assert v_tr({**tr_good, "source_url": ""}) == (False, ["missing-source_url"])
    # 非URL(捏造) → 両系統とも source_url-not-http
    assert "source_url-not-http" in v_cap({**cap_good, "source_url": "記憶"})[1]
    assert "source_url-not-http" in v_tr({**tr_good, "source_url": "記憶"})[1]
