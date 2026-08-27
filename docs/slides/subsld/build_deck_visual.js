// SubSLD法 デッキ v3 — オーナーFB「白スクショ貼り・図が読めない・フォント崩れ」を解消
// 方針: 日本語=Hiragino Sans(Mac PowerPoint実書体) / 図は衛星・SLDを自動クロップして大きく /
//       衛星クロップ(ダーク)を地に馴染ませ、白面はSLD1枚に限定
const pptxgen = require("pptxgenjs");
const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5

const BG = "141417", PANEL = "1F1F26", PANEL2 = "2A2A33";
const TXT = "F2F1EC", MUT = "A5A3AC", YEL = "FFD54F";
const V500 = "D62728", V275 = "FF7F0E", V154 = "9467BD", V66 = "17BECF";
const CHIPS = [["500kV", V500], ["275kV", V275], ["154kV", V154], ["66kV", V66]];
const F = "Hiragino Sans";       // 日本語実書体(Mac)
const FL = "Helvetica Neue";     // 英字キッカー

function base(s) { s.background = { color: BG }; }
function chips(s, x, y, small) {
  const w = small ? 0.74 : 0.92, h = small ? 0.27 : 0.33, gap = 0.12;
  CHIPS.forEach(([lab, col], i) => {
    s.addText(lab, {
      x: x + i * (w + gap), y, w, h, fill: { color: col },
      color: "FFFFFF", fontSize: small ? 10 : 12, bold: true,
      fontFace: FL, align: "center", valign: "middle", margin: 0,
      rectRadius: 0.05, shape: pres.ShapeType.roundRect,
    });
  });
}
function kicker(s, txt, x, y) {
  s.addText(txt, { x, y, w: 7, h: 0.32, fontFace: FL, fontSize: 11.5,
    color: MUT, charSpacing: 3, margin: 0 });
}

// ---------------- 1. タイトル ----------------
{
  const s = pres.addSlide(); base(s);
  s.addImage({ path: "assets/geo_shinkeiyo.png", x: 7.5, y: 0, w: 5.83, h: 7.5,
    sizing: { type: "cover", w: 5.83, h: 7.5 } });
  kicker(s, "ALL-JAPAN-GRID  /  2026-08-26", 0.7, 0.85);
  s.addText("SubSLD法", { x: 0.62, y: 1.55, w: 6.6, h: 1.4, fontFace: F,
    fontSize: 60, bold: true, color: TXT, margin: 0 });
  s.addText("実証ペア図法 — 変電所構成の全国機械生成", {
    x: 0.66, y: 3.05, w: 6.6, h: 0.55, fontFace: F, fontSize: 20,
    color: YEL, margin: 0 });
  chips(s, 0.66, 3.9, false);
  s.addText("OSM＝正・捏造ゼロ・全端子に根拠。衛星写真上の構内幾何と単線結線図のペアで、全国6,956変電所を描く。", {
    x: 0.66, y: 4.7, w: 6.2, h: 1.2, fontFace: F, fontSize: 14.5,
    color: TXT, lineSpacing: 24, margin: 0 });
  s.addText("Evidence-Paired Substation Single-Line Diagramming", {
    x: 0.66, y: 6.75, w: 6.4, h: 0.3, fontFace: FL, fontSize: 10.5,
    color: MUT, margin: 0 });
}

