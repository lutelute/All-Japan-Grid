# トラックB④ 孤立断片・第三波（ドライラン）— 台帳追記本文（親セッションが共有台帳へ転記する） 2026-09-02

担当: フォーク trackB4-fragments（Claude Fable 5.1）。**正典 `docs/data/built/all.json` は未変更**（`git diff --quiet HEAD -- docs/data/built/all.json` で確認済み）。
数値の正本: `docs/reports/fragment_third_wave_2026-09-02.json`（同 `.md` は表形式、`same_site_proposals_2026-09-02.yaml` は承認待ち提案）。

## 0. 「927」について（定義の確定）

docs/reports・docs・handover を全文検索したが、断片の件数として **927 は一度も出てこない**（ヒットは vm 0.927 のみ）。
断片の数には 3 つの定義が併存しており、いずれも 927 ではない:

| 定義 | 出典 | 成分 | ノード | 変電所 |
|---|---|---:|---:|---:|
| (i) 波の定義＝島内 k5 キーで畳み・両端が島内の枝のみ（stitch/タイ無し） | 第一波/第二波・本トラック | **601** | **1,107** | **324** |
| (ii) 連結性の単一権威 `compute_connectivity`（越境 stitch 158＋AC タイ 6 込み・座標重複を畳まない） | `mixed_pref_gate_2026-09-02.md` の「本系統外ノード」 | 596 | **1,273** | 369 |
| (iii) `all.json` の `stats` キー（古い焼き付け） | — | 625 | 1,292 | — |

キャンペーン開始時（08-20）は (i) で 904 成分/1,749 ノード、第二波後 691 成分。handover の「927」は
(i) と (ii) の間の値でどの記録とも一致しないため **誤記の可能性が高い**。以後は (i)=成分 601 / (ii)=ノード 1,273 で呼ぶ。

## 1. 現状（介入#42 後・定義 (i)）

| 島 | キー数 | 本系統 | 断片成分 | 断片ノード | 断片変電所 |
|---|---:|---:|---:|---:|---:|
| hokkaido | 760 | 722 | 24 | 38 | 18 |
| east | 5,400 | 5,086 | 168 | 314 | 110 |
| west | 7,230 | 6,481 | 403 | 749 | 190 |
| okinawa | 81 | 75 | 6 | 6 | 6 |
| 計 | 13,471 | 12,364 | **601** | **1,107** | **324** |

## 2. 第三波（継ぎ目緩和の OSM way 連鎖）— ドライラン結果

実装 `scripts/hunt_fragment_third_wave.py`（第二波 `hunt_fragment_osm_chains.py` の共通関数を import・辿るのは
`docs/data/lines_all.geojson` の実線形のみ・直線ジャンプ無し）。ゲート＝電圧整合 ≤25% / **迂回係数**（実線長÷直線距離 ≤1.5、直線 <200m は不問）/
**跨島双子**（断片の過半、または端点座標に別島ノード）は回収せず再属性へ / ノード接触 ≤80m / 最大 6 way。

| 島 | ≤60m（第二波再現段） | ≤120m | **≤200m（適用段）** | ≤300m | 棄却（300m 段） |
|---|---|---|---|---|---|
| hokkaido | 1 | 3 | **3**（24→21 成分・+6 ノード） | 3 | unreachable 21 |
| east | 8 | 10 | **17**（168→151・+37） | 21 | unreachable 130・twin_cross_island 12・twin_endpoint 2・detour 3 |
| west | 26 | 35 | **48**（403→355・+91） | 60 | unreachable 295・twin_cross_island 25・twin_endpoint 8・detour 15 |
| okinawa | 0 | 0 | 0 | 0 | unreachable 6 |
| 計 | 35 | 48 | **68**（601→**533** 成分・**+134 ノード**） | 84 | — |

- **周波数跨ぎ枝: 99 → 99（適用段の 68 本で不変）**。初回ドライランでは 99→101 になり、原因は端点座標に別島の同座標ノード
  がある 6 候補（静岡・山梨・長野境界帯）だった → `twin_endpoint` ゲートを追加して 0 化（`--write` は跨ぎ枝が増える場合に中止する）。
- way 数の分布（300m 段 84 本）: 1way 22 / 2way 42 / 3way 11 / 4〜6way 9。初出段: 60m 35・120m 13・200m 19・300m 17。
  60m 段に 35 本あるのは第二波（08-20）以後の #35/#39/#42 で島の所属・本系統が動いた分（第二波は当時の正典で網羅済み）。
