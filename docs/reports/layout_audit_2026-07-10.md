# docs/ 公開ページ レイアウト監査レポート

- 監査日: 2026-07-10
- 対象: `docs/` 直下の公開HTML（GitHub Pages配信）**全7ページ**
- 方法: 静的検査（メタ/参照/リンク実在/SHA照合）＋ 動的検査（ローカル配信 `http.server` → Playwrightで実レンダリング。デスクトップ1280×900 / モバイル390×844）
- 成果物: 本レポート ＋ スクリーンショット11枚（同ディレクトリ `*.png`）
- **本タスクは確認と報告のみ。docs/等のプロジェクトファイルは一切変更していない。** 検査用ローカルサーバは停止済み。
- 注: スクリーンショット原本はセッション作業域(非追跡)。再取得は Playwright で docs/ をローカル配信して同条件(1280×900/390×844)で撮影可
- 対応状況(2026-07-10): I2(index→download導線)とI3(バナー版数v1.6.0化)は v1.6.0 リリースで是正済(456e53c)。B1/I1/I4/M1-M6 はオーナー判断待ち

---

## 1. ページ一覧（役割つき）

| # | ファイル | 役割 | テーマ | 構造 | 参照元(公開ページ間) |
|---|---------|------|--------|------|------|
| 1 | index.html | メイン系統図ダッシュボード（ハブ）。8タブ、compare/editor/reviewをiframe埋込 | ダーク #0f1419/#1a1a2e | サイドバー360px＋地図＋上部タブバー | （トップ） |
| 2 | download.html | データセット配布ランディングページ（v1.5.0） | ダーク #0b0f14 | hero＋chipナビ＋カードグリッド＋footer | なし（孤立） |
| 3 | compare.html | Before/After トポロジ比較（2ペイン地図） | ダーク #0f1419 | 2ペインflex＋上部凡例 | index.html（リンク＋iframe） |
| 4 | editor.html | 接続編集プラットフォーム（新・67KB） | ダーク #0d1117 | 地図＋右パネル382px固定 | index.html（iframe） |
| 5 | review.html | 候補レビュー（A島接続・閲覧専用） | ダーク #0d1117 | 地図＋右パネル360px固定 | index.html（iframe） |
| 6 | uc_map.html | UC before/after 潮流マップ | ライト（白パネル） | 地図＋フローティングパネル | なし（孤立） |
| 7 | connection_editor.html | 接続編集ツール（旧・6KB） | ダーク #0d1117 | 地図＋右パネル340px固定 | なし（孤立・editor.htmlの旧版） |

---

## 2. 不整合の全リスト

### 重大度: 壊れている（Broken）

**B1. モバイル幅で地図系ページがレイアウト崩壊**（index / editor / review / connection_editor / uc_map / compareの6枚）
- 地図＋固定幅パネル構成のため、390px幅では地図が潰れ実質使用不能。
  - index.html（トップページ）: サイドバー360px固定で地図がほぼ見えず、右の一覧パネル（変電所/送電線/発電所）がDOWNLOADボタン群に重なる。上部タブは8個が詰め込まれ「潮流解/析」「候補レ/ビュー」と2行に折返し。→ index_mobile.png
  - editor.html: 実測 地図幅8px / パネル382px（viewport390px）。地図が消失。→ editor_mobile.png
  - review / connection_editor / uc_map も同じ固定パネル方式で同様に崩れる。
- 補足: compare.html は2ペインflexのため横スクロールは無く（scrollW=clientW）表示自体は成立するが、ヘッダ凡例が縦に伸び地図が画面下部に押しやられ窮屈。→ compare_mobile.png
- 性質: これらは元来デスクトップ専用の地図ツール。ただし全ページが viewport meta を出しており、モバイルで開くと壊れる。特に index.html はトップページのため実害が大きい。

### 重大度: 不統一（Inconsistent）

**I1. テーマ不統一** — uc_map.html だけライトテーマ（白半透明パネル）。他6ページは全てダーク。さらにダーク側も背景色が3系統に割れている（index/compare=#0f1419系、editor/review/connection_editor=#0d1117系、download=#0b0f14）。同一プロジェクトのページ群として配色の統一がない。→ uc_map_desktop.png

**I2. ナビゲーションの断絶（孤立ページ3枚）** — 公開ページ間リンクをgrep調査した結果:
- download.html・uc_map.html・connection_editor.html はどの公開ページからもリンクされておらず、URL直打ちでしか到達できない。
- ハブである index.html から download.html（配布ページ）・uc_map.html への導線がゼロ（grep -c = 0）。
- 一方 download.html → index.html のリンクは存在（片方向のみ）。配布ページにトップから辿り着けないのは実害。

**I3. バージョン表記の不整合** — index.html の "What's new" バナーは「v1.1.0 release」を宣伝（N-1/Ybus等）。同時期の download.html は「v1.5.0」（core/full配布）。トップページのバナーが4マイナー版古いまま。→ index_desktop.png vs download_desktop_full.png

