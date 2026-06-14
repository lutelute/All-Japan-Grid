# 系統DB全面改修 実装計画 — OSM正・ボトムアップ・GridMend

対象: `All-Japan-Grid`。方針: **真は物理接続(OSM幾何)・潮流/連結性は検証器・committedスコアカードは不可触(A/Bは新日付JSONのみ追加)・捏造禁止**。

> 由来: 2026-06-14 オーナー全面改修指示 + 計画ワークフロー(8エージェント並列・理解→設計→統合)。
> 本書は提示用の計画であり、実装は **計画提示→承認→フェーズ実行** の順で進める。

---

## (1) アーキテクチャ全体像

```
OSM(真) ─┐
         │  power=substation ポリゴン + line(本線/busbar/bay/cable)
         ▼
[正規化] 座標5桁丸め・電圧 a;b 分解・周波数/DC除外
         ▼
[ボトムアップ構築]  低圧端シード → 同電圧成長(union-find) → 終端なし線を母線へ束縛 → 階級境界を変圧器で上位集約
         ▼
┌─────────────────────────────────────────────┐
│ node-breaker(忠実層) VoltageLevel/Busbar/Bay/Terminal/CN │ ← 監査・OSM還元・編集UI・CIM emit
│        │ topology processing(同VL内をCN集約で1busに潰す)    │
│        ▼                                                    │
│ bus-branch(計算層) = 現 {sid}@{c} + 変圧器ラダーと同型      │ ← pandapower/潮流(ρ)/AC
└─────────────────────────────────────────────┘
         ▼
[GridMend] 編集→append専用ログ→機械適用→A/B検証→GitHub issue→採用→supplement統合→OSM ODbL還元
```

3本柱:
- **OSM正**: 接続の一次根拠はOSM幾何。計算結果は検証器であって真理判定者ではない。
- **ボトムアップ**: 低圧(66kV)→高圧(500kV)の階級昇順で決定的に成長させ、変圧器を唯一のクロス階級ジョイントにする。後の全国集約が容易になる。
- **bus/bay/busbar一級市民化**: 現状「捨てる」busbar/bay(`drop_busbar_bay`)を「母線ノードへ畳み込む」へ反転。毛玉(嶺南で内部線154本)が母線1ノードへ吸収される。

### 重要な技術前提: GeoJSONはOSMのノード参照トポロジを持たない
実測: `data/tokyo_lines.geojson` 8295本のうち **`@id`/`nodes`(OSMノード参照)を持つ線は 0本**。
→ OSMの真の「どのwayがどのノードで繋がるか」は抽出時に失われ、**座標一致(スナップ)が接続を再推論する唯一の手段**。
ボトムアップ構築はこの座標スナップ(5桁丸め=約1m)に立脚する。**将来**: 生OSM(.pbf/ノード参照付き)から再抽出すれば真トポロジを直接得られ、スナップ推論の誤り(取りこぼし/誤融合)を排除できる(別途検討)。

---

## (2) データモデル(CIM整合・永続化)

現行 `Substation`=1バスを廃し、4階層に分解。`src/model/` にデータクラス追加、`src/db/schema.py` にテーブル追加。`src/cim/level2.py` の emit はこれを**読む**(再生成しない)。

| 新モデル(`src/model/`) | CIMクラス | 役割 | OSM源泉 | 実証(嶺南) |
|---|---|---|---|---|
| `Substation`(既存) | `cim:Substation` | 敷地ポリゴン=容器 | `power=substation` | MultiPolygon可 |
| `VoltageLevel` | `cim:VoltageLevel`+`BaseVoltage` | 変電所内1電圧階級 `sid@kv` | ポリゴン `voltage="a;b"` 分解 | 500000;275000 |
| `BusbarSection` | `cim:BusbarSection`+`ConnectivityNode` | 各VLの集電母線=**終端なし線の接続先** | `line=busbar` | 500kV×48本 |
| `Bay` | `cim:Bay` | 母線↔本線/機器の引込区画 | `line=bay` | 500/275/77kV |
| `Terminal` | `cim:Terminal`(`sequenceNumber`,`connected`) | 線端点。CNへ束縛 | 本線端点 | bay/busbarと座標一致 snap≈0.1m |

