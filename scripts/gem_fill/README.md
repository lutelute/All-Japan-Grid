# gem_fill — 1-C GEM容量充填パイプライン（保全コピー）

九州/沖縄2,581件の容量欠損を gem.wiki（Global Energy Monitor・CC BY 4.0）との
突合で充填した 2026-07-11/12 実行分（commit `e959b07` / `a5f8058`）のスクリプト正本。
経緯と結果の正本は `docs/reports/gem_capacity_fill_2026-07-11.md`。

**なぜhere**: 当初はセッションscratchpad（/private/tmp）限りの運用だったが、OS掃除で
**2度**消失した（07-11に transcript から復元・07-14にも再消失を確認）。コード（数KB）は
リポジトリに保全し、**収穫キャッシュ（gem_japan_pages.jsonl 等・数十MB）だけを
scratchpad/作業ディレクトリに置く**方針に改める（dataspace方針=外部データは源泉に留める、
はキャッシュ非コミットで維持）。

## 実行モデル

スクリプトは「作業ディレクトリにデータと同居」する設計（S = 自ファイルのdirname）。
使うときは**このディレクトリごと作業場所へコピー**して回す:

```bash
WORK=/path/to/workdir && mkdir -p "$WORK" && cp scripts/gem_fill/* "$WORK/" && cd "$WORK"
python3 harvest_gem_japan.py gem_japan_pages.jsonl        # ①収穫(~8分・11.6kページ)
python3 match_gem_placeholders.py gem_japan_pages.jsonl <repo> match   # ②決定的突合
# ③ワークフロー入力組立: build_continuation_inputs.py を参照
#   (初回フル実行なら gem_capacity_workflow.js / 復旧・継続なら continuation_workflow.js)
# ④Workflow実行(Claude Code) → 結果JSONを保存
python3 normalize_result_keys.py wf_result.json           # ⑤plantキー正規化(必須)
python3 merge_results.py continuation_result.json wf_result.json   # (継続時のみ)
python3 assemble_confirmed.py wf_result.json confirmed.jsonl        # ⑥確定セット
python3 build_gem_records.py gem_japan_pages.jsonl confirmed.jsonl <repo> recs.jsonl      # ⑦-a 名前一意分
python3 build_geo_records.py gem_japan_pages.jsonl confirmed.jsonl <repo> geo_recs.jsonl  # ⑦-b 名前衝突分(座標キー)
# ⑧追記→検証→適用(リポジトリ側ツール):
#   capacity_provenance.append_records(recs) → capacity_provenance.py verify
#   → PYTHONPATH=. python scripts/apply_capacity_sources.py → pytest
```

## ファイル

| ファイル | 役割 |
|---|---|
| `harvest_gem_japan.py` | gem.wiki 日本8カテゴリの機械収穫（UA明示・maxlag=5・~2req/s・wikitext保存） |
| `match_gem_placeholders.py` | 決定的突合 → AUTO / AMBIG / UNMATCHED(major) の3バケット |
| `gem_capacity_workflow.js` | 初回フル実行のWorkflow（裁定77+スポット+AUTO検証79+捜索11） |
| `build_continuation_inputs.py` | 復旧・継続用の入力組立（キャッシュ照合・ドリフト検査つき） |
| `continuation_workflow.js` | 残作業のみの継続Workflow（07-11復旧で実戦済・118体エラー0） |
| `normalize_result_keys.py` | 結果のplantキー正規化（key+名前混入の救済・組立前必須） |
| `merge_results.py` | キャッシュ済み結果と継続結果の合算 |
| `assemble_confirmed.py` | 採用規則（反証除外・low不採用・GEM側一意性）で確定セット化 |
| `build_gem_records.py` | 名前が全国一意な確定分 → 出典レコード（URL+逐語quote） |
| `build_geo_records.py` | 名前衝突分 → 座標キー`geo:`レコード（D層1:1自己検証・重複unit行ガード） |

## 他地域展開時の要調整点

- `match_gem_placeholders.py` / 各所の対象地域（現状 kyushu/okinawa ハードコード）
- `build_continuation_inputs.py` の `REPO` パス
- `RETRIEVED` 日付（build_*_records.py）— 収穫実行日に更新
- 教訓（詳細はレポート§4/§7）: Workflowの`resumeFromRunId`はセッション跨ぎ不可 /
  結果は都度リポジトリ側へ退避 / GEMページ内の重複unit行（別トラッカー併載）は合算不能
