# 電圧崩壊の再現（1987/7/23 首都圏大停電）で見つかったモデル上の問題

日付: 2026-09-20
対象ネット: `docs/reports/codex_ac_diagnosis_2026-09-15/input_network.json.gz`（canonical east, pandapower 3.4.0, 東京ゾーンを使用）
用途: このネットを使って準定常の電圧崩壊シミュレーション（潮流＋発電機の界磁制限＋定電力負荷の回復）を行い、
1987 年 7 月 23 日の首都圏大停電を再現した。解析コードはリポジトリ外にあり、本リポジトリは読み取りのみ。

そのままでは実績と合わず、原因を追うと以下 8 件のモデル上の問題に行き当たった。1〜3 は電圧安定度・無効電力の解析結果を
大きく左右する。4〜8 はデータの整合性の問題。各項目に証拠の数値と再現コードを付ける。

補正後（1・2・3 を解析側で補正し、電源を 1987 年の構成にして、送電線リアクタンスと調相設備量を実績の送電限界に合わせた後）は、
主要 500kV 変電所の実測電圧（江川, 電学論B 129-2, 2009, 図2）に対し 13:00〜13:15 の 4 時刻で平均 −5〜+2kV の差に収まった。
つまりトポロジと線路定数は電圧崩壊の解析に十分使える水準にあり、問題は主に以下の付帯データにある。

再現コードの共通部分:

```python
import gzip, json
import numpy as np, pandapower as pp
net = pp.from_json_string(gzip.decompress(open(
    "docs/reports/codex_ac_diagnosis_2026-09-15/input_network.json.gz", "rb").read()).decode())
tok = net.bus.zone == "tokyo"
```

---

## 1. 変圧器が 1 変電所 1 バンクの仮置きで、容量が需要に対して大幅に不足している【影響大】

東京ゾーン（負荷 44.2GW）の変圧器は、電圧階級の組ごとに同一定格・`parallel=1`・`vk_percent=12` で入っている。

| 組 | 台数 | 1 台の容量 | 合計 |
|---|---|---|---|
| 500/275kV | 27 | 953 MVA | 25.8 GVA |
| 275/154kV | 59 | 267 MVA | 15.7 GVA |
| 500/154kV | 11 | 267 MVA | 2.9 GVA |
| 275/66kV | 70 | 100 MVA | 8.5 GVA |
| 154/66kV | 251 | 100 MVA | 25.5 GVA |
| 500/66kV | 23 | 100 MVA | 2.3 GVA |

下位系へ降ろす変圧器（154/66・275/66・500/66）の合計は 36GVA で、44GW の負荷に対して 100% 超の過負荷になる。
漏れリアクタンスでの無効電力損失（I²X）が 10GVar 級になり、次の症状が出る。

- 合成調相（`add_reactive_compensation`）を 2 倍にしないと初期断面が解けない。
- 正常電圧（0.98pu）のまま局所的にノーズ端に達する。調相設備に頼りすぎた系統の典型的な挙動で、実系統とは違う。
- `docs/AC_DIAGNOSIS_TOOL.md` の「Q 制限つきでは公称需要で収束しない」「66kV 経由で約 19GVar」の主因と見られる。

解析側では、ピーク断面の直流潮流に対して稼働率 60% 以下になるよう `parallel` を設定し直した（82.9 → 約 150GVA、平均 1.5 バンク、最大 8〜20）。
これだけで系統全体が同時に沈む現実的な崩壊になった。

```python
tr = net.trafo[tok.reindex(net.trafo.hv_bus).values]
pair = tr.vn_hv_kv.astype(int).astype(str) + "/" + tr.vn_lv_kv.astype(int).astype(str)
print(tr.groupby(pair).agg(n=("sn_mva", "size"), sn=("sn_mva", "median"), total=("sn_mva", "sum"), par=("parallel", "max")))
print("load MW", net.load[tok.reindex(net.load.bus).values].p_mw.sum())
```

