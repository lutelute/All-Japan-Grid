# UC検証ループ計画 — 発電実績（nas03/PWS_DB）との突合

タスク#13の設計文書（2026-06-12、オーナー指示「終了判定は計画の終了で」に基づく
計画フェーズの成果物）。実装は本計画に従って段階導入する。

## 1. 確定したデータソース（2026-06-12調査）

**nas03 = pws-nas03（UGREEN DXP4800 Plus）`/volume1/PWS_DB/`** — 研究室データNAS。
README.md（NAS上）が正本。アクセス経路:

| 経路 | 用途 |
|---|---|
| SSH `pwslab@100.102.148.23`（Tailscale） | 探索・必要断面のscp取得（本計画の既定） |
| SMB `//pws-nas03.local/PWS_DB` | Mac/Finder手動参照 |
| pws-gpu3060 `/mnt/nas03`（fstab永続マウント済み） | 重い集計のNAS近接実行 |

### 1.1 発電実績（本命）: `demand_raw/{company}/`

- **10社**（hokkaido/tohoku/tepco/chubu/hokuriku/kansai/chugoku/shikoku/kyushu/okinawa）
- 実測ヘッダ（hokuriku/202404.csv、CP932・30分値）:
  `DATE,TIME,エリア需要,原子力,火力(LNG),火力(石炭),火力(石油),火力(その他),水力,地熱,バイオマス,太陽光発電実績,太陽光出力制御量,風力発電実績,風力出力制御量,揚水,蓄電池,連系線,その他,合計`
  → **UCの燃料区分と直接対応する電源種別実績**（出力制御量も別列で取れる）
- 期間は社で異なる（kansai/chugoku 2016〜、多くがFY2023-2025をカバー、
  hokkaidoは202605まで=ほぼ現在）。**命名・形式は社別方言あり**
  （月次`YYYYMM.csv` / 年次`year_YYYY.csv` / 四半期`2019_1Q.csv`等、
  tepcoはエンコーディング差あり） → 社別パーサが必要
- `demand_normalized/{company}/demand_{year}.csv` は**需要のみ**の正規化
  （dt/demand_MW）— 電源種別検証には使えない。需要側の照合には有用

### 1.2 同時に確定した別件

- **MSM GPV**: `msm_raw/2024,2025`（GRIB2、計~1.2TB）→ データスペース
  `msm` 契約の所在が確定（`AJGRID_MSM_ROOT` 候補 = ssh/マウント経由の
  `/volume1/PWS_DB/msm_raw`）。Phase 2（RE実測CF化）のブロッカー解消
- **JEPX スポット**: `price_raw/jepx/{YYYY}/{YYYYMM}.csv`（2009年〜）
  → タスク#12（経済停止の構造要因分解）の入力が確保済み
- `demand_daily` は **pws-gpu3060 の cron で毎日自動更新** — 定期検証の
  データ鮮度が既に機械化されている

## 2. 検証ループの設計

### 2.1 突合の軸

```
UC側:  uc_annual チャンク（fy2023r2maint / fy2025r1measured）の
       地域×燃料×時間（fuel_energy_mwh、必要なら時系列）
実績側: demand_raw の同期間・同地域の電源種別30分値 → 月次集計
KPI:   月次 × 地域 × 燃料 の乖離（MWh・シェアpp・L1合計）
       — 現状の「年間・全国1点」検証（reference_shares_pct）から
       「月次・地域別」へ分解能を2段引き上げる
```

語彙対応（UC→実績）: nuclear→原子力 / lng→火力(LNG) / coal→火力(石炭) /
oil→火力(石油)+火力(その他)※区分差は開示 / hydro→水力 / geothermal→地熱 /
biomass→バイオマス / solar→太陽光発電実績(+制御量は別KPI) / wind→風力同 /
pumped_hydro→揚水 / battery→蓄電池。連系線列はUCのic flowと照合可能（副産物）。

### 2.2 データスペース統合（zero-copy原則）

- `config/dataspace.yaml` の `nas03_generation_records` を確定情報で更新
  （location: ssh+path、形式、社別方言の注記）
- コネクタ `src/dataspace/connectors/nas03.py`: query={company, month}で
  **必要月のCSVだけ** ssh cat（またはローカルキャッシュ）→ 社別パーサ →
  正規形（dt, fuel, mw）を返す。生CSVは持ち帰らない
  （redistribute_raw=false、集計派生物のみレポートへ）
- 取得sha256をprovenanceに記録（再現性チェーン、profile_refと同方式）

### 2.3 検証ドライバ

`scripts/uc_validate.py --scenario fy2023r2maint --annual docs/reports/uc_annual_*.json
--companies hokuriku,kansai,tepco --months 202304..202403`

