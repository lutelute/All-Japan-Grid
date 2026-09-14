#!/usr/bin/env python3
"""D4 curated records: Cabinet Office damage-estimation parameters that are printed as numbers.

Writes damage_functions.jsonl and missing_D4.jsonl. Quotes are contiguous runs of the PDF
text layer (whitespace removed); build_db.py verifies them after NFKC normalisation.
Table cells were paired using word coordinates where the text layer order is ambiguous.
"""
import json
import sys
from pathlib import Path

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "external/hazard_support/records"

NANKAI25 = "https://www.bousai.go.jp/jishin/nankai/taisaku_wg_02/pdf/sanko_gaiyo.pdf"
T_N25 = "令和7年3月 南海トラフ巨大地震の被害想定項目及び手法の概要(中央防災会議)"
SYUTO05 = "https://www.bousai.go.jp/kaigirep/chuobou/senmon/shutochokkajishinsenmon/15/pdf/shiryou3.pdf"
T_S05 = "首都直下地震に係る被害想定手法について 資料3(内閣府, 首都直下地震対策専門調査会第15回 2005-02-25)"
SYUTO25 = "https://www.bousai.go.jp/jishin/syuto/higaisotei/pdf/r7houkokusho4.pdf"
T_S25 = "令和7年12月19日 首都直下地震の被害想定項目及び手法の概要(首都直下地震モデル・被害想定手法検討会)"
OKAYAMA = "https://www.pref.okayama.jp/uploaded/life/826156_7804116_misc.pdf"
T_OK = "岡山県 地震・津波被害想定 手法編(内閣府2006年手法の転記を含む)"

rows = []


def add(**kw):
    rows.append(kw)


# --- thermal plant stop rates (2025 Nankai method overview, PDF page 43 = printed 42)
times = ["直後", "1日後", "3日後", "1週間後", "2週間後", "3週間後", "1ヶ月後", "5週間後", "6週間後", "7週間後",
         "2ヶ月後", "3ヶ月後", "4ヶ月後", "8か月後", "9か月後", "11か月後", "12か月後"]
shake = {
    "震度4未満": [0] * 17,
    "震度4": [0] * 17,
    "震度5弱": [8, 4] + [0] * 15,
    "震度5強": [20, 7, 2, 1] + [0] * 13,
    "震度6弱": [90] * 6 + [23, 6] + [0] * 9,
    "震度6強": [90] * 6 + [23, 6] + [0] * 9,
    "震度7": [100] * 16 + [0],
}
tsunami = {
    "浸⽔なし": [0] * 17,
    "浸⽔深0.3m以上1m未満": [100] * 12 + [0] * 5,
    "浸⽔深1m以上": [100] * 14 + [0] * 3,
}
for kind, table, label in [("thermal_plant_stop_rate_shaking", shake, "揺れによる火力発電所の停止率（震度別）"),
                           ("thermal_plant_stop_rate_tsunami", tsunami, "津波による火力発電所の停止率（浸水深別）")]:
    for cls, vals in table.items():
        quote = cls + "".join(f"{v}%" for v in vals)
        for t, v in zip(times, vals):
            add(kind=kind, parameter=f"{cls.replace('⽔', '水')} @ {t}", value=v / 100, value_as_published=f"{v}%",
                unit="fraction of plants stopped", applies_to="旧一般電気事業者(自社+関連会社)の火力発電所。その他の火力・新エネも同等と想定",
                source_title=T_N25, source_url=NANKAI25, page="PDF p.43 (印刷ページ42)",
                cell=f"{label}: 行={cls} 列={t}", quote=quote,
                note="出典注: 経済産業省『平成26年度災害に強い電気設備検討調査』のテーブルを使用")

add(kind="distribution_pole_damage_tsunami", parameter="浸水エリア内の電柱等被害率(東日本大震災・東北電力管内実績)",
    value=0.163, value_as_published="16.3％", unit="fraction", applies_to="津波浸水エリア内の架空配電設備(電柱=支持物)",
    source_title=T_N25, source_url=NANKAI25, page="PDF p.42 (印刷ページ41)",
    quote="浸水エリア内での被害率は16.3％であった",
    note="知見として記載。2025手法の算定式そのものの係数とは明記されていない")
