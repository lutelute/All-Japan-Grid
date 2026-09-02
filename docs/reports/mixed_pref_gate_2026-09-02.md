# 介入#42 混在県個別化 — 採用ゲート(2026-09-02)

- モデル: **Claude Fable 5.1**(フォーク trackB3-mixedpref)
- 状態: **採用・既定ON**(`apply_node_hygiene.py --mixed-pref` 既定 True・STEPS/Snakefile は明示フラグも渡す)
- 正典適用: `docs/data/built/all.json` にフリップ **108 ノード**(tokyo→chubu 69・chubu→tokyo 20・chubu→tohoku 19)。
  帳簿 `docs/data/fragments/mixed_pref_ledger.json`(全件・逆再生可)、バックアップ `all.json.pre_mixed.bak`(gitignore)、
  マーカー `mixed_pref="intervention42"`
- 数値の正本: `mixed_pref_gate_2026-09-02.json`(pre/mid/post の3段・判定基準つき)

## 何をしたか

#6/#38 の周波数ガードは混在県(長野・新潟・静岡)の周波数跨ぎ候補 **243 ノードを県単位で丸ごと**保持していた。
#42 は出典つき境界資産(`data/reference/freq_boundary_mixed.geojson`: 長野の東京電力PG 50Hz 供給域=一次/二次情報別、
新潟の 60Hz 飛び地、静岡=富士川主流 W05)と越境幹線/FC ホワイトリスト(`freq_corridor_whitelist.json`)で
**守るべきものだけを守り**、残りを領土(座標→県→エリア)で再属性する。拒否は3段:
(A) 保護域内 / 富士川実河道と領土定数の不一致 → 維持 (B) FC 名・越境幹線に接する → 拒否
(C) 切断ガード: 仮適用で新規の島跨ぎエッジが生じるフリップを拒否して反復(収束時点で新規切断 0 を構造的に保証)。

計画: ガード対象 243 → フリップ 108・WL拒否 10・切断ガード拒否 28・保護域維持 79〜80・河道不一致維持 17。
既存の跨ぎ 130(触らない)・**新規切断 0**。物理接続(OSM 由来)は不変更 — region ラベルのみの現実回復(#5/#38 の延長)。

## 3段比較(pre=正典HEAD / mid=同経路#35の保留断片2件適用後・#42前 / post=#42後)

同じ正典適用経路(`apply_node_hygiene.py --write`)に **#35 の保留断片 2 件(5 ノード・2 エッジ: 川上村変電所の完全双子 1 +
箱根付近 chubu junction 4)** が残っており、`--mixed-pref --write` で同時に適用された。#42 単独の効果を分離するため
`all.json.pre_mixed.bak` を mid として計測した(帳簿 `node_hygiene_ledger.json` は 08-27 分に**追記**・上書きしていない)。

| 指標 | pre | mid | post | Δ(#42=post−mid) |
|---|---|---|---|---|
| ノード / エッジ | 17,745 / 19,895 | 17,740 / 19,893 | 17,740 / 19,893 | 0 / 0(ラベルのみ) |
| 周波数跨ぎエッジ | 130 | 127 | **99** | **−28** |
| 本系統外ノード(変電所) | 1,292 (373) | 1,292 (373) | **1,273 (369)** | **−19 (−4)** |
| 成分数 east / west | 186 / 407 | 185 / 406 | 168 / 400 | −17 / −6 |
| 本系統サイズ east / west | 5,097 / 6,470 | 5,097 / 6,470 | 5,086 / 6,487 | −11 / +17 |

潮流(fy2023r2・built_full_v4_nameplate・ピーク断面・pref_demand/reactive_comp/dedup 既定):

| 島 | 時刻 | pre | mid | post | 判定 |
|---|---|---|---|---|---|
| west | 17 | AC・slack 9,086.9・loss 2,782・vm_min 0.667・7,931バス | 同 9,086.8 | **AC・slack 8,796.0・loss 2,491・vm_min 0.667・7,946バス** | ✅ slack **−291MW**・損失 −291MW |
| east | 17 | AC・slack 5,162.3・vm_min 0.822・6,267バス | 同 5,162.3・6,266バス | AC・slack 5,159.6・vm_min 0.815・6,223バス | ✅ 収束維持(vm_min −0.007・観測) |
| hokkaido | 18 | AC・slack 820.8・vm_min 0.856 | 同 | 同 | ✅ 不変 |

判定基準(全8項目合格): 跨ぎエッジ・本系統外ノード・孤立変電所が増えない / west ピーク AC 収束・slack 悪化 ≤ +50MW
(mid 比・pre 比とも) / east ピーク AC 収束維持 / hokkaido 不変(±1MW)。

## 読み方・限界(正直に)

- **west の slack −291MW は「東信〜南信・富士川以西の中部設備が west 島に合流した」効果**(+15 バス・成分 −6)。
  需要が近い電源で賄われる分だけ合成 slack が減った。実在の潮流値の裏付けではない(#9-#11 の上の数字)。
- east は tokyo ラベルの 43 バスが抜けて(南信・蒲原など実際は中部電力の設備)vm_min が 0.822→0.815 と僅かに下がった。
  跨ぎ 130→99 のうち残る 99 本は**既存の実跨ぎ(FC・越境幹線・保護域境界)**で、#42 では触らない設計。
- 境界資産の二次情報部分(長野 protected_50hz_secondary: 軽井沢・御代田・東御・上田・立科・佐久穂・小海・南牧・南相木・北相木・川上)は
  一次資料未確認(資産内に明記)。一次で否定されたら feature を落とすだけで再計画される(冪等)。
- 座標→ノード索引は同一座標の重複ノードを後勝ちで引く(監査と同規約)。切断ガードは保守的判定(拒否側に倒れる)。
- 新潟 chubu→tohoku 19 件には鉄道変電所(えちごトキめき鉄道 二本木)を含む — 領土は東北電力エリアだが給電元は未確認。

## 無効化・復元

1. `apply_node_hygiene.py --no-mixed-pref`(以後の regen で適用しない)+ `git revert`
2. `docs/data/fragments/mixed_pref_ledger.json` の flips を to→from で逆再生(id 付き・全件)
3. `docs/data/built/all.json.pre_mixed.bak` を戻す(gitignore・ローカルのみ)
4. `reattribute_node_regions(mixed_pref=False)`(既定 OFF: 正典側で適用済みのため PF ドライバは再計画しない)

## 再現

```bash
PYTHONPATH=. python3 scripts/audit_mixed_pref_flip.py                 # ドライラン(適用済み正典では計画 0)
PYTHONPATH=. python3 scripts/apply_node_hygiene.py --mixed-pref        # 判定のみ
PYTHONPATH=. python3 scripts/uc_to_pf_built.py --islands west --hours 17 --out /tmp/w.json
PYTHONPATH=. python3 -m pytest -q tests/test_mixed_pref.py
```