// ---------------- 2. 問い ----------------
{
  const s = pres.addSlide(); base(s);
  // 右は人吉の衛星クロップをフルブリード(ダークが地に馴染む)
  s.addImage({ path: "assets/geo_hitoyoshi.png", x: 8.0, y: 0, w: 5.33, h: 7.5,
    sizing: { type: "cover", w: 5.33, h: 7.5 } });
  s.addShape(pres.ShapeType.rect, { x: 8.0, y: 6.55, w: 5.33, h: 0.95,
    fill: { color: "000000", transparency: 45 }, line: { type: "none" } });
  s.addText("人吉変電所(九州・220/110/66kV) — 手作業ゼロの実出力", {
    x: 8.2, y: 6.75, w: 5.0, h: 0.5, fontFace: F, fontSize: 12,
    color: "FFFFFF", margin: 0 });
  kicker(s, "01  MOTIVATION", 0.7, 0.5);
  s.addText("変電所の中身を、\n公開データだけで描けるか", {
    x: 0.66, y: 0.95, w: 7.0, h: 1.5, fontFace: F, fontSize: 28, bold: true,
    color: TXT, lineSpacing: 40, margin: 0 });
  const rows = [
    ["非公開の壁", "母線・変圧器・回線の内部構成は事業者資料。研究には使えない", V500],
    ["手作業の実証", "嶺南変電所1所で、OSM実データから node-breaker 構造を確認(2026-07)", V154],
    ["機械化の問い", "同じことを全国6,956所へ。証拠が無い値は埋めない(捏造ゼロ)", V66],
  ];
  rows.forEach(([h, b, c], i) => {
    const y = 3.0 + i * 1.42;
    s.addShape(pres.ShapeType.ellipse, { x: 0.7, y: y + 0.04, w: 0.5, h: 0.5,
      fill: { color: c }, line: { type: "none" } });
    s.addText(String(i + 1), { x: 0.7, y: y + 0.04, w: 0.5, h: 0.5,
      fontFace: FL, fontSize: 17, bold: true, color: "FFFFFF",
      align: "center", valign: "middle", margin: 0 });
    s.addText(h, { x: 1.45, y, w: 5.6, h: 0.42, fontFace: F, fontSize: 17,
      bold: true, color: TXT, margin: 0 });
    s.addText(b, { x: 1.45, y: y + 0.46, w: 6.1, h: 0.85, fontFace: F,
      fontSize: 12.5, color: MUT, lineSpacing: 18, margin: 0 });
  });
}

// ---------------- 3. 方針引用 ----------------
{
  const s = pres.addSlide(); base(s);
  // 地に駿遠の衛星を薄く敷く
  s.addImage({ path: "assets/geo_sunen.png", x: 0, y: 0, w: 13.33, h: 7.5,
    sizing: { type: "cover", w: 13.33, h: 7.5 }, transparency: 92 });
  chips(s, 0.7, 0.7, true);
  s.addText("線は基本変電所に入る。\n変電所で電圧階級・タップ・回線・導体を接続する。\nそこから負荷に分配供給されるからである。", {
    x: 1.1, y: 2.15, w: 11.2, h: 2.7, fontFace: F, fontSize: 27, bold: true,
    color: TXT, lineSpacing: 46, margin: 0 });
  s.addText("— 設計方針(2026-07-02)。SubSLD法はこの一文の全国機械化である。", {
    x: 1.12, y: 5.35, w: 10.5, h: 0.5, fontFace: F, fontSize: 14,
    color: YEL, margin: 0 });
}

// ---------------- 4. 3段パイプライン ----------------
{
  const s = pres.addSlide(); base(s);
  kicker(s, "02  PIPELINE", 0.7, 0.5);
  s.addText("3段パイプライン — 抽出・集約・描画", { x: 0.66, y: 0.92, w: 11.5,
    h: 0.65, fontFace: F, fontSize: 27, bold: true, color: TXT, margin: 0 });
  const cards = [
    ["1", "抽出", "GridStitch P2", "OSMの実証拠(頂点共有・ポリゴン内包・lead-in)だけで node-breaker 構造DBを生成", "全国6,956所 / 約4秒", V500],
    ["2", "集約", "プロパティ層", "線タグ circuits / wires / cables を端子に突き合わせ、変電所単位の回線数・導体数に", "5,920サイト", V154],
    ["3", "描画", "SubSLD", "GeoPane(衛星+構内幾何)×SLDPane(単線結線図)の実証ペア図を出力", "約1〜6秒 / 所", V66],
  ];
  cards.forEach(([n, tag, name, body, stat, col], i) => {
    const x = 0.66 + i * 4.24;
    s.addShape(pres.ShapeType.roundRect, { x, y: 1.95, w: 3.85, h: 4.35,
      fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.09 });
    s.addShape(pres.ShapeType.ellipse, { x: x + 0.3, y: 2.25, w: 0.56, h: 0.56,
      fill: { color: col }, line: { type: "none" } });
    s.addText(n, { x: x + 0.3, y: 2.25, w: 0.56, h: 0.56, fontFace: FL,
      fontSize: 19, bold: true, color: "FFFFFF", align: "center",
      valign: "middle", margin: 0 });
    s.addText(tag, { x: x + 1.0, y: 2.36, w: 2.5, h: 0.4, fontFace: F,
      fontSize: 14, bold: true, color: col, margin: 0 });
    s.addText(name, { x: x + 0.3, y: 3.05, w: 3.3, h: 0.5, fontFace: F,
      fontSize: 21, bold: true, color: TXT, margin: 0 });
    s.addText(body, { x: x + 0.3, y: 3.72, w: 3.25, h: 1.7, fontFace: F,
      fontSize: 12.5, color: MUT, lineSpacing: 19, margin: 0 });
    s.addText(stat, { x: x + 0.3, y: 5.62, w: 3.25, h: 0.42, fontFace: F,
      fontSize: 13.5, bold: true, color: col, margin: 0 });
    if (i < 2) s.addText("→", { x: x + 3.8, y: 3.85, w: 0.55, h: 0.6,
      fontFace: FL, fontSize: 26, color: MUT, align: "center", margin: 0 });
  });
  s.addText("全生成物は OSM + 構造DB から決定的に再生成できる", {
    x: 0.66, y: 6.65, w: 12, h: 0.4, fontFace: F, fontSize: 12,
    color: MUT, margin: 0 });
}