- 出力: `docs/reports/uc_validation_{scenario}_{date}.json`
  （月次×地域×燃料の乖離表+L1サマリ+語彙対応の開示）
- uc_runs 索引へ kind="validation" で記録
- 図: 地域×月のヒートマップ（乖離pp）を docs/reports/ へ（LINE報告用）

### 2.4 段階導入

| Phase | 内容 | 規模 |
|---|---|---|
| A | hokuriku+kansai+tepco × FY2023 で突合パイプ実証（社別パーサ3種） | 小 |
| B | 10社×FY2023/FY2025 全域化（方言パーサ拡充、kyushu四半期形式等） | 中 |
| C | 定期検証: demand_daily の自動更新に乗せ、月次で乖離を自動算出 → LINE | 自動化 |

### 2.5 期待される使い道

- coal +10.6pp 残差（経済停止モデル外）の**地域・月分解** — どの地域の
  どの季節で過大かが分かれば、#12（JEPX価格×経済停止）の検証材料になる
- fy2025r1 の RE容量未較正バイアスの定量化（太陽光実績との直接比較）
- UC連系線フロー vs 実績連系線列の照合（ゾーナル検証の実測版）

## 3. 未決事項（実装フェーズへの持ち越し）

- 社別方言の全数調査（特にtepcoのエンコーディング、kansaiの年次ファイル構造、
  kyushuの四半期形式）— Phase Aで3社分を先行確定
- 揚水の符号規約（発電正/動力負の向き）が社で揃っているか
- 「その他」「火力(その他)」の扱い（UC側unknownとの対応）
- nas03のSSH認証は鍵登録済み（このMacから接続確認済み）。サーバー
  （pws-160core）からの経路は未確認 — 重い集計はpws-gpu3060が近道

## 4. 達成水準と残差の構造（2026-06-12 総括 — 自己改善8巡の結果）

### 4.1 達成水準（精度担保の現状）

| 指標 | 値 |
|---|---|
| 検証カバレッジ | **8/10社**（hokkaido/tohoku/tepco/hokuriku/shikoku=新形式、kansai/chugoku/kyushu=旧形式。残: chubu=年度別形式・okinawa） |
| 地域別L1（ピーク日2025-08-06） | 平均 **37.2pp**（ベースライン47.0から8巡で-9.8） |
| 同・天気正規化（--re-actuals） | 平均 **32.6pp** |
| 最良地域 | **kyushu 18.5pp** / kansai 23.7 / hokuriku 21.0（閑散日） |
| 外部妥当性 | 全国地熱**549MW=公表~550MW一致** / fuel_cost=JEPX 2025-08クラスタと整合 / 北陸coal 61.2 vs 62.0 GWh/日 / tohoku送出 UC-107 vs 実績-121 GWh/日（方向・規模一致） |
| 時間形状 | solar相関0.89-0.97（形状は較正済み、乖離は量側） |

### 4.2 8巡で潰した要因（台帳⑰〜㉔）

季節係数未適用→帰属誤り（IGCC・橘湾・敦賀）→効率ティルト→天気正規化→
地熱坑井重複→検証カバレッジ3社拡大→ティルト幅JEPX較正→連系線突合。
「燃料費が誤り」「全国coal設備が過大」の両仮説は**計測により棄却**。

### 4.3 残差の構造（現アーキテクチャの限界として開示）

1. **coal部分負荷運用**: UCはコスト最小化でcoalをフル稼働させるが、実績は
   57-63%稼働。効率ティルトで一部表現したが、残りは**自社需要+市場取引**
   （JEPX約定に応じた出力調整）の領分 — 市場結合モデルは本UCのスコープ外
2. **連系線の時間パターン**: 日量・方向は整合（4.1）するが形状相関は低い
   （0.26〜-0.58）— 市場スケジュールと連動する時間配分は同上の限界
3. **検証データ側**: kansai 2024.csvがHTML破損（NAS取得スクリプトの修繕要）、
   OCCTO需要の保持窓~14ヶ月（古い日付は--demand-from-measuredで代替）
4. 単日検証は天気・曜日・定検の影響を受ける — 恒久運用はPhase C
   （月次自動検証）で平滑化するのが正

### 4.4 再現

```bash
AJGRID_NAS03_ROOT="ssh://pwslab@100.102.148.23/volume1/PWS_DB" \
  python3 scripts/uc_validate.py --scenario fy2025r1 --date 2025-08-06            # ピーク日
  python3 scripts/uc_validate.py --scenario fy2025r1 --date 2025-08-10 --re-actuals  # 天気正規化
  python3 scripts/uc_validate.py --scenario fy2025r1 --date 2023-12-13 \
    --companies kansai,chugoku,kyushu --demand-from-measured --re-actuals       # 旧形式3社
```
