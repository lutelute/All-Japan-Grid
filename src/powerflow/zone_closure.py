"""区域の収支を、公表されている連系線の潮流に合わせる(介入 #62 の案・既定 OFF).

日別断面(scripts/export_day_flows.py)は、区域ごとに需要を実績に合わせ、発電を燃料別の実績で
置き換える。ところが次の場合に、区域の(発電 − 需要)が実際の受け渡しからずれ、ずれた分を
基準の母線(スラック)1 点が肩代わりしていた(2026-11-08 の 12 時で 東 3.7 GW・西 2.0 GW・北海道 0.6 GW):

  - 燃料別の実績が無い区域・時刻(東北は約 2 か月遅れ)。容量比例の配分は区域の中で需要と釣り合わせる
    ので、域外への送電(東北 → 東京で約 5 GW)が入らない
  - 実績の出力がモデルの容量を超えて載らない分(帳簿の clipped)
  - 主系統につながらない孤立片の需要(孤立片ごとのスラックが賄う)

区域の境を流れる電力は OCCTO が公表している(連系線の潮流、5 分値)。区域の中の発電機の出力を、
「発電 − 需要 = 域外へ出す量」になるように出力比で配り直す。線路の潮流には合わせない(合わせるのは
区域の境の公表値だけ)ので、線路の潮流実績との一致は、この直しとは独立な確かめになる。

層の扱い: 連系線の潮流は公表値(observed)、配り直した発電機の出力は計算値(derived)。
"""
from __future__ import annotations

import csv
import datetime as dt
import json
from pathlib import Path

# 連系線の名前(OCCTO の表記)→ 鍵。順方向(正)の向きは OCCTO の定義:
#   北本 = 北海道→東北 / 相馬双葉 = 東北→東京 / FC = 東京→中部 / 関西中国 = 関西→中国 /
#   阿南紀北 = 関西→四国 / 本四 = 中国→四国 / 関門 = 中国→九州
# フェンスは 3 つで中部・北陸・関西の輪を表す(2026-11-09〜10 の 92 コマで 中部 − 北陸 − 関西 の中央値 6 MW):
#   中部フェンス = 中部から出る向きが正 / 北陸フェンス = 北陸へ入る向きが正 / 関西フェンス = 関西へ入る向きが正
TIE_KEYS = {
    "北海道・本州間電力連系設備": "hokuhon",
    "相馬双葉幹線": "soma",
    "周波数変換設備": "fc",
    "西播東岡山線・山崎智頭線": "kansai_chugoku",
    "関西-中国（西）": "kansai_chugoku_w",     # 公表 04(計画潮流)は 2 本に分けて出す
    "関西-中国（東）": "kansai_chugoku_e",
    "阿南紀北直流幹線": "anan_kihoku",
    "本四連系線": "honshi",
    "関門連系線": "kanmon",
    "中部フェンス": "fence_chubu",
    "北陸フェンス": "fence_hokuriku",
    "関西フェンス": "fence_kansai",
}
REQUIRED = ("hokuhon", "soma", "fc", "kansai_chugoku", "anan_kihoku", "honshi", "kanmon",
            "fence_chubu", "fence_hokuriku", "fence_kansai")
# 天気で決まる電源は配り直しに使わない(夜の太陽光に出力を載せない)
WEATHER_TYPES = ("solar", "wind")


def zone_net_export(ic: dict) -> dict | None:
    """連系線の潮流(順方向が正、MW)から、区域ごとの「域外へ出す量」(MW、出す向きが正)を出す。

    ic は TIE_KEYS の鍵 → MW。足りない鍵があれば None(一部だけで収支を閉じない)。
    各社のエリア需給実績の連系線の欄(別の公表)と 2026-11-09 の 24 時刻で比べて、平均の差は
    16〜89 MW だった(docs/reports/sync_scoreboard_2026-11-10.md)。
    """
    v = dict(ic)
    if v.get("kansai_chugoku") is None and None not in (v.get("kansai_chugoku_w"), v.get("kansai_chugoku_e")):
        v["kansai_chugoku"] = v["kansai_chugoku_w"] + v["kansai_chugoku_e"]
    if any(v.get(k) is None for k in REQUIRED):
        return None
    hk, sf, fc = v["hokuhon"], v["soma"], v["fc"]
    kc, ks, cs, ck = v["kansai_chugoku"], v["anan_kihoku"], v["honshi"], v["kanmon"]
    return {
        "hokkaido": hk,
        "tohoku": sf - hk,
        "tokyo": -sf + fc,
        "chubu": -fc + v["fence_chubu"],
        "hokuriku": -v["fence_hokuriku"],
        "kansai": kc + ks - v["fence_kansai"],
        "chugoku": -kc + cs + ck,
        "shikoku": -ks - cs,
        "kyushu": -ck,
    }