// ---------------- 5. GeoPane(衛星側) ----------------
{
  const s = pres.addSlide(); base(s);
  s.addImage({ path: "assets/geo_shinkeiyo.png", x: 5.6, y: 0, w: 7.73, h: 7.5,
    sizing: { type: "cover", w: 7.73, h: 7.5 } });
  kicker(s, "03  GEOPANE", 0.7, 0.5);
  s.addText("GeoPane\n構内幾何を衛星の上に", { x: 0.66, y: 1.0, w: 4.7, h: 1.6,
    fontFace: F, fontSize: 26, bold: true, color: TXT, lineSpacing: 38,
    margin: 0 });
  const its = [
    ["地理院写真", "全国最新写真を下敷き・出典焼込", YEL],
    ["敷地=黄縁・母線=電圧色", "busbar way を階級色の太線で", V500],
    ["端子の根拠マーカー", "●vertex ■polygon ▲leadin", V275],
    ["鉄塔 ▲ とインセット", "回廊を目で追える・大規模所は自動拡大", V66],
  ];
  its.forEach(([h, b, c], i) => {
    const y = 3.0 + i * 1.02;
    s.addShape(pres.ShapeType.rect, { x: 0.7, y: y + 0.07, w: 0.16, h: 0.16,
      fill: { color: c }, line: { type: "none" } });
    s.addText(h, { x: 1.0, y, w: 4.4, h: 0.35, fontFace: F, fontSize: 14.5,
      bold: true, color: TXT, margin: 0 });
    s.addText(b, { x: 1.0, y: y + 0.38, w: 4.5, h: 0.5, fontFace: F,
      fontSize: 11.5, color: MUT, margin: 0 });
  });
}

// ---------------- 6. SLDPane(結線図側) ----------------
{
  const s = pres.addSlide(); base(s);
  kicker(s, "04  SLDPANE", 0.7, 0.5);
  s.addText("SLDPane 単線結線図 — 新京葉変電所", { x: 0.66, y: 0.9, w: 9,
    h: 0.6, fontFace: F, fontSize: 26, bold: true, color: TXT, margin: 0 });
  // SLDは白地が正: 大きな白カード1枚に限定して掲載
  s.addShape(pres.ShapeType.roundRect, { x: 0.6, y: 1.7, w: 7.2, h: 5.5,
    fill: { color: "FBFBF9" }, line: { type: "none" }, rectRadius: 0.08 });
  s.addImage({ path: "assets/sld_shinkeiyo.png", x: 0.85, y: 1.85, w: 6.7,
    h: 5.2, sizing: { type: "contain", w: 6.7, h: 5.2 } });
  const its = [
    ["母線=太い水平線", "BusbarSection数でセクション分割。BT=バスタイ", V500],
    ["平行ストローク=回線数", "2回線なら2本。導体数はタグ注記(4導体等)", V275],
    ["上=流入・下=流出(推定)", "対向変電所の電圧階層から判定・矢印付き。灰=対向不明", V154],
    ["二重円=変圧器", "バンク数・銘板は出典付きの時のみ。変圧器の無い階級は「スルー」明記", V66],
  ];
  its.forEach(([h, b, c], i) => {
    const y = 1.95 + i * 1.32;
    s.addShape(pres.ShapeType.rect, { x: 8.15, y: y + 0.06, w: 0.16, h: 0.16,
      fill: { color: c }, line: { type: "none" } });
    s.addText(h, { x: 8.45, y, w: 4.5, h: 0.38, fontFace: F, fontSize: 15,
      bold: true, color: TXT, margin: 0 });
    s.addText(b, { x: 8.45, y: y + 0.42, w: 4.6, h: 0.8, fontFace: F,
      fontSize: 12, color: MUT, lineSpacing: 17, margin: 0 });
  });
}

