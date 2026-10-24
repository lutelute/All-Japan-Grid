# 外部の公表データを毎時の処理に組み込む設計の調査 2026-10-24

> 調査役のエージェント(読み取りのみ・リポジトリは変更なし)の報告を、そのまま記録として残したものです。
> **このあと確かめて直したこと**: (1) 地点需要(#30)の年度の二重計上 → 数え直して確かめ PR #104 で直した (2) `fetch_system_disclosure` が通信の失敗でも 0 を返す → この PR で直した(通信の失敗は 2、いつもの「該当リンクなし」は 0)。staging と差分の報告の仕組み(§4・§5)は提案で、まだ入れていません。
> 中で参照している計測用のスクリプトは、一時置き場からこのフォルダの隣(同名のフォルダ)へ移しました。

---

## 調査の報告: 外部の公表データを毎時の処理に組み込む設計

ファイルの書き換えとコミットはしていません。リポジトリのパスは `/Users/shigenoburyuto/dev/github/project_Hayashi/All-Japan-Grid` からの相対で書きます。コードは `origin/main`(437d1ca8)を `git show` で読みました。ネットワークへの確認は次の 4 つだけです。
- 様式5・空容量の一覧ページの dry-run(スクリプトを scratchpad に写して実行。書き込みなし)
- open-keitouzu の `git ls-remote` と、ピンとの compare API
- REI の ArcGIS の層のメタデータを 2 回
- HKS のトップページを 1 回

### 先に結論
1. **モデルの入力になるもの(差分を見てから反映)**: 空容量一覧・インピーダンス・open-keitouzu・変圧器の台帳・地点需要(point_demand)の 5 つ。
   - 空容量一覧・インピーダンス・open-keitouzu の 3 つは、regen の段 `apply_circuit_sources`(介入 #44)が**毎回 data/external から読み直します**。台帳経由ではありません。取得物を本番の置き場に入れた時点で、次の regen の回線数が変わります。
   - 地点需要は、毎時の NOW 断面と日別断面が**実行時に**読みます。
2. **観測・表示だけのもの(自動でよい)**: 発電所マスタ・FIT・HKS・REI。発電所マスタの出力を読むのはローカルのビューア(`scripts/viz/*.html`)だけで、Pages にもモデルにも入っていません。REI は main に使う側がありません。
3. **組み込む前に直す欠陥が 2 つあります(実測)**。
   - 地点需要(#30・既定 ON)が**年度をまたいで足されています**。`src/powerflow/point_demand.load_point_demand` の結果は 615.4 MW、最新年だけだと 285.5 MW で約 2.2 倍です。492 変電所のうち 351 が複数年を持っています。新しい年度が入るとさらに増えます。
   - FIT は**北海道が 0 件**で、東京都は 1,304 件が二重です(`fit_13.東京都` と `13.東京都` の両方を読んでいる)。
4. **すでに新しい公表が出ています**。初回の実行で staging に保留が出ます。
   - インピーダンス: 東北 `impedance_2026_02.xlsx`(手元は 2025_02)、関西 `01_roop_2025_1.pdf`(手元は 2024 まで)
   - 空容量: 北陸と四国が 202610(手元は 202608)、東北の local01_tr が 202609(手元は 202607)
   - open-keitouzu: 上流がピン db1c6c6 より 2 コミット先です(どちらも 08-13、`data/crosswalk.csv` だけ +61/−73)。
5. **既存の週の段(PR #100)にも穴があります**。`fetch_system_disclosure` は取得に失敗しても終了コード 0 を返すので、通信が落ちた週にも印が付き、その週は飛ばされます。

---

### 1. データ源ごとの表

| データ源 | 取得 | 後段(順) | 使う側 | モデルの入力か | 公表元の頻度 | 環境変数 | 自動化の推奨 |
|---|---|---|---|---|---|---|---|
| 発電所マスタ | (FIT と HKS) | `build_generator_master.py` → `build_g_table.py` → `geocode_generators.py --min-mw 1` → `build_fit_geojson.py` / `build_generator_geojson.py` / `build_generation_geojson.py` | `normalized/generator_master*.csv`・`g_table_units.csv`(読む側なし)・`system_disclosure/viz/*.geojson` → `scripts/viz/observed_flow.html`(ローカル) | いいえ。表示だけ | 元データしだい | ×(全部 ROOT 固定) | 月 1・自動で本番へ |
| FIT | `fetch_fit.py`(playwright・47 都道府県・約 82MB) | → マスタ | 同上 | いいえ | 月次(docstring)。手元は _202606 を 08-13 に取得 | ×(`relative_to(ROOT)` なので置き場を外へ出すと例外) | 月 1・自動。ただし 47 県そろったときだけ入れ替える |
| OCCTO HKS | `fetch_hks.py 2024/04/01 2024/04/07`(playwright)。手元は 1 週分だけ | → マスタ(297 発電所)・`build_generation_geojson.py` | 同上 | いいえ | 推測: 日々の速報 | × | 月 1 で先月の第 1 週を取る・自動 |
| REI | `fetch_rei_gridmap.py`(41 層・38,331 件・65MB) | なし(08-17 の全国突合の走査スクリプトは main に無い) | レポートだけ | いいえ | 層の最終編集日 2023-04-10/18(2 層で確認) | ×。しかも**既存ファイルは取り直さない**(L90) | 月 1・メタデータだけ見て変わった層を取り直す・自動 |
| open-keitouzu | `keitouzu/fetch_keitouzu.py`(コミットにピン・sha 照合) | `adjudicate_xwalk` → `crosscheck_keitouzu` → `export_divergent_geojson` → `gen_adjudication_queue` | **#44 S4**(routes.csv の回線数)・Pages の食い違いオーバーレイ(`docs/data/keitouzu_divergent.geojson`)・toporag | **はい**(regen) | 上流は 08-13 以降動きなし | × | 月 1・上流の先端だけ見る → 進んでいれば staging → ピンを上げる PR(手) |
| 空容量一覧 | `fetch_system_disclosure --kind capacity`(関西・四国・北海道)と `--kind capacity_less`(関西)、`fetch_capacity_tables.py`(6 社)。東京は `--kind yosochoryu_csv` | `build_line_observations` → `export_obs_compare` / `export_obs_local`。`calibrate_line_capacity`(#45)。`fetch_transformer_lists`(下の行) | **#44 S1〜S3**(九州 S7 は手で取った PDF のプール)・#45(既定 OFF)・#49/#50(台帳経由)・観測の照合 | **はい** | 月次(ファイル名の YYYYMM で確認)。関西はほぼ毎日(台帳の記録) | 一部。`fetch_system_disclosure`・`build_line_observations` は○、`fetch_capacity_tables`・`calibrate`・`apply_circuit_sources` は × | 週 1・staging → 差分 → 保留 |
| インピーダンス | `fetch_system_disclosure --kind impedance`(10 社・0.8MB) | `parse_impedance` → `match_impedance_to_model` → `compare_observed_derived_impedance` → `build_line_observations` | **#44 S5**(回線別の行)・観測の表。`--line-impedance` と #27/#46 は既定 OFF | **はい** | 年 1〜2 回(2025_02〜2026_07 とばらばら) | 一部。`parse_impedance` は ×(`--outdir` だけ)、match/compare は○(`AGJ_DISCLOSURE_NORM/OUT`) | 月 1(日々の一覧確認で前倒し)・staging |
| 変圧器の台帳 | `python3 -I fetch_transformer_lists.py`(95 ファイル・55MB。うち東京の PDF が 54MB) | `score_transformer_topology.py --export / --export-capacity / --export-levels` | `data/reference/published_transformer_pairs.json`(#49 既定 ON)・`config/transformer_capacity_by_pair.json`(#50 既定 ON)・`published_missing_levels.json`(構造 DB) | **はい**(追跡ファイルは手で書き出したときだけ変わる) | 空容量一覧と同じ源泉なので月次 | ×(REPO 固定・`git -C REPO check-ignore`) | 空容量が変わった週に、変わった社だけ staging → PR(手) |
| (関連)地点需要 | 潮流実績の変圧器 CSV(週の段で取得済み) | `parse_point_demand.py` | **#30 既定 ON**。NOW 断面・日別断面・正典 PF・配布 MATPOWER・CIM L2 が**実行時に**読む | **はい** | 年 1 | ×(本体の絶対パス固定 L25) | 変圧器のファイルが変わった週だけ staging(手で反映) |

補足:
- 各社の系統図 PDF(台帳の `keitouzu` と `flow_maps`)は人が読むためのものです。転載禁止なので git の外に置いたまま、月 1 で本番へ自動で入れてよいと考えます。
- 最終取得日は依頼の一覧どおりでした。空容量の関西・四国は 08-11、東京は 08-12 で、9-02 に取ったのは 6 社だけです。

### 2. 手元を見て分かった欠陥

1. **地点需要が年度をまたいで足されている**(上の結論 3)。`parse_point_demand.py` L119 は全年度の `jisseki_*_tr_*` を読み、`load_point_demand` は年度を見ずに合算しています。docstring には「複数バンクを合算」としか書いておらず、意図しない合算だと判断しました。L120 は沖縄の `tyoryu_2025_2.csv` を名前で固定しています。
2. **FIT**: 北海道が 0 件です。原因は推測で、`pg.click("text=北海道")`(L71)が別の要素に当たっている可能性があります。また `build_generator_master` は `FIT/*.xlsx` を全部読む(L115)ので、来月の版が並ぶとさらに二重になります。
3. **東京の空容量が使う側に届かない**。`yosochoryu_csv` は `tokyo/yosochoryu_csv/` に保存されます(fetch L106)。一方、使う側の 3 本(`apply_circuit_sources` L213・`calibrate` L136・`build_line_observations` L315)は `tokyo/capacity/` を読みます。今の `tokyo/capacity/` は 08-12 に手で置いたものです(中身は同じでした)。
4. **年月入りのファイル名が積もって二重に読まれる**。
   - `parse_impedance` は xlsx を全部読むので、東北の 2025_02 と 2026_02 が両方入ります。
   - 関西は `01_roop_2024_1.pdf` を固定で選んでいて(L224)、2025 版は無視されます。
   - `calibrate` は四国の全月を読みます(L106)。
5. **終了コードと取得のやり方**。
   - `fetch_system_disclosure` は失敗しても 0 を返します(結論 5)。リクエストの間に待ちもありません。
   - `fetch_capacity_tables` は毎回上書きして出所を追記し、変化の検出がありません。
   - `fetch_transformer_lists` は取得の前に `rmtree(RAW/u)` するので(L283)、途中で失敗するとその社の原本が消えます。
6. **runner で危ないこと**。runner は疎な worktree で、`data/external` のうち `normalized` だけが本体へのリンクです。
   - ROOT 固定のスクリプトは、runner の空の `data/external` を読み書きします。`parse_impedance` をそのまま流すと、何も読まずに**リンク越しに本体の `impedance_lines.csv` を空で上書き**します(出力が空でも書く)。
   - `fetch_capacity_tables` は追跡ファイル `data/external/system_disclosure/provenance.jsonl` に追記します。runner では毎時の `checkout -f` で消えます。
7. **中部の潮流実績が使われない**(既存の段の穴)。10-24 に `rule_78〜92` を取得しましたが、`convert_chubu_flow.py` は手で改名した `jisseki_*_<FY>.xlsx` しか読みません。台帳の URL は年度ごとの固定なので、2026 年度の分は自動では見つかりません。
8. **気づかれずにモデルへ入る経路**。週の段が自動で作り直す `line_observations.csv` は、次の regen で #44 S6 として回線数に効きます。また regen は #44 を毎回外部データから作り直すので、正典は git の外の状態に依存しています。

### 3. 直す所(環境変数・置き場ほか)

- **A. 共通の置き場**: `src/paths.py` を新しく作り、次の 3 つを置く。
  - `AGJ_EXTERNAL`(既定 ROOT/data/external)
  - `AGJ_SYSTEM_DISCLOSURE`(既定 $AGJ_EXTERNAL/system_disclosure)
  - `rel_external(p)`: 出所や帳簿の file 欄を、置き場によらず `data/external/...` に揃える
- **B. `fetch_capacity_tables.py`**: L44-46 を A に、L174 の `relative_to(ROOT)` を `rel_external` に。sha が同じなら書かない。`--changed-file` を足す。失敗したら 0 以外を返す。
- **C. 東京の保存先**: `fetch_system_disclosure.py` L106 を `k.get("dest_kind", kind)` にし、台帳 L114 の `yosochoryu_csv` に `dest_kind: capacity` を付ける。
- **D. `fetch_system_disclosure.py`**: 失敗または未発見があれば exit 2。リクエスト間に 1 秒待つ。必要なら ETag / If-Modified-Since も。
- **E. `fetch_transformer_lists.py`**:
  - L106: `AGJ_TRANSFORMER_LISTS` で置き場を変えられるように
  - L808: 置き場の側のリポジトリで check-ignore する
  - L283: 一時ディレクトリに取ってから差し替える
  - MANIFEST の sha を前回と比べて `--changed-file` を出す
- **F. `parse_impedance.py`**: L33-34 を A に。L224 の固定を外す。(社, 系統区分)ごとに最新の年月だけ読む。行数が前回の 8 割未満なら書かない。
- **G/H. 地点需要**:
  - `parse_point_demand.py` L25-27 を A にして `--out` を足す。最新年だけ読む。
  - `src/powerflow/point_demand.py` L21 を `AGJ_POINT_DEMAND` で差し替えられるようにする(staging での A/B 用)。年度をまたいだ合算をやめる。
- **I. `apply_circuit_sources.py`**: L60-61 を A に、L231 の `relpath(path, ROOT)` を `rel_external` に。
- **J. `calibrate_line_capacity.py`**: L50-52 を A に。`--out-dir` と `--config-out` を足す(今は docs/reports と config へ固定で書く)。最新版だけ読む。
- **K/L/M. 発電所系**:
  - `fetch_fit.py`: L30 を `AGJ_FIT_DIR` に、L71 を完全一致に、L79 を直す
  - `build_generator_master.py`: L31-33 を A に、L115 を「県ごとに最新の 1 本」に
  - `fetch_hks.py`・`geocode_generators.py`(CACHE も本体へ)・`build_g_table.py`・`build_*_geojson.py`: A に
- **N. `fetch_rei_gridmap.py`**: L25 を A に。`--refresh-if-edited` を足す(層の editingInfo.dataLastEditDate を manifest と比べ、変わった層だけ一時ファイルに取ってから置き換える)。
- **O. keitouzu の 5 本**: `fetch_keitouzu.py` に `--commit` と `--record-only`(sha は照合でなく記録)を足し、DEST を A に。突合などの 4 本は A と `--out-dir` に。
- **P. `convert_chubu_flow.py`**: A にして、`rule_NN` を標準の名前に対応づける。

### 4. `realtime_cycle.sh` に足す段

`bash scripts/realtime_publish.sh` の直後、同じ `{ }` の中に貼ります。NOW 断面を先に公開するための位置です。`/bin/bash` 3.2 で構文を確かめました(`bash -n` は通り、shellcheck は info が 2 件だけ)。新しく作るスクリプトは `scripts/stage_derive.sh`・`scripts/promote_external.sh`・`scripts/external_diff_report.py` の 3 本です(§5)。

```bash
  # ===== 外部の公表データの定期取り込み =====
  # NOW を公開した後に回す。launchd は同じジョブを重ねて起動しないので、長い回は次が遅れるだけ。
  # & で裏に回さない(ジョブが終わると launchd が同じプロセスグループを止める)。
  # 観測だけ → 本番へ自動。モデルの入力 → staging で作り直して差分を報告し保留(手で promote_external.sh)。
  # staging は data/external/_staging(git 外)。data/realtime は LaboData へ同期されるので置かない。
  MONTH=$(date +%Y%m)
  EXT="$STORE/external"
  STAGE="$EXT/_staging"
  RT=data/realtime
  export AGJ_EXTERNAL="$EXT"
  export AGJ_SYSTEM_DISCLOSURE="$EXT/system_disclosure"
  export AGJ_SD_PROVENANCE="$STORE/realtime/system_disclosure_provenance.jsonl"
  mkdir -p "$STAGE"

  stage_ext() {   # $1=段 $2..=写すフォルダ。APFS の複製(cp -c。1.1GB で 0.14 秒を実測)
    local name="$1"; shift
    local d="$STAGE/$name" x
    rm -rf "$d"; mkdir -p "$d/external"
    for x in "$@"; do cp -c -R "$EXT/$x" "$d/external/$x"; done
    (cd "$EXT" && find "$@" -type f ! -path '*/_superseded/*' -print0 | xargs -0 shasum -a 256) > "$d/live_manifest.txt"
    echo "$d"
  }
  give_up() {     # 失敗は次の回に取り直す。同じ印で 3 回まで
    local t="$RT/.try_$1"
    echo x >> "$t"
    if [ "$(wc -l < "$t")" -ge 3 ]; then touch "$RT/.$1"; echo "  $1: 3 回失敗 → この期間は見送る"; fi
    return 0
  }
  stage_finish() { # staging で後段を作り直し差分を報告。モデルの入力が変わらなければ取り込む
    local name="$1" so="$2"
    if bash scripts/stage_derive.sh "$name" "$so" > "$so/derive.log" 2>&1; then
      echo "  $name: $(sed -n 's/^要約: //p' "$so/REPORT.md" | head -1)  → $so/REPORT.md"
      if grep -q '"status": *"no_model_change"' "$so/REPORT.json" 2>/dev/null; then
        if bash scripts/promote_external.sh "$name" --yes --no-pr >> "$so/derive.log" 2>&1; then
          echo "  $name: モデルの入力は変わらない → 取り込んだ"
        else
          echo "  $name: 自動の取り込みに失敗 $so/derive.log"
        fi
      else
        echo "  $name: モデルの入力が変わる → 保留。見てから scripts/promote_external.sh $name"
      fi
    else
      echo "  $name: staging の作り直しに失敗 $so/derive.log"
    fi
  }

  find "$EXT" -maxdepth 1 -name .refresh.lock -mmin +360 -exec rmdir {} \; 2>/dev/null || true
  if mkdir "$EXT/.refresh.lock" 2>/dev/null; then
    trap 'rmdir "$EXT/.refresh.lock" 2>/dev/null || true' EXIT

    # ── 日: 一覧だけ読む(約 20 GET)。新しい名前が出たら週・月の印を消して前倒し ──
    if [ ! -f "$RT/.probe_$TODAY" ]; then
      for k in impedance capacity; do
        if python3 -m scripts.fetch_system_disclosure --kind "$k" --dry-run 2>/dev/null \
             | sed -n 's/^ *\[dry-run\] \([^ ]*\) .*/\1/p' | sort > "$RT/probe_$k.new" && [ -s "$RT/probe_$k.new" ]; then
          if [ -f "$RT/probe_$k.txt" ] && ! cmp -s "$RT/probe_$k.new" "$RT/probe_$k.txt"; then
            echo "一覧に新しい名前($k): $(comm -13 "$RT/probe_$k.txt" "$RT/probe_$k.new" | head -3 | tr '\n' ' ')"
            if [ "$k" = impedance ]; then rm -f "$RT/.impedance_$MONTH"; else rm -f "$RT/.capacity_$WEEK"; fi
          fi
          mv "$RT/probe_$k.new" "$RT/probe_$k.txt"
        fi
      done
      touch "$RT/.probe_$TODAY"
    fi

    # ── 週: 空容量一覧 → staging(#44・#45・台帳経由で #49/#50) ──
    if [ ! -f "$RT/.capacity_$WEEK" ]; then
      if SO="$(stage_ext capacity system_disclosure keitouzu)"; then
        SD="$SO/external/system_disclosure"; CH="$SO/changed.txt"; : > "$CH"; ok=1
        # 北海道の capacity は fetch_capacity_tables に任せる(置き方の違う 2 本が同じフォルダに書くため)
        for uk in kansai:capacity kansai:capacity_less shikoku:capacity tokyo:yosochoryu_csv; do
          if AGJ_SYSTEM_DISCLOSURE="$SD" AGJ_SD_PROVENANCE="$SO/provenance.jsonl" \
               python3 -m scripts.fetch_system_disclosure --utility "${uk%%:*}" --kind "${uk##*:}" \
               --changed-file "$SO/ch.tmp" >> "$SO/fetch.log" 2>&1; then
            cat "$SO/ch.tmp" >> "$CH"
          else ok=0; fi
        done
        if AGJ_SYSTEM_DISCLOSURE="$SD" AGJ_SD_PROVENANCE="$SO/provenance.jsonl" \
             PYTHONPATH=. python3 scripts/fetch_capacity_tables.py --changed-file "$SO/ch.tmp" >> "$SO/fetch.log" 2>&1; then
          cat "$SO/ch.tmp" >> "$CH"
        else ok=0; fi
        if [ "$ok" = 0 ]; then
          echo "空容量: 取得に失敗した社あり $SO/fetch.log"; give_up "capacity_$WEEK"
        elif [ ! -s "$CH" ]; then
          echo "空容量: 新しい公表なし"; rm -rf "$SO"; touch "$RT/.capacity_$WEEK"
        else
          echo "空容量: 新しい公表 $(wc -l < "$CH" | tr -d ' ') ファイル → staging で作り直す"
          TRU=$(awk -F/ '{print $4}' "$CH" | sort -u | tr '\n' ' ')   # 変わった社だけ台帳を取り直す
          AGJ_TRANSFORMER_LISTS="$SD/transformer_lists" python3 -I scripts/fetch_transformer_lists.py --utilities $TRU \
            > "$SO/transformer_lists.log" 2>&1 || echo "  変圧器の台帳の取り直しに失敗 $SO/transformer_lists.log"
          stage_finish capacity "$SO"
          touch "$RT/.capacity_$WEEK"
        fi
      fi
    fi

    # ── 週: 地点需要(#30)。潮流実績の変圧器が新しくなった週だけ。本番は毎時読まれるので触らない ──
    if [ -f "$RT/.flow_actual_$WEEK" ] && [ ! -f "$RT/.point_demand_$WEEK" ]; then
      if grep -qE '/flow_actual/.*(_tr_|tyoryu)' "$RT/.flow_actual_changed" 2>/dev/null; then
        SO="$STAGE/point_demand"; rm -rf "$SO"; mkdir -p "$SO"
        if python3 scripts/parse_point_demand.py --out "$SO/point_demand.csv" > "$SO/parse.log" 2>&1; then
          stage_finish point_demand "$SO"
        else
          echo "地点需要: 作り直しに失敗 $SO/parse.log"
        fi
      fi
      touch "$RT/.point_demand_$WEEK"
    fi

    # ── 月: インピーダンス → staging(#44 S5・観測の表) ──
    if [ ! -f "$RT/.impedance_$MONTH" ]; then
      if SO="$(stage_ext impedance system_disclosure keitouzu)"; then
        SD="$SO/external/system_disclosure"
        if AGJ_SYSTEM_DISCLOSURE="$SD" AGJ_SD_PROVENANCE="$SO/provenance.jsonl" \
             python3 -m scripts.fetch_system_disclosure --kind impedance --changed-file "$SO/changed.txt" > "$SO/fetch.log" 2>&1; then
          if [ -s "$SO/changed.txt" ]; then
            echo "インピーダンス: 新しい公表 $(wc -l < "$SO/changed.txt" | tr -d ' ') ファイル → staging"
            stage_finish impedance "$SO"
          else
            echo "インピーダンス: 新しい公表なし"; rm -rf "$SO"
          fi
          touch "$RT/.impedance_$MONTH"
        else
          echo "インピーダンス: 取得に失敗 $SO/fetch.log"; give_up "impedance_$MONTH"
        fi
      fi
    fi

    # ── 月: open-keitouzu。上流の先端だけ見て、ピンから進んでいたら staging(#44 S4) ──
    if [ ! -f "$RT/.keitouzu_$MONTH" ]; then
      PIN=$(sed -n 's/^PINNED_COMMIT = "\([0-9a-f]\{40\}\)".*/\1/p' scripts/keitouzu/fetch_keitouzu.py)
      UP=$(git ls-remote https://github.com/ibarapascal/open-keitouzu refs/heads/main 2>/dev/null | cut -f1)
      if [ -z "$UP" ]; then
        echo "open-keitouzu: 上流を確かめられない"; give_up "keitouzu_$MONTH"
      elif [ "$UP" = "$PIN" ]; then
        echo "open-keitouzu: ピンのまま(${PIN:0:7})"; touch "$RT/.keitouzu_$MONTH"
      elif SO="$(stage_ext keitouzu system_disclosure keitouzu)"; then
        echo "open-keitouzu: 上流が進んだ ${PIN:0:7} → ${UP:0:7}"
        if AGJ_EXTERNAL="$SO/external" python3 scripts/keitouzu/fetch_keitouzu.py --commit "$UP" --record-only \
             > "$SO/fetch.log" 2>&1; then
          stage_finish keitouzu "$SO"
        else
          echo "  取得に失敗 $SO/fetch.log"
        fi
        touch "$RT/.keitouzu_$MONTH"
      fi
    fi

    # ── 月: REI(観測だけ)。変わった層だけ取り直す ──
    if [ ! -f "$RT/.rei_$MONTH" ]; then
      if python3 scripts/fetch_rei_gridmap.py --refresh-if-edited > "$RT/rei_fetch.log" 2>&1; then
        echo "REI: $(tail -1 "$RT/rei_fetch.log")"; touch "$RT/.rei_$MONTH"
      else
        echo "REI: 確認に失敗 $RT/rei_fetch.log"; give_up "rei_$MONTH"
      fi
    fi

    # ── 月(15 日以降): 発電所マスタ(FIT・HKS。観測・表示だけ)。本番へ自動で ──
    if [ ! -f "$RT/.generators_$MONTH" ] && [ "$(date +%d)" -ge 15 ]; then
      NEW=0
      FIN="$EXT/fit/_incoming/$MONTH"; rm -rf "$FIN"; mkdir -p "$FIN"
      AGJ_FIT_DIR="$FIN" python3 scripts/fetch_fit.py > "$RT/fit_fetch.log" 2>&1 || true
      NFIT=$(ls "$FIN"/*.xlsx 2>/dev/null | wc -l | tr -d ' ')
      if [ "$NFIT" -lt 47 ]; then
        echo "FIT: $NFIT/47 県しか取れない → 入れ替えない $RT/fit_fetch.log"
      elif [ -z "$(cd "$FIN" && for f in *.xlsx; do cmp -s "$f" "$EXT/fit/$f" || echo "$f"; done)" ]; then
        echo "FIT: 新しい版なし"
      else
        mkdir -p "$EXT/fit/_superseded/$MONTH"   # 前の版は消さずに退避(上の段に 2 か月分あるとマスタが二重に読む)
        for f in "$EXT/fit/"*.xlsx; do if [ -e "$f" ]; then mv "$f" "$EXT/fit/_superseded/$MONTH/"; fi; done
        for f in "$FIN/"*.xlsx; do mv "$f" "$EXT/fit/"; done
        if [ -f "$FIN/provenance.jsonl" ]; then cat "$FIN/provenance.jsonl" >> "$EXT/fit/provenance.jsonl"; fi
        echo "FIT: 47 都道府県を入れ替えた"; NEW=1
      fi
      rm -rf "$FIN"
      H0=$(date -v-1m +%Y/%m/01); H1=$(date -v-1m +%Y/%m/07)   # HKS は先月の第 1 週だけ(顔ぶれの更新が目的)
      if [ ! -f "$EXT/occto/hks/hks_${H0//\//}_${H1//\//}.csv" ]; then
        if python3 scripts/fetch_hks.py "$H0" "$H1" >> "$RT/hks_fetch.log" 2>&1; then NEW=1; else echo "HKS: 取得に失敗"; fi
      fi
      if [ "$NEW" = 1 ]; then
        if { python3 scripts/build_generator_master.py && python3 scripts/build_g_table.py \
             && python3 scripts/geocode_generators.py --min-mw 1 && python3 scripts/build_fit_geojson.py \
             && PYTHONPATH=. python3 scripts/build_generator_geojson.py \
             && PYTHONPATH=. python3 scripts/build_generation_geojson.py; } > "$RT/generators_build.log" 2>&1; then
          echo "発電所マスタ: 作り直した"
        else
          echo "発電所マスタ: 作り直しに失敗 $RT/generators_build.log"
        fi
      fi
      touch "$RT/.generators_$MONTH"
    fi

    rmdir "$EXT/.refresh.lock" 2>/dev/null || true
    trap - EXIT
  else
    echo "外部データ: 取り込みの作業中(ロックあり)→ この回は飛ばす"
  fi
```

### 5. 「差分を見てから反映」の仕組み

**staging の置き場**: `<本体>/data/external/_staging/<段>/` に置きます。
- 中身: `external/`(本体の複製の上に新しい取得物を重ねたもの)、`live_manifest.txt`、`changed.txt`、`provenance.jsonl`、`out/`、`REPORT.md`、`REPORT.json`、`PR_BODY.md`
- 毎回、本体から作り直します。取り込むまでは、毎回同じ保留が報告され続けます。

**`scripts/stage_derive.sh <段> <staging>`(新規)**: `AGJ_EXTERNAL` と `AGJ_SYSTEM_DISCLOSURE` を staging に向け、本番と追跡ファイルには触りません。
- 共通: `cp -c docs/data/built/all.json $OUT/all.json` で正典を写し、#44 をドライランする。
  `apply_circuit_sources.py --built $OUT/all.json --ledger $OUT/circuit_counts.jsonl --out-dir $OUT`
- **capacity**:
  1. `build_line_observations`
  2. #44 のドライラン
  3. `score_transformer_topology.py --registry $SD/transformer_lists/transformer_registry.csv --out $OUT/... --detail $OUT/... --export $OUT/published_transformer_pairs.json --export-capacity $OUT/transformer_capacity_by_pair.json --export-levels $OUT/published_missing_levels.json`
  4. `calibrate_line_capacity --out-dir $OUT --config-out $OUT/...`
- **impedance**: `parse_impedance --outdir $SD/normalized` → `match_impedance_to_model` → `compare_observed_derived_impedance` → `build_line_observations` → #44 のドライラン
- **keitouzu**: `adjudicate_xwalk` → `crosscheck_keitouzu`(どちらも `--out-dir $OUT`)→ #44 のドライラン
- 最後に `external_diff_report.py` を呼ぶ。

**`scripts/external_diff_report.py <段>`(新規)**: 本番と staging、追跡ファイルと staging を比べます。
- `status` は `no_change` / `no_model_change` / `model_change` / `error` のどれか。
- 比べるもの:
  - 取得物: 版の年月の新旧と、置き換わる旧版
  - `impedance_lines`: (社, 系統区分, 名前, from, to)ごとの増減と R/X/B の変化
  - #44 の帳簿: (地域, 線, kV, from, to)ごとの回線数と、par が増える枝の数。date・quote・retrieved・source_file は無視する(quote に公表の更新日が入るので、毎月全行が変わって見えるため)
  - #49: 組の増減。#50: 組ごとの中央値の変化率
  - #30: 地域別の合計 MW と変電所の増減
  - keitouzu: 整合率と食い違いの数
  - #45: 比
- 守ること: 行数が前回の 8 割未満なら `error` にする。`REPORT.md` は git の外の詳しい版、`PR_BODY.md` は件数と比だけの版にする。

**`scripts/promote_external.sh <段> [--yes] [--no-pr]` と `--rollback <段>-<時刻>`(新規)**: 手で使い、取り込みを行います。
1. ロックを取る。staging を作った後で本番が変わっていたら中止する(`live_manifest.txt` と比べる)。
2. 本番の該当フォルダを `_snapshots/<段>-<時刻>/` へ `cp -c` で写す。
3. 取り込む:
   - `changed.txt` のファイルだけ本番へ置き換える。年月だけ違う旧版は `<社>/<種類>/_superseded/<時刻>/` へ移す(消さない)。上の段だけを読む glob から外れる。
   - 変圧器の台帳はフォルダごと入れ替える。
   - 出所の行を `AGJ_SD_PROVENANCE` へ追記する。
4. normalized は段ごとに決めたファイルだけ写す。
   - impedance: `impedance_lines.csv`・`impedance_transformers.csv`・`summary.json`・`crosswalk_impedance_to_model.csv`・比較の CSV
   - point_demand: `point_demand.csv`(一時ファイルから mv で置き換える)
   - `line_observations` は本番で作り直す。続けて `export_obs_compare` と `export_obs_local` を流し、次の公開で Pages へ出す。
5. 追跡ファイルを変える段は、別の worktree で PR にします。worktree は `git worktree add -b data/refresh-<段>-<日付> ~/dev/github/project_Hayashi/AGJ-refresh origin/main` で作ります。runner と本体のチェックアウトは使いません。マージは人が行います。
   - #49/#50: `--export` 3 つ → `tests/test_station_layers.py` → PR
   - keitouzu: `PINNED_COMMIT` と sha を上げ、突合・`export_divergent`・裁定キューを流して PR
   - #44: 追跡ファイルは regen が書くので、PR は作らない。代わりに「次の regen で回線数が N 本変わる」を記録する。
   - #45: 既定 OFF なので、`--write-config` はオーナー判断。
6. staging を `_staging/_promoted/` へ移して残す。追跡ファイルを戻すときは git revert。

**提案**: regen が #44 と #30 で読む外部ファイルの sha を、`docs/data/MODEL_VERSION.json` に記録する。正典がどの外部データから作られたか分かり、上の 8 の穴も見えるようになります。

### 6. 危ない所

- **ライセンス**
  - 東京電力PG と関西電力送配電は All-Rights-Reserved で、他社も転載を前提にしていません。生の容量・インピーダンス・地点別の値は git、Pages、PR 本文に入れません。#50 は追跡ファイルに集計しか入れないことをテストが保証しています。
  - staging と snapshot は `data/external`(gitignore)に置きます。`data/realtime` は `sync_realtime_to_nas.sh` が LaboData(共有 NAS)へ送るので置きません。
  - FIT の原本には事業者の氏名・住所が入っています。マスタで落とし、報告は県・燃料ごとの件数だけにします。
  - REI の属性の原典は各社のデータなので、同じ扱いにします。open-keitouzu は CC BY 4.0 なので表示を残します。HKS は出典と、加工した旨を書きます。
- **重さ**
  - 実測: 週の潮流実績は約 12 分かかります(10-24 15:13 の回。120 ファイルを毎回全部落として sha で比べている)。台帳は 55MB(54MB が東京の PDF)、空容量は 2MB/203 ファイル、インピーダンスは 0.8MB です。
  - 見込み: FIT は playwright で 82MB、REI は 65MB。
  - 月初の週は 30〜40 分に延びうるので、発電所は 15 日以降に回します。条件付き GET(ETag)を入れると軽くなります。
- **公表元の形式の変化**
  - ファイル名の年月の変化(上の 2 の 4 で手当て)。中部の rule 番号は年度ごとに増えます。FIT は Salesforce の画面です。HKS は画面の入力欄を探して操作しています。REI のサービス名の増減。九州の送電線は手で取った PDF です。
  - staging でパースした結果が空や急減になった場合は、`error` にして止めます。

### 推測・未確認
- FIT で北海道が取れない原因(セレクタ)、FIT の公表時期(約 1.5 か月遅れ)、HKS の公開の頻度。
- 東京の `impedance.pdf?251028` は改訂日の印かもしれません。中身は比べていません。
- launchd の挙動(重ねて起動しない・ジョブが終わるとプロセスグループを止める)は仕様からの判断で、ここでは試していません。
- 「解析結果が同じなら自動で取り込む」は提案で、採るかどうかはオーナーが判断することです。

構文を確かめた bash の原本: `docs/reports/external_refresh_survey_2026-10-24/cycle_addition.sh`(上の版は、FIT の旧版を移すループを if に直してあります)
