# OSM を最新にして正典を作り直す手順の調査 2026-10-24

> 調査役のエージェント(読み取りのみ・リポジトリは変更なし)の報告を、そのまま記録として残したものです。
> **このあと確かめたこと**: 「open-keitouzu の対応表の id が 08-16 の振り直しで別の変電所を指す」は名前で数え直して確かめ、PR #103 で座標と名前による引き直しを入れました(今の正典で同じ変電所を指すのは 657 件中 9 件だった)。それ以外の数字(OSM の差分の件数・時間の見積もりなど)は、作り直しの作業のときに確かめ直します。
> 中で参照している計測用のスクリプトは、一時置き場からこのフォルダの隣(同名のフォルダ)へ移しました。

---

## OSM を最新にして正典を作り直す手順の調査

リポジトリのファイルは書き換えていません。コミットも、git の状態を変える操作もしていません。行ったのは `git fetch` と読み取りだけです。計測用のスクリプトはスクラッチパッドに置き、ネットワークは使わず手元のデータだけで比べました。

### 要点（前提の訂正を含む）

1. **「OSM の断面が 06-15 のまま」は正しくありません。**
   - 基底の線と変電所は **2026-08-16 に取り直したもの**です。
     - `data/*_{lines,substations}.geojson` は全件に `osm_id` を持ち、`fetched_at` は 2026-08-16 14:07〜14:38（JST）です。
     - 取得したときの生の応答 `data/osm_refresh/raw/`（50 タイル）のうち、42 タイルは断面が 2026-08-16T05:05〜05:36Z でした。
     - **残る 8 タイルは古いミラーの応答**で、断面は 05-06〜07-12 でした: chubu_lines_t1・chubu_substations_t2・chugoku_lines_t0（中国の線は全域）・hokkaido_lines_t3・hokkaido_substations_t3・kyushu_lines_t2・tohoku_substations_t1・tokyo_lines_t3。
   - `MODEL_VERSION.json` の `osm_snapshot`（06-15）は、`record_osm_snapshot.py` が `data/osm_raw/*.json` だけを読んで出した値です。このフォルダは B 路線の試作 `osm_node_topology.py` のキャッシュで、基底とは関係ありません。Snakefile の注記も同じ誤りです。
   - 発電所はそもそも取り直していません。8 地域は 03-04 の OSM、九州と沖縄は 04-22 に JRP から変換したものです。
   - 変電所の構内の層（介入 #48 の入力）は、Geofabrik の PBF（2026-10-06T20:21Z）から作っています。
   - つまり**今の正典には OSM の断面が 4 種類混ざっています。**
2. **OSM の変化は小さいです。**
   - 10-06 の PBF（`.claude/worktrees/station-nb/data/osm_pbf/japan-power.osm.pbf`）と基底を osm id で比べました（地域の範囲の内側だけ）。
   - 線の way は 33,463 → 33,615 本です。消えたのが 99 本、増えたのが 251 本、形が変わったのが 226 本でした。タグの変化は voltage 58・circuits 46・cables 76 です。
   - 変電所は 6,114 → 6,202 件です。消えたのが 11 件、増えたのが 99 件、voltage の変化が 25 件でした。
   - 変化は 1% 前後です。一方で、ノードの番号は広く振り直されます（次の項）。
3. **ノードの番号は変電所ファイルの並び順で決まります。**
   - `snapped_topology.py` の 608 行目 `sid = f"{region}_sub_{i}"` の `i` は、ファイル内の順番です。変電所が 1 件増えたり消えたりすると、それより後ろの番号がすべてずれます。
   - 分岐点 `_jct_` は座標から作るので、ずれません。
   - 実害はすでに出ています。open-keitouzu の対応表（AGJ v1.6.0 の id で 657 件）のうち、今の正典に存在する id は 227 件だけでした。そのうち同じ名前の変電所を指しているのは **10 件だけ**で、217 件は別の変電所を指していました（例: 城端→開発変電所、上越→つくば並木）。名前の照合は粗いので概数です。08-16 の刷新で壊れたと考えます（推測）。