add(kind="building_collapse_shaking", parameter="時間差地震で1回目に半壊した建物の2回目の全壊率",
    value=0.5, value_as_published="計測震度が0.5高い場合と同じ全壊率", unit="JMA instrumental intensity offset",
    applies_to="1回目の地震で半壊となった建物", source_title=T_N25, source_url=NANKAI25, page="PDF p.10 (印刷ページ9)",
    quote="※計測震度が0.5高い場合と同じ全壊率を設定。")
add(kind="building_collapse_shaking", parameter="被害率曲線の区分数(木造/S造/RC・SRC造の建築年次区分)",
    value=None, value_as_published="木造６区分／Ｓ造２区分／ＲＣ・ＳＲＣ造３区分", unit=None,
    applies_to="揺れによる建物被害(2025南海手法)", source_title=T_N25, source_url=NANKAI25, page="PDF p.5",
    quote="構造別、建築年次別（木造６区分／Ｓ造２区分／ＲＣ・ＳＲＣ造３区分）に計算",
    note="曲線そのものは図(ラスター画像)のみで数値パラメータは本文に無い")

# --- 2005 Capital-quake method (shiryou3.pdf): pole damage formulas (PDF page 19)
add(kind="distribution_pole_damage_building_collapse", parameter="建物全壊による電柱折損率の係数",
    value=0.17155, value_as_published="０．１７１５５×木造建物全壊率", unit="poles broken per pole, multiplied by wooden total-collapse ratio",
    applies_to="非延焼エリアの電柱(阪神淡路の実態による)", source_title=T_S05, source_url=SYUTO05, page="PDF p.19 (印刷ページ18)",
    quote="建物全壊による電柱折損率＝０．１７１５５×木造建物全壊率（阪神淡路の実態による）")
for inten, v, pub, q in [("震度7", 0.008, "０．８％", "０．８％震度７"), ("震度6", 0.00056, "０．０５６％", "０．０５６％震度６"),
                         ("震度5", 0.0000005, "０．００００５％", "０．００００５％震度５")]:
    add(kind="distribution_pole_damage_shaking", parameter=f"揺れによる電柱折損率 {inten}", value=v, value_as_published=pub,
        unit="fraction of poles", applies_to="電柱(非延焼エリア)", source_title=T_S05, source_url=SYUTO05,
        page="PDF p.19 (印刷ページ18)", cell="表『揺れによる電柱折損率』(縦書き配置。値と震度の対応は語のx座標一致で確認)",
        quote=q)
add(kind="underground_equipment_damage_building_collapse", parameter="建物全壊による地中設備の路上設置機器の損壊係数",
    value=0.005, value_as_published="建物全壊率×損壊係数（＝0.005）", unit="multiplier on building total-collapse ratio",
    applies_to="地中配電設備の路上設置機器", source_title=T_S05, source_url=SYUTO05, page="PDF p.19 (印刷ページ18)",
    quote="建物全壊による地中設備の路上設置機器の損壊率＝建物全壊率×損壊係数（＝0.005）")
add(kind="building_collapse_shaking", parameter="全壊率テーブルの関数形",
    value=None, value_as_published="正規分布の累積確率密度関数", unit=None,
    applies_to="2005年首都直下手法 木造3区分(S37以前/S38～S55/S56以降)・非木造3区分",
    source_title=T_S05, source_url=SYUTO05, page="PDF p.6 (印刷ページ5)",
    quote="建物が全壊するときの震度が正規分布に従うと仮定（全壊率テーブルに正規分布の累積確率密度関数を使用）。",
    note="平均・標準偏差の数値は資料に記載なし")
for struct, vals, page, q in [("木造", (0.71, 0.50, 0.11), "PDF p.6 (印刷ページ5)", "（推計震度6.4のとき）71％50％11％"),
                              ("非木造", (0.15, 0.11, 0.03), "PDF p.7 (印刷ページ6)", "15％11％3％（推計震度6.4のとき）")]:
    for era, v in zip(["旧築年", "中築年", "新築年"], vals):
        add(kind="building_collapse_shaking", parameter=f"{struct}全壊率 @推計震度6.4 {era}", value=v,
            value_as_published=f"{round(v * 100)}％", unit="fraction", applies_to=f"2005年首都直下手法 {struct} {era}",
            source_title=T_S05, source_url=SYUTO05, page=page, cell="全壊率テーブル図の注記値",
            quote=q, note="3つの数値と築年区分の対応は図中の曲線位置(古い築年ほど高い)による判読で、本文に対応表は無い")

# --- 2025-12 Capital-quake method: same pole-damage knowledge statement
add(kind="distribution_pole_damage_shaking", parameter="揺れによる電柱被害率の位置付け(2025首都直下)",
    value=None, value_as_published="揺れによる被害率は、従来手法よりも小さな値となっている", unit=None,
    applies_to="東日本大震災の知見", source_title=T_S25, source_url=SYUTO25, page="PDF p.39 (印刷ページ38)",
    quote="揺れによる被害率は、従来手法よりも小さな値となっている。",
    note="新しい係数値は本概要に記載なし")

# --- Okayama (prefecture document transcribing the 2006 Cabinet Office method)
add(kind="distribution_pole_damage_building_collapse", parameter="電柱被害本数式(建物倒壊巻き込まれ)", value=0.17155,
    value_as_published="電柱被害本数＝0.17155×木造建物全壊率×電柱本数", unit="coefficient",
    applies_to="阪神・淡路大震災の実態に基づく式", source_title=T_OK, source_url=OKAYAMA, page="PDF p.48 (印刷ページ44)",
    quote="電柱被害本数＝0.17155×木造建物全壊率×電柱本数",
    note="県資料は『内閣府中央防災会議 東南海、南海地震等に関する専門調査会(2006年)での手法を用いる』と記載")
add(kind="distribution_pole_damage_shaking", parameter="表4.3.2 揺れによる電柱折損率(震度7/6強・6弱/5強・5弱)", value=None,
    value_as_published="震度７ 0.8% / 震度６強・６弱 0.056% / 震度５強・５弱 0.00005%", unit="fraction of poles",
    applies_to="岡山県手法(2006年内閣府手法の転記)", source_title=T_OK, source_url=OKAYAMA, page="PDF p.48 (印刷ページ44)",
    quote="震度７0.8%震度６強・６弱0.056%震度５強・５弱0.00005%")
add(kind="outage_per_broken_pole", parameter="電柱被害1本当たりの停電軒数", value=10.975, value_as_published="10.975",
    unit="customers per damaged pole", applies_to="神奈川県(2009)が1995年兵庫県南部地震の実績から設定した値を岡山県が採用",
    source_title=T_OK, source_url=OKAYAMA, page="PDF p.48 (印刷ページ44)",
    quote="電柱被害1本当たりの停電軒数は、神奈川県(2009)が1995年兵庫県南部地震での実績に基づいて設定した10.975を用いて算出する。",
    note="一次の神奈川県(2009)資料は未取得")
add(kind="restoration_rate", parameter="電柱復旧効率の想定(1班あたり)", value=3, value_as_published="1 班3 本/日程度",
    unit="poles per crew per day", applies_to="岡山県想定での確認用の仮定(内閣府2013の復旧推移と矛盾しないことを確認)",
    source_title=T_OK, source_url=OKAYAMA, page="PDF p.49 (印刷ページ45)", quote="1 班3 本/日程度の復旧効率を想定",
    note="県の想定値であり実績ではない")