**1次/2次側**: `PowerTransformerEnd.endNumber`(1=HV/2=LV)で表現。現 `xfmr_stubs`(snapped_topology.py L1207-1210)と `insert_transformers` のHV/LV判定(transforms.py)を**そのままオブジェクト化**。OSMに明示タグが無いため**電圧階級の大小から決定的に導出**。`@u`(無印母線)は最高位VLにぶら下げる既存規則(L1197-1207)を `BusbarSection.inferred_kv` として保持し、隣接Bay電圧から継承補完(嶺南34本)。

**二層は同一オブジェクトの2ビュー**: node-breaker(全保持)を topology processing で同VL内CN集約 → bus-branch(計算用)。後者は現ビルダ出力と同型なので既存の潮流経路をそのまま使える。

---

## (3) ボトムアップ接続アルゴリズム(機械的・再現可能・決定的)

決定性の担保: 座標は5桁丸めで正規化、巡回はソート済みキー順、union-find のマージ順序非依存。`build_network_snapped` の置換ではなく **`--bottom-up` フラグの追加経路**として実装し後方互換を保つ。

```
STEP 0  正規化  : 線・ポリゴン読込、座標5桁丸め。busbar/bay線は「内部結線エビデンス」として保持(捨てない)。ポリゴンの a;b → class_set(sid)。
STEP 1  母線階級確定 : classes = parse_multi_voltage(sid) ∪ 引込線電圧。voltage無印母線は隣接bay電圧を継承。各 c に Busbar(sid,c) を生成。
STEP 2  低圧端シード : 全線端点のうち degree==1 かつ最低電圧の自由端を leaf に。key=(kv, coord) で決定的ソート。
STEP 3  同電圧成長 : 階級 c を昇順(66→77→…→500)に、c の線だけで union-find。busbar/bay内部線も同VLの Busbar(sid,c) へ union → 構内が1ノードへ畳まれる(毛玉解消)。
STEP 4  終端なし線束縛 : degree==1 の tip について、内包/lead-in band 内の sid を判定 → 同電圧 Busbar 優先(無ければ最近接)に bind。辺を捏造せず母線へ吸着。異電圧なら変圧器境界をマーク。
STEP 5  階級境界=変圧器で上位集約 : 各 sid で ladder=sorted(busbars,key=kv)。隣接対 (lo,hi) に insert_transformer(side1=hi/HV, side2=lo/LV)。低圧成分が母線→変圧器→上位母線→上位線と機械的に吸い上がる。
STEP 6  chain collapse/jct昇格 : 現行踏襲(degree≥3の実タップのみ合成バス化。母線内部はSTEP3で畳済)。
```

接続規則の実証根拠(U2): 嶺南で本線端点23本がbay/busbarノードと座標一致(snap≈0.1m)、degree-7ノードが「bay×6+本線×1」=同一母線区画への集約点。幾何上すでにボトムアップ結線が成立しており、アルゴリズムはそれを忠実に再構成する。

---

## (4) 現builderからの移行 & A/B・スコアカード検証戦略

**移行手順(ロジック流用・破棄なし)**:
1. `Busbar(sid,c)`/`VoltageLevel`/`Bay`/`Terminal` を `src/model/substation.py` に dataclass 追加し永続化(現状は build時に捨てる scaffolding)。
2. `drop_busbar_bay` の「除外」(L651)を STEP3「母線ノードへ collapse」に置換。opt-in は段階的に廃止。
3. `S|sid|cls` キーイング・`sub_resolved`・`xfmr_stubs` ラダー(L1153-1210)は STEP1/5 の土台として再利用。
4. 無向隣接+max-merge を「階級昇順の決定的成長(union-find)」に置換するが、**出力バス/辺集合は同型**に保つ。

**検証戦略(committed不可触)**:
- 現行(`--top-down` 既定)と `--bottom-up` を同一断面で build → `POST /api/verify/{region}` で島数 before/after・本系統サイズ・Δ を計測。
- ρ(13b比)・AC収束を **新日付JSON `data/db/ab_bottomup_YYYYMMDD.json` に追記のみ**。既存スコアカード(13b)・本番モデルは pending→adopted まで一切変えない。
- バス/辺集合をソート済みで diff。**受入条件: 毛玉解消(辺数減)かつ 島数非増加かつ ρ非悪化かつ 全地域AC維持**。
- GridMend の `replay` でログ→build→島数をCI再実行し回帰検出。

