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
