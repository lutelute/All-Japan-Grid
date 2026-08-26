// SubSLD法 アカデミック版デッキ — 白基調・定義/数式/擬似コード/フロー図
const pptxgen = require("pptxgenjs");
const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5

const BG = "FFFFFF", INK = "1A1A1A", MUT = "55555F", NAVY = "1E2761";
const PANEL = "F4F4F6", CODE = "F7F7F2";
const V500 = "D62728", V275 = "FF7F0E", V154 = "9467BD", V66 = "17BECF";
const YEL = "FFD54F";
const F = "Hiragino Sans", FM = "Courier New", FL = "Helvetica Neue";

function base(s) { s.background = { color: BG }; }
function head(s, num, sec, title) {
  s.addText(`${num}  ${sec}`, { x: 0.7, y: 0.42, w: 8, h: 0.3, fontFace: FL,
    fontSize: 12, bold: true, color: NAVY, charSpacing: 2, margin: 0 });
  s.addText(title, { x: 0.66, y: 0.78, w: 12.0, h: 0.62, fontFace: F,
    fontSize: 25, bold: true, color: INK, margin: 0 });
}
function foot(s, n) {
  s.addText(`SubSLD法 — 実証ペア図法  /  All-Japan-Grid`, { x: 0.7, y: 7.12,
    w: 6, h: 0.3, fontFace: FL, fontSize: 9, color: MUT, margin: 0 });
  s.addText(String(n), { x: 12.5, y: 7.12, w: 0.5, h: 0.3, fontFace: FL,
    fontSize: 10, color: MUT, align: "right", margin: 0 });
}

// ---------- 1. タイトル ----------
{
  const s = pres.addSlide(); base(s);
  s.addText("SubSLD法：公開地理データからの\n変電所内部構成の実証的機械生成", {
    x: 0.9, y: 1.15, w: 11.6, h: 1.75, fontFace: F, fontSize: 33, bold: true,
    color: INK, lineSpacing: 50, margin: 0 });
  s.addText("Evidence-Paired Substation Single-Line Diagramming", {
    x: 0.93, y: 3.0, w: 11.5, h: 0.45, fontFace: FL, fontSize: 16,
    italic: true, color: NAVY, margin: 0 });
  s.addText("All-Japan-Grid Project  /  2026-08-26", {
    x: 0.93, y: 3.6, w: 11.5, h: 0.4, fontFace: F, fontSize: 13,
    color: MUT, margin: 0 });
  s.addImage({ path: "assets/geo_shinkeiyo.png", x: 0, y: 4.55, w: 13.33,
    h: 2.95, sizing: { type: "cover", w: 13.33, h: 2.95 } });
  s.addShape(pres.ShapeType.rect, { x: 0, y: 4.55, w: 13.33, h: 2.95,
    fill: { color: "000000", transparency: 78 }, line: { type: "none" } });
  s.addText("図: GeoPane(新京葉変電所) — OSM実証拠を地理院写真上に重畳した実出力", {
    x: 0.7, y: 6.95, w: 10, h: 0.35, fontFace: F, fontSize: 10.5,
    color: "FFFFFF", margin: 0 });
}

