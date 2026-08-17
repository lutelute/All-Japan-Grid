"""L_DB: 地点需要(観測)の需要ビューとバス対応付け(2026-08-17 並列キャンペーン).

point_demand.csv(変圧器バンク潮流実績の統計)から「需要」として使える集合を作る:
  - 二次kV ≤ 22(配電用バンク)のみ。kikan層(500/275)は階級間融通なので除外
  - peak_mw ≤ 0(年間逆潮=発電系)を除外
  - 変電所単位に複数バンクを合算(mean_mwの和=年平均受電)

バス対応付けの防御(罠14: 同名別所):
  - 事業者→zoneの制約付き(東北の観測は tohoku zone のバスにのみ当てる)
  - 正規化名の一意一致のみ(複数候補は不採用・件数を帳簿に出す)
  - エイリアス台帳(config/utility_name_aliases.yaml)を通す
"""
from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CSV = ROOT / "data/external/system_disclosure/normalized/point_demand.csv"
ALIAS = ROOT / "config/utility_name_aliases.yaml"

UTIL_ZONE = {"tohoku": "tohoku", "chubu": "chubu", "hokuriku": "hokuriku",
             "chugoku": "chugoku", "shikoku": "shikoku", "kyushu": "kyushu",
             "okinawa": "okinawa", "kansai": "kansai", "tokyo": "tokyo",
             "hokkaido": "hokkaido"}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"配変[0-9]+号$", "", s)          # 沖縄「与那原配変4号」→与那原
    s = re.sub(r"(変電所|開閉所|電力所|配電変電所).*$", "", s)
    s = re.sub(r"[0-9]+kV$", "", s)
    return s


def load_point_demand() -> dict[tuple[str, str], float]:
    """{(zone, 正規化変電所名): 年平均需要MW} を返す(需要ビュー)。"""
    # (zone, 事業者名)→モデル名。zoneキー必須: 沖縄の大山(宜野湾)に九州用
    # 「大山→日田市」が誤適用された事故(2026-08-17)の再発防止
    alias: dict[tuple[str, str], str] = {}
    try:
        import yaml
        for a in yaml.safe_load(ALIAS.read_text(encoding="utf-8"))["aliases"]:
            alias[(a["region"], _norm(a["utility_name"]))] = _norm(a["model_name"])
    except Exception:  # noqa: BLE001
        pass
    out: dict[tuple[str, str], float] = {}
    with open(CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                sec = float(r.get("secondary_kv") or 0)
                peak = float(r.get("peak_mw") or 0)
                mean = float(r.get("mean_mw") or 0)
            except ValueError:
                continue
            if sec > 22.5 or peak <= 0 or mean <= 0:
                continue
            zone = UTIL_ZONE.get(r["utility"])
            if not zone:
                continue
            k = _norm(r["substation"])
            k = alias.get((zone, k), k)
            if not k:
                continue
            out[(zone, k)] = out.get((zone, k), 0.0) + mean
    return out


def match_buses(net, demand: dict[tuple[str, str], float]):
    """観測地点をバスへ対応付ける。

    Returns: {bus_index: mw}, ledger(dict)
    一意一致のみ採用。多層変電所は「バンク一次kVに最も近いvn_kv」…の情報は
    需要ビューに残っていないため、**その変電所の最低vn_kv(≥60kV)のバス**に置く
    (配電バンクは最下層送電バスから受電、の近似)。
    """
    by_key: dict[tuple[str, str], list[int]] = {}
    zone_names: dict[str, list[tuple[str, int]]] = {}
    for b in net.bus.index:
        nm = _norm(net.bus.at[b, "name"])
        if not nm:
            continue
        zone = net.bus.at[b, "zone"]
        by_key.setdefault((zone, nm), []).append(b)
        zone_names.setdefault(zone, []).append((nm, b))

    # 観測一次kV(包含経路の電圧階級ガード用)。豊田77kV→豊田市275kVの誤採用で導入
    obs_kv: dict[tuple[str, str], set[float]] = {}
    try:
        with open(CSV, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                z = UTIL_ZONE.get(r["utility"])
                if not z:
                    continue
                try:
                    pk = float(r.get("primary_kv") or 0)
                except ValueError:
                    continue
                if pk > 0:
                    obs_kv.setdefault((z, _norm(r["substation"])), set()).add(pk)
    except OSError:
        pass

    def kv_compatible(key: tuple[str, str], cands: list[int]) -> bool:
        """候補バス群に観測一次kVと同階級(比0.8〜1.25)のバスがあるか。観測kV不明は通す。"""
        kvs = obs_kv.get(key)
        if not kvs:
            return True
        for b in cands:
            vn = float(net.bus.at[b, "vn_kv"])
            if any(0.8 <= vn / k <= 1.25 for k in kvs if k > 0):
                return True
        return False

    def containment_cands(zone: str, obs: str) -> list[int]:
        """住所合成名への前方一致(詫間⊂詫間町詫間・南箕輪⊂南箕輪村等)。
        中間一致は別地名の偶発部分文字列(松島⊂南小松島町・番町⊂浮津二番町で実証)
        のため前方のみ。方角接頭辞(春近⊂東春近)は個別検証してエイリアス台帳で扱う。
        罠10対策: obs≥2文字・前方一致先は一意の正規化名のみ採用。"""
        if len(obs) < 2:
            return []
        hit_names = {nm for nm, _ in zone_names.get(zone, [])
                     if nm.startswith(obs) and nm != obs}
        if len(hit_names) != 1:
            return []
        nm = hit_names.pop()
        return by_key.get((zone, nm), [])

    def _lonlat(b):
        g = net.bus_geodata if hasattr(net, "bus_geodata") else None
        if g is not None and b in g.index:
            return float(g.at[b, "x"]), float(g.at[b, "y"])
        return None, None

    pinned: dict[int, float] = {}
    n_multi = n_miss = n_contain = 0
    for key, mw in demand.items():
        cands = by_key.get(key)
        if not cands:
            cands = containment_cands(key[0], key[1])
            if cands and not kv_compatible(key, cands):
                cands = None
            if cands:
                n_contain += 1
        if not cands:
            n_miss += 1
            continue
        # 同名別所ガード(罠14): 候補の座標広がりが2km超なら別実体の混在 → 不採用
        pts = [p for p in (_lonlat(b) for b in cands) if p[0] is not None]
        if len(pts) >= 2:
            lons = [p[0] for p in pts]
            lats = [p[1] for p in pts]
            if (max(lons) - min(lons)) > 0.022 or (max(lats) - min(lats)) > 0.018:
                n_multi += 1
                continue
        subs = [b for b in cands if float(net.bus.at[b, "vn_kv"]) >= 60]
        pool = subs or cands
        # 最低送電電圧層(配電受電の親)
        b = min(pool, key=lambda x: float(net.bus.at[x, "vn_kv"]))
        if b in pinned:
            pinned[b] += mw
        else:
            pinned[b] = mw
    ledger = {"n_obs_points": len(demand), "n_pinned_buses": len(pinned),
              "n_unmatched": n_miss, "n_ambiguous_skipped": n_multi,
              "n_containment": n_contain,
              "pinned_mw": round(sum(pinned.values()), 1)}
    return pinned, ledger