- 適用段 ≤200m の連鎖 68 本の断片 kv: 不明(0) 46・66kV 13・275kV 3・77kV 1・154kV 1。最長 42.4 km（山口・古開作〜美和町西畑線、2way・迂回 1.14）。
  代表例: 南信変電所 500kV への 4 ノード断片（信濃幹線・継ぎ目 112m・14.1km・迂回 1.03）、東浜三丁目〜浅山一丁目線 275kV（継ぎ目 152m）。
- **200m を適用段とする理由**: 300m 段で増える 16 本は迂回棄却も同時に増え（west 11→15）、継ぎ目 300m は道路一区画に近く
  「別線の端点同士」を繋ぐ危険が出る。200m までは棄却率が段に依らず安定（detour 3/11）。300m 段は判読付きで個別採用に回す。

## 3. 同一敷地同定の提案（承認待ち・`same_site_proposals_2026-09-02.yaml`・approved: false）

| 断片 | 本系統側 | 距離 | kv | 備考 |
|---|---|---:|---|---|
| 羽田変電所 (east) | 羽田変電所 | 57m | 500 vs 66 → **kv_ok false** | 第一波からの持ち越し。同名で階級が違う＝別設備の疑い |
| 新湯沢変電所 (east) | 新湯沢変電所 | 143m | 275/275 | 新規 |
| 新那須変電所 (east) | 新那須変電所 | 147m | 275/275 | 第一波からの持ち越し |
| 保渡田町変電所 (east) | 保渡田町変電所 | 249m | 66/66 | 新規 |
| 中部電力PG 屋代変電所 (west) | 同名 | 28m | 0/77 | 新規 |

第一波の 7 件のうち みなかみ町・沼津×2・沼田・玉淀 の 5 件は既に解消（#35 ノード衛生＝同座標双子の統合で本系統へ合流したとみられる）。

## 4. 残存断片の分類（成分単位・機械ヒューリスティクス＝判読ではない）

| 分類 | hokkaido | east | west | okinawa | 代表例 |
|---|---:|---:|---:|---:|---|
| c 跨島双子（越境スライスの二重登録疑い→再属性で解く） | 0 | 12 | 25 | 0 | tokyo/chubu junction 36.6453:139.1105（同座標に両島）・福島変電所 66kV（青函） |
| d 鉄道き電（回収対象外） | 2 | 12 | 19 | 0 | JR北海道木古内機電区分所・えちごトキめき鉄道 二本木・JR東 神保原 154kV |
| d 遠隔/離島（OSM 線 1km 内・本系統 5km 内とも無し） | 0 | 6 | 12 | 3 | 温海・白馬村・奥間・宮古島市 |
| d 配電/kv 不明の単独変電所 | 10 | 27 | 102 | 3 | — |
| e 開示台帳に名前あり（開示の再適用で繋がる候補） | 1 | 7 | 14 | 0 | 円山 66kV(4n)・三条 154kV(2n)・**西相模 77kV(22n・west 所属＝region 残留疑い)** |
| f 未分類 | 11 | 104 | 231 | 0 | tokyo junction 35.9661:139.6611(27n)・南会津町(10n)・kansai junction 34.3441:136.7615 77kV(12n) |
| └ f のギャップ ≤1km / 1-3 / 3-10 / >10km | 3/3/2/3 | 36/48/14/6 | 52/82/55/42 | — | ギャップ=本系統最近傍ノードまでの直線距離 |

⚠ `e` の west 側に関東座標のノード（西相模変電所 35.29N/139.12E・清水変電所 36.47N/140.07E）が残っている。#38/#42 の
再属性が届いていない region 残留（旧 ID 誤爆 #39 の残り or 一意周波数県ガード外）の可能性 — B3 の残課題として親に回す。

## 5. 親が `--write` するときの手順とゲート（本セッションでは未実行）

```bash
# 1) 直前の再計測(#40 再判定と同じ正典であること・跨ぎ枝 99 を確認)
PYTHONPATH=. python3 scripts/hunt_fragment_third_wave.py --seam-m 200          # ドライラン(数分)
# 2) 適用(バックアップ all.json.pre_frag3.bak・recovery="osm_chain3" マーカー・跨ぎ枝が増えれば自動中止)
PYTHONPATH=. python3 scripts/hunt_fragment_third_wave.py --seam-m 200 --write
# 3) ゲート
PYTHONPATH=. python3 -m pytest -q tests/test_fragment_third_wave.py tests/test_mixed_pref.py
PYTHONPATH=. python3 scripts/uc_to_pf_built.py --islands west --out output/frag3/west_sel_post.json   # AC 収束・slack 開示
PYTHONPATH=. python3 scripts/uc_to_pf_built.py --islands east --out output/frag3/east_sel_post.json
PYTHONPATH=. python3 scripts/regenerate_all.py --stamp-only && python3 scripts/record_osm_snapshot.py
```
合否: 跨ぎ枝 99 不変（スクリプトが保証）／定義 (i) 成分 601→533・ノード +134 が再現／west・east ピーク AC 収束維持・slack の変化を開示（減る方向が期待だが基準は「非収束にならない」）／`.gitignore` に `*.pre_frag3.bak` が要るか確認（既存 `.bak` パターンに含まれるか）。
無効化: `recovery=="osm_chain3"` の枝を機械除去 / `all.json.pre_frag3.bak` 復元 / git revert。regen 耐性: **STEPS/Snakefile には未組込**（親が組込むなら `fragment_recovery_chains` の直後に `hunt_fragment_third_wave.py --seam-m 200 --write` を追加）。