// ---------- 2. 背景と貢献 ----------
{
  const s = pres.addSlide(); base(s);
  head(s, "1", "INTRODUCTION", "背景と貢献");
  s.addText([
    { text: "課題", options: { bold: true, color: NAVY, breakLine: true } },
    { text: "系統解析に必要な変電所内部構成（母線・変圧器・回線・導体）は事業者内部資料であり、研究利用できる全国データが存在しない。", options: { breakLine: true } },
    { text: "", options: { breakLine: true } },
    { text: "先行実証", options: { bold: true, color: NAVY, breakLine: true } },
    { text: "嶺南変電所1所において、OSM実データのみから node-breaker 構造を手作業で確認できた（2026-07, GridStitch P2）。本手法はその全国機械化である。", options: {} },
  ], { x: 0.7, y: 1.7, w: 5.9, h: 4.4, fontFace: F, fontSize: 14,
    color: INK, lineSpacing: 23, margin: 0, valign: "top" });
  const cons = [
    ["C1", "全国6,956変電所の内部構造（母線・ベイ・端子・変圧器）をOSM実証拠のみから決定的に抽出"],
    ["C2", "回線数・導体数を線タグから変電所単位に集約（証拠と推計を分離保持）"],
    ["C3", "構内幾何×単線結線図の「実証ペア図」を全所自動生成（衛星重畳・根拠付き）"],
    ["C4", "捏造ゼロ・全端子根拠・推定明記・再現可能という検証可能性の設計"],
  ];
  cons.forEach(([n, t], i) => {
    const y = 1.75 + i * 1.28;
    s.addShape(pres.ShapeType.roundRect, { x: 7.0, y, w: 5.7, h: 1.12,
      fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.06 });
    s.addText(n, { x: 7.25, y: y + 0.28, w: 0.65, h: 0.5, fontFace: FL,
      fontSize: 17, bold: true, color: NAVY, margin: 0 });
    s.addText(t, { x: 7.95, y: y + 0.14, w: 4.6, h: 0.9, fontFace: F,
      fontSize: 11.5, color: INK, lineSpacing: 16, margin: 0, valign: "middle" });
  });
  foot(s, 2);
}

// ---------- 3. 問題設定 ----------
{
  const s = pres.addSlide(); base(s);
  head(s, "2", "PROBLEM SETTING", "問題設定と表記");
  s.addText("入力はOSM由来の地域別データ（変電所ポリゴン・送電線way・タグ）。座標は約1m格子に量子化して同一設備を融合し、同期島ごとの座標グラフを構成する。", {
    x: 0.7, y: 1.6, w: 12.0, h: 0.75, fontFace: F, fontSize: 13.5,
    color: INK, lineSpacing: 21, margin: 0 });
  s.addImage({ path: "assets/eq_quant.png", x: 0.9, y: 2.5, w: 10.8, h: 1.15,
    sizing: { type: "contain", w: 10.8, h: 1.15 } });
  const syms = [
    ["s,  Poly(s)", "変電所サイトとその敷地ポリゴン"],
    ["W_busbar / W_bay / W_main", "構内way（line=busbar / bay）と本線way"],
    ["t ∈ Terminals(s)", "線端の束縛レコード（根拠 binding を保持）"],
    ["kv_v,  L(s,v)", "電圧階級 v と、その階級に束縛された線集合"],
    ["far(g)", "線グループ g の対向変電所集合（connections + 線名から解決）"],
  ];
  s.addText("記号", { x: 0.7, y: 3.95, w: 3, h: 0.4, fontFace: F,
    fontSize: 14, bold: true, color: NAVY, margin: 0 });
  syms.forEach(([k, v], i) => {
    const y = 4.4 + i * 0.52;
    s.addText(k, { x: 0.9, y, w: 3.9, h: 0.42, fontFace: FM, fontSize: 12,
      color: INK, margin: 0 });
    s.addText(v, { x: 5.0, y, w: 7.6, h: 0.42, fontFace: F, fontSize: 12,
      color: MUT, margin: 0 });
  });
  foot(s, 3);
}

