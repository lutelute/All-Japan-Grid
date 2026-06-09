"""Tests for the canonical OSM voltage parser (REVIEW_FINDINGS #10)."""

from src.utils.voltage import parse_voltage_kv


def test_simple_volts():
    assert parse_voltage_kv("275000") == 275.0


def test_already_kv():
    assert parse_voltage_kv("154") == 154.0


def test_multi_voltage_takes_max():
    assert parse_voltage_kv("154000;66000") == 154.0


def test_order_independent():
    """The crux of #10: token order must not change the result."""
    assert parse_voltage_kv("66000;154000") == parse_voltage_kv("154000;66000")
    assert parse_voltage_kv("66000;154000") == 154.0


def test_comma_is_a_separator_not_thousands():
    # "77000,6600" is two voltages, not 770006600
    assert parse_voltage_kv("77000,6600") == 77.0


def test_none_and_garbage():
    assert parse_voltage_kv(None) is None
    assert parse_voltage_kv("") is None
    assert parse_voltage_kv("yes") is None
    assert parse_voltage_kv("0") is None


def test_mixed_garbage_keeps_valid():
    assert parse_voltage_kv("abc;275000") == 275.0
