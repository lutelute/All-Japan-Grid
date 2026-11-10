"""発電機の出力を、公表されているユニット別の発電実績で置く(介入 #63 の案・既定 OFF).

日別断面は、区域の発電を燃料別の実績の合計に合わせ、燃料の中は容量の比で発電機に配っている。どの発電所が
動いているかは入っていない。OCCTO の「ユニット別発電実績公開システム」は、認可出力 10 万 kW 以上のユニットの
30 分ごとの発電量を前日分まで公表している(2026-11-10 に確かめた。468 ユニット・265 発電所)。

ここでは発電所ごとに合算し、名前でモデルの発電機に結び、その出力を観測の値にする。結べない発電所と、
公表に無い小さい発電機は、これまでどおり燃料別の実績の残りを容量の比で受け持つ(scripts/export_day_flows.py)。

層の扱い: ユニット別の発電実績は公表値(observed・速報値)。名前の結びはこのモジュールの判断(derived)で、
結んだ相手と結び方を帳簿に残す。生の CSV は data/external(git の外)に置き、再配布しない。
出典: 電力広域的運営推進機関 ユニット別発電実績公開システム。
"""
from __future__ import annotations

import csv
import datetime as dt
import re
import unicodedata
from pathlib import Path

AREA_ZONE = {"北海道": "hokkaido", "東北": "tohoku", "東京": "tokyo", "中部": "chubu", "北陸": "hokuriku",
             "関西": "kansai", "中国": "chugoku", "四国": "shikoku", "九州": "kyushu", "沖縄": "okinawa"}
# 公表の「発電方式・燃種」→ モデルの燃料の組(scripts/export_day_flows.py の _GEN_FUEL_MAP の鍵)
FUEL_GROUP = {"原子力": "nuclear", "火力(ガス)": "gas", "火力(石炭)": "coal", "火力(石油)": "oil", "水力": "hydro"}
_OWNERS = ("株式会社", "(株)", "電源開発", "東京電力", "JERA", "関西電力", "中部電力", "東北電力", "九州電力", "中国電力",
           "四国電力", "北陸電力", "北海道電力", "沖縄電力", "相馬共同火力発電", "常磐共同火力", "共同火力発電", "共同火力")
_TAILS = ("原子力発電所", "火力発電所", "水力発電所", "発電所", "パワーステーション", "原子力", "火力")


def norm_name(s: str) -> str:
    """発電所の名前を、比べるための形にそろえる(全角半角・空白・会社名・「発電所」などの語尾・号機)。"""
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = re.sub(r"\s+", "", s)
    s = s.replace("ヶ", "ケ").replace("ｹ", "ケ")           # 袖ケ浦 と 袖ヶ浦
    s = re.sub(r"\((東北|東京|中部|北陸|関西|中国|四国|九州|北海道|沖縄)\)$", "", s)   # 「田子倉発電所(東北)」
    for w in _OWNERS:
        s = s.replace(w, "")
    # 号機・系列・軸の印を落とす: 「新1号機」「第2号機」「4号系列」「1号」「GT2号」「3G」「第1号1軸」
    s = re.sub(r"(新|第|GT)?[0-9]+号((機|系列)|[0-9]*軸)?.*$", "", s)
    s = re.sub(r"[0-9]+G$", "", s)
    changed = True
    while changed:
        changed = False
        for t in _TAILS:
            if s.endswith(t) and len(s) > len(t):
                s = s[: -len(t)]
                changed = True
    return s