提案: バンク数を通過潮流か配下の負荷から決める（N-1 設計でピーク稼働率 6 割程度）。少なくとも仮置きであることを
`DATA_DICTIONARY.md` に明記する。

## 2. 負荷の都県別シェアが需要実績と大きくずれている【影響大】

負荷母線の座標を `data/reference/japan_prefectures_simplified.geojson` で都県判定し、
`data/reference/pref_demand_fy2024.json`（経産省 電力調査統計）のシェアと比べた。静岡は東電管内を県全体の 3 割と仮定。

| 都県 | モデル | 需要実績 |
|---|---|---|
| 東京 | 15.8% | 29.2% |
| 神奈川 | 16.1% | 17.8% |
| 埼玉 | 16.4% | 13.9% |
| 千葉 | 13.1% | 13.4% |
| 茨城 | 10.1% | 8.8% |
| 栃木 | 10.3% | 5.8% |
| 群馬 | 10.7% | 5.7% |
| 山梨 | 3.0% | 2.2% |
| 静岡（東部） | 4.3% | 3.2% |

`allocate_loads(pref_gwh=…)` は都県シェアを使う設計のはずだが、このネットでは東京都が実績の半分、群馬・栃木が約 2 倍になっている。
停電範囲の解析では、補正前は群馬 40%・栃木 28% が停電する誤った結果になり、補正後は実績（北関東は無傷）と合った。

```python
from matplotlib.path import Path
prefs = json.load(open("data/reference/japan_prefectures_simplified.geojson"))["features"]
ld = net.load[net.load.in_service & tok.reindex(net.load.bus).values]
xy = np.array([json.loads(g)["coordinates"][:2] for g in net.bus.geo.reindex(ld.bus)])
for f in prefs:
    polys = f["geometry"]["coordinates"] if f["geometry"]["type"] == "MultiPolygon" else [f["geometry"]["coordinates"]]
    m = np.zeros(len(ld), bool)
    for p in polys:
        m |= Path(np.array(p[0])).contains_points(xy)
    if ld.p_mw[m].sum() > 500:
        print(f["properties"]["pref_ja"], round(100 * ld.p_mw[m].sum() / ld.p_mw.sum(), 1), "%")
```

## 3. 発電機が高圧母線に直結され、昇圧変圧器が無い【電圧解析で影響大】

全発電機が `net.gen`（PV ノード）として 500/275/154kV 母線に直接つながっている。実機の AVR は発電機端子の電圧を保持し、
昇圧変圧器（機器ベースで 12〜15%）を挟んだ高圧側は無効電力出力とともに下がる。直結だと発電機が界磁制限に入るまで
高圧母線電圧が固定され、500kV の電圧低下を再現できない（実績 370〜390kV に対し 0.9pu 止まりだった）。

解析側では 高圧母線 —x_t— 端子 —x_d— 内部電圧 の 3 段にし、AVR は端子、界磁制限は内部電圧で表現した。
動特性・電圧安定度向けの出力では、昇圧変圧器の枝を任意で付けられると良い。

## 4. 発電機データの重複と燃料種別の混入

```python
g = net.gen[net.gen.in_service & (net.gen.max_p_mw >= 100)]
print(g[g.duplicated(subset=["name", "bus", "max_p_mw"], keep=False)][["name", "bus", "max_p_mw"]])   # 川崎火力発電所 3420MW が 2 件
print(net.gen.type.value_counts().tail(8))          # 'gsimaps/ort', 'gsimaps/seamlessphoto', 'image' が燃料種別に入っている
print(net.gen[net.gen.name.astype(str).str.contains("仙台火力")][["name", "type", "max_p_mw"]])     # 446MW が solar 扱い
```