// ---------- 4. 手法概要(フロー図) ----------
{
  const s = pres.addSlide(); base(s);
  head(s, "3", "METHOD OVERVIEW", "3段パイプライン（データフロー）");
  const arrow = (x1, y1, x2, y2) => s.addShape(pres.ShapeType.line,
    { x: x1, y: y1, w: x2 - x1, h: y2 - y1,
      line: { color: MUT, width: 1.6, endArrowType: "triangle" } });
  const data = (x, y, w, h, txt, fs) => {
    s.addShape(pres.ShapeType.roundRect, { x, y, w, h,
      fill: { color: PANEL }, line: { color: "D8D8DE", width: 0.75 },
      rectRadius: 0.06 });
    s.addText(txt, { x: x + 0.12, y, w: w - 0.24, h, fontFace: F,
      fontSize: fs || 11.5, color: INK, align: "center", valign: "middle",
      margin: 0, lineSpacing: 15 });
  };
  const proc = (x, y, w, h, txt, col) => {
    s.addShape(pres.ShapeType.roundRect, { x, y, w, h,
      fill: { color: col || NAVY }, line: { type: "none" }, rectRadius: 0.07 });
    s.addText(txt, { x: x + 0.1, y, w: w - 0.2, h, fontFace: F, fontSize: 13,
      bold: true, color: "FFFFFF", align: "center", valign: "middle",
      margin: 0, lineSpacing: 17 });
  };
  // 入力
  data(0.7, 1.9, 2.5, 0.85, "OSM 地域別データ\nsubstations / lines / タグ");
  // 段1
  proc(3.85, 1.85, 2.35, 0.95, "① GridStitch P2\n構造抽出");
  data(3.7, 3.3, 2.65, 1.0, "構造DB（node-breaker）\nSite / VL / Busbar / Bay /\nTerminal / Trafo", 10.5);
  // 段2
  proc(7.0, 1.85, 2.35, 0.95, "② プロパティ層\n回線・導体の集約");
  data(6.9, 3.3, 2.55, 1.0, "substation_properties\n（5,920サイト）+ sub_props", 10.5);
  // 段3
  proc(10.1, 1.85, 2.45, 0.95, "③ SubSLD 描画\nGeoPane × SLDPane");
  data(10.05, 3.3, 2.55, 1.0, "実証ペア図 PNG\n× 6,956所", 11);
  arrow(3.2, 2.32, 3.82, 2.32);
  arrow(5.02, 2.82, 5.02, 3.28);
  arrow(6.22, 2.32, 6.97, 2.32);
  arrow(8.17, 2.82, 8.17, 3.28);
  arrow(9.37, 2.32, 10.07, 2.32);
  arrow(11.3, 2.82, 11.3, 3.28);
  // ③の補助入力(タイル・鉄塔・対向解決)は③の列に配置して上向きに接続
  data(10.05, 4.62, 2.55, 0.92, "③の補助入力:\n地理院タイル・鉄塔\nconnections（対向解決）", 10);
  arrow(11.3, 4.6, 11.3, 4.34);
  // 下段: 特性
  const props = [
    ["決定的", "同一入力→同一出力。OSM更新に全所追随", V66],
    ["根拠付き", "全 Terminal に binding（証拠語彙）を刻む", V275],
    ["冪等・再開可能", "全段が regen パイプライン(STEPS)に組込済み", V154],
  ];
  props.forEach(([h, b, c], i) => {
    const x = 0.7 + i * 4.24;
    s.addShape(pres.ShapeType.rect, { x, y: 6.02, w: 0.16, h: 0.16,
      fill: { color: c }, line: { type: "none" } });
    s.addText(h, { x: x + 0.28, y: 5.9, w: 3.6, h: 0.4, fontFace: F,
      fontSize: 13.5, bold: true, color: INK, margin: 0 });
    s.addText(b, { x: x + 0.28, y: 6.32, w: 3.8, h: 0.45, fontFace: F,
      fontSize: 10.5, color: MUT, lineSpacing: 14, margin: 0 });
  });
  s.addText("実装: build_substation_structure.py ・ build_substation_properties.py ・ build_subsld_batch.py（手法文書 docs/SUBSLD_METHOD.md）", {
    x: 0.7, y: 6.82, w: 12.2, h: 0.32, fontFace: FM, fontSize: 9.5,
    color: MUT, margin: 0 });
  foot(s, 4);
}

