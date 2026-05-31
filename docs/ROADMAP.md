# Roadmap — All-Japan-Grid

復元した日本全国送電網モデルの開発計画(7 フェーズ)と、現状の率直な評価です。

---

## 7-Phase Plan

### P1. 全国ゾーナル正準モデル + ライブ公開 (National-Zonal Canonical + Live Deploy)
- OSM 由来トポロジを vertex-snap 方式で復元し、同期 AC 島(hokkaido / east /
  west / okinawa)単位に整理、エリア間 AC 連系線(OCCTO)を付加
  (`examples/build_national_snapped.py`)。
- 地域別 AC/DC 潮流を計算し、`docs/` の Leaflet マップ(系統図・エリア・潮流解析・
  単線図の 4 タブ)としてライブ公開。
- **状態: 運用中 (live)**。

### P2. MATPOWER OPF / 経済性 (GENCOST) — **[DONE]**
- `build_gencost()` を追加し、`build_matpower_case` の両経路 (snapped / legacy) が
  GENCOST 付き OPF 対応ケースを生成。`save_case_to_matfile()` で標準 `.mat` 出力、
  `examples/export_and_solve_matpower.py` で書き出し+pandapower 検証まで自動化。
- 燃料種別 merit order(原子力<石炭<LNG<石油、再エネ≒0)で経済ディスパッチが可能。
- **状態: 完了**。

### P3. 連続潮流法 + N-1 (Continuation Power Flow + N-1) — **[in progress]**
- CPF (`src/dynamics/analysis/voltage_stability.py`) で P-V ノーズカーブを描き、
  電圧崩壊の負荷余裕 (loading margin) を算出。関西の臨界負荷 ~9.3 GW を実測済み
  (`output/cpf/kansai_pv.json`)。
- N-1 単一設備故障時の潮流再評価を整備中。
- **状態: 進行中**。

### P4. 想定事故 + 過渡安定度 (Contingency + Transient Stability)
- 動揺方程式ソルバ (`src/dynamics/swing_solver.py`)・同期機/励磁/調速機モデル
  (`src/dynamics/models/`)を用いた事故後の角度・周波数応答解析。
- 想定事故セットによる安定度スクリーニング。
- **状態: 計画**。

### P5. 8760h 時系列 + 再エネ (Time-Series + Renewables)
- 年間 8760 時間の需要曲線・再エネ出力(太陽光/風力)時系列での連続潮流・UC。
- UC 基盤 (`src/uc/`) と需要曲線 (`src/powerflow/load_curve.py`) を活用。
- **状態: 計画**。

### P6. 弱小地域の OSM 補強 (Weak-Region OSM Enrichment)
- OSM が疎な四国・北陸・中国を中心に、OCCTO 実系統と突き合わせて欠落線・誤接続を
  補正し、断片化 (`n_components`) と低電圧を低減。
- **状態: 計画**。

### P7. ドキュメント + 比較タブ (Docs + Compare Tab)
- `docs/WHAT_TO_CHECK.md` / `docs/TECHNICAL_FAQ.md` / `docs/MATPOWER_EXPORT_GUIDE.md`
  と Before/After 比較ページ (`docs/compare.html`) を整備。
- **状態: 進行中**。

---

## 全体評価 (Overall Assessment)

- **トポロジ復元は堅実で実用レベル**。vertex-snap + トレランス・スナップ +
  degree-2 collapse により、旧最近傍方式の断片化を大幅に改善し、実ルートで連結した
  全国モデルを得られている。
- **電気的パラメータが合成値であることが運用上の信頼性を制限する**。R/X/B は
  電圧クラス別標準値、負荷配分は kV² 近似、コストは FX 換算の計画値。相対傾向や
  merit order は有意だが、絶対値・個別線の運用可否判断には不適。
- **弱小地域は OSM の被覆ギャップを正直に反映**。低電圧・断片化を合成で糊塗せず、
  multi_slack で各成分を解いて可視化、同一陸塊 5 km 以内のギャップのみ点線で補完。
  関西 AC の FAIL も電圧安定性限界の正直な表れ。

**結論**: 教育・研究・トポロジ可視化には十分使えるが、運用級の電気解析には
P3–P6 のパラメータ/データ補強が前提となる。