def hourly_instant(stamps: dict, day: dt.date) -> list:
    """時刻の印が瞬時値のとき(OCCTO の潮流実績)の 1 時間の平均: 台形 (v(h:00) + 2 v(h:30) + v(h+1:00)) / 4。"""
    out = []
    for h in range(24):
        t0 = dt.datetime.combine(day, dt.time(h, 0))
        a, b, c = (stamps.get(t0 + dt.timedelta(minutes=m)) for m in (0, 30, 60))
        if None in (a, b):
            out.append(None)
        elif c is None:
            out.append((a + b) / 2.0)       # 最新のコマまでしか無い時刻は 2 点の平均
        else:
            out.append((a + 2.0 * b + c) / 4.0)
    return out


def _hourly_slot_end(stamps: dict, day: dt.date) -> list:
    """時刻の印がコマの終わりのとき(公表 04 の 30 分値、「00:30」が最初)の 1 時間の平均。"""
    out = []
    for h in range(24):
        t0 = dt.datetime.combine(day, dt.time(h, 0))
        a, b = (stamps.get(t0 + dt.timedelta(minutes=m)) for m in (30, 60))
        out.append(None if None in (a, b) else (a + b) / 2.0)
    return out


def load_ic_from_occto_today(path: Path, day: dt.date) -> dict | None:
    """毎時の処理が書く当日分(docs/data/flow_map/occto_today.json)から、連系線の実績の 1 時間値を読む。

    返り値 {"kind": "実績", "source": ..., "hourly": {鍵: [24 個]}}。その日が入っていなければ None。
    """
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    if day.isoformat() not in (d.get("days") or []):
        return None
    times = [dt.datetime.strptime(t, "%Y-%m-%d %H:%M") for t in d["times"]]
    hourly = {}
    for name, vals in (d.get("ic") or {}).items():
        key = TIE_KEYS.get(name)
        if not key:
            continue
        stamps = {t: float(v[0]) for t, v in zip(times, vals) if v and v[0] is not None}
        hourly[key] = hourly_instant(stamps, day)
    return {"kind": "実績", "source": "OCCTO 系統情報サービス 連系線潮流実績(5 分値 → 30 分ごとの値)", "hourly": hourly}


def load_ic_from_kohyo04(path: Path, day: dt.date) -> dict | None:
    """公表 04(連系線の運用容量・計画潮流、30 分値)の月ごとの CSV から、計画潮流の 1 時間値を読む。"""
    if not path.exists():
        return None
    tgt = day.strftime("%Y/%m/%d")
    nxt = (day + dt.timedelta(days=1)).strftime("%Y/%m/%d")
    stamps: dict[str, dict] = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.reader(f):
            if len(r) < 9 or r[0] not in (tgt, nxt):
                continue
            key = TIE_KEYS.get(r[2])
            if not key:
                continue
            try:
                hh, mm = (int(x) for x in r[1].split(":")[:2])
                v = float(r[7])          # 順方向計画潮流(MW)
            except ValueError:
                continue
            base = dt.datetime.strptime(r[0], "%Y/%m/%d")
            stamps.setdefault(key, {})[base + dt.timedelta(hours=hh, minutes=mm)] = v
    if not stamps:
        return None
    return {"kind": "計画", "source": "OCCTO 広域予備率Web公表システム 04(順方向計画潮流、30 分値)",
            "hourly": {k: _hourly_slot_end(s, day) for k, s in stamps.items()}}


def load_ic(root: Path, day: dt.date) -> dict | None:
    """その日の連系線の潮流を読む。実績(当日分)があればそれ、無ければ計画潮流(公表 04)。"""
    for got in (load_ic_from_occto_today(root / "docs/data/flow_map/occto_today.json", day),
                load_ic_from_kohyo04(root / "data/external/occto" / f"kohyo_04_{day:%Y%m}.csv", day)):
        if got and _complete(got["hourly"]):
            return got
    return None


def _complete(hourly: dict) -> bool:
    """収支を閉じるのに要る連系線がそろっていて、値のある時刻が 1 つはあるか。"""
    return any(targets_at({"hourly": hourly}, h) for h in range(24))


def targets_at(ic: dict | None, h: int) -> dict | None:
    """h 時の区域ごとの「域外へ出す量」。値が欠ける時刻は None。"""
    if not ic:
        return None
    return zone_net_export({k: (v[h] if h < len(v) else None) for k, v in ic["hourly"].items()})


def boundary_series(ic: dict | None, island: str) -> dict:
    """島の境(FC・北本)の注入の 24 時刻。scripts/export_day_flows.day_boundary_series と同じ形・同じ符号。

    収支を合わせる連系線と同じ出どころの値を使う(出どころが違うと、その差が基準の母線に残る)。
    """
    if not ic:
        return {}
    out = {}
    fc, hb = ic["hourly"].get("fc"), ic["hourly"].get("hokuhon")
    sign = {"west": 1.0, "east": -1.0}.get(island)
    if fc and sign:
        out[("chubu", "tokyo")] = [None if v is None else sign * v for v in fc]
    sign = {"east": 1.0, "hokkaido": -1.0}.get(island)
    if hb and sign:
        out[("hokkaido", "tohoku")] = [None if v is None else sign * v for v in hb]
    return out