4. **追跡している手直しのバックアップ `data/db/enrichments.jsonl` は 06-11 から更新されていません。**
   - 線と変電所の行（243,093 行のうち、線 90,519 行・変電所 12,456 行）は、すべて 08-16 より前の形のキー `g:`（形のハッシュ）です。
   - 手元の `grid.db` では、102,975 行がどの地物にも結び付いていません。
   - 今の手直し（名前）は、事実上**基底の GeoJSON の中に印として残っています**。線は `_name_carried` が 28,136 本、端点から付けた名前が 29,521 本です。変電所は住所から作った名前が 3,009 件、そのうち `_2` などの連番付きが 423 件です。

### 1. 基底データの流れ

```
Overpass ──fetch_osm_refresh.py──> data/osm_refresh/raw/{region}_{layer}_t{i}.json（生の応答・追跡外）
                                   data/osm_refresh/{region}_{lines,substations}.geojson（osm_id と全タグ）
   ──migrate_osm_refresh.py──> data/{region}_{layer}.geojson（古いものは data/osm_refresh/backup_old/ へ）
        名前の引き継ぎ: OSM の実名 > 古い名前 > 無名。同じ設備かは形で判定（線は両端 ±約 11 m、変電所は重心の約 100 m の升目）
   ──db ingest → db enrich --lines → db export --out-dir data──> 基底（追跡する）＋ data/grid.db（追跡外）
   ──regenerate_all.py（STEPS）──> docs/data/built/all.json ほか
```

- **DB**（`src/db/geojson_sync.py`）は 3 層です。R 層が生の地物、C 層が手直し、D 層がそれを合わせた出力です。
  - 手直しは地物の id（`w{osm_id}`）で結びます。手で付けた値（manual など）は再 ingest でも残ります。ただし今の C 層には manual も audit_fix もありません。
  - **合成では手直しの値が生のタグに必ず勝ちます**（`compose_properties`）。古い名前の行を osm_id で戻すと、OSM に後から付いた実名を上書きしてしまいます（コードからの推論）。
- **承認済みの判定の上書き**（`config/isolated_verdict_overrides.yaml`・27 件すべて承認済み）は名前と地域で引きます。そのうち 19 件は住所から作った名前です。
- **介入**は STEPS の中で毎回当て直されます。引き方は次の 3 通りです。

| 引き方 | 介入 |
|---|---|
| 新しい OSM から毎回計算し直す | #34 回収、#35/#42/#38 ノード衛生、#47、#44（名前と経路）、#51（変電所名）、#48/#49（地域と名前） |
| 座標が固定 | v2 の帳簿 205 本（端点を 500 m 以内の最寄りの節点へ寄せる）、衛星判読 #36（ぴったり一致のみ）、切断（`data/hokuriku_cuts.json`）、エディタの補足線（kansai 317・hokuriku 321）、供給ノード 31 局 |
| 名前で引く | v1（TEPCO の照合結果と Wikipedia の表。`大間町変電所_3` のような連番名も含む）、地域の訂正 161 件（id と名前の両方を確かめる #39。名前が合わなければ名前で救い、救えなければ捨てる） |

### 2. 08-16 の基底刷新（0e1bd177・ec57bc3d）で何をしたか

- **手順**は 3 段でした: 取得（`fetch_osm_refresh.py`）→ 移行（`migrate_osm_refresh.py --write`）→ `regenerate_all` を 2 周。
  - 1 周目で問題が出ました。「OSM の線へ置き換え済みなら飛ばす」防波堤が、作り直した直後の状態では実証接続 12 本を消していました。そこで「正典にスタブがあるときだけ飛ばす」に直しました。
  - 第 2 部で DB のループを回しました: ingest → `enrich --lines`（名前が消えた 1,398 本を付け直し）→ export → drift の検査 13 件がすべて通過。
