"""Regression guard: Overpass requests must send a descriptive User-Agent.

overpass-api.de rejects requests carrying the default ``python-requests``
User-Agent with **HTTP 406 (Not Acceptable)** — a failure mode only visible
against the live API, which silently zeroed the plant tag-enricher. Both
Overpass callers must set a project User-Agent (with a contact URL, per the
Overpass usage policy).
"""

import inspect


def _asserts_ua(headers):
    assert "User-Agent" in headers, "Overpass call must set a User-Agent"
    ua = headers["User-Agent"]
    assert "All-Japan-Grid" in ua and "github.com/lutelute" in ua, ua


def test_enrich_overpass_tags_sets_user_agent():
    from scripts import enrich_overpass_tags as m
    _asserts_ua(m.OVERPASS_HEADERS)
    # the header must actually be wired into the request call
    assert "headers=OVERPASS_HEADERS" in inspect.getsource(m.fetch_overpass_batch)


def test_fetch_plants_sets_user_agent():
    from scripts import fetch_plants as m
    _asserts_ua(m.OVERPASS_HEADERS)
    assert "headers=OVERPASS_HEADERS" in inspect.getsource(m)
