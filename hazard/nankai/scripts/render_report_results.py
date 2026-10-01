#!/usr/bin/env python3
"""レポート(docs/reports/nankai_power_hazard_v0_2026-09-13.md)の §4 結果と §0 の数値を run ディレクトリから再生成する。

    PYTHONPATH=hazard/nankai/src python3 hazard/nankai/scripts/render_report_results.py <run_jshis> <run_gmpe> <report.md> <fig_dir_rel>
"""
from __future__ import annotations
import json, os, re, sys
import numpy as np, pandas as pd


def m(x):
    return f"{x/1e4:,.0f}万"


def main(R, G, report, figrel):
    cj = json.load(open(f"{R}/naikakufu_compare.json")); cg = json.load(open(f"{G}/naikakufu_compare.json"))
    sj = json.load(open(f"{R}/summary.json")); dec = pd.read_csv(f"{R}/cause_decomposition.csv")
    five = {t: cj[f"five_t{t}"] for t in (0, 1, 4, 7)}; fiveg = {t: cg[f"five_t{t}"] for t in (0, 1, 4, 7)}
    w = sj["islands"]["west"]; e = sj["islands"]["east"]; N = sj["samples"]
    tw = {r["t_days"]: r["served_frac"] for r in w["timeline"]}; te = {r["t_days"]: r["served_frac"] for r in e["timeline"]}
    sw = pd.read_csv(f"{R}/west/timeline_summary.csv"); se = pd.read_csv(f"{R}/east/timeline_summary.csv")
    pw = dict(zip(sw.t_days, sw.phys_frac)); pe = dict(zip(se.t_days, se.phys_frac)); bw = dict(zip(sw.t_days, sw.blackout_mw))
    pot_w = w["potential_vs_analysis"]; pot_e = e["potential_vs_analysis"]
    rows = ["| 時点 | 内閣府2013 基本 | 内閣府2025 基本 | 内閣府2025 陸側 | 本解析 物理停電 | 本解析 不足込み | (GMPE場 物理) |", "|---|---:|---:|---:|---:|---:|---:|"]
    for t in (0, 1, 4, 7):
        v = five[t]; rows.append(f"| {'直後' if t==0 else str(t)+'日後'} | {m(v['n2013_basic'])} | {m(v['n2025_basic'])} | {m(v['n2025_landward'])} | **{m(v['ours_phys'])}** | {m(v['ours_total'])} | {m(fiveg[t]['ours_phys'])} |")
    LAB = {"tokai": "東海", "kinki": "近畿", "sanyo": "山陽", "shikoku": "四国", "kyushu": "九州2県"}
    tab_reg = ["| 地域(需要家数) | 直後 内閣府2025/本解析 | 1日後 | 4日後 | 7日後 |", "|---|---|---|---|---|"]
    for r in LAB:
        c = cj[f"{r}_t0"]["customers"]
        tab_reg.append(f"| {LAB[r]}({m(c)}) | " + " | ".join(f"{m(cj[f'{r}_t{t}']['n2025_basic'])} / **{m(cj[f'{r}_t{t}']['ours_phys'])}**" for t in (0, 1, 4, 7)) + " |")
    dec_rows = ["| 時点 | 系統崩壊(需給) | 変電所 津波 | 変電所 揺れ | 上流孤立 | 計 |", "|---|---:|---:|---:|---:|---:|"]
    for _, r in dec.iterrows():
        dec_rows.append(f"| {('直後' if r.t_days==0 else (f'{r.t_days*24:g}h' if r.t_days<1 else f'{r.t_days:g}日'))} | {m(r.blackout)} | {m(r.site_tsunami)} | {m(r.site_shaking)} | {m(r.isolated)} | {m(r.total)} |")
    curve = ["| 島 | 指標 | 直後 | 12h | 1日 | 2日 | 4日 | 7日 | 14日 | 30日 | 90日 |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name, tlx, px in (("west(60Hz・73.9GW)", tw, pw), ("east(50Hz・55.3GW)", te, pe)):
        curve.append(f"| {name} | 受電可能(物理) | " + " | ".join(f"{px[t]:.0%}" for t in (0, 0.5, 1, 2, 4, 7, 14, 30, 90)) + " |")
        curve.append(f"| | 供給率(不足込み) | " + " | ".join(f"{tlx[t]:.0%}" for t in (0, 0.5, 1, 2, 4, 7, 14, 30, 90)) + " |")
    d7 = dec[dec.t_days == 7].iloc[0]; dmax_sh = dec.site_shaking.max()
    res = f"""## 4. 結果(既定・N={N}・west+east)

### 4.1 内閣府想定との比較(五地域の停電軒数; 本解析は west+east 合算・供給地点数換算 {m(cj['five_t0']['customers'])}、内閣府は電灯軒数 2,420〜2,470万)

{chr(10).join(rows)}

![]({figrel}/naikakufu_compare_jshis.png)

{chr(10).join(tab_reg)}

- 直後: 中部エリアは供給不足で系統崩壊(崩壊状態の需要 {bw[0.0]/w['load_mw']:.0%})。関西は若狭の原子力(5弱・scram せず)を数えると不足率がしきい値未満で崩壊しない場合が多く、内閣府の「近畿三府県の約9割」より小さい。山陽・九州は内閣府より小さい(J-SHIS 場では 5弱〜5強)。
- 1日後: 全地域で内閣府 2025 の範囲内(東海は同水準、近畿は下回る)。
- 4日後以降: 本解析が 1 桁多い。原因分解(4.3)のとおり津波浸水域の変電所と上流孤立。内閣府は津波全壊需要家を復旧対象から除外し、電柱被害の復旧(1〜2 週間)を別途見ている。**「4 日で解消」は本解析の設備モデルでは再現できない**というのが今回の主要な負の結果で、配電層と津波除外集計を入れて再評価する必要がある。

### 4.2 復旧曲線(J-SHIS 場・N={N})

{chr(10).join(curve)}

![]({figrel}/curve_west.png)

west の直後は供給率 {tw[0.0]:.0%}(受電可能 {pw[0.0]:.0%})で、差の {pw[0.0]-tw[0.0]:.0%} が供給力不足による遮断(計画停電相当)。2 日でほぼ消える(需要減と 5強以下の火力復帰)。east は静岡東部・神奈川の一部のみで {te[0.0]:.0%}→{te[1.0]:.0%}。

### 4.3 物理停電の原因分解(五地域・J-SHIS 場・N=30)

{chr(10).join(dec_rows)}

![]({figrel}/cause_decomposition_jshis.png)

系統崩壊は 2 日で消える。**2 日目以降の主役は津波浸水域の変電所(約 {d7.site_tsunami/1e4:.0f} 万軒・復旧中央値 60 日)と上流孤立(約 {d7.isolated/1e4:.0f} 万軒)**、変電所の揺れ損傷は最大 {dmax_sh/1e4:.0f} 万軒で 2 週間で消える。

### 4.4 地図

| | |
|---|---|
| ![]({figrel}/hazard_west.png) | ![]({figrel}/pout_t0_west.png) |
| J-SHIS 震度(母線)と津波浸水域内の母線(青丸 381) | 停電確率(物理) 直後: 中部エリア全域が需給崩壊 |
| ![]({figrel}/pout_t7_west.png) | ![]({figrel}/expected_days_west.png) |
| 7 日後: 沿岸の津波浸水域(大阪湾岸・伊勢湾岸・高知・徳島・広島港・大分・宮崎)に集中 | 期待停電日数(0〜90 日積分) |
| ![]({figrel}/potential_west.png) | ![]({figrel}/hazard_west_gmpe.png) |
| ポテンシャル法(B・復旧期): 電源までの経路生存率×供給余力 | 感度ケース: GMPE 合成場(内閣府基本ケースの目視近似)。J-SHIS より 1 階級強い |

GIF: `{figrel}/restoration_west.gif`(16 フレーム・停電確率(物理)の時間推移 + 復旧曲線)。動画: `{figrel}/nankai_hazard_walkthrough.mp4`。1 手ずつビューア: `{figrel}/steps_viewer.html`(556 手)。公開地図: `{figrel}/hazard_map_artifact.html`。

### 4.5 ポテンシャル法(B) vs 解析(A)

| 島 | 相関(直後, トリップ込み指標 vs 停電確率) | 相関(2日後) | 需要加重相関(2日後) | 相関(期待停電日数) |
|---|---:|---:|---:|---:|
| west | {pot_w['corr_pout_t0']:.2f} | {pot_w['corr_pout_t2']:.2f} | {pot_w['wcorr_pout_t2']:.2f} | {pot_w['corr_expected_days']:.2f} |
| east | {pot_e['corr_pout_t0']:.2f} | {pot_e['corr_pout_t2']:.2f} | {pot_e['wcorr_pout_t2']:.2f} | {pot_e['corr_expected_days']:.2f} |

需要の大きい母線ほど一致する(需要加重 {pot_w['wcorr_pout_t2']:.2f})。母線単位の相関が 0.3〜0.4 に留まるのは、(i) 経路生存率が経路長に対して積で落ちるため被災域内で 1 に飽和する、(ii) A の「上流孤立」はサンプルごとの組合せで決まり、中央値場の最良経路では捉えにくい、(iii) 系統崩壊(zone 需給)を B が持たない、ため。**用途は優先順位付け・スクリーニング**であり、確率の絶対値は A で読む。

### 4.6 GMPE 合成場との感度

GMPE 場(母線平均で J-SHIS より +0.3)では五地域の物理停電が直後 {m(fiveg[0]['ours_phys'])}・1日後 {m(fiveg[1]['ours_phys'])}・4日後 {m(fiveg[4]['ours_phys'])}・7日後 {m(fiveg[7]['ours_phys'])}(`naikakufu_compare_gmpe.png`)。直後〜1 日は内閣府 2013 基本ケースに近づき、4 日以降の乖離はさらに広がる。地震動場の選択は直後の桁を動かすが、4 日以降の乖離は場の問題ではない。

"""
    s = open(report, encoding="utf-8").read()
    a = s.index("## 4. 結果"); b = s.index("## 5. 限界")
    s = s[:a] + res + s[b:]
    # §0 の数値
    s = re.sub(r"\*\*直後 [\d,]+万軒 / 1日後 [\d,]+万軒 / 4日後 [\d,]+万軒 / 7日後 [\d,]+万軒\*\*",
               f"**直後 {five[0]['ours_phys']/1e4:,.0f}万軒 / 1日後 {five[1]['ours_phys']/1e4:,.0f}万軒 / 4日後 {five[4]['ours_phys']/1e4:,.0f}万軒 / 7日後 {five[7]['ours_phys']/1e4:,.0f}万軒**", s)
    s = re.sub(r"需要加重相関 [\d.]+\(単純相関 [\d.]+\)", f"需要加重相関 {pot_w['wcorr_pout_t2']:.2f}(単純相関 {pot_w['corr_pout_t2']:.2f})", s)
    open(report, "w", encoding="utf-8").write(s)
    print("report updated:", {t: round(five[t]["ours_phys"] / 1e4) for t in (0, 1, 4, 7)})


if __name__ == "__main__":
    main(*sys.argv[1:5])
