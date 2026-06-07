# Ybus Conditioning & Power-Flow Solvability — A Technical Note

**Reading the bus admittance matrix (Ybus) to judge whether an AC power flow
will converge, and to root-cause it when it won't.**

母線アドミタンス行列 (Ybus) の数値性質から「その系統で交流潮流が収束するか」を
判断し、収束しないときに根本原因を突き止めるための技術ノート。
All-Japan-Grid の kansai 非収束を解いた実例に基づく。

---

## TL;DR

- **Ybus の数値性質は「解きやすさ」を語る** — 条件数・固有値・対角優位性・対角成分の
  スプレッドを見れば、その系統が数値的に素直か、悪条件かが分かる。
- **しかし Ybus 悪条件は AC 非収束の *必要条件* であって *十分条件* ではない。**
  潮流は非線形（負荷が一定電力）なので、最終的な可解性は「需要 vs 送電容量」
  （電圧崩壊）にも依存する。
- **実例 (kansai):** `|Ydiag|` のスプレッドが **6.9e20**（他地域の 100〜1000 倍）。
  原因は vertex-snap が生んだ **~5 m の極短線路**で、`y = 1/x ∝ 1/length` が巨大化。
  ただし極短線路を是正しても収束せず → 真因は容量不足（needs demand×0.3）。
- **教訓:** Ybus で「数値的悪条件」を診断 → 悪条件を緩和 → それでも解けなければ
  「需給バランス（電圧崩壊）」を疑う。この順で切り分けると速い。

---

## 1. The question / 問い

潮流計算ソルバ（Newton–Raphson 等）が「収束しない (LoadflowNotConverged)」と
返したとき、知りたいのは次の2つ:

1. **数値の問題か、物理の問題か** — 行列が悪条件で数値的に解きにくいのか、それとも
   そもそも解が存在しない（送電網が需要を流せない＝電圧崩壊）のか。
2. **どこが悪いのか** — どの母線・どの枝が原因か。

Ybus はこの両方の最初の手がかりを与える。

---

## 2. Ybus in one paragraph / Ybus とは

母線アドミタンス行列 $\mathbf{Y}_{\mathrm{bus}}$ は系統の線形部分（送電網）を表す
$n \times n$ 複素疎行列。要素は

$$
Y_{ik} = \begin{cases}
  \displaystyle \sum_{j \in \mathcal{N}(i)} y_{ij} + y_{i}^{\text{sh}} & (i = k)\ \text{(対角=自己アドミタンス)}\\[2mm]
  -\,y_{ik} & (i \ne k)\ \text{(非対角=枝アドミタンス)}
\end{cases}
$$

枝アドミタンス $y_{ik} = 1/z_{ik} = 1/(r_{ik} + jx_{ik})$。潮流方程式
$\mathbf{S} = \mathrm{diag}(\mathbf{V})\,(\mathbf{Y}_{\mathrm{bus}}\mathbf{V})^{*}$ の係数行列であり、
Newton–Raphson のヤコビアンも Ybus から組み立てられる。**Ybus の数値的素性が、その
まま潮流求解の数値的素性に効く。**

> DC 近似では $\mathbf{Y}_{\mathrm{bus}}$ は実の **B 行列**（サセプタンス、$\approx 1/x$）に縮退する。
> 本ノートの診断は DC Ybus（`rundcpp` で必ず作れる）で行うと安定して取れる。

---

## 3. Five metrics to read from Ybus / Ybus から読む5つの指標

| 指標 | 計算 | 何を意味するか | 危険サイン |
|---|---|---|---|
| **条件数** `cond(Y)` | `np.linalg.cond` | 数値的悪条件（誤差増幅率） | `> 1e12` / `inf` |
| **固有値スペクトル** | `eigvals` の絶対値 | ゼロ=孤立/特異、小さい=near-singular | `eig_min ≈ 0`、`eig_ratio` 大 |
| **対角優位性** | 各行 `|Yii|` vs `Σ|Yij|` | 反復法の安定性（優位だと安定） | 非優位行が多い |
| **`\|Ydiag\|` スプレッド** | `max/min` of `\|diag\|` | 枝アドミタンスの極端さ | `ratio > 1e15` |
| **ゼロ対角** | `\|Yii\| == 0` の数 | 孤立母線・全枝 out-of-service | 0 より多い |

