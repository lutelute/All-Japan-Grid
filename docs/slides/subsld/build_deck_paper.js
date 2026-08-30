// SubSLD 論文発表デッキ（IEEEtran 6ページ論文の15分トーク）
//
// 構成はワークフロー（3案 × 3観点の判定パネル → 統合）の勝ち案。
// 背骨は「完全性を主張せず測定する」。S6 でヒンジを打ち、S11-S12 で回収し、
// S14 の結論で同じ弧を閉じる。S4 で現物を先出しして視覚文法を先に渡す。
//
// 数値衛生（実装時の必須ルール。破ると論旨が弱る）:
//   1. 同じ数値を2枚に出さない（変圧器は S13 に一本化、流向%は S11 に集約）
//   2. Table II 系（S10）と Table III 系（S13）を同じ枚に並べない
//   3. 論文本文にある数値のみ。図の中の値は図に語らせ、再プロットしない
//   4. 開閉器・ループ・2ロールは論文未収載 → 予備 S16 に隔離
//
// 本編14枚で 15:00 ちょうど。S15/S16 は質疑用（配分ゼロ）。
const pptxgen = require("pptxgenjs");
const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5

const BG = "FFFFFF", INK = "1A1A1A", MUT = "55555F", NAVY = "1E2761";
const PANEL = "F4F4F6", CODE = "F7F7F2", RED = "C62828", GRN = "2E7D32";
const V500 = "D62728", V275 = "FF7F0E", V154 = "9467BD", V66 = "17BECF";
const F = "Hiragino Sans", FM = "Courier New", FL = "Helvetica Neue";
const A = "assets/";

function base(s) { s.background = { color: BG }; }

// 見出し。sec は論文の節番号バッジ（出典追跡性・案Aから移植）
function head(s, sec, title, sub) {
  if (sec) {
    s.addShape(pres.ShapeType.roundRect, { x: 0.68, y: 0.38, w: 1.15, h: 0.3,
      fill: { color: NAVY }, line: { type: "none" }, rectRadius: 0.05 });
    s.addText(sec, { x: 0.68, y: 0.38, w: 1.15, h: 0.3, fontFace: FL,
      fontSize: 11, bold: true, color: "FFFFFF", align: "center",
      valign: "middle", margin: 0 });
  }
  s.addText(title, { x: sec ? 1.98 : 0.66, y: 0.34, w: 10.6, h: 0.42,
    fontFace: F, fontSize: 22, bold: true, color: INK, margin: 0,
    valign: "middle" });
  if (sub) {
    s.addText(sub, { x: 0.68, y: 0.8, w: 12.0, h: 0.32, fontFace: F,
      fontSize: 12, color: MUT, margin: 0 });
  }
}
function foot(s, n, mins) {
  s.addText("SubSLD — All-Japan-Grid", { x: 0.7, y: 7.12, w: 6, h: 0.28,
    fontFace: FL, fontSize: 9, color: MUT, margin: 0 });
  if (mins) s.addText(mins, { x: 10.6, y: 7.12, w: 1.6, h: 0.28,
    fontFace: FL, fontSize: 9, color: MUT, align: "right", margin: 0 });
  s.addText(String(n), { x: 12.4, y: 7.12, w: 0.5, h: 0.28, fontFace: FL,
    fontSize: 10, color: MUT, align: "right", margin: 0 });
}
// 数式: Cambria Math + 実下付き（画像にしない＝編集可能）
function meq(s, x, y, w, runs, fs, align) {
  s.addText(runs.map(([t, o]) => {
    o = o || {};
    return { text: t, options: {
      fontFace: o.jp ? F : "Cambria Math", italic: !!o.i,
      subscript: !!o.sub, superscript: !!o.sup,
      color: o.c || INK, fontSize: o.fs || fs || 18 } };
  }), { x, y, w, h: 0.5, margin: 0, valign: "middle",
    align: align || "left" });
}
function card(s, x, y, w, h, title, body, col, fs) {
  s.addShape(pres.ShapeType.roundRect, { x, y, w, h, fill: { color: PANEL },
    line: { type: "none" }, rectRadius: 0.06 });
  if (col) s.addShape(pres.ShapeType.rect, { x: x + 0.22, y: y + 0.2,
    w: 0.14, h: 0.14, fill: { color: col }, line: { type: "none" } });
  s.addText(title, { x: x + (col ? 0.46 : 0.24), y: y + 0.1, w: w - 0.6,
    h: 0.34, fontFace: F, fontSize: fs || 13, bold: true, color: INK,
    margin: 0, valign: "middle" });
  s.addText(body, { x: x + 0.24, y: y + 0.48, w: w - 0.48, h: h - 0.6,
    fontFace: F, fontSize: (fs || 13) - 2, color: MUT, lineSpacing: 16,
    margin: 0, valign: "top" });
}

/* ===================== 1. タイトル ===================== */
{
  const s = pres.addSlide(); base(s);
  s.addText("SubSLD：公開地理データから変電所の中を描く", {
    x: 0.9, y: 1.05, w: 11.6, h: 0.9, fontFace: F, fontSize: 32, bold: true,
    color: INK, margin: 0 });
  s.addText("SubSLD: Evidence-Paired Generation of Substation Single-Line\nDiagrams from Volunteered Geographic Information", {
    x: 0.93, y: 2.05, w: 11.5, h: 0.85, fontFace: FL, fontSize: 15,
    italic: true, color: NAVY, lineSpacing: 22, margin: 0 });
  s.addText("Ryuto Shigenobu　—　University of Fukui, Dept. of Electrical, Electronic and Computer Engineering", {
    x: 0.93, y: 3.05, w: 11.5, h: 0.35, fontFace: F, fontSize: 12.5,
    color: MUT, margin: 0 });
  s.addText("OSM を正とし、根拠のある要素だけを出す。", {
    x: 0.93, y: 3.55, w: 11.5, h: 0.4, fontFace: F, fontSize: 15,
    color: INK, margin: 0 });
  s.addImage({ path: A + "title_strip.png", x: 0, y: 4.55, w: 13.33, h: 2.95 });
  s.addShape(pres.ShapeType.rect, { x: 0, y: 4.55, w: 13.33, h: 2.95,
    fill: { color: "000000", transparency: 78 }, line: { type: "none" } });
  s.addText("GeoPane（駿遠変電所・500/275/154/77 kV）— OSM の証拠を地理院写真に重畳した実出力", {
    x: 0.7, y: 6.98, w: 11, h: 0.32, fontFace: F, fontSize: 10.5,
    color: "FFFFFF", margin: 0 });
  s.addNotes("タイトルと所属だけ読み、すぐ次へ。数値は一切言わない。0:30");
}