---

## (5) 「DB改善ツール」命名 & 段階リリース

**推奨名: GridMend(グリッドメンド)／和名「系統DB改善ツール」**。grid+mend(綻びを繕う)。OSM文化(mapping/mending)に親和し `ajgrid mend` として動詞的にCLIへ収まる。衝突なし。

候補(採否):
- **GridMend** ← 推奨(短い動詞・衝突なし・OSM文脈適合)
- GridStitch(縫合)— 次点
- OSM-GridFixer / 接続DB編集器 — "Fixer"が捏造連想で方針と不整合・冗長

**正体**: 新規ソフトではなく、完成済み編集ループ(E5–E13、台帳113–121)に**名前・CLI境界・再現コマンド・docを与えてリリース可能にする**。実体は `src/server/{app,edit_log,edit_apply,issue_submit,built_view}.py` + `templates/editor.html`。

**提供形態**:
- サーバ(主): `ajgrid mend serve --port 8080`(= uvicorn src.server.app:app)で `/editor` 配信。
- CLI(ヘッドレス): `ajgrid mend` 配下に `log`/`apply`/`verify`/`issue`/`replay`。`src/cli.py` の subparsers に1つ追加するのみ(新パッケージ不要)。
- doc: `docs/GRIDMEND.md`(`CONNECTION_EDITOR_DESIGN.md` を改名/参照)正本化、READMEに独立節。

**リリース単位**: GridMend v0.1(編集→ログ→検証→issue→採用) → v0.2(cut機構E8b・属性検証・ρ/AC連動・status自動判定) → v0.3(提示UI E11・認証/同時編集/OSM changeset自動化 E9)。

---

## (6) フェーズ分け(成果物・検証・pytest緑)

| Phase | 成果物 | 検証 | pytest緑の担保 |
|---|---|---|---|
| **P0 基盤(命名)** | GridMend命名・`ajgrid mend` サブコマンド・`docs/GRIDMEND.md`・README節。既存ループを束ねるのみ | 既存 `/api/verify` `/api/issue` `/api/built` の疎通。issue #28 再現 | 既存1103緑を不変で維持(機能追加のみ・モデル変更なし) |
| **P1 互換ビュー** | `drop_busbar_bay` skip廃止→busbar/bay を母線ノードへ畳み込み。現出力を「bus-branch ビュー」と定義 | A/B島数(`ab_bottomup_YYYYMMDD.json`)・辺数減(毛玉解消)・ρ非悪化・全地域AC維持 | 既存テスト緑維持 + 畳み込みの単体テスト追加(嶺南内部線→母線1ノード) |
| **P2 データモデル永続化** | `VoltageLevel`/`BusbarSection`/`Bay`/`Terminal` dataclass + DBテーブル。node-breaker層をDB化。bus-branch は集約で導出 | node-breaker↔bus-branch の連結性・潮流(ρ)・AC が両層一致。pin更新 | 新dataclass/schemaのCRUD・集約導出の単体テスト。回帰pin再生成。全緑 |
| **P3 ボトムアップ構築** | `--bottom-up` 経路(STEP0-6・union-find)。`Terminal` 束縛・変圧器1次/2次をモデルから駆動 | `--top-down` vs `--bottom-up` 同一断面 A/B。受入条件(島数非増・ρ非悪化・AC維持・辺数減)を新日付JSONで確認 | 決定性テスト(同入力→同バス/辺集合)。STEP単位テスト。全緑 |
| **P4 CIM/UI駆動** | `level2.py` emit を node-breaker オブジェクトから駆動。編集UIを node-breaker 表示に。GridMend v0.2(cut/属性検証) | CIM往復(emit→検証)・編集→A/B→issue→採用→supplement→(将来)OSM changeset | CIM emit のスナップショットテスト。E8b cut機構テスト。全緑 |

各フェーズ末で「ログ→build→島数」をCI再実行(replay)し回帰検出。committed スコアカードは全フェーズで不可触、A/Bは新日付JSON追記のみ。

---

