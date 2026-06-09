"""The coverage report must surface authoritative-vs-synthetic honestly.

It is the tool that makes the data's limits *measurable*, so these tests pin
that it always names the P03 authoritative share AND the synthetic-electrical
limitation — a regression here would let the tool overstate the model.
"""

from scripts.coverage_report import render
from src.cli import build_parser

_SAMPLE = {
    "db": "x.db",
    "raw": {"substations": 6962, "lines": 40077, "plants": 19138},
    "p03_plants": 3109, "p03_capacity": 2433, "p03_operator": 3082,
    "any_named_plants": 19000,
    "by_source": [("legacy_marker", 184985), ("p03_db", 13705),
                  ("overpass_db", 20)],
}


def test_render_reports_authoritative_share_and_limits():
    out = render(_SAMPLE)
    assert "P03" in out and "16.2%" in out          # corroborated share
    assert "83.8%" in out                            # honest OSM-only remainder
    assert "authoritative: 国土数値情報 P03" in out   # provenance tag on the source
    assert "KNOWN LIMITATION" in out                 # synthetic R/X/B disclosed
    assert "SYNTHETIC" in out


def test_render_zero_authoritative_is_still_honest():
    d = dict(_SAMPLE, p03_plants=0, p03_capacity=0, p03_operator=0,
             by_source=[("legacy_marker", 184985)])
    out = render(d)
    assert "0.0%" in out and "100.0%" in out          # 0 validated / all OSM-only
    assert "KNOWN LIMITATION" in out


def test_cli_exposes_coverage_subcommand():
    args, _ = build_parser().parse_known_args(["coverage", "--db", "x.db"])
    assert args.command == "coverage" and args.db == "x.db"
