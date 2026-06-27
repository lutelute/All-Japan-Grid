# west島 交流潮流「収束」の正直な特性化 — 4面検証統合レポート

- 日付: 2026-06-27
- 対象: `docs/data/powerflow_full/summary.json` の `islands.west`(ac_converged=true)
- ビルダ: `scripts/run_full_powerflow_from_db.py` / ソルバ `src/powerflow/batch_solve.py` / 剪定 `src/powerflow/transforms.py`
- 方式: 全数値を jq/grep/sed で読み取り専用に再確認(再計算・書込なし)
- 作成: モデル判断(機序/物理/文書整合)。本レポートは docs/reports/ 保全用

---

## 0. 要旨(TL;DR)

summary.json の `west: ac_converged=true` は **「西日本60Hz同期系統がフルAC収束した」という意味ではない**。実体は **convergence-by-fragmentation(断片化による収束)**: west を 2531個の非連結成分に砕き、その 94.5%(2393個)に vm=1.0固定の合成無限大母線を植え、DC隘路枝を prune し、許容差を最大10MVAまで緩めて、各成分を独立に数値的に解いたもの。得られた解は **vm_min 0.665 / max_loading 1035%** と運用制約(vm≈0.9-1.1, loading≲100%)を大きく逸脱し、物理的に無意味。一体同期島の west AC は WHITEPAPER/README/ieej/WEST_AC_ANALYSIS が一貫して述べる通り **非収束**で、両者は別問題。

---

## 1. 再確認した実測値(全て主張通り・一致)

```
jq '.islands.west' docs/data/powerflow_full/summary.json
```
| 項目 | 値 |
|---|---|
| n_bus | 10193 |
| n_line / n_trafo | 9793 / 1061 |
| n_edge_skipped | 1390 |
| n_gen | 10087 |
| n_components | 2531 |
| n_slack | 2531 |
| n_synthetic_slack | 2393 (94.5%) |
| ac_converged | **true** |
| ac_solver | nr |
| ac_vm_min / ac_vm_max | **0.66486 / 1.12552** |
| ac_max_loading_pct | **1035.18** |
| dc_max_loading_pct | 984.18 |
| ac_total_loss_mw | 1531.82 |
| solve_seconds | 235.0 |

`_meta`: source=`docs/data/built/all.json`, n_nodes=17333, generated=2026-06-18 04:43:32, scale=`full (no voltage-class reduction)`。islands 合計 836+6205+10193+99 = 17333 で n_nodes と一致。

### 4島比較(westが全指標で最悪)
| 島 | n_bus | 成分密度/1k | 合成slack% | vm_min | max_loading% |
|---|---|---|---|---|---|
| hokkaido | 836 | 56 | 85 | 0.826 | 91 |
| east | 6205 | 83 | 91 | 0.830 | 930 |
| **west** | **10193** | **248** | **94** | **0.665** | **1035** |
| okinawa | 99 | 70 | 71 | 0.917 | 183 |

`ac_converged=true` は4島すべてで立つ。これは系統健全性ではなく per-component-slack 方式を反映するフラグにすぎない。

---

## 2. 機序(west収束が実際にしていること)

ビルダの3段。

1. **成分分割**: ビルド時に kv不整合・同一母線(ja==jb)・線路パラメータ無の枝を計 **1390本**(全枝の約11%)捨て(`run_full_powerflow_from_db.py` L144-169)、west は1つの連結網でなく **2531個の非連結成分**(平均4.03バス/成分)になる。
2. **成分別slack**: `add_per_component_slacks`(L312-342)が成分1個ごとに slack を1個必ず設置。発電機あり成分はその最大容量母線、発電機ゼロ成分は変電所に **vm=1.0固定の合成無限大母線**を植える。west=2531 slack、うち **2393(94.5%)が合成**。実発電機由来は138成分(5.5%)のみ。連結成分は互いに非接続なので各成分は自分の slack で不平衡を独立吸収=2531個の小問題に分解。
3. **隘路除去+許容差緩和**: `solve_island`(L367-388)が prune梯子 `(None, 45.0, 30.0, 20.0)` を順に試し、`prune_dc_infeasible`(transforms.py:541, 最大5ラウンド)が DC角度差>閾値の線/変圧器を `in_service=False` で切断してから AC を解く。ソルバ連鎖(batch_solve.py:34-46)は NR 6段で tolerance_mva = `[1e-2, 1e-2, 1e-2, 1e-1, 1.0, 10.0]`、`enforce_q_lims=True` は最初の2段のみ。最初に大域収束した時点で break。