## (7) リスクと未確定点(オーナー判断が要る箇所)

- **[判断要] busbar/bay の扱いを「捨てる」→「畳み込む」へ反転する既定変更**: P1で `drop_busbar_bay=False` 既定の挙動が変わる。現行top-down出力との後方互換をどこまで保証するか(完全同型を必須とするか、毛玉解消による辺数減は受容するか)。
- **[判断要] voltage無印母線の電圧継承ポリシー**: 嶺南34本など無印busbarを隣接Bay電圧から継承補完するのは推論=捏造境界に近い。継承を許すか、無印のまま `@u` で保持し計算層でのみ最高位に寄せるか。
- **[判断要] 1次/2次の電圧階級導出規則**: OSMに primary/secondary タグが無いため「階級大=1次」と決定的に導出。3巻線・特殊結線(嶺南の 500/275/77 同居)で2巻線変圧器ラダー近似が物理と乖離する場合の扱い。
- **[判断要] node-breaker をどこまでDB永続化するか**: 全国2189バス規模で4階層を持つとデータ量増。全国一括か、検証済み地域から段階適用か。
- **[判断要] GridMend のリリース範囲(v0.1の線引き)**: cut機構(E8b)・ρ/AC検証連動・認証/同時編集を v0.1 に含めず後送りする提案。最小ループ(編集→ログ→島数A/B→issue→採用)でリリースしてよいか。
- **[判断要] OSM ODbL還元の自動化**: adopted接続のOSM changeset自動生成(E9)は外部書込で不可逆。手動レビュー必須とするか、自動化の権限境界。
- **[未確定] `line=substation`(全28本・voltage欠損43%)の扱い**: 信頼度低く件数僅少。構築に使うか無視するか未決。
- **[未確定] DC/異周波数連系の境界**: ボトムアップ成長は同期領域内が前提。FC・BTB の扱いは現行 `_freq_excluded` 踏襲だが、`--bottom-up` での明示的扱いは要設計。

---

## (8) 島の自動分類 — 方針A(オーナー確定 2026-06-14)

島(未接続節点)を機械的に2分類し、issue/候補へ振り分ける(`tokyo_sub_534`=南大井一丁目変電所の調査で確定):

| 種別 | 判定(自動) | 扱い |
|---|---|---|
| **A: OSM実体あり・線なし** | 近傍にOSM `power=substation` 有り、degree 0〜低、接続OSM線 0本 | **「仕方ない」=接続候補/OSM貢献**。バグ化しない。人間が実態で繋ぐかOSMに線追加 |
| **B: OSM実体なし幽霊** | 近傍にOSM substation 無いのにモデル節点だけ存在 | **真のバグ**=抽出/合成アンカー誤り → bug issue化して除去/修正 |

**確定方針(A)**: OSMに書かれているもの(A)は正として尊重しバグ扱いしない。GridMendは A を接続候補、B のみバグissueとして出す。判定器は島ごとに「OSM substation近接の有無・接続線の有無・degree」を算出して仕分ける。

---

## (9) 越境・二重記録の回避(オーナー懸念 2026-06-14)

**懸念**: 地域/所有者の境界付近で編集すると、同一の物理点/線が複数地域のデータに重複記録され DB が二重化する。明確に避けたい。

**対策(GridMendに組込)**:
- **全国(多地域)表示を既定に近づける**: 1地域ずつでなく隣接/全国を重ねて表示し、既存の点/線が見える状態で編集 → 重複追加を未然に防ぐ(オーナー示唆「全国表示にしておけば問題ないかも」)。多地域表示は既に着手(要再実装)。
- **編集時の重複検出**: `add_point`/`connect` 記録前に「その要素が既に系統に組み込まれているか」を全地域横断で判定(座標近接・既存OSM要素・既存編集ログとの一致)。一致すれば警告/抑止。
- **系統組込み判定**: 追加対象が「既にbuild後モデルの節点/辺として存在するか」を `built_view` 横断で照合。存在するなら新規記録せず既存にスナップ。
- **編集の地域タグ規律**: 越境接続は片側primary地域に1回だけ記録(両地域に二重登録しない)。supplement統合先も単一に固定。

→ これらは GridMend v0.1 の「编集前バリデーション」として実装する。