// ---------- 5. Algorithm 1 ----------
{
  const s = pres.addSlide(); base(s);
  head(s, "4", "STAGE 1 — EXTRACTION", "構造抽出と端子束縛（binding 述語）");
  // 擬似コード
  s.addShape(pres.ShapeType.roundRect, { x: 0.7, y: 1.6, w: 6.4, h: 4.6,
    fill: { color: CODE }, line: { color: "E0E0D8", width: 0.75 },
    rectRadius: 0.06 });
  s.addText("Algorithm 1  構造抽出（1変電所）", { x: 1.0, y: 1.78, w: 5.8,
    h: 0.35, fontFace: F, fontSize: 12.5, bold: true, color: INK, margin: 0 });
  const code = [
    "入力: 変電所 feature s, 前処理済み ways W",
    "1: Poly(s) ← shape(s); V ← vcls(tag) ∪ vcls(構内線)",
    "2: for w ∈ W[busbar]: 頂点共有の連結成分",
    "     → BusbarSection（無タグは隣接から kv 導出）",
    "3: for w ∈ W[bay]: 同様 → Bay（接触母線を記録）",
    "4: for 各本線wayの端点 p:",
    "5:   binding(p) ← vertex ≻ polygon ≻ leadin",
    "6:   Terminal(vl, attach, binding, par=ĉ(w))",
    "7: 隣接電圧階級対 → Transformer(structural)",
    "出力: SubstationStructure（決定的・全端子に根拠）",
  ];
  code.forEach((l, i) => {
    s.addText(l, { x: 1.0, y: 2.22 + i * 0.375, w: 5.9, h: 0.36,
      fontFace: FM, fontSize: 11, color: INK, margin: 0 });
  });
  // binding 述語
  s.addText("端子束縛の証拠語彙（強い順に採用）", { x: 7.5, y: 1.75, w: 5.2,
    h: 0.4, fontFace: F, fontSize: 14, bold: true, color: NAVY, margin: 0 });
  s.addImage({ path: "assets/eq_binding.png", x: 7.5, y: 2.3, w: 5.35,
    h: 1.85, sizing: { type: "contain", w: 5.35, h: 1.85 } });
  s.addText("弱い証拠は図上でも弱く描く（leadin＝破線）。証拠の無い接続は作らない（捏造ゼロ）。name-evidence（「A~B線」等の線名）は connections 欠測時の対向解決のみに用い、接続そのものは作らない。", {
    x: 7.5, y: 4.35, w: 5.2, h: 1.7, fontFace: F, fontSize: 12,
    color: MUT, lineSpacing: 19, margin: 0 });
  foot(s, 5);
}

// ---------- 6. 電圧整合ゲート ----------
{
  const s = pres.addSlide(); base(s);
  head(s, "5", "STAGE 1 — SAFETY GATE", "電圧整合ゲート");
  s.addText("物理的に近接していても電気的に接続してはならない対（併架・並走回廊）を、電圧の相対乖離で棄却する。", {
    x: 0.7, y: 1.6, w: 12.0, h: 0.5, fontFace: F, fontSize: 13.5,
    color: INK, margin: 0 });
  s.addImage({ path: "assets/eq_gate.png", x: 1.6, y: 2.35, w: 8.5, h: 0.8,
    sizing: { type: "contain", w: 8.5, h: 0.8 } });
  s.addShape(pres.ShapeType.roundRect, { x: 0.7, y: 3.6, w: 12.0, h: 2.7,
    fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.07 });
  s.addText("正当性の事例（2026-08-20 断片解消キャンペーン c1）", { x: 1.0,
    y: 3.85, w: 11, h: 0.4, fontFace: F, fontSize: 13.5, bold: true,
    color: NAVY, margin: 0 });
  s.addText("甲府近郊の66kV断片は、154kV系のjunctionと物理的に80m以内で接触していたが、本ゲートが接続を正しく棄却。後の診断で断片自体が跨region二重登録の人工物と判明し、ゲートは「物理的には近いが電気的に繋いではならない」ケースを実証的に防いだ。以降もゲートは緩めない方針を採る。", {
    x: 1.0, y: 4.35, w: 11.4, h: 1.7, fontFace: F, fontSize: 12.5,
    color: INK, lineSpacing: 21, margin: 0 });
  foot(s, 6);
}

