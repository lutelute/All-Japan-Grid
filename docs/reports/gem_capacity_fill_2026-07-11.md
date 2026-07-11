# 1-C GEM容量充填 — 九州/沖縄プレースホルダ2,581件の出典付き突合（2026-07-11）

モデル: Claude Fable 5（裁定/検証/捜索エージェント含む）。
資産化ロードマップ 1-C（`docs/ROADMAP_ASSET.md`）の実行記録。
正本: `data/generator_capacity_sources.jsonl`（160→**270行**・全行 `capacity_provenance.py verify` PASS）。

## 0. ひとことで

gem.wiki（Global Energy Monitor・CC BY 4.0）日本11,631ページを機械収穫し、九州/沖縄の
容量未知プレースホルダ発電所2,581件と決定的突合＋多段エージェント裁定・敵対的検証を実施。
**同定確定202件 → 出典レコード110件（計18,914 MW）を正本に追記**し、D層（docs/data）へ
出典リンク付きで反映した。密集FIT太陽光の大多数は「同定不能=null」が正解であり、
1,901件の裁定のうち95%はnullで確定（誠実な負の結果）。

## 1. 方法（3系統×敵対的検証）

1. **収穫**: gem.wiki の日本8カテゴリ11,631ページをAPI機械収穫（UA明示・maxlag=5・〜2req/s）。
   ユニット表から Status / Nameplate capacity をパース。収穫キャッシュはリポジトリ非投入
   （データスペース方針=外部データは源泉に留める）。
2. **決定的突合**（`match_gem_placeholders.py`）: 空間グリッド＋燃料整合＋正規化名一致で
   AUTO 134 / AMBIG 1,901 / UNMATCHED 546（major 103）に分類。
3. **エージェント裁定・検証**（計316体・2ラン合算）:
   - 裁定: AMBIG全1,901件（25件/バッチ×77）。規約=「確信が持てなければnull（誤同定は捏造）」
   - スポット反証: 裁定acceptの85件をWebFetch実査（敵対的・疑わしきはrefuted）
   - AUTO検証: major全49＋solar決定的標本30=79件。ページ実在・容量検算・cap_raw逐語存在の3点
   - 捜索: 未マッチmajor 103件をgem.wiki検索APIで捜索＋ヒット3件を同定反証

## 2. 結果

| 段階 | 数 |
|---|---|
| 裁定verdict | 1,901/1,901（accept 94・null 1,807） |
| スポット反証 | 85実査 → **6 refuted**（規模乖離・住所矛盾等） |
| AUTO検証 | 79実査 → **2 refuted**・容量検算不一致0・fetch失敗0 |
| 捜索 | 103件 → ヒット3（岩屋戸52MW・諸塚50MW・響灘火力112MW）全て反証通過 |
| **確定** | **202**（auto 132 / adjudicated 67 / searched 3）・落選29（競合12/低確信9/スポット反証6/AUTO反証2） |
| **出典レコード** | **110件・18,914 MW**（名前衝突ガード89件・Operating無し3件は見送り） |

- レコード内訳: solar 72 / hydro 16 / coal 9 / geothermal 5 / nuclear 2 / gas 2 / oil 2 / waste 1 / wind 1
- 大物例: 玄海2,360（3,4号）・川内1,780・新大分2,875・苓北1,400・九電松浦1,700・電発松浦2,000・小丸川1,200
- 適用: `apply_capacity_sources.py` → generators 356 / plants_all 269 / plants_utility 252 / plants_ipp 17
  （元 capacity_mw は保持・sourced列で併記=「嘘をつかない」表示原則）
- ライセンス: GEM CC BY 4.0 の帰属を `NOTICE` §5 に追加。値は逐語quote+URL引用のみ（データセット再配布なし）

## 3. 検証が実際に捕まえたもの（敵対的検証の実効性）

