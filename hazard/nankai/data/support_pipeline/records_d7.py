#!/usr/bin/env python3
"""D7 curated records: past disaster restoration (outages, personnel, generator vehicles, damage).

Writes restoration_records.jsonl and missing_D7.jsonl. Quotes are contiguous runs of the source
text layer with line separators removed; build_db.py verifies them (NFKC, whitespace removed)
and fills PDF page numbers. Table columns were checked with word coordinates where noted.
"""
import json
import sys
from pathlib import Path

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "external/hazard_support/records"

METI_RWG5 = "https://www.meti.go.jp/shingikai/enecho/denryoku_gas/denryoku_gas/resilience_wg/pdf/005_04_00.pdf"
TEPCO_1031 = "https://www.tepco.co.jp/press/release/2019/pdf4/191031j0201.pdf"
TEPCO_0116 = "https://www.tepco.co.jp/press/release/2020/pdf1/200116j0101.pdf"
KEPCO_REP = "https://www.kepco.co.jp/corporate/pr/souhaiden/2018/pdf/1213_1j_02.pdf"
KYUDEN = "https://www.kyuden.co.jp/company/history/energy/disaster/disaster-1.html"
JSCE_KYU = ("https://committees.jsce.or.jp/eec2/system/files/05_H28%E7%86%8A%E6%9C%AC%E5%9C%B0%E9%9C%87%E3%81%AB%E3%81%8A%E3%81%91"
            "%E3%82%8B%E9%9B%BB%E5%8A%9B%E8%A8%AD%E5%82%99%E8%A2%AB%E5%AE%B3%E7%8A%B6%E6%B3%81%EF%BC%88%E4%B9%9D%E9%9B%BB%EF%BC%89.pdf")
HEPCO_SUM = "https://www.hepco.co.jp/info/info2018/__icsFiles/afieldfile/2018/12/21/181221a_1.pdf"
HEPCO_FULL = "https://www.hepco.co.jp/info/info2018/__icsFiles/afieldfile/2019/11/26/181221.pdf"
OCCTO_SUM = "https://www.occto.or.jp/assets/iinkai/hokkaido_kensho/files/181219_hokkaido_saishu_gaiyou.pdf"
METI_NOTO = "https://www.meti.go.jp/shingikai/sankoshin/hoan_shohi/denryoku_anzen/denki_setsubi/pdf/020_01_01.pdf"
RIKU_PRESS = "https://www.rikuden.co.jp/press/attach/26061801.pdf"
TDGC = ("https://www.tdgc.jp/information/docs/%E3%80%90%E6%9B%B4%E6%96%B0%E7%89%88%E3%80%91%E4%BB%A4%E5%92%8C6%E5%B9%B4%E8%83%BD%E7%99%BB"
        "%E5%8D%8A%E5%B3%B6%E5%9C%B0%E9%9C%87%E3%81%AB%E4%BC%B4%E3%81%86%E5%BE%A9%E6%97%A7%E3%81%AB%E5%90%91%E3%81%91%E3%81%9F%E9%9B%BB"
        "%E5%8A%9B%E5%90%84%E7%A4%BE%E3%81%AB%E3%82%88%E3%82%8B%E5%BF%9C%E6%8F%B4%E6%B4%BE%E9%81%A3%E3%81%AE%E7%8A%B6%E6%B3%81%E3%81%AB"
        "%E3%81%A4%E3%81%84%E3%81%A6%EF%BC%880214%E6%9B%B4%E6%96%B0%EF%BC%89.pdf")
RIKU_OUKYU = "https://www.rikuden.co.jp/esg_quality/attach/oukyuusouden.pdf"
RIKU_JININ = "https://www.rikuden.co.jp/esg_quality/attach/jinin.pdf"
BOUSAI_TOHOKU = "https://www.bousai.go.jp/kaigirep/chousakai/tohokukyokun/9/pdf/sub2.pdf"
BOUSAI_TOHOKU1 = "https://www.bousai.go.jp/kaigirep/chousakai/tohokukyokun/1/pdf/sub2.pdf"
CAO_2025 = "https://www.bousai.go.jp/jishin/nankai/taisaku_wg_02/pdf/sanko_gaiyo.pdf"
METI_FK1 = "https://www.meti.go.jp/shingikai/sankoshin/hoan_shohi/denryoku_anzen/denki_setsubi/pdf/015_01_00.pdf"
METI_FK2 = "https://www.meti.go.jp/shingikai/sankoshin/hoan_shohi/denryoku_anzen/denki_setsubi/pdf/015_02_00.pdf"
TOHOKU_NW_0317 = "https://nw.tohoku-epco.co.jp/news/pdf/__icsFiles/afieldfile/2022/03/17/2203170510.pdf"