- **踏んだ問題**
  - 罠 15: 変電所の重心が動いて、帳簿の座標 34 箇所（2〜274 m）が節点から外れました。帳簿を当てるときに最寄りの節点（500 m 以内）へ寄せる処理を足し、外れた枝 33 本は手で取り除きました。
  - 罠 17: 上の防波堤の欠陥。
  - 中国地方の 245 本と九州の 521 本は、OSM 側の書き直しで名前を引き継げませんでした。
- **所要時間**
  - 取得は約 31 分（raw の時刻で 14:07〜14:38、50 回の問い合わせ）。
  - 基底のコミットは 15:18、治癒を終えたコミットは 20:48 でした。治癒に約 5.5 時間かかっています。
- **検証のやり方**
  - 移行の差分（`docs/reports/osm_refresh_migration_2026-08-16.json`）。
  - 帳簿の名前を引けるか（v2 のドライランの出力で「未解決ノード」0・「距離ガード」の発動 0）。
  - KPI の比較: ノード 17,357→17,881、本系統 15,668→16,061、孤立 457→499、A 75→123。
  - 4 島の AC。
  - drift の検査。
- **後始末**: 試験の固定値 6 件が 06-13 のまま残り、2 か月 CI が赤でした（IMPROVEMENT_LOG の 09-01）。

### 3. 今やるときの手順（そのまま貼れる形）