def _spread(p, cap, amount: float):
    """amount を出力 p の比で配る。増やすときは容量 cap まで(超える分は残りに回す)。返り値 (増分, 容量を超えた分)。"""
    import numpy as np
    add = np.zeros(len(p))
    if amount <= 0:
        tot = float(p.sum())
        return (p * (amount / tot) if tot > 0 else add), 0.0
    rest = float(amount)
    for _ in range(50):
        room = np.maximum(cap - (p + add), 0.0)
        live = (p > 0) & (room > 1e-9)
        w = float(p[live].sum())
        if rest <= 1e-6 or w <= 0:
            break
        step = np.where(live, p / w * rest, 0.0)
        step = np.minimum(step, room)
        add += step
        rest -= float(step.sum())
    over = 0.0
    if rest > 1e-6:                     # 動いている発電機の容量を使い切った分は、容量を超えて載せる(帳簿に残す)
        w = float(p.sum())
        if w > 0:
            add += p / w * rest
            over = rest
    return add, over


def close_zone_balance(net, targets: dict, island: str | None = None, tol_mw: float = 1.0) -> dict:
    """主系統の中で、区域ごとの(発電 − 需要)を targets(域外へ出す量、MW)に合わせる。net.gen.p_mw を書き換える。

    - 配り先は、その区域の動いている発電機(出力 > 0)。出力の比で配る(分散スラックと同じ形)。止まっている
      発電機は動かさない。太陽光・風力は、ほかに動いている発電機があれば使わない
    - 増やす分は容量まで。動いている発電機の容量を使い切ったら、超えた分も出力比で載せ、帳簿の over_capacity_mw に書く
    - 区域の本籍の島だけで当てる(境の点が別の島の網に入っていても、そこでは当てない)
    返り値 {区域: {before_mw, target_mw, moved_mw, over_capacity_mw, n_units}}。
    """
    import numpy as np

    from src.powerflow.full_from_built import ISLAND_OF, bus_component_index

    comp = bus_component_index(net)
    g = net.gen[net.gen.in_service]
    gz = g["bus"].map(net.bus["zone"])
    if "zone_src" in g.columns:
        src = g["zone_src"]
        gz = gz.where(~(src.notna() & (src != "")), src)
    g_main = g["bus"].map(lambda b: comp.get(int(b), -1) == 0)
    ld = net.load[net.load.in_service]
    lz = ld["bus"].map(net.bus["zone"])
    l_main = ld["bus"].map(lambda b: comp.get(int(b), -1) == 0)
    ledger = {}
    for z, tgt in sorted(targets.items()):
        if island is not None and ISLAND_OF.get(z, (None,))[0] != island:
            continue
        gm = g_main & (gz == z)
        if not gm.any():
            continue
        cur = float(g.loc[gm, "p_mw"].astype(float).sum()) - float(ld.loc[l_main & (lz == z), "p_mw"].astype(float).sum())
        move = float(tgt) - cur
        rec = {"before_mw": round(cur, 1), "target_mw": round(float(tgt), 1), "moved_mw": 0.0,
               "over_capacity_mw": 0.0, "n_units": 0}
        if abs(move) > tol_mw:
            p_all = g.loc[gm, "p_mw"].astype(float)
            pick = (p_all > 0) & ~g.loc[gm, "type"].isin(WEATHER_TYPES)
            if not pick.any():
                pick = p_all > 0
            if pick.any():
                idx = p_all.index[pick.to_numpy()]
                p = net.gen.loc[idx, "p_mw"].astype(float).to_numpy()
                cap = net.gen.loc[idx, "max_p_mw"].astype(float).fillna(0.0).clip(lower=0.0).to_numpy()
                add, over = _spread(p, np.maximum(cap, p), move)
                net.gen.loc[idx, "p_mw"] = p + add
                rec.update(moved_mw=round(float(add.sum()), 1), over_capacity_mw=round(over, 1), n_units=int(len(idx)))
        ledger[z] = rec
    return ledger


def summarize(hourly: dict) -> dict:
    """時刻ごとの帳簿 {h: {区域: rec}} を、区域ごとの要約にする(出力の JSON に入れる)。"""
    out: dict = {}
    for h, zs in sorted(hourly.items()):
        for z, r in zs.items():
            s = out.setdefault(z, {"hours": 0, "moved_abs_mwh": 0.0, "moved_max_mw": 0.0, "over_capacity_mwh": 0.0})
            s["hours"] += 1
            s["moved_abs_mwh"] += abs(r["moved_mw"])
            s["moved_max_mw"] = max(s["moved_max_mw"], abs(r["moved_mw"]))
            s["over_capacity_mwh"] += r["over_capacity_mw"]
    return {z: {k: (round(v, 1) if isinstance(v, float) else v) for k, v in s.items()} for z, s in out.items()}
