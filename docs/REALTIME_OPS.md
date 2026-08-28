# リアルタイム潮流サイクル 運用メモ

`docs/flow_map.html`（潮流方向・発電稼働率マップ）の NOW 断面を定期更新する仕組み。

## 何をするか

`scripts/realtime_cycle.sh` が1サイクルで以下を実行する。

1. `fetch_denkiyoho.py` — 各社「でんき予報」のエリア実績需要（9社）
2. `fetch_area_fuelmix.py` — エリア需給実績の燃料別内訳（任意・失敗しても続行）
3. `export_flow_map_data.py --realtime` — **実績需要にスケールした NOW 断面 PF**
   → `flows_now_*.geojson` / `gens_now_*.geojson` / `now_meta.json`
4. `export_day_flows.py` — 日別断面（時刻別の再生用アーカイブ）
5. `slim_flow_map.py` → `git commit` + `push`（Pages へ反映）

## 自動実行

launchd に登録済み（**1時間ごと**）。

```bash
launchctl list | grep alljapangrid          # 登録確認
launchctl unload ~/Library/LaunchAgents/jp.ac.u-fukui.alljapangrid.realtime.plist  # 停止
launchctl load   ~/Library/LaunchAgents/jp.ac.u-fukui.alljapangrid.realtime.plist  # 再開
```

plist の原本は `scripts/realtime_launchd.plist`（パスを埋めて `~/Library/LaunchAgents/` へコピーする）。

**なぜ1時間か**: でんき予報の実績が毎時更新なので、30分間隔にしても新しい断面は
増えず commit だけが倍になる。データ源の粒度に合わせている。

**このMacで動く前提**: スリープ中は走らない（復帰後に1回だけ実行される）。
常時稼働させたい場合はサーバへ移すことになるが、`git push` の認証を
サーバ側に用意する必要がある。

## ログ

| ファイル | 内容 |
|---|---|
| `data/realtime/cycle.log` | サイクル本体のログ（取得件数・PF結果・push有無） |
| `data/realtime/launchd.log` | launchd から見た標準出力・エラー |

## 既知の弱点

- **west は AC が収束せず DC フォールバック**する。負荷条件で在線数が変動し
  （実測 8,155〜8,244）、日別断面の線順検証が落ちることがある。NOW 断面自体は出る。
- **日別断面の線順検証**は `flows_{island}.geojson` を基準に照合する。系統を変更する
  介入（ノード衛生・接続追加など）を行ったら、`export_flow_map_data.py`（`--realtime`
  なし）で基準を再生成すること。**再生成を忘れると east/west が黙って出力されない**。
  2026-08-28 に介入#35/#36 後の再生成漏れで実際に発生した。
- 停止に気づきにくい。`docs/data/realtime/latest.json` の `fetched_at` が
  数時間以上古ければ止まっている。

---

# NAS(nas03) への電力系データ退避

git に載せない（重い／再生成可能な）成果物を、**どの版から作ったか**が分かる形で
nas03 に保全する。再生成には時間がかかる（CIM 全国で数分、SubSLD ギャラリーで
約1時間、全国潮流で数分）ため、リリースごとの実物を残しておくと過去版との比較・
再配布が効く。

## 場所と現状

```
/mnt/nas03-share/claude-agent/
  alljapangrid/v1.8.0/     674MB   リリース版スナップショット
  subsld_gallery/          9.4GB   SubSLD 実証ペア図 PNG(全7,239所)
```

`alljapangrid/<版>/` の内訳（v1.8.0 実測）:

| 対象 | 容量 | 中身 |
|---|---|---|
| `dist/cim` | 320MB | CGMES EQ/GL 全国（node-breaker 層込み） |
| `dist/cim_level2` | 150MB | CGMES Level-2（EQ/TP/SSH/SV・解ける潮流ケース） |
| `dist/matpower_canonical` | 18MB | MATPOWER 正典エクスポート |
| `data/osm_raw_towers` | 107MB | OSM 鉄塔（Overpass 生） |
| `data/structures` | 27MB | 変電所構造DB（node-breaker） |
| `docs/data/powerflow_full` | 31MB | 全国潮流の結果 |
| `docs/data/flow_map` | 24MB | 潮流方向マップ（NOW 断面＋日別断面） |

各版に `MANIFEST.json`（version / git_head / git_dirty / archived_at / host / size / targets）が入る。
**これが無いと後で「どのモデルから作ったか」が分からなくなる**ので必ず確認すること。

## 実行

NAS は 160core にしかマウントされていない（Mac 側は未マウント）。したがって
**サーバ側で実行し、git 情報は Mac から渡す**。

```bash
# 1) 成果物をサーバへ（rtk フック回避のため tar over ssh。rsync は使わない）
/usr/bin/tar czf - dist/cim dist/cim_level2 dist/matpower_canonical \
  data/structures data/osm_raw_towers docs/data/powerflow_full docs/data/flow_map \
  | ssh pws-ubuntu-server@10.0.70.42 'cd subsld && tar xzf -'

# 2) NAS へ退避（版名と git HEAD を明示）
ssh pws-ubuntu-server@10.0.70.42 \
  "cd ~/subsld && GIT_HEAD=$(git rev-parse HEAD) \
   NAS=/mnt/nas03-share/claude-agent/alljapangrid \
   bash scripts/archive_to_nas.sh v1.8.0"

# 何を送るか確認するだけ
DRY=1 bash scripts/archive_to_nas.sh
```

## 注意

- サーバ側の `~/subsld` は **git 管理外**。`GIT_HEAD` を渡さないと MANIFEST が空になる
  （2026-08-28 に実際に空で書かれ、やり直した）
- 退避は転送完了を待ってから実行する。転送中に走らせると**不完全な状態で
  MANIFEST が確定する**（同日 CIM が 320MB→38MB で記録された）
- nas02（CLAUDE.md 記載）は現在マウントされていない。保全先は nas03 を使うこと
