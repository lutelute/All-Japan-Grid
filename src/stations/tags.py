"""OSM の電力タグの読み方 — 1 本の way を電圧ごとの回線集合に分ける。

All-EU-Grid ``all_eu_grid/tags.py``(2026-10-07 時点)から必要な部分だけを移植した。
日本向けに変えたのは周波数の扱いだけ。

* **50 Hz と 60 Hz を同じ系統 ``ac`` として扱う。** 欧州版は 50 Hz 以外を ``ac_other``
  として別の電圧階級にする。日本では西日本の線に ``frequency=60`` が付き、同じ変電所の
  無タグの線とは同じ母線に入る。欧州版のままだと、タグの有無だけで 1 つの 154 kV
  階級が 2 つに割れる。周波数変換所(佐久間・新信濃・東清水・飛騨信濃)の 50/60 Hz
  の両側は、OSM の node を共有しない限り別の接続点のまま残るので、同じ階級 ID に
  入っても電気的につながったことにはならない(``views.analyse`` の ``tn_mapped`` に出る)。
* 鉄道の 16.7 Hz(欧州の DB Energie 等)は日本に無いが、タグがあれば ``rail`` として
  分ける規則は残した。事業者名から鉄道系統を推す規則は欧州固有なので外した。

電圧の単位は常に V(OSM の約束)。``66000.0`` は 66 kV、``6600`` は 6.6 kV。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

RAIL_FREQS = (16.7, 16.67, 16.66, 16.6)
GRID_FREQS = (50.0, 60.0)

SRC_CIRCUITS = "circuits"          # 位置の揃った circuits、または曖昧さのない単一値
SRC_CABLES = "cables"              # cables から(三相交流 3 本で 1 回線、鉄道・直流は 2 本)
SRC_DEFAULT = "default"            # 読めるものが無い → 1


def split_list(raw: object) -> list[str]:
    """OSM の複数値タグを ``;`` で分ける(空要素も残す)。"""
    if raw is None:
        return []
    s = str(raw).strip()
    if not s:
        return []
    return [p.strip() for p in s.split(";")]


def _to_float(s: str) -> float | None:
    try:
        return float(s.replace(",", "."))
    except (ValueError, AttributeError):
        return None


def parse_voltage_kv(part: str) -> float | None:
    """電圧 1 トークン(V)→ kV。正でなければ None。

    ``66000.0`` を 660 kV と読むような、数字だけを抜き出して連結する読み方はしない
    (SubSLD の ``_vclasses`` で見つかった潜在不具合、docs/reports/
    station_node_breaker_adoption_2026-10-07.md)。
    """
    v = _to_float(part)
    if v is None or v <= 0:
        return None
    return v / 1000.0


def parse_voltages_kv(raw: object) -> list[float | None]:
    """位置を保った電圧の並び(読めないトークンは None)。"""
    return [parse_voltage_kv(p) for p in split_list(raw)]


def parse_frequency(part: str) -> float | None:
    return _to_float(part)


def _aligned(values: list[str], n: int, i: int) -> str | None:
    """n 個の集合と並びが揃うときは i 番目、単一値ならそれを返す。"""
    if len(values) == n:
        return values[i]
    if len(values) == 1:
        return values[0]
    return None


def _int_or_none(s: str | None) -> int | None:
    if s is None:
        return None
    v = _to_float(s)
    if v is None or v <= 0 or v != int(v):
        return None
    return int(v)


def classify_freq(freq: float | None) -> str:
    """'ac' | 'rail' | 'dc' | 'ac_other'。日本の 50 Hz・60 Hz・無タグは 'ac'。"""
    if freq is None:
        return "ac"
    if freq == 0:
        return "dc"
    if any(abs(freq - r) < 0.05 for r in RAIL_FREQS):
        return "rail"
    if any(abs(freq - f) < 0.5 for f in GRID_FREQS):
        return "ac"
    return "ac_other"


@dataclass
class CircuitSet:
    """1 本の way が運ぶ 1 つの電圧系統。"""
    kv: float | None
    system: str               # ac | rail | dc | ac_other
    circuits: int
    circuits_src: str         # circuits | cables | default
    frequency: float | None

    def to_dict(self) -> dict:
        return asdict(self)


def circuit_sets(tags: dict) -> list[CircuitSet]:
    """power=line/cable の way を電圧ごとの回線集合に分ける。

    * ``voltage`` がタグ順に集合を決める。読めなければ ``kv=None`` の 1 集合。
    * ``frequency`` / ``circuits`` / ``cables`` は、並びの長さが集合の数と同じなら位置で、
      単一値なら全集合に当てる。ただし複数電圧の way の単一 ``circuits`` は
      (合計か電圧ごとか)曖昧なので当てず、``cables`` を試す。
    """
    volts = parse_voltages_kv(tags.get("voltage"))
    if not volts:
        volts = [None]
    n = len(volts)
    freqs = split_list(tags.get("frequency"))
    circs = split_list(tags.get("circuits"))
    cabs = split_list(tags.get("cables"))

    out: list[CircuitSet] = []
    for i, kv in enumerate(volts):
        f_raw = _aligned(freqs, n, i)
        freq = parse_frequency(f_raw) if f_raw is not None else None
        system = classify_freq(freq)

        c = None
        src = SRC_DEFAULT
        if len(circs) == n or (len(circs) == 1 and n == 1):
            c = _int_or_none(circs[i] if len(circs) == n else circs[0])
            if c is not None:
                src = SRC_CIRCUITS
        if c is None:
            cab = _int_or_none(_aligned(cabs, n, i) if (len(cabs) == n or n == 1) else None)
            per = 3 if system in ("ac", "ac_other") else 2
            if cab is not None and cab % per == 0:
                c = cab // per
                src = SRC_CABLES
        if c is None:
            c = 1
            src = SRC_DEFAULT
        out.append(CircuitSet(kv=kv, system=system, circuits=c,
                              circuits_src=src, frequency=freq))
    return out