// ---------- 7. プロパティ集約 ----------
{
  const s = pres.addSlide(); base(s);
  head(s, "6", "STAGE 2 — AGGREGATION", "回線数・導体数の集約");
  s.addText("線タグ（circuits / cables / wires）を terminal の line_key で構造DBに接合し、変電所×電圧階級の単位に集約する。証拠のある値と推計値を分離して保持し、無タグを推測で埋めない。", {
    x: 0.7, y: 1.6, w: 12.0, h: 0.8, fontFace: F, fontSize: 13.5,
    color: INK, lineSpacing: 21, margin: 0 });
  s.addImage({ path: "assets/eq_circuits.png", x: 0.9, y: 2.6, w: 11.4,
    h: 1.35, sizing: { type: "contain", w: 11.4, h: 1.35 } });
  // wires 対応表
  s.addText("導体数（wiresタグ）の写像", { x: 0.7, y: 4.35, w: 5, h: 0.4,
    fontFace: F, fontSize: 13.5, bold: true, color: NAVY, margin: 0 });
  const wt = [["single", "1"], ["double", "2"], ["triple", "3"], ["quad", "4"]];
  wt.forEach(([k, v], i) => {
    const x = 0.9 + i * 1.9;
    s.addShape(pres.ShapeType.roundRect, { x, y: 4.85, w: 1.7, h: 0.85,
      fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.06 });
    s.addText(k, { x, y: 4.95, w: 1.7, h: 0.35, fontFace: FM, fontSize: 11,
      color: MUT, align: "center", margin: 0 });
    s.addText(v + " 導体", { x, y: 5.3, w: 1.7, h: 0.35, fontFace: F,
      fontSize: 12.5, bold: true, color: INK, align: "center", margin: 0 });
  });
  s.addText([
    { text: "被覆（全国40,087線・実測）: ", options: { bold: true } },
    { text: "circuits系の証拠 68.2%（27,352線）・wiresタグ 12.7%（5,080線）。被覆自体を結果として報告し、欠測は unknown のまま可視化する。", options: {} },
  ], { x: 8.6, y: 4.75, w: 4.1, h: 1.7, fontFace: F, fontSize: 12,
    color: INK, lineSpacing: 19, margin: 0 });
  foot(s, 7);
}

// ---------- 8. 描画規則(流向) ----------
{
  const s = pres.addSlide(); base(s);
  head(s, "7", "STAGE 3 — RENDERING", "SLDPane の描画規則と流向推定");
  const rules = [
    ["母線", "電圧階級別の太い水平線。BusbarSection 数でセクション分割・BT=バスタイ", V500],
    ["線スタブ", "実際の束縛セクションに接着。平行ストローク本数＝回線数", V275],
    ["破線", "leadin 根拠（弱い証拠を弱く描く）・灰＝対向不明", V154],
    ["変圧器", "母線間の二重円（バンク数・銘板は出典がある時のみ）。無い階級は「スルー」明記", V66],
  ];
  rules.forEach(([h, b, c], i) => {
    const y = 1.7 + i * 0.78;
    s.addShape(pres.ShapeType.rect, { x: 0.72, y: y + 0.07, w: 0.16, h: 0.16,
      fill: { color: c }, line: { type: "none" } });
    s.addText(h, { x: 1.0, y, w: 1.8, h: 0.4, fontFace: F, fontSize: 13.5,
      bold: true, color: INK, margin: 0, valign: "top" });
    s.addText(b, { x: 2.9, y: y + 0.02, w: 9.7, h: 0.62, fontFace: F,
      fontSize: 12, color: MUT, lineSpacing: 17, margin: 0, valign: "top" });
  });
  s.addText("流向（入/出）の推定規則", { x: 0.7, y: 4.95, w: 6, h: 0.4,
    fontFace: F, fontSize: 14, bold: true, color: NAVY, margin: 0 });
  s.addImage({ path: "assets/eq_dir.png", x: 0.9, y: 5.42, w: 11.4, h: 1.55,
    sizing: { type: "contain", w: 11.4, h: 1.55 } });
  foot(s, 8);
}

