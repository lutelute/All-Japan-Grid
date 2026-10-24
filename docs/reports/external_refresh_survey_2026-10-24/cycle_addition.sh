#!/bin/bash
set -e
{
  STORE=/tmp/x; TODAY=$(date +%Y%m%d); WEEK=$(date +%G%V)
  # ===== ここから貼る(bash scripts/realtime_publish.sh の後・同じ { } の中) =====
  # 外部の公表データの定期取り込み(発電所・FIT・REI・系統図・空容量・インピーダンス・変圧器の台帳・地点需要)
  #  - NOW 断面を公開した後に回す。launchd は同じジョブを重ねて起動しないので、長い回は次の回が遅れるだけ。
  #    & で裏に回さない(ジョブが終わると launchd が同じプロセスグループを止める)
  #  - 観測・表示だけのもの → 本番の置き場へ自動で入れて作り直す
  #  - モデルの入力 → staging に取って作り直し、差分を報告して止める。取り込みは手で
  #    scripts/promote_external.sh <段>。解析結果が同じ(更新日だけ変わった等)の回だけ自動で取り込む
  #  - staging は data/external/_staging(git の外)。data/realtime は LaboData へ同期されるので置かない
  #  前提: 環境変数・終了コード・最新版の選び方の改修(A〜P)が入っていること
  MONTH=$(date +%Y%m)
  EXT="$STORE/external"
  STAGE="$EXT/_staging"
  RT=data/realtime
  export AGJ_EXTERNAL="$EXT"
  export AGJ_SYSTEM_DISCLOSURE="$EXT/system_disclosure"
  export AGJ_SD_PROVENANCE="$STORE/realtime/system_disclosure_provenance.jsonl"
  mkdir -p "$STAGE"

  # staging を作る。$1=段 $2..=写すフォルダ(data/external の下)。APFS の複製(cp -c)なので一瞬で容量も食わない
  stage_ext() {
    local name="$1"; shift
    local d="$STAGE/$name" x
    rm -rf "$d"; mkdir -p "$d/external"
    for x in "$@"; do cp -c -R "$EXT/$x" "$d/external/$x"; done
    # 取り込むとき「staging を作った後で本番が変わっていないか」を確かめる目録
    (cd "$EXT" && find "$@" -type f ! -path '*/_superseded/*' -print0 | xargs -0 shasum -a 256) > "$d/live_manifest.txt"
    echo "$d"
  }
  # 失敗した回は印を付けず次の回に取り直す。ただし同じ印で 3 回まで(公表元が落ちているとき毎時たたかない)
  give_up() {
    local t="$RT/.try_$1"
    echo x >> "$t"
    if [ "$(wc -l < "$t")" -ge 3 ]; then touch "$RT/.$1"; echo "  $1: 3 回失敗 → この期間は見送る"; fi
    return 0
  }
  # staging の中で後段を作り直して差分を報告する。解析結果が同じなら取り込む。$1=段 $2=staging
  stage_finish() {
    local name="$1" so="$2"
    if bash scripts/stage_derive.sh "$name" "$so" > "$so/derive.log" 2>&1; then
      echo "  $name: $(sed -n 's/^要約: //p' "$so/REPORT.md" | head -1)  → $so/REPORT.md"
      if grep -q '"status": *"no_model_change"' "$so/REPORT.json" 2>/dev/null; then
        if bash scripts/promote_external.sh "$name" --yes --no-pr >> "$so/derive.log" 2>&1; then
          echo "  $name: モデルの入力は変わらない(更新日などだけ)→ 取り込んだ"
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

    # ── 日: 一覧ページだけ読む(約 20 回の GET)。新しいファイル名が出ていたら週・月の印を消して前倒し ──
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

    # ── 週: 各社の空容量一覧 → staging(モデルの入力: #44 回線数・#45 較正・変圧器の台帳 → #49/#50) ──
    if [ ! -f "$RT/.capacity_$WEEK" ]; then
      if SO="$(stage_ext capacity system_disclosure keitouzu)"; then
        SD="$SO/external/system_disclosure"; CH="$SO/changed.txt"; : > "$CH"; ok=1
        # 台帳(config/system_disclosure.yaml)で取る社・種類。北海道の capacity は fetch_capacity_tables に任せる
        # (置き方の違う 2 本が同じフォルダに書くため)
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
          # 変圧器の台帳は同じ一覧の変圧器の行。変わった社だけ staging で取り直す(東京の PDF 54MB が重い)
          TRU=$(awk -F/ '{print $4}' "$CH" | sort -u | tr '\n' ' ')
          AGJ_TRANSFORMER_LISTS="$SD/transformer_lists" python3 -I scripts/fetch_transformer_lists.py --utilities $TRU \
            > "$SO/transformer_lists.log" 2>&1 || echo "  変圧器の台帳の取り直しに失敗 $SO/transformer_lists.log"
          stage_finish capacity "$SO"
          touch "$RT/.capacity_$WEEK"
        fi
      fi
    fi

    # ── 週: 地点需要(#30)。潮流実績の変圧器のファイルが新しくなった週だけ staging で作り直す ──
    # point_demand.csv は毎時の NOW 断面・日別断面が実行時に読むので、本番は差分を見るまで触らない
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

    # ── 月: インピーダンス(様式5) → staging(モデルの入力: #44 の S5・観測の表) ──
    if [ ! -f "$RT/.impedance_$MONTH" ]; then
      if SO="$(stage_ext impedance system_disclosure keitouzu)"; then
        SD="$SO/external/system_disclosure"
        if AGJ_SYSTEM_DISCLOSURE="$SD" AGJ_SD_PROVENANCE="$SO/provenance.jsonl" \
             python3 -m scripts.fetch_system_disclosure --kind impedance --changed-file "$SO/changed.txt" > "$SO/fetch.log" 2>&1; then
          if [ -s "$SO/changed.txt" ]; then
            echo "インピーダンス: 新しい公表 $(wc -l < "$SO/changed.txt" | tr -d ' ') ファイル → staging で作り直す"
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

    # ── 月: open-keitouzu(CC BY 4.0)。上流の先端だけ見て、ピンから進んでいたら staging で取得・突合(#44 の S4) ──
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

    # ── 月: REI 送電線マップ(観測だけ・使う側はまだ無い)。層の最終編集日だけ見て、変わった層だけ取り直す ──
    if [ ! -f "$RT/.rei_$MONTH" ]; then
      if python3 scripts/fetch_rei_gridmap.py --refresh-if-edited > "$RT/rei_fetch.log" 2>&1; then
        echo "REI: $(tail -1 "$RT/rei_fetch.log")"; touch "$RT/.rei_$MONTH"
      else
        echo "REI: 確認に失敗 $RT/rei_fetch.log"; give_up "rei_$MONTH"
      fi
    fi

    # ── 月(15 日以降): 発電所マスタ(FIT・OCCTO HKS。観測・表示だけ)。本番の置き場へ自動で入れて作り直す ──
    if [ ! -f "$RT/.generators_$MONTH" ] && [ "$(date +%d)" -ge 15 ]; then
      NEW=0
      FIN="$EXT/fit/_incoming/$MONTH"; rm -rf "$FIN"; mkdir -p "$FIN"
      AGJ_FIT_DIR="$FIN" python3 scripts/fetch_fit.py > "$RT/fit_fetch.log" 2>&1 || true
      NFIT=$(ls "$FIN"/*.xlsx 2>/dev/null | wc -l | tr -d ' ')
      if [ "$NFIT" -lt 47 ]; then
        echo "FIT: $NFIT/47 県しか取れない → 入れ替えない(本番は前の版のまま) $RT/fit_fetch.log"
      elif [ -z "$(cd "$FIN" && for f in *.xlsx; do cmp -s "$f" "$EXT/fit/$f" || echo "$f"; done)" ]; then
        echo "FIT: 新しい版なし"
      else
        # 前の版は消さずに _superseded へ(上の段に 2 か月分が並ぶとマスタが二重に読む)
        mkdir -p "$EXT/fit/_superseded/$MONTH"
        for f in "$EXT/fit/"*.xlsx; do [ -e "$f" ] && mv "$f" "$EXT/fit/_superseded/$MONTH/"; done
        for f in "$FIN/"*.xlsx; do mv "$f" "$EXT/fit/"; done
        if [ -f "$FIN/provenance.jsonl" ]; then cat "$FIN/provenance.jsonl" >> "$EXT/fit/provenance.jsonl"; fi
        echo "FIT: 47 都道府県を入れ替えた"; NEW=1
      fi
      rm -rf "$FIN"
      # HKS: 先月の第 1 週だけ(マスタの目的は発電所の顔ぶれ。30 分値は貯めない)
      H0=$(date -v-1m +%Y/%m/01); H1=$(date -v-1m +%Y/%m/07)
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
  # ===== ここまで =====
} >> /dev/null 2>&1