/* ===================== 2. 問題 ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "§I", "公開送電網モデルは変電所の「柵」で止まる");
  // 左: 従来モデル
  s.addText("従来の公開モデル", { x: 0.9, y: 1.15, w: 5, h: 0.32, fontFace: F,
    fontSize: 13, bold: true, color: MUT, margin: 0 });
  s.addShape(pres.ShapeType.ellipse, { x: 2.35, y: 2.1, w: 0.78, h: 0.78,
    fill: { color: "9A9AA6" }, line: { type: "none" } });
  [[1.0, 1.6], [1.0, 3.4], [4.5, 1.6], [4.5, 3.4]].forEach(([x, y]) =>
    s.addShape(pres.ShapeType.line, { x: Math.min(x, 2.74), y: Math.min(y, 2.49),
      w: Math.abs(2.74 - x), h: Math.abs(2.49 - y),
      flipH: x > 2.74, flipV: y > 2.49,
      line: { color: "9A9AA6", width: 1.6 } }));
  s.addText("変電所 = 1ノード", { x: 1.45, y: 3.0, w: 2.6, h: 0.3, fontFace: F,
    fontSize: 11, color: MUT, align: "center", margin: 0 });
  // 右: node-breaker
  s.addText("本研究が出すもの（node-breaker）", { x: 7.0, y: 1.15, w: 5.6,
    h: 0.32, fontFace: F, fontSize: 13, bold: true, color: NAVY, margin: 0 });
  s.addShape(pres.ShapeType.line, { x: 7.2, y: 1.95, w: 4.4, h: 0,
    line: { color: V500, width: 4 } });
  s.addShape(pres.ShapeType.line, { x: 7.2, y: 3.15, w: 4.4, h: 0,
    line: { color: V66, width: 4 } });
  [7.7, 9.1, 10.6].forEach(x => s.addShape(pres.ShapeType.line,
    { x, y: 1.5, w: 0, h: 0.45, line: { color: V500, width: 1.5 } }));
  [8.2, 10.0].forEach(x => s.addShape(pres.ShapeType.line,
    { x, y: 3.15, w: 0, h: 0.45, line: { color: V66, width: 1.5 } }));
  s.addShape(pres.ShapeType.line, { x: 11.9, y: 1.95, w: 0, h: 1.2,
    line: { color: "444444", width: 1.4 } });
  [2.35, 2.62].forEach(y => s.addShape(pres.ShapeType.ellipse,
    { x: 11.76, y, w: 0.28, h: 0.28, fill: { type: "none" },
      line: { color: "444444", width: 1.4 } }));
  s.addText("母線区分・ベイ・端子の根拠・回線数・変圧器", { x: 7.0, y: 3.75,
    w: 5.6, h: 0.3, fontFace: F, fontSize: 11, color: MUT, margin: 0 });

  s.addText([
    { text: "できないこと：", options: { bold: true, color: INK } },
    { text: "(1) bus-splitting　(2) 遮断器レベルの事故時解析　(3) ベイ単位のホスティングキャパシティ", options: { color: MUT } },
  ], { x: 0.9, y: 4.35, w: 11.6, h: 0.35, fontFace: F, fontSize: 12.5, margin: 0 });
  s.addText("加えて、ノードと枝だけで描くと「その表現がどれだけ強い証拠に立っているか」自体が見えない。", {
    x: 0.9, y: 4.75, w: 11.6, h: 0.35, fontFace: F, fontSize: 12.5,
    color: MUT, margin: 0 });

  s.addText("出発点：変電所の中は、公開データに部分的に写っている", { x: 0.9,
    y: 5.35, w: 11.6, h: 0.35, fontFace: F, fontSize: 14, bold: true,
    color: NAVY, margin: 0 });
  [["航空写真", "屋外母線とベイ列が写る"],
   ["OSM 変電所ポリゴン", "敷地の外形"],
   ["OSM 構内way・線路タグ", "line=busbar / bay、circuits・cables・wires"]]
    .forEach(([t, b], i) => card(s, 0.9 + i * 3.9, 5.78, 3.6, 0.95, t, b, NAVY, 12));
  foot(s, 2, "1:00");
  s.addNotes("公開モデルは柵の外まで。中は事業者図面。だからこの3つができない。右へ振って「しかし中は公開データに写っている」。");
}

/* ===================== 3. 道筋（結論先出し＋スコープ線引き） ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "§I", "本発表の道筋：中を出す → 測る → 標準で渡す");
  s.addText("変電所の中は、根拠のある要素しか出さない抽出だけで全国分描ける。\n描けなかった所こそが、次に何をマップすべきかを教える。", {
    x: 0.9, y: 1.2, w: 11.6, h: 0.95, fontFace: F, fontSize: 19, bold: true,
    color: INK, lineSpacing: 30, margin: 0 });
  const steps = [
    ["①", "抽出", "OSM＋航空写真から\nnode-breaker 構造", NAVY],
    ["②", "測る", "どこまで見えたかを\n被覆として報告", NAVY],
    ["③", "渡す", "CIM/CGMES へ\n直接シリアライズ", NAVY],
    ["④", "運用に触る", "開閉器・ループ・2ロール", "B9B9C2"],
  ];
  steps.forEach(([n, t, b, col], i) => {
    const x = 0.9 + i * 3.05;
    s.addShape(pres.ShapeType.roundRect, { x, y: 2.5, w: 2.8, h: 1.5,
      fill: { color: col }, line: { type: "none" }, rectRadius: 0.08 });
    s.addText(n + "  " + t, { x: x + 0.2, y: 2.62, w: 2.4, h: 0.35,
      fontFace: F, fontSize: 14, bold: true,
      color: col === NAVY ? "FFFFFF" : "3A3A44", margin: 0 });
    s.addText(b, { x: x + 0.2, y: 3.0, w: 2.45, h: 0.85, fontFace: F,
      fontSize: 11.5, color: col === NAVY ? "E8E8F0" : "55555F",
      lineSpacing: 15, margin: 0 });
    if (i < 3) s.addText("→", { x: x + 2.62, y: 3.05, w: 0.45, h: 0.4,
      fontFace: FL, fontSize: 20, color: MUT, align: "center", margin: 0 });
  });
  s.addShape(pres.ShapeType.roundRect, { x: 10.6, y: 2.36, w: 2.2, h: 0.3,
    fill: { color: RED }, line: { type: "none" }, rectRadius: 0.05 });
  s.addText("本稿の先（予備 S16）", { x: 10.6, y: 2.36, w: 2.2, h: 0.3,
    fontFace: F, fontSize: 10, bold: true, color: "FFFFFF", align: "center",
    valign: "middle", margin: 0 });
  s.addText("①②③ が本稿の範囲", { x: 0.9, y: 4.15, w: 8, h: 0.3, fontFace: F,
    fontSize: 11.5, color: MUT, margin: 0 });

  s.addShape(pres.ShapeType.roundRect, { x: 0.9, y: 4.85, w: 11.6, h: 1.5,
    fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.07 });
  s.addText("設計原則", { x: 1.2, y: 5.0, w: 4, h: 0.32, fontFace: F,
    fontSize: 13, bold: true, color: NAVY, margin: 0 });
  s.addText([
    { text: "健全性（捏造ゼロ）は構成的に成立させる", options: { bold: true, breakLine: true } },
    { text: "完全性は主張せず測定する", options: { bold: true } },
  ], { x: 1.2, y: 5.42, w: 11, h: 0.8, fontFace: F, fontSize: 15,
    color: INK, lineSpacing: 24, margin: 0 });
  foot(s, 3, "0:45");
  s.addNotes("結論を先に言う。④は論文に載っていないと最初に宣言し、以後この線引きの質問を発生させない。");
}

/* ===================== 4. 現物先出し ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "§VII", "まず現物：実証ペア図（新京葉・500/275/154/66 kV）");
  s.addImage({ path: A + "geo_shinkeiyo.png", x: 0.85, y: 1.25, w: 4.66,
    h: 4.98 });
  s.addShape(pres.ShapeType.roundRect, { x: 6.05, y: 1.25, w: 6.45, h: 4.98,
    fill: { color: "FBFBF9" }, line: { color: "E3E3E8", width: 0.8 },
    rectRadius: 0.05 });
  s.addImage({ path: A + "sld_shinkeiyo.png", x: 7.05, y: 1.37, w: 3.75,
    h: 4.74 });
  s.addText("(a) GeoPane — 構内幾何・端子の根拠", { x: 0.85, y: 6.3, w: 4.7,
    h: 0.3, fontFace: F, fontSize: 11, color: MUT, margin: 0 });
  s.addText("(b) SLDPane — 同じ証拠の電気的な読み", { x: 6.05, y: 6.3, w: 5,
    h: 0.3, fontFace: F, fontSize: 11, color: MUT, margin: 0 });
  // 視覚文法（ここで教え切る）
  s.addShape(pres.ShapeType.roundRect, { x: 10.95, y: 1.45, w: 1.45, h: 1.5,
    fill: { color: "FFFFFF", transparency: 8 }, line: { color: "E3E3E8", width: 0.8 },
    rectRadius: 0.05 });
  s.addText([
    { text: "視覚文法", options: { bold: true, breakLine: true, fontSize: 10 } },
    { text: "破線＝弱い証拠", options: { breakLine: true, fontSize: 9 } },
    { text: "灰＝棄権", options: { breakLine: true, fontSize: 9 } },
    { text: "破線母線＝推定", options: { fontSize: 9 } },
  ], { x: 11.05, y: 1.55, w: 1.3, h: 1.3, fontFace: F, color: INK,
    lineSpacing: 13, margin: 0 });
  s.addText("左は監査面 — どの線路の話で、どれだけ強く接続されているかが見える。右は同じ証拠の電気的な読み取り。", {
    x: 0.85, y: 6.65, w: 11.7, h: 0.32, fontFace: F, fontSize: 12,
    color: INK, margin: 0 });
  foot(s, 4, "1:20");
  s.addNotes("先に現物。以降の説明は全部「この1枚をなぜ信じてよいか」の話。●■▲を指して『証拠の強さが線の描き方に出ている』を1回だけ言い切る。");
}

/* ============ 4.5 動: 読み方と全国展開(GIF) ============ */
{
  const s = pres.addSlide();
  s.background = { color: "0A0D1A" };
  s.addImage({ path: A + "subsld_flipbook.gif", x: 0.17, y: 0, w: 13.0, h: 7.5 });
  s.addNotes("動きで読み方を3段(左=構内幾何/右=SLD/捏造ゼロ)→全国406所の機械生成を流す。新京葉の次に『これが1所ではない』ことを見せる。0:45");
}

