# 系統図判読エージェント共通契約（AGJ・孤立変電所の実証接続）

リポジトリ: /Users/shigenoburyuto/Documents/GitHub/project_Hayashi/All-Japan-Grid
scratchpad: /private/tmp/claude-501/-Users-shigenoburyuto-Documents-GitHub-project-Hayashi-All-Japan-Grid/69ca6350-e35f-4ce1-b335-621694b92146/scratchpad

## 目的
担当地域の「孤立変電所(繋ぐべきA)」それぞれについて、送配電事業者の公表系統図PDFから
**その変電所が繋がる相手変電所と線路名を判読**し、根拠つきで報告する。

## 入力
- ターゲット: scratchpad/targets_{region}.json — {targets:[{name,kv,lat,lon}], main_subs:[{name,kv,lat,lon}]}
  main_subs は AGJ モデルで本系統に載っている変電所一覧（相手端の実在確認に使う）。
- 図PDF: 指示で渡すパス（data/external/system_disclosure/ 配下・**転載禁止データ**）。

## 方法（順守）
1. `pdftotext -f 1 -l 99 <pdf> -` でテキスト層を見てターゲット名の載るページ/ファイルを特定。
   名前は「変電所」抜き・短縮形（例: 西新宿変電所→西新宿）で載ることが多い。
2. `pdftoppm -r 250 -png -f <p> -l <p> <pdf> <out>` でそのページを画像化し、
   Pythonで対象部を crop して Read（画像として読む）。crop は scratchpad に保存し、パスを結果に残す。
3. 図中でターゲット変電所を見つけ、**描かれている線**とその**相手端の変電所名**、
   可能なら**線名/線番号ラベル**を読む。
4. **座標照合**: 相手端の名前が targets_{region}.json の main_subs に存在するか確認。
   同名が複数あるときはターゲットの lat/lon に近いものが妥当か（都市名・県名で判断）。
5. 判定を confidence 高/中/低 で付ける。高=名前ラベルと線が明瞭・相手が main_subs に一意。

## 禁止事項（捏造防止・最重要）
- **図に描かれていない接続を推測で書かない**。地理的に近いから・普通はこう繋ぐから、は禁止。
- 記号だけで名前ラベルの無い変電所（無名の●等）を相手端として報告しない
  （その場合は unresolved・reason="相手端が無名記号"）。
- ターゲットが図に見つからない場合は unresolved・reason を正直に
  （「テキスト層に不在」「該当エリアに描画なし」等）。**見つからないのは正常な結果**。
- PDFの内容（図そのもの・数値）を出力に転載しない。出力は接続事実（名前と線名）のみ。

## 出力
scratchpad/mapread_{担当名}.json に JSON で保存し、最終メッセージに要約を書く:
```json
{"region": "...", "source_files": ["..."],
 "resolved": [{"target": "...", "target_kv": 66, "partner_as_printed": "...",
   "partner_in_main_subs": "一致したmain_subs名 or null", "line_label": "...または null",
   "kv_of_line": 66, "file": "...", "page": 3, "crop": "scratchpad/....png",
   "confidence": "高|中|低", "note": "..."}],
 "unresolved": [{"target": "...", "reason": "...", "files_checked": ["..."]}],
 "flags": [{"target": "...", "issue": "region誤ラベル疑い等の気づき"}]}
```
- resolved は「図で線が確認できたもの」だけ。partner_in_main_subs が null（相手も孤立/不在）でも
  図に描かれていれば resolved に載せてよい（連鎖で解けるため）。
- 迷ったら unresolved に落とす。数より正確さ。