- **滝上地熱**（AUTO反証）: GEMページ32.5MWは出光の5MWバイナリーを含む。九電滝上発電所は
  27.5MW 1号機のみ=事業者混在の過大計上を防止
- **大分共同発電所**（AUTO反証）: 同一構内の別発電所（新日鐵大分330MW石炭単機）への誤マッチを検出
- **葉山風力**（裁定null）: GEM座標が高知県の設備を波照間に誤配置（thewindpower.net由来の座標誤り）
- スポット反証6件: OSMポリゴン実測面積との規模乖離（0.04haに1.2MWは物理不可能等）を根拠に排除
- 響灘火力（捜索ヒット）: OSM側 fuel=wind は誤タグ（名称は火力・GEM題名と完全一致）。noteに開示

## 4. 障害と復旧（負の結果の記録）

初回ラン（07-11朝）は**月次spend上限**で148/198エージェントが失敗。キャッシュ再開中に
セッションが終了しワークフローが途中死、さらに入力ファイル（/private/tmp scratchpad）が
OS掃除で消失した。復旧手順:

1. transcriptから生成スクリプト全10本（Write入力・ヒアドキュメント）を逐語回収
2. ワークフローjournalからキャッシュ済み裁定75/77バッチ=1,849 verdicts＋スポット20件を回収
3. gem.wiki再収穫→決定的突合の再現で**ドリフトゼロ**を確認（AUTO134/AMBIG1901/major103が完全一致・
   キャッシュ裁定の全plantが現行曖昧集合に存在）
4. 残作業のみの継続ワークフローを手組み（118体・エラー0）→キャッシュと合算

教訓: ワークフロー入力はセッションscratchpadでなく永続側に置くか、生成を決定的にしておく
（今回は後者が成立していたため完全復旧できた）。

## 5. 限界と残課題

- **充填率**: 110/2,581=4.3%。ただし残の大半は匿名小規模FIT太陽光で、GEM側も近似座標・
  無番号ページのため**個体同定が原理的に不能**（nullが正解）。major燃料では突合対象185→38充填
- **名前衝突ガードで89件見送り**: 確定202のうち89件は全国で発電所名が非一意
  （「〇〇市発電所」等の自動命名）のためレコード化不可。applyが名前照合である限りの構造的制約。
  解消には安定キー（region:idx or OSM id）でのapply対応が必要（1-C残課題）
- solar AUTOは標本30/85の検証（refuted 0）。全数検証はしていない
- GEMは二次資料（集約DB）のため confidence=medium。一次資料（有報・自治体資料）での
  格上げは対象を絞って別途
- 適用はD層のみ（base extractのcapacity_mw=-1は設計通り不変）。UCシナリオ等への波及は
  apply経由で自動

## 6. 再現

```bash
# 収穫→突合→入力構築→（ワークフロー）→組立→レコード→追記→適用
python3 harvest_gem_japan.py gem_japan_pages.jsonl
python3 match_gem_placeholders.py gem_japan_pages.jsonl <repo> match
python3 build_continuation_inputs.py           # 入力+ドリフト検査
python3 merge_results.py continuation_result.json wf_result.json
python3 assemble_confirmed.py wf_result.json confirmed.jsonl
python3 build_gem_records.py gem_japan_pages.jsonl confirmed.jsonl <repo> gem_capacity_records.jsonl
PYTHONPATH=. python3 -c "from scripts.capacity_provenance import append_records; ..."
python3 scripts/capacity_provenance.py verify   # ok=270 bad=0
PYTHONPATH=. python3 scripts/apply_capacity_sources.py
python3 -m pytest tests/ -q                     # 1187 passed（既知3失敗=okinawa supplement混入・無関係）
```

スクリプト正本はセッションscratchpad（`.../358d755e.../scratchpad/gem/`）。
リポジトリ非投入（収穫キャッシュ同梱を避けるため）だが、本レポートの手順で完全再現可能。