// ---------- 9. 結果: 実証ペア図 ----------
{
  const s = pres.addSlide(); base(s);
  head(s, "8", "RESULTS", "実証ペア図 — 新京葉変電所（500/275/154/66kV）");
  s.addImage({ path: "assets/pair_full.png", x: 0.85, y: 1.62, w: 11.6,
    h: 5.15, sizing: { type: "contain", w: 11.6, h: 5.15 } });
  s.addText("左: GeoPane（構内幾何・端子根拠・鉄塔・インセット）　右: SLDPane（母線セクション・回線ストローク・流向・変圧器・スルー）", {
    x: 0.85, y: 6.78, w: 11.8, h: 0.35, fontFace: F, fontSize: 11,
    color: MUT, margin: 0 });
  foot(s, 9);
}

// ---------- 10. 結果: 全国適用 ----------
{
  const s = pres.addSlide(); base(s);
  head(s, "9", "RESULTS", "全国適用 — 10地域・6,956所を同一コードで処理");
  const gs = [
    ["assets/geo_minamihayakita.png", "南早来（北海道）275/187/66"],
    ["assets/geo_sunen.png", "駿遠（中部）500/275/154/77"],
    ["assets/geo_hitoyoshi.png", "人吉（九州）220/110/66"],
    ["assets/geo_zukeran.png", "瑞慶覧（沖縄）132/66"],
  ];
  gs.forEach(([p, cap], i) => {
    const x = 0.7 + i * 3.08;
    s.addImage({ path: p, x, y: 1.7, w: 2.9, h: 3.9,
      sizing: { type: "cover", w: 2.9, h: 3.9 } });
    s.addText(cap, { x, y: 5.66, w: 2.9, h: 0.36, fontFace: F,
      fontSize: 10.5, color: INK, margin: 0 });
  });
  s.addText("バッチ生成器（再開可能・タイルキャッシュ・礼儀スロットル）により全所を一括描画。約1〜6秒/所、10地域並列で全国を約1時間で処理（pws-160core 実測）。", {
    x: 0.7, y: 6.25, w: 12.2, h: 0.65, fontFace: F, fontSize: 12,
    color: MUT, lineSpacing: 18, margin: 0 });
  foot(s, 10);
}

// ---------- 11. 被覆評価 ----------
{
  const s = pres.addSlide(); base(s);
  head(s, "10", "EVALUATION", "被覆の定量評価");
  const stats = [
    ["6,956", "対象変電所（構造抽出は全数成功）", INK],
    ["68.2%", "回線数のOSM証拠被覆（線ベース）", NAVY],
    ["13.9%", "母線way記載率 — 最大の欠測（issue #49）", V500],
  ];
  stats.forEach(([v, l, c], i) => {
    const y = 1.8 + i * 1.65;
    s.addText(v, { x: 0.7, y, w: 3.4, h: 0.9, fontFace: FL, fontSize: 46,
      bold: true, color: c, margin: 0 });
    s.addText(l, { x: 0.74, y: y + 0.95, w: 3.7, h: 0.55, fontFace: F,
      fontSize: 11.5, color: MUT, lineSpacing: 15, margin: 0 });
  });
  s.addChart(pres.ChartType.bar, [{
    name: "母線way記載率",
    labels: ["北海道", "東北", "北陸", "四国", "中国", "中部", "九州", "関西", "沖縄", "東京"],
    values: [53, 25, 25, 12, 11, 10, 10, 8, 5, 5],
  }], {
    x: 4.9, y: 1.6, w: 7.8, h: 5.1, barDir: "bar",
    chartColors: [NAVY], showLegend: false,
    showTitle: true, title: "母線way記載率(%) — OSMマッピング粒度の地域差",
    titleColor: INK, titleFontSize: 13, titleFontFace: F,
    showValue: true, dataLabelPosition: "outEnd", dataLabelColor: INK,
    dataLabelFontSize: 10, dataLabelFontFace: FL,
    catAxisLabelColor: INK, catAxisLabelFontSize: 11, catAxisLabelFontFace: F,
    valAxisLabelColor: MUT, valAxisLabelFontSize: 10, valAxisLabelFontFace: FL,
    valGridLine: { color: "E3E3E8", size: 0.5 },
    catGridLine: { style: "none" },
    valAxisMaxVal: 60,
  });
  foot(s, 11);
}

