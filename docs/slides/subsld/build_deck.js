// SubSLD法 デッキ v2 — ダーク基調・衛星ペア図が主役・電圧色チップをモチーフ
const pptxgen = require("pptxgenjs");
const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5

// パレット(コンテンツ由来): 衛星写真の闇 + 電圧階級色 + 敷地黄
const BG = "141417", PANEL = "1F1F26", PANEL2 = "26262E";
const TXT = "F2F1EC", MUT = "9C9AA3", YEL = "FFD54F";
const V500 = "D62728", V275 = "FF7F0E", V154 = "9467BD", V66 = "17BECF";
const CHIPS = [["500kV", V500], ["275kV", V275], ["154kV", V154], ["66kV", V66]];
const F = "Arial";

function base(s) { s.background = { color: BG }; }
function chips(s, x, y, small) {
  const w = small ? 0.72 : 0.92, h = small ? 0.26 : 0.32, gap = 0.12;
  CHIPS.forEach(([lab, col], i) => {
    s.addText(lab, {
      x: x + i * (w + gap), y, w, h, fill: { color: col },
      color: "FFFFFF", fontSize: small ? 10 : 12, bold: true,
      fontFace: F, align: "center", valign: "middle", margin: 0,
      rectRadius: 0.05, shape: pres.ShapeType.roundRect,
    });
  });
}
function kicker(s, txt, x, y, w) {
  s.addText(txt, { x, y, w, h: 0.32, fontFace: F, fontSize: 12,
    color: MUT, charSpacing: 2, margin: 0 });
}

// ---------------- 1. タイトル ----------------
{
  const s = pres.addSlide(); base(s);
  s.addImage({ path: "assets/hero_geo.png", x: 7.6, y: 0, w: 5.73, h: 7.5,
    sizing: { type: "cover", w: 5.73, h: 7.5 } });
  // 画像左端を溶かすグラデ代わりの帯
  s.addShape(pres.ShapeType.rect, { x: 7.35, y: 0, w: 0.5, h: 7.5,
    fill: { color: BG, transparency: 35 }, line: { type: "none" } });
  kicker(s, "ALL-JAPAN-GRID  /  2026-08-26", 0.7, 0.85, 6.2);
  s.addText("SubSLD法", { x: 0.62, y: 1.5, w: 6.6, h: 1.5, fontFace: F,
    fontSize: 66, bold: true, color: TXT, margin: 0 });
  s.addText("実証ペア図法 — 変電所構成の全国機械生成", {
    x: 0.66, y: 3.05, w: 6.6, h: 0.6, fontFace: F, fontSize: 21,
    color: YEL, margin: 0 });
  chips(s, 0.66, 3.95, false);
  s.addText([
    { text: "OSM = 正・捏造ゼロ・全端子に根拠。", options: { breakLine: true } },
    { text: "衛星写真の上の構内幾何と、単線結線図のペアで全国6,956変電所を描く。",
      options: {} },
  ], { x: 0.66, y: 4.75, w: 6.3, h: 1.2, fontFace: F, fontSize: 15,
    color: TXT, lineSpacing: 24, margin: 0 });
  s.addText("Evidence-Paired Substation Single-Line Diagramming", {
    x: 0.66, y: 6.75, w: 6.4, h: 0.3, fontFace: F, fontSize: 11,
    color: MUT, italic: false, margin: 0 });
  s.addNotes("SubSLD法の表紙。右は新京葉変電所のGeoPane(実出力)。");
}

