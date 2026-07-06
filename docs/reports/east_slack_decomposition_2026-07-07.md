# east backbone slack 9.2%の内訳分解 — 恒等式が機械精度で閉じた（もはや「粗さ」ではない）

- 日付: 2026-07-07 / モデル: Claude Fable 5
- 位置づけ: backbone計算モデル（`docs/reports/backbone_model_2026-07-05.md`）で
  east slack 25.5→9.2%に改善した後の「残り9.2%はなにか」の分解。

## TL;DR

east backbone の slack は**未知の粗さではなく、既知構造3項の合計**だと確定した:

```
slack = 損失 + 島間融通ギャップ + 注入clip (+ battery unmatched)
        3.57%       4.02%           1.90%        0.02%     = 9.51%   (残差 0.00%)
```

24時間×全断面で恒等式が**機械精度**（t=17残差 2.3e-13 MW）で成立する。
`--bridge`（okinawa較正で配線済みの容量較正）を適用すると clip が消えて
**9.51% → 7.41%**。残る7.4%の内訳は損失3.36%（物理的に正当 — UCは損失分を
ディスパッチしない）+ 島間融通4.02%（構造的 — PF島モデルは東西FC・北本を持たない）。

## 1. 方法（新計器2つ）

1. **注入clip/unmatchedの記録** — `uc_to_pf_built.py` が時刻別に
   `injection_issues`（燃料別のclip超過MW・受け皿なしMW）をJSONへ記録
   （silent truncation禁止の徹底）。
2. **UC側の島需給恒等式** — `scripts/uc_island_gap.py`（新設）が
   `requested（注入要求）- demand（PF負荷）= 島間融通ギャップ` を時刻別にダンプ。
   eastは毎時1,300〜3,000MWの**輸入超過**（東西FC: chubu→tokyo ~2,100MW張り付き
   + 北本: ±900MW）で、PF島モデルには輸入が存在しないためこの分が丸ごとslackに落ちる。

## 2. 分解結果（24時間計・demand比）

| 成分 | 07-05正典 | 07-07 bridgeなし | 07-07 --bridge | 性質 |
|---|---|---|---|---|
| mean \|slack\|/demand | 9.19% | 9.51% | **7.41%** | |
| 損失 | 3.57% | 3.57% | 3.36% | 物理的に正当（UCは損失を配らない） |
| 島間融通ギャップ | 4.02% | 4.02% | 4.02% | 構造的（PF島に東西FC・北本がない） |
| 注入clip | （未計装） | 1.90% | 0.01% | **tokyo石炭 平均968MW/h** → bridgeの容量パッチで解消 |
| 注入unmatched | （未計装） | 0.02% | 0.02% | UC地域集約蓄電池の受け皿なし |
| 残差 | 1.60%(＝実はclip) | **0.00%** | **0.00%** | 恒等式が閉じた |

- t=17検算（bridgeなし）: slack 5,127.3 = 損失2,376.9 + ギャップ1,673.6 + clip 1,076.8（残差 2e-13）
- 07-05正典の「残差1.60%」は旧計器でclipが見えていなかっただけで、正体はほぼ全てclip。
- 07-05（9.19%）と07-07（9.51%）の差は、okinawaフリート変更後のUC再solve（縮退解の揺れ）。

## 3. --bridge の east 適用内容（正直化）

- patched=13（勿来IGCC・広野IGCC等の出典付き公称容量 — tokyo石炭のclip解消の主因）
- dedup_disabled=6（bbox重なり由来の大型機二重計上を容量0化）
- nuclear_stopped=6（稼働炉リスト外のidle原子炉=柏崎刈羽等を容量0化、Δ-13.8GW。
  UC側は稼働炉リスト適用済みなのでディスパッチには元々現れない — PF側の見かけ容量の正直化）
- unmatched_patches はeastに存在しない九州・沖縄系の発電所のみ（適用は健全）

## 4. 次の改善レバー（優先順）

1. **島境界注入の実装**（効果 -4.02%）: UCの連系フロー（`uc_island_gap`が出力済み）を
   PF側の境界バス（新信濃/佐久間/東清水FC・北本上北）に注入すれば構造項が消える。
   slackは損失+微小残差（~3.4%）まで下がる見込み。
2. **--bridge の既定ON化**（効果 -2.1%）: 96断面正典の更新とセットでオーナー判断。
3. **損失の扱いの明示**: UC需要への損失率上乗せ or 「slack≒損失」を正典解釈として開示。

## 5. 再現

```bash
PYTHONPATH=. .venv/bin/python scripts/uc_island_gap.py --island east
PYTHONPATH=. .venv/bin/python scripts/uc_to_pf_built.py --islands east --all-hours \
    --model backbone --out docs/reports/uc_pf_built_east_backbone_nobridge_2026-07-07.json
PYTHONPATH=. .venv/bin/python scripts/uc_to_pf_built.py --islands east --all-hours \
    --model backbone --bridge --out docs/reports/uc_pf_built_east_backbone_bridged_2026-07-07.json
```

## 6. 開示・限界

- zone汚染（`phantom_tie_zone_contamination_2026-07-07.md`）はeastでは軽度
  （tohoku↔tokyo跨ぎ50本・同名発電所重複122件）だが、需要・発電の**地理分布**には
  影響が残る（slack総量の恒等式には現れない）。zone再属性（オーナー判断待ち）とは独立。
- 島間融通ギャップの符号はeastでは常に輸入（slack正に寄与）。輸出超過の島では
  slackを負側に押す（okinawaの負slack断面と同型の現象は融通のない沖縄では蓄電池由来）。
- UC縮退解の揺れ（±0.3%）は分解の各項に吸収され、恒等式自体は常に閉じる。