それぞれの読み方:

- **条件数 (condition number):** 線形系 $\mathbf{Y}\mathbf{x}=\mathbf{b}$ の解の誤差増幅率。
  大きいほど浮動小数点で解きにくい。送電網が参照母線（slack）で接地されていないと
  $\mathbf{Y}$ は行和ゼロで構造的に特異（`cond=inf`）になるので、**孤立母線がある場合も
  `inf` になる点に注意**（後述）。

- **固有値スペクトル:** `eig_min ≈ 0` は特異（孤立成分 or 接地なし）。`eig_max/eig_min`
  （実効条件数）が大きいほど悪条件。**ゼロ固有値の個数 ≒ 連結成分の自由度**。

- **対角優位性 (diagonal dominance):** 各行で自己アドミタンス $|Y_{ii}|$ が
  周辺枝の和 $\sum_{k\ne i}|Y_{ik}|$ 以上なら優位。優位な行が多いほど反復法
  (Gauss–Seidel / NR) が安定。送電網は普通ほぼ優位（shunt と長枝で）。

- **`|Ydiag|` スプレッド:** 対角成分の最大/最小比。**枝アドミタンスの極端さを映す。**
  これが今回の決定打だった（§4, §5）。極端に短い線路や非標準変圧器があると跳ね上がる。

- **ゼロ対角:** 接続枝が 1 本も無い（孤立）か、全接続枝が out-of-service の母線。
  reconnect 漏れの検出に使える。

---

## 4. Case study: All-Japan-Grid regions / ケーススタディ

収束する地域（okinawa, tokyo）と非収束だった kansai の DC Ybus を比較した（実測値）:

| 地域 | AC収束 | `n` | `\|Ydiag\|` 比 | 固有値比 | 最弱母線の `\|Ydiag\|` |
|---|:---:|---:|---:|---:|---|
| okinawa | ✅ | 81 | **1.9e18** | 3.7e18 | 0, 0, 0, 632, 1090 |
| tokyo | ✅ | 2954 | **7.1e19** | 1.1e20 | 0, 0, 163, 163, 474 |
| **kansai** | ❌ | 1673 | **6.9e20** | **1.4e21** | **0, 0, 0, 0, 0** |

**読み取れること:**

1. 全地域に `cond=inf`・ゼロ対角（孤立母線）がある → これ単体は収束/非収束を分けない
   （tokyo も収束するのにゼロ対角あり）。**孤立母線の有無は決め手ではなかった。**
2. しかし kansai は `|Ydiag|` 比が **6.9e20** と突出（tokyo の約10倍、okinawa の約360倍）。
   **対角成分の幅が桁違いに広い = どこかに極端なアドミタンスがある。**
3. 最弱母線が 5 個とも `0`（kansai だけ顕著）→ 孤立母線も多め。

→ 仮説:「kansai には極端に大きいアドミタンスを生む枝がある」。

---

## 5. Root-causing: from weak buses to 5 m lines / 根本原因の追跡

`|Ydiag|` 最大が **6.89e8** と巨大だったので、巨大アドミタンス $y=1/z$ を作る枝＝
**インピーダンスが極端に小さい枝**を探した。線路インピーダンスは長さに比例
（$r,x \propto \text{length}$）するので、**極端に短い線路**が疑わしい。

線路長分布を見ると（kansai, 1573 本）:

```
min length = 0.0047 km  (= 4.7 m !)
< 0.05 km : 32 本
< 0.1  km : 60 本
< 0.5  km : 510 本  (全体の 1/3)
< 1    km : 661 本
```

