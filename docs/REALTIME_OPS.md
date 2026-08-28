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
