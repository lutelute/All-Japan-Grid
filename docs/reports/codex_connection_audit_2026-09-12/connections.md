# 系統接続監査

入力 SHA256: `955d6e0b2baf5d18ae44762db4100e1b446f171e8ad16502856281caf2e33b6a`

正典は変更していない。件数はこの入力スナップショットに対する監査値。

## 確認済みのデータ整合性

- ノード 17,738（保存済み統計 17,841）、枝 19,944（保存済み統計 19,529）。
- 保存済み main と所属島別の再計算が異なるノード: 194。定義差と更新漏れの両方を含み得る。
- 端点ノード欠落: 0。座標自己ループ: 2181（うち 2172 は構内stubと明示。誤接続件数ではない）。

## 座標グラフの残存断片

既存枝のみ・島内k5座標。追加stitch/tieなし。変電所は座標キー単位で、サイト数や電気母線数ではない。

| 島 | 座標キー | 最大成分 | 断片成分 | 断片ノード | 断片変電所 |
|---|---:|---:|---:|---:|---:|
| hokkaido | 760 | 728 | 21 | 32 | 18 |
| east | 5579 | 5154 | 221 | 425 | 132 |
| west | 6987 | 6498 | 277 | 489 | 157 |
| okinawa | 81 | 75 | 6 | 6 | 6 |

## 接続候補（未確定）

近いだけでは接続しない。同一way・頂点共有・敷地への引込・電圧階級・周波数・公式図の順に確認する。

| 島 | 断片側 | 本系統側 | 距離m | 断片ノード | 電圧証拠 | 跨島重複 |
|---|---|---|---:|---:|---|---|
| east | chubu junction 35.9666:139.107:66 | tokyo junction 35.9665:139.1073:66 | 27.1 | 12 | same_observed_class | False |
| east | 秩父変電所 | 秩父変電所 | 46.2 | 12 | same_observed_class | False |
| east | 横瀬変電所 | 横瀬変電所 | 78.8 | 12 | same_observed_class | False |
| east | 武州中川変電所 | 武州中川変電所 500kV | 121.0 | 12 | same_observed_class | False |
| east | 武州中川変電所 | 奥秩父変電所 500kV | 209.2 | 12 | same_observed_class | False |
| east | chubu junction 35.9535:138.9266:66 | 楢平変電所 | 267.1 | 12 | same_observed_class | False |
| east | chubu junction 36.4906:139.012:66 | 南渋川変電所 | 51.6 | 7 | same_observed_class | False |
| east | chubu junction 35.559:138.9143:154 | 谷村変電所 154kV | 106.3 | 4 | same_observed_class | False |
| east | chubu junction 35.6377:138.5729:154 | 山梨変電所 154kV | 193.3 | 4 | same_observed_class | False |
| east | chubu junction 36.3789:138.8958:66 | 上里見変電所 | 5.0 | 2 | same_observed_class | False |
| east | chubu junction 36.2949:139.0825:66 | tokyo junction 36.2948:139.0825:66 | 5.6 | 2 | same_observed_class | False |
| east | chubu junction 36.0293:139.0955:66 | tokyo junction 36.0293:139.0956:66 | 6.4 | 2 | same_observed_class | False |
| east | chubu junction 35.708:138.9071:500 | 葛野川発電所屋外開閉設備 | 7.2 | 2 | same_observed_class | False |
| east | chubu junction 36.0292:139.0955:66 | tokyo junction 36.0293:139.0956:66 | 7.7 | 2 | same_observed_class | False |
| east | chubu junction 36.3791:138.8958:66 | 上里見変電所 | 10.0 | 2 | same_observed_class | False |
| east | chubu junction 36.3495:139.1372:66 | 駒形変電所 | 19.4 | 2 | same_observed_class | False |
| east | chubu junction 36.5171:139.0129:66 | 子持変電所 | 20.7 | 2 | same_observed_class | False |
| east | chubu junction 36.5171:139.0127:66 | 子持変電所 | 21.6 | 2 | same_observed_class | False |
| east | chubu junction 36.5235:138.9883:66 | 金井変電所 154kV | 22.2 | 2 | same_observed_class | False |
| east | chubu junction 36.5472:138.8334:500 | 新榛名 500kV | 23.7 | 2 | same_observed_class | False |
| east | chubu junction 36.452:139.0038:154 | 吉岡変電所 | 25.0 | 2 | same_observed_class | False |
| east | chubu junction 36.38:139.105:66 | 野中変電所 | 25.2 | 2 | same_observed_class | False |
| east | chubu junction 36.2508:138.9697:66 | 吉井変電所 | 25.3 | 2 | same_observed_class | False |
| east | chubu junction 36.2949:139.0825:66 | tokyo junction 36.2949:139.0823:66 | 25.7 | 2 | same_observed_class | False |
| east | chubu junction 36.3495:139.137:66 | 駒形変電所 | 27.5 | 2 | same_observed_class | False |

## その他の確認対象

- 別島に同一座標が存在: 39座標。異電圧端子や変換所の可能性もあるため一括統合しない。
- 端点の島集合が互いに重ならない枝: 34。HVDC/FCの実線と地域誤帰属を分類する必要がある。
- pathと接続先座標が500m超離れる端点: 256。変電所重心への取付を除外して判読する。

全件・ノードID・枝index・根拠は connections.json。候補直線は位置の比較用で、実在線路を意味しない。