LABEL = {
    "2019_typhoon15": "令和元年房総半島台風(台風15号)", "2018_typhoon21": "平成30年台風21号",
    "2018_typhoon24": "平成30年台風24号", "2016_kumamoto": "平成28年熊本地震", "2018_iburi": "平成30年北海道胆振東部地震",
    "2024_noto": "令和6年能登半島地震", "2011_tohoku": "東日本大震災(東北地方太平洋沖地震)", "2022_fukushima_oki": "令和4年福島県沖地震",
}
rows = []


def add(event, utility, metric, value, pub, unit, url, quote, date=None, approx=None, definition=None, cell=None, note=None):
    rows.append(dict(event=event, event_label=LABEL[event], utility=utility, date_or_day=date, date_verbatim=date,
                     metric=metric, value=value, value_as_published=pub,
                     approx=("約" in pub or "程度" in pub or "規模" in pub) if approx is None else approx,
                     unit=unit, definition=definition, source_url=url, cell=cell, quote=quote, note=note,
                     collected_by="records_d7.py"))


# ---------------- METI 電力レジリエンスWG 第5回 資料 (typhoon comparison tables; columns checked by word x-coordinates)
T11 = "p.11表『過去の台風被害との復旧体制の比較』列: 復旧対応人数(他電力含む)|他電力からの応援人数|高圧発電機車(他電力含む)|低圧発電機車(他電力含む)"
T12 = "p.12表『他地域からの応援規模』列: 他電力からの応援人数(延べ人数)|他電力による高圧発電機車|他電力による低圧発電機車"
T10 = "p.10表『過去の類似の災害との比較』列: 最大停電件数|ピーク時から99％の停電が復旧するまでの時間"
for ev, util, q10, out, hrs, q11, tot, oth, hv, lv, q12, oth2, hv2, lv2 in [
    ("2018_typhoon21", "関西電力", "台風21号（関西電力）約240万戸約120時間", 2400000, 120,
     "台風21号（関西電力）約12,000名約500名58台4台", 12000, 500, 58, 4, "台風21号（関西電力）約500名40台０台", 500, 40, 0),
    ("2018_typhoon24", "中部電力", "台風24号（中部電力）約180万戸約70時間", 1800000, 70,
     "台風24号（中部電力）約8,000名約200名73台3台", 8000, 200, 73, 3, "台風24号（中部電力）約200名10台０台", 200, 10, 0),
    ("2019_typhoon15", "東京電力", "台風15号（東京電力）約93万戸約280時間", 930000, 280,
     "台風15号（東京電力）約16,000名約4,000名238台122台", 16000, 4000, 238, 122, "台風15号（東京電力）約10,000名※174台30台", 10000, 174, 30),
]:
    add(ev, util, "peak_outage_households", out, f"約{out // 10000}万戸", "戸", METI_RWG5, q10, cell=T10)
    add(ev, util, "hours_peak_to_99pct_restored", hrs, f"約{hrs}時間", "時間", METI_RWG5, q10, cell=T10,
        definition="ピーク時から99％の停電が復旧するまでの時間")
    add(ev, util, "personnel_total_incl_other_utilities", tot, f"約{tot:,}名", "人", METI_RWG5, q11, cell=T11,
        definition="復旧対応人数（他電力含む）", note="ピーク人数か延べかは表に明記なし(次表は延べと注記)")
    add(ev, util, "personnel_other_utilities", oth, f"約{oth:,}名", "人", METI_RWG5, q11, cell=T11, definition="他電力からの応援人数")
    add(ev, util, "hv_generator_vehicles_incl_other_utilities", hv, f"{hv}台", "台", METI_RWG5, q11, cell=T11, approx=False,
        definition="高圧発電機車（他電力含む）", note="注記: 電源車の数値は延べ台数")
    add(ev, util, "lv_generator_vehicles_incl_other_utilities", lv, f"{lv}台", "台", METI_RWG5, q11, cell=T11, approx=False,
        definition="低圧発電機車（他電力含む）", note="注記: 電源車の数値は延べ台数")
    add(ev, util, "personnel_other_utilities_cumulative", oth2, f"約{oth2:,}名", "人", METI_RWG5, q12, cell=T12,
        definition="他電力からの応援人数（延べ人数）")
    add(ev, util, "hv_generator_vehicles_other_utilities", hv2, f"{hv2}台", "台", METI_RWG5, q12, cell=T12, approx=False)
    add(ev, util, "lv_generator_vehicles_other_utilities", lv2, f"{lv2}台", "台", METI_RWG5, q12, cell=T12, approx=False)

