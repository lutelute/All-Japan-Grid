# データスペース設計 — 外部データの疎結合連携

- **方針**（オーナー指示 2026-06-11）: 「気象データはある。予測値はMSMから取得できる。
  しかしそこはデータスペースみたいな連携をすべきで、**全て持ってくるのはナンセンス**」
- **状態**: 設計v1 + 最小実装（registry / 契約 / キャッシュ / 出所記録 / コネクタ2種）

---

## 1. 原則

1. **データは源泉に留める（zero-copy）** — MSMのGRIB2アーカイブ（TB級）や
   OCCTOの30分値全量をこのリポジトリに複製しない。AGJ側が持つのは
   **コネクタ・契約・キャッシュ・出所記録**だけ。
2. **必要な断面だけを引く** — UCが必要とするのは「地域×時間のCF/需要系列」
   （数百KB）であって全国メッシュ×全変数ではない。集約は**源泉に近い場所**
   （NASをマウントした pws-160core 等）で行い、AGJへは集約結果のみ渡す。
3. **契約（Data Contract）を明文化** — 提供者・所在・ライセンス・再配布可否・
   粒度を `config/dataspace.yaml` に宣言。**契約にない使い方はしない**
   （例: P03生GML・MSM生GRIB2は redistribute_raw: false → コミット禁止）。
4. **出所の機械記録（provenance）** — 何を・いつ・どこから・どのクエリで
   取得したかを `data/cache/dataspace/provenance.jsonl` に追記。
   結果の再現は「契約+クエリ+取得時刻」で説明できる。
5. **既存慣行と接続** — `data/external/`（gitignore・取得コマンドはdocstring）、
   `enrichments.jsonl` の source体系、grid.db の R/C/D 層は本設計の先行例。
   データスペースはそれらの**入口を統一する層**であり、置き換えではない。

## 2. アーキテクチャ

```
┌─ 源泉（custodian側に留まる）──────────────────────────────┐
│ MSM GPVアーカイブ(研究室NAS)  OCCTO web-kohyo  P03  エネ庁統計 │
└──────┬───────────────┬──────────┬──────┬──────────────────┘
       │ connector=msm │ =occto   │ =p03 │ =energy_stats
       ▼               ▼          ▼      ▼
┌─ src/dataspace/ ────────────────────────────────────────────┐
│ registry.py   config/dataspace.yaml の契約カタログを解決      │
│ connectors/   fetch(query, contract) → 集約済み軽量データのみ │
│ store.py      キャッシュ(data/cache/dataspace/, sha256キー)   │
│               + provenance.jsonl 追記                         │
└──────┬──────────────────────────────────────────────────────┘
       ▼ 地域別CF系列・需要系列・較正値（数百KB、契約上committable）
┌─ 消費側 ─────────────────────────────────────────────────────┐
│ UCシナリオ(config/uc_scenarios/*.yaml) ・ 較正レポート ・ 検証  │
└──────────────────────────────────────────────────────────────┘
```

## 3. プロバイダカタログ（契約の要点）

| provider | 所在（custodian） | 取るもの | 再配布 |
|---|---|---|---|
| `msm` | 研究室NAS（京大RISH配布の気象庁MSM GPV） | 地域集約した日射/風速→CF系列のみ | 生GRIB2不可・派生集約は出典明記で可 |
| `occto_kohyo` | OCCTO web-kohyo 公開CSV API | エリア需要実測・連系線潮流（30分値）の期間統計/系列 | 生CSV非追跡・集計値は出典明記で可 |
| `p03` | 国土数値情報（MLIT） | 発電所権威属性（enrich経由） | 生GML不可・derived属性のみ |
| `energy_stats` | 資源エネ庁 電力調査統計/総合エネルギー統計 | 実績シェア等の較正定数 | 数値引用可（出典明記） |

詳細・更新は `config/dataspace.yaml` が正本。

## 4. 使い方

```python
from src.dataspace import DataSpace

ds = DataSpace()                      # config/dataspace.yaml を読む
c = ds.contract("msm")               # 契約の参照（所在・ライセンス・可否）
series = ds.fetch("occto_kohyo", {   # 取得（キャッシュ+出所記録つき）
    "kind": "area_demand",
    "date_from": "2025-04-01", "date_to": "2025-04-07",
})
```

- `fetch` は同一クエリをキャッシュから返す（`force=True` で再取得）。
- すべての取得は provenance.jsonl に記録される。
- **MSMコネクタは所在が設定されるまで動かない**（`AJGRID_MSM_ROOT` 環境変数
  またはカタログの location）。未設定時は所在の設定方法を案内して失敗する —
  暗黙にどこかへ取りに行くことはしない。

## 5. UCシナリオとの接続（Phase 2 仕様）

シナリオYAMLの renewables に、固定CF曲線の代わりにデータスペース参照を
書けるようにする（実装はPhase 2、仕様のみ先行定義）:

```yaml
renewables:
  solar:
    capacity_mw: {...}
    profile_ref:                  # cf_base_24h の代替
      provider: msm
      kind: regional_cf
      variable: dswrf             # 下向き短波放射 → CF変換
      period: fy2023
```

ローダーは profile_ref があれば `DataSpace.fetch` で系列を解決し、
シナリオsha256には**取得結果のsha**も合成する（再現性の連鎖を保つ）。

## 6. 段階導入

- **済（このcommit）**: registry / 契約カタログ / キャッシュ+provenance /
  OCCTOコネクタ（エリア需給CSV、エンドポイントは設定可能）/ MSMコネクタIF+ガード
- **Phase 2**: MSM実装（NAS所在の確定後: GRIB2→地域マスク集約→CF変換を
  pws-160core 側で実行）/ profile_ref のローダー解決 / OCCTO実測needsへの置換
- **Phase 3**: grid.db との統合（dataspace取得物のR層スナップショット化）、
  他研究プロジェクト（JRP等）との相互提供

## 7. 「持ってこない」ことの具体的な意味

- リポジトリにコミットしてよいのは: 契約カタログ・コネクタコード・
  **集約済み派生物のうち契約が再配布を許すもの**（地域別CF系列等）・provenance
- コミットしてはならないもの: MSM GRIB2・OCCTO生CSV・P03生GML（既存方針継続）
- キャッシュ（data/cache/dataspace/）は gitignore — 消えても契約+クエリから再構築可能

## 8. 電源種別の発電実績 — 所在調査（2026-06-12）

UC検証ループ（モデルの燃料別ディスパッチ vs 実績）に必要な
**電源種別・時間別の発電実績**の所在を調査した結果:

- **OCCTO web-kohyo には無い**。`jhSybt` 全探索（01=日別需給・02=エリア需要実測
  〔稼働中〕・03/06=連系線の運用容量・04=連系線潮流・05=時刻別需給・
  07=広域予備率・08=無効）— いずれも需要/供給力/予備力の総量のみで
  電源種別内訳は提供されない
- **本命は各一般送配電事業者の「エリア需給実績」CSV**（月次公開・30分または
  1時間値）: 原子力/火力/水力/地熱/バイオマス/太陽光(実績+出力制御)/
  風力(同)/揚水/連系線 の種別列を持つ。例: 東京電力PG `eria_jukyu_*.csv`。
  10社で URL・列構成が異なるため、プロバイダ `area_jukyu` として
  社別entrypointを契約カタログに列挙する方式が適切（Phase 2+）
- でんき予報リアルタイム（`juyo-j.csv` 等）は需要+使用率のみ → 検証ループには
  月次の需給実績を使い、リアルタイム値は速報モニタ用途に限る
