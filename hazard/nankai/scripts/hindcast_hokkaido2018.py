#!/usr/bin/env python3
"""北海道 2018 ブラックアウトのヒンドキャスト(周波数モデル dynamics.FreqCore の検算)。

    PYTHONPATH=hazard/nankai/src python3 hazard/nankai/scripts/hindcast_hokkaido2018.py <out_png>

事象と量はすべて OCCTO「平成30年北海道胆振東部地震に伴う大規模停電に関する検証委員会 最終報告(本文)」から:
  需要 309 万 kW(発電端)/ 苫東厚真 2・4 号機 ▲116 万 kW(振動検知)/ 北本 AFC 49.62 Hz 動作・受電 7→57 万 kW /
  UFR 48.5 Hz(時限 0.1〜21 s)・48.0 Hz(0.1〜6 s)で計 ▲130 万 kW / 風力 ▲17 万 kW / 狩勝幹線ほかの事故で道東が単独系統 →
  周波数上昇で水力停止(道東 ▲37 万 kW・全体 ▲43 万 kW)、道東の残需要 ▲13 万 kW(約 1 分後に再閉路で戻る)/ 最下点 46.13 Hz /
  3:20〜3:23 苫東厚真 1 号機 ▲20 万 kW → UFR ▲16 万 kW(49.5 Hz 程度へ)/ 3:24〜3:25 1 号機停止 ▲10 万 kW → UFR ▲6 万 kW →
  火力 3 基 ▲34 万 kW 停止・水力停止(主に 46 Hz 以下)・北本運転不能 → ブラックアウト

モデル側の仮定(調整していない既定値): 慣性 H・ガバナ上げ代・負荷の周波数特性(config/dynamics_default.yaml)、
発電機の内訳(苫東厚真 1 号機 300 MW・その他火力 790 MW・水力 本体 230 MW / 道東 370 MW・道東の需要 250 MW)、
道東の分離時刻 3 秒、UFR の遮断量の配分(48.5 Hz 段 28%・48.0 Hz 段 21%)。北本の容量は 2018 年当時の 600 MW(新北本 300 MW は 2019 年運開)。
"""
from __future__ import annotations
import copy, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import numpy as np, yaml
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from nankai.dynamics import FreqCore, Link

NANKAI = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SPACING = os.environ.get("UFR_SPACING", "log")   # 時限の並べ方(linear / log)。linear はヒンドキャストで否定
T_SEP = float(os.environ.get("T_SEP", "6"))       # 道東の分離時刻[s]
DEMAND_UP = float(os.environ.get("DEMAND_UP", "104"))  # 3:09〜3:19 の需要増[MW](3:20 の北本受電 570 MW に合わせる)
plt.rcParams["font.family"] = ["Hiragino Sans"]