**真因確定:** vertex-snap（頂点グラフ化）が、同一変電所構内の近接ノードを
**~5 m の極短線路**で繋いでいた。$x \to 0$ で $y = 1/x \to \infty$ となり、Ybus の対角に
巨大値が乗って悪条件化していた。

> **追試で分かった重要な点:** 極短線路を最小長 0.1〜2 km にクランプして悪条件を
> 緩和しても **AC は収束しなかった**。つまり悪条件は「数値を悪化させる副次要因」で
> あって、非収束の *本質* ではなかった。本質は §6・§8 の需給バランス（電圧崩壊）。

---

## 6. Five lessons / 5つの教訓

1. **Ybus 悪条件は必要条件であって十分条件ではない。** 条件数が悪くても解ける系統は
   あるし、条件数を改善しても解けない系統もある（kansai がまさにこれ）。

2. **悪条件を緩和して解けなければ、需給バランスを疑え。** 極短線路クランプ・並列増・
   無効補償をすべて試して非収束なら、原因は数値でなく物理（送電容量 < 需要 → 電圧崩壊）。
   実際 kansai は **needs demand×0.3** で初めて解けた。

3. **DC Ybus の素性と AC 収束は別物。** DC（線形）は常に解ける。AC（非線形、定電力負荷）
   は解の存在自体が需要に依存する。Ybus は線形部分しか語らない。

4. **「容量を増やす」が逆効果になることがある。** 並列回線復元は他地域の vmin を改善
   したが、kansai では極短線路と相まって `|Ydiag|` をさらに膨らませ悪条件を悪化させた。
   悪条件系統では闇雲な容量増より、まず極端要素の是正・需要適正化。

5. **元 net の収束 ≠ 変換後 net の収束。** pandapower の生 net で解けても、CGMES に
   往復させた net（cim2pp）では収束性が変わる（borderline 地域は揺らぐ）。**可解性は
   最終的に使う形（往復後）で判定すること。**

---

## 7. A solvability checklist / 実用・可解性判定フロー

潮流が収束しないとき、この順で切り分けると速い:

```
[1] Ybus を作る (DC: rundcpp -> makeYbus)。cond / eig / 対角優位 / |Ydiag|比 を見る
       |Ydiag|比 > 1e15 ?
         └─ Yes → [2] 極端な枝を探す
         └─ No  → [4] へ
[2] |Ydiag| 最大の母線に繋がる枝を調べる。極短線路 (length ~ 0) / 非標準変圧器 ?
       └─ 極短線路 → 最小長クランプ or ノード統合
       └─ 変圧器  → 電圧比・容量を是正
[3] 悪条件を是正して再求解 → 収束した? 
       └─ Yes → 完了（原因は数値的悪条件）
       └─ No  → [4] へ
[4] 需給バランスを疑う。負荷を段階的に縮小 (×0.7, ×0.5, ×0.3...) して収束点を探す
       └─ 縮小で収束 → 原因は送電容量不足（電圧崩壊）。容量増 or 需要適正化
       └─ どれでも非収束 → 孤立・トポロジ破綻を疑う（連結성・slack を確認）
[5] 無効電力 (Q) も一応試す: shunt 補償 / gen Q 制限緩和。
       └─ これで収束 → 電圧支持不足（Q 問題）。改善せず → Q は主因でない
```

> All-Japan-Grid kansai の実際の経路: [1] `|Ydiag|`比 6.9e20 → [2] 5 m 線路発見 →
> [3] クランプでも非収束 → [5] Q 否定 → [4] demand×0.3 で収束。
> 真因 = 容量不足 + 悪条件の複合、Q ではない。

---

## 8. Why power flow actually fails / なぜ潮流は解けないのか（理論）

AC 潮流の非収束には大きく3つの型がある:

1. **特異・非連結 (singular / disconnected):** 孤立母線、slack 不在。Ybus の
   ゼロ固有値・ゼロ対角に出る。→ 連結性と参照母線を確保すれば解消。

