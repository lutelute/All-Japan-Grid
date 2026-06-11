"""Smoke tests for the unified ajgrid CLI (src.cli)."""

import pytest

from src import cli


def test_parser_builds():
    p = cli.build_parser()
    args, rest = p.parse_known_args(["regions"])
    assert args.command == "regions"


def test_solve_args():
    p = cli.build_parser()
    args, _ = p.parse_known_args(
        ["solve", "okinawa", "--topology", "snapped", "--reconnect"])
    assert args.region == "okinawa"
    assert args.topology == "snapped" and args.reconnect is True


def test_passthrough_subcommands_keep_rest():
    p = cli.build_parser()
    args, rest = p.parse_known_args(["cim", "--regions", "okinawa", "--verify"])
    assert args.command == "cim"
    assert rest == ["--regions", "okinawa", "--verify"]
    args, rest = p.parse_known_args(["db", "export", "--verify"])
    assert rest == ["export", "--verify"]


def test_regions_command_runs(capsys):
    rc = cli.cmd_regions(None, [])
    out = capsys.readouterr().out
    assert rc == 0
    assert "hokkaido" in out and "沖縄" in out


def test_db_rejects_unknown_subcommand():
    assert cli.cmd_db(None, ["bogus"]) == 2


def test_uc_passthrough_and_validation():
    p = cli.build_parser()
    args, rest = p.parse_known_args(["uc", "benchmark", "--duals"])
    assert args.command == "uc"
    assert rest == ["benchmark", "--duals"]
    # 未知サブコマンドは usage (rc=2)
    assert cli.cmd_uc(None, ["bogus"]) == 2
    assert cli.cmd_uc(None, []) == 2