// ---------------- 2. 問い ----------------
{
  const s = pres.addSlide(); base(s);
  kicker(s, "01  MOTIVATION", 0.7, 0.5, 5);
  s.addText("変電所の中身を、公開データだけで描けるか", {
    x: 0.66, y: 0.9, w: 12.0, h: 0.75, fontFace: F, fontSize: 30, bold: true,
    color: TXT, margin: 0 });
  const rows = [
    ["非公開の壁", "系統解析に要る変電所内部(母線・変圧器・回線)は事業者資料で、研究には使えない"],
    ["手作業の実証", "嶺南変電所1所でOSM実データから node-breaker 構造を手作業で確認できた(2026-07)"],
    ["機械化の問い", "同じことを全国6,956所へ。ただし捏造ゼロ — 証拠が無い値は埋めない"],
  ];
  rows.forEach(([h, b], i) => {
    const y = 2.0 + i * 1.55;
    s.addShape(pres.ShapeType.ellipse, { x: 0.66, y: y + 0.06, w: 0.52, h: 0.52,
      fill: { color: [V500, V154, V66][i] }, line: { type: "none" } });
    s.addText(String(i + 1), { x: 0.66, y: y + 0.06, w: 0.52, h: 0.52,
      fontFace: F, fontSize: 18, bold: true, color: "FFFFFF",
      align: "center", valign: "middle", margin: 0 });
    s.addText(h, { x: 1.42, y, w: 5.0, h: 0.4, fontFace: F, fontSize: 18,
      bold: true, color: TXT, margin: 0 });
    s.addText(b, { x: 1.42, y: y + 0.44, w: 5.4, h: 0.9, fontFace: F,
      fontSize: 13.5, color: MUT, lineSpacing: 19, margin: 0 });
  });
  s.addShape(pres.ShapeType.roundRect, { x: 7.35, y: 1.95, w: 5.3, h: 4.7,
    fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.08 });
  s.addImage({ path: "assets/g3.png", x: 7.55, y: 2.15, w: 4.9, h: 3.85,
    sizing: { type: "contain", w: 4.9, h: 3.85 } });
  s.addText("人吉変電所(九州・220/110/66kV) — 手作業ゼロで生成された実出力", {
    x: 7.55, y: 6.1, w: 4.9, h: 0.4, fontFace: F, fontSize: 11.5,
    color: MUT, align: "center", margin: 0 });
}

// ---------------- 3. 方針引用 ----------------
{
  const s = pres.addSlide(); base(s);
  chips(s, 0.7, 0.65, true);
  s.addText("“", { x: 0.5, y: 1.2, w: 1.4, h: 1.4, fontFace: "Times New Roman",
    fontSize: 120, color: YEL, margin: 0 });
  s.addText("線は基本変電所に入る。\n変電所で電圧階級・タップ・回線・導体を接続する。\nそこから負荷に分配供給されるからである。", {
    x: 1.6, y: 2.1, w: 10.2, h: 2.6, fontFace: F, fontSize: 28, bold: true,
    color: TXT, lineSpacing: 44, margin: 0 });
  s.addText("設計方針(2026-07-02) — GridStitch P2 の憲法。SubSLD法はこの一文の全国機械化である。", {
    x: 1.62, y: 5.3, w: 10.2, h: 0.5, fontFace: F, fontSize: 14,
    color: MUT, margin: 0 });
}

// ---------------- 4. 3段パイプライン ----------------
{
  const s = pres.addSlide(); base(s);
  kicker(s, "02  PIPELINE", 0.7, 0.5, 5);
  s.addText("3段パイプライン — 抽出・集約・描画", { x: 0.66, y: 0.9, w: 11.5,
    h: 0.7, fontFace: F, fontSize: 30, bold: true, color: TXT, margin: 0 });
  const cards = [
    ["1  抽出", "GridStitch P2", "OSMの実証拠(頂点共有・ポリゴン内包・lead-in)だけで node-breaker 構造DBを生成", "全国 6,956所 / 約4秒", V500],
    ["2  集約", "プロパティ層", "線タグ(circuits / wires / cables)を terminal に突き合わせ、変電所単位の回線数・導体数に", "5,920サイト(重複統合後)", V154],
    ["3  描画", "SubSLD", "GeoPane(衛星+構内幾何) × SLDPane(単線結線図) の実証ペア図PNG", "約6秒 / 所", V66],
  ];
  cards.forEach(([num, name, body, stat, col], i) => {
    const x = 0.66 + i * 4.24;
    s.addShape(pres.ShapeType.roundRect, { x, y: 2.0, w: 3.85, h: 4.2,
      fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.09 });
    s.addText(num, { x: x + 0.3, y: 2.3, w: 3.2, h: 0.4, fontFace: F,
      fontSize: 13, bold: true, color: col, charSpacing: 3, margin: 0 });
    s.addText(name, { x: x + 0.3, y: 2.72, w: 3.3, h: 0.55, fontFace: F,
      fontSize: 23, bold: true, color: TXT, margin: 0 });
    s.addText(body, { x: x + 0.3, y: 3.45, w: 3.25, h: 1.7, fontFace: F,
      fontSize: 13.5, color: MUT, lineSpacing: 20, margin: 0 });
    s.addText(stat, { x: x + 0.3, y: 5.45, w: 3.25, h: 0.45, fontFace: F,
      fontSize: 14, bold: true, color: col, margin: 0 });
    if (i < 2) s.addText("→", { x: x + 3.82, y: 3.7, w: 0.5, h: 0.6,
      fontFace: F, fontSize: 28, color: MUT, align: "center", margin: 0 });
  });
  s.addText("全生成物は OSM + 構造DB から決定的に再生成できる(D層)", {
    x: 0.66, y: 6.6, w: 12, h: 0.4, fontFace: F, fontSize: 12.5,
    color: MUT, margin: 0 });
}

