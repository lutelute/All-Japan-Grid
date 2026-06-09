"""The exported CGMES Level-2 set must pass strict structural validation.

Independently of pandapower ``cim2pp``, the tracked okinawa profile set must
have zero dangling references, well-formed UUID mRIDs, and a FullModel header
— i.e. the README's "0 dangling references" claim, enforced as a test.
"""

import os

import pytest

pytest.importorskip("lxml")

from scripts.validate_cgmes import _files_for_region, validate_model  # noqa: E402

CIM_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "dist", "cim_level2")

_HAS_OKINAWA = os.path.exists(os.path.join(CIM_DIR, "okinawa_L2_EQ.xml"))


@pytest.mark.skipif(not _HAS_OKINAWA, reason="okinawa L2 profiles absent")
def test_okinawa_cgmes_is_structurally_valid():
    rep = validate_model("okinawa", _files_for_region("okinawa", CIM_DIR))
    assert not rep.malformed, rep.malformed
    assert rep.declared, "no objects parsed"
    assert rep.dangling == [], rep.dangling[:5]
    assert rep.bad_id == [], rep.bad_id[:5]
    assert rep.mrid_mismatch == [], rep.mrid_mismatch[:5]
    assert rep.has_fullmodel and rep.has_profile
    assert rep.ok


def test_validator_flags_a_dangling_reference(tmp_path):
    """A reference to an undeclared id must be reported (catches regressions)."""
    rdf = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rdf:RDF xmlns:cim="http://iec.ch/TC57/2013/CIM-schema-cim16#" '
        'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        'xmlns:md="http://iec.ch/TC57/61970-552/ModelDescription/1#">'
        '<md:FullModel rdf:about="urn:uuid:x">'
        '<md:Model.profile>test</md:Model.profile></md:FullModel>'
        '<cim:Substation rdf:ID="_11111111-1111-1111-1111-111111111111">'
        '<cim:IdentifiedObject.mRID>11111111-1111-1111-1111-111111111111'
        '</cim:IdentifiedObject.mRID>'
        '<cim:Substation.Region rdf:resource="#_deadbeef-0000-0000-0000-000000000000"/>'
        '</cim:Substation></rdf:RDF>')
    f = tmp_path / "m_EQ.xml"
    f.write_text(rdf, encoding="utf-8")
    rep = validate_model("m", [str(f)])
    assert len(rep.dangling) == 1
    assert not rep.ok
