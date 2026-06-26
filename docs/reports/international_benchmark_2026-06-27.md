# All-Japan-Grid (AGJ) 国際比較 — 査読対応スコアカード / International Benchmark

作成: 2026-06-27 / モデル: claude-opus-4-8(検証ワークフロー)。AGJの数値は本リポジトリ実ファイルで実測、比較10件は一次出典(論文/Zenodo/GitHub)で照合済の値を採用。**事実は出典URL付き。確認できない軸は「未確認」と明記**。

---

## 0. エグゼクティブサマリ / Executive summary

AGJが**正当に主張できる優位**は、`OSM由来 × 日本全国(全10広域・50/60Hz) × CGMESネイティブ × 事業者公表の実測線路別潮流に対する順位相関検証 × 値単位出典` の**組合せの初出**に限られる。CGMESネイティブ出力は本セット内でAGJのみ(他10件は全て `cgmes:false`)で、ここは明確かつ検証可能な優位。一方、**再現DAG・DOI・査読出版・ネットワーク連結性・検証の広さ**では先行勢(特にPyPSA-Eur)に明確に劣る。`ρ=0.721` は実測潮流の一致ではなく**容量/トポロジの代理指標**であり、PyPSA-Eurの `ρ=0.96-0.998`(ルート/回路長)とは**物理量が異なるため横並び比較不可**。

---

## 1. 比較マトリクス(データセット × 軸) / Comparison matrix

| 軸 \\ Dataset | **AGJ** | PyPSA-Eur / Xiong2025 | PyPSA-Earth | SciGRID | GridKit | KPG-193 | TAMU/ACTIVSg | osmTGmod/eGo | SimBench | OPSD |
|---|---|---|---|---|---|---|---|---|---|---|
| 地域 Scope | **日本 全10広域(50/60Hz)** | 欧州35カ国 | 全球(Africa実証) | 独(欧州コード) | 欧州/北米 | 韓国 | 米国(合成) | 独(EHV/HV) | 独(全電圧) | 欧州(発電所/時系列) |
| 源泉 Source | OSM一次+P03 | OSM(旧ENTSO-E) | OSM | OSM | OSM/ENTSO-E地図 | 合成(OSM位相) | 合成 | OSM | 合成 | 公的統計/TSO |
| 規模(送電要素) | 変電所6,962 / 線40,077(源泉) ; built 17,333ノード/19,031エッジ | バス5,848-6,737 / AC線7,320-8,994 ※版差 | クラスタ依存(固定値なし) | 独515頂点/833リンク | 線6,001/変電所3,657 | 193バス/AC359+HVDC1 | ACTIVSg2000=2000バス/1250変電所 | バス11,294/ブランチ19,605 | EHV 571バス/849線 | 送電網トポロジ=0(発電所/時系列のみ) |
| 電圧 Voltage | 500-66kV網羅(最頻66kV 7,655本) | AC≥220kV+全HVDC | 110-765kV(Africa) | AC≥220kV | AC≥220kV+全HVDC | 154/345/765kV+500kV HVDC | 500/230/161/115kV | 380/220/110/60kV | 0.4/10/20/110/220/380kV |
| 検証タイプ Validation | **実測線路別潮流(TEPCO)順位相関+電圧クラス突合** | 構造統計(ENTSO-E)相関+最適化コスト比較 | 構造統計+設備容量(IRENA) | 構造的カバレッジのみ(検証は今後) | **定量検証なし** | 自己無撞着(ソルバ収束)+定性 | 構造統計(realistic but not real) | モデル対モデルAC潮流(Avacon) | **潮流線路負荷 vs BNetzA 2017** | 出典間クロス比較(系統モデル無し) |
| 検証の定量値 | ρ=0.721(代理) / 実測AC ρ≈0.46-0.60 / 電圧クラス37/38 | 回路長ρ=0.998, ルート長ρ=0.958-0.964, 越境NTC ρ=0.844-0.849 | Africa設備容量165/229GW一致 | ≥220kV線長カバレッジ約95% | — | — | 平均次数2.3-2.8等の指標適合 | 有効電力わずか/無効電力有意に乖離 | EHV潮流をBNetzA実績線路負荷と比較 | — |
| **CGMES** | **✅ L1+L2(10/10 VALID・0 dangling・cim2pp往復)** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| 出典粒度 Provenance | 要素ごとOSM出自+**発電容量160件 URL+quote** | OSM-ID+powerplantmatching | 源泉DB粒度 | OSM-ID(電気値は標準型) | 弱い(OSM-ID保持は未確認) | 集約レベル | 粗い(合成) | 幾何=高/電気値=既定 | 要素別出典なし(合成) | パッケージ/出典単位 |
| 形式 Formats | **GeoJSON+CGMES+MATPOWER+pandapower** | CSV/netCDF | netCDF | CSV/GeoJSON | CSV | MATPOWER | PowerWorld/MATPOWER/PSS-E/PSLF | PostGIS/CSV/PyPSA | pandapower/CSV/PowerFactory/INTEGRAL | CSV/XLSX/SQLite |
| 再現性 Repro | uv.lock+regenerate_all.py(**DAG/Snakemake無し・OSM時刻未記録**) | **Snakemake+pixi.lock+Zenodo DOI** | **Snakemake+Pixi+OS別lock** | 自動Py(lock/DOI無し) | 手動DB(lock無し) | パイプライン無し | 低(PowerWorld依存) | OSS(lock無し) | pip+版管理(DAG未確認) | Jupyter+版DOI |
| DOI | **none** | 10.1038/s41597-025-04550-7 +複数Zenodo | 10.1016/j.apenergy.2023.121096 | 10.1016/j.egyr.2016.12.001 | Zenodo 55853/47317 | **arXivのみ(none)** | 10.1109/TPWRS.2016.2616385 | 10.1088/1742-6596/977/1/012003 | 10.3390/en13123290 | 10.1016/j.apenergy.2018.11.097 |
| 査読 Peer-review | 草稿(未出版・自己矛盾あり) | ✅Nature Sci Data 2025 | ✅Applied Energy 2023 | ✅Energy Reports 2017 | ❌(ツール+Zenodo) | ❌(arXiv) | ✅TPWRS 2017 | ✅IET GTD 2020/IOP 2018 | ✅Energies 2020 | ✅Applied Energy 2019 |
| ライセンス | MIT/ODbL+P03約款 | MIT/ODbL | AGPL-3.0/ODbL | AFL/Apache+ODbL(不一致) | MIT/ODbL/CC-BY | 未確認/ODbL | 無償(OSI明示なし) | AGPL/Apache+ODbL | BSD-3/ODbL | MIT/混在 |

