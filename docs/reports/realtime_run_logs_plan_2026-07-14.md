# 計画: リアルタイム実行ログが見える開発体制（2026-07-14）

モデル: Claude Fable 5。オーナー指示「リアルタイムの実行ログが見える開発を計画」に基づく設計計画。
**ステータス: 計画（オーナー承認待ち・未実装）**。

## 0. ひとことで

この開発で走る長時間ジョブ（再生成・潮流・収穫・pytest・エージェント作業のスクリプト部）を
**標準の実行ラッパ**で起動し、ログと状態を**リポジトリ内の恒久レジストリ**（`logs/runs/`）に落とし、
**:8088 に `/runs` ビュー（SSEライブテール）**を足す。ブラウザを開けば「いま何が走っていて、
どこまで進んでいて、死んでいないか」が開始直後からリアルタイムに見える。

## 1. 動機（07-11の事故が教訓）

1-C GEM充填で実際に起きたこと:
- ワークフローがセッション死で**無言で途中死**（「running のまま」を誰も検知できない）
- ログ/入力が `/private/tmp` の セッションscratchpad にあり **OS掃除で消失**
- 進捗確認が journal.jsonl の grep や背景bashのポーリングという**場当たり**

現状の構造的欠落:
- `:8088/tools` は `subprocess.run(capture_output=True, timeout=30)` = **完了後一括・30秒上限**。
  長時間ジョブは実行も閲覧もできない
- 長時間スクリプトのログ置き場・状態(実行中/成功/失敗/**行方不明**)の規約がない

## 2. 設計原則（このリポジトリの流儀を継承）

- **正典=ファイル**: レジストリは `logs/runs/` のプレーンなディレクトリ+JSON。サーバが死んでも
  ファイルが正。git管理外（`.gitignore` 追加）だが**セッション非依存・/tmp掃除の影響なし**
- **嘘をつかない**: 「running」は heartbeat で裏取りする。heartbeat が古く pid も死んでいれば
  **stale（行方不明）と機械判定して表示**する — 07-11 の「無言の途中死」の再発防止
- **ビュー分離の原則**: `/runs` は閲覧専用の新ビュー（edit≠tools≠runs）。編集系と混ぜない
- **SECURITY 現行方針の維持**: 127.0.0.1 バインド・任意コマンド実行UIは作らない（起動は
  既存の固定ツールレジストリ or CLI から。`/runs` が配るのは `logs/runs/` 配下の実在ファイルのみ）

## 3. アーキテクチャ（3部品）

### 3.1 実行ラッパ `src/runlog.py` + CLI `scripts/run_logged.py`（コア）

```bash
# CLI: 何でも包める
python scripts/run_logged.py --name pf-national -- python scripts/run_national_powerflow.py --all
# Python API: スクリプト内から
from src.runlog import RunLog
with RunLog("harvest-gem") as rl:
    rl.progress(3, 77, phase="adjudicate")   # 構造化進捗(任意)
```

生成物（1ラン=1ディレクトリ）:
```
logs/runs/2026-07-14_1030_pf-national_a1b2c3/
├── run.json   # {name, cmd, cwd, git_head, pid, started_at, heartbeat_at,
│              #  status: running|done|failed|stale, exit_code, ended_at,
│              #  progress: {k, n, phase}}   ← heartbeatスレッドが5秒毎に更新
└── out.log    # stdout+stderr合流・行バッファ・追記のみ
```

- ラッパは子プロセスを `Popen` で起動し、パイプを **tee**（端末にも流す=既存の使い勝手を壊さない）
- `::progress k/n phase` 形式の行を out.log から拾って run.json に反映（スクリプト側は
  print するだけでよい＝progress-display スキルの既存出力とも親和）
- stale 判定はビュー側で導出: `status==running && heartbeat_at が30秒超過 && pid 不在`

### 3.2 :8088 `/runs` ビュー（リアルタイム閲覧）

- `GET /runs` — ラン一覧ページ（実行中を先頭・進捗バー・経過時間・stale警告・モバイル対応は
  07-10 のモバイルCSS流儀に合わせる）
- `GET /api/runs` — run.json の集約一覧
- `GET /api/runs/{id}/stream?offset=N` — **SSE で out.log を tail -f**（FastAPI
  StreamingResponse・offset 再開可・done/failed で自動クローズ）。EventSource で
  ブラウザに逐次描画。WebSocket は使わない（単方向で足りる・実装/依存が軽い）
- パス防御は既存 `_safe_path` の流儀（realpath で `logs/runs/` 配下限定）

### 3.3 既存系との接続

- **tools_dashboard**: ツールレジストリに `long: true` 印を追加し、該当ツールは
  `subprocess.run(timeout=30)` でなく**ラッパ経由で起動して run_id を即返す** →
  UIは `/runs/{id}` へリンク。既存の短時間ツールは現行のまま（回帰なし）
- **Claude Code セッション**: CLAUDE.md に運用ルールを1行追加 —
  「長時間(>1分)のスクリプト実行は `run_logged.py` 経由で起動する」。これで
  Claudeが裏で回すジョブも**オーナーがブラウザで直接**見える（ハーネスのtaskファイル
  への依存が消え、セッション死・/tmp掃除に耐える）
- **progbar / LINE は置換しない**: progbar=Claudeセッション俯瞰、LINE=節目の成果通知という
  現行の住み分けを維持。`/runs` は「プロセスの生ログ」を受け持つ

## 4. フェーズ計画（各フェーズ単独で価値が出る順）

| フェーズ | 内容 | 目安 |
|---|---|---|
| **P0** | `src/runlog.py`+`scripts/run_logged.py`+`.gitignore`。`regenerate_all.py`・PF系2本を移行。この時点で `tail -f logs/runs/<id>/out.log` だけでも実用 | 半日 |
| **P1** | :8088 `/runs` 一覧+SSEライブテール+モバイル。tools_dashboard の long ツール接続 | 1日 |
| **P2** | stale検知の表示・完了/失敗のローカル通知（macOS osascript）・CLAUDE.md運用ルール・単体テスト（registry読み書き/SSE offset再開/stale判定/パス防御） | 半日 |
| **P3**（任意） | pytest のライブ表示プリセット / ワークフロー journal.jsonl のブリッジ表示 / ランのローテーション(30日) / LINE完了通知のラッパ直結 | 適宜 |

## 5. 非目標

- リモート公開・認証機構（127.0.0.1 限定を維持。外から見たいときは Tailscale 越し）
- 任意コマンドを打てる実行UI（固定レジストリ原則を崩さない）
- progbar / LINE ブリッジ / claude-mem の置換

## 6. 要オーナー判断

1. **この計画で着手してよいか**（P0→P2 で計2日目安）
2. LINE 通知をラッパから直接打つか（line-bridge の外部I/F調査が必要・P3）、
   現行どおり Claude 経由の節目通知に留めるか
3. Claude の長時間バックグラウンド実行を**全部** run_logged 経由に強制するか
   （CLAUDE.md ルール化・推奨）

## 7. 受け入れ基準（P2完了時）

- 任意の長時間スクリプトを run_logged で起動 → **5秒以内に** `/runs` に現れ、ログが流れる
- 実行中プロセスを kill -9 → 30秒以内に `/runs` 上で stale 表示になる（無言のrunning放置なし）
- サーバ再起動してもラン履歴とログは消えない
- 既存 tools/editor の全機能に回帰なし・ゲート(pytest)グリーン維持
