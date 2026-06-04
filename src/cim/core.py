"""CIM/CGMES core: namespaces, deterministic mRID, and an RDF/XML writer.

Dependency-free CGMES RDF/XML serialisation. Uses the CIM16 namespace
(CGMES 2.4.15) — the most widely interoperable CIM profile, readable by
pandapower ``cim2pp``, PowerFactory, CIMverter and similar tooling.

CGMES conventions implemented here:
  * Every CIM object is written as ``<cim:Class rdf:ID="_<mrid>">``.
  * Internal references use ``rdf:resource="#_<mrid>"``.
  * Enumerated values use ``rdf:resource="<NS_CIM><Enum>.<value>"``.
  * A ``md:FullModel`` header declares the profile and modeling authority.
"""

from __future__ import annotations

import uuid
from typing import Dict, List, Optional
from xml.sax.saxutils import escape

# ---------------------------------------------------------------------------
# Namespaces (CGMES 2.4.15 / CIM16)
# ---------------------------------------------------------------------------
NS_CIM = "http://iec.ch/TC57/2013/CIM-schema-cim16#"
NS_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
NS_MD = "http://iec.ch/TC57/61970-552/ModelDescription/1#"

# CGMES profile URIs (ENTSO-E convention) used in the md:FullModel header.
PROFILE_EQ = "http://entsoe.eu/CIM/EquipmentCore/3/1"
PROFILE_GL = "http://entsoe.eu/CIM/GeographicalLocation/2/1"

# Modeling authority set — identifies the producer of this CIM model.
MODELING_AUTHORITY = "https://github.com/lutelute/All-Japan-Grid"

# Deterministic-mRID seed. uuid5(_MRID_ROOT, key) is stable across runs and
# machines, so re-exporting the same feature always yields the same mRID
# (required for reproducible, diff-able CIM datasets).
_MRID_ROOT = uuid.UUID("a3e1d2c4-0000-5000-8000-616c6c6a7067")


def mrid(*parts: object) -> str:
    """Return a deterministic UUID string from key ``parts``.

    Same inputs always produce the same mRID. Use stable, globally-unique keys
    (e.g. ``mrid("substation", region, feature_index)``) so that identifiers do
    not collide across kinds/regions and stay constant between exports.

    Args:
        *parts: Components of the identity key; joined with ``|``.

    Returns:
        A canonical UUID string (e.g. ``"3f2504e0-4f89-51d3-9a0c-0305e82c3301"``).
    """
    key = "|".join(str(p) for p in parts)
    return str(uuid.uuid5(_MRID_ROOT, key))


def base_voltage_mrid(kv: float) -> str:
    """Deterministic mRID for the BaseVoltage of nominal voltage ``kv`` (kV).

    Shared by the Level-1 EQ, the Level-2 EQ and the boundary set so that all
    three reference the *same* BaseVoltage objects (CGMES boundary convention).
    """
    return mrid("basevoltage", round(float(kv), 3))


class RdfWriter:
    """Minimal, append-only CGMES RDF/XML writer (standard library only).

    Build a document by calling :meth:`header` once, then :meth:`obj` for each
    CIM object, and finally :meth:`render` (or :meth:`write`) to obtain the
    serialised RDF/XML string.
    """

    def __init__(self, profile_uri: str, model_mrid: str) -> None:
        """Initialise the writer for one CGMES profile file.

        Args:
            profile_uri: Profile declared in the header (e.g. :data:`PROFILE_EQ`).
            model_mrid: mRID identifying this model/profile instance.
        """
        self._lines: List[str] = []
        self._profile = profile_uri
        self._model_mrid = model_mrid
        self._count = 0

    @staticmethod
    def _esc(value: object) -> str:
        """XML-escape a scalar value for use as element text."""
        return escape(str(value), {'"': "&quot;"})

    @property
    def object_count(self) -> int:
        """Number of CIM objects written so far (excludes the model header)."""
        return self._count

    def header(self) -> "RdfWriter":
        """Emit the XML declaration, ``rdf:RDF`` root and ``md:FullModel``."""
        add = self._lines.append
        add('<?xml version="1.0" encoding="UTF-8"?>')
        add(
            f'<rdf:RDF xmlns:cim="{NS_CIM}" '
            f'xmlns:rdf="{NS_RDF}" '
            f'xmlns:md="{NS_MD}">'
        )
        add(f'  <md:FullModel rdf:about="urn:uuid:{self._model_mrid}">')
        add(f"    <md:Model.profile>{self._profile}</md:Model.profile>")
        add(
            "    <md:Model.modelingAuthoritySet>"
            f"{MODELING_AUTHORITY}"
            "</md:Model.modelingAuthoritySet>"
        )
        add("  </md:FullModel>")
        return self

    def obj(
        self,
        cls: str,
        m: str,
        attrs: Optional[Dict[str, object]] = None,
        refs: Optional[Dict[str, Optional[str]]] = None,
        enums: Optional[Dict[str, Optional[str]]] = None,
    ) -> "RdfWriter":
        """Write a single CIM object.

        Args:
            cls: CIM class name (e.g. ``"Substation"``, ``"ACLineSegment"``).
            m: mRID of this object (without the leading underscore).
            attrs: Datatype properties keyed by full CIM attribute name
                (e.g. ``{"IdentifiedObject.name": "Foo", "Conductor.length": 12000}``).
                ``None`` values are skipped.
            refs: Object properties resolved as internal references
                (``rdf:resource="#_<target_mrid>"``). ``None`` targets skipped.
            enums: Object properties whose value is a CIM enumeration literal,
                given as the ``"<Enum>.<value>"`` suffix
                (e.g. ``{"...": "WindGenUnitKind.onshore"}``). ``None`` skipped.

        Returns:
            ``self`` (for chaining).
        """
        add = self._lines.append
        add(f'  <cim:{cls} rdf:ID="_{m}">')
        for k, v in (attrs or {}).items():
            if v is None:
                continue
            add(f"    <cim:{k}>{self._esc(v)}</cim:{k}>")
        for k, target in (refs or {}).items():
            if target is None:
                continue
            targets = target if isinstance(target, (list, tuple)) else [target]
            for t in targets:
                if t is not None:
                    add(f'    <cim:{k} rdf:resource="#_{t}"/>')
        for k, suffix in (enums or {}).items():
            if suffix is None:
                continue
            add(f'    <cim:{k} rdf:resource="{NS_CIM}{suffix}"/>')
        add(f"  </cim:{cls}>")
        self._count += 1
        return self

    def render(self) -> str:
        """Return the complete RDF/XML document as a string."""
        return "\n".join(self._lines + ["</rdf:RDF>", ""])

    def write(self, path: str) -> None:
        """Write the rendered RDF/XML to ``path`` (UTF-8)."""
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.render())