```bash
R=~/dev/github/project_Hayashi/All-Japan-Grid      # 本体（別のセッションの作業がある・触らない）
W=~/dev/github/project_Hayashi/AGJ-osm-refresh     # 作業用の worktree
S=~/agj-osm-refresh-work; PY=$R/.venv/bin/python
mkdir -p $S/{before,baseline,after}
# 0. worktree と、git の外にある入力（APFS の複製 cp -c。容量は増えず、本体へは書き戻さず、毎時の更新でも動かない）
git -C $R fetch origin && git -C $R worktree add -b data/osm-refresh-$(date +%Y%m%d) $W origin/main
cd $R && git ls-files --others --ignored --exclude-standard --directory data config \
 | grep -v -E '^data/(osm_refresh/|realtime/|\.DS_Store)' \
 | while read p; do mkdir -p "$W/$(dirname "$p")"; cp -cR "$R/${p%/}" "$W/$(dirname "$p")/"; done
cd $W   # data/osm_refresh は作らない（取得が新しく作る。本体の 08-16 の raw は残る）。worktree で git clean はしない

# 1. 前の状態と、今日の入力で旧基底を回した結果（環境の確認。毎時の処理で data/external が変わっているため）
cp docs/data/built/all.json $S/before/all.json
PYTHONPATH=. $PY scripts/build_structures_batch.py --all
PYTHONPATH=. $PY scripts/regenerate_all.py 2>&1 | tee $S/baseline/regen.log        # 15〜25 分
cp docs/data/built/all.json $S/baseline/all.json; cp dist/matpower_national/meta.json $S/baseline/mp_meta.json
PYTHONPATH=. $PY docs/reports/regenerate_reproducibility_2026-10-21/compare.py $S/before/all.json $S/baseline/all.json --out $S/baseline/vs_canon.json
PYTHONPATH=. $PY scripts/build_connectivity_audit.py && PYTHONPATH=. $PY scripts/classify_isolated_subs.py | tee $S/baseline/audit.txt
AJGRID_SLOW_TESTS=1 PYTHONPATH=. $PY -m pytest -q -m canonical -rA tests/test_canonical_islands.py | tee $S/baseline/ac.txt

# 2. DB が基底とそろっているか確かめ、今の手直し（osm_id キー）を退避する
PYTHONPATH=. $PY scripts/db/export.py --verify          # 失敗したら先に scripts/db/ingest.py
PYTHONPATH=. $PY scripts/db/export.py --dump-enrichments $S/before/enrichments_current.jsonl

# 3. 取得（10 地域・25 タイル×2 層＝50 回の問い合わせ・順番に送る・間を 8 秒あける・約 30〜45 分・raw は約 34 MB）
PYTHONPATH=. $PY scripts/fetch_osm_refresh.py 2>&1 | tee $S/fetch.log
for f in data/osm_refresh/raw/*.json; do printf "%s %s\n" "$(head -c 400 $f | grep -o '"timestamp_osm_base": *"[^"]*"' | cut -d'"' -f4)" "$(basename $f)"; done | sort | tee $S/raw_stamps.txt
grep -l '"remark"' data/osm_refresh/raw/*.json        # 打ち切られた応答が無いか（08-16 は 0）
# 古い断面が混じった地域・層は出力を消して取り直す（1 回目は overpass-api.de。失敗すると kumi に回って古くなりうる）
#   rm data/osm_refresh/<region>_<layer>.geojson && PYTHONPATH=. $PY scripts/fetch_osm_refresh.py --region <region>

# 4. 移行（報告のファイル名が 08-16 に固定。08-16 の記録を上書きするので、退避してから戻す）
PYTHONPATH=. $PY scripts/migrate_osm_refresh.py --dry-run && cp docs/reports/osm_refresh_migration_2026-08-16.json $S/migration_dryrun.json
PYTHONPATH=. $PY scripts/migrate_osm_refresh.py --write
mv docs/reports/osm_refresh_migration_2026-08-16.json docs/reports/osm_refresh_migration_$(date +%F).json
git restore docs/reports/osm_refresh_migration_2026-08-16.json

# 5. DB のループ（w キーで退避した手直しは戻さない。戻すと新しい OSM の実名を上書きする）
PYTHONPATH=. $PY scripts/db/ingest.py
PYTHONPATH=. $PY scripts/db/enrich.py --lines
PYTHONPATH=. $PY scripts/db/export.py --out-dir data && PYTHONPATH=. $PY scripts/db/export.py --verify
PYTHONPATH=. $PY -m pytest -q tests/test_db_source_unified.py tests/test_db_geojson_sync.py

# 6. STEPS が読むのに、STEPS の中では作り直さない派生物を先に作る（順序の穴）
PYTHONPATH=. $PY scripts/build_static_site.py             # docs/data/lines_all.geojson（#34 の回収が読む・STEPS では最後に作る）
PYTHONPATH=. $PY scripts/build_structures_batch.py --all  # 構造 DB（無い時しか作られない）

# 7. 正典の作り直し（2 回流してバイト単位で一致するか見る）
PYTHONPATH=. $PY scripts/regenerate_all.py 2>&1 | tee $S/after/regen1.log
$PY -c "import json;s=json.load(open('docs/data/MODEL_VERSION.json'))['steps'];print({k:v for k,v in s.items() if v['status'] not in ('ok','skipped')} or 'all ok')"
grep -E '帳簿端点スナップ|#39|HOLD|skip |未解決|stop' $S/after/regen1.log
cp docs/data/built/all.json $S/after/run1.json
PYTHONPATH=. $PY scripts/regenerate_all.py > $S/after/regen2.log 2>&1 && cmp $S/after/run1.json docs/data/built/all.json && echo 決定的

# 8. 比べる
CMP=docs/reports/regenerate_reproducibility_2026-10-21/compare.py
PYTHONPATH=. $PY $CMP $S/baseline/all.json docs/data/built/all.json --out $S/after/vs_baseline.json   # OSM による差だけ
PYTHONPATH=. $PY $CMP $S/before/all.json   docs/data/built/all.json --out $S/after/vs_canon.json      # 全体の差
PYTHONPATH=. $PY scripts/build_connectivity_audit.py && PYTHONPATH=. $PY scripts/classify_isolated_subs.py | tee $S/after/audit.txt
AJGRID_SLOW_TESTS=1 PYTHONPATH=. $PY -m pytest -q -m canonical -rA tests/test_canonical_islands.py | tee $S/after/ac.txt
PYTHONPATH=. $PY scripts/apply_disclosure_v2.py 2>&1 | grep -E '未解決|距離ガード|候補|新規'   # 帳簿の名前を引けるか（ドライラン・書かない）
PYTHONPATH=. $PY -m pytest -q && $PY -m cogapp -I . -r README.md                               # 固定値と README の数字
```