// ---------------- 7. ギャラリー(衛星クロップで統一) ----------------
{
  const s = pres.addSlide(); base(s);
  kicker(s, "05  EVERYWHERE", 0.7, 0.45);
  s.addText("全国どこでも同じパイプライン", { x: 0.66, y: 0.85, w: 11, h: 0.6,
    fontFace: F, fontSize: 26, bold: true, color: TXT, margin: 0 });
  const gs = [
    ["assets/geo_minamihayakita.png", "南早来(北海道) 275/187/66kV"],
    ["assets/geo_sunen.png", "駿遠(中部) 500/275/154/77kV"],
    ["assets/geo_hitoyoshi.png", "人吉(九州) 220/110/66kV"],
    ["assets/geo_zukeran.png", "瑞慶覧(沖縄) 132/66kV"],
  ];
  gs.forEach(([p, cap], i) => {
    const x = 0.66 + (i % 4) * 3.08;
    s.addImage({ path: p, x, y: 1.65, w: 2.92, h: 4.6,
      sizing: { type: "cover", w: 2.92, h: 4.6 } });
    s.addShape(pres.ShapeType.rect, { x, y: 5.62, w: 2.92, h: 0.63,
      fill: { color: "000000", transparency: 40 }, line: { type: "none" } });
    s.addText(cap, { x: x + 0.12, y: 5.7, w: 2.7, h: 0.5, fontFace: F,
      fontSize: 10.5, bold: true, color: "FFFFFF", margin: 0 });
  });
  s.addText("SLDPane も同時生成される(ここでは衛星側のみ)。10地域・6,956所を同一コードで処理", {
    x: 0.66, y: 6.6, w: 12, h: 0.4, fontFace: F, fontSize: 12,
    color: MUT, margin: 0 });
}

// ---------------- 8. 被覆と限界(チャート) ----------------
{
  const s = pres.addSlide(); base(s);
  kicker(s, "06  COVERAGE", 0.7, 0.45);
  s.addText("被覆と、正直な限界", { x: 0.66, y: 0.85, w: 8, h: 0.6,
    fontFace: F, fontSize: 26, bold: true, color: TXT, margin: 0 });
  const stats = [
    ["6,956", "対象変電所(全国)", TXT],
    ["68%", "回線数のOSM証拠被覆", V66],
    ["14%", "母線way記載率 — 最大の欠測(issue #49)", V500],
  ];
  stats.forEach(([v, l, c], i) => {
    const y = 1.75 + i * 1.72;
    s.addText(v, { x: 0.66, y, w: 3.4, h: 0.95, fontFace: FL, fontSize: 52,
      bold: true, color: c, margin: 0 });
    s.addText(l, { x: 0.7, y: y + 1.0, w: 3.7, h: 0.55, fontFace: F,
      fontSize: 12, color: MUT, lineSpacing: 16, margin: 0 });
  });
  s.addChart(pres.ChartType.bar, [{
    name: "母線way記載率",
    labels: ["北海道", "東北", "北陸", "四国", "中国", "中部", "九州", "関西", "沖縄", "東京"],
    values: [53, 25, 25, 12, 11, 10, 10, 8, 5, 5],
  }], {
    x: 4.9, y: 1.5, w: 7.8, h: 5.35, barDir: "bar",
    chartColors: [YEL], showLegend: false,
    showTitle: true, title: "母線way記載率(%) — OSMマッピング粒度の地域差",
    titleColor: TXT, titleFontSize: 13, titleFontFace: F,
    showValue: true, dataLabelPosition: "outEnd", dataLabelColor: TXT,
    dataLabelFontSize: 10, dataLabelFontFace: FL,
    catAxisLabelColor: TXT, catAxisLabelFontSize: 11, catAxisLabelFontFace: F,
    valAxisLabelColor: MUT, valAxisLabelFontSize: 10, valAxisLabelFontFace: FL,
    valGridLine: { color: "3A3A44", size: 0.5 },
    catGridLine: { style: "none" },
    valAxisMaxVal: 60, plotArea: { fill: { color: BG } },
    chartArea: { fill: { color: BG } },
  });
}