> 規模の版差注記: PyPSA-Eurは arXiv断面(5,848バス/7,320線/261,757km)と**出版Nature版=正典**(6,737バス/8,994線/283,974km)で値が異なる。引用時は出版版を一次値とする。

---

## 2. AGJの優劣 / Where AGJ leads and lags

### 2.1 優位(根拠つき) — Leads
1. **日本全国スコープの唯一性**: 公開OSM由来送電網で日本の全10広域(50/60Hz両系統)を扱うのはAGJのみ。源泉レイヤ 6,962/40,077/19,138 を `dist/cim/cim_index.json` totals と `DATA_CATALOG.md` L184-186 で実測確認。比較勢は欧州/米国/韓国で日本は対象外。
2. **CGMESネイティブ(本セット唯一)**: `cgmes:true`。L1(EQ+GL)+L2(EQ+TP+SSH+SV+GL+境界)を全10地域、10/10 VALID・0 dangling・cim2pp往復(`docs/reports/formal_review_2026-06-26.md`, `CHANGELOG.md` L37/L139-140)。他10件は全て `cgmes:false`。**最も明確で検証可能な優位**。
3. **形式網羅**: GeoJSON+CGMES+MATPOWER+pandapower。OSM由来勢でCGMESとMATPOWERを併せ持つのはAGJのみ。
4. **実測「潮流」検証の試行**: 事業者公表の線路別潮流(TEPCO)に対する回廊使用率の順位相関 interior ρ=0.721(p≈1e-09)+実測AC ρ≈0.46/0.60+関西TD電圧クラス37/38(`docs/reports/external_kansai_lines_voltage_2026-06-26.json`)。OSM欧州勢は構造統計/モデル対モデル止まり。
5. **値単位の出典**: `data/generator_capacity_sources.jsonl` 160件を plant×field 粒度で source_url/quote 付き(verify=160 ok/0 bad)。OSM-IDのみの競合より粒度が高い(発電容量に限る)。