# --- 2026-09-14 追加探索(team-lead依頼): 内閣府以外の一次資料での木造全壊率曲線の数値
SHIZ = "https://www.pref.shizuoka.jp/_res/projects/default_project/_page_/001/029/868/dai3henkaradai5hen.pdf"
T_SHIZ = "静岡県第4次地震被害想定(第一次報告) 第3編から第5編 (被害想定手法)"
GIROJ = "https://www.giroj.or.jp/publication/earthquake_research/No37_3.pdf"
T_GIROJ = "損害保険料率算出機構 地震保険研究37 第III章 被害予測手法の整理"
add(kind="building_collapse_shaking", parameter="中央防災会議(2012)木造全壊率関数の適用上限(計測震度)", value=7.0,
    value_as_published="計測震度7.0 までを適用限界", unit="JMA instrumental intensity",
    applies_to="中央防災会議(2012)の木造建物被害関数。7.0以上は被害率一定", source_title=T_SHIZ, source_url=SHIZ,
    quote="中央防災会議（2012）では計測震度7.0 までを適用限界としており、7.0 以上は被害率を一定としている。",
    note="静岡県は7.0以上を外挿で設定と記載。曲線の数値パラメータは本資料にも無い(図III-1.4のみ)")
add(kind="building_collapse_shaking", parameter="中央防災会議(2012)木造被害関数の建築年次区分(静岡県資料の記載)", value=None,
    value_as_published="旧築年(1961年以前)/中築年2区分(1962-71/1972-81)/新築年3区分(1982-89/1990-2001/2002以降)", unit=None,
    applies_to="中央防災会議(2012)", source_title=T_SHIZ, source_url=SHIZ,
    quote="中央防災会議（2012）では旧築年（1961 年以前）、中築年２区分（1962-71 年／1972-81 年）、新築年３区分（1982-89 年／1990-2001 年／2002 年以降）ごとに、計測震度を横軸とする被害関数を設定している。",
    note="区分境界は資料により1年ずれる(GIROJ・東京都2022は1962年以前/1963-71/1972-80/1981-89…)。原文どおり記録")
add(kind="building_collapse_shaking", parameter="中央防災会議系の木造全壊率関数形 P(I)=Φ((I-λ)/ζ) のパラメータ定義", value=None,
    value_as_published="λ,ζ: 計測震度Iの平均値および標準偏差", unit=None,
    applies_to="中央防災会議(2001〜2013)手法を採用した自治体(GIROJの整理)", source_title=T_GIROJ, source_url=GIROJ,
    quote="𝜆,𝜁 ：𝐼の平均値および標準偏差",
    note="λ,ζの数値は同資料にも無い(図Ⅲ-1-1-1/1-1-2のみ)。数値表があるのは村尾・山崎(2000,2002)のPGV版(表Ⅲ-1-1-1)で計測震度版ではない")
add(kind="building_collapse_shaking", parameter="中央防災会議(2013)木造全壊率曲線の建築年次6区分(GIROJの整理)", value=None,
    value_as_published="旧築年1962年以前/中築年1963～1971年・1972～1980年/新築年1981～1989年・1990～2001年・2002年以降", unit=None,
    applies_to="中央防災会議(2013)", source_title=T_GIROJ, source_url=GIROJ,
    quote="旧築年：1962年以前中築年：1963～1971年 1972～1980年新築年：1981～1989年 1990～2001年 2002年以降")

