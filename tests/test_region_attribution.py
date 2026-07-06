"""領土ベースzone再属性(A案)の回帰ピン — 幻tie解剖で確定した誤属性座標が直ること."""
import pytest

from src.powerflow.region_attribution import (
    area_of_coord,
    prefecture_of,
    reattribute_node_regions,
)


class TestAreaOfCoord:
    # 幻tie解剖(phantom_tie_zone_contamination_2026-07-07.md)の実座標ピン
    @pytest.mark.parametrize("lat,lon,expect", [
        (33.95941, 132.16053, "chugoku"),   # 柳井市変電所(shikoku誤属性だった)
        (34.19979, 131.82605, "chugoku"),   # 東山口変電所500kV(kyushu誤属性だった)
        (33.96303, 132.05472, "chugoku"),   # 田布施町変電所(kyushu誤属性だった)
        (33.99930, 130.96380, "chugoku"),   # 下関変電所(関門の本州側=山口県)
        (33.81040, 130.80430, "kyushu"),    # 北九州変電所(関門の九州側)
        (34.45930, 133.78300, "chugoku"),   # 菰池二丁目(児島=本四の本州側)
        (34.32690, 133.86220, "shikoku"),   # 昭和町二丁目(坂出=本四の四国側)
        (33.87970, 134.65180, "shikoku"),   # 阿南発電所(kansai誤属性だった)
        (35.65000, 136.07000, "hokuriku"),  # 敦賀(嶺南も北陸電力エリア)
        (41.77000, 140.73000, "hokkaido"),  # 函館(青函の北側)
        (40.90000, 140.80000, "tohoku"),    # 青森市付近(青函の南側)
    ])
    def test_contested_coords(self, lat, lon, expect):
        assert area_of_coord(lat, lon) == expect

    def test_shizuoka_fujikawa_split(self):
        assert area_of_coord(35.10, 138.86) == "tokyo"   # 沼津(富士川以東)
        assert area_of_coord(34.71, 137.73) == "chubu"   # 浜松(富士川以西)

    def test_offshore_falls_back_to_nearest(self):
        # 瀬戸内海上(大槌島付近) — ポリゴン外でも最近傍県で答えが出る
        assert area_of_coord(34.42, 133.93) in ("chugoku", "shikoku")

    def test_prefecture_lookup(self):
        assert prefecture_of(34.18583, 131.47139) == "山口県"  # 山口市
        assert prefecture_of(26.2124, 127.6809) == "沖縄県"    # 那覇


class TestReattributeNodeRegions:
    def test_reattributes_and_keeps_audit_trail(self):
        nodes = [
            {"lat": 33.95941, "lon": 132.16053, "region": "shikoku"},  # 柳井
            {"lat": 33.81040, "lon": 130.80430, "region": "kyushu"},   # 北九州(正)
        ]
        stats = reattribute_node_regions(nodes)
        assert nodes[0]["region"] == "chugoku"
        assert nodes[0]["region_src"] == "shikoku"
        assert nodes[1]["region"] == "kyushu"
        assert stats["n_changed"] == 1
        assert stats["changes"] == {"shikoku->chugoku": 1}

    def test_idempotent(self):
        nodes = [{"lat": 33.95941, "lon": 132.16053, "region": "shikoku"}]
        reattribute_node_regions(nodes)
        stats2 = reattribute_node_regions(nodes)
        assert stats2["n_changed"] == 0
        assert nodes[0]["region_src"] == "shikoku"  # 初回の退避が保持される

    def test_frequency_guard_keeps_50hz_claims_in_60hz_prefectures(self):
        # 新信濃変換所(東京電力50Hz・長野県) — 県近似ではchubuだが、
        # 周波数を跨ぐ移動は禁止(eastの安曇幹線が切れる)→tokyoのまま
        nodes = [{"lat": 36.13479, "lon": 137.88469, "region": "tokyo"}]
        stats = reattribute_node_regions(nodes)
        assert nodes[0]["region"] == "tokyo"
        assert stats["n_changed"] == 0
        assert stats["skipped_freq"] == {"tokyo->chubu": 1}

    def test_frequency_guard_keeps_60hz_spillover(self):
        # 山梨(東京電力50Hz領土)へのchubu抽出はみ出し — 周波数跨ぎなので保持
        # (既知の限界として開示。修正には運用者/周波数データが必要)
        nodes = [{"lat": 35.66, "lon": 138.57, "region": "chubu"}]
        stats = reattribute_node_regions(nodes)
        assert nodes[0]["region"] == "chubu"
        assert stats["skipped_freq"] == {"chubu->tokyo": 1}

    def test_same_frequency_cross_island_moves_allowed(self):
        # 青函: hokkaido抽出が青森へはみ出し — 同一50Hzなので島所属ごと修正
        nodes = [{"lat": 40.90, "lon": 140.80, "region": "hokkaido"}]
        stats = reattribute_node_regions(nodes)
        assert nodes[0]["region"] == "tohoku"
        assert stats["changes"] == {"hokkaido->tohoku": 1}