- `compare.py` は id で突き合わせたあと、座標と kV でも突き合わせます。そのため番号が振り直されても比べられます。
- ノード・枝・本系統・島ごとの成分数は、次のスクリプトで測れます: `docs/reports/osm_refresh_survey_2026-10-24/kpi.py`
  - 中身は `compute_connectivity(nodes, edges)` で、`main_keys` の数と `meta["components"]` を出します。
  - 今の正典の値: 17,743 ノード・19,906 枝・本系統 16,573・本系統の外 1,170・孤立した変電所 367。成分数は北海道 22・東 235・西 292・沖縄 7。回線数の合計 36,263。
  - 監査（`build_connectivity_audit`）とは数え方が違うので、08-16 の KPI と並べるときは監査の数字を使ってください。
- 4 島の AC の今の記録値（`tests/test_canonical_islands.py`）:

| 島 | バス | 畳んだバス | 損失 |
|---|---|---|---|
| 沖縄 | 100 | 0 | 1.88% |
| 北海道 | 831 | 0 | 2.63% |
| 東 | 6,245 | 0 | 2.99% |
| 西 | 7,976 | 6 | 2.16% |

### 4. 危ない所と対策

| 危険 | 中身（実測） | 事前に守る手立て |
|---|---|---|
| ノードの番号の振り直し | `{region}_sub_{i}` はファイル内の順番。id で引くもの: keitouzu の対応表（すでに 10/657）、`disclosure_map_connections.yaml` の `frm: tokyo_sub_NNNN` 7 件（`frm_near` あり）、エディタの未処理の編集、構造 DB のサイト id（重心と名前のハッシュ）→ `observed_transformer_pairs.json` | id では比べない（`compare.py` は座標でも突き合わせる）。#39 のログ（revert / rescue / stale）の件数を見る。対応表は座標と名前で作り直す。番号を osm_id から作る方式に変えるかは判断待ち |
| 座標で引く介入が外れる | v2 の帳簿は 410 端点のうち 400 がぴったり一致、10 は寄せが要る（最大 274 m）。寄せるときに電圧を見ないので、別の電圧の母線へ付く恐れがある。衛星判読 #36 は寄せる処理も節点の確認も無く、外れても黙って宙に浮いた枝を足す。北陸の切断 1 件は**今の基底ですでに当たっていない**（線分にも節点にも一致しない・いつからかは未確認） | 取り直しの前後で、固定座標から最寄りの節点までの距離を全件測る。50 m を超えて寄せたものは目で見る。衛星判読と切断は個別に確かめる |
| 名前で引く台帳 | 承認済みの上書き 27 件のうち 19 件、`disclosure_map` の参照 256 件のうち 22 件、名前のエイリアス 8 件のうち 6 件が住所から作った名前。OSM に実名が付くか、形で引き継げないと名前が変わる。v1 の `_3` のような連番名も同じ | v2 のドライランで「未解決」と「距離ガード」を確かめる。移行の `lost_sample` と台帳の名前を突き合わせる |
| 増えた線との二重計上 | 公表から足した直線の枝は、OSM の線に置き換わるのが「本系統の外の断片が 7 割以上」のときだけ。新しく描かれた線がすでに本系統にあると直線の枝が残り、並列の回線を二重に数える（コードからの推論）。補足の地物は、東京の線 1/218 本・変電所 4/77 件がすでに基底と同じ osm id | 作り直したあと、公表の枝の両端を結ぶ OSM の経路（迂回 1.3 倍以内・同じ電圧）を列挙して人が裁定する。道具は作る必要がある。補足の地物は osm_way_id、供給ノードは 300 m 以内の新しい変電所で照合する（10-06 時点では該当 0） |
| 消えた線 | 10-06 までに 99 本 | `compare.py` の片側だけの枝のうち 154 kV 以上を、OSM の履歴と公表資料で確かめる。荒らしや描き間違いは採らない |
| 古いミラーと打ち切り | 08-16 は 8/50 タイルが古い断面だった。取得スクリプトは断面時刻も `remark` も見ない | 手順 3 の検査と取り直し |
| 手順の順序の穴 | #34 の回収は STEPS の最後に作る `lines_all.geojson` を読む。構造 DB は無い時しか作られない | 手順 6（前もって作る）か、regen を 2 周 |
| 段が失敗しても止まらない | regen は失敗した段があっても後続を続ける | MODEL_VERSION の各段の状態を確かめる |
| 作業環境 | 本体に別のセッションの未コミットの作業がある。git の外の入力（`data/external` 1.8 GB）が要る。シンボリックリンクだと本体の viz・grid.db・構造 DB へ書き込む | worktree と APFS の複製を使い、旧基底で環境を確かめる回を先に入れる |
| 移行スクリプトの癖 | 報告のファイル名が日付で固定。`backup_old` は既にあれば退避しない。名前の引き継ぎは形だけで、osm_id を使わない。`_name_carried` の印は "osm_refresh_2026-08" に固定 | 手順 4 の退避と復元。osm_id による引き継ぎを足すかは判断待ち |
| 刻印の誤り | `record_osm_snapshot.py` は `data/osm_raw` しか読まない | `data/osm_refresh/raw` を読むように直さないと、作り直しても 06-15 と記録される |
| 下流 | flow_map の基準は 10-03 のまま（東 6,467 線、正典は 6,443）で、10-21 の作り直しにも追従していない。日別の断面は署名が合わないと使われない。README の数字、試験の固定値（09-01 の教訓）、データセットの版 | `export_flow_map_data.py` と全日付の `export_day_flows.py`、cog、固定値の更新を、理由を付けて同じ PR で |
| 同じ座標の双子 2,241 組 | 地域ごとの切り出し範囲の重なりが原因 | 地域の範囲は変えない（変えると全部変わる） |

