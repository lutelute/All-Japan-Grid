"""発電機の接続規則（介入#24 `--gen-attach`）のゲート。

2026-08-09 の組み合わせ探索で、接続規則が過負荷を最も強く動かす軸だと分かった
（east cap で過負荷 603→551、太陽光の是正と併せて 303）。規則を本番へ移したので、

  1. 既定 `nearest` が**従来と完全に同じ**であること（無効化手段が本当に効くこと）
  2. 各規則が意図どおりバスを選ぶこと
  3. what-if が本番へ**委譲**していること（実装の二重化＝過去2回誤った原因を禁じる）

を固定する。実データを使わない合成系統なので速い。
"""
from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PF = ROOT / "scripts" / "run_full_powerflow_from_db.py"
WGV = ROOT / "scripts" / "capacity" / "whatif_gen_voltage.py"

pytestmark = pytest.mark.skipif(not PF.exists(), reason="潮流本体が無い")


def _pf():
    spec = importlib.util.spec_from_file_location("pf_under_test", PF)
    m = importlib.util.module_from_spec(spec)
    sys.modules["pf_under_test"] = m
    spec.loader.exec_module(m)
    return m


def _net():
    """66kV が近く・500kV が遠い、実系統の縮図。

    bus0 66kV（発電所から 1km）／bus1 500kV（12km）を幹線で支える。
    最寄り規則ならどんな大型機も bus0 に載る。
    """
    import pandapower as pp
    net = pp.create_empty_network()
    b0 = pp.create_bus(net, vn_kv=66.0, name="near66")
    b1 = pp.create_bus(net, vn_kv=500.0, name="far500")
    b2 = pp.create_bus(net, vn_kv=66.0, name="tail66")
    b3 = pp.create_bus(net, vn_kv=500.0, name="tail500")
    pp.create_line_from_parameters(net, b0, b2, length_km=5.0, r_ohm_per_km=0.1,
                                   x_ohm_per_km=0.3, c_nf_per_km=0.0, max_i_ka=0.6)
    pp.create_line_from_parameters(net, b1, b3, length_km=5.0, r_ohm_per_km=0.02,
                                   x_ohm_per_km=0.25, c_nf_per_km=0.0, max_i_ka=4.0)
    return net, b0, b1


def _nodes_bus_of(b0, b1):
    """発電所(35.00, 139.00) から bus0 は約 1km、bus1 は約 12km。"""
    nodes = {"n0": {"lat": 35.009, "lon": 139.0, "sub": 1},
             "n1": {"lat": 35.108, "lon": 139.0, "sub": 1}}
    return nodes, {"n0": b0, "n1": b1}


def _plant(mw):
    return {"type": "Feature",
            "geometry": {"type": "Point", "coordinates": [139.0, 35.0]},
            "properties": {"osm_id": 1, "name": "試験火力", "fuel_type": "gas",
                           "capacity_mw": mw}}


def _attach(pf, monkeypatch, mode, mw):
    """島の発電所リストを差し替えて 1 機だけ繋ぐ。"""
    import json as _json
    net, b0, b1 = _net()
    nodes, bus_of = _nodes_bus_of(b0, b1)
    monkeypatch.setattr(pf, "ISLAND_OF", {"testregion": ("testisland", 50.0)},
                        raising=False)
    monkeypatch.setattr(pf.os.path, "exists", lambda p: "testregion_plants" in str(p))
    payload = _json.dumps({"features": [_plant(mw)]})

    import io
    real_open = open

    def fake_open(path, *a, **k):
        if "testregion_plants" in str(path):
            return io.StringIO(payload)
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", fake_open)
    # use_sourced=False — 合成系統に出典付き容量は関係ない。**そして本物のD層を
    # 引かせない**: このヘルパーは `os.path.exists` をグローバルに差し替えているので、
    # その最中に索引を引くと 0 件がキャッシュに焼き付き、後続テストへ漏れる
    # （2026-08-10 に実際に 2 本落とした）。
    info = pf.attach_generators(net, bus_of, nodes, "testisland", territory=False,
                                attach_mode=mode, stats=True, use_sourced=False)
    monkeypatch.setattr("builtins.open", real_open)
    kv = float(net.bus.at[int(net.gen.at[0, "bus"]), "vn_kv"]) if len(net.gen) else None
    return info, kv


def test_nearest_is_the_default_and_picks_the_close_66kv(monkeypatch):
    """既定は従来どおり最寄り — 3,600MW でも 1km 先の 66kV に載る（これが真因A）。"""
    pytest.importorskip("pandapower")
    pf = _pf()
    info, kv = _attach(pf, monkeypatch, "nearest", 3600.0)
    assert info["n_gen"] == 1 and kv == 66.0
    assert info["n_moved"] == 0, "既定モードで繋ぎ替えが起きてはいけない"


def test_cap_moves_a_large_unit_to_the_bus_that_can_receive_it(monkeypatch):
    """cap: 受電容量が出力に足りない 66kV を避け、12km 先の 500kV を選ぶ。"""
    pytest.importorskip("pandapower")
    pf = _pf()
    info, kv = _attach(pf, monkeypatch, "cap", 3600.0)
    assert kv == 500.0, "受電容量で選べば大型機は 66kV に載らない"
    assert info["n_moved"] == 1 and info["moved_mw"] == pytest.approx(3600.0)


def test_cap_leaves_a_small_unit_where_it_was(monkeypatch):
    """cap: 66kV が受けきれる小型機は動かさない（外科的であること）。"""
    pytest.importorskip("pandapower")
    pf = _pf()
    info, kv = _attach(pf, monkeypatch, "cap", 5.0)
    assert kv == 66.0 and info["n_moved"] == 0


def test_kvfit_uses_the_ladder_measured_from_the_model(monkeypatch):
    """kvfit: 階級の梯子はモデル自身の導体定数から測る（外部の表を持ち込まない）。"""
    pytest.importorskip("pandapower")
    pf = _pf()
    info, kv = _attach(pf, monkeypatch, "kvfit", 3600.0)
    assert kv == 500.0
    assert "66kV" in (info["ladder_note"] or ""), "梯子がモデル実測から作られていない"


def test_unknown_mode_is_rejected(monkeypatch):
    pytest.importorskip("pandapower")
    pf = _pf()
    with pytest.raises(ValueError):
        _attach(pf, monkeypatch, "somethingelse", 100.0)


# ── 単位系のゲート ────────────────────────────────────────────────────────
def test_bus_incident_mva_counts_parallel_circuits():
    """並列回線を数え落とすと受電容量が半分に出る — この系列で 5 回踏んだ罠。"""
    pytest.importorskip("pandapower")
    import pandapower as pp
    pf = _pf()
    net = pp.create_empty_network()
    a = pp.create_bus(net, vn_kv=110.0)
    b = pp.create_bus(net, vn_kv=110.0)
    pp.create_line_from_parameters(net, a, b, length_km=1.0, r_ohm_per_km=0.1,
                                   x_ohm_per_km=0.3, c_nf_per_km=0.0, max_i_ka=0.5,
                                   parallel=3)
    got = pf.bus_incident_mva(net)[a]
    assert got == pytest.approx(0.5 * 110.0 * math.sqrt(3.0) * 3, rel=1e-6)


def test_required_kv_picks_the_lowest_class_that_can_carry_it():
    pf = _pf()
    ladder = [(66.0, 137.0), (154.0, 533.0), (275.0, 1905.0), (500.0, 6928.0)]
    assert pf.required_kv(100.0, ladder) == 66.0
    assert pf.required_kv(600.0, ladder) == 275.0
    assert pf.required_kv(99999.0, ladder) == 500.0, "運べない出力は最上位へ"
    assert pf.required_kv(100.0, []) == 0.0


# ── 実装の一本化 ──────────────────────────────────────────────────────────
def test_whatif_delegates_to_production():
    """what-if は本番を呼ぶだけであること。写しを戻したらここで落ちる。"""
    src = WGV.read_text(encoding="utf-8")
    assert "pf.attach_generators(" in src, "本番へ委譲していない"
    for leaked in ("def bus_incident_mva", "def class_branch_mva", "def required_kv"):
        assert leaked not in src, f"規則の写しが what-if に戻っている: {leaked}"