### 2.2 劣位(根拠つき) — Lags
1. **再現DAG不在**: Snakemake/Makefile/dvc無し+OSM時刻未記録で再現不能。PyPSA-Eur(Snakemake+pixi.lock+Zenodo)に明確に劣る。
2. **DOI/査読なし**: doi=none・草稿のみ。DOI+査読を備える7件に劣る(同列の無DOIはKPG-193のみ)。
3. **連結性**: built `n_components=1,096`、主成分11,423/17,333(約66%)、`n_tie=7`、未タグkVエッジ1,679本。連結網を出すPyPSA-Eur/SimBach/KPG-193/TAMUに劣る。
4. **検証の狭さ・汚染**: 東京単一+関西クラスのみ、最良値が代理指標、実測AC中程度、幻発電所dispatch混入(H2)。
5. **発電フリート出典**: 値単位出典は160件のみ。powerplantmatchingで全発電所に出所を付すPyPSA勢に体系性で劣る面。

---

## 3. 正当な新規性ステートメント / Defensible novelty (strictly scoped)

> **JP**: 「OSMから抽出し要素ごと出典を付した**日本の全国(全10広域・50/60Hz)送電網**を、**CGMESネイティブ(L1+L2)**を含む標準交換形式(CGMES+MATPOWER+pandapower+GeoJSON)で相互運用可能に公開し、**事業者公表の実測線路別潮流(TEPCO)に対する順位相関検証**(interior ρ=0.721=容量/トポロジ代理、実測AC ρ≈0.46-0.60)と電圧クラス突合(関西TD 37/38)まで併せ持つ、**我々の知る限り初**の公開データセットである。」
>
> **EN**: "To our knowledge, the first openly available dataset that simultaneously (i) covers Japan's entire 10-area, dual-frequency (50/60 Hz) transmission grid extracted from OSM with per-element provenance, (ii) ships **native CGMES (L1+L2)** alongside MATPOWER/pandapower/GeoJSON, and (iii) is externally validated against a utility's **published per-line flows** via corridor-usage rank correlation (a capacity/topology proxy, ρ=0.721; AC-on-synthetic-loads ρ≈0.46-0.60)."

**限定の明示(主張してはならない範囲)**:
- 「電力一般でOSM抽出が新規」とは言わない(SciGRID 2017 / PyPSA-Earth 2023 / Xiong 2025 が先行)。
- 「実測突合自体が新規」とは言わない(SimBench は BNetzA 2017 線路負荷と潮流照合済、PyPSA-Eur/-Earth は ENTSO-E/IRENA 統計と構造照合済)。
- **CGMESネイティブが「初」と言えるのは本比較セット内**(他10件が `cgmes:false`)に限る。

---

## 4. 過剰主張リスク / Overclaim risks (査読で突かれる点)
1. 論文結論 `the first openly available`(L251)が**未ヘッジ**。READMEは適切にヘッジ済(`to our knowledge, a first for an OSM-extracted public grid`)だが論文側が未修整。スコープ限定必須。
2. 論文散文 **8,164変電所**(L37/L59/L198/L251) vs 自Table(L219)/実データ **6,962** の自己矛盾。UC機数 757 vs 646 も不一致(formal_review H1)。
3. **ρ=0.721を潮流検証の見出し成果として提示**するリスク。代理指標であり実測潮流量MAEではない。PyPSA-Eurのρ=0.96-0.998(長さ相関)と**物理量が異なるため横並び不可**。
4. **訂正容量が検証潮流に未伝播**(H2): 蘇我1,440MW(本来0)・大間(着工中・実0)等の幻発電所がdispatchに残存し検証ρに混入。設計の明示か伝播修正が必要。
5. **関西97%の母数省略**: 開示182幹線中、名称一致で照合できた38本中37本=97%(被覆約21%)。かつ電圧クラス限定(レーティング/潮流ではない)。
6. **「三者totals一致」は不正確**: `regions.json` の地域別合計は 8,994/19,031(=built)で源泉6,962/40,077と不一致(plants 19,138のみ一致)。`regions.json`はbuilt/地域ビューと表現すべき。