### 5. 判断が要る点

1. **今やる価値があるか。** 変化は 1% 前後です。ただし、古い 8 タイルの解消と、混ざった断面をそろえる効果があります。
2. **取得の方法。** 今ある Overpass のスクリプトを使うか、Geofabrik の PBF にするか。PBF は断面が 1 つにそろい、Overpass に負荷をかけません。ただし fetch と同じ形の GeoJSON に変える変換器がまだありません。
3. **発電所も取り直すか。** 今回は外すことを勧めます。出典付きの容量は座標で引いていて、P03 は id で引いているためです。
4. **先に小さなコード修正を入れるか。**
   - (a) 取得: 断面時刻と remark を検査する、kumi を外す
   - (b) 移行: 報告のファイル名の日付、osm_id での引き継ぎ
   - (c) `record_osm_snapshot` が読むフォルダ
   - (d) STEPS の先頭に `build_static_site` と `build_structures_batch` を置く
   - (e) 衛星判読の適用に節点の確認を足す
   - (f) 番号を osm_id から作る（番号はどのみち振り直されるので、この機会に）
5. **OSM の実名が住所から作った名前を置き換えたとき**、名前で引く台帳（上書き・YAML・エイリアス）を書き換えるか。
6. **`enrichments.jsonl` を作り直してコミットするか。** w キーで作り直すと 32 MB の差分になります。
7. **新しい同一敷地の組（F 類）を帳簿に足すか**（`--update-ledger`）。08-16 は自動で 25 組足しました。人の判断の方針とどう合わせるか。
8. **双子 2,241 組の整理と、keitouzu の対応表の作り直しを同時にやるか。**
9. **採否の物差し。** 一次資料と合っているかで決め、潮流がよくなるかでは決めない。公開物（Pages・データセット）が変わるので、マージをオーナーが見るか委任するか。