# ---------------- 2019 typhoon 15: TEPCO documents
U = "東京電力パワーグリッド"
add("2019_typhoon15", U, "peak_outage_households", 934900, "約934,900軒", "軒", TEPCO_1031, "最大停電軒数約934,900軒")
add("2019_typhoon15", U, "personnel_peak", 16000, "最大約16,000名", "人", TEPCO_1031, "第2非常態勢へ移行し，最大約16,000名の態勢で対応")
add("2019_typhoon15", U, "personnel_pre_event", 2300, "総勢約2,300名", "人", TEPCO_1031, "「事前」期においては総勢約2,300名")
add("2019_typhoon15", U, "outage_excluded_hard_to_restore", 120000, "約12万軒", "軒", TEPCO_1031, "復旧困難箇所の約12万軒を除き",
    note="9月10日中の復旧見通し公表時に除外した軒数")
add("2019_typhoon15", U, "poles_broken", 2000, "約2,000本", "本", TEPCO_0116, "電柱約2,000 本が折損")
add("2019_typhoon15", U, "transmission_towers_collapsed", 2, "2基", "基", TEPCO_0116, "送電鉄塔2 基が倒壊")

# ---------------- 2018 typhoon 21: Kansai verification report
U = "関西電力"
add("2018_typhoon21", U, "peak_outage_households", 1680000, "最大約168万軒", "軒", KEPCO_REP, "(9月4日21時)最大約168万軒",
    date="2018-09-04 21:00")
add("2018_typhoon21", U, "cumulative_outage_households", 2200000, "延べ220万軒", "軒", KEPCO_REP, "延べ220万軒の停電")
add("2018_typhoon21", U, "restoration_complete", None, "9/20 17:51 停電の復旧完了", None, KEPCO_REP, "9/20 17:51 停電の復旧完了",
    date="2018-09-20 17:51")
for day, pct in [("1日後0時", 81), ("2日後0時", 88), ("3日後0時", 95), ("5日後0時", 99)]:
    add("2018_typhoon21", U, "outage_reduction_pct_marker", pct, f"△約{pct}%", "%", KEPCO_REP, f"({day})△約{pct}%", date=day,
        note="停電軒数推移図の注記。△は最大時からの減少率と解されるが図中に定義の明記なし")
add("2018_typhoon21", U, "poles_damaged", 1343, "1,343", "本", KEPCO_REP, "1,343|4,914|362|38|0|544|10".replace("|", ""),
    cell="設備被害表 配電 架空線 支持物【本】（折損・倒壊等）", note="内訳: 折損・倒壊881, 傾斜・沈下・ひび462", approx=False)
add("2018_typhoon21", U, "poles_broken_or_collapsed", 881, "881", "本", KEPCO_REP, "※１【折損・倒壊】881", approx=False)

# ---------------- 2016 Kumamoto: Kyushu
U = "九州電力"
add("2016_kumamoto", U, "peak_outage_households", 477000, "約47万7千戸", "戸", KYUDEN, "最大で全社の5.9％に相当する約47万7千戸が停電した",
    date="本震 2016-04-16")
add("2016_kumamoto", U, "peak_outage_households", 476600, "最大476.6千戸", "戸", JSCE_KYU, "最大476.6千戸(4月16日(土)2時)",
    date="2016-04-16 02:00", approx=False)
add("2016_kumamoto", U, "personnel_peak_own_and_contractors", 3600, "最大約3,600人", "人", KYUDEN,
    "当社社員及び委託・請負先を含め、最大約3,600人を動員して復旧対応を行い")