/* ===================== 5. 関連研究 ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "§II", "位置づけ：変電所を「1ノード」に畳むか、中身を出すか");
  const rows = [
    ["大陸/国スケール抽出\n(SciGRID, PyPSA-Eur ほか)", "単一ノードに抽象化", "内部が現れる場合も\n「抽出」ではなく「仮定」", "なし"],
    ["航空写真からの設備検出\n(TTPLA ほか)", "対象外（線路・鉄塔）", "画像からの自動検出", "検出器としては使わず\n人手トリアージの経路"],
    ["SubSLD（本研究）", "内部構造を抽出", "OSM 構内way＋タグの実証拠", "要素ごとに provenance"],
  ];
  const cols = [3.5, 2.5, 3.2, 2.9], x0 = 0.9;
  ["", "変電所の扱い", "内部構造の出所", "要素ごとの根拠"].forEach((h, j) => {
    let x = x0; for (let k = 0; k < j; k++) x += cols[k];
    s.addText(h, { x: x + 0.12, y: 1.35, w: cols[j] - 0.2, h: 0.3, fontFace: F,
      fontSize: 11, bold: true, color: NAVY, margin: 0 });
  });
  rows.forEach((r, i) => {
    const y = 1.75 + i * 1.2, last = i === 2;
    s.addShape(pres.ShapeType.rect, { x: x0, y, w: cols.reduce((a, b) => a + b),
      h: 1.1, fill: { color: last ? NAVY : (i % 2 ? "FFFFFF" : PANEL) },
      line: { type: "none" } });
    r.forEach((c, j) => {
      let x = x0; for (let k = 0; k < j; k++) x += cols[k];
      s.addText(c, { x: x + 0.12, y: y + 0.06, w: cols[j] - 0.24, h: 0.98,
        fontFace: F, fontSize: j === 0 ? 11.5 : 11,
        bold: j === 0, color: last ? "FFFFFF" : INK,
        lineSpacing: 15, margin: 0, valign: "middle" });
    });
  });
  s.addShape(pres.ShapeType.roundRect, { x: 0.9, y: 5.5, w: 11.6, h: 0.6,
    fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.06 });
  s.addText("公開データから全国規模の変電所群に対し、要素ごとの provenance 付き単線結線図を機械生成した先行研究は、著者の知る限り無い。", {
    x: 1.15, y: 5.5, w: 11.1, h: 0.6, fontFace: F, fontSize: 12.5,
    color: INK, margin: 0, valign: "middle" });
  foot(s, 5, "0:45");
  s.addNotes("先行研究は変電所を1ノードに畳む。中身が出る場合もそれは抽出ではなく仮定。TTPLAは検出器ではなく人手トリアージの経路として軽く使う、と1文添える。");
}

/* ===================== 6. 定式化（ヒンジ） ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "§IV", "定式化：抽出は「証拠閉包」作用素");
  s.addImage({ path: A + "fig_concept.png", x: 0.75, y: 1.05, w: 11.8,
    h: 2.14 });
  s.addShape(pres.ShapeType.roundRect, { x: 0.9, y: 3.4, w: 5.6, h: 1.05,
    fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.06 });
  s.addText("Definition 1（証拠閉包）", { x: 1.1, y: 3.48, w: 5, h: 0.28,
    fontFace: F, fontSize: 11.5, bold: true, color: NAVY, margin: 0 });
  meq(s, 1.1, 3.82, 5.2, [
    ["F", { i: 1 }], ["(", {}], ["O", { i: 1 }], [") = ", {}],
    ["S", { i: 1 }], ["*", { sup: 1 }], [" = { ", {}], ["x", { i: 1 }],
    [" | witnesses(", {}], ["x", { i: 1 }], [", ", {}], ["O", { i: 1 }],
    [") ≠ ∅ }", {}],
  ], 16);
  s.addShape(pres.ShapeType.roundRect, { x: 6.9, y: 3.4, w: 5.6, h: 2.3,
    fill: { color: "FFFFFF" }, line: { color: NAVY, width: 1.2 },
    rectRadius: 0.06 });
  s.addText("命題 1（F の性質）", { x: 7.15, y: 3.5, w: 5, h: 0.3, fontFace: F,
    fontSize: 12.5, bold: true, color: NAVY, margin: 0 });
  [["(i) 決定性", "同一入力から byte-identical（全国テストで検証）"],
   ["(ii) 冪等性", "再適用しても変わらない → 再生成パイプラインに埋め込める"],
   ["(iii) 健全性", "全要素が witness を持つ ＝「捏造ゼロ」の形式的内容"]]
    .forEach(([t, b], i) => {
      s.addText(t, { x: 7.15, y: 3.9 + i * 0.6, w: 1.5, h: 0.28, fontFace: F,
        fontSize: 11.5, bold: true, color: INK, margin: 0 });
      s.addText(b, { x: 8.6, y: 3.9 + i * 0.6, w: 3.75, h: 0.5, fontFace: F,
        fontSize: 10.5, color: MUT, lineSpacing: 13, margin: 0 });
    });
  s.addShape(pres.ShapeType.roundRect, { x: 0.9, y: 4.7, w: 5.6, h: 1.0,
    fill: { color: "FFF3F3" }, line: { color: RED, width: 1.1 },
    rectRadius: 0.06 });
  s.addText("逆の完全性は主張しない。O の被覆に縛られるから。\nだから測って報告する（→ S11）", {
    x: 1.1, y: 4.8, w: 5.2, h: 0.8, fontFace: F, fontSize: 12.5, bold: true,
    color: RED, lineSpacing: 19, margin: 0 });
  foot(s, 6, "1:20");
  s.addNotes("命題1は運用上の意味に翻訳して読む。最後の『完全性は主張しない、だから測る』はゆっくり。ここが後半の受け取り方を決める。");
}

/* ===================== 7. 端子束縛とゲート ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "§IV", "端子束縛：証拠の辞書式最大化と、近さ≠接続のゲート");
  s.addShape(pres.ShapeType.roundRect, { x: 0.9, y: 1.15, w: 6.0, h: 1.85,
    fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.06 });
  meq(s, 1.15, 1.28, 5.6, [
    ["binding(", {}], ["t", { i: 1 }], [") = max", {}], ["≻", { sub: 1 }],
    [" { ", {}], ["e", { i: 1 }], [" | ", {}], ["e", { i: 1 }],
    [" は t の証人 }", { jp: 1, fs: 13 }],
  ], 16);
  meq(s, 1.15, 1.88, 5.6, [["vertex  ≻  polygon  ≻  lead-in", {}]], 15);
  s.addText("頂点共有 ≻ 敷地内包 ≻ 引込帯（δ = 0.6 km）", { x: 1.15, y: 2.35,
    w: 5.6, h: 0.28, fontFace: F, fontSize: 11, color: MUT, margin: 0 });
  s.addText("選ばれた証拠は記録に残る。弱い証拠は弱く描く（lead-in → 破線スタブ）", {
    x: 1.15, y: 2.63, w: 5.6, h: 0.3, fontFace: F, fontSize: 11,
    color: NAVY, margin: 0 });

  s.addText("整合制約：物理的近接は電気的接続ではない", { x: 7.3, y: 1.2,
    w: 5.3, h: 0.3, fontFace: F, fontSize: 12.5, bold: true, color: NAVY,
    margin: 0 });
  s.addShape(pres.ShapeType.roundRect, { x: 7.3, y: 1.55, w: 5.25, h: 0.75,
    fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.06 });
  meq(s, 7.45, 1.6, 5.0, [
    ["admit(", {}], ["ℓ", { i: 1 }], [",", {}], ["n", { i: 1 }],
    [") ⟺ ¬( |", {}], ["kv", { i: 1 }], ["ℓ", { i: 1, sub: 1 }], ["−", {}],
    ["kv", { i: 1 }], ["n", { i: 1, sub: 1 }], ["| > 0.25·max(", {}],
    ["kv", { i: 1 }], ["n", { i: 1, sub: 1 }], [",1) )", {}],
  ], 13);
  const cs = [[GRN, "✓", "ケースA 適合", "66 kV 線 → 66 kV ノード"],
              [RED, "✗", "ケースB 棄却", "66 kV 線 → 154 kV ノード（80 m 以内）"]];
  cs.forEach(([col, mk, t, b], i) => {
    const y = 2.45 + i * 0.85;
    s.addShape(pres.ShapeType.roundRect, { x: 7.3, y, w: 5.25, h: 0.75,
      fill: { color: "FFFFFF" }, line: { color: col, width: 1.1 },
      rectRadius: 0.05 });
    s.addText(mk, { x: 7.45, y, w: 0.4, h: 0.75, fontFace: F, fontSize: 18,
      bold: true, color: col, align: "center", valign: "middle", margin: 0 });
    s.addText(t, { x: 7.95, y: y + 0.08, w: 2.2, h: 0.3, fontFace: F,
      fontSize: 11.5, bold: true, color: col, margin: 0 });
    s.addText(b, { x: 7.95, y: y + 0.38, w: 4.4, h: 0.3, fontFace: F,
      fontSize: 10.5, color: MUT, margin: 0 });
  });
  s.addShape(pres.ShapeType.roundRect, { x: 0.9, y: 4.35, w: 11.6, h: 1.5,
    fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.06 });
  s.addText("ゲートが効いた実例", { x: 1.15, y: 4.5, w: 4, h: 0.3, fontFace: F,
    fontSize: 12.5, bold: true, color: NAVY, margin: 0 });
  s.addText("154 kV ジャンクションに 80 m 以内で接する 66 kV フラグメントを正しく棄却した。後の診断で、そのフラグメント自体が\nクロスリージョン登録アーティファクトだと判明 — ゲートは、真因が別の場所にある誤りを未然に防いだ。", {
    x: 1.15, y: 4.85, w: 11.1, h: 0.85, fontFace: F, fontSize: 12.5,
    color: INK, lineSpacing: 19, margin: 0 });
  foot(s, 7, "1:05");
  s.addNotes("S4 で見た破線スタブはここで決まっている、と現物に戻して繋ぐ。ゲートは実例で締める。");
}

/* ===================== 8. 下界推定 ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "§V", "回線数：埋めずに、証明付きの下界として保証する");
  s.addShape(pres.ShapeType.roundRect, { x: 0.9, y: 1.15, w: 11.6, h: 1.45,
    fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.06 });
  // 場合分けは本物の cases 組み（値の列と条件の列を分ける）
  meq(s, 2.5, 1.62, 1.1, [
    ["ĉ", { i: 1 }], ["(", {}], ["w", { i: 1 }], [") =", {}],
  ], 20, "right");
  s.addText("{", { x: 3.62, y: 1.28, w: 0.4, h: 1.2, fontFace: "Cambria Math",
    fontSize: 44, color: INK, margin: 0, valign: "middle" });
  const cases = [
    [1.22, [["c", { i: 1 }], ["tag", { sub: 1 }], ["(", {}], ["w", { i: 1 }],
            [")", {}]], "circuits タグがある"],
    [1.62, [["⌊", {}], ["n", { i: 1 }], ["cables", { sub: 1 }], ["(", {}],
            ["w", { i: 1 }], [")/3⌋", {}]],
     "circuits が無く cables がある（切り捨て）"],
    [2.02, [["1", {}]], "どちらの証拠も無い（存在の下限）"],
  ];
  cases.forEach(([y, runs, cond]) => {
    meq(s, 3.95, y, 2.5, runs, 18, "left");
    s.addText(cond, { x: 6.7, y: y + 0.1, w: 4.2, h: 0.3, fontFace: F,
      fontSize: 11, color: MUT, margin: 0 });
  });

  s.addShape(pres.ShapeType.roundRect, { x: 0.9, y: 2.72, w: 11.6, h: 2.15,
    fill: { color: "FFFFFF" }, line: { color: NAVY, width: 1.2 },
    rectRadius: 0.06 });
  s.addText("命題 2（下界性）", { x: 1.15, y: 2.84, w: 4, h: 0.3, fontFace: F,
    fontSize: 13, bold: true, color: NAVY, margin: 0 });
  meq(s, 1.15, 3.15, 11.1, [
    ["c", { i: 1 }], ["sum", { sub: 1 }], ["(", {}], ["s", { i: 1 }], [",", {}],
    ["v", { i: 1 }], [")  ≤  ", {}], ["c", { i: 1 }], ["est", { sub: 1 }],
    ["(", {}], ["s", { i: 1 }], [",", {}], ["v", { i: 1 }], [")  ≤  ", {}],
    ["c", { i: 1 }], ["true", { sub: 1 }], ["(", {}], ["s", { i: 1 }],
    [",", {}], ["v", { i: 1 }], [")", {}],
  ], 20, "center");
  s.addText("仮定 A1: 存在する circuits タグは正しい　／　A2: 三相回線は少なくとも 3 導体を使う", {
    x: 1.15, y: 3.66, w: 11.1, h: 0.28, fontFace: F, fontSize: 11,
    color: MUT, align: "center", margin: 0 });
  s.addShape(pres.ShapeType.roundRect, { x: 1.15, y: 3.97, w: 11.1, h: 0.78,
    fill: { color: CODE }, line: { type: "none" }, rectRadius: 0.05 });
  s.addText([
    { text: "証明骨子　", options: { bold: true } },
    { text: "① 項ごとに ĉ(w) ≤ c_true(w)：タグありは A1、cables のみは ⌊n/3⌋ が A2 により過小計上、存在する way は 1 回線以上。", options: { breakLine: true } },
    { text: "　② 総和は不等式を保存する。　③ c_sum は c_est の非負項を落とすだけ。", options: {} },
  ], { x: 1.35, y: 4.04, w: 10.7, h: 0.66, fontFace: F, fontSize: 10.5,
    color: INK, lineSpacing: 14, margin: 0 });

  // 下界性の数直線
  s.addShape(pres.ShapeType.line, { x: 2.4, y: 5.35, w: 8.6, h: 0,
    line: { color: INK, width: 1.5, endArrowType: "triangle" } });
  s.addShape(pres.ShapeType.rect, { x: 5.4, y: 5.27, w: 3.5, h: 0.16,
    fill: { color: "F2C4C4" }, line: { type: "none" } });
  [[3.3, "sum", V66], [5.4, "est", NAVY], [8.9, "true", V500]]
    .forEach(([x, lab, col]) => {
      s.addShape(pres.ShapeType.line, { x, y: 5.22, w: 0, h: 0.26,
        line: { color: col, width: 2.2 } });
      meq(s, x - 0.7, 5.45, 1.4, [["c", { i: 1 }], [lab, { sub: 1 }]], 13,
        "center");
    });
  s.addText("未観測ぶん — 推測で埋めず、この幅自体を測って報告する（→ S11）", {
    x: 5.1, y: 5.88, w: 6, h: 0.3, fontFace: F, fontSize: 11, color: MUT,
    margin: 0 });
  s.addText("帰結：SubSLD の図は「少なくともこれだけの回線が存在する」と述べる。下流で容量の代理指標に使っても、誤差は保守側に出る。", {
    x: 0.9, y: 6.3, w: 11.6, h: 0.32, fontFace: F, fontSize: 12.5,
    color: INK, margin: 0 });
  foot(s, 8, "1:15");
  s.addNotes("効かせどころは『少なくともこれだけある／過大評価しない側に誤る』。証明骨子は読み上げず、A1・A2 を指して20秒で通す。");
}

/* ===================== 9. 三値推論 ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "§VI", "流向：三値推論 — 分からないときは棄権する");
  s.addText("線路が変電所へ入るか出るかはタグ付けされていない。変電所を最高電圧レベルで順序付けて推論する。", {
    x: 0.9, y: 1.15, w: 11.6, h: 0.3, fontFace: F, fontSize: 12.5,
    color: MUT, margin: 0 });
  s.addShape(pres.ShapeType.roundRect, { x: 0.9, y: 1.6, w: 7.1, h: 2.6,
    fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.06 });
  meq(s, 1.15, 1.72, 6.7, [
    ["d̂", { i: 1 }], [" :  ", {}], ["G", { i: 1 }],
    ["  →  { in,  out,  ⊥ }", {}],
  ], 17);
  meq(s, 1.15, 2.3, 6.7, [
    ["d̂", { i: 1 }], ["(", {}], ["g", { i: 1 }], [") = in  ⟺  ∃", {}],
    ["s′", { i: 1 }], ["∈far(", {}], ["g", { i: 1 }], ["): ", {}],
    ["kv", { i: 1 }], ["max", { sub: 1 }], ["(", {}], ["s′", { i: 1 }],
    [") > ", {}], ["kv", { i: 1 }], ["v", { i: 1, sub: 1 }], ["  ∨  ", {}],
    ["kv", { i: 1 }], ["v", { i: 1, sub: 1 }], [" = ", {}],
    ["kv", { i: 1 }], ["top", { sub: 1 }], ["(", {}], ["s", { i: 1 }], [")", {}],
  ], 13);
  meq(s, 1.15, 2.85, 6.7, [
    ["d̂", { i: 1 }], ["(", {}], ["g", { i: 1 }], [") = ⊥  ⟺  far(", {}],
    ["g", { i: 1 }], [") = ∅", {}],
    ["　（棄権）", { jp: 1, fs: 12, c: MUT }],
  ], 15);
  meq(s, 1.15, 3.3, 6.7, [
    ["d̂", { i: 1 }], ["(", {}], ["g", { i: 1 }], [") = out　otherwise", {}],
  ], 15);
  s.addText("far(g) は導出済みのサイト間接続から解決し、接続が欠けている場合は「A–B line」形式の線路名にフォールバックする。", {
    x: 1.15, y: 3.75, w: 6.6, h: 0.35, fontFace: F, fontSize: 10.5,
    color: MUT, margin: 0 });

  // 電圧半順序の梯子
  s.addShape(pres.ShapeType.roundRect, { x: 8.3, y: 1.6, w: 4.2, h: 2.6,
    fill: { color: "FFFFFF" }, line: { color: "D8D8DE", width: 0.9 },
    rectRadius: 0.06 });
  s.addText("s′ ≻ v", { x: 8.55, y: 1.75, w: 1.3, h: 0.28,
    fontFace: "Cambria Math", italic: true, fontSize: 12, color: V500,
    margin: 0 });
  s.addShape(pres.ShapeType.line, { x: 10.0, y: 2.0, w: 0, h: 0.5,
    line: { color: V500, width: 2, endArrowType: "triangle" } });
  s.addText("in", { x: 10.15, y: 2.05, w: 0.6, h: 0.3, fontFace: FL,
    fontSize: 11, bold: true, color: V500, margin: 0 });
  s.addShape(pres.ShapeType.line, { x: 8.55, y: 2.65, w: 3.7, h: 0,
    line: { color: INK, width: 2.5 } });
  s.addText("v（自所の階級）", { x: 8.55, y: 2.72, w: 2.5, h: 0.28,
    fontFace: F, fontSize: 9.5, color: INK, margin: 0 });
  s.addText("s′ ∼ v", { x: 8.55, y: 3.1, w: 1.3, h: 0.28,
    fontFace: "Cambria Math", italic: true, fontSize: 12, color: V66,
    margin: 0 });
  s.addShape(pres.ShapeType.line, { x: 10.0, y: 3.05, w: 0, h: 0.5,
    line: { color: V66, width: 2, beginArrowType: "triangle" } });
  s.addText("out", { x: 10.15, y: 3.25, w: 0.7, h: 0.3, fontFace: FL,
    fontSize: 11, bold: true, color: V66, margin: 0 });
  s.addText("far(g) = ∅ → ⊥（灰スタブ）", { x: 8.55, y: 3.62, w: 3.6, h: 0.3,
    fontFace: F, fontSize: 10, color: MUT, margin: 0 });

  s.addShape(pres.ShapeType.roundRect, { x: 0.9, y: 4.5, w: 11.6, h: 1.15,
    fill: { color: "FFF3F3" }, line: { color: RED, width: 1.1 },
    rectRadius: 0.06 });
  s.addText([
    { text: "遠端が不明なら手法は棄権し、図はスタブを灰色で描く（S4 で見た灰スタブ）。",
      options: { breakLine: true } },
    { text: "棄権率は評価指標として報告し、隠さない（→ S11）。", options: {} },
  ], { x: 1.15, y: 4.5, w: 11.1, h: 1.15, fontFace: F, fontSize: 13.5,
    bold: true, color: RED, lineSpacing: 22, margin: 0, valign: "middle" });
  foot(s, 9, "0:55");
  s.addNotes("第三の値を置いたことが要点。実測パーセンテージはこの枚では言わず S11 に集約する。");
}

/* ===================== 10. 全国適用 ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "§VII", "全国適用：10地域を同一コードで、決定的に、1コマンドで");
  const stats = [["7,239", "抽出された変電所構造"], ["47,979", "evidence-bound terminals"],
                 ["11,586", "導出されたサイト間接続"], ["≈ 4 秒", "全国抽出"]];
  stats.forEach(([v, l], i) => {
    const x = 0.9 + i * 3.05;
    s.addShape(pres.ShapeType.roundRect, { x, y: 1.2, w: 2.8, h: 1.15,
      fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.07 });
    s.addText(v, { x, y: 1.28, w: 2.8, h: 0.62, fontFace: FL, fontSize: 28,
      bold: true, color: NAVY, align: "center", margin: 0 });
    s.addText(l, { x, y: 1.9, w: 2.8, h: 0.32, fontFace: F, fontSize: 10.5,
      color: MUT, align: "center", margin: 0 });
  });
  const tiles = [[A + "tile_miyagi.png", "宮城（東北）500/275/154/66"],
                 [A + "tile_minamihayakita.png", "南早来（北海道）275/187/66"],
                 [A + "tile_hitoyoshi.png", "人吉（九州）220/110/66"],
                 [A + "tile_kochi.png", "高知（四国）187/110/66"]];
  tiles.forEach(([p, cap], i) => {
    const x = 0.9 + i * 3.05;
    s.addImage({ path: p, x, y: 2.6, w: 2.8, h: 3.5 });
    s.addText(cap, { x, y: 6.13, w: 2.9, h: 0.3, fontFace: F, fontSize: 10,
      color: INK, margin: 0 });
  });
  s.addText("ペア図描画は 1〜6 秒/所。160 スレッドのサーバで 10 地域ワーカー、全サイトのスイープが約 1 時間・失敗ゼロ。\n抽出・属性集計・描画の3段すべてが決定的かつ冪等で、プロジェクトの単一再生成コマンドに組み込まれている。", {
    x: 0.9, y: 6.5, w: 11.8, h: 0.55, fontFace: F, fontSize: 11.5,
    color: MUT, lineSpacing: 16, margin: 0 });
  foot(s, 10, "0:50");
  s.addNotes("事実の羅列で速く抜ける。母線・ベイ・変圧器の件数はここで出さない（S13 に一本化）。");
}

/* ===================== 11. 測った欠測（山場） ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "§VII-A", "測った欠測：何が観測できて、何ができなかったか");
  s.addText("命題1で「主張しない」と言った完全性を、ここで数値として返す。", {
    x: 0.9, y: 1.08, w: 11.6, h: 0.3, fontFace: F, fontSize: 12.5,
    color: MUT, margin: 0 });
  s.addImage({ path: A + "fig_coverage.png", x: 0.6, y: 1.5, w: 12.1, h: 3.61 });
  const kk = [["68.2 %", "回線証拠（40,087 本の line 中）", NAVY],
              ["39.4 %", "流向の棄権（18,851 line group）", NAVY],
              ["14.2 %", "母線way を持つサイト", RED]];
  kk.forEach(([v, l, c], i) => {
    const x = 0.9 + i * 3.95;
    s.addText(v, { x, y: 5.35, w: 2.0, h: 0.5, fontFace: FL, fontSize: 24,
      bold: true, color: c, margin: 0 });
    s.addText(l, { x: x + 2.05, y: 5.42, w: 1.9, h: 0.42, fontFace: F,
      fontSize: 10.5, color: MUT, lineSpacing: 13, margin: 0 });
  });
  s.addText("地域勾配が強い：北海道 53.3 % に対し 東京 5.2 %・沖縄 5.1 %。構内way を持ちえない点ジオメトリのサイトは 3.2 % のみ\n— つまり欠測の大半は「点だから描けない」のではない。", {
    x: 0.9, y: 5.95, w: 11.6, h: 0.55, fontFace: F, fontSize: 11.5,
    color: INK, lineSpacing: 16, margin: 0 });
  s.addShape(pres.ShapeType.roundRect, { x: 0.9, y: 6.55, w: 11.6, h: 0.5,
    fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.06 });
  s.addText("これらは弱点の告白ではない。完全性を主張しない設計が返す測定値である。", {
    x: 1.15, y: 6.55, w: 11.1, h: 0.5, fontFace: F, fontSize: 13, bold: true,
    color: NAVY, margin: 0, valign: "middle" });
  foot(s, 11, "1:40");
  s.addNotes("発表の重心。図の値をそのまま読む。最後の一文を言い切って S12 へ。");
}

/* ===================== 12. 欠測 → 作業リスト ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "§VII-B", "欠測は作業リストになる：14所の航空写真判読");
  s.addText("問い：このギャップはマッピング漏れか、物理的不在か。母線way を欠く送電変電所 14 件を、それ自身の SubSLD GeoPane で判読した。", {
    x: 0.9, y: 1.1, w: 11.6, h: 0.32, fontFace: F, fontSize: 12.5,
    color: INK, margin: 0 });
  card(s, 0.9, 1.65, 5.6, 1.5, "マッピング漏れ　9 件（64 %）",
    "上空から明瞭に見える屋外気中絶縁母線とベイ列を持つ。\n必要な作業＝新規ジオメトリ＋タグ", GRN, 14);
  card(s, 0.9, 3.3, 5.6, 1.5, "タグ付け漏れ　1 件",
    "構内way と頂点共有端子はあるが line=busbar タグが無いだけ。\n必要な作業＝タグのみ（新規ジオメトリ不要）", V275, 14);
  s.addText("残りは GIS または屋内設備で、母線が可視の線として存在しない — 推定母線（inferred busbar）が適切な答えとなる。", {
    x: 0.9, y: 4.95, w: 5.7, h: 0.6, fontFace: F, fontSize: 11.5,
    color: MUT, lineSpacing: 16, margin: 0 });
  s.addImage({ path: A + "geo_shinkeiyo.png", x: 7.0, y: 1.65, w: 5.5, h: 3.9,
    sizing: { type: "crop", w: 5.5, h: 3.9, x: 0.3, y: 0.6 } });
  s.addText("判読の実物：屋外母線列とベイ列が上空から見える", { x: 7.0, y: 5.6,
    w: 5.5, h: 0.3, fontFace: F, fontSize: 10.5, color: MUT, margin: 0 });
  s.addShape(pres.ShapeType.roundRect, { x: 0.9, y: 6.0, w: 11.6, h: 0.85,
    fill: { color: NAVY }, line: { type: "none" }, rectRadius: 0.07 });
  s.addText("計測されたギャップ →　編集リンク付きの貢献リストとして公開（9 サイト ＋ OSM 未登録の送電線 1 本）", {
    x: 1.2, y: 6.0, w: 11.1, h: 0.85, fontFace: F, fontSize: 14, bold: true,
    color: "FFFFFF", margin: 0, valign: "middle" });
  foot(s, 12, "1:20");
  s.addNotes("『14件をレビューし、うち9件（64%）が…』『残りは GIS または屋内設備で…』と件数を出さずに述べる。被覆率統計が作業に変わった、が落とし所。");
}

/* ===================== 13. 標準への書き出し ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "§VIII", "標準への書き出し：証拠と推定の区別はエクスポート後も残る");
  s.addText("自前レンダラ専用の構造では到達範囲が限られる。§IV のデータモデルは当初から CIM に対して定義した — エクスポートは翻訳ではなく直接シリアライズである。", {
    x: 0.9, y: 1.1, w: 11.6, h: 0.32, fontFace: F, fontSize: 12.5,
    color: MUT, margin: 0 });
  const map = [
    ["SubstationSite", "cim:Substation", "サイトごとに 1 件"],
    ["VoltageLevel", "cim:VoltageLevel", "サイト・電圧クラスごと"],
    ["BusbarSection", "cim:BusbarSection", "4,743（推定 2,289 / 観測 2,454）"],
    ["Bay", "cim:Bay", "8,475"],
    ["TransformerSpec", "cim:PowerTransformer", "2,586"],
    ["Terminal", "cim:Terminal", "ConnectivityNode 付き"],
  ];
  s.addText("SubSLD クラス", { x: 1.05, y: 1.55, w: 2.6, h: 0.28, fontFace: F,
    fontSize: 11, bold: true, color: NAVY, margin: 0 });
  s.addText("CIM / CGMES", { x: 3.75, y: 1.55, w: 2.8, h: 0.28, fontFace: FM,
    fontSize: 11, bold: true, color: NAVY, margin: 0 });
  s.addText("全国件数", { x: 6.65, y: 1.55, w: 2.2, h: 0.28, fontFace: F,
    fontSize: 11, bold: true, color: NAVY, margin: 0 });
  map.forEach(([a, b, c], i) => {
    const y = 1.9 + i * 0.52, hi = i === 2;
    s.addShape(pres.ShapeType.rect, { x: 0.9, y, w: 8.1, h: 0.48,
      fill: { color: hi ? "EFF1F8" : (i % 2 ? "FFFFFF" : PANEL) },
      line: { type: "none" } });
    s.addText(a, { x: 1.05, y, w: 2.6, h: 0.48, fontFace: F, fontSize: 11.5,
      color: INK, margin: 0, valign: "middle" });
    s.addText(b, { x: 3.75, y, w: 2.8, h: 0.48, fontFace: FM, fontSize: 11,
      color: INK, margin: 0, valign: "middle" });
    s.addText(c, { x: 6.65, y, w: 2.25, h: 0.48, fontFace: F, fontSize: 11,
      bold: hi, color: hi ? NAVY : INK, margin: 0, valign: "middle" });
  });
  // 観測/推定の内訳バー
  s.addShape(pres.ShapeType.rect, { x: 1.05, y: 5.05, w: 4.18, h: 0.3,
    fill: { color: NAVY }, line: { type: "none" } });
  s.addShape(pres.ShapeType.rect, { x: 5.23, y: 5.05, w: 3.77, h: 0.3,
    fill: { color: "B9B9C2" }, line: { type: "none" } });
  s.addText("観測 2,454", { x: 1.05, y: 5.05, w: 4.18, h: 0.3, fontFace: F,
    fontSize: 10, bold: true, color: "FFFFFF", align: "center",
    valign: "middle", margin: 0 });
  s.addText("推定 2,289（印つき）", { x: 5.23, y: 5.05, w: 3.77, h: 0.3,
    fontFace: F, fontSize: 10, bold: true, color: "3A3A44", align: "center",
    valign: "middle", margin: 0 });

  s.addShape(pres.ShapeType.roundRect, { x: 9.25, y: 1.55, w: 3.25, h: 3.8,
    fill: { color: "2A2A33" }, line: { type: "none" }, rectRadius: 0.06 });
  s.addText("推定母線は印を保持する", { x: 9.45, y: 1.68, w: 2.9, h: 0.3,
    fontFace: F, fontSize: 11.5, bold: true, color: "FFD54F", margin: 0 });
  s.addText("CGMES 2.4 に「estimated」属性が無いため、provenance を\nIdentifiedObject.description に書き込む：", {
    x: 9.45, y: 2.02, w: 2.9, h: 0.6, fontFace: F, fontSize: 10,
    color: "C9C9D2", lineSpacing: 13, margin: 0 });
  s.addText("inferred-topology (SubSLD):\nno busbar way in OSM;\nexistence derived from\nstrongly-bound terminals", {
    x: 9.45, y: 2.7, w: 2.9, h: 1.1, fontFace: FM, fontSize: 9,
    color: "8FE3A0", lineSpacing: 12, margin: 0 });
  s.addText("このフィールドを無視するツールも妥当なトポロジを受け取る。読むツールや人は、観測と推定を分離できる。", {
    x: 9.45, y: 3.9, w: 2.9, h: 0.9, fontFace: F, fontSize: 10,
    color: "E8E8F0", lineSpacing: 13, margin: 0 });
  s.addText("同一電圧レベルの2つの母線区分に接するベイは coupler 候補として名前で開示する（スイッチは観測していないので Breaker と断定しない）。", {
    x: 0.9, y: 5.6, w: 11.6, h: 0.55, fontFace: F, fontSize: 11.5,
    color: INK, lineSpacing: 16, margin: 0 });
  s.addText("EQ / GL・全 10 地域　｜　Level-2 は独立インポータでラウンドトリップ確認済み　｜　電圧階級が確定しない VoltageLevel は BaseVoltage を捏造しないため出力しない", {
    x: 0.9, y: 6.25, w: 11.8, h: 0.5, fontFace: F, fontSize: 10.5,
    color: MUT, margin: 0 });
  foot(s, 13, "1:10");
  s.addNotes("『推定母線は CGMES でも推定のまま』を必ず言う。件数の差（構造DB 5,228 vs CIM 4,743）は電圧階級が確定しない分を出さないため、と口頭で自己開示する。");
}

/* ===================== 14. まとめ ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "§IX–X", "まとめ：限界と、次にマップすべきもの");
  const lims = [
    ["lead-in 帯", "近傍を通過するだけの線路を弱い証拠として受け入れる（可視化はするが除去しない）"],
    ["流向", "潮流計算ではなく電圧階層ヒューリスティック。全体を通じて inference と表示"],
    ["導体数", "被覆が低く、束情報はフィールドではなく疎な注釈として扱うべき"],
    ["被覆数値", "生きたデータベースのスナップショットである"],
  ];
  lims.forEach(([t, b], i) => card(s, 0.9 + (i % 4) * 2.95, 1.15, 2.75, 1.5,
    t, b, MUT, 11.5));
  s.addShape(pres.ShapeType.roundRect, { x: 0.9, y: 2.95, w: 11.6, h: 1.5,
    fill: { color: NAVY }, line: { type: "none" }, rectRadius: 0.08 });
  s.addText("抽出を健全性が構成的に成立するよう定式化し、推定を下界として保証し、推論に棄権を許すならば、\n変電所の内部構成は VGI から全国規模で復元できる。計測されたギャップは結果の付録ではなく、\n次に何をマップすべきかをコミュニティに伝える結果の一部である。", {
    x: 1.2, y: 2.95, w: 11.0, h: 1.5, fontFace: F, fontSize: 15, bold: true,
    color: "FFFFFF", lineSpacing: 24, margin: 0, valign: "middle" });
  s.addText("今後", { x: 0.9, y: 4.65, w: 2, h: 0.3, fontFace: F, fontSize: 12.5,
    bold: true, color: NAVY, margin: 0 });
  [["画像からの自動検出", "鉄塔・母線を検出し、人手レビュー無しに証拠基盤を拡大"],
   ["貢献リスト", "モデルがソースを改善する循環を閉じる"],
   ["ベイレベル構造", "公開全国モデル上での遮断器レベル解析の前提条件"]]
    .forEach(([t, b], i) => {
      const x = 0.9 + i * 3.2;
      s.addText(`${i + 1}. ${t}`, { x, y: 5.0, w: 3.0, h: 0.28, fontFace: F,
        fontSize: 11.5, bold: true, color: INK, margin: 0 });
      s.addText(b, { x, y: 5.3, w: 3.05, h: 0.6, fontFace: F, fontSize: 10.5,
        color: MUT, lineSpacing: 14, margin: 0, valign: "top" });
    });
  s.addImage({ path: A + "qr_repo.png", x: 10.6, y: 4.7, w: 0.95, h: 0.95 });
  s.addText("GitHub", { x: 10.6, y: 5.68, w: 0.95, h: 0.24, fontFace: F,
    fontSize: 9, color: MUT, align: "center", margin: 0 });
  s.addImage({ path: A + "qr_viewer.png", x: 11.65, y: 4.7, w: 0.95, h: 0.95 });
  s.addText("全国ビューア", { x: 11.6, y: 5.68, w: 1.05, h: 0.24, fontFace: F,
    fontSize: 9, color: MUT, align: "center", margin: 0 });
  s.addText("All-Japan-Grid v1.8.0　|　github.com/lutelute/All-Japan-Grid　|　lutelute.github.io/All-Japan-Grid/subsld.html　|　CGMES EQ/GL は scripts/export_cim.py で再生成", {
    x: 0.9, y: 6.35, w: 11.8, h: 0.28, fontFace: FM, fontSize: 9,
    color: MUT, margin: 0 });
  s.addText("航空写真：国土地理院　|　ベースマップ：© OpenStreetMap contributors (ODbL)　|　謝辞：本研究を可能にした OpenStreetMap の貢献者に感謝する", {
    x: 0.9, y: 6.62, w: 11.8, h: 0.28, fontFace: F, fontSize: 9,
    color: MUT, margin: 0 });
  foot(s, 14, "1:05");
  s.addNotes("限界を先に自分から出し、結論一文で閉じる。質疑中も投影し続けられる面。");
}

/* ===================== 15.［予備］Algorithm 1 ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "予備", "Algorithm 1：1変電所ぶんの構造抽出", "F の計算的実現（定義そのものは S6）");
  s.addShape(pres.ShapeType.roundRect, { x: 0.9, y: 1.3, w: 7.4, h: 4.9,
    fill: { color: CODE }, line: { color: "E0E0D8", width: 0.8 },
    rectRadius: 0.06 });
  const code = [
    "入力: 変電所 feature s, 前処理済み ways W",
    "1: Poly(s) ← shape(s); V ← vcls(tags) ∪ vcls(構内線)",
    "2: for w ∈ W[busbar]: 頂点共有の連結成分",
    "     → BusbarSection（無タグは隣接から kv 導出）",
    "3: for w ∈ W[bay]: 同様 → Bay（接触母線を記録）",
    "4: for 各本線wayの端点 p:",
    "5:   b ← binding(p)  … 辞書式最大（S7）",
    "6:   if b が存在し admit が成立:",
    "7:     emit Terminal(v, attach, b, par = ĉ(w))",
    "8: 隣接電圧クラス対 → Transformer (structural)",
    "9: 階級に強束縛端子が2本以上あり母線wayが無い",
    "     → 推定母線を emit（印つき）",
    "出力: S*（全要素に witness）",
  ];
  code.forEach((l, i) => s.addText(l, { x: 1.15, y: 1.55 + i * 0.34, w: 7.0,
    h: 0.32, fontFace: FM, fontSize: 11, color: INK, margin: 0 }));
  s.addText("最終ステップの含意", { x: 8.7, y: 1.4, w: 3.8, h: 0.3,
    fontFace: F, fontSize: 12.5, bold: true, color: NAVY, margin: 0 });
  s.addText("GIS・屋内変電所では母線は可視の線として存在せず、観測できない。しかし同一階級に2本以上が強い証拠で束縛されるなら、内部に共通母線があることは電気的に必然である。\n\nそこで存在のみを主張する推定母線を置く — 幾何も端子の再束縛も主張しない。source = inferred-topology と記録し、図では破線で描く。\n\nこれにより命題1の健全性は保たれ、注意書きは可視のまま残る。", {
    x: 8.7, y: 1.8, w: 3.8, h: 4.2, fontFace: F, fontSize: 11,
    color: MUT, lineSpacing: 16, margin: 0, valign: "top" });
  foot(s, 15);
  s.addNotes("質疑用。『Algorithm はどう動くのか』『推定母線は捏造では』に対して出す。");
}

/* ===================== 16.［予備・論文未収載］運用レイヤ ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "予備", "本稿の先：開閉器・ループ・2ロール");
  s.addShape(pres.ShapeType.roundRect, { x: 0.9, y: 0.95, w: 11.6, h: 0.42,
    fill: { color: "FFF3F3" }, line: { color: RED, width: 1.1 },
    rectRadius: 0.05 });
  s.addText("論文未収載 — v1.8.0 以降の実装であり、本稿の主張には含まれない", {
    x: 1.15, y: 0.95, w: 11.1, h: 0.42, fontFace: F, fontSize: 12, bold: true,
    color: RED, margin: 0, valign: "middle" });

  s.addText("① 開閉器（導出）", { x: 0.9, y: 1.55, w: 5.6, h: 0.3, fontFace: F,
    fontSize: 12.5, bold: true, color: NAVY, margin: 0 });
  s.addText("ベイの位置づけから決定的に導出：2つ以上の母線区分に跨る → coupler、端子が付く → feeder、変圧器の hv/lv → trafo。\n全国 8,386 件（feeder 3,615 / coupler 3,593 / trafo 1,178）。", {
    x: 0.9, y: 1.9, w: 5.6, h: 0.75, fontFace: F, fontSize: 11,
    color: MUT, lineSpacing: 15, margin: 0 });
  // 開閉器記号の凡例
  s.addShape(pres.ShapeType.line, { x: 1.1, y: 3.1, w: 4.6, h: 0,
    line: { color: V500, width: 3.5 } });
  [[1.9, false], [3.1, true], [4.6, false]].forEach(([x, open]) => {
    s.addShape(pres.ShapeType.line, { x, y: 2.75, w: 0, h: 0.35,
      line: { color: V500, width: 1.2 } });
    s.addShape(pres.ShapeType.rect, { x: x - 0.09, y: 2.66, w: 0.18, h: 0.18,
      fill: { color: open ? "FFFFFF" : V500 },
      line: { color: V500, width: 1.4 } });
    if (open) s.addShape(pres.ShapeType.line, { x: x - 0.09, y: 2.66,
      w: 0.18, h: 0.18, flipV: true, line: { color: V500, width: 1.2 } });
  });
  s.addText("□＝閉（導通）　斜線□＝開", { x: 1.1, y: 3.2, w: 4.6, h: 0.28,
    fontFace: F, fontSize: 10.5, color: MUT, margin: 0 });
  s.addShape(pres.ShapeType.roundRect, { x: 0.9, y: 3.6, w: 5.6, h: 1.15,
    fill: { color: CODE }, line: { type: "none" }, rectRadius: 0.05 });
  s.addText("観測ではない：source = inferred-bay。OSM に breaker タグは通常無い。\nCIM へは cim:Breaker 8,174 件（電圧不明の階級は写像しないため差分 212 件）。\nnormalOpen = 開 は coupler に一律付与した運用上の既定であり、事業者別の実データではない。", {
    x: 1.1, y: 3.68, w: 5.25, h: 1.0, fontFace: F, fontSize: 9.5,
    color: INK, lineSpacing: 13, margin: 0 });

  s.addText("② ループ（事実。ただし被覆に縛られる）", { x: 6.9, y: 1.55,
    w: 5.6, h: 0.3, fontFace: F, fontSize: 12.5, bold: true, color: NAVY,
    margin: 0 });
  s.addImage({ path: A + "fig_loops.png", x: 6.9, y: 1.9, w: 5.6, h: 1.65 });
  s.addText("circuit rank = E − V + C を同期島単位で算出。図の値をそのまま読む。\nループはグラフから決まる事実で推定を含まないが、モデルの OSM 被覆に縛られる — 欠測で切れている箇所も橋として現れる。\n※(c) の母数 n=9,259 は built のノード数で、本編 S10 の 7,239（構造DB のサイト数）とは母数が違う。", {
    x: 6.9, y: 3.6, w: 5.6, h: 1.15, fontFace: F, fontSize: 9.5,
    color: MUT, lineSpacing: 13, margin: 0 });

  s.addText("③ 2つのロール（ビューア実装）", { x: 0.9, y: 4.95, w: 5.6, h: 0.3,
    fontFace: F, fontSize: 12.5, bold: true, color: NAVY, margin: 0 });
  card(s, 0.9, 5.3, 5.6, 1.35, "制御所",
    "1変電所の開閉器を操作し、母線区分の充電状態を Union-Find で再計算して表示。平常時からの操作差分を追跡・復帰できる。", NAVY, 11.5);
  card(s, 6.9, 5.3, 5.6, 1.35, "中央給電指令所",
    "全国の開閉点を地域別に俯瞰し、操作中の変電所を集約する。ループ構造の表もここに出る。", NAVY, 11.5);
  foot(s, 16);
  s.addNotes("質疑専用。冒頭で必ず『論文未収載』と断る。開閉器は導出であって観測ではない、ループは事実だが被覆に縛られる、と3層で格付けして話す。");
}

pres.writeFile({ fileName: "SubSLD_paper_talk.pptx" })
  .then(() => console.log("written: SubSLD_paper_talk.pptx"));
