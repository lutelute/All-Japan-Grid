"""CIM (IEC 61970 / CGMES) export layer for All-Japan-Grid.

Maps the OSM-derived Japanese grid (substations / lines / plants) onto the
IEC 61970 Common Information Model and serialises it as CGMES-compatible
RDF/XML. Two profiles are emitted:

  - EQ  (Equipment)            : Substation, VoltageLevel, BaseVoltage,
                                 ACLineSegment, Terminal, ConnectivityNode,
                                 {Thermal,Hydro,Wind,Solar,Nuclear}GeneratingUnit,
                                 SynchronousMachine, GeographicalRegion ...
  - GL  (Geographical Location): Location, PositionPoint, CoordinateSystem
                                 (carries the OSM geographic coordinates)

The implementation is dependency-free (standard library only) and uses the
CIM16 namespace (CGMES 2.4.15), the most widely interoperable CIM profile.
"""

from .core import NS_CIM, NS_RDF, NS_MD, mrid, RdfWriter, PROFILE_EQ, PROFILE_GL

__all__ = [
    "NS_CIM",
    "NS_RDF",
    "NS_MD",
    "mrid",
    "RdfWriter",
    "PROFILE_EQ",
    "PROFILE_GL",
]