2. **数値的悪条件 (ill-conditioning):** 極端なインピーダンス比（短線路・非標準変圧器）で
   ヤコビアンが悪条件。`|Ydiag|`比・条件数に出る。→ 極端要素の是正、より頑健なソルバ
   (`init=dc`, 反復増) で改善することが多い。

3. **解の不在＝電圧崩壊 (voltage collapse):** 需要が送電網の輸送能力を超え、潮流方程式の
   実数解が消える（鞍点分岐、ヤコビアンが解近傍で特異）。これは **Ybus 単体では見えない**
   — 負荷（定電力、非線形）が絡むため。判定には連続潮流 (CPF) や負荷余裕 (load margin)
   が要る。kansai はこの型だった。

電圧崩壊点の近傍では、潮流ヤコビアン $\mathbf{J}$ の最小特異値が 0 に近づく。厳密な可解性・
余裕の評価は

- **連続潮流 (Continuation Power Flow, CPF):** 負荷を徐々に増やし、解が消える点
  （nose point）までの余裕を測る。本リポジトリの `scripts/run_cpf.py` 系がこれ。
- **ヤコビアン最小特異値 / 固有値:** 解の近傍で $\sigma_{\min}(\mathbf{J})$ を監視。

Ybus 条件はあくまで **線形ネットワークの素性**であり、可解性の **必要条件の診断**。
十分判定は負荷を含む CPF/ヤコビアンで。

---

## 9. Tooling / 実装

```bash
# Ybus conditioning per region (condition number, dominance, weakest buses)
python scripts/diagnose_ybus.py --regions kansai tokyo okinawa
```

`scripts/diagnose_ybus.py` の核心（pandapower 経由で Ybus を作って解析）:

```python
import numpy as np, pandapower as pp
from pandapower.pypower.makeYbus import makeYbus

pp.rundcpp(net)                     # DC は常に解けて net._ppc を埋める
ppc = net._ppc
Ybus, _, _ = makeYbus(ppc["baseMVA"], ppc["bus"], ppc["branch"])

Yd      = np.abs(Ybus.diagonal())                       # |Ydiag|
offdiag = np.asarray(np.abs(Ybus).sum(axis=1)).ravel() - Yd
nondom  = int(np.sum(Yd < offdiag))                     # 非・対角優位な行数
full    = Ybus.toarray()
cond    = np.linalg.cond(full)                          # 条件数
eig     = np.sort(np.abs(np.linalg.eigvals(full)))      # 固有値スペクトル
ratio   = Yd.max() / max(Yd.min(), 1e-12)               # |Ydiag| スプレッド  ★決定打
weak    = np.argsort(Yd)[:5]                             # 最弱母線（極短線路/孤立の手がかり）
```

> 大規模系統では密行列の `cond`/`eigvals` が重い。疎のまま
> `scipy.sparse.linalg.eigs(..., which='SM')` で最小固有値だけ取る、
> あるいは `|Ydiag|` スプレッドと対角優位性（疎のまま計算可）で代用するとよい。

---

## 10. Limits of this method / 本手法の限界

- Ybus 条件は **線形ネットワークの素性**しか語らない。定電力負荷の非線形性（電圧崩壊）は
  含まない → **可解性の十分判定にはならない**。十分判定は CPF / ヤコビアン特異値。
- `cond=inf` は孤立母線でも起きるため、条件数だけで悪条件を判断しない。
  **`|Ydiag|` スプレッドと対角優位性の方が、極端な枝の検出には有効**だった。
- DC Ybus で診断 → AC で検証、の2段で見ること。DC が素直でも AC が崩壊する系統はある。

---

### See also

- `scripts/diagnose_ybus.py` — 本ノートの診断ツール
- `docs/WEST_AC_ANALYSIS.md` — west（kansai含む）AC 非収束の系統工学的分析
- `docs/CIM_MAPPING.md` §6 — Level-2 CGMES で kansai/hokuriku を demand-scale した経緯