// ---------------- 5. 実証ペア図の解剖 ----------------
{
  const s = pres.addSlide(); base(s);
  kicker(s, "03  THE PAIR FIGURE", 0.7, 0.4, 6);
  s.addText("実証ペア図 — 新京葉変電所", { x: 0.66, y: 0.78, w: 8.5, h: 0.6,
    fontFace: F, fontSize: 26, bold: true, color: TXT, margin: 0 });
  s.addShape(pres.ShapeType.roundRect, { x: 0.55, y: 1.5, w: 8.9, h: 5.65,
    fill: { color: "FFFFFF" }, line: { type: "none" }, rectRadius: 0.06 });
  s.addImage({ path: "assets/pair_full.png", x: 0.7, y: 1.62, w: 8.6, h: 5.4,
    sizing: { type: "contain", w: 8.6, h: 5.4 } });
  const notes = [
    ["GeoPane(左)", "地理院写真+敷地黄縁+母線の電圧色+鉄塔▲+ズームインセット", YEL],
    ["SLDPane(右)", "母線=太い水平線。線は実接着セクションに刺さる", V275],
    ["回線・導体", "平行ストローク本数=回線数。導体数はタグ注記", V66],
    ["流向と変換", "上=流入・下=流出(推定・矢印)。二重円=変圧器、無い階級は「スルー」", V154],
  ];
  notes.forEach(([h, b], i) => {
    const y = 1.55 + i * 1.42;
    s.addShape(pres.ShapeType.rect, { x: 9.75, y: y + 0.05, w: 0.16, h: 0.16,
      fill: { color: notes[i][2] }, line: { type: "none" } });
    s.addText(h, { x: 10.02, y, w: 3.0, h: 0.35, fontFace: F, fontSize: 15,
      bold: true, color: TXT, margin: 0 });
    s.addText(b, { x: 10.02, y: y + 0.38, w: 3.05, h: 0.95, fontFace: F,
      fontSize: 12, color: MUT, lineSpacing: 17, margin: 0 });
  });
}

// ---------------- 6. ギャラリー ----------------
{
  const s = pres.addSlide(); base(s);
  kicker(s, "04  EVERYWHERE, SAME PIPELINE", 0.7, 0.4, 6);
  s.addText("全国どこでも同じ品質 — 10地域で検証", { x: 0.66, y: 0.78, w: 11,
    h: 0.6, fontFace: F, fontSize: 26, bold: true, color: TXT, margin: 0 });
  const gs = [
    ["assets/g1.png", "南早来(北海道) 275/187/66"],
    ["assets/g2.png", "駿遠(中部) 500/275/154/77"],
    ["assets/g3.png", "人吉(九州) 220/110/66"],
    ["assets/g4.png", "瑞慶覧(沖縄) 132/66"],
  ];
  gs.forEach(([p, cap], i) => {
    const x = 0.66 + (i % 2) * 6.2, y = 1.55 + Math.floor(i / 2) * 2.85;
    s.addShape(pres.ShapeType.roundRect, { x, y, w: 6.0, h: 2.7,
      fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.06 });
    s.addImage({ path: p, x: x + 0.12, y: y + 0.12, w: 4.55, h: 2.46,
      sizing: { type: "cover", w: 4.55, h: 2.46 } });
    s.addText(cap, { x: x + 4.75, y: y + 0.25, w: 1.2, h: 2.3, fontFace: F,
      fontSize: 11.5, bold: true, color: TXT, margin: 0, valign: "top" });
  });
}

