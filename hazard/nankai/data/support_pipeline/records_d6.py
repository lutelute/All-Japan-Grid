#!/usr/bin/env python3
"""D6 curated records: utility scale from FY2025 有価証券報告書 (as of 2026-03-31) and company pages.

Writes utility_scale.jsonl and missing_D6.jsonl. Quotes are contiguous runs of the PDF text
layer with the '|' line separators removed (build_db.py normalises NFKC + strips whitespace,
verifies the quote and fills the PDF page number automatically).
Retail contract counts by supply area (電力取引報) are parsed in build_db.py, not here.
"""
import json
import sys
from pathlib import Path

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "external/hazard_support/records"
FY = "2026年３月31日現在 (FY2025 有価証券報告書)"

SRC = {
    "東京電力パワーグリッド": ("https://www.tepco.co.jp/pg/company/bond/securities_report/pdf/260624_01-j.pdf", "東京電力パワーグリッド 有価証券報告書 FY2025(提出会社=東京電力PG)"),
    "関西電力送配電": ("https://www.kepco.co.jp/ir/brief/securities/102/pdf/report102.pdf", "関西電力 有価証券報告書 設備の状況(2)連結子会社 関西電力送配電㈱"),
    "中部電力パワーグリッド": ("https://www.chuden.co.jp/ir/ir_siryo/yukashoken/__icsFiles/afieldfile/2026/06/24/102yuho_1.pdf", "中部電力 有価証券報告書 設備の状況(2)国内子会社 ①中部電力パワーグリッド㈱"),
    "中国電力ネットワーク": ("https://www.energia.co.jp/ir/pdf/ir13-2025.pdf", "中国電力 有価証券報告書 設備の状況 中国電力ネットワーク㈱"),
    "北海道電力ネットワーク": ("https://www.hepco.co.jp/corporate/ir/ir_lib/pdf/102securities.pdf", "北海道電力 有価証券報告書 設備の状況(3)国内子会社 北海道電力ネットワーク㈱"),
    "九州電力送配電": ("https://www.kyuden.co.jp/var/rev0/0871/4590/N32fdvqX.pdf", "九州電力 有価証券報告書 設備の状況 九州電力送配電株式会社"),
    "東北電力ネットワーク": ("https://www.tohoku-epco.co.jp/ir_n/report/securities_report/pdf/2025_ho.pdf", "東北電力 有価証券報告書 設備の状況 東北電力ネットワーク㈱"),
    "北陸電力送配電": ("https://www.rikuden.co.jp/library/attach/202606yuuka.pdf", "北陸電力 有価証券報告書 設備の状況(当社グループの電気事業固定資産表)"),
    "四国電力送配電": ("https://www.yonden.co.jp/assets/pdf/corporate/ir/library/securities_report/yuhofy2025.pdf", "四国電力 有価証券報告書 ＜送配電事業の主要な設備＞"),
    "沖縄電力": ("https://www.okiden.co.jp/shared/pdf/ir/zaimu/2026/260625.pdf", "沖縄電力 有価証券報告書 設備の状況(提出会社。送配電部門は法的分離なし)"),
}
LIC = "各社 有価証券報告書(金融商品取引法に基づく公衆縦覧書類。著作権は各社)"

rows = []


def add(utility, field, label, value, pub, unit, quote, scope=None, note=None, url=None, fy=FY, cell=None):
    u, title = SRC.get(utility, (None, None))
    rows.append(dict(utility=utility, field=field, label_verbatim=label, value=value, value_as_published=pub,
                     unit=unit, fiscal_year=fy, scope=scope or title, source_url=url or u, cell=cell,
                     quote=quote, note=note, collected_by="records_d6.py"))


def std(utility, trans, subs, dist, trf, quotes, trf_label="変圧器個数", trf_unit="個"):
    qt, qs, qd, qf = quotes
    add(utility, "transmission_supports", "送電設備 支持物数", trans, f"{trans:,}基", "基", qt)
    add(utility, "substations", "変電所数", subs, f"{subs:,}か所", "箇所", qs)
    add(utility, "distribution_supports", "配電設備 支持物数", dist, f"{dist:,}基", "基", qd)
    add(utility, "distribution_transformers", "配電設備 " + trf_label, trf, f"{trf:,}{trf_unit}", trf_unit, qf)


# ---- TEPCO PG (own securities report)
std("東京電力パワーグリッド", 49674, 1601, 6044193, 2649559,
    ("回線延長12,775ｋｍ支持物数49,674基", "変電所数1,601か所", "電線延長36,718ｋｍ支持物数6,044,193基", "変圧器個数2,649,559個"))
add("東京電力パワーグリッド", "offices", "業務設備", None, "本社１か所 総支社10か所 電力所２か所等", "箇所", "本社１か所総支社10か所")
add("東京電力パワーグリッド", "employees_company", "提出会社の状況 従業員数", 13888, "13,888", "人",
    "2026年３月31日現在従業員数(人)平均年齢(歳)平均勤続年数(年)平均年間給与(円)平均年間給与の対前事業年度増減率(％)13,888",
    note="就業人員数であり、出向人員等は含まない(同注記)")
