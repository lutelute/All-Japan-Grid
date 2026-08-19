# 未解決課題#1・#2の実装 — 正典系譜MATPOWERケース+実測線路R/X適用 2026-08-20

オーナー指示「1,2の未解決課題をやっておくといいかも」(潮流計算編スライド14頁)。
実装・実測=AI(Claude Fable 5)。

## 課題#2: 配布ケースの改善 — 完了

### 実装

- `export_national_matpower.py` を分割: 書き出し部を系譜非依存の
  `export_net(island_id, net, ac_ok, ...)` へ(既存snapped系はそのまま動く)
- **`scripts/export_matpower_canonical.py`(新設)**: built正典+標準注入
  (build_island_net・容量比例・L_DB・補償・成分別スラック・fy2023需要)で
  4島を組み、素朴NR(既定tol・dc→flatの2トライ)で解けた島のみ ac=true。
  **緩い許容誤差の解は焼き込まない**(誠実性)。westは dc-only とし、
  **west_reduced**(アンテナ集約・需要保存・帳簿つき)を素朴AC可ケースとして併載
- `src/powerflow/reduce_antenna.py`(新設): 試験コードを製品化した
  `aggregate_antennas(net)`(帳簿: n_removed/moved_load_mw/...)

### 結果(dist/matpower_canonical/・生成レシピ=スクリプト)

| ケース | バス | 素朴AC | roundtrip | MATPOWER実機 |
|---|---|---|---|---|
| hokkaido | 831 | ✅(dc-init) | ok | (未・下記) |
| **east** | 6,145 | ✅(dc-init) | ok | 保留(下記) |
| west | 8,242 | dc-only(正直) | ok | — |
| **west_reduced** | 6,139 | ✅(flat!) | ok | **✅ runpf成功 損失2.41% vm=[0.927,1.074]** |
| okinawa | 100 | ✅ | ok | (未) |

**west_reducedがMATLAB(MATPOWER 8.1)のrunpfで解けた** — スライド14頁の
「--reduced同梱でMATPOWERで全島runpf」の実証。旧snapped系譜で解けなかった
eastも正典系譜ではpandapower素朴ACで収束。

### 保留(正直に): east等のMATLAB実機確認

深夜のメモリ枯渇(swap 12GB・空き100MB)でMATLABが起動段階でクラッシュを
繰り返し(Trace trap/abort・crash dump 93914/95149ほか)、非クラッシュの1回では
eastが `mp.task.dm_converter_class: input data format not recognized` を返した。
**データ起因ではない強い傍証**: 同一形式・同一値域のwest_reducedが同一セッションで
成功・east.matはNaN/Inf無し・pandapower roundtrip ok。機材が健全なときに
east/hokkaido/okinawaのMATLAB確認を再実行すること(未確認のまま成功と主張しない)。

## 課題#1: 実測線路R/Xの適用(様式5 crosswalk) — v1実装+実測

### 実装

- `src/powerflow/line_impedance.py`(新設): crosswalk(both_resolved 411行)を
  端点座標近接(1.2km・電圧優先)でモデルバスへ照合し、**両端を直結する
  モデル線がある場合のみ** R%/X%/B半%→Ω換算で置換(1回線あたり%・parallelは
  pandapowerが処理)。公表1線=モデル複数区間の経路按分は未実装(将来課題)
- 実験ハーネス: `scripts/diagnostics/trial_line_impedance.py`

### 結果

| 島 | 適用 | 未適用の内訳 | 厳密tol AC | 備考 |
|---|---|---|---|---|
| west | **44本** | バス不一致212・直結線なし109 | ❌→❌(不変) | 緩解(tol10)のvm_minが0.725→**0.557**に変動 |
| east | **35本** | バス不一致275・直結線なし87 | ✅→✅(vm 0.830→0.831) | 回帰なし=適用は安全 |

### 解釈

1. **収束には効かない(予想どおり)** — 適用先は基幹中心で、収束の敵は
   アンテナ側(別レポートで確定済み)
2. **緩解の非信頼性の追加証拠**: 実測インピーダンスを入れただけで緩解の
   vm_minが0.17pu動く = tol10MVA解の末端電圧は物理量として引用不可
3. **律速は照合**(適用率 west 44/約200・east 35/約140):
   (a) バス照合212/275不一致 — crosswalkの座標とモデルバス座標のずれ・
   電圧階級バスの選び分け (b) 直結線なし109/87 — 公表1線がモデルでは
   junction経由の複数区間。**次の一手 = 名前照合の併用+経路按分**
