# 島境界注入の実装 — east slack≒損失のみ（需給残差+0.02%）

- 日付: 2026-07-07 / モデル: Claude Fable 5
- 位置づけ: slack分解（`east_slack_decomposition_2026-07-07.md`）で特定した最大の構造項
  「島間融通ギャップ（east +4.02% / west −3.30%）」の解消。オーナー指示「進めて」の
  推奨順②。
- 再現: `PYTHONPATH=. .venv/bin/python scripts/uc_to_pf_built.py --islands east
  --all-hours --model backbone --bridge --boundary-injection`

## TL;DR

UCの島間連系フロー（東西FC・北本）を、**builtに実在する境界設備バス**（新信濃変電所・
東清水変電所・上北変電所・今別変換所・飛騨変換所・北斗変換所 — OSM実体を名前で解決、
座標の捏造なし）へ sgen として注入する `--boundary-injection` を実装した。
PF島モデルが表現できなかった島間融通がslackから消え、**east の slack は損失と
ほぼ一致（3.06% vs 損失3.03%、需給整合の残差+0.02%）** した。

## 1. 設計

| 項目 | 内容 |
|---|---|
| 注入点の解決 | `BOUNDARY_POINTS`（島別の設備名＋定格重み）→ net.bus を名前部分一致で解決（最高電圧のバス）。**未解決の点は同ペア内で重みを再配分し開示**（例: east側に佐久間FCの受け皿バスが無い → 新信濃0.83/東清水0.17へ） |
| 重み | 変換所定格（interconnections.yaml converters + 公知: 新信濃600+飛騨信濃900・佐久間300・東清水300 = FC計2,100 / 北本900 = 旧600+新300）。west側は飛騨信濃の西端=飛騨変換所へ900を配分。hokkaido側は函館変換所ノードが無く北斗へ集約（開示） |
| フロー | UC解の interconnection_flows から島境界を跨ぐものだけを符号付き（輸入+）で採用。時刻別に sgen p_mw を設定（輸出は負=消費） |
| 記録 | 注入点・share・時刻別MWをJSONへ（`boundary_injection` / `boundary_mw`） |

## 2. 結果（backbone・--bridge併用・24h）

| 島 | 収束 | mean \|slack\|/demand | 損失/demand | slack−損失（需給整合の残差） |
|---|---|---|---|---|
| east | 24/24 AC | **3.06%** | 3.03% | **+0.02%** |
| hokkaido | 24/24 AC | **1.43%** | 1.20% | +0.23%（蓄電池等） |
| west | 24/24（AC 22 + dc 2） | **1.46%** | 1.65%（AC 22h） | **−0.12%**（AC 22h） |

westの補足: この構成では**ハマり⑨（BLAS abort）が発生しなかった**（t=17/19もAC収束。
境界sgenで数値条件が変わったため。abortは構成依存 — 対策のチャンク隔離手順は
`zone_reattribution_2026-07-07.md` §3 に記録済み）。t=20/21は正直にdc_fallback。
okinawaは島間連系が無いため対象外（bridge較正のみで3.7% — `okinawa_fleet_calibration`）。

### east slack の弧（キャンペーン全体）

```
25.5%  (07-05 full・v4銘板)
 9.2%  (07-05 backbone・断片電源の復帰)
 7.4%  (07-07 --bridge・容量較正でclip解消)
 3.06% (07-07 --boundary-injection・島間融通の構造項解消)
 ≒3.03% = 損失そのもの(slack−loss = +0.02%)
```

UC運用断面とOSM由来PF網の需給整合は、**損失を除けば0.02%まで閉じた**。
残る本質的課題は損失の扱い（UCは損失をディスパッチしない — 開示済みの構造）と、
枝容量制約なしの潮流配分（tie突合で露出済み）。

## 3. 開示・限界

- FCの分割比は設備定格による固定比（実運用の変換所別配分は模擬しない）
- 佐久間FCの50Hz側受け皿バスがeast網に無い（OSMトレース範囲）→ 新信濃・東清水へ再配分
- 旧北本の道内側（函館変換所）ノードが無い → 北斗変換所へ集約
- UC側の連系フロー自体の妥当性（OCCTO実績との突合）は別課題
- west はハマり⑨（BLAS abort）の影響を受けた時刻をチャンク隔離で処理（下記）

## 4. 再現

```bash
PYTHONPATH=. .venv/bin/python scripts/uc_to_pf_built.py --islands east \
    --all-hours --model backbone --bridge --boundary-injection \
    --out docs/reports/uc_pf_built_east_backbone_boundary_2026-07-07.json
# hokkaido / west も同様(westはabort時刻を--hoursで隔離)
```