**I4. 「接続編集」ツールが二重に存在** — editor.html（新・洗練されたカードUI）と connection_editor.html（旧・素朴なUI）が両方公開されている。index.htmlのタブは新版を使い、旧版は孤立。体裁も異なり、公開URLとしては重複・混乱の元。→ editor_desktop.png vs connection_editor_desktop.png

**I5. ヘッダ/フッタ体裁の不統一** — download.html のみ hero header＋chipナビ＋footer を持つランディング体裁。他6ページは共通ヘッダ/フッタ/ブランドバーを持たず地図フルスクリーン。役割相応ではあるが、ページ間を横断する共通ナビ・ブランド帯がないため「同一サイトの一部」という一貫性が視覚的に希薄。

### 重大度: 軽微（Minor）

**M1. compare.html: ペインタイトルとズームコントロールの重なり** — 各ペインの <h2>（BEFORE/AFTER）が position:absolute; top:8px; left:8px で、同じ左上のLeaflet +/- ズームコントロールと衝突。頭2文字が隠れ「FORE(旧)」「TER(新)」と表示される。→ compare_desktop.png

**M2. uc_map.html: パネル内ラジオの折返し** — 「断面」の before/after/差分 の3ラジオが max-width:290px に収まらず折返し、「after（UC 注入)」の "注入)" が2行目にこぼれ窮屈。→ uc_map_desktop.png

**M3. メタ宣言の表記ゆれ** — charset が UTF-8（大文字: index/compare/download）と utf-8（小文字: editor/connection_editor/review/uc_map）で混在。viewport も initial-scale=1.0 と =1 で混在。実害はないが不統一。

**M4. favicon 未設定** — 全ページで favicon.ico が 404。ブラウザタブのブランドアイコンがない。

**M5. download.html「回し方」のコード例がカード幅を超過** — <pre> のコマンド末尾が視覚的に切れる（overflow-x:auto で横スクロールは可能だが初見で欠落して見える）。→ download_desktop_full.png

**M6. 外部CDN依存（インフラ寄り）** — 全ビューアページが unpkg.com からLeaflet CSS/JSを読込。CDN障害/オフライン時に地図UIが全滅。レイアウトの直接原因ではないが表示崩れリスク。

---

## 3. 正常だった点（問題なし）

- 内部リンク・アセット参照は全て実在（リンク切れゼロ）。index.html のjs/css/png、download.html の画像、editor/reviewのjs、いずれも実ファイルあり。
- download.html のSHA256表記は正しい。記載のcore b7522aae… / full f66d8216… は dist/bundle/all-japan-grid-dataset-v1.5.0-{core,full}.zip の実ハッシュと完全一致。バージョン(v1.5.0)・リンク先(GitHub Releases)も整合。
- download.html はデスクトップ/モバイル両方でレイアウト良好。レスポンシブグリッドが1列化し横スクロールなし（scrollW=clientW=375）。7ページ中もっとも完成度が高い。
- editor.html / review.html はデスクトップでGitHubトーンに整然と統一され崩れなし。

---

## 4. 修正提案（優先度順・実装はしていない）

1. （I2/I3 高）トップ導線とバージョンの是正: index.html から download.html（配布）への導線を追加。What's newバナーを実リリース(v1.5.0)に更新。孤立している uc_map.html の導線も検討。
2. （I4 高）重複解消: connection_editor.html（旧版）を廃止 or editor.html へのリダイレクトに。公開「接続編集」を1本化。
3. （I1 中）テーマ統一: uc_map.html をダーク化、もしくはダーク背景色を1つ（例 #0d1117）に揃える。共通CSS変数の共有を検討。
4. （B1 中）モバイル方針の明確化: 地図ツールは「デスクトップ推奨」を明示するか、パネルをモバイルで下部ドロワー/折畳みにする最小対応。少なくとも index.html（トップ）は要対応。
5. （M1 低）compare.html のペイン <h2> を left から right 寄せ、またはズームコントロールを topright へ移動して重なり解消。
6. （M2 低）uc_map.html のパネル max-width を拡げるか断面ラジオを縦積みに。
7. （M3/M4 低）charset/viewport表記を統一、favicon（emoji/PNG）を全ページ共通で追加。

---

## 5. スクリーンショット対応表

| ファイル | 内容 |
|---------|------|
| index_desktop.png / index_mobile.png | トップ。モバイルで崩壊（B1） |
| download_desktop_full.png / download_mobile.png | 配布ページ。両幅で良好 |
| compare_desktop.png / compare_mobile.png | 比較2ペイン。デスクトップでタイトル重なり(M1) |
| editor_desktop.png / editor_mobile.png | 接続編集(新)。モバイルで地図8px(B1) |
| review_desktop.png | 候補レビュー。デスクトップ良好 |
| uc_map_desktop.png | UC潮流。ライトテーマ(I1)＋ラジオ折返し(M2) |
| connection_editor_desktop.png | 接続編集(旧)。孤立・重複(I4) |