add("2016_kumamoto", U, "personnel_other_utilities_cumulative", 7667, "延べ7,667人", "人", KYUDEN, "人員（延べ7,667人、最大629人）", approx=False)
add("2016_kumamoto", U, "personnel_other_utilities_peak", 629, "最大629人", "人", KYUDEN, "人員（延べ7,667人、最大629人）", approx=False)
add("2016_kumamoto", U, "hv_generator_vehicles_incl_other_utilities", 148, "148台", "台", KYUDEN,
    "他電力からの応援（注１）を含む148台の高圧発電機車による応急送電を実施", approx=False)
add("2016_kumamoto", U, "hv_generator_vehicles_other_utilities", 110, "110台", "台", KYUDEN, "高圧発電機車（110台）", approx=False)
add("2016_kumamoto", U, "restoration_hv_lines_except_aso", None, "２日後の18日21時50分に高圧配電線への送電を完了", None, KYUDEN,
    "２日後の18日21時50分に高圧配電線への送電を完了した", date="2016-04-18 21:50", definition="阿蘇地区を除く")
add("2016_kumamoto", U, "restoration_hv_lines_except_inaccessible", None, "20日19時10分に高圧配電線への送電を完了", None, KYUDEN,
    "立入困難箇所を除き、20日19時10分に高圧配電線への送電を完了した", date="2016-04-20 19:10")
add("2016_kumamoto", U, "poles_damaged", 3152, "3,152本", "本", KYUDEN, "配電設備の支持物損壊3,152本", approx=False)

# ---------------- 2018 Iburi: Hokkaido
U = "北海道電力"
for d, v, pub, q in [("2018-09-06 04:00", 2950000, "約295万戸", "6日4時時点約295万戸"), ("2018-09-07 00:00", 2290000, "約229万戸", "7日0時時点約229万戸"),
                     ("2018-09-08 02:00", 27000, "約2.7万戸", "8日2時時点約2.7万戸"), ("2018-09-09 00:00", 675, "675戸", "9日0時点675戸")]:
    add("2018_iburi", U, "outage_households", v, pub, "戸", HEPCO_SUM, q, date=d)
add("2018_iburi", U, "generator_vehicles_from_other_utilities", 151, "151台", "台", HEPCO_SUM,
    "電力会社8社から151台の移動発電機車のご協力をいただき", approx=False)
add("2018_iburi", U, "supporting_utilities_generator_vehicles", 8, "8社", "社", HEPCO_SUM, "電力会社8社から151台の移動発電機車", approx=False)
add("2018_iburi", U, "hours_blackout_to_most_area_supplied", 45, "45時間程度", "時間", OCCTO_SUM,
    "ブラックアウトから概ね全域に供給できるまで45時間程度を要した", approx=True, definition="概ね全域に供給できるまで")

# ---------------- 2024 Noto: Hokuriku TD
U = "北陸電力送配電"
for d, v, q in [("2024-01-01", 40000, "1/1 約40,000戸"), ("2024-01-05", 28500, "1/5 約28,500戸"),
                ("2024-01-15", 8700, "1/15 約8,700戸"), ("2024-01-31", 2500, "1/31 約2,500戸")]:
    add("2024_noto", U, "outage_households", v, q.split(" ")[1], "戸", METI_NOTO, q, date=d, cell="p.4 図『停電復旧の推移』")
add("2024_noto", U, "personnel_daily_typical", 1000, "連日約1,000人規模", "人", METI_NOTO, "連日約1,000人規模で対応",
    definition="電力各社や協力企業からの応援を含む")
add("2024_noto", U, "personnel_peak_daily", 1400, "１日1,400名規模", "人", RIKU_PRESS, "ピーク時では１日1,400名規模の体制で復旧作業")
add("2024_noto", U, "back_office_support_cumulative", 1200, "延べ1,200名", "人", RIKU_PRESS, "後方支援は延べ1,200名を投入")
add("2024_noto", U, "personnel_other_utilities_cumulative", 4754, "4,754名", "人", TDGC, "合計※2|4,754名|31台|44台|261台|95台|661台".replace("|", ""),
    approx=False, definition="応援要員および各車両数は入替含む延べ数。2月2日までの実績", cell="応援元別表 合計行 列: 応援要員|高圧発電機車|サポートカー|高所作業車|建柱車|工事車両・業務車両等")
add("2024_noto", U, "hv_generator_vehicles_other_utilities_cumulative", 31, "31台", "台", TDGC,
    "合計※2|4,754名|31台|44台|261台|95台|661台".replace("|", ""), approx=False, definition="入替含む延べ数")