def build(cfg):
    cfg = copy.deepcopy(cfg)
    cfg["ufls"]["stages"] = [
        {"ratio": 48.5 / 50, "delay_s": [0.1, 21.0], "shed_frac": 0.28, "n_relays": 12, "spacing": SPACING},
        {"ratio": 48.0 / 50, "delay_s": [0.1, 6.0], "shed_frac": 0.21, "n_relays": 8, "spacing": SPACING},
    ]
    # 母線: 0 = 本体, 1 = 道東
    load = np.array([2840.0, 250.0])
    gens = [  # (名前, 種別, 母線, 出力, 最大)
        ("苫東厚真1", "thermal", 0, 300.0, 350.0),
        ("苫東厚真2・4", "thermal", 0, 1160.0, 1300.0),
        ("その他火力", "thermal", 0, 790.0, 870.0),
        ("水力(本体)", "hydro", 0, 230.0, 600.0),
        ("水力(道東)", "hydro", 1, 370.0, 450.0),
        ("風力", "wind", 0, 170.0, 300.0),
    ]
    names = [g[0] for g in gens]
    core = FreqCore(cfg, 50.0, [g[1] for g in gens], [g[2] for g in gens], [g[3] for g in gens], [g[4] for g in gens], load)
    core.links.append(Link("北本", 600.0, "external", np.array([0]), flow=70.0))
    return core, names


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "hokkaido2018_hindcast.png"
    cfg = yaml.safe_load(open(os.path.join(NANKAI, "config", "dynamics_default.yaml"), encoding="utf-8"))
    core, names = build(cfg)
    T = []; F = []; FD = []; AID = []; SHED = []
    def rec(c):
        T.append(c.t); F.append(50 + c.df[c.bus_island[0]]); FD.append(50 + c.df[c.bus_island[1]] if (c.bus_island[1] != c.bus_island[0] and not c.collapsed[1]) else np.nan)
        AID.append(c.links[0].flow); SHED.append(float((c.L0 * c.shed * c.bus_on).sum()))
    core.cfg["integration"]["calm_rocof_hz_s"] = 0.002
    # 3:08 地震
    core.trip_gens([1], "苫東厚真2・4 振動検知")
    core.run_until(T_SEP, rec)                               # 報告書の順序(脱落 → UFR 動作 → 送電線事故で道東分離)に合わせ、UFR の後に分離
    core.set_islands(np.array([0, 1]))
    core.p0[3] -= 60.0                                       # 本体の水力 ▲6 万 kW(その他の送電線事故) — 出力を下げて表す
    core.log.append((core.t, "道東が単独系統・本体の水力 ▲60 MW", 0, 0))
    core.run_until(60.0, rec)
    nadir1 = float(np.nanmin(F)); shed1 = SHED[-1]
    # 約 1 分後: 道東の送電線が再閉路、残需要が本体に戻る
    core.bus_on[1] = True; core.collapsed[1] = False; core.set_islands(np.array([0, 0]))
    core.log.append((core.t, "道東 再閉路(残需要が戻る)", 0, 0))
    # 3:09〜3:19: 需要増加(照明・テレビ等と再送電後の電圧上昇、事象10)と中給の出力増加指令。量は記録に無いので、
    # 3:20 の北本受電(観測 57 万 kW で頭打ち)に合わせて需要を足す(状態の初期化であって物理パラメータの調整ではない)
    core.run_until(120.0, rec)
    for k in range(20):
        core.L0[0] += DEMAND_UP / 20; core.run_until(120.0 + 25 * (k + 1), rec)
    core.run_until(720.0, rec)
    f_3_20 = F[-1]; aid_3_20 = AID[-1]
    # 3:20〜3:23 1 号機 ▲200 MW(徐々に)
    for k in range(18):
        core.p0[0] -= 200.0 / 18; core.run_until(720.0 + 10 * (k + 1), rec)
    core.run_until(960.0, rec)
    f_3_24 = F[-1]; shed2 = SHED[-1] - shed1
    # 3:24〜3:25 1 号機停止(▲100 MW)
    core.trip_gens([0], "苫東厚真1 停止")
    core.run_until(1100.0, rec)
    collapsed = bool(core.collapsed[0])
    t_col = next((e[0] for e in core.log if e[1] == "COLLAPSE" and e[0] > 900), None)
    print("=== 北海道 2018 ヒンドキャスト(観測 vs モデル)")
    print(f"1 回目の最下点        観測 46.13 Hz   モデル {nadir1:.2f} Hz")
    print(f"1 回目の UFR 遮断     観測 1,300 MW   モデル {shed1:,.0f} MW")
    print(f"風力の停止            観測 170 MW     モデル {'停止' if not core.online[5] else '運転継続'}")
    print(f"道東の単独系統        観測 周波数上昇→水力停止→停電  モデル {'水力停止・停電' if not core.online[4] else '継続'}")
    print(f"3:20 の周波数と北本   観測 50 Hz 付近・受電 570 MW   モデル {f_3_20:.2f} Hz・{aid_3_20:.0f} MW")
    print(f"2 回目の UFR 遮断     観測 160 MW(+60 MW)   モデル {shed2:,.0f} MW(3:24 まで)")
    print(f"ブラックアウト        観測 3:25(1 号機停止の約 1 分以内)   モデル {'全停(1 号機停止の %.0f 秒後)' % (t_col - 960) if t_col else '崩壊せず'}")
    print(f"3:24 の周波数         観測 49.5 Hz 程度(2 回目の UFR 後)   モデル {f_3_24:.2f} Hz")
    for e in core.log:
        if e[1] not in ("UFLS",):
            print(f"   t={e[0]:7.1f}s  {e[1]}  {e[2]:.0f}")
    # 図
    T = np.array(T); F = np.array(F)
    fig, ax = plt.subplots(2, 1, figsize=(12, 7), gridspec_kw={"height_ratios": [2.2, 1]}, sharex=False)
    m = T <= 60
    ax[0].plot(T[m], F[m], color="#c0392b", lw=2, label="モデル(本体)")
    ax[0].plot(T[m], np.array(FD)[m], color="#2980b9", lw=1.2, ls="--", label="モデル(道東の単独系統)")
    ax[0].axhline(46.13, color="k", lw=1, ls=":"); ax[0].text(59, 46.2, "観測の最下点 46.13 Hz", ha="right", fontsize=10)
    for y, s in ((49.62, "北本 AFC 49.62 Hz"), (48.5, "UFR 48.5 Hz"), (48.0, "UFR 48.0 Hz"), (46.0, "水力の多く 46.0 Hz")):
        ax[0].axhline(y, color="#999", lw=0.6); ax[0].text(0.5, y + 0.05, s, fontsize=9, color="#666")
    ax[0].set_ylim(45.5, 53.5); ax[0].set_xlim(0, 60); ax[0].set_ylabel("周波数 [Hz]"); ax[0].set_xlabel("地震から [秒]")
    ax[0].set_title("1 回目の周波数低下(3:08〜3:09)"); ax[0].legend(loc="upper right")
    ax[1].plot(T / 60, F, color="#c0392b", lw=1.5); ax[1].set_ylim(44, 52); ax[1].set_xlabel("地震から [分]"); ax[1].set_ylabel("Hz")
    ax[1].axvline(12, color="#999", lw=0.6); ax[1].axvline(16, color="#999", lw=0.6)
    ax[1].text(12.1, 51.2, "3:20 1 号機 出力低下", fontsize=9); ax[1].text(16.1, 51.2, "3:24 1 号機 停止", fontsize=9)
    ax[1].set_title("3:08〜3:26(観測は 3:25 に全停。モデルは最終段で UFR が約 100 MW 多く残り回復する)")
    fig.tight_layout(); fig.savefig(out, dpi=130)
    print("figure", out)


if __name__ == "__main__":
    main()