> 皮肉: ソルバ側コメント(batch_solve.py)自身が「**west島(AC非収束が確定)**…west は速やかに非収束判定→DCにフォールバック」と書いており、収束させているのは別経路の成分分割定式化だと裏付けられる。

`ac_converged` は pandapower の大域フラグ `net.converged` を bool化したもの(L534)。どの prune段で収束したか・何本除去したか・どの許容差/Q制限だったかは summary に**記録されない**(回収不能)。`n_edge_skipped=1390` は build段のカウンタで prune とは別物。

---

## 3. 物理的意味

- **成分間融通ゼロ**: 2531成分は電気的に切れており、連系線潮流・地域間 interchange・広域需給という同期島解析の本質が定義上欠落。これは1つの60Hz系統でなく2531個の孤立網の寄せ集めの解。
- **自明解の水増し**: singleton(1母線成分)≈2209、サイズ≤3 成分≈2476。母線数個+slack は自明に vm=1.0 で収束する。「2531 slack 収束」の大半は系統を解いたことにならない。
- **合成slackが物理を捏造**: 94.5%の成分は実発電機なし。変電所に理想電圧源を勝手に置いて可解化しているだけで、dispatch とは無関係。
- **max_loading 1035%**: 熱容量の約10.35倍の電流。現実なら即トリップ/溶断。原因は隘路除去後の少数枝集中・合成slack注入・非物理スタブ線(intra-substation/recon_line/≤0.06km, transforms.py:596-601 が west の見かけ1632%過負荷の元凶と明記)。
- **vm_min 0.665**: 定格の66.5%。電圧崩壊域。健全解なら vm≈0.95-1.05。
- 結論: `ac_converged=true` は「Newtonが不動点に到達した」数値事実にすぎず、vm 0.665/loading 1035% が示す通り**運用点ではない**。

---

## 4. 正直な判定

1. **一体同期島の west AC は収束しない**(WHITEPAPER/README/ieej/WEST_AC_ANALYSIS + ソルバコメントと一致、本検証も支持)。
2. summary の `ac_converged=true` は**別定式化(成分別slack法)の弱い収束**。矛盾でなく別問題だが「west系統が潮流計算できる」と読むのは**誤読**。
3. 条件付きで言えるのは「west を2531成分へ分割し94.5%に合成無限大母線を与え隘路枝を除去し許容差を最大10MVAまで緩めれば runpp は一度収束する」のみ。**解は運用制約を満たさず物理的に無意味**。
4. 「west が解ける」と言うための未達要件: 孤立母線+断片を正しい連系線で1連結網へ修復 / 合成slackでなく少数の物理基準機+地域間バランス(dispatch/AGC) / 下位網変圧器(66-132kV, 20:1, 非標準電圧)のOCCTO級整備 / 隘路を削らずQ制限を効かせ厳しい許容差(≤1e-2MVA)で収束 / 解が vm≈0.9-1.1・loading≲100% を満たす。**現状いずれも未達**。dispatch/負荷整備前は「予備的試算」、west は DC確定が誠実(memory 8b7dac8)。

---

## 5. 文書間の不整合

| # | 不整合 | 出典 |
|---|---|---|
| 1 | summary west=収束 vs WHITEPAPER/README/ieej/WEST_AC_ANALYSIS=非収束 | summary.json `.islands.west`; WHITEPAPER.md:961; README.md:127; papers/ieej.tex:740; docs/WEST_AC_ANALYSIS.md:120 |
| 2 | ナラティブ内部分裂: PLAN_NEXT は west収束、他は非収束 | docs/PLAN_NEXT.md:20 vs WHITEPAPER/README/ieej |
| 3 | コードとデータ矛盾: batch_solve.py「west AC非収束が確定→DC」 vs summary ac_converged=true | src/powerflow/batch_solve.py |
| 4 | バス数 10193(full) vs 約8400(旧ゾーナル) | summary._meta vs WHITEPAPER.md:961, WEST_AC_ANALYSIS.md:4 |
| 5 | 断片化の三重不整合: PFモデル2531 vs 同summary内 audit 544/main8782 vs WEST_AC_ANALYSIS 52成分/98%被覆 | summary `.connectivity_audit_db2.west`; WEST_AC_ANALYSIS.md:21 |
| 6 | 最新成果物が文書未反映(powerflow_full/per-component/10193/2531 が4文書とも grep 0件) | README/WHITEPAPER/ieej.tex/WEST_AC_ANALYSIS |
| 7 | 再現性ギャップ: --max-ac-buses 既定6000では west/east とも DC-only のはずだが両方収束=別実行 | run_full_powerflow_from_db.py:489; regenerate_all.py:39 |
| 8 | summary._meta に per-component/prune/物理非妥当の caveat 無し | summary._meta |