---

## 5. 正直な限界 / Honest limitations
- ワンコマンド再現DAG不在・OSMスナップショット時刻未記録 → ビット再現不能。
- DOI/Zenodo/査読なし。引用可能な恒久識別子を欠く。
- builtトポロジ断片化(1,096成分・主成分66%・連系7・未タグ1,679本) → 全国一括で解ける連結網に未到達。
- 実測潮流検証が東京単一+関西クラスのみ、定量値が代理中心、H2汚染。
- 値単位出典(URL+quote)は発電容量160件のみ。送電線レーティングは非公開TD資料依存で全要素網羅ではない。
- 編集サーバ:8088が無認証(H3, 配信安全性の既知の穴)。
- 国際定量ベンチマーク表が本作業以前は不在(H5・スコア3.5)——本表がその空白を埋める。

---

## 6. 出典一覧 / Sources

**AGJ(本リポジトリ実測)**:
- `dist/cim/cim_index.json`(totals={substations:6962, lines:40077, plants:19138})
- `DATA_CATALOG.md`(L184-186 三者照合表、L7-10 7,962誤記の訂正)
- `docs/data/built/all.json`(stats: n_nodes 17333 / n_edges 19031 / main_size 11423 / n_components 1096 / n_tie 7 / 最頻kv 66.0=7655本 / 未タグ0.0=1679本)
- `docs/data/regions.json`(地域別合計 substations 8994 / lines 19031)
- `docs/reports/external_kansai_lines_voltage_2026-06-26.json`(開示182・名称一致38・agree 37=0.974・クラス別 500kV6/6・275kV16/16・154kV15/16)
- `docs/reports/formal_review_2026-06-26.md`(H1 変電所自己矛盾・H2 容量未伝播・H3 無認証・H5 国際ベンチ不在・スコアカード)
- `papers/ieee-openaccess.tex`(L37/L59/L198/L219/L251)

**比較データセット(一次出典)**:
- PyPSA-Eur / Xiong2025: https://doi.org/10.1038/s41597-025-04550-7 ; arXiv https://arxiv.org/abs/2408.17178 ; Zenodo https://doi.org/10.5281/zenodo.14144752 ; 原著 arXiv https://arxiv.org/abs/1806.01613
- PyPSA-Earth: https://doi.org/10.1016/j.apenergy.2023.121096 ; arXiv https://arxiv.org/abs/2209.04663
- SciGRID power: https://doi.org/10.1016/j.egyr.2016.12.001
- GridKit: https://zenodo.org/records/55853 ; https://zenodo.org/records/47317 ; https://github.com/bdw/GridKit
- KPG-193: https://arxiv.org/abs/2411.14756 ; https://github.com/agm-center/kpg-testgrid
- Birchfield / TAMU ACTIVSg: https://doi.org/10.1109/TPWRS.2016.2616385 ; https://doi.org/10.3390/en10081233 ; https://electricgrids.engr.tamu.edu/
- osmTGmod / eGo: https://doi.org/10.1088/1742-6596/977/1/012003 ; https://doi.org/10.1049/iet-gtd.2020.0107
- SimBench: https://doi.org/10.3390/en13123290 ; https://github.com/e2nIEE/simbench
- OPSD: https://doi.org/10.1016/j.apenergy.2018.11.097 ; https://open-power-system-data.org

> 注: 比較10件の数値は事前検証(一次照合)で confirmed/corrected 済の値を採用。PyPSA-Eur規模は版差あり(出版Nature版=正典)。SciGRID欧州v0.2「479 nodes/765 edges」は一次未確認。