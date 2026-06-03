# CIM / CGMES Mapping — All-Japan-Grid

This document specifies how the All-Japan-Grid dataset (OSM-derived Japanese
transmission grid) is mapped onto the **IEC 61970 Common Information Model
(CIM)** and serialised as **CGMES-compatible RDF/XML**.

本書は、All-Japan-Grid データセット（OSM 由来の日本全国送電網）を国際標準
**IEC 61970 CIM** へマッピングし、**CGMES 互換 RDF/XML** として出力する規則を定義する。

- **Namespace / 名前空間:** `http://iec.ch/TC57/2013/CIM-schema-cim16#` (CIM16 = CGMES 2.4.15)
- **Profiles / プロファイル:** EQ (Equipment) + GL (Geographical Location)
- **Generator / 生成:** `python scripts/export_cim.py`  → `dist/cim/<region>_{EQ,GL}.xml`
- **Implementation / 実装:** `src/cim/` (standard library only / 依存ゼロ)

---

## 1. Why CIM / なぜ CIM 化するか

CIM (IEC 61970/61968) is the international standard information model for power
systems, used for model exchange between TSOs, EMS/SCADA, and analysis tools
(PowerFactory, PSS/E via converters, pandapower `cim2pp`, CIMverter, ENTSO-E
CGMES exchanges). Publishing All-Japan-Grid as CIM makes every substation,
line and plant a **standards-conformant, tool-interoperable object** instead of
an ad-hoc GeoJSON property bag — the dataset becomes a *complete, exchangeable
grid database*.

CIM は電力系統の国際標準情報モデルであり、TSO 間のモデル交換・EMS/SCADA・解析
ツールで広く用いられる。All-Japan-Grid を CIM 化することで、変電所・送電線・
発電所の各要素が独自 GeoJSON プロパティではなく **規格準拠でツール相互運用可能な
オブジェクト** となり、データセットが *交換可能な完全系統 DB* になる。

---

## 2. Profiles & files / プロファイルとファイル

| Profile | File | Contents |
|---|---|---|
| **EQ** (Equipment) | `<region>_EQ.xml` | Topology & electrical objects: containers, substations, voltage levels, lines, terminals, connectivity nodes, generating units, machines |
| **GL** (Geographical Location) | `<region>_GL.xml` | Coordinates: `CoordinateSystem`, `Location`, `PositionPoint` — carries the OSM geometry (WGS84) |

Each `md:FullModel` header declares its profile URI and
`modelingAuthoritySet = https://github.com/lutelute/All-Japan-Grid`.
A `dist/cim/cim_index.json` manifest lists per-region counts and base voltages.

---

## 3. Class mapping / クラスマッピング

### 3.1 Containers & reference / コンテナと参照

| All-Japan-Grid | CIM class | Key attributes / references | Profile |
|---|---|---|---|
| Japan (whole) | `GeographicalRegion` | `IdentifiedObject.name = "Japan"` | EQ |
| Region (10 EPCO areas) | `SubGeographicalRegion` | `.name`, `.Region →` GeographicalRegion | EQ |
| Voltage class (e.g. 275 kV) | `BaseVoltage` | `.nominalVoltage` (kV) — shared, deduplicated per region | EQ |
| WGS84 CRS | `CoordinateSystem` | `.crsUrn = urn:ogc:def:crs:EPSG::4326` | GL |

### 3.2 Substations / 変電所

| Feature | CIM class | Attributes / references |
|---|---|---|
| `data/<r>_substations.geojson` feature | `Substation` | `.name`, `.mRID`, `.Region →` SubGeographicalRegion |
| (voltage container inside it) | `VoltageLevel` | `.Substation →`, `.BaseVoltage →` |
| geometry (Point/Polygon → representative pt) | `Location` + 1 `PositionPoint` | GL |

### 3.3 Transmission lines / 送電線

| Feature | CIM class | Attributes / references |
|---|---|---|
| `data/<r>_lines.geojson` feature | `ACLineSegment` | `.name`, `.mRID`, `Conductor.length` (m, Haversine), `ConductingEquipment.BaseVoltage →` |
| line endpoints ×2 | `Terminal` | `ACDCTerminal.sequenceNumber` (1,2), `.ConductingEquipment →`, `.ConnectivityNode →` |
| connection points ×2 | `ConnectivityNode` | (Level-1: independent per line; see §6) |
| geometry (LineString vertices) | `Location` + N `PositionPoint` | GL — full polyline preserved |

### 3.4 Power plants / 発電所

`fuel_type` selects the CIM `GeneratingUnit` subclass:

| `fuel_type` | CIM class | Rotating machine? |
|---|---|---|
| coal, lng, gas, oil, biomass, waste, geothermal | `ThermalGeneratingUnit` | ✅ `SynchronousMachine` |
| nuclear | `NuclearGeneratingUnit` | ✅ `SynchronousMachine` |
| hydro, pumped_hydro | `HydroGeneratingUnit` | ✅ `SynchronousMachine` |
| wind | `WindGeneratingUnit` | — |
| solar | `SolarGeneratingUnit` | — |
| battery, mixed, unknown | `GeneratingUnit` | — |

> CGMES 2.4.15 lacks Geothermal/Battery generating-unit subclasses, so
> geothermal → Thermal and battery → generic `GeneratingUnit`.

Attributes: `GeneratingUnit.ratedP`, `.maxOperatingP`, `.minOperatingP` (MW,
from `capacity_mw` when > 0). Rotating units add a `SynchronousMachine` with
`RotatingMachine.ratedS` and `.GeneratingUnit →`. Plant geometry → `Location` +
1 `PositionPoint`.

---

## 4. Identity (mRID) / 同一性