add("2024_noto", U, "aerial_work_vehicles_other_utilities_cumulative", 261, "261台", "台", TDGC,
    "合計※2|4,754名|31台|44台|261台|95台|661台".replace("|", ""), approx=False, definition="入替含む延べ数",
    note="列順はテキスト層の見出し順(応援要員|高圧発電機車|サポートカー高所作業車|建柱車|工事車両・業務車両等)による")
add("2024_noto", U, "emergency_supply_max_days", 54, "最大54日間", "日", RIKU_OUKYU, "応急送電を継続した（最大54日間）", approx=False)
add("2024_noto", U, "peak_outage_households", 40000, "最大約４万戸", "戸", RIKU_PRESS, "地震により最大約４万戸の停電が発生")

# ---------------- 2011 Tohoku / TEPCO
U = "東北電力"
add("2011_tohoku", U, "peak_outage_households", 4660000, "最大約４６６万戸", "戸", BOUSAI_TOHOKU, "最大停電戸数約４６６万戸")
add("2011_tohoku", U, "restored_fraction_day3", 0.80, "約８０％", "fraction", BOUSAI_TOHOKU, "発災後３日で約８０％※の停電を解消",
    definition="※復旧作業に着手不可能な地域を含む")
add("2011_tohoku", U, "restored_fraction_day8", 0.94, "約９４％", "fraction", BOUSAI_TOHOKU, "発災後８日で約９４％※の停電を解消",
    definition="※復旧作業に着手不可能な地域を含む")
add("2011_tohoku", U, "restoration_complete_accessible", None, "６月１８日１１時３分", None, BOUSAI_TOHOKU,
    "６月１８日１１時３分に復旧作業に着手可能な地域の停電はすべて復旧", date="2011-06-18 11:03")
add("2011_tohoku", U, "personnel_other_utilities_person_days", 4200, "延べ４．２［千人・日］", "人日", BOUSAI_TOHOKU,
    "延べ４．２［千人・日］の復旧要員と応急用電源車４１台（１８，５００ｋＶＡ）", approx=False, date="3月13日から")
add("2011_tohoku", U, "power_supply_vehicles_other_utilities", 41, "４１台（１８，５００ｋＶＡ）", "台", BOUSAI_TOHOKU,
    "応急用電源車４１台（１８，５００ｋＶＡ）", approx=False)
add("2011_tohoku", U, "poles_tilted_or_collapsed", 18228, "１８，２２８", "本", BOUSAI_TOHOKU, "合計１８，２２８１５，６８１２０，５２３８，７１４２２０",
    approx=False, cell="p.10 配電設備被害表 合計行 列: 電柱(傾斜・倒壊等)|電柱(流失・滅失)|高圧線|柱上変圧器|架空開閉器 (x座標で確認)",
    note="6月18日16時現在把握分。津波被害地域は調査中と注記")
add("2011_tohoku", U, "poles_washed_away", 15681, "１５，６８１", "本", BOUSAI_TOHOKU, "合計１８，２２８１５，６８１２０，５２３８，７１４２２０",
    approx=False, cell="同上 電柱(流失・滅失)")
add("2011_tohoku", "東北電力", "restored_fraction_day3", 0.80, "約80％", "fraction", CAO_2025, "3日後には被害全体の約80％を復旧",
    note="内閣府2025手法概要の参考記述")
U = "東京電力"
add("2011_tohoku", U, "peak_outage_households", 4050000, "最大約405万戸", "戸", CAO_2025, "東京電力管内では、最大約405万戸が停電したが")
add("2011_tohoku", U, "outage_households", 600000, "60万戸", "戸", CAO_2025, "翌日には、60万戸", date="翌日", approx=False)
add("2011_tohoku", U, "outage_households", 7300, "7,300戸", "戸", CAO_2025, "4日後には7,300戸まで減", date="4日後", approx=False)
add("2011_tohoku", U, "restoration_complete_days", 7, "7日後", "日", CAO_2025, "7日後には全ての停電が復旧", approx=False)

# ---------------- 2022 Fukushima-oki
add("2022_fukushima_oki", "東京電力・東北電力(両管内計)", "peak_outage_households", 2200000, "最大約220万戸", "戸", METI_FK1,
    "（UFR）が動作して、最大約220万戸の停電が発生", definition="周波数低下リレー動作による停電を含む両管内合計")