// ---------------- 9. 不変条件 + 展開 ----------------
{
  const s = pres.addSlide(); base(s);
  kicker(s, "07  INVARIANTS & ROLLOUT", 0.7, 0.45);
  s.addText("不変条件と全所展開", { x: 0.66, y: 0.85, w: 9, h: 0.6,
    fontFace: F, fontSize: 26, bold: true, color: TXT, margin: 0 });
  const inv = [
    ["捏造ゼロ", "実証拠のみで接続。無タグ値は unknown のまま", V500],
    ["全端子に根拠", "vertex-shared / polygon / leadin / name-evidence", V275],
    ["推定は推定と明記", "流向(入/出)は推定であり凡例に明記", V154],
    ["決定的に再生成", "OSM更新に全所が追随できる", V66],
  ];
  inv.forEach(([h, b, c], i) => {
    const x = 0.66 + (i % 2) * 3.2, y = 1.8 + Math.floor(i / 2) * 1.35;
    s.addShape(pres.ShapeType.rect, { x, y: y + 0.06, w: 0.16, h: 0.16,
      fill: { color: c }, line: { type: "none" } });
    s.addText(h, { x: x + 0.3, y, w: 2.9, h: 0.35, fontFace: F,
      fontSize: 14.5, bold: true, color: TXT, margin: 0 });
    s.addText(b, { x: x + 0.3, y: y + 0.38, w: 2.85, h: 0.75, fontFace: F,
      fontSize: 10.5, color: MUT, lineSpacing: 15, margin: 0 });
  });
  // 右: 展開ステップ
  s.addShape(pres.ShapeType.roundRect, { x: 7.35, y: 1.65, w: 5.3, h: 5.35,
    fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.09 });
  s.addText("全所展開", { x: 7.7, y: 1.95, w: 4.6, h: 0.45, fontFace: F,
    fontSize: 17, bold: true, color: TXT, margin: 0 });
  const steps = [
    ["全6,956所を一括描画", "pws-160core・10地域並列 — 実行中", true],
    ["検索付き全国ギャラリー", "地域index+HTML", false],
    ["editor統合", "地図クリックでその場表示", false],
    ["OSM貢献ループ", "母線なし所の調査(issue #49)", false],
  ];
  steps.forEach(([h, b, on], i) => {
    const y = 2.6 + i * 1.08;
    s.addShape(pres.ShapeType.ellipse, { x: 7.72, y: y + 0.03, w: 0.4, h: 0.4,
      fill: { color: on ? YEL : PANEL2 }, line: { type: "none" } });
    s.addText(String(i + 1), { x: 7.72, y: y + 0.03, w: 0.4, h: 0.4,
      fontFace: FL, fontSize: 13, bold: true, color: on ? BG : MUT,
      align: "center", valign: "middle", margin: 0 });
    s.addText(h, { x: 8.3, y, w: 4.25, h: 0.38, fontFace: F, fontSize: 13.5,
      bold: true, color: TXT, margin: 0 });
    s.addText(b, { x: 8.3, y: y + 0.4, w: 4.25, h: 0.4, fontFace: F,
      fontSize: 11, color: on ? YEL : MUT, margin: 0 });
  });
  // 下: 限界の一行
  s.addText("限界も見せる: 流向不明(灰)の主因は対向変電所のOSM欠測 — 図の飾りではなくデータの正直な状態表示", {
    x: 0.66, y: 6.75, w: 12.2, h: 0.4, fontFace: F, fontSize: 11.5,
    color: MUT, margin: 0 });
}

// ---------------- 10. まとめ ----------------
{
  const s = pres.addSlide(); base(s);
  s.addImage({ path: "assets/geo_zukeran.png", x: 0, y: 0, w: 13.33, h: 7.5,
    sizing: { type: "cover", w: 13.33, h: 7.5 }, transparency: 92 });
  chips(s, 0.7, 0.75, true);
  s.addText("変電所の中身は、公開データと\n根拠付き抽出だけで全国一括「見える化」できる", {
    x: 0.66, y: 2.35, w: 12.2, h: 2.0, fontFace: F, fontSize: 34, bold: true,
    color: TXT, lineSpacing: 52, margin: 0 });
  s.addText("docs/SUBSLD_METHOD.md ・ issue #49 ・ data/subsld(全国ギャラリー)", {
    x: 0.68, y: 5.3, w: 12.0, h: 0.45, fontFace: F, fontSize: 13.5,
    color: MUT, margin: 0 });
  s.addText("SubSLD法 — All-Japan-Grid", { x: 0.68, y: 6.7, w: 8, h: 0.35,
    fontFace: F, fontSize: 12, color: YEL, margin: 0 });
}

pres.writeFile({ fileName: "SubSLD_deck.pptx" }).then(() => console.log("written"));
