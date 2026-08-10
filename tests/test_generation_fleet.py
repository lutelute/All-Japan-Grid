"""発電フリートの合成度合いと番兵値のゲート。

2026-08-09 の監査で分かったこと:
  - モデル総容量 477GW の 48.3% が燃料別既定値による合成
  - `capacity_mw = -1` の番兵値が 3,936 件（九州・沖縄は全件）
  - 太陽光の既定値 10MW は実容量中央値 0.10MW の 100 倍で、170GW を水増ししている

いずれもモデルを壊してはいない（潮流本体は `cap <= 0` を既定値に置換する）が、
**集計を書く側が知らないと踏む**。状況が変わったら気づけるよう固定する。
"""
from __future__ import annotations

import glob
import json
import statistics as st
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLANTS = sorted(glob.glob(str(ROOT / "data" / "*_plants.geojson")))

# 潮流本体（scripts/run_full_powerflow_from_db.py）と揃えること
DEFAULT_CAP = {"nuclear": 1000.0, "coal": 600.0, "gas": 400.0, "oil": 300.0,
               "hydro": 50.0, "solar": 0.10, "wind": 10.0, "biomass": 20.0}

pytestmark = pytest.mark.skipif(not PLANTS, reason="plants geojson が無い")


def _iter_plants():
    for f in PLANTS:
        reg = Path(f).name.replace("_plants.geojson", "")
        for ft in json.load(open(f)).get("features", []):
            p = ft["properties"]
            fuel = str(p.get("fuel_type") or p.get("plant:source") or "unknown").lower()
            try:
                cap = float(p.get("capacity_mw"))
            except (TypeError, ValueError):
                cap = None
            yield reg, fuel, cap


def test_default_cap_matches_powerflow():
    """既定値が潮流本体とずれていないか。ずれると監査の数字が嘘になる。"""
    src = (ROOT / "scripts" / "run_full_powerflow_from_db.py").read_text(encoding="utf-8")
    for fuel, v in DEFAULT_CAP.items():
        assert f'"{fuel}": {v}' in src, f"{fuel} の既定値が潮流本体と不一致"


def test_negative_capacity_is_a_sentinel_not_a_value():
    """負の容量は物理的にありえない。番兵値として使われていることを固定する。"""
    negs = [(r, f, c) for r, f, c in _iter_plants() if c is not None and c < 0]
    assert negs, "番兵値が無くなった。null 化されたなら本テストと監査を更新すること"
    vals = {c for _, _, c in negs}
    assert vals == {-1.0}, f"番兵値が -1 以外になった: {sorted(vals)[:5]}"


def test_powerflow_does_not_ingest_negative_capacity():
    """潮流本体が非正の容量を既定値に置換していること（ここが緩むとモデルが壊れる）。"""
    src = (ROOT / "scripts" / "run_full_powerflow_from_db.py").read_text(encoding="utf-8")
    assert "cap is None or cap <= 0" in src, \
        "非正容量のガードが消えた。負の発電出力がモデルに入る"


def test_solar_default_tracks_the_observed_median():
    """太陽光の既定値が実容量の中央値に張り付いていること（介入#25・2026-08-10 是正）。

    **かつてこのテストは逆を主張していた** — 既定 10MW が中央値 0.10MW の 100 倍
    乖離している事実を固定し、「直した人が監査レポートを更新する動線」として働いていた。
    2026-08-10 に既定を 0.10 へ是正したので、いまは**中央値から離れたら失敗する**
    向きへ入れ替える。10MW へ戻すとここで落ちる。

    経緯: 10MW は太陽光を 180GW＝実績ピークの 318% に膨らませ、`balance_by_zone` が
    容量比例で配るためゾーン内の空間配分そのものを歪めていた（夕方17時の断面で
    east 注入の 45.9% が太陽光ノード＝17時の太陽光出力はゼロ）。合成率 48.3%→20.1%。
    """
    obs = [c for _, f, c in _iter_plants() if "solar" in f and c is not None and c > 0]
    assert obs, "実容量の付いた太陽光が無い"
    med = st.median(obs)
    ratio = DEFAULT_CAP["solar"] / med
    assert 0.2 <= ratio <= 5.0, (
        f"太陽光の既定値 {DEFAULT_CAP['solar']}MW が実容量中央値 {med:.3f}MW から "
        f"{ratio:.1f} 倍ずれている。既定値を戻したか、実容量の分布が動いた。"
        "どちらであれ generation_fleet_audit を取り直して記述を更新すること")


def test_synthetic_share_is_disclosed_not_hidden():
    """合成容量の割合が監査レポートに開示されていること。"""
    reports = sorted((ROOT / "docs" / "reports").glob("generation_fleet_audit_*.json"))
    if not reports:
        pytest.skip("監査レポート未生成")
    d = json.load(open(reports[-1]))
    assert 0 < d["synth_share"] < 1, "合成割合が記録されていない"
    assert d["n_negative_sentinel"] > 0, "番兵値の件数が記録されていない"
    # 100% 合成のエリア（実容量ゼロ）は特に開示が要る
    all_synth = [r["region"] for r in d["regions"] if r["synth_share"] == 1.0]
    assert "kyushu" in all_synth and "okinawa" in all_synth, \
        f"実容量ゼロのエリアが変わった: {all_synth}（監査の記述を更新すること）"
