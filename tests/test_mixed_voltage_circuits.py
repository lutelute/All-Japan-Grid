"""併架線(同じ鉄塔に別電圧の回線が乗る線路)の回線数を、線路名ごとに読み直す。

OSM は ``voltage=275000;66000`` ``circuits=6`` のように、併架線の回線数を
合計で書く。以前のビルダーは合計を上位電圧に全部付け(下位は 1 回線)ており、
275 kV が 6 回線ぶんの容量を持つことになっていた(実際は香取線 2 + 湖南線 4)。
同じ線路の単一電圧区間に circuits タグがあれば、それを直接証拠として使う。
"""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from powerflow.snapped_topology import (  # noqa: E402
    _circuit_evidence, _is_synthetic_line_name, _line_name_list,
    _voltage_class_list,
)


def test_voltage_class_list_keeps_tag_order():
    assert _voltage_class_list("275000;66000") == [275.0, 66.0]
    assert _voltage_class_list("66000;275000") == [66.0, 275.0]
    assert _voltage_class_list("275000") == [275.0]
    assert _voltage_class_list(None) == []


def test_line_name_list_splits_both_separators():
    assert _line_name_list("香取線 / 湖南線") == ["香取線", "湖南線"]
    assert _line_name_list("秦浜線;湘南線") == ["秦浜線", "湘南線"]
    assert _line_name_list("香取線") == ["香取線"]
    assert _line_name_list(None) == []


def test_evidence_only_from_single_voltage_ways():
    props = [
        {"voltage": "275000", "name": "香取線", "circuits": "2"},
        {"voltage": "275000", "name": "香取線", "circuits": "2"},
        {"voltage": "66000", "name": "湖南線", "circuits": "4"},
        {"voltage": "66000", "name": "湖南線", "circuits": "4"},
        # 併架の way 自身は証拠にしない(これが数え過ぎの元)
        {"voltage": "275000;66000", "name": "香取線 / 湖南線", "circuits": "6"},
    ]
    ev = _circuit_evidence(props)
    assert ev == {("香取線", 275.0): 2, ("湖南線", 66.0): 4}


def test_evidence_needs_min_support():
    """1 本だけの way は証拠にしない(端部の 1 回線を全線に広げないため)。"""
    one = [{"voltage": "77000", "name": "勧進橋東線", "circuits": "1"}]
    assert _circuit_evidence(one) == {}
    two = one * 2
    assert _circuit_evidence(two) == {("勧進橋東線", 77.0): 1}


def test_evidence_needs_circuits_tag():
    """circuits タグの無い way は証拠にしない(cables 由来の推定は使わない)。"""
    props = [{"voltage": "154000", "name": "甲線", "cables": "6"}] * 3
    assert _circuit_evidence(props) == {}


def test_evidence_takes_max_not_majority():
    """値が割れたら最大値。端部の 1 回線 way が本線に勝たないように。"""
    props = [
        {"voltage": "500000", "name": "富津火力線", "circuits": "1"},
        {"voltage": "500000", "name": "富津火力線", "circuits": "1"},
        {"voltage": "500000", "name": "富津火力線", "circuits": "1"},
        {"voltage": "500000", "name": "富津火力線", "circuits": "2"},
    ]
    assert _circuit_evidence(props)[("富津火力線", 500.0)] == 2
    tie = [
        {"voltage": "154000", "name": "乙線", "circuits": "1"},
        {"voltage": "154000", "name": "乙線", "circuits": "2"},
    ]
    assert _circuit_evidence(tie)[("乙線", 154.0)] == 2


def test_evidence_ignores_multi_name_ways():
    """名前が複数ある way は電圧との対応が取れないので証拠にしない。"""
    props = [{"voltage": "154000", "name": "甲線;乙線", "circuits": "4"}] * 3
    assert _circuit_evidence(props) == {}


def test_synthetic_names_are_not_evidence():
    """実名の無い線に付けた合成名は、別々の線路が同名になるので証拠にしない。"""
    assert _is_synthetic_line_name("東北電力ネットワーク 66.0kV線")
    assert _is_synthetic_line_name("由利本荘市変電所~鳥海町下直根変電所線")
    assert not _is_synthetic_line_name("香取線")
    props = [{"voltage": "66000", "name": "東北電力ネットワーク 66.0kV線",
              "circuits": "6"}] * 50
    assert _circuit_evidence(props) == {}