missing = [
    dict(dataset="D4", item="木造全壊率曲線の数値(計測震度に対する平均・標準偏差、または震度別数値表)を内閣府以外の一次資料で探索(2026-09-14追加)",
         searched=[
             "https://www.bousai.go.jp/jishin/nankai/taisaku_wg/8/pdf/sub2.pdf (内閣府2012 南海 手法概要 参考資料2: PDF p.4 図のみ)",
             SHIZ + " (静岡県第4次: PDF p.10 図III-1.4のみ。本文は中防2012踏襲・7.0上限の記述)",
             "https://www.pref.shizuoka.jp/_res/projects/default_project/_page_/001/029/868/sankou.pdf (静岡県 参考: 該当なし)",
             "https://www.bousai.metro.tokyo.lg.jp/_res/projects/default_project/_page_/001/000/401/assumption.part3.pdf (東京都2012 第3部: PDF p.6 図のみ・ベクター図)",
             "https://www.bousai.metro.tokyo.lg.jp/_res/projects/default_project/_page_/001/021/571/20220525/n/06n.pdf (東京都2022 6章: PDF p.5 図のみ・ベクター図、中防新築年①〜③の参考曲線を含む)",
             "https://www.klnet.pref.kanagawa.jp/g_archives/rest/media?cls=med02&pkey=00000794 (神奈川県: 木造6区分は図のみ。数値表は非木造PGV版)",
             "https://www.pref.kanagawa.jp/documents/16375/2syou02.pdf (神奈川県 更新手法: 図のみ)",
             "https://www.pref.mie.lg.jp/common/content/000028314.pdf (三重県2014: PDF p.4 図のみ)",
             OKAYAMA + " (岡山県 手法編: 図2.2.2(1)のみ)",
             "https://www.pref.kochi.lg.jp/doc/2025050100140/file_contents/file_20255154145719_4.pdf (高知県2025: 内閣府R7手法採用の記述のみ)",
             "https://www.pref.osaka.lg.jp/documents/2473/5_shiryou_3.pdf (大阪府 検討部会資料3: 結果と注記のみ)",
             "https://www.pref.wakayama.lg.jp/prefg/011400/d00153668_d/fil/wakayama_higaisoutei.pdf (和歌山県H26: 結果の要約のみ)",
             GIROJ + " (GIROJ地震保険研究37: 関数形と区分のみ)",
             "https://www.pref.aichi.jp/soshiki/bosai/r8higaiyosoku.html ほか愛知県: Incapsulaのボット対策で自動取得不可(回避していない)",
             "WebSearch: 木造 全壊率 計測震度 正規分布 平均値 標準偏差 建築年次 / \"全壊率テーブル\" 木造 計測震度 数値 表 ほか",
         ],
         note="数値表・パラメータは見つからず、いずれも曲線の図のみ。東京都2012/2022の曲線はベクター図なので座標抽出で数値化はできるが、図からの読み取り値になるため実施していない(採否はオーナー判断)。横浜市・徳島県の手法資料は未確認。愛知県は手動ブラウザでの確認が必要"),

    dict(dataset="D4", item="内閣府(2012/2013南海・2013首都直下・2025南海)木造全壊率曲線の数値パラメータ(建築年次6区分)",
         searched=[NANKAI25 + " PDF p.6-7(曲線はラスター画像のみ)", SYUTO25,
                   "https://www.bousai.go.jp/jishin/syuto/taisaku_wg/pdf/syuto_wg_butsuri.pdf",
                   "https://www.bousai.go.jp/jishin/nankai/taisaku_wg/pdf/20120829_higai.pdf", SYUTO05, OKAYAMA,
                   "https://www.pref.mie.lg.jp/common/content/000028314.pdf",
                   "WebSearch: 中央防災会議 木造 全壊率曲線 パラメータ 平均値 標準偏差 計測震度"],
         note="いずれも図のみで平均・標準偏差や震度別数値表は本文に無い。図はラスター画像のため厳密なデジタル化は不可。数値が要る場合は内閣府への照会か、数値表を公開した県資料の特定が必要"),
    dict(dataset="D4", item="2025南海手法の電柱折損率(揺れ)の新係数",
         searched=[NANKAI25 + " PDF p.42-43", SYUTO25 + " PDF p.39-40"],
         note="概要資料には16.3%(津波浸水域の実績)と『従来手法より小さい』旨のみ。係数値は非公開(詳細手法資料は未発見)"),
    dict(dataset="D4", item="神奈川県(2009)の電柱1本当たり停電軒数10.975の一次資料",
         searched=[OKAYAMA], note="岡山県手法編での引用のみ確認"),
]

OUT.mkdir(parents=True, exist_ok=True)
with (OUT / "damage_functions.jsonl").open("w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
with (OUT / "missing_D4.jsonl").open("w", encoding="utf-8") as f:
    for r in missing:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("damage_functions", len(rows), "missing", len(missing))