---

## 6. 推奨表現(location別・抜粋)

- **summary.json `_meta`**: 「ac_converged は per-component 解法の数値収束フラグで一体AC収束ではない。west=2531成分/合成slack94.5%/prune/tolerance最大10MVA。vm_min0.665・max_loading1035%で運用解でない予備試算」と method_note を追加。
- **WHITEPAPER §13.6**: 「フルDBビルダは west を一体でなく2531成分へ分割し成分別slack+pruneで解く。数値収束(ac_converged=true)するが vm0.665/loading1035%で運用解でない。本節の非収束は一体AC潮流の結論で別問題」を追記。
- **README L127**: 「west DC(一体AC潮流は非収束)。per-component試算は数値収束するが過負荷1035%/電圧0.665で物理的に無意味な予備値」。
- **papers/ieej.tex L740**: 「per-component解法では数値収束するが大半は仮想無限大母線による自明解で,電圧0.665p.u.・過負荷1035%と運用制約を満たさず予備的試算にとどまる」。
- **PLAN_NEXT.md L20**: 「4島フルAC収束」→「per-component解法で runpp 数値収束(west=2531成分・合成slack94.5%・vm0.665・loading1035%=予備試算)。一体west ACは依然非収束」。
- **WEST_AC_ANALYSIS.md L120**: 別解法 per-component では数値収束するが2531独立小問題への分解で一体解でない旨を追記。
- **batch_solve.py コメント**: 「一体同期島の west ACは非収束のためDCフォールバック。per-component解法では数値収束しうるが運用解でない」に更新。
- **regenerate_all.py L39**: 呼び出しに `--max-ac-buses 17000` を明示(既定6000では再現不能)、または summary._meta に実行値を記録。

---

## 7. 検証コマンド(根拠)

```bash
jq '.islands.west' docs/data/powerflow_full/summary.json          # 全値一致
jq '.connectivity_audit_db2.west' summary.json                    # 544/8782/193(2531と別物)
sed -n '312,342p' scripts/run_full_powerflow_from_db.py           # add_per_component_slacks
sed -n '367,388p' scripts/run_full_powerflow_from_db.py           # prune梯子(None,45,30,20)
sed -n '34,46p' src/powerflow/batch_solve.py                      # tolerance 1e-2..10.0, q_lims先頭2段
grep -n 'max-ac-buses' scripts/run_full_powerflow_from_db.py scripts/regenerate_all.py  # 既定6000 vs 無指定
grep -rn 'powerflow_full|per-component|10193|2531' README.md WHITEPAPER.md papers/ieej.tex docs/WEST_AC_ANALYSIS.md  # 0件
```

## 出典(リポジトリ内)
- `docs/data/powerflow_full/summary.json`(`.islands.west`, `._meta`, `.connectivity_audit_db2.west`)
- `scripts/run_full_powerflow_from_db.py`(L144-169 build skip, L312-342 add_per_component_slacks, L367-388 solve_island, L489 --max-ac-buses default=6000, L534-535 永続化)
- `src/powerflow/batch_solve.py`(L34-46 ソルバ梯子, L53-55 q_lims記録, 「west島AC非収束が確定」コメント)
- `src/powerflow/transforms.py`(L541-582 prune_dc_infeasible, L596-601 非物理スタブ線→1632%過負荷)
- `WHITEPAPER.md`:961 / `README.md`:127 / `papers/ieej.tex`:740 / `docs/WEST_AC_ANALYSIS.md`:1,21,120 / `docs/PLAN_NEXT.md`:20 / `scripts/regenerate_all.py`:39