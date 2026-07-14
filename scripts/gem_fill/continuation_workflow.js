export const meta = {
  name: 'gem-capacity-continuation',
  description: '1-C GEM容量充填の継続: 残り裁定+未スポット反証+AUTO検証+捜索(キャッシュ済み裁定は回収済み前提)',
  phases: [
    { title: 'Adjudicate', detail: '残り裁定バッチ+未スポットaccept反証' },
    { title: 'VerifyAuto', detail: 'AUTOマッチ(major全+solar標本)の敵対的検証' },
    { title: 'Search', detail: '未マッチmajorのgem.wiki捜索+同定検証' },
  ],
}

const A = typeof args === 'string' ? JSON.parse(args) : args
const S = A.scratch

const HONESTY = `重要規約(捏造防止):
- 同一の「物理施設」であることが要件。根拠=名前(GEMタイトルのローマ字/英語 ⇄ OSMの日本語名の対応・GEMページ内の和名併記)・所在地(市町村)・座標距離・容量規模・カテゴリと燃料の整合。
- 確信が持てなければ match_title は null(誤同定は捏造。nullが正解のことは多い。特に密集メガソーラー地帯)。
- OSM側座標は敷地ポリゴンの重心なので、同一施設でも数百mズレは正常。1km超は名前一致など強い独立根拠が必須。
- note が "gem page claimed by closer plant" の事案は、OSMが1施設を複数ポリゴンに分割した可能性が高い。GEMページが表す施設「全体」に最も対応する1件だけを match とし、部分片は null。
- 必要なら candidates 内の url を WebFetch してページ本文(和名・所在地・ユニット構成)を確認してよい。
- verdicts には入力の全 plant を漏れなく含めること。`

const VERDICTS = {
  type: 'object', required: ['verdicts'], additionalProperties: false,
  properties: { verdicts: { type: 'array', items: {
    type: 'object', additionalProperties: false,
    required: ['plant', 'match_title', 'confidence', 'reason'],
    properties: {
      plant: { type: 'string' },
      match_title: { type: ['string', 'null'] },
      confidence: { enum: ['high', 'medium', 'low'] },
      reason: { type: 'string', maxLength: 200 },
    } } } },
}

const SPOT = {
  type: 'object', required: ['checks'], additionalProperties: false,
  properties: { checks: { type: 'array', items: {
    type: 'object', additionalProperties: false,
    required: ['plant', 'refuted', 'reason'],
    properties: {
      plant: { type: 'string' },
      refuted: { type: 'boolean' },
      reason: { type: 'string', maxLength: 200 },
    } } } },
}

const REFUTE = {
  type: 'object', additionalProperties: false,
  required: ['plant', 'refuted', 'reason', 'page_operating_sum_mw'],
  properties: {
    plant: { type: 'string' },
    refuted: { type: 'boolean' },
    reason: { type: 'string', maxLength: 250 },
    page_operating_sum_mw: { type: ['number', 'null'] },
  },
}

const FOUND = {
  type: 'object', required: ['results'], additionalProperties: false,
  properties: { results: { type: 'array', items: {
    type: 'object', additionalProperties: false,
    required: ['plant', 'gem_title', 'note'],
    properties: {
      plant: { type: 'string' },
      gem_title: { type: ['string', 'null'] },
      note: { type: 'string', maxLength: 200 },
    } } } },
}

const pad = (i) => String(i).padStart(3, '0')

// ---- Phase 1a: 残り裁定(pipeline: 裁定 → バッチ内accept上位のスポット反証) ----
phase('Adjudicate')
const remBatches = Array.from({ length: A.nRemBatches }, (_, i) => i)
const adjP = pipeline(
  remBatches,
  (i) => agent(
    `あなたは日本の発電所データの同定裁定者です。九州/沖縄のOSM由来発電所(容量未知)と Global Energy Monitor wiki のページ候補の突合を裁定します。\n` +
    `ファイル ${S}/wf_adj_rem/batch_${pad(i)}.json を Read してください。各要素 = {plant: {key,name,fuel,lat,lon}, note?, candidates: [{title, ja_name, loc, category, lat, lon, url, operating_units, operating_total_mw, other_status, distance_m, name_eq}]}。\n` +
    `各 plant について、candidates の中から同一物理施設をひとつ選ぶか、該当なし(null)と判定してください。\n\n` +
    HONESTY + `\n\n最終出力は StructuredOutput のみ。plant フィールドには入力の plant.key をそのまま入れること。`,
    { label: `adj:${pad(i)}`, phase: 'Adjudicate', schema: VERDICTS }),
  (res, i) => {
    if (!res) return null
    const acc = res.verdicts.filter(v => v.match_title)
    if (!acc.length) return { batch: i, verdicts: res.verdicts, spot: null }
    const targets = acc.slice(0, 3)
    return agent(
      `あなたは敵対的な検証者です。以下の発電所同定を**反証**してください(疑わしきは refuted=true)。\n` +
      `検証対象: ${JSON.stringify(targets)}\n` +
      `手順: 各 match_title の gem.wiki ページ (https://www.gem.wiki/<title の空白を_に>) を WebFetch し、そのページが本当に対象plant(ファイル ${S}/wf_adj_rem/batch_${pad(i)}.json 内の該当要素)と同一施設かを、和名・所在地・座標・容量規模で点検。同定が誤りらしければ refuted=true。ページ取得に失敗したら refuted=false とし reason に fetch-failed と書く。\n` +
      `最終出力は StructuredOutput のみ(checks に対象全件)。`,
      { label: `adjspot:${pad(i)}`, phase: 'Adjudicate', schema: SPOT })
      .then(sc => ({ batch: i, verdicts: res.verdicts, spot: sc ? sc.checks : null }))
  },
)

// ---- Phase 1b: 前回キャッシュ済みacceptのうち未スポット分の反証(3件/バッチ) ----
const spotBatches = Array.from({ length: A.nSpotBatches }, (_, i) => i)
const spotP = parallel(spotBatches.map(i => () => agent(
  `あなたは敵対的な検証者です。ファイル ${S}/wf_spot/batch_${pad(i)}.json を Read してください。内容 = {targets: [{plant, match_title, confidence, reason}], context: [{plant: {key,...}, candidates: [...]}]}。\n` +
    `targets の各発電所同定を**反証**してください(疑わしきは refuted=true)。\n` +
    `手順: 各 match_title の gem.wiki ページ (https://www.gem.wiki/<title の空白を_に>) を WebFetch し、そのページが本当に対象plant(context 内の該当要素)と同一施設かを、和名・所在地・座標・容量規模で点検。同定が誤りらしければ refuted=true。ページ取得に失敗したら refuted=false とし reason に fetch-failed と書く。\n` +
    `最終出力は StructuredOutput のみ(checks に対象全件・plant には plant.key)。`,
  { label: `spot:${pad(i)}`, phase: 'Adjudicate', schema: SPOT })
  .then(sc => (sc ? sc.checks : null))))

// ---- Phase 2: AUTOマッチの敵対的検証(1件1エージェント) ----
phase('VerifyAuto')
const verItems = Array.from({ length: A.nVerItems }, (_, k) => k)
const verP = parallel(verItems.map(k => () => agent(
  `あなたは敵対的な検証者です。自動突合された発電所同定を**反証**してください(疑わしきは refuted=true が既定)。\n` +
  `ファイル ${S}/wf_ver/item_${pad(k)}.json を Read。内容 = {plant: {key,name,fuel,lat,lon}, match: {title, ja_name, loc, url, operating_units, operating_total_mw, ...}}。\n` +
  `手順: ① match.url を WebFetch してページ実在と施設同一性(和名/所在地/座標/燃料)を点検 ② ページの Operating ユニット容量を読み取り合算し、match.operating_total_mw と一致するか検算(page_operating_sum_mw に記入) ③ operating_units の cap_raw 文字列が実ページに存在するか確認。\n` +
  `不一致・同一性への疑義があれば refuted=true。ページ取得失敗は refuted=false + reason=fetch-failed。plant には plant.key を入れる。最終出力は StructuredOutput のみ。`,
  { label: `ver:${pad(k)}`, phase: 'VerifyAuto', schema: REFUTE })))

// ---- Phase 3: 未マッチmajorの捜索 → 発見分の同定検証 ----
phase('Search')
const srchBatches = Array.from({ length: A.nSrchBatches }, (_, i) => i)
const foundP = pipeline(
  srchBatches,
  (i) => agent(
    `あなたは調査者です。九州/沖縄のOSM由来発電所(容量未知・自動突合で未発見)が Global Energy Monitor wiki (gem.wiki) に存在するか捜索してください。\n` +
    `ファイル ${S}/wf_srch/batch_${pad(i)}.json を Read。各要素 = {key, name, fuel, lat, lon}。\n` +
    `手段: gem.wiki の検索API (https://www.gem.wiki/w/api.php?action=query&list=search&srsearch=<ローマ字名や地名>&format=json) を WebFetch。日本語名をローマ字化した検索語(例: 夜明→Yoake)や所在地名で探す。ヒットしたらページを開いて所在地・座標(±数km)・燃料の一致を確認。\n` +
    `注意: 多くは小規模水力でGEM収載閾値未満=見つからないのが正常。無理に当てない(曖昧なら null)。gem_title には正確なページ名。最終出力は StructuredOutput のみ。`,
    { label: `srch:${pad(i)}`, phase: 'Search', schema: FOUND }),
  (res, i) => {
    if (!res) return null
    const hits = res.results.filter(r => r.gem_title)
    if (!hits.length) return { batch: i, results: res.results, spot: null }
    return agent(
      `敵対的検証者として、以下の捜索ヒットの同定を**反証**してください(疑わしきは refuted=true)。対象plantの情報はファイル ${S}/wf_srch/batch_${pad(i)}.json にあります。\n` +
      `ヒット: ${JSON.stringify(hits)}\n` +
      `各 gem_title のページを WebFetch し、和名・所在地・座標・燃料の同一性を点検。最終出力は StructuredOutput のみ(checks に対象全件)。`,
      { label: `srchspot:${pad(i)}`, phase: 'Search', schema: SPOT })
      .then(sc => ({ batch: i, results: res.results, spot: sc ? sc.checks : null }))
  },
)

const [adj, spotsExtra, autoVer, found] = await Promise.all([adjP, spotP, verP, foundP])

// ---- 集約(戻り値はコンパクトに・前回キャッシュとの合算は呼び出し側で) ----
const verdicts = adj.filter(Boolean).flatMap(b => (b.verdicts || []).map(v => ({
  plant: v.plant, match_title: v.match_title, confidence: v.confidence,
  reason: (v.reason || '').slice(0, 120),
})))
const spots = adj.filter(Boolean).flatMap(b => b.spot || [])
  .concat(spotsExtra.filter(Boolean).flat())
const searches = found.filter(Boolean).flatMap(b => (b.results || []))
const searchSpots = found.filter(Boolean).flatMap(b => b.spot || [])
const nAccept = verdicts.filter(v => v.match_title).length
log(`残り裁定: ${verdicts.length}件中 accept=${nAccept} / スポット反証=${spots.filter(s => s.refuted).length}/${spots.length}`)
log(`AUTO検証: refuted=${autoVer.filter(Boolean).filter(v => v.refuted).length}/${autoVer.filter(Boolean).length}`)
log(`捜索: hit=${searches.filter(s => s.gem_title).length}/${searches.length}`)
return { verdicts, spots, autoVer: autoVer.filter(Boolean), searches, searchSpots }