- 川崎火力発電所（3,420MW, 稲荷変電所 154kV）が同一内容で 2 件。容量が二重に計上される。
- 燃料種別に OSM の `source` タグ由来と見られる値（`gsimaps/ort` など）が混じる。
- 仙台火力が `東北電力株式会社仙台火力発電所`（gas, 446MW）と `仙台火力発電所`（solar, 446MW）の 2 件で入っている。同じ発電所の二重計上で、片方は燃料種別も誤り。
- 真岡発電所 1,248MW が 66kV 母線に接続されている。

## 5. 都心の 66kV 網と上位系の接続が少ない

154kV 未満の負荷を「電気的に最も近い 154kV 以上の母線」へ寄せると、都心〜多摩の 255 需要地・5.9GW（全体の 13.9%）が
`tokyo junction 35.6604:139.3722:275`（八王子付近の 275kV 分岐点）1 点に集まる。275kV 以上の一次変電所へ同じ方法で割り当てると
笹目変電所 154kV に 10GW が集まる。都心の 275/66kV 地中変電所の変圧器が不足しているためと見られる。

供給区域を電気的距離で推定する用途には現状使えず、解析側では地理的に最も近い変電所へ割り当てた。

## 6. 500kV タグの付いた小規模変電所

500kV 線路が近くを通るだけの配電用変電所が 500kV 母線として入っている（例: ＪＲ新熊谷変電所、神保町変電所、三咲町変電所、
金杉八丁目変電所、船橋変電所、市川塩浜変電所、根戸変電所）。分岐点でない 500kV 母線 79 のうち、500/275kV か 500/154kV の変圧器を持つのは 38 で、残り 41 が該当する。1 の表の 500/66kV 100MVA × 23 台はこれに対応する。
500kV 母線の一覧や一次変電所の抽出に混入するので、変圧器の組（500/275・500/154 を持つか）で絞る必要があった。

```python
b = net.bus[tok & (net.bus.vn_kv == 500) & ~net.bus.name.astype(str).str.contains("junction")]
has_bulk = set(net.trafo.hv_bus[(net.trafo.vn_hv_kv >= 400) & (net.trafo.vn_lv_kv >= 150)])
print(len(b), "buses;", sum(i in has_bulk for i in b.index), "with 500/275 or 500/154 transformer")
```

## 7. 東北側: 女川の送出が 275/66kV 変圧器 1 台に集中している

東系統（東京＋東北）全体で直流潮流を解くと母線位相が −100°〜+75° に開き、`大郷町変電所 275kV – 66kV` の変圧器 1 台
（x=0.12pu）に 56.7° の位相差が出る。塚浜変電所（女川）からの 275kV が系統側の 275kV につながっておらず、
66kV 経由でしか送出できない形になっている。東系統の AC が解けない一因と見られる。

## 8. 線路の経路形状が pandapower ネットに入っていない

このネットの `net.line.geo` は全件空。経路形状は `docs/data/built/tokyo.json` の `edges[].path` にあるが、
4,749 辺中 1,380 辺は `path` が無く両端座標のみ。地図描画で直線になる。

---

## 補足: 1987 年の再現に使った補正と結果

- 電源は 1987 年 7 月時点の号機構成（エリア内 31.4GW＋域外受電 11.0GW）に差し替え。
- 現在のトポロジは 1987 年より強いので、275kV 以上の送電線リアクタンスを 1.8 倍、合成調相を 1.335 倍にして、
  送電限界を実績の直前最大需要 3,930 万 kW に、13:00 の電圧を実測 517kV に合わせた。
- 需要は実績どおり（13:00 に 3,820 万 kW → 毎分 40 万 kW で午前の水準へ → 緩やかな伸び）。
- 結果: 主要 500kV 変電所の電圧は 13:00 / 13:05 / 13:10 / 13:15 で実測との差 −5 / −4 / −3 / +2kV、375kV を切る時刻 13:19:09（実績 13:19）。

出典: 江川正尚「広域停電をきっかけとした電力系統安定化技術の飛躍的進歩」電学論B 129巻2号 (2009);
経済産業省 電力調査統計 都道府県別電力需要実績 2024 年度。