def load_day(paths: list[Path], day: dt.date) -> dict:
    """その日の発電所ごとの 1 時間値。{(区域, 発電所名): {"fuel": 燃料の組か None, "mw": [24 個], "n_units": 数}}。

    CSV の列は「00:30[kWh]」〜「24:00[kWh]」(コマの終わりの時刻、30 分の発電量)。h 時台 = h:30 と (h+1):00 のコマ。
    同じ日が複数のファイルにあれば、あとのファイル(名前の順)の値を採る(速報値の差し替え)。
    """
    tgt = day.strftime("%Y/%m/%d")
    units: dict = {}
    for p in sorted(paths):
        with open(p, encoding="utf-8-sig", newline="") as f:
            rd = csv.reader(f)
            hdr = next(rd, None)
            if not hdr or "対象日" not in hdr:
                continue
            i_day, i_area, i_plant, i_unit, i_fuel = (hdr.index(k) for k in ("対象日", "エリア", "発電所名", "ユニット名", "発電方式・燃種"))
            slot = {h[:5]: i for i, h in enumerate(hdr) if re.match(r"\d{2}:\d{2}\[kWh\]", h)}
            for r in rd:
                if len(r) <= i_day or r[i_day] != tgt:
                    continue
                zone = AREA_ZONE.get(r[i_area])
                if not zone:
                    continue
                mw = []
                for h in range(24):
                    a, b = r[slot[f"{h:02d}:30"]], r[slot[f"{h + 1:02d}:00"]]
                    try:
                        mw.append((float(a) + float(b)) / 1000.0)      # 30 分の kWh 2 コマ → その 1 時間の平均 MW
                    except ValueError:
                        mw.append(None)
                units[(zone, r[i_plant], r[i_unit])] = (unicodedata.normalize("NFKC", r[i_fuel]), mw)
    plants: dict = {}
    for (zone, plant, _unit), (fuel, mw) in units.items():
        rec = plants.setdefault((zone, plant), {"fuel": FUEL_GROUP.get(fuel), "mw": [None] * 24, "n_units": 0})
        rec["n_units"] += 1
        for h, v in enumerate(mw):
            if v is not None:
                rec["mw"][h] = (rec["mw"][h] or 0.0) + v
    return plants


def find_files(root: Path) -> list[Path]:
    return sorted((root / "data" / "external" / "occto" / "hks").glob("hks_*.csv"))


def load_aliases(path: Path) -> dict:
    """名前で結べない発電所の台帳 {(区域, 公表の発電所名): モデルの発電機の名前}。無ければ空。"""
    if not path.exists():
        return {}
    import yaml
    out = {}
    for row in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("aliases") or []:
        out[(row["zone"], row["hks"])] = row["model"]
    return out


# 「含む・含まれる」で結ぶときに、燃料が食い違う相手を外すための組(公表の燃料の組 → モデルの種別)
_COMPAT = {"nuclear": {"nuclear"}, "hydro": {"hydro"},
           "gas": {"gas", "coal", "oil", "biomass", "unknown"}, "coal": {"gas", "coal", "oil", "biomass", "unknown"},
           "oil": {"gas", "coal", "oil", "biomass", "unknown"}}
CONTAINS_MIN_LEN = 3       # 短い名前の「含む」は取り違えやすい(船町 → 山川入船町指宿市発電所)
CONTAINS_CAP_RATIO = 3.0   # 観測の最大が相手の容量のこの倍を超えたら結ばない(奥美濃 → 奥美濃所内水力)


def match_plants(net, plants: dict, island: str, aliases: dict | None = None) -> tuple[dict, list]:
    """公表の発電所を、この島の網の発電機に名前で結ぶ。

    返り値 (pins, ledger)。pins = {(区域, 発電所名): [発電機の番号, …]}。ledger は発電所ごとの結び方
    (alias = 台帳 / exact = そろえた名前が同じ / contains = 片方がもう片方を含み、相手が 1 つだけ)。
    区域の本籍の島がこの島でない発電所は結ばない。そろえた名前が同じ発電機が複数あれば、全部に容量の比で配る。
    contains は、名前が 3 字以上・燃料が食い違わない・観測の最大が相手の容量の 3 倍以内のときだけ。
    """
    from src.powerflow.full_from_built import ISLAND_OF
    aliases = aliases or {}
    g = net.gen[net.gen.in_service]
    by_norm: dict = {}
    for gi, nm in zip(g.index, g["name"].astype(str)):
        by_norm.setdefault(norm_name(nm), []).append(int(gi))
    by_raw = {}
    for gi, nm in zip(g.index, g["name"].astype(str)):
        by_raw.setdefault(nm, []).append(int(gi))
    mine = {k: v for k, v in plants.items() if ISLAND_OF.get(k[0], (None,))[0] == island}
    exact_keys = {norm_name(k[1]) for k in mine}
    pins, ledger = {}, []
    for key in sorted(mine):
        zone, plant = key
        n = norm_name(plant)
        how, gis = None, []
        if key in aliases:
            gis, how = by_raw.get(aliases[key]) or by_norm.get(norm_name(aliases[key])) or [], "alias"
        elif n and n in by_norm:
            gis, how = by_norm[n], "exact"
        elif len(n) >= CONTAINS_MIN_LEN:
            # 片方がもう片方を含む相手。ほかの公表の発電所とそろえた名前が同じ相手は除く(新潟 と 東新潟 の取り違えを避ける)
            cand = [m for m in by_norm if len(m) >= CONTAINS_MIN_LEN and (n in m or m in n) and m not in exact_keys]
            ok_types = _COMPAT.get(mine[key]["fuel"])
            peak = max((v for v in mine[key]["mw"] if v is not None), default=0.0)

            def fits(m):
                idx = by_norm[m]
                if ok_types and not any(str(net.gen.at[gi, "type"]) in ok_types for gi in idx):
                    return False
                cap = sum(max(float(net.gen.at[gi, "max_p_mw"] or 0.0), 0.0) for gi in idx)
                return peak <= CONTAINS_CAP_RATIO * cap
            cand = [m for m in cand if fits(m)]
            if len(cand) == 1:
                gis, how = by_norm[cand[0]], "contains"
        if gis:
            pins[key] = gis
        ledger.append({"zone": zone, "hks": plant, "how": how,
                       "model": sorted({str(net.gen.at[gi, "name"]) for gi in gis}) if gis else None})
    return pins, ledger