// ---------- 12. 限界と考察 ----------
{
  const s = pres.addSlide(); base(s);
  head(s, "11", "DISCUSSION", "限界と考察 — 欠測を欠測として見せる");
  const lims = [
    ["母線wayの欠測 86%", "OSMマッピング粒度の地域差（北海道53% ⇔ 東京5%）。母線なしサイトは1母線仮定で描画される。推定母線の導入は inferred マーカー前提で検討（issue #49）"],
    ["流向不明（灰スタブ）", "主因は対向変電所自体のOSM欠測。connections＋線名 name-evidence で低減したが、残余は「不明」を明示する設計を保つ"],
    ["leadin の偽陽性", "引込帯0.6kmは近傍通過線を拾い得る。弱い証拠を弱く描く（破線）ことで図上でも可視化"],
    ["導体数被覆 12.7%", "wiresタグ自体が希少。航空写真からの検出（TTPLA系）が補完候補"],
  ];
  lims.forEach(([h, b], i) => {
    const x = 0.7 + (i % 2) * 6.3, y = 1.75 + Math.floor(i / 2) * 2.5;
    s.addShape(pres.ShapeType.roundRect, { x, y, w: 5.95, h: 2.25,
      fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.07 });
    s.addText(h, { x: x + 0.3, y: y + 0.22, w: 5.4, h: 0.42, fontFace: F,
      fontSize: 14, bold: true, color: INK, margin: 0 });
    s.addText(b, { x: x + 0.3, y: y + 0.72, w: 5.4, h: 1.4, fontFace: F,
      fontSize: 11.5, color: MUT, lineSpacing: 17, margin: 0 });
  });
  foot(s, 12);
}

// ---------- 13. 結論 ----------
{
  const s = pres.addSlide(); base(s);
  head(s, "12", "CONCLUSION", "結論と今後");
  s.addText("変電所の内部構成は、公開データと根拠付き抽出のみで全国一括に「見える化」できる。", {
    x: 0.7, y: 1.75, w: 12.0, h: 0.6, fontFace: F, fontSize: 17, bold: true,
    color: NAVY, margin: 0 });
  s.addText([
    { text: "本研究の要点", options: { bold: true, breakLine: true } },
    { text: "・3段パイプライン（抽出・集約・描画）を全て決定的・冪等に実装し、OSM更新へ全所追随可能とした", options: { breakLine: true } },
    { text: "・証拠語彙（vertex ≻ polygon ≻ leadin）と電圧整合ゲートで、捏造ゼロのまま接続を主張", options: { breakLine: true } },
    { text: "・回線数・導体数は証拠と推計を分離保持し、欠測を欠測として報告", options: {} },
  ], { x: 0.7, y: 2.6, w: 12.0, h: 1.9, fontFace: F, fontSize: 13,
    color: INK, lineSpacing: 22, margin: 0 });
  s.addText([
    { text: "今後", options: { bold: true, breakLine: true } },
    { text: "・editor統合（地図クリックでSubSLD表示）　・OSM貢献ループ（母線なし所の衛星判読→編集候補）", options: { breakLine: true } },
    { text: "・変圧器銘板の出典拡充　・推定母線（inferred）の設計検討", options: {} },
  ], { x: 0.7, y: 4.7, w: 12.0, h: 1.4, fontFace: F, fontSize: 13,
    color: INK, lineSpacing: 22, margin: 0 });
  s.addText("資料: docs/SUBSLD_METHOD.md ・ github.com/lutelute/All-Japan-Grid ・ issue #49", {
    x: 0.7, y: 6.35, w: 12, h: 0.4, fontFace: FM, fontSize: 11,
    color: MUT, margin: 0 });
  foot(s, 13);
}

pres.writeFile({ fileName: "SubSLD_academic.pptx" }).then(() => console.log("written"));