## 6. docs/MODEL_INTERVENTIONS.md への追記案（#34 追補3・適用後に書く）

> **#34 追補3（第三波・継ぎ目緩和）**: `hunt_fragment_third_wave.py` で way 連鎖の継ぎ目閾値を 60m→200m に緩め（120/200/300m 段で計測・300m 段は迂回棄却が増えるため個別採用に回す）、**OSM 実線形の連鎖 68 本**を回収（1way 22・2way 42 ほか）。創作防止ゲート＝電圧整合 ≤25%・迂回係数 ≤1.5・跨島双子（断片過半 or 端点）は回収せず再属性へ。効果＝定義(i) 断片成分 601→**533**・本系統 +134 ノード・周波数跨ぎ枝 99 不変。①根拠=OSM 実線形＋接触/継ぎ目/迂回の帳簿（各枝 `disclosure` 文＋`fragment_third_wave_<date>.json`）②帳簿=同 JSON（棄却理由別件数込み）③無効化=`recovery="osm_chain3"` マーカー除去 / `all.json.pre_frag3.bak` / git revert。同時に同一敷地同定 5 件を承認待ち提案（`same_site_proposals_<date>.yaml`・approved:false）として出し、残存 533 成分を c/d/e/f に機械分類（f 未分類 346・うちギャップ ≤1km 91）。

## 7. IMPROVEMENT_LOG.md 2026-09-02 エントリへの段落案

- **【トラックB④】孤立断片の第三波をドライランで準備**（フォーク trackB4、`fragment_third_wave_2026-09-02.md`）:
  第二波の継ぎ目 60m を 120/200/300m へ段階緩和し OSM 実線形の連鎖だけを辿る `hunt_fragment_third_wave.py` を実装
  （電圧整合・迂回係数 ≤1.5・跨島双子の 3 ゲート、テスト 9 本）。適用段 ≤200m で **68 本**（hokkaido 3・east 17・west 48）＝
  断片成分 601→**533**・本系統 +134 ノード・**周波数跨ぎ枝 99 不変**（初回は端点双子で 99→101 になり `twin_endpoint` ゲートを追加）。
  同一敷地同定は 5 件を承認待ち提案に（第一波 7 件中 5 件は #35 で解消済み）。残存を機械分類: 跨島双子 37（再属性で解く）・
  鉄道 33・遠隔/離島 21・配電/kv 不明 142・開示台帳に名前あり 22・未分類 346（ギャップ ≤1km 91）。
  「927」は全文書に不在＝誤記（正しくは定義(i) 成分 601 / 定義(ii) ノード 1,273）。**正典は未変更・適用は親が 200m 段で `--write`**

## 変更ファイル（未コミット・親がコミット）

- 新規: `scripts/hunt_fragment_third_wave.py`, `tests/test_fragment_third_wave.py`（9 passed・0.3s）,
  `docs/reports/fragment_third_wave_2026-09-02.{json,md}`, `docs/reports/same_site_proposals_2026-09-02.yaml`, 本ファイル
- 触っていない: `docs/data/built/all.json`（HEAD と同一）・既存 hunt_fragment_osm_*.py・共有台帳
- 一時ログ: `output/frag3/dryrun*.log`（gitignore 対象・削除可）

## 残課題

- `f_unclassified` 346 成分（うちギャップ ≤1km 91）は継ぎ目 300m でも OSM 線形が届かない＝**OSM 側の線欠落**。衛星判読/開示図の対象
- `e` の west 側にある関東座標ノード（西相模 22n・清水）の region 残留は B3/#39 系の確認事項
- 300m 段の追加 16 本は迂回棄却と同時に増えるため、個別判読つきで採否（一括適用しない）
- STEPS/Snakefile への組込は親判断（regen で消えないようにするなら必要）
- **`.gitignore` に `docs/data/built/all.json.pre_frag3.bak` が無い**（`git check-ignore` で未該当を確認）。`--write` の前に B3 と同様の 1 行を親が追加すること