4. 物理忠実度は前進(基幹44+35本が事業者実測値) — 「物理を足す」の第一歩。
   本丸のLTCタップ・調相モデル化は未着手(次の実験)

## 次の一手

1. east/hokkaido/okinawaのMATLAB実機確認(機材健全時)
2. crosswalk照合の強化(名前併用・経路按分)→適用率を44本→200本級へ
3. LTC/調相モデル化の実験(アンテナ温存で厳密解に届くかの本命)
4. 次回リリース(v1.8)で matpower_canonical(west_reduced込み)を配布へ

---

## 追補(同日深夜): LTC/LRT・調相のモデル化 — west厳密ACの本丸が開いた

オーナー「LTC、LRT、調相のモデル化などなどできそうなら」。
ハーネス=`scripts/diagnostics/trial_ltc.py`(タップ・プリソルブ方式)。

### 方式

1. 全変圧器944基にタップ機構を付与(lv側・±12段×1.5%=±18%・pandapower標準列)。
   タップの符号規約は実験内で自動較正(probe変圧器にpos=+5→lv電圧0.820→0.874で+1と確定)
2. **緩解(tol10MVA)の電圧プロファイルから各変圧器lv側の誤差を読みタップ位置を設定**
   (=LTC/LRTの静的運転点近似)→厳密tolを試行
3. 残存弱電圧の負荷バスへ調相SC(q=0.35×P負荷・配変の標準的力率改善規模)

### 結果(west全部入り8,242バス・アンテナ温存・厳密=既定許容誤差)

| 段階 | 厳密tol AC | vm範囲 | vm<0.95 |
|---|---|---|---|
| 基準(タップなし) | ❌ | (tol10緩解のみ) | — |
| **+LTC/LRT(稼働172/944基・1ラウンド)** | ✅ **0.6s** | [0.715, 1.034] | 25バス |
| **+調相SC(20箇所)** | ✅ 0.5s | **[0.945, 1.266]** | **1バス** |

- **再現性**: LTC round1成立は独立2ランで再現(いずれも172基・0.6s・vm同一)
- **負の結果も記録**: タップの精錬継続(round2〜5)は**逆効果**(過補正で厳密tol
  再喪失・緩解vm_minも0.643まで悪化)。1ラウンドで止めてSCに引き継ぐのが正
- 残存25バスの正体=**変圧器を持たない線のみのアンテナ**(タップの届かない場所)
  → そこにSCが効いた(25→1バス)

### 結論 — 6月来の「west AC問題」の解決筋が確定

**「物理を足す」で解ける。** アンテナ(構造)を消さなくても、実系統が普遍的に持つ
電圧調整(LTC/LRT 172基相当の静的タップ+調相SC 20箇所)をモデルに与えるだけで、
west全規模の厳密AC真解に到達する。6月の真因命題は最終形として
「**下位網の電圧調整の物理の不在**」に確定。

### 限界(誠実開示)

- 単一需要断面(fy2023)。24h横断・実績断面は未検証
- タップは静的プリソルブ(制御ループでの逐次調整ではない)・タップ位置は
  実運用値ではなくモデル推定(実タップ位置は非公表)
- SCの規模0.35Pは標準的仮置き — **vm_max 1.266の過電圧が出ており**、SCの
  サイズ・箇所の精緻化(または開閉制御)が必要。既定ONにはこの精緻化が前提
- 既定パイプラインへは未組込(--voltage-regulationオプション化が次)

### MATPOWER実機検証(west_vr) — 「matpowerで解けるの?」への答え=YES

LTC(タップ172本→branch TAP列)+調相SC(→bus BS列)込みの全部入りwestを
`west_vr.mat`として出力(`scripts/diagnostics/export_west_vr.py`・
roundtrip ΔVM/ΔVA=0.0)し、MATPOWER 8.1 `runpf`で3通りの初期値を実機検証:

| 初期値 | 結果 | 損失 | vm範囲 |
|---|---|---|---|
| a) 焼き込み電圧(warm) | ✅ success | 1,833.3MW | [0.945, 1.266] |
| **b) フラットスタート** | ✅ **success** | 1,833.3MW | 同一 |
| c) DC初期化(rundcpf→runpf) | ✅ success | 1,833.3MW | 同一 |

**フラットスタートでも解ける**(=利用者が何も工夫しなくてもrunpf一発)。
3通りとも同一解に収束し、pandapower側の厳密解ともvm一致(3桁)。
これで「構造を消す」(west_reduced)と「物理を足す」(west_vr)の両ルートが
MATPOWER実機で成立した。過電圧vm_max 1.266(SC 0.35P仮置き)の開示は変わらず。
