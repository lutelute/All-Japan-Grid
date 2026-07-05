# backbone計算モデル — 「縮約してもリアリティを失わない」の実装と24h実証 2026-07-05

**モデル**: Claude Fable 5
**オーナー方針(2026-07-05)**:「結局のところ計算は縮約することも考え、リアルと簡素化の
一途を辿るし、その上でリアリティをなくしてはいけない」
**実装**: `scripts/uc_to_pf_built.py --model backbone`(`build_backbone_net`)

## 1. 設計 — データ資産と計算モデルの分離

- **built(データ資産)は不変**: OSM忠実・全規模・出典付き。編集は人間判断(梃子候補の方針)
- **backbone(計算モデル)は変換**: ≥154kV(沖縄132)のバスだけ残し、下位網の load/gen を
  - 同一成分内 → 最寄り(hop)backboneバスへ集約
  - **断片(backbone無し成分) → 地理的最寄りbackboneバスへ集約**(from_fragmentマーカー)。
    断片上の実在電源(磯子1,200MW・奥清津1,600MW等)は現実には繋がっている —
    これは**現実の回復**であって捏造ではない。全件を帳簿(ledger)に記録
- v4銘板の基幹変圧器(500/275・500/154・275/154等)は縮約後も温存
- 注意: ネット側backboneはトポロジ切断(154kV未満経由の経路は落ちる)。回路論的に厳密な
  縮約は dist/ybus の Kron backbone(行列側・別成果物)

## 2. 縮約の帳簿(透明性 — silent truncation禁止)

| 島 | バス | 断片復帰 load | 断片復帰 gen | 越境集約 | 地理集約max | 銘板残 |
|---|---|---|---|---|---|---|
| east | 6,205→1,310 | 5,553MW | 14,089MW | (帳簿参照) | (同) | 4 |
| west | 10,193→2,779 | 16,722MW | **32,168MW** | 967件 | 57.7km | 3 |

## 3. 24h×4島の結果(full比較)

| 島 | model | バス | AC収束 | slack/需要(med) | vm範囲 | 損失(med) |
|---|---|---|---|---|---|---|
| hokkaido | full | 836 | 24/24 | 3.7% | [0.625,1.006] | 96MW |
| hokkaido | **backbone** | 124 | 24/24 | **2.1%** | **[0.908,1.003]** | 37MW |
| east | full | 6,205 | 24/24 | 25.5% | [0.677,1.040] | 4,838MW |
| east | **backbone** | 1,310 | 24/24 | **9.2%** | [0.701,1.036] | **1,982MW** |
| west | full | 10,193 | 0/24(DC) | 5.7%(DC) | — | — |
| west | **backbone** | 2,779 | **23/24** | 7.6% | [0.687,1.093] | 1,136MW |
| okinawa | full | 99 | 24/24 | 49.9% | [0.733,1.000] | 46MW |
| okinawa | **backbone** | 23 | 24/24 | **47.9%(ほぼ不変)** | [0.977,1.000] | 15MW |

**読み方**:
- **west 23/24 AC** = built系譜で初のwest島AC時系列(6月に「下位網変圧器が真因」と確定した
  仮説の実証 — 下位網を畳むとACが立つ)。t=21のみ有界チェーン不成立→正直にdc_fallback
- **east 25.5→9.2%** = slack解剖(同日)で特定した「断片上の実在電源17.9GW」の復帰効果。
  残り9.2%は損失(3.3%)+UC/PF需給整合の粗さ
- **okinawaがほぼ不変(49.9→47.9%)** = 診断の裏付け。沖縄の主犯はトポロジでなく
  **燃料別容量の不一致**(UC石油1,482MW要求 vs PF石油系600MW)。縮約では直らない=
  次の一手は capacity_bridge の built系適用か沖縄発電フリートの出典充填

## 4. ハマりどころ(再現手順つき)

**macOS Accelerate の cblas_dgemv abort**: run_powerflow のフォールバック鎖のうち
`max_iteration=200-300 / tolerance_mva=0.1-10`(粘りソルバー)が、発散状態のNRを
100反復超えて回すと `BLAS error: Parameter number 3 passed to cblas_dgemv had an
invalid value` で**プロセスごとabort**する(west backbone t=13 で決定的に再現。
スレッド数制限では直らない。例外でなくabortのためin-processで捕捉不能)。
対処 = `_BOUNDED_AC`(厳トレランス1e-2・100反復まで×3構成)+prune ladder。
緩トレランス解は物理的にも意味が薄く、有界化は誠実性も改善する。
正典の solve_island(run_powerflow)は不変更(full系で abort は未発生)。

## 5. 再現

```bash
PYTHONPATH=. python scripts/uc_to_pf_built.py --islands west --all-hours --model backbone
PYTHONPATH=. python scripts/uc_to_pf_built.py --islands hokkaido east okinawa --all-hours --model backbone
```
出力: `uc_pf_built_backbone_allhours_2026-07-05.json`(帳簿は islands.*.backbone_ledger)
