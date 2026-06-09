#!/usr/bin/env python3
"""Strict, independent validation of the exported CGMES RDF/XML.

This is a *second opinion* that does not go through pandapower ``cim2pp``:
it parses the RDF/XML directly and checks the structural invariants a
CGMES consumer relies on, over a complete profile set (EQ/TP/SSH/SV/GL +
the boundary EQ_BD/TP_BD). It is the rigorous form of the README's
"0 dangling references" claim and a step toward M3 (CGMES strict
validation, docs/VISION.md Pillar 2).

Checks per model (a set of files treated as one exchange):
  1. **Well-formedness** — every file parses as XML.
  2. **rdf:ID format** — every declared id is ``_<uuid>`` (CGMES mRIDs are UUIDs).
  3. **mRID agreement** — where an object carries ``cim:IdentifiedObject.mRID``,
     it equals the rdf:ID without the leading underscore.
  4. **Referential integrity** — every intra-model ``rdf:resource="#_<uuid>"``
     resolves to a declared rdf:ID somewhere in the set (boundary included).
     Enum/profile refs (``http://…#…``) are external and skipped.
  5. **FullModel header** — at least one ``md:FullModel`` with a ``Model.profile``.

Usage:
    python scripts/validate_cgmes.py --all --dir dist/cim_level2
    python scripts/validate_cgmes.py --region okinawa --dir dist/cim_level2
    python scripts/validate_cgmes.py a_EQ.xml a_TP.xml … AllJapan_EQ_BD.xml

Exit code is non-zero if any model fails — usable in CI.
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys

from lxml import etree

RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
MD = "{http://iec.ch/TC57/61970-552/ModelDescription/1#}"
CIM = "{http://iec.ch/TC57/2013/CIM-schema-cim16#}"

PROFILES = ("EQ", "TP", "SSH", "SV", "GL")
BOUNDARY = ("AllJapan_EQ_BD.xml", "AllJapan_TP_BD.xml")
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class ModelReport:
    def __init__(self, name):
        self.name = name
        self.files = []
        self.malformed = []          # (file, error)
        self.declared = set()        # rdf:ID values, "_<uuid>"
        self.n_refs = 0
        self.dangling = []           # (file, target)
        self.bad_id = []             # (file, id) — not "_<uuid>"
        self.mrid_mismatch = []      # (file, id, mrid)
        self.has_fullmodel = False
        self.has_profile = False

    @property
    def ok(self):
        return (not self.malformed and not self.dangling and not self.bad_id
                and not self.mrid_mismatch and self.has_fullmodel
                and self.has_profile)

    def summary(self):
        head = "OK  " if self.ok else "FAIL"
        return (f"[{head}] {self.name}: {len(self.declared)} objects, "
                f"{self.n_refs} refs, {len(self.dangling)} dangling, "
                f"{len(self.bad_id)} bad-id, {len(self.mrid_mismatch)} mRID-mismatch"
                + ("" if self.has_fullmodel else ", NO FullModel"))


def validate_model(name, files) -> ModelReport:
    rep = ModelReport(name)
    refs = []  # (file, target_id)
    for f in files:
        rep.files.append(f)
        if not os.path.exists(f):
            rep.malformed.append((f, "missing file"))
            continue
        try:
            root = etree.parse(f).getroot()
        except etree.XMLSyntaxError as exc:
            rep.malformed.append((f, str(exc)))
            continue
        for el in root.iter():
            if el.tag == MD + "FullModel":
                rep.has_fullmodel = True
                if el.find(MD + "Model.profile") is not None:
                    rep.has_profile = True
            rid = el.get(RDF + "ID")
            if rid is not None:
                rep.declared.add(rid)
                if not (rid.startswith("_") and UUID_RE.match(rid[1:])):
                    rep.bad_id.append((f, rid))
                mrid_el = el.find(CIM + "IdentifiedObject.mRID")
                if mrid_el is not None and (mrid_el.text or "").strip():
                    mrid = mrid_el.text.strip()
                    if rid != "_" + mrid:
                        rep.mrid_mismatch.append((f, rid, mrid))
            res = el.get(RDF + "resource")
            if res is not None and res.startswith("#"):
                refs.append((f, res[1:]))
    rep.n_refs = len(refs)
    rep.dangling = [(f, t) for (f, t) in refs if t not in rep.declared]
    return rep


def _files_for_region(region, d):
    files = [os.path.join(d, f"{region}_L2_{p}.xml") for p in PROFILES]
    files += [os.path.join(d, b) for b in BOUNDARY]
    return files


def _regions_in(d):
    found = []
    for path in sorted(glob.glob(os.path.join(d, "*_L2_EQ.xml"))):
        found.append(os.path.basename(path)[: -len("_L2_EQ.xml")])
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="profile files forming one model")
    ap.add_argument("--dir", default="dist/cim_level2", help="CGMES output dir")
    ap.add_argument("--region", help="validate this region's L2 set + boundary")
    ap.add_argument("--all", action="store_true",
                    help="validate every region found in --dir")
    ap.add_argument("--show", type=int, default=5,
                    help="how many example problems to print per category")
    args = ap.parse_args(argv)

    models = []  # (name, files)
    if args.all:
        for r in _regions_in(args.dir):
            models.append((r, _files_for_region(r, args.dir)))
    elif args.region:
        models.append((args.region, _files_for_region(args.region, args.dir)))
    elif args.files:
        models.append(("model", args.files))
    else:
        ap.error("pass --all, --region REGION, or explicit files")

    all_ok = True
    for name, files in models:
        rep = validate_model(name, files)
        print(rep.summary())
        all_ok = all_ok and rep.ok
        for label, items in (("malformed", rep.malformed),
                             ("bad-id", rep.bad_id),
                             ("mRID-mismatch", rep.mrid_mismatch),
                             ("dangling", rep.dangling)):
            for it in items[: args.show]:
                print(f"    {label}: {it}")
            if len(items) > args.show:
                print(f"    {label}: … +{len(items) - args.show} more")

    print(f"\n{'ALL MODELS VALID' if all_ok else 'VALIDATION FAILED'} "
          f"({len(models)} model(s))")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