// ---------------- 7. 数字とチャート ----------------
{
  const s = pres.addSlide(); base(s);
  kicker(s, "05  COVERAGE", 0.7, 0.4, 5);
  s.addText("被覆と正直な限界", { x: 0.66, y: 0.78, w: 8, h: 0.6, fontFace: F,
    fontSize: 26, bold: true, color: TXT, margin: 0 });
  const stats = [
    ["6,956", "対象変電所(全国)", TXT],
    ["68%", "回線数のOSM証拠被覆", V66],
    ["14%", "母線wayの記載率 — 最大の欠測(issue #49)", V500],
  ];
  stats.forEach(([v, l, c], i) => {
    const y = 1.7 + i * 1.75;
    s.addText(v, { x: 0.66, y, w: 3.4, h: 0.95, fontFace: F, fontSize: 54,
      bold: true, color: c, margin: 0 });
    s.addText(l, { x: 0.7, y: y + 0.98, w: 3.6, h: 0.55, fontFace: F,
      fontSize: 12.5, color: MUT, lineSpacing: 16, margin: 0 });
  });
  s.addChart(pres.ChartType.bar, [{
    name: "母線way記載率",
    labels: ["北海道", "東北", "北陸", "四国", "中国", "中部", "九州", "関西", "沖縄", "東京"],
    values: [53, 25, 25, 12, 11, 10, 10, 8, 5, 5],
  }], {
    x: 4.9, y: 1.55, w: 7.8, h: 5.3, barDir: "bar",
    chartColors: [YEL], showLegend: false,
    showTitle: true, title: "母線way記載率(%) — OSMマッピング粒度の地域差",
    titleColor: TXT, titleFontSize: 13, titleFontFace: F,
    showValue: true, dataLabelPosition: "outEnd", dataLabelColor: TXT,
    dataLabelFontSize: 10, dataLabelFontFace: F,
    catAxisLabelColor: TXT, catAxisLabelFontSize: 11, catAxisLabelFontFace: F,
    valAxisLabelColor: MUT, valAxisLabelFontSize: 10, valAxisLabelFontFace: F,
    valGridLine: { color: "3A3A44", size: 0.5 },
    catGridLine: { style: "none" },
    valAxisMaxVal: 60, plotArea: { fill: { color: BG } },
    chartArea: { fill: { color: BG } },
  });
}

// ---------------- 8. 不変条件 ----------------
{
  const s = pres.addSlide(); base(s);
  kicker(s, "06  INVARIANTS", 0.7, 0.4, 5);
  s.addText("不変条件 — 憲法に従う", { x: 0.66, y: 0.78, w: 9, h: 0.6,
    fontFace: F, fontSize: 26, bold: true, color: TXT, margin: 0 });
  const inv = [
    ["捏造ゼロ", "接続は実証拠のみ。タグの無い回線数・導体数・銘板は unknown のまま見せる", V500],
    ["全端子に根拠", "vertex-shared / polygon / leadin / name-evidence を端子ごとに刻む", V275],
    ["推定は推定と明記", "流向(入/出)は対向変電所の電圧階層による推定。凡例に明記し断定しない", V154],
    ["決定的に再生成", "同一入力から同一出力。OSM更新に全所が追随できる", V66],
  ];
  inv.forEach(([h, b, c], i) => {
    const x = 0.66 + (i % 2) * 6.2, y = 1.7 + Math.floor(i / 2) * 2.5;
    s.addShape(pres.ShapeType.roundRect, { x, y, w: 6.0, h: 2.25,
      fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.09 });
    s.addShape(pres.ShapeType.rect, { x: x + 0.32, y: y + 0.4, w: 0.2, h: 0.2,
      fill: { color: c }, line: { type: "none" } });
    s.addText(h, { x: x + 0.68, y: y + 0.28, w: 5.0, h: 0.45, fontFace: F,
      fontSize: 18, bold: true, color: TXT, margin: 0 });
    s.addText(b, { x: x + 0.68, y: y + 0.82, w: 5.0, h: 1.2, fontFace: F,
      fontSize: 13, color: MUT, lineSpacing: 19, margin: 0 });
  });
}