### 6. 時間とマシン

| 段 | 見積もり | 根拠 |
|---|---|---|
| 準備 | 15 分 | |
| 旧基底で 1 回回す | 15〜25 分 | 10-21 の刻印で軽い段と潮流・N-1 が 6.4 分。MATPOWER は 3.1 分（10-20 の meta）。CIM は計測なし |
| 取得 | 30〜45 分 | 08-16 は 31 分 |
| 移行と DB | 10 分 | |
| regen ×2 | 30〜50 分 | |
| 比較・監査・4 島 AC・試験 | 30〜40 分 | |
| 人の裁定と治癒 | 半日〜1 日（推測） | 08-16 は 5.5 時間 |

- 計算機が動いている時間は合計 2.5〜3 時間ほどで、大半は待ちです。
- マシンは**手元の Mac を勧めます。** 私的な入力と APFS の複製がそろっていて、どの段も Mac で走った実績があります。NR が発散して macOS でプロセスごと落ちる罠には `nr_guard` が入っています。
- pws-160core は、checkout が浅くて古く、`data/external` もありません。運び込む手間に見合いません。Overpass への取得だけなら 160core からもできます（直接インターネットにつながり、User-Agent は設定済み）。

### 根拠

- 手順とコード: `/Users/shigenoburyuto/dev/github/project_Hayashi/All-Japan-Grid/` の下の次のファイルです（origin/main で読みました）。
  - `scripts/regenerate_all.py`、`scripts/fetch_osm_refresh.py`、`scripts/migrate_osm_refresh.py`、`scripts/record_osm_snapshot.py`、`scripts/build_editor_data.py`
  - `src/server/built_view.py`、`src/powerflow/snapped_topology.py`（608 行・991 行）
  - `src/db/geojson_sync.py`、`scripts/db/{ingest,export,enrich}.py`
  - `scripts/apply_disclosure_v2.py`（430〜465 行・527 行以降）、`scripts/apply_tepco_connections.py`、`scripts/apply_satellite_connections.py`、`scripts/apply_voltage_corrections.py`
  - `scripts/hunt_fragment_*.py`、`scripts/build_static_site.py`、`scripts/build_substation_properties.py`（98 行）
  - `Snakefile`、`tests/test_canonical_islands.py`、`tests/test_db_source_unified.py`、`tests/test_repro_dag.py`
- 報告と台帳: `docs/reports/osm_refresh_2026-08-16.md`、`docs/reports/regenerate_reproducibility_2026-10-21.md`（と `compare.py`）、`docs/reports/IMPROVEMENT_LOG.md`（08-16(2)・09-01）、`docs/MODEL_INTERVENTIONS.md`
- データ: `data/db/enrichments.jsonl`、`data/grid.db`、`data/stations/MANIFEST.json`、`data/external/keitouzu/crosswalk.csv`、`data/hokuriku_cuts.json`、`config/*.yaml`、`docs/data/flow_map/meta.json`
- コミット: 0e1bd177・ec57bc3d（08-16）、0ad6809c（09-02）、c7557510（10-03）、6434cbe5（10-21）
- 私が作った計測スクリプト（手元の PBF との差分と、供給ノードの照合）:
  - `docs/reports/osm_refresh_survey_2026-10-24/diff_pbf_base.py`
  - `docs/reports/osm_refresh_survey_2026-10-24/suppl_vs_new.py`