add("東京電力パワーグリッド", "employees_group", "連結会社の状況 従業員数", 20469, "20,469", "人",
    "2026年３月31日現在従業員数(人)20,469", note="東京電力PGグループ(単一セグメント)")
add("東京電力パワーグリッド", "distribution_overhead_km", "配電 架空電線路 亘長", 348239, "348,239ｋｍ", "km", "亘長348,239ｋｍ")

# ---- Kansai TD
std("関西電力送配電", 107292, 1624, 2780625, 1894253,
    ("7,842km支持物数107,292基", "変電所数1,624か所", "電線延長11,276km支持物数2,780,625基", "変圧器個数1,894,253台"), trf_unit="台")
add("関西電力送配電", "offices", "業務設備 事業所数", None, "本店1 本部10 電力所17 配電営業所31", "箇所",
    "事業所数本店１本部10電力所17配電営業所31")
add("関西電力送配電", "employees_company", "設備の状況表 従業員数 合計(関西電力送配電㈱)", 8128, "8,128", "人",
    "合計(24,834,909)226,920 55,720 1,959,220 2,241,862 8,128", note="設備区分別従業員数の合計")
add("関西電力送配電", "employees_segment", "連結 送配電事業セグメント 従業員数", 11159, "11,159［1,919］", "人",
    "送配電事業11,159［1,919］", note="臨時従業員数［1,919］は外数", scope="関西電力 連結会社の状況 セグメント=送配電事業")
add("関西電力送配電", "distribution_overhead_km", "配電 架空電線路 亘長", 126900, "126,900km", "km", "亘長126,900km")

# ---- Chubu PG
std("中部電力パワーグリッド", 34592, 995, 2895908, 1672000,
    ("支持物数34,592 基", "変電所995 カ所", "支持物数2,895,908 基", "変圧器個数1,672,000 個"))
add("中部電力パワーグリッド", "offices", "業務設備", None, "本社1 支社19 営業所35", "箇所", "支社19 カ所営業所35 カ所")
add("中部電力パワーグリッド", "employees_company", "設備の状況表 従業員数 計(中部電力パワーグリッド㈱)", 8663, "8,663", "人",
    "計―(17,187,803)198,555 1,065,216 597,951 151,850 △53,749 1,959,824 8,663",
    note="注記: 従業員数(就業人員数)は建設工事従事者159人を除いたもの")
add("中部電力パワーグリッド", "employees_segment", "連結 パワーグリッドセグメント 従業員数", 9886, "9,886", "人",
    "パワーグリッド9,886", scope="中部電力 連結会社の状況 セグメント=パワーグリッド")
add("中部電力パワーグリッド", "distribution_overhead_km", "配電 架空電線路 亘長", 132020, "132,020 km", "km", "亘長132,020 km")

# ---- Chugoku NW
std("中国電力ネットワーク", 52164, 556, 1719248, 932708,
    ("支持物数52,164基", "変電所数556か所", "支持物数1,719,248基", "変圧器個数932,708台"), trf_unit="台")
add("中国電力ネットワーク", "offices", "業務設備 事業所数", None, "本店1 ネットワークセンター23 ネットワークサービスセンター1", "箇所",
    "本店１か所ネットワークセンター23か所ネットワークサービスセンター１か所")
add("中国電力ネットワーク", "employees_segment", "連結 送配電事業セグメント 従業員数", 4614, "4,614", "人", "送配電事業4,614",
    scope="中国電力 連結会社の状況 セグメント=送配電事業")
add("中国電力ネットワーク", "distribution_overhead_km", "配電 架空電線路 亘長", 81815, "81,815km", "km", "亘長81,815km")

# ---- Hokkaido NW
std("北海道電力ネットワーク", 44422, 397, 1485915, 561366,
    ("支持物数44,422 基", "変電所数397 ヵ所", "支持物数1,485,915 基", "変圧器台数561,366 台"), trf_label="変圧器台数", trf_unit="台")
add("北海道電力ネットワーク", "offices", "業務設備", None, "本店1 支店10 ネットワークセンター28", "箇所",
    "支店10 ヵ所(359,472)ネットワークセンター28 ヵ所")
add("北海道電力ネットワーク", "employees_segment", "連結 北海道電力ネットワークセグメント 従業員数", 2686, "2,686", "人",
    "北海道電力ネットワーク2,686", scope="北海道電力 連結会社の状況 セグメント=北海道電力ネットワーク")
add("北海道電力ネットワーク", "distribution_overhead_km", "配電 架空電線路 亘長", 66637, "66,637 km", "km", "亘長66,637 km")

# ---- Kyushu TD (labels and values are in separate runs in the text layer)
std("九州電力送配電", 74321, 660, 2534035, 1123843,
    ("1,254㎞74,321基", "調相設備容量660か所", "5,163㎞2,534,035基1,123,843個", "2,534,035基1,123,843個"))
for r in rows[-4:]:
    r["cell"] = "テキスト層で項目名(架空電線路|亘長|回線延長|…|支持物数)の後に値が同順で並ぶ表"