// ---------------- 9. 全所展開 ----------------
{
  const s = pres.addSlide(); base(s);
  kicker(s, "07  ROLLOUT", 0.7, 0.4, 5);
  s.addText("全所展開 — 実行中", { x: 0.66, y: 0.78, w: 9, h: 0.6, fontFace: F,
    fontSize: 26, bold: true, color: TXT, margin: 0 });
  const steps = [
    ["バッチ生成", "全6,956所を一括描画。再開可能・タイルはキャッシュ+礼儀スロットル", "実行中(160core並列)"],
    ["全国ギャラリー", "検索付きHTMLで全所を閲覧", "バッチ完走後に生成"],
    ["editor統合", "地図の変電所クリックでSubSLDをその場表示", "計画"],
    ["OSM貢献ループ", "母線なし所の調査(issue #49)→衛星判読→OSM編集候補へ", "計画"],
  ];
  steps.forEach(([h, b, st], i) => {
    const y = 1.75 + i * 1.25;
    s.addShape(pres.ShapeType.ellipse, { x: 0.7, y: y + 0.04, w: 0.46, h: 0.46,
      fill: { color: i === 0 ? YEL : PANEL2 }, line: { type: "none" } });
    s.addText(String(i + 1), { x: 0.7, y: y + 0.04, w: 0.46, h: 0.46,
      fontFace: F, fontSize: 15, bold: true,
      color: i === 0 ? "141417" : MUT,
      align: "center", valign: "middle", margin: 0 });
    if (i < 3) s.addShape(pres.ShapeType.rect, { x: 0.91, y: y + 0.55,
      w: 0.03, h: 0.75, fill: { color: PANEL2 }, line: { type: "none" } });
    s.addText(h, { x: 1.4, y, w: 3.4, h: 0.45, fontFace: F, fontSize: 17,
      bold: true, color: TXT, margin: 0 });
    s.addText(b, { x: 4.9, y, w: 5.6, h: 0.9, fontFace: F,
      fontSize: 13, color: MUT, lineSpacing: 18, margin: 0 });
    s.addText(st, { x: 10.6, y, w: 2.4, h: 0.6, fontFace: F,
      fontSize: 11.5, bold: true, color: i === 0 ? YEL : MUT, margin: 0 });
  });
}

// ---------------- 10. まとめ ----------------
{
  const s = pres.addSlide(); base(s);
  chips(s, 0.7, 0.7, true);
  s.addText("変電所の中身は、\n公開データと根拠付き抽出だけで\n全国一括「見える化」できる", {
    x: 0.66, y: 2.0, w: 12.0, h: 2.8, fontFace: F, fontSize: 38, bold: true,
    color: TXT, lineSpacing: 56, margin: 0 });
  s.addText("docs/SUBSLD_METHOD.md   ·   issue #49(母線なし86%の調査)   ·   data/subsld(全国ギャラリー)", {
    x: 0.68, y: 5.6, w: 12.0, h: 0.45, fontFace: F, fontSize: 14,
    color: MUT, margin: 0 });
  s.addText("SubSLD法 — All-Japan-Grid", { x: 0.68, y: 6.7, w: 8, h: 0.35,
    fontFace: F, fontSize: 12, color: YEL, margin: 0 });
}

pres.writeFile({ fileName: "SubSLD_deck.pptx" }).then(() => console.log("written"));
