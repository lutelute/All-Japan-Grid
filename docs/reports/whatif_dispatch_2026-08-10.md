# 給電の置き方を変えたら過負荷はどうなるか（what-if・2026-08-10）

これまでの過負荷診断はすべて `balance_by_zone`＝**ゾーン内を銘板容量に比例して
一律スケール**を前提にしていた。実系統は経済給電なので、注入の地理が根本から違う。
接続規則は本番既定（介入#24 = cap）で固定し、給電だけ差し替えた。
UC シナリオ `fy2023r2`・断面 t=17（全国純需要が最大の時刻）。

**`uc` は交絡している。** `inject_dispatch_by_zone` は需要側も UC 純需要へ
スケールし、しかも注入が需要に届かない（west は 13.3% がスラック持ち）。
そのままでは需要水準・不足分・配分の3つが同時に動く。**`uc_norm` が対照条件**で、
需要を PF 側の値に戻し総注入を銘板比例と同じ 1.05×需要に揃えてある — 
変数は**注入の燃料・空間配分だけ**。結論は `uc_norm` で読むこと。

| 島 | 給電 | 過負荷 | 最大負荷率 | 超過潮流 | 注入合計 | 稼働機数 | 太陽光シェア | 偽電源 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| east | nameplate | 551 (9.00%) | 1594.7% | 90,360 MW | 58,012 MW | 8,235 | 45.9% | 291 |
| east | uc | 396 (6.47%) | 847.9% | 118,622 MW | 56,603 MW | 359 | 0.0% | 291 |
| east | uc_norm | 370 (6.04%) | 738.2% | 125,697 MW | 58,012 MW | 359 | 0.0% | 291 |
| west | nameplate | 291 (3.48%) | 708.2% | 33,950 MW | 77,558 MW | 8,775 | 34.8% | 490 |
| west | uc | 389 (4.65%) | 963.7% | 82,517 MW | 60,643 MW | 488 | 0.0% | 490 |
| west | uc_norm | 388 (4.64%) | 737.7% | 59,084 MW | 77,558 MW | 488 | 0.0% | 490 |

## 注入の燃料構成

| 島 | 給電 | 上位燃料 |
|---|---|---|
| east | nameplate | solar 26,622MW / gas 14,510MW / coal 5,646MW / hydro 4,061MW / oil 3,892MW / nuclear 2,144MW |
| east | uc | gas 35,784MW / coal 17,790MW / hydro 1,918MW / biomass 463MW / geothermal 309MW / waste 291MW |
| east | uc_norm | gas 36,676MW / coal 18,233MW / hydro 1,966MW / biomass 474MW / geothermal 317MW / waste 299MW |
| west | nameplate | solar 26,964MW / gas 17,136MW / coal 10,864MW / hydro 10,042MW / oil 5,670MW / nuclear 4,691MW |
| west | uc | gas 26,336MW / coal 25,465MW / hydro 4,543MW / nuclear 2,890MW / biomass 943MW / geothermal 240MW |
| west | uc_norm | gas 33,682MW / coal 32,568MW / hydro 5,810MW / nuclear 3,696MW / biomass 1,206MW / geothermal 307MW |

---
**未適用**。採否は人間判断。生成: `scripts/capacity/whatif_dispatch.py`（DC）