def pinned_at(net, pins: dict, plants: dict, h: int) -> dict:
    """h 時の {発電機の番号: (MW, 燃料の組か None)}。発電所に発電機が複数結ばれていれば、容量の比で配る。"""
    out = {}
    for key, gis in pins.items():
        mw = plants[key]["mw"][h]
        if mw is None:
            continue
        caps = [max(float(net.gen.at[gi, "max_p_mw"] or 0.0), 0.0) for gi in gis]
        tot = sum(caps)
        for gi, c in zip(gis, caps):
            share = (c / tot) if tot > 0 else 1.0 / len(gis)
            prev = out.get(gi, (0.0, None))[0]
            out[gi] = (prev + max(mw, 0.0) * share, plants[key]["fuel"])
    return out


def apply_pins(net, pinned: dict) -> dict:
    """発電機の出力を観測の値にする。容量を超える値は容量を引き上げて載せ、引き上げた分を返す。"""
    raised = 0.0
    for gi, (mw, _fuel) in pinned.items():
        cap = float(net.gen.at[gi, "max_p_mw"] or 0.0)
        if mw > cap:
            raised += mw - cap
            net.gen.at[gi, "max_p_mw"] = mw
        net.gen.at[gi, "p_mw"] = mw
    return {"n": len(pinned), "mw": round(sum(v[0] for v in pinned.values()), 1), "raised_cap_mw": round(raised, 1)}


def rebalance_unpinned(net, zone: str, pinned: dict) -> dict:
    """燃料別の実績が無い区域で、観測の無い発電機の出力を「区域の需要 − 観測のある発電機の合計」に合わせ直す。

    容量比例の配分は区域の中で需要と釣り合わせる(balance_by_zone)。そこへ観測の出力を置くと二重になるので、
    残りの発電機を容量の比で配り直す。観測の合計が需要を超える区域(送電している区域)では、残りは 0 になる。
    """
    gz = net.gen["bus"].map(net.bus["zone"])
    if "zone_src" in net.gen.columns:
        src = net.gen["zone_src"]
        gz = gz.where(~(src.notna() & (src != "")), src)
    zm = (gz == zone) & net.gen.in_service
    pin_sum = sum(mw for gi, (mw, _f) in pinned.items() if bool(zm.get(gi, False)))
    free = zm & ~net.gen.index.isin(list(pinned))
    load = float(net.load.loc[(net.load.bus.map(net.bus["zone"]) == zone) & net.load.in_service, "p_mw"].sum())
    caps = net.gen.loc[free, "max_p_mw"].astype(float).clip(lower=0.0)
    rest = max(load - pin_sum, 0.0)
    cap_sum = float(caps.sum())
    if cap_sum > 0:
        net.gen.loc[free, "p_mw"] = caps * min(rest / cap_sum, 1.0)
    return {"load_mw": round(load, 1), "pinned_mw": round(pin_sum, 1), "rest_mw": round(rest, 1)}