add("2022_fukushima_oki", "東京電力パワーグリッド", "restoration_time", None, "3/17 2:52に復電", None, METI_FK1, "東京電力管内は3/17 2:52に復電",
    date="2022-03-17 02:52")
U = "東北電力ネットワーク"
add("2022_fukushima_oki", U, "restoration_time", None, "3/17 21:41に復電", None, METI_FK1, "東北電力管内は3/17 21:41に復電", date="2022-03-17 21:41")
q = "2022|3/16|地震|（震度６強）|宮城県，|福島県|196|22時間04分|158,370戸|162,126戸|2,835人|（社員1,798:工事会社1,037）".replace("|", "")
cell = "p.1表 列: 停電フィーダー数|停電復旧時間|最大停電戸数|延べ停電戸数|稼働状況(他電力への応援要請なし)"
add("2022_fukushima_oki", U, "peak_outage_households", 158370, "158,370戸", "戸", METI_FK2, q, cell=cell, approx=False, date="2022-03-16 23:50")
add("2022_fukushima_oki", U, "cumulative_outage_households", 162126, "162,126戸", "戸", METI_FK2, q, cell=cell, approx=False)
add("2022_fukushima_oki", U, "outage_feeders", 196, "196", "フィーダー", METI_FK2, q, cell=cell, approx=False)
add("2022_fukushima_oki", U, "hours_to_restoration", 22.07, "22時間04分", "時間", METI_FK2, q, cell=cell, approx=False,
    note="22時間04分を時間に換算(22+4/60=22.07)")
add("2022_fukushima_oki", U, "personnel_total", 2835, "2,835人", "人", METI_FK2, q, cell=cell, approx=False, definition="他電力への応援要請なし")
add("2022_fukushima_oki", U, "personnel_own", 1798, "社員1,798", "人", METI_FK2, q, cell=cell, approx=False)
add("2022_fukushima_oki", U, "personnel_contractor", 1037, "工事会社1,037", "人", METI_FK2, q, cell=cell, approx=False)
add("2022_fukushima_oki", U, "poles_tilted", 93, "９３基", "基", METI_FK2, "電柱の傾斜等：９３基", approx=False)
add("2022_fukushima_oki", U, "outage_households", 4532, "4,532戸（97％復旧）", "戸", METI_FK2, "3/17(木）11時00分|4,532戸（97％復旧）".replace("|", ""),
    date="2022-03-17 11:00", approx=False)

missing = [
    dict(dataset="D7", item="2018_iburi 北海道電力 復旧要員数(自社・協力会社・他電力応援人数)",
         searched=[HEPCO_SUM, HEPCO_FULL, OCCTO_SUM, "https://www.hepco.co.jp/h30_iburi_earthquake/index.html"],
         note="移動発電機車151台(8社)のみ確認。人数の一次記載は見つからず"),
    dict(dataset="D7", item="2018_typhoon21 関西電力 自社・協力会社の内訳人数",
         searched=[KEPCO_REP, METI_RWG5], note="METI表の総数約12,000名と他電力約500名のみ"),
    dict(dataset="D7", item="2011_tohoku 東北電力・東京電力の自社/協力会社の日別復旧人員",
         searched=[BOUSAI_TOHOKU, BOUSAI_TOHOKU1, "https://www.fdma.go.jp/disaster/higashinihon/item/higashinihon001_16_03-03-06_01.pdf",
                   "https://www.tohoku-epco.co.jp/pastinformation/1182212_821.html"],
         note="他電力応援の延べ人日と電源車台数のみ"),
    dict(dataset="D7", item="2022_fukushima_oki 東京電力PG管内の最大停電軒数と復旧人員",
         searched=[METI_FK1, METI_FK2], note="両管内合計約220万戸と復電時刻のみ"),
    dict(dataset="D7", item="2024_noto 自社・協力会社の内訳と日別人員推移",
         searched=[METI_NOTO, RIKU_PRESS, RIKU_JININ, TDGC, "https://www.rikuden.co.jp/nw_saigaitaiou/notohantou.html (HTTP 404)"],
         note="ピーク1,400名規模・連日約1,000人規模・他電力延べ4,754名のみ"),
]

OUT.mkdir(parents=True, exist_ok=True)
with (OUT / "restoration_records.jsonl").open("w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
with (OUT / "missing_D7.jsonl").open("w", encoding="utf-8") as f:
    for r in missing:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("restoration_records", len(rows))