add("九州電力送配電", "offices", "業務設備 事業所数", None, "配電事業所54か所", "箇所", "事業所数配電事業所54か所")
add("九州電力送配電", "employees_segment", "連結 送配電事業セグメント 従業員数", 3776, "3,776", "人", "送配電事業3,776",
    scope="九州電力 連結会社の状況 セグメント=送配電事業")
add("九州電力送配電", "employees_company", "会社概要 従業員数", 3776, "3,776人", "人", "従業員数3,776人（2026年３月31日現在）",
    url="https://www.kyuden.co.jp/td/company/outline.html", scope="九州電力送配電 会社概要ページ", fy="2026年３月31日現在")

# ---- Tohoku NW
std("東北電力ネットワーク", 58530, 637, 3189814, 1223520,
    ("支持物数58,530基", "変電所数637か所", "支持物数3,189,814基", "変圧器個数1,223,520個"))
add("東北電力ネットワーク", "offices", "業務設備 事業所数", None, "本社1 支社他8 電力センター62", "箇所", "事業所数本社1 支社他8電力センター62")
add("東北電力ネットワーク", "employees_segment", "連結 送配電事業セグメント 従業員数", 8737, "8,737", "人", "送配電事業8,737",
    scope="東北電力 連結会社の状況 セグメント=送配電事業")
add("東北電力ネットワーク", "employees_company", "会社概要 従業員数", 6381, "6,381名", "人", "資本金240億円従業員数6,381名",
    url="https://nw.tohoku-epco.co.jp/company/profile/", scope="東北電力ネットワーク 会社概要ページ",
    fy="ページ内の設備欄に（2026年3月末現在）とあるが従業員数の時点は明記なし")

# ---- Hokuriku (consolidated electric-business fixed-asset table)
hk = "北陸電力 有価証券報告書 設備の状況(当社グループ電気事業固定資産表。送配電設備は北陸電力送配電の保有と解されるが表中に会社名の明記なし)"
std("北陸電力送配電", 12577, 259, 604222, 397529,
    ("支持物数12,577基", "変電所数259ヵ所", "支持物数604,222基", "変圧器個数397,529個"))
for r in rows[-4:]:
    r["scope"] = hk
add("北陸電力送配電", "employees_segment", "連結 送配電事業セグメント 従業員数", 1536, "1,536[252]", "人", "送配電事業1,536[252]",
    scope="北陸電力 連結会社の状況 セグメント=送配電事業", note="臨時従業員数[252]は外数")

# ---- Shikoku TD
std("四国電力送配電", 11983, 240, 857577, 517492,
    ("支持物数11,983基", "変電所数240ヵ所", "支持物数857,577基", "変圧器個数517,492個"))
add("四国電力送配電", "offices", "業務設備 事業所数", None, "本社1 支社4 事業所16", "箇所", "本社１ヵ所支社４ヵ所事業所16ヵ所")
add("四国電力送配電", "employees_segment", "連結 送配電事業セグメント 従業員数", 1944, "1,944 [ 17]", "人", "送配電事業1,944 [ 17]",
    scope="四国電力 連結会社の状況 セグメント=送配電事業", note="臨時従業員数[17]は外数")

# ---- Okinawa (no legal unbundling)
std("沖縄電力", 10860, 127, 236800, 135152,
    ("支持物数10,860基", "変電所数127ヵ所", "支持物数236,800基", "変圧器個数135,152台"), trf_unit="台")
add("沖縄電力", "employees_company", "提出会社の状況 従業員数", 1511, "1,511", "人",
    "2026年３月31日現在従業員数(人)平均年齢(歳)平均勤続年数(年)平均年間給与(円)平均年間給与の対前事業年度増減率(％)1,511",
    note="沖縄電力全体(発電・小売を含む)。送配電部門単独の人数ではない")

missing = [
    dict(dataset="D6", item="各一般送配電事業者の供給地点数(託送の需要場所数)",
         searched=["各社 有価証券報告書(上記10件)", "https://www.tepco.co.jp/pg/company/summary/", "https://powergrid.chuden.co.jp/corporate/company/com_outline/",
                   "https://www.kyuden.co.jp/td/company/outline.html", "https://nw.tohoku-epco.co.jp/company/profile/",
                   "https://www.energia.co.jp/nw/company/guide/outline/"],
         note="供給地点数は見つからず。代替としてエリア別の小売契約口数(電力取引報 令和8年3月分)を utility_scale に retail_contracts_* として格納"),
    dict(dataset="D6", item="北海道・中国・北陸・四国の送配電会社単体の従業員数",
         searched=["各社 有価証券報告書 設備の状況/従業員の状況"],
         note="有報は連結セグメント人数のみ(中国は設備区分別人数はあるが合計行なし)。会社概要ページは未確認"),
    dict(dataset="D6", item="FY2019-2023 の時系列値", searched=[], note="時間の制約で未取得(FY2025有報のみ)"),
]

OUT.mkdir(parents=True, exist_ok=True)
with (OUT / "utility_scale.jsonl").open("w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
with (OUT / "missing_D6.jsonl").open("w", encoding="utf-8") as f:
    for r in missing:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("utility_scale", len(rows))