def test_model_default_is_cap_but_function_default_stays_nearest():
    """既定ON化(2026-08-09)の形を固定する。

    モデルを組む側は `GEN_ATTACH_DEFAULT="cap"`。しかし**関数の引数既定は nearest**。
    what-if 群は引数なしで `attach_generators(...)` を呼び「旧既定＝最寄り」を比較の
    ベースラインにしているので、関数側を cap にすると公表済み診断の base が
    黙って cap に化ける。この分離が崩れたらここで落とす。
    """
    import inspect
    pf = _pf()
    assert pf.GEN_ATTACH_DEFAULT == "cap", "モデル既定が cap でない"
    sig = inspect.signature(pf.attach_generators)
    assert sig.parameters["attach_mode"].default == "nearest", \
        "関数の引数既定を動かすと what-if の base が汚染される"


def test_model_building_pipelines_use_the_shared_default():
    """モデルを組む経路が全部同じ島別既定を使っていること（食い違うと成果物が混ざる）。

    介入#41(2026-09-02)で既定は `ISLAND_ATTACH_DEFAULT` 経由の `attach_default_for(island)`
    になった。定数 `GEN_ATTACH_DEFAULT` を直接渡す経路が残ると、その経路だけ
    hokkaido/west が cap(318%/1103%)のモデルを組んで成果物が混ざる。
    """
    for rel in ("scripts/uc_to_pf_built.py",
                "scripts/sensitivity/build_sensitivity.py",
                "scripts/sensitivity/benchmark_sensitivity.py",
                "scripts/sensitivity/hosting_capacity.py",
                "scripts/diagnose_pf_frontier.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "attach_mode=attach_default_for(island)" in src, \
            f"{rel} が島別既定(#41)を使っていない"
        assert "attach_mode=GEN_ATTACH_DEFAULT" not in src, \
            f"{rel} に定数直渡しが残っている(#41 以前の経路)"


def test_whatif_baselines_still_call_without_a_mode():
    """what-if の base 呼び出しに mode を付けてはいけない（旧既定を指すため）。"""
    for rel in ("scripts/capacity/whatif_solar_default.py",
                "scripts/capacity/whatif_stepdown.py",
                "scripts/capacity/overload_vs_topology.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "attach_generators(net, bus_of, nodes, island)" in src, \
            f"{rel} の比較ベースラインが書き換わっている"


def test_hokkaido_dc_pins_the_island_default_and_the_cap_defect():
    """既定接続規則の**実モデルの数値**を固定する(CI同等=銘板無し条件)。

    2026-08-09 に既定を倒したとき、既存 1,266 本のうち **1 本も落ちなかった**。
    潮流の出力値を押さえたテストが無かったということなので、ここで塞ぐ。
    hokkaido は 815 線・DC で数秒なのでゲートに載る。

    銘板(data/structures/)は gitignore でチェックアウトに無いため、CI とローカルで
    値が食い違わないよう **銘板キャッシュを空にして**測る(2026-09-01 の再現手順と同じ)。
    """
    pytest.importorskip("pandapower")
    pf = _pf()
    if not Path(pf.BUILT).exists():
        pytest.skip("built DB が無い")
    pf._NAMEPLATES_CACHE = {}          # CI 相当（構造DB 無し）に揃える
    import json as _json
    with open(pf.BUILT, encoding="utf-8") as f:
        db = _json.load(f)
    nodes, edges = db["nodes"], db["edges"]
    cfg = pf.load_demand_config()
    from src.powerflow.pref_demand import pref_zone_gwh
    pref_gwh, _ = pref_zone_gwh(nodes)

    island_default = pf.attach_default_for("hokkaido")
    assert island_default == "capkv", "介入#41: hokkaido の島別既定は capkv"

    got = {}
    for mode in ("nearest", "cap", island_default):
        net, bus_of, _ = pf.build_island_net(
            "hokkaido", nodes, edges, pf.ISLAND_FREQ["hokkaido"], {},
            dedup_nodes=True, site_trafos=False, deenergize_unbuilt=False)
        pf.attach_generators(net, bus_of, nodes, "hokkaido", attach_mode=mode)
        pf.allocate_loads(net, cfg, pref_gwh=pref_gwh)
        from src.powerflow.pipeline import add_reactive_compensation
        add_reactive_compensation(net, factor=cfg.get("reactive_compensation_factor", 0.6))
        pf.add_per_component_slacks(net)
        pf.balance_by_zone(net, cfg)
        solved, _dc, _a, _b = pf.solve_island(net, max_ac_buses=0)
        got[mode] = round(float(solved.res_line["loading_percent"].dropna().max()), 1)

    # 実測値(銘板無し・DC)。動いたら「なぜ動いたか」を IMPROVEMENT_LOG に書いてから更新すること。
    #   2026-08-09: nearest 90.2% / cap 86.0%（太陽光既定 10MW のとき）
    #   2026-08-10: nearest 128.8% / cap 87.1% ← 介入#25（太陽光既定 10→0.10MW）を既定ON
    #   2026-08-10b: nearest 136.3% / cap 88.4% ← 出典付き容量を潮流へ届けた(銘板あり)
    #   2026-09-01: nearest 133.3% / cap 318.0% ← 08-16 基底刷新後・銘板無し。cap は
    #     電圧階級を見ないため京極400MW が札幌66kV に載り 318% 化(真因確定)
    #   2026-09-02: 介入#41 島別既定 hokkaido=capkv → 86.3%(過負荷0本)。cap の 318% は
    #     **既知の欠陥として据え置き記録**(--gen-attach cap で再現可能)
    assert got["nearest"] == pytest.approx(133.3, abs=0.15), \
        f"旧接続規則での最大負荷率が動いた: {got['nearest']}%"
    assert got["cap"] == pytest.approx(318.0, abs=0.15), \
        f"cap(電圧階級を見ない・既知の欠陥)の最大負荷率が動いた: {got['cap']}%"
    assert got["capkv"] == pytest.approx(86.3, abs=0.15), \
        f"島別既定(capkv)での最大負荷率が動いた: {got['capkv']}%"
    assert got["capkv"] < got["nearest"] and got["capkv"] < got["cap"], \
        "島別既定が改善になっていない"


def test_capkv_keeps_large_units_off_66kv():
    """介入#24 の欠陥(cap が電圧階級を見ない)を capkv が塞ぐこと。

    cap の判定は「バスに集まる枝の**合計**容量 >= 出力」だけなので、枝が多ければ
    66kV バスでも選ばれる。北海道では京極発電所400MW(実系統は275kV・西双葉開閉所)が
    札幌市南区の66kVに載り、68.6MVA定格の同一敷地タイに218MWを流して318%を作った。
    capkv は必要階級(出力を1回線で運べる最下位階級)も課すので大型機が66kVに落ちない。

    数値そのものではなく**構造的な主張**を pin する(基底データの更新で桁は動くため)。
    """
    pytest.importorskip("pandapower")
    pf = _pf()
    if not Path(pf.BUILT).exists():
        pytest.skip("built DB が無い")
    import json as _json
    with open(pf.BUILT, encoding="utf-8") as f:
        db = _json.load(f)
    nodes, edges = db["nodes"], db["edges"]

    def big_on_66kv(mode):
        net, bus_of, _ = pf.build_island_net(
            "hokkaido", nodes, edges, pf.ISLAND_FREQ["hokkaido"], {},
            dedup_nodes=True, site_trafos=False, deenergize_unbuilt=False)
        pf.attach_generators(net, bus_of, nodes, "hokkaido", attach_mode=mode)
        g = net.gen.copy()
        g["kv"] = [float(net.bus.at[int(b), "vn_kv"]) for b in g.bus]
        big = g[g.p_mw >= 200.0]
        return len(big), len(big[big.kv <= 66.0])

    n_big_cap, n_bad_cap = big_on_66kv("cap")
    n_big_kv, n_bad_kv = big_on_66kv("capkv")

    assert n_big_cap == n_big_kv and n_big_cap >= 5, "大型機の母数が両モードで揃わない"
    # cap モード自体の欠陥が現存すること(#41 は既定を島別に変えただけで cap の挙動は不変。
    # ここが 0 になったら cap の判定式が変わったということなので台帳を更新すること)
    assert n_bad_cap >= 1, "cap の欠陥が消えている — 判定式が変わったなら台帳を更新すること"
    # capkv では 200MW 超が 66kV 以下に落ちない
    assert n_bad_kv == 0, f"capkv でも大型機が66kVに載った: {n_bad_kv}台"


def test_capkv_is_a_registered_mode_and_island_defaults_are_pinned():
    """capkv が選択肢として提供され、既定は**島別**(介入#41)であること。

    east は降圧点(66↔275kV 変圧器)の欠損を cap が偶然覆い隠しているため、capkv に
    すると 725→1031% と悪化する。出典つき補完が済むまで east/okinawa は cap 据え置き。
    全島一律の定数 `GEN_ATTACH_DEFAULT` は cap のまま(what-if の base と旧経路の互換)。
    """
    pf = _pf()
    assert "capkv" in pf.ATTACH_MODES, "capkv が ATTACH_MODES に無い"
    assert pf.GEN_ATTACH_DEFAULT == "cap", "一律定数が動いた(旧経路の互換が崩れる)"
    assert pf.ISLAND_ATTACH_DEFAULT == {"hokkaido": "capkv", "west": "capkv",
                                        "east": "cap", "okinawa": "cap"}, \
        "島別既定が動いた — 台帳(#41)と IMPROVEMENT_LOG を先に更新すること"
    for island, mode in pf.ISLAND_ATTACH_DEFAULT.items():
        assert pf.attach_default_for(island) == mode
    assert pf.attach_default_for("unknown-island") == pf.GEN_ATTACH_DEFAULT, \
        "未知の島は一律定数へフォールバックすること"


def test_disable_switch_is_documented_in_the_ledger():
    """介入#24/#25 が台帳に登録され、無効化手段が書かれていること。"""
    led = (ROOT / "docs" / "MODEL_INTERVENTIONS.md").read_text(encoding="utf-8")
    assert "--gen-attach" in led, "介入#24 が台帳に無い"
    assert "--default-cap" in led, "介入#25 が台帳に無い"


# ── 介入#26: 発電機の計上エリアを operator で決める ──────────────────────
def test_zone_src_comes_from_the_single_source_table():
    """operator→管内 の表は `src/uc/scenario.OPERATOR_REGION` を import すること。

    `_DEFAULT_CAP` が 4 箇所に散った二の舞を防ぐ構造ゲート。
    """
    src = PF.read_text(encoding="utf-8")
    assert "from src.uc.scenario import OPERATOR_REGION" in src, \
        "operator→管内 の表を写している（単一出典を import すること）"


def test_balance_by_zone_defaults_to_coordinate_zone():
    """既定は従来どおり座標 zone（介入#26 は opt-in）。"""
    import inspect
    pf = _pf()
    sig = inspect.signature(pf.balance_by_zone)
    assert sig.parameters["use_zone_src"].default is False, \
        "介入#26 が既定 ON になっている"


def test_operator_override_moves_kansai_nuclear_out_of_hokuriku():
    """嶺南原発群が hokuriku 計上のままでないこと（2026-08-10 の実測を固定）。

    大飯4,494MW・高浜3,392MW は立地=福井県だが関西電力の電源。座標 zone のままだと
    hokuriku の容量として数えられ scale=0.20 で出力が 1/3 になる。
    """
    pytest.importorskip("pandapower")
    pf = _pf()
    if not Path(pf.BUILT).exists():
        pytest.skip("built DB が無い")
    import json as _json
    with open(pf.BUILT, encoding="utf-8") as f:
        db = _json.load(f)
    nodes, edges = db["nodes"], db["edges"]
    net, bus_of, _ = pf.build_island_net(
        "west", nodes, edges, pf.ISLAND_FREQ["west"], {},
        dedup_nodes=True, site_trafos=False, deenergize_unbuilt=False)
    pf.attach_generators(net, bus_of, nodes, "west",
                         attach_mode=pf.GEN_ATTACH_DEFAULT)
    if "zone_src" not in net.gen.columns:
        pytest.fail("zone_src 列が付いていない（operator タグを読めていない）")
    got = {}
    for _i, r in net.gen.iterrows():
        nm = str(r["name"])
        if nm in ("大飯原子力発電所", "高浜原子力発電所"):
            got[nm] = (str(net.bus.at[int(r["bus"]), "zone"]), r.get("zone_src"))
    assert got, "嶺南原発群が west に載っていない"
    for nm, (bus_zone, src) in got.items():
        assert src == "kansai", f"{nm} の operator 由来エリアが kansai でない: {src}"
        assert bus_zone == "hokuriku", \
            f"{nm} の座標 zone が hokuriku でなくなった（レポートの前提が変わった）: {bus_zone}"