Every `IdentifiedObject` carries an `mRID` — a **deterministic UUIDv5** derived
from a stable key (`uuid5(seed, "kind|region|index")`). Re-running the export
on unchanged data always yields the **same mRIDs**, so CIM files are
reproducible and diff-able. References use the CGMES convention
`rdf:ID="_<mrid>"` / `rdf:resource="#_<mrid>"`.

各 `IdentifiedObject` は **決定的 UUIDv5** の mRID を持つ。同一データの再実行で
mRID は不変 → CIM ファイルは再現可能・差分可能。

---

## 5. Voltage handling / 電圧の扱い

Raw OSM `voltage` (volt-valued string, possibly multi-level / DC) is parsed to
kV per `config/data_schema.yaml` rules (split on `;`/`,`, `dc` prefix → DC,
`kv` suffix already-kV else ÷1000, drop ≤ 0). The resulting kV becomes a
`BaseVoltage.nominalVoltage`. **Voltages are recorded as-is (not snapped)** so
the CIM model faithfully reflects the source; standardisation to JP classes is a
separate analysis concern (`_clean_voltage` in `build_snapped_topology.py`).

---

## 6. Levels / 段階

- **Level 1 (this export):** every feature → correct CIM class, with nominal
  voltage, regional container and geographic location. Line `ConnectivityNode`s
  are **independent per line** — a valid *equipment catalogue*, but lines are
  not yet electrically joined at shared buses.
- **Level 2 (planned):** built from the snapped topology (`GridNetwork`, which
  already carries `from_substation_id`/`to_substation_id`/`connected_bus_id`),
  giving **shared `ConnectivityNode`s**, `PowerTransformer` + `PowerTransformerEnd`,
  `EnergyConsumer` loads, and the TP/SSH/SV profiles needed for a CGMES
  power-flow case.

---

## 7. National counts / 全国件数

Generated by `scripts/export_cim.py` (matches `DATA_CATALOG.md` measured counts):

| Region | Substations | Lines | Plants | EQ objects | GL objects |
|---|--:|--:|--:|--:|--:|
| Hokkaido | 471 | 4,136 | 436 | 22,154 | 52,623 |
| Tohoku | 901 | 6,628 | 1,311 | 36,439 | 76,512 |
| Tokyo | 1,726 | 8,295 | 7,207 | 52,348 | 92,887 |
| Chubu | 1,163 | 6,589 | 3,792 | 39,342 | 117,666 |
| Hokuriku | 267 | 2,296 | 432 | 12,527 | 35,081 |
| Kansai | 902 | 3,994 | 1,518 | 23,392 | 53,026 |
| Chugoku | 531 | 3,176 | 1,173 | 18,244 | 58,523 |
| Shikoku | 258 | 1,532 | 688 | 8,944 | 25,189 |
| Kyushu | 684 | 3,314 | 2,549 | 20,651 | 63,560 |
| Okinawa | 59 | 117 | 32 | 747 | 1,724 |
| **Total** | **6,962** | **40,077** | **19,138** | **234,788** | **576,791** |

All 10 regions are well-formed XML with **zero dangling internal references**.

---

## 8. Usage / 使い方

```bash
# Generate all regions (-> dist/cim/, ~294 MB raw XML, ~32 MB zipped)
python scripts/export_cim.py

# One region
python scripts/export_cim.py --regions okinawa --out-dir dist/cim
```

The generated RDF/XML is consumable by CIM-aware tools. A tracked sample
(`dist/cim/okinawa_{EQ,GL}.xml`) is kept in the repository; the full national
set is regenerable and published as a zipped GitHub Release asset.

---

## 9. Interoperability validation / 相互運用性検証

The Level-1 export was validated against **pandapower 3.4 `cim2pp`** — an
independent, industry CGMES parser. Feeding `okinawa_{EQ,GL}.xml` to
`cim2pp.from_cim`, the parser **recognised and processed** the CIM objects:
`BaseVoltage`, `Terminal`, `ConnectivityNode` and `GeneratingUnit` were all
parsed into its internal tables. This confirms the output is genuine,
tool-readable CGMES — not merely well-formed XML.

A full pandapower *network* is **not** built from EQ+GL alone: the parser needs
the steady-state operating data (`in_service`, etc.) carried by the **TP/SSH
profiles**, which Level 1 deliberately omits (it stops at `in_service` = NaN).
Producing a solvable CGMES power-flow case (EQ + GL + TP + SSH + SV) is the
Level-2 goal (§6).

Level-1 出力を独立した CGMES パーサ **pandapower 3.4 `cim2pp`** で検証した。
`okinawa_{EQ,GL}.xml` を読ませると `BaseVoltage`・`Terminal`・`ConnectivityNode`・
`GeneratingUnit` が正しく認識・処理され、出力が単なる整形 XML ではなく **本物の
ツール可読 CGMES** であることを確認した。EQ+GL のみでは完全な pandapower
ネットワークは構築されない（`in_service` 等の定常状態を持つ TP/SSH が必要）。
求解可能な CGMES 潮流ケース（EQ+GL+TP+SSH+SV）の生成は Level 2 の課題（§6）。

---

## 10. Limitations / 制限

- **Level-1 connectivity** only (see §6): lines are not yet joined at shared
  buses; not a ready-to-solve power-flow case on its own.
- Electrical line parameters (`r`, `x`, `b`) are **not** emitted in Level 1
  (they are synthetic, voltage-class typicals — see `DATA_DICTIONARY.md`);
  they belong to the Level-2 analysis profile.
- CGMES 2.4.15 subclass gaps (geothermal, battery) handled by fallback (§3.4).
- Same caveats as the underlying OSM dataset apply (see the README disclaimer):
  operator/ownership attribution is not authoritative.
