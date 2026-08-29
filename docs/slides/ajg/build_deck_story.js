// All-Japan-Grid 全史デッキ（プロジェクトを最初から作った記録・20分トーク）
//
// 5幕構成: 地理を掘る → 電気にして標準で渡す → 誠実さを制度にする
//          → 公式開示と接続する → 変電所の中へ
// 各幕は「前の幕が露わにした問い」に答える形で繋がる。
//
// 出典: papers/ieee-openaccess.tex（パイプライン・UC結果）/ papers/subsld/（第5幕）
//       / CHANGELOG.md v1.0.0–v1.8.0。
//
// 数値衛生（subsldデッキと同じ規約 + 全史デッキ固有の1条）:
//   1. 同じ数値を2枚に出さない
//   2. 図の中の値を再プロットしない
//   3. **すべての数値に測定時点（版）を付す** — 変電所数は定義が版で変わる
//      （データセットfeature 6,962 [v1.2確定] と 構造DBサイト 7,239 [v1.8] は別物）。
//      ieee-openaccess.tex 本文の 8,164 は既知の誤記（同論文の表は 6,962）— 使わない。
//
// 本編16枚で 20:00。
const pptxgen = require("pptxgenjs");
const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5

const BG = "FFFFFF", INK = "1A1A1A", MUT = "55555F", NAVY = "1E2761";
const PANEL = "F4F4F6", CODE = "F7F7F2", RED = "C62828", GRN = "2E7D32";
// 幕の色 = 電圧色（幕が進むほど階級が上がる）
const ACT = ["9A9AA6", "17BECF", "9467BD", "FF7F0E", "D62728"];
const F = "Hiragino Sans", FM = "Courier New", FL = "Helvetica Neue";
const A = "assets/";

function base(s) { s.background = { color: BG }; }

// 見出し。tag は幕バッジ（"第3幕 v1.5–1.6" 等）、col は幕色
function head(s, tag, title, col, sub) {
  if (tag) {
    s.addShape(pres.ShapeType.roundRect, { x: 0.68, y: 0.38, w: 2.1, h: 0.3,
      fill: { color: col || NAVY }, line: { type: "none" }, rectRadius: 0.05 });
    s.addText(tag, { x: 0.68, y: 0.38, w: 2.1, h: 0.3, fontFace: F,
      fontSize: 11, bold: true, color: "FFFFFF", align: "center",
      valign: "middle", margin: 0 });
  }
  s.addText(title, { x: tag ? 2.95 : 0.66, y: 0.34, w: tag ? 9.7 : 12.0,
    h: 0.42, fontFace: F, fontSize: 21, bold: true, color: INK, margin: 0,
    valign: "middle" });
  if (sub) s.addText(sub, { x: 0.68, y: 0.8, w: 12.0, h: 0.32, fontFace: F,
    fontSize: 12, color: MUT, margin: 0 });
}
function foot(s, n, mins) {
  s.addText("All-Japan-Grid — the making of", { x: 0.7, y: 7.12, w: 6, h: 0.28,
    fontFace: FL, fontSize: 9, color: MUT, margin: 0 });
  if (mins) s.addText(mins, { x: 10.6, y: 7.12, w: 1.6, h: 0.28, fontFace: FL,
    fontSize: 9, color: MUT, align: "right", margin: 0 });
  s.addText(String(n), { x: 12.4, y: 7.12, w: 0.5, h: 0.28, fontFace: FL,
    fontSize: 10, color: MUT, align: "right", margin: 0 });
}
function card(s, x, y, w, h, title, body, col, fs) {
  s.addShape(pres.ShapeType.roundRect, { x, y, w, h, fill: { color: PANEL },
    line: { type: "none" }, rectRadius: 0.06 });
  if (col) s.addShape(pres.ShapeType.rect, { x: x + 0.22, y: y + 0.24,
    w: 0.14, h: 0.14, fill: { color: col }, line: { type: "none" } });
  s.addText(title, { x: x + (col ? 0.45 : 0.25), y: y + 0.12, w: w - 0.5,
    h: 0.35, fontFace: F, fontSize: fs || 12.5, bold: true, color: INK,
    margin: 0 });
  s.addText(body, { x: x + 0.25, y: y + 0.5, w: w - 0.5, h: h - 0.62,
    fontFace: F, fontSize: (fs || 12.5) - 2, color: MUT, lineSpacing: 15,
    margin: 0, valign: "top" });
}
// 大きな数字 + キャプション（測定時点ラベル必須）
function stat(s, x, y, w, big, cap, when, col) {
  s.addShape(pres.ShapeType.roundRect, { x, y, w, h: 1.25,
    fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.06 });
  s.addText(big, { x, y: y + 0.08, w, h: 0.55, fontFace: FL, fontSize: 26,
    bold: true, color: col || NAVY, align: "center", margin: 0 });
  s.addText(cap, { x: x + 0.1, y: y + 0.63, w: w - 0.2, h: 0.34, fontFace: F,
    fontSize: 10.5, color: INK, align: "center", margin: 0 });
  s.addText(when, { x: x + 0.1, y: y + 0.95, w: w - 0.2, h: 0.26, fontFace: F,
    fontSize: 8.5, color: MUT, align: "center", margin: 0 });
}
function meq(s, x, y, w, runs, fs, align) {
  s.addText(runs.map(([t, o]) => {
    o = o || {};
    return { text: t, options: {
      fontFace: o.jp ? F : "Cambria Math", italic: !!o.i,
      subscript: !!o.sub, superscript: !!o.sup,
      color: o.c || INK, fontSize: o.fs || fs || 18 } };
  }), { x, y, w, h: 0.5, margin: 0, valign: "middle", align: align || "left" });
}

/* ===================== 1. タイトル ===================== */
{
  const s = pres.addSlide(); base(s);
  // 右: 全国電圧クラス図（フルブリード縦）
  s.addImage({ path: A + "fig_national_all.png", x: 7.9, y: 0.35, w: 5.1,
    h: 6.56 });
  s.addText("出典: 本プロジェクトの実出力（OSM © OpenStreetMap contributors, ODbL）", {
    x: 7.9, y: 6.95, w: 5.1, h: 0.3, fontFace: F, fontSize: 8.5, color: MUT,
    margin: 0 });
  s.addText("ALL-JAPAN-GRID  /  2026-03 → 2026-08", { x: 0.75, y: 1.0,
    w: 6.6, h: 0.32, fontFace: FL, fontSize: 11.5, bold: true, color: NAVY,
    charSpacing: 2, margin: 0 });
  s.addText("OSMから、日本全国の\n送電網モデルを作る", { x: 0.7, y: 1.5,
    w: 6.9, h: 2.0, fontFace: F, fontSize: 36, bold: true, color: INK,
    lineSpacing: 52, margin: 0 });
  s.addText("— 6ヶ月・1,021コミット・10リリースの記録", { x: 0.75, y: 3.6,
    w: 6.7, h: 0.45, fontFace: F, fontSize: 17, color: INK, margin: 0 });
  s.addText("All-Japan-Grid: Automated Extraction of Japan's Nationwide\nTransmission Grid Topology from OpenStreetMap", {
    x: 0.75, y: 4.35, w: 6.7, h: 0.7, fontFace: FL, fontSize: 12.5,
    italic: true, color: NAVY, lineSpacing: 17, margin: 0 });
  s.addText("Ryuto Shigenobu — University of Fukui,\nDept. of Electrical, Electronic and Computer Engineering", {
    x: 0.75, y: 5.25, w: 6.7, h: 0.6, fontFace: F, fontSize: 11.5, color: MUT,
    lineSpacing: 16, margin: 0 });
  s.addText("地図はある。モデルが無い。だから作った。", { x: 0.75, y: 6.1,
    w: 6.7, h: 0.4, fontFace: F, fontSize: 14.5, bold: true, color: INK,
    margin: 0 });
  s.addNotes("30秒。右の図は本プロジェクトの実出力（全国の電圧クラス別送電網）。「地図はある、モデルが無い」だけ言って次へ。");
}

/* ===================== 2. HERO: 出来上がったもの ===================== */
{
  const s = pres.addSlide();
  s.background = { color: "0A0D1A" };
  s.addImage({ path: A + "hero_grid.png", x: 0, y: 0, w: 13.33, h: 7.5 });
  s.addText("これが、出来上がったもの。", { x: 0.7, y: 0.75, w: 7.2, h: 0.75,
    fontFace: F, fontSize: 34, bold: true, color: "FFFFFF", margin: 0 });
  s.addText("OpenStreetMapに描かれた「線」から復元した、日本全国の送電系統。\n電圧階級つき・4同期島 — そのままUC・潮流・周波数制御まで解ける。", {
    x: 0.72, y: 1.65, w: 6.8, h: 0.95, fontFace: F, fontSize: 14.5,
    color: "C8CDD8", lineSpacing: 22, margin: 0 });
  // 素材との対比(同構図の単色細線)
  s.addImage({ path: A + "hero_grid_raw.png", x: 0.72, y: 3.0, w: 3.0,
    h: 1.69 });
  s.addShape(pres.ShapeType.rect, { x: 0.72, y: 3.0, w: 3.0, h: 1.69,
    fill: { type: "none" }, line: { color: "3A4266", width: 1 } });
  s.addText("素材はこれ — OSMの power=line/cable 40,077本の\n「ただの線」(同構図・装飾なし)", {
    x: 0.72, y: 4.75, w: 3.6, h: 0.6, fontFace: F, fontSize: 10.5,
    color: "8E96B8", lineSpacing: 14, margin: 0 });
  // 電圧凡例
  [["500 kV級", "FF3B30"], ["275 kV級", "FF9500"], ["154/187", "BF5AF2"],
   ["110 kV級", "34C759"], ["66/77 kV", "32ADE6"]].forEach(([t, c], i) => {
    const y = 3.12 + i * 0.3;
    s.addShape(pres.ShapeType.rect, { x: 4.1, y: y + 0.07, w: 0.3, h: 0.06,
      fill: { color: c }, line: { type: "none" } });
    s.addText(t, { x: 4.5, y, w: 1.6, h: 0.26, fontFace: FL, fontSize: 10,
      color: "C8CDD8", margin: 0 });
  });
  s.addText("built正典 v1.8: 実線形19,895枝 / ノード17,745(うち変電所9,139) — 全要素がOSM実体か出典つき介入に遡れる", {
    x: 2.75, y: 7.08, w: 10.0, h: 0.3, fontFace: F, fontSize: 10,
    color: "5A648F", margin: 0 });
  s.addNotes("30秒黙って見せてから一言。「素材はただの線。ここから解ける系統までが本発表」。数字はbuilt正典の実測。");
}

/* ===================== 3. 動機 ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "序", "日本には、公開のバスレベル系統モデルが無い", NAVY);
  const rows = [
    ["米国", "FERC Form 715", "ネットワークモデルの開示義務。バスレベルで研究利用できる", GRN],
    ["欧州", "ENTSO-E", "透明性プラットフォーム＋PyPSA-Eur等の公開モデル群", GRN],
    ["日本", "OCCTO 公表", "連系線容量・需給計画のみ。インピーダンス・変圧器・ノード需要は事業者内部", RED],
  ];
  rows.forEach(([reg, src, body, col], i) => {
    const y = 1.35 + i * 1.25;
    s.addShape(pres.ShapeType.roundRect, { x: 0.9, y, w: 11.6, h: 1.1,
      fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.06 });
    s.addText(reg, { x: 1.2, y: y + 0.12, w: 1.5, h: 0.4, fontFace: F,
      fontSize: 15, bold: true, color: col, margin: 0 });
    s.addText(src, { x: 1.2, y: y + 0.58, w: 2.2, h: 0.35, fontFace: FL,
      fontSize: 11.5, color: MUT, margin: 0 });
    s.addText(body, { x: 3.6, y, w: 8.6, h: 1.1, fontFace: F, fontSize: 13,
      color: INK, margin: 0, valign: "middle" });
  });
  s.addShape(pres.ShapeType.roundRect, { x: 0.9, y: 5.35, w: 11.6, h: 1.15,
    fill: { color: NAVY }, line: { type: "none" }, rectRadius: 0.06 });
  s.addText("一方で OpenStreetMap には、変電所の位置・送電線の経路・発電所が「地理」としては写っている。\n地理トポロジから系統モデルへ — このギャップを埋めるのが本プロジェクト。", {
    x: 1.2, y: 5.35, w: 11.0, h: 1.15, fontFace: F, fontSize: 13.5,
    bold: true, color: "FFFFFF", lineSpacing: 20, margin: 0,
    valign: "middle" });
  foot(s, 3, "1:00");
  s.addNotes("論文（ieee-openaccess）§I の構図そのまま。日本だけ赤。下段で OSM に橋を架けると宣言。");
}

/* ===================== 3. 出発点と設計原則 ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "序", "OSMが持つもの・持たないもの — そして最初に置いた原則", NAVY);
  s.addImage({ path: A + "fig_layer_combined.png", x: 0.9, y: 1.2, w: 11.6,
    h: 4.1 });
  card(s, 0.9, 5.45, 5.6, 1.35, "OSMにあるもの（地理トポロジ）",
    "位置・経路・電圧タグ・回線数タグ・運用者名。\n「どこに何があり、空間的にどう繋がるか」", GRN, 12);
  card(s, 6.9, 5.45, 5.6, 1.35, "OSMに無いもの（電気）",
    "インピーダンス・変圧器特性・ノード需要。\n→ 無いものは推定と明記して分離保持する（捏造ゼロ）", RED, 12);
  foot(s, 4, "1:00");
  s.addNotes("3層（線・変電所・発電所）を見せて、下2枚で線引き。「捏造ゼロ」はここで一度だけ宣言し、以後は行動で見せる。");
}

/* ===================== 4. 年表（5幕） ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "序", "6ヶ月の道筋：5幕 — 各幕は前の幕が露わにした問いに答える", NAVY);
  const acts = [
    ["第1幕", "v1.0", "地理を掘る", "OSM抽出・7段補完・UC/PF一式", "「地図はある」→ モデルにした"],
    ["第2幕", "v1.1–1.4", "電気にして\n標準で渡す", "CIM/CGMES・統一DB・全10地域AC", "作れた → 解けるのか？"],
    ["第3幕", "v1.5–1.6", "誠実さを\n制度にする", "介入台帳・fake-AC検出・二重抽出根治", "解けた → 本当か？"],
    ["第4幕", "v1.7", "公式開示と\n接続する", "様式5・OCCTO容量・実測突合", "正した → 現実と合うか？"],
    ["第5幕", "v1.8", "変電所の\n中へ", "SubSLD法・実証ペア図・node-breaker", "網はできた → 最後の暗箱へ"],
  ];
  acts.forEach(([act, ver, title, body, q], i) => {
    const x = 0.72 + i * 2.42;
    s.addShape(pres.ShapeType.roundRect, { x, y: 1.35, w: 2.28, h: 3.15,
      fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.07 });
    s.addShape(pres.ShapeType.rect, { x, y: 1.35, w: 2.28, h: 0.12,
      fill: { color: ACT[i] }, line: { type: "none" } });
    s.addText(`${act}　${ver}`, { x: x + 0.15, y: 1.58, w: 2.0, h: 0.3,
      fontFace: FL, fontSize: 10.5, bold: true, color: MUT, margin: 0 });
    s.addText(title, { x: x + 0.15, y: 1.9, w: 2.0, h: 0.85, fontFace: F,
      fontSize: 14.5, bold: true, color: INK, lineSpacing: 19, margin: 0 });
    s.addText(body, { x: x + 0.15, y: 2.85, w: 2.0, h: 0.9, fontFace: F,
      fontSize: 10, color: MUT, lineSpacing: 14, margin: 0 });
    s.addText(q, { x: x + 0.15, y: 3.85, w: 2.0, h: 0.6, fontFace: F,
      fontSize: 9.5, italic: true, color: NAVY, lineSpacing: 13, margin: 0 });
  });
  // 実時間ストリップ（2026-03-01 → 09-01 を x 0.9–12.4 に線形写像）
  const y0 = 5.35;
  s.addShape(pres.ShapeType.line, { x: 0.9, y: y0, w: 11.5, h: 0,
    line: { color: INK, width: 1.5 } });
  ["3月", "4月", "5月", "6月", "7月", "8月"].forEach((m, i) => {
    const x = 0.9 + 11.5 * (i * 31) / 184;
    s.addShape(pres.ShapeType.line, { x, y: y0 - 0.06, w: 0, h: 0.12,
      line: { color: MUT, width: 1 } });
    s.addText(m, { x: x - 0.3, y: y0 + 0.14, w: 0.8, h: 0.25, fontFace: F,
      fontSize: 9.5, color: MUT, margin: 0 });
  });
  // タグ打点（日付は実日、幕色）
  const tags = [
    ["v1.0.0", 3, 0], ["v1.1.0", 94, 1], ["v1.2.1", 99, 1], ["v1.3.0", 100, 1],
    ["v1.4.0", 102, 1], ["v1.5.0", 130, 2], ["v1.6.0", 131, 2],
    ["v1.7.0", 172, 3], ["v1.8.0", 179, 4],
  ];
  tags.forEach(([v, d, a]) => {
    const x = 0.9 + 11.5 * d / 184;
    s.addShape(pres.ShapeType.ellipse, { x: x - 0.055, y: y0 - 0.055,
      w: 0.11, h: 0.11, fill: { color: ACT[a] }, line: { type: "none" } });
  });
  [["v1.0.0", 3], ["v1.1–1.4", 98], ["v1.5–1.6", 130.5], ["v1.7.0", 172],
   ["v1.8.0", 179]].forEach(([lab, d]) => {
    const x = 0.9 + 11.5 * d / 184;
    s.addText(lab, { x: x - 0.55, y: y0 - 0.45, w: 1.1, h: 0.26, fontFace: FL,
      fontSize: 9, color: INK, align: "center", margin: 0 });
  });
  s.addText("6月上旬に5連リリース（v1.1.0〜v1.4.0）— 標準化と解ける化の集中期", {
    x: 0.9, y: 6.15, w: 11.5, h: 0.3, fontFace: F, fontSize: 10.5, color: MUT,
    margin: 0 });
  foot(s, 5, "1:00");
  s.addNotes("この1枚が地図。以降のスライドは左上バッジ（幕色つき）で現在地を示す。斜体の問いの連鎖だけ読み上げる。");
}

/* ===================== 5. 第1幕: 抽出パイプライン ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "第1幕 v1.0", "地理を掘る：抽出から解析まで、最初から一本のパイプライン", ACT[0]);
  s.addImage({ path: A + "fig_pipeline_flow.png", x: 0.62, y: 1.3, w: 12.1,
    h: 5.02 });
  s.addText("Overpassタイル分割抽出 → 7段の属性補完（Nominatim / MLIT P03、欠損87%削減）→ Haversine端点マッチング → 電圧クラス別の合成パラメータ → pandapower / MATPOWER / Ybus / UC", {
    x: 0.9, y: 6.4, w: 11.6, h: 0.55, fontFace: F, fontSize: 11.5, color: INK,
    lineSpacing: 16, margin: 0 });
  foot(s, 6, "1:30");
  s.addNotes("論文 §III–VI をこの1枚に圧縮。「電気パラメータは合成＝推定と明記」を図の緑ブロックを指して言う。87%は補完の欠損削減率（論文値）。");
}

/* ===================== 6. 第1幕: v1.0 の結果 ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "第1幕 v1.0", "初版で出た数字：全国10地域・50/60 Hz を1つのデータセットに", ACT[0]);
  stat(s, 0.9, 1.35, 2.75, "6,962", "変電所 feature", "測定 v1.2 で確定", INK);
  stat(s, 3.85, 1.35, 2.75, "40,077", "送電線", "測定 v1.2 で確定", INK);
  stat(s, 6.8, 1.35, 2.75, "19,138", "発電所", "測定 v1.2 で確定", INK);
  stat(s, 9.75, 1.35, 2.75, "10 / 10", "地域（50/60 Hz 両系統）", "v1.0.0", NAVY);
  // 全国UC
  s.addShape(pres.ShapeType.roundRect, { x: 0.9, y: 3.0, w: 11.6, h: 2.5,
    fill: { color: "FFFFFF" }, line: { color: NAVY, width: 1.2 },
    rectRadius: 0.06 });
  s.addText("全国ユニットコミットメント（757機・10地域・24時間・MILP）", {
    x: 1.15, y: 3.15, w: 11.0, h: 0.32, fontFace: F, fontSize: 13.5,
    bold: true, color: NAVY, margin: 0 });
  const uc = [
    ["銅板（連系線制約なし）", "7.65 兆円", "9.28 s"],
    ["連系線制約あり", "7.76 兆円", "8.72 s"],
    ["混雑コストプレミアム", "+1.40 %", "—"],
  ];
  s.addTable(uc.map(r => r.map(c => ({ text: c, options: {
    fontFace: F, fontSize: 12.5, color: INK, margin: 0.06 } }))), {
    x: 1.15, y: 3.6, w: 8.2, h: 1.6, colW: [4.2, 2.2, 1.8],
    border: { type: "solid", color: "DDDDE2", pt: 0.75 },
    fill: { color: "FFFFFF" } });
  s.addText("最適解まで 10 秒未満。\n9連系線すべてがピーク需要時に利用率 100 %。", {
    x: 9.6, y: 3.7, w: 2.75, h: 1.4, fontFace: F, fontSize: 11, color: MUT,
    lineSpacing: 16, margin: 0 });
  s.addText("限界も初版から明記：インピーダンスは合成推定・端点マッチング誤接続 ~2–3 %・運用計画には使えない（研究・教育用）。", {
    x: 0.9, y: 5.8, w: 11.6, h: 0.6, fontFace: F, fontSize: 12, color: RED,
    lineSpacing: 17, margin: 0 });
  foot(s, 7, "1:30");
  s.addNotes("数値は論文 Table I / II。本文の 8,164 は誤記（同論文の表合計は 6,962）で、この版から 6,962 に統一している。限界の明記が第3幕への伏線。");
}

/* ===================== 7. 第2幕: 標準で渡す ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "第2幕 v1.2", "標準で渡す：CIM/CGMES は輸出先ではなく検証器だった", ACT[1]);
  card(s, 0.9, 1.3, 5.6, 1.7, "IEC 61970 CIM (CGMES 2.4.15) 書き出し",
    "EQ + GL の全10地域。決定的 UUIDv5 mRID・dangling参照 0。\n独立実装 pandapower cim2pp で読み戻して検証", ACT[1], 12.5);
  card(s, 0.9, 3.15, 5.6, 1.7, "Level-2：解ける潮流ケース",
    "EQ/TP/SSH/SV。cim2pp ラウンドトリップ後に runpp が収束\n（初出 okinawa 81母線 → 境界セット整備で全10地域）", ACT[1], 12.5);
  card(s, 0.9, 5.0, 5.6, 1.7, "統一DB（R/C/D 3層・SQLite）",
    "生feature（不変）/ キュレーション / 導出を分離。232,139行の\n人手修正が OSM 再取得を生き延びる — 出所つきで", ACT[1], 12.5);
  // 右: ラウンドトリップが見つけたバグ
  s.addShape(pres.ShapeType.roundRect, { x: 6.9, y: 1.3, w: 5.6, h: 5.4,
    fill: { color: "FFF3F3" }, line: { color: RED, width: 1.1 },
    rectRadius: 0.06 });
  s.addText("ラウンドトリップ検証が捕まえた電気的バグ（v1.2.1）", {
    x: 7.15, y: 1.45, w: 5.1, h: 0.55, fontFace: F, fontSize: 13, bold: true,
    color: RED, margin: 0 });
  s.addText([
    ["並列回線・変圧器バンクのインピーダンスが最大4倍（束等価を書かず素の値を出していた）"],
    ["Conductor.length がメートルのまま → km と解釈され1000倍で往復"],
    ["in_service が落ち、停止線・停止負荷がインポートで再充電"],
    ["需要スケール版が発電3.5倍のまま出荷、slack が72%を吸収（→ load×1.05 に再配分）"],
    ["『native収束』を名乗っていた2地域は、バグ入り往復が偶然収束していただけ"],
  ].map(([t], i) => ({ text: t, options: {
    bullet: { characterCode: "2022", indent: 12 }, breakLine: true,
    fontFace: F, fontSize: 11.5, color: INK, lineSpacing: 16 } })), {
    x: 7.15, y: 2.1, w: 5.15, h: 3.6, margin: 0, valign: "top" });
  s.addText("→ 修正後は vm差 < 1e-4 pu の電気的同一性を回帰テストで固定。\n標準に書き出せる＝独立実装に読ませて突き合わせられる、ということ。", {
    x: 7.15, y: 5.75, w: 5.15, h: 0.8, fontFace: F, fontSize: 11.5,
    bold: true, color: NAVY, lineSpacing: 16, margin: 0 });
  foot(s, 8, "1:30");
  s.addNotes("この枚の主張は右の赤枠。「標準対応しました」ではなく「標準が検証器になった」。5つのバグはどれも自前レンダラだけなら気づけない。");
}

/* ===================== 8. 第2幕: 解ける化と外部検証 ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "第2幕 v1.3–1.4", "解ける化：トポロジのバグを潰したら 10/10 地域が解けた", ACT[1]);
  // 左: 修正と検証
  card(s, 0.9, 1.3, 6.2, 1.4, "並列回線の数え方（v1.3）",
    "1本のwayがノード対をジグザグに跨ぐと並列数が水増しされていた。\n次数2連鎖の縮約が回線多重度を1にリセットするのも修正 → 同鉄塔2回線の容量が戻る", ACT[1], 12);
  card(s, 0.9, 2.82, 6.2, 1.4, "電圧タグ解釈の統一（v1.3）",
    "\"66000;154000\" は最高階級154 kVに解決、\",\" は値区切り\n（\"77000,6600\" → 770006.6 kV という連結事故を根絶）。6実装2意味論 → 1実装", ACT[1], 12);
  card(s, 0.9, 4.34, 6.2, 1.4, "実データとの外部検証（v1.4）",
    "東電の線別潮流と回廊利用率の順位相関、関西の開示線名と照合\n（≥154 kV 幹線38本で97%一致）— スコアカードをJSONで同梱", GRN, 12);
  s.addImage({ path: A + "fig_satellite_validation.png", x: 0.9, y: 5.88,
    w: 6.2, h: 1.14, sizing: { type: "cover", w: 6.2, h: 1.14 } });
  s.addShape(pres.ShapeType.rect, { x: 0.9, y: 6.72, w: 6.2, h: 0.3,
    fill: { color: "000000", transparency: 45 }, line: { type: "none" } });
  s.addText("v1.1 比較タブ：衛星写真上で位置を目視検証（左から鹿島・火力構内・変電所）", {
    x: 1.0, y: 6.72, w: 6.0, h: 0.3, fontFace: F, fontSize: 8.5,
    color: "FFFFFF", margin: 0, valign: "middle" });
  // 右: 全国AC図
  s.addImage({ path: A + "fig_cim_national_pf.png", x: 7.55, y: 1.35,
    w: 5.15, h: 5.07 });
  s.addText("全国ACPF：14,647母線・10/10地域が解けた（v1.4, CGMES往復後の実測図）", {
    x: 7.35, y: 6.5, w: 5.3, h: 0.5, fontFace: F, fontSize: 10.5, color: MUT,
    lineSpacing: 14, margin: 0 });
  foot(s, 9, "1:30");
  s.addNotes("左下の衛星3連画像は v1.1 の比較タブ（衛星写真で位置を目視検証）。右図は自慢の1枚だが、次の幕でこれを自分で疑いにいく。");
}

/* ===================== 9. 第3幕: 収束は正しさではない ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "第3幕 v1.5", "収束は正しさではない — 誠実さを仕組みに変えた", ACT[2]);
  s.addShape(pres.ShapeType.roundRect, { x: 0.9, y: 1.25, w: 11.6, h: 1.0,
    fill: { color: NAVY }, line: { type: "none" }, rectRadius: 0.06 });
  s.addText("モデルを「繋がって・解けて・完全に」見せる機構は19個あった。ひとつずつ台帳に載せ、OFFスイッチを付けた。", {
    x: 1.2, y: 1.25, w: 11.0, h: 1.0, fontFace: F, fontSize: 14.5,
    bold: true, color: "FFFFFF", margin: 0, valign: "middle" });
  card(s, 0.9, 2.5, 5.6, 1.6, "介入台帳 MODEL_INTERVENTIONS.md",
    "最近傍発電機接続・合成需要配分・既定容量・成分別slack・\n刈り込み梯子…19機構すべてに根拠・台帳・OFFスイッチ", ACT[2], 12);
  card(s, 0.9, 4.25, 5.6, 1.6, "fake-AC ガード",
    "AC解は解前需要の95%以上を給電していなければ無効。\nserved_frac を全結果JSONに同梱 — 収束≠正しさ", ACT[2], 12);
  // 右: east ACの再解釈（一番痛い話）
  s.addShape(pres.ShapeType.roundRect, { x: 6.9, y: 2.5, w: 5.6, h: 3.35,
    fill: { color: "FFF3F3" }, line: { color: RED, width: 1.1 },
    rectRadius: 0.06 });
  s.addText("一番痛かった再解釈：東日本フルAC", { x: 7.15, y: 2.65, w: 5.1,
    h: 0.32, fontFace: F, fontSize: 13, bold: true, color: RED, margin: 0 });
  s.addText("誇っていた「フルAC 99.0 % 給電」を7変種プローブで解体したら、bboxで誤配置された需要地理の上に立っていた。正直な地理ではフルACは解けない — dc_fallback と正直に報告する側に倒した。\n\n途中「復活した」と見えた解も、飛騨回廊に偶然2.3 GWのバラストを置く重み付けバグだった。出荷前に棄却。", {
    x: 7.15, y: 3.05, w: 5.15, h: 2.3, fontFace: F, fontSize: 11.5,
    color: INK, lineSpacing: 17, margin: 0 });
  s.addText("結果を良くする変更より、結果を悪くする訂正の方が価値がある。", {
    x: 7.15, y: 5.35, w: 5.15, h: 0.4, fontFace: F, fontSize: 11.5,
    bold: true, color: NAVY, margin: 0 });
  s.addText("あわせて v1.5 で配布基盤も整備：自己完結バンドル（SHA256 MANIFEST）・pandapower/MATLAB両チュートリアルを実ダウンロード→新環境E2Eで検証してから公開。", {
    x: 0.9, y: 6.05, w: 11.6, h: 0.6, fontFace: F, fontSize: 11.5, color: MUT,
    lineSpacing: 16, margin: 0 });
  foot(s, 10, "2:00");
  s.addNotes("プロジェクトの転回点。8枚目の全国AC図を自分で解体した話。「結果を悪くする訂正」の一文をゆっくり。ここが第5幕の『完全性を主張せず測定する』の源流。");
}

/* ===================== 10. 第3幕: 二重抽出の根治 ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "第3幕 v1.6", "西日本 2,531成分の謎：バグは1つ、見え方は3つ", ACT[2]);
  // 因果チェーン
  const chain = [
    ["観測", "西日本が2,531の連結成分に割れる\n東西で損失が不自然に小さい", RED],
    ["根因", "地域bboxの重なりが同一設備を二重登録\n（同じosm_idが隣接2地域の抽出に載る）", NAVY],
    ["処置", "座標+電圧の同一ノード・同経路の同一枝を統合\n（実並列回線 par>1 の8,898本は無傷）", GRN],
  ];
  chain.forEach(([t, b, col], i) => {
    const x = 0.9 + i * 4.0;
    s.addShape(pres.ShapeType.roundRect, { x, y: 1.3, w: 3.7, h: 1.55,
      fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.06 });
    s.addText(t, { x: x + 0.2, y: 1.42, w: 3.3, h: 0.3, fontFace: F,
      fontSize: 12.5, bold: true, color: col, margin: 0 });
    s.addText(b, { x: x + 0.2, y: 1.76, w: 3.35, h: 1.0, fontFace: F,
      fontSize: 10.5, color: INK, lineSpacing: 15, margin: 0 });
    if (i < 2) s.addText("→", { x: x + 3.68, y: 1.85, w: 0.35, h: 0.4,
      fontFace: FL, fontSize: 18, bold: true, color: MUT, margin: 0 });
  });
  stat(s, 0.9, 3.15, 3.7, "2,531 → 544", "西日本の連結成分数", "v1.6 dedup 前→後", NAVY);
  stat(s, 4.85, 3.15, 3.7, "9,793 → 8,353", "西日本の線数（二重計上の解消）", "v1.6 dedup 前→後", NAVY);
  stat(s, 8.8, 3.15, 3.7, "+5.7 %", "東日本AC損失（増える＝正しくなる）", "v1.6：人工的な半減の解消", RED);
  s.addText("損失が増えるのは劣化ではない。二重登録がインピーダンスを実効的に半減させていた — その訂正である。既定ONへの昇格は4島のbefore/afterプローブと44ゲートで判定してから。", {
    x: 0.9, y: 4.6, w: 11.6, h: 0.6, fontFace: F, fontSize: 12, color: INK,
    lineSpacing: 17, margin: 0 });
  s.addShape(pres.ShapeType.roundRect, { x: 0.9, y: 5.35, w: 11.6, h: 1.2,
    fill: { color: CODE }, line: { type: "none" }, rectRadius: 0.06 });
  s.addText([
    { text: "方法論として一般化して公開　", options: { bold: true } },
    { text: "OSM由来系統モデルの落とし穴4クラス／診断手法5種（変種プローブ・プロセス分離・served_fracガード・DC角トリアージ・不変量比較）／他プロジェクト向け12項目チェックリスト — 負の結果も記録", options: {} },
  ], { x: 1.15, y: 5.35, w: 11.1, h: 1.2, fontFace: F, fontSize: 11.5,
    color: INK, lineSpacing: 17, margin: 0, valign: "middle" });
  foot(s, 11, "1:30");
  s.addNotes("デバッグ譚として一番話せる枚。「+5.7%が訂正」の反直感を丁寧に。方法論文書は osm_grid_pitfalls_methodology_2026-07-10.md。");
}

/* ===================== 11. 第4幕: 公式開示と接続 ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "第4幕 v1.7", "公式開示と接続する：開示データは「上書き」ではなく「照合」", ACT[3]);
  card(s, 0.9, 1.3, 5.6, 1.75, "様式5 インピーダンス表（全10 TSO）",
    "1,009線・213変圧器を正規化し、実証接続89本を canon に適用。\n再生成のたびに再適用されるパイプライン段として組込（黙って消えない）", ACT[3], 12);
  card(s, 0.9, 3.2, 5.6, 1.75, "EGGC：証拠ゲート付きの線形照合",
    "開示コードがOSM実線形に吸着するのは「断片＝開示線そのもの」\n（off-main比 ≥ 0.7）のときだけ。幾何の捏造なし・14本を台帳化", ACT[3], 12);
  card(s, 0.9, 5.1, 5.6, 1.75, "UC定式の訂正",
    "地域収支が不等式で「余剰のタダ捨て」を許していた → 等式＋\n明示スピル変数に。九州の幻の5.7 GW発電と関門2倍違反が消えた", RED, 12);
  // 右: 連系線の一次資料照合
  s.addShape(pres.ShapeType.roundRect, { x: 6.9, y: 1.3, w: 5.6, h: 3.65,
    fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.06 });
  s.addText("連系線を一次資料で引き直す（OCCTO公表28レコード）", {
    x: 7.15, y: 1.45, w: 5.2, h: 0.35, fontFace: F, fontSize: 12.5,
    bold: true, color: NAVY, margin: 0 });
  s.addText([
    ["関門：対称2,780 MW → 方向別 850 / 2,850 MW（順方向を3.3倍過大評価していた）"],
    ["南福光はBTB直流300 MW — ACスルーで575–1,210 MW流れていた母線を分割"],
    ["OCCTO直線の合成連系線7本は実形と二重計上 → in_service=False で退役"],
    ["阿南紀北直流幹線に実OSM線形（海底46 km＋架空50.6 km）"],
  ].map(([t]) => ({ text: t, options: {
    bullet: { characterCode: "2022", indent: 12 }, breakLine: true,
    fontFace: F, fontSize: 11.5, color: INK, lineSpacing: 16 } })), {
    x: 7.15, y: 1.95, w: 5.15, h: 2.9, margin: 0, valign: "top" });
  s.addShape(pres.ShapeType.roundRect, { x: 6.9, y: 5.1, w: 5.6, h: 1.75,
    fill: { color: "FFFFFF" }, line: { color: NAVY, width: 1.2 },
    rectRadius: 0.06 });
  s.addText("容量の出典主義", { x: 7.15, y: 5.25, w: 5.2, h: 0.3, fontFace: F,
    fontSize: 12.5, bold: true, color: NAVY, margin: 0 });
  s.addText("発電容量・変圧器銘板・連系線容量はすべて「出典URL＋原文引用つきレコード」の provenance DB 経由でだけモデルに入る。出典が無い値は既定値のまま、既定値と明記される。", {
    x: 7.15, y: 5.6, w: 5.2, h: 1.15, fontFace: F, fontSize: 11.5, color: INK,
    lineSpacing: 16, margin: 0 });
  foot(s, 12, "1:30");
  s.addNotes("第3幕の規律が開示データにも適用される、が主題。「開示があるから正しい」ではなく開示も証拠ゲートを通す（EGGC）。UC訂正は開示容量と突き合わせて初めて見えた。");
}

/* ===================== 12. 第4幕: 観測と突合し、動かし続ける ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "第4幕 v1.7→", "観測と突合し、動かし続ける", ACT[3]);
  s.addImage({ path: A + "flow_map_demo.gif", x: 0.9, y: 1.3, w: 7.2,
    h: 4.89 });
  s.addText("flow_map.html — 24時間ノード潮流・方向つきアニメーション（Pages実画面・スライドショーで動きます）", {
    x: 0.9, y: 6.25, w: 7.2, h: 0.3, fontFace: F, fontSize: 10.5, color: MUT,
    margin: 0 });
  card(s, 8.4, 1.3, 4.1, 1.8, "燃料別の実績注入",
    "9/10 TSOのエリア需給実績から燃料構成と原子力停止が日次断面へ自動反映。ゾーン純位置は公表連系実績と39–129 MWで一致（v1.7検証）", GRN, 11.5);
  card(s, 8.4, 3.3, 4.1, 1.55, "リアルタイム断面",
    "でんき予報の実績需要スナップショットでNOW断面PFを毎時再計算（launchd常駐・v1.8後）", ACT[3], 11.5);
  card(s, 8.4, 5.05, 4.1, 1.55, "観測方向の照合",
    "モデル潮流の向きを公表実績の向きと突合し、一致/不一致を地図に描く — 隠さず可視化", ACT[3], 11.5);
  foot(s, 13, "1:00");
  s.addNotes("静的データセットが「動く系統の観測器」になった枚。39–129 MWの一致幅は検証時点の実測。デモできるならここで flow_map を開く。");
}

/* ===================== 13. 第5幕: 変電所の中へ ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "第5幕 v1.8", "最後の暗箱：変電所の中へ — SubSLD法", ACT[4]);
  s.addImage({ path: A + "geo_shinkeiyo.png", x: 0.9, y: 1.35, w: 3.85,
    h: 4.11 });
  s.addImage({ path: A + "sld_shinkeiyo.png", x: 4.95, y: 1.35, w: 3.25,
    h: 4.11 });
  s.addText("実証ペア図（新京葉 500/275/154/66 kV）：構内幾何 × 単線結線図", {
    x: 0.9, y: 5.55, w: 7.3, h: 0.3, fontFace: F, fontSize: 10.5, color: MUT,
    margin: 0 });
  // 右: 方法の芯
  s.addShape(pres.ShapeType.roundRect, { x: 8.55, y: 1.35, w: 3.95, h: 1.5,
    fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.06 });
  meq(s, 8.75, 1.5, 3.6, [
    ["F", { i: 1 }], ["(", {}], ["O", { i: 1 }], [") = ", {}],
    ["S", { i: 1 }], ["*", { sup: 1 }],
  ], 17);
  s.addText("証拠閉包：witness を持つ要素だけを出す。健全性（捏造ゼロ）は構成的に成立し、完全性は主張せず測定する", {
    x: 8.75, y: 2.0, w: 3.6, h: 0.85, fontFace: F, fontSize: 10.5, color: INK,
    lineSpacing: 14, margin: 0 });
  stat(s, 8.55, 3.1, 3.95, "7,239", "全サイトの構造抽出＋ペア図", "構造DB v1.8（feature数とは別定義）", ACT[4]);
  stat(s, 8.55, 4.55, 3.95, "≈ 4 秒", "全国抽出（決定的・冪等）", "v1.8", NAVY);
  s.addText("推定は推定と明記（推定母線は破線・inferred-topology）。node-breaker層は CIM の BusbarSection / Bay / Terminal として書き出し、第2幕の標準ラインに合流。", {
    x: 0.9, y: 6.05, w: 11.6, h: 0.6, fontFace: F, fontSize: 12, color: INK,
    lineSpacing: 17, margin: 0 });
  s.addText("→ 手法の詳細は姉妹デッキ SubSLD_paper_talk.pptx（16枚）と論文 papers/subsld/（IEEEtran 6p）", {
    x: 0.9, y: 6.62, w: 11.6, h: 0.32, fontFace: F, fontSize: 11, color: MUT,
    margin: 0 });
  foot(s, 14, "2:00");
  s.addNotes("7,239 は構造DBのサイト数で、第1幕の 6,962（データセットfeature・v1.2測定）とは定義が違う — 聞かれたら即答する。深掘りは姉妹デッキへ誘導。");
}

/* ===================== 15. 終幕: AGCとは ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "終幕 v1.9へ", "最後の問い：発電所が突然落ちたら、この系統は生き残れるか", NAVY);
  s.addShape(pres.ShapeType.roundRect, { x: 0.9, y: 1.25, w: 11.6, h: 1.3,
    fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.06 });
  s.addText([
    { text: "電気は貯められない。", options: { bold: true } },
    { text: "作る量と使う量がズレると、周波数(50/60 Hz)がズレる。ズレすぎると発電機が次々止まり、大停電になる。\n", options: {} },
    { text: "AGC（自動発電制御）", options: { bold: true, color: NAVY } },
    { text: " ＝ 周波数のズレを見て発電所の出力を自動で増減し、系統を守る仕組み。", options: {} },
  ], { x: 1.2, y: 1.25, w: 11.0, h: 1.3, fontFace: F, fontSize: 14,
    color: INK, lineSpacing: 22, margin: 0, valign: "middle" });
  // 3段チェーン(平易な言葉で)
  const steps = [
    ["① 計画する", "UC", "「今日どの発電所を動かす？」\n24時間の起動停止を最適化。\nこの選択が、事故時に系統を支える\n「慣性」と「調整余力」も決める", ACT[0]],
    ["② 流してみる", "潮流計算", "「その電気、送りきれる？」\n計画した発電を実際の送電線網に\n流して確認 — 4島すべて100%供給", ACT[1]],
    ["③ 事故らせる", "AGC", "「突然、最大の発電所が落ちたら？」\n周波数の急落と自動復帰を秒単位で\n再現 — 制御の仕組みは電気学会の\n標準モデル(AGC30)に準拠", ACT[4]],
  ];
  steps.forEach(([t, tag, b, col], i) => {
    const x = 0.9 + i * 4.0;
    s.addShape(pres.ShapeType.roundRect, { x, y: 2.85, w: 3.6, h: 2.6,
      fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.07 });
    s.addShape(pres.ShapeType.rect, { x, y: 2.85, w: 3.6, h: 0.12,
      fill: { color: col }, line: { type: "none" } });
    s.addText(t, { x: x + 0.2, y: 3.08, w: 2.2, h: 0.35, fontFace: F,
      fontSize: 15, bold: true, color: INK, margin: 0 });
    s.addText(tag, { x: x + 2.3, y: 3.1, w: 1.15, h: 0.32, fontFace: FL,
      fontSize: 11, bold: true, color: col === "9A9AA6" ? MUT : col,
      align: "right", margin: 0 });
    s.addText(b, { x: x + 0.2, y: 3.5, w: 3.25, h: 1.85, fontFace: F,
      fontSize: 11, color: MUT, lineSpacing: 16, margin: 0 });
    if (i < 2) s.addText("→", { x: x + 3.62, y: 3.85, w: 0.4, h: 0.4,
      fontFace: FL, fontSize: 20, bold: true, color: MUT, margin: 0 });
  });
  s.addShape(pres.ShapeType.roundRect, { x: 0.9, y: 5.75, w: 11.6, h: 1.05,
    fill: { color: NAVY }, line: { type: "none" }, rectRadius: 0.06 });
  s.addText("この3つは本来、別々の組織の、別々の非公開データの仕事。ここでは地図から作った1つの公開モデルの上で、1コマンドで全部つながって動く。", {
    x: 1.2, y: 5.75, w: 11.0, h: 1.05, fontFace: F, fontSize: 14, bold: true,
    color: "FFFFFF", lineSpacing: 21, margin: 0, valign: "middle" });
  foot(s, 15, "1:00");
  s.addNotes("AGCを知らない聴衆向けの1枚。「電気は貯められない」から始める。次の枚で実際に事故らせる。");
}

/* ===================== 16. 終幕: 事故を起こしてみた ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "終幕 v1.9へ", "事故を起こしてみた：最大の発電所を、いきなり落とす", NAVY);
  // 左: 地図(島の色=波形の色)
  s.addImage({ path: A + "fig_agc_map.png", x: 0.55, y: 1.2, w: 4.35,
    h: 5.44 });
  // 右: 注釈付き波形
  s.addImage({ path: A + "fig_agc_story.png", x: 5.05, y: 1.35, w: 7.75,
    h: 4.45 });
  s.addText("地図の島の色 ＝ グラフの線の色。★が落とした発電所の実在の場所。", {
    x: 5.15, y: 5.85, w: 7.6, h: 0.3, fontFace: F, fontSize: 11.5, bold: true,
    color: INK, margin: 0 });
  s.addText("小さな北海道(4.4 GW)は苫東厚真を失うと負荷遮断まで落ち込む。大きな東日本(59 GW)は3倍の規模(富津 5,040 MW)を失っても踏みとどまる — 系統の大きさ(慣性)の差が、そのまま運命の差になる。", {
    x: 5.15, y: 6.2, w: 7.6, h: 0.6, fontFace: F, fontSize: 11,
    color: MUT, lineSpacing: 16, margin: 0 });
  foot(s, 16, "1:30");
  s.addNotes("2018年9月6日の実話(北海道ブラックアウト)から入る。「あの構図が、地図から作ったモデルで出る」。動特性は典型値の構造実証、プラント粒度=ユニットN-1の上界、は聞かれたら答える。");
}

/* ===================== 17. 動揺も解ける(AGC-N) ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "終幕 v1.9へ", "動揺も解ける：同じ事故を、54機を1機ずつ解く（AGC30 → AGC-N）", NAVY);
  s.addImage({ path: A + "fig_swing_hokkaido.png", x: 0.85, y: 1.15, w: 11.6,
    h: 5.28 });
  s.addText("AGC30の機種モデルをUCがオンラインにした全プラントへ1機ずつ与え、実網のKron縮約Ybus上で動揺方程式と共シミュレーション。潮流解との初期化整合は厳密(max 0.0 MW)。", {
    x: 0.9, y: 6.5, w: 11.6, h: 0.35, fontFace: F, fontSize: 11.5, color: INK,
    margin: 0 });
  s.addText("下段=各機の相差角(±40°の動揺→減衰整定)。多機版はCOI簡約版よりやや深く沈む(−3.0 vs −2.5 Hz) — 定Z負荷とGF幅の実装差で、帳簿に開示。", {
    x: 0.9, y: 6.82, w: 11.6, h: 0.3, fontFace: F, fontSize: 10.5, color: MUT,
    margin: 0 });
  foot(s, 17, "1:00");
  s.addNotes("「動揺がないのが違和感」への回答。UFLSの3段が1.6/2.0/2.7秒に入るのが拡大で見える。AGC100の話が出たら『これはAGC-54。Nは任意で、東なら数百機』。");
}

/* ===================== 18. 全国・全機の動揺 ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "終幕 v1.9へ", "系統ごと、全部解く：4島・542機の動揺", NAVY);
  s.addImage({ path: A + "fig_swing_national.png", x: 1.9, y: 1.05, w: 9.55,
    h: 5.80 });
  s.addText("東182機は富津3,893MWを失っても−0.45Hzで踏みとどまり、全機がうねりながら回復する。西302機は±0.3Hzの機間動揺が10秒で減衰。弱結合の小規模機7機は脱調保護が切り離す(切離しの瞬間まで描画・全経過は帳簿)。", {
    x: 0.9, y: 7.0 - 0.05, w: 11.6, h: 0.55, fontFace: F, fontSize: 11,
    color: INK, lineSpacing: 15, margin: 0 });
  foot(s, 18, "1:00");
  s.addNotes("west はDC断面初期化(フルACは不成立が正典)と断面ごとに開示。542=53+182+302+5。「AGC100?」→「これはAGC-542」。");
}

/* ===================== 19. 実況: 事故が地図の上を走る ===================== */
{
  const s = pres.addSlide();
  s.background = { color: "0A0D1A" };
  // GIF 960x720 — スライドショー再生でアニメーション
  s.addImage({ path: A + "agc_hokkaido_trip.gif", x: 3.53, y: 0.15, w: 9.3,
    h: 6.98 });
  s.addText("実況リプレイ", { x: 0.55, y: 0.7, w: 2.9, h: 0.5, fontFace: F,
    fontSize: 24, bold: true, color: "FFFFFF", margin: 0 });
  s.addText("苫東厚真の脱落を、北海道の\n実系統地図の上で再生する。", {
    x: 0.57, y: 1.35, w: 2.95, h: 0.85, fontFace: F, fontSize: 13,
    color: "C8CDD8", lineSpacing: 19, margin: 0 });
  [["線の色", "周波数(青白50Hz → 深赤47.5Hz)"],
   ["✕", "落ちた発電所(実座標)"],
   ["消える白点", "UFLSで遮断された変電所ぶん"],
   ["時間軸", "直後スロー→復帰タイムラプス"]].forEach(([k, v], i) => {
    const y = 2.5 + i * 0.62;
    s.addText(k, { x: 0.57, y, w: 1.6, h: 0.3, fontFace: F, fontSize: 11.5,
      bold: true, color: "FFFFFF", margin: 0 });
    s.addText(v, { x: 0.57, y: y + 0.28, w: 2.95, h: 0.3, fontFace: F,
      fontSize: 10.5, color: "8E96B8", margin: 0 });
  });
  s.addText("遮断量はシミュレーション実値。\nどの変電所を切るかは非公開のため\n消灯箇所は演出(画面内にも明記)。", {
    x: 0.57, y: 5.3, w: 2.95, h: 1.0, fontFace: F, fontSize: 10,
    color: "5A648F", lineSpacing: 14, margin: 0 });
  s.addText("スライドショー再生で動きます(GIF)", { x: 0.57, y: 6.6, w: 2.9,
    h: 0.3, fontFace: F, fontSize: 10, italic: true, color: "8E96B8",
    margin: 0 });
  foot(s, 19, "1:00");
  s.addNotes("ここは喋らず30秒流す。止め絵になる環境ではPDF版の1コマ目が出るので「動画はGIF参照」と言う。");
}

/* ===================== 18. いまの姿（スタック） ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "現在", "いまの姿：1コマンドで再生成できる5層スタック", NAVY);
  const layers = [
    ["観測・UI", "Pages: flow map（毎時更新）/ SubSLDビューア / エディタ / ダウンロード", ACT[4]],
    ["標準出力", "CIM/CGMES EQ+GL＋Level-2（node-breaker層込み）/ MATPOWER / GeoJSON / Ybus", ACT[3]],
    ["モデル", "built canon（介入台帳つき）/ 全国UC / 島別PF / AGC連鎖 / 変電所構造DB", ACT[2]],
    ["統一DB", "SQLite R/C/D 3層 — 生feature不変・キュレーション出所つき・導出は再生成可能", ACT[1]],
    ["基底データ", "OSMスナップショット + 開示（様式5・OCCTO）+ 出典つき容量/銘板DB", ACT[0]],
  ];
  layers.forEach(([t, b, col], i) => {
    const y = 1.3 + i * 0.98;
    s.addShape(pres.ShapeType.roundRect, { x: 0.9, y, w: 9.0, h: 0.86,
      fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.06 });
    s.addShape(pres.ShapeType.rect, { x: 0.9, y, w: 0.14, h: 0.86,
      fill: { color: col }, line: { type: "none" } });
    s.addText(t, { x: 1.25, y, w: 1.75, h: 0.86, fontFace: F, fontSize: 12.5,
      bold: true, color: INK, margin: 0, valign: "middle" });
    s.addText(b, { x: 3.1, y, w: 6.7, h: 0.86, fontFace: F, fontSize: 11,
      color: MUT, margin: 0, valign: "middle", lineSpacing: 15 });
  });
  s.addShape(pres.ShapeType.roundRect, { x: 10.2, y: 1.3, w: 2.3, h: 4.78,
    fill: { color: CODE }, line: { type: "none" }, rectRadius: 0.06 });
  s.addText("regenerate_all.py", { x: 10.35, y: 1.45, w: 2.0, h: 0.55,
    fontFace: FM, fontSize: 11, bold: true, color: INK, margin: 0 });
  s.addText("全層を1コマンドで順に再生成し、git HEAD と各段の生成時刻を MODEL_VERSION に刻印 — 鮮度ズレを可視化", {
    x: 10.35, y: 2.0, w: 2.0, h: 2.0, fontFace: F, fontSize: 10, color: MUT,
    lineSpacing: 14, margin: 0 });
  s.addImage({ path: A + "qr_repo.png", x: 10.5, y: 4.2, w: 0.8, h: 0.8 });
  s.addImage({ path: A + "qr_viewer.png", x: 11.5, y: 4.2, w: 0.8, h: 0.8 });
  s.addText("GitHub / ビューア", { x: 10.4, y: 5.05, w: 2.0, h: 0.25,
    fontFace: F, fontSize: 8.5, color: MUT, align: "center", margin: 0 });
  s.addText("下の層ほど古い幕の成果。上の幕は下を壊さず積んだ — 幕の色がそのまま層の色。", {
    x: 0.9, y: 6.3, w: 11.6, h: 0.35, fontFace: F, fontSize: 12, color: INK,
    margin: 0 });
  foot(s, 20, "1:00");
  s.addNotes("年表（S4）の5幕がそのまま5層に堆積している、という視覚的な回収。層の色＝幕の色。");
}

/* ===================== 15. 6ヶ月で学んだこと ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "総括", "6ヶ月で学んだこと：正直さは態度ではなく、仕組み", NAVY);
  const lessons = [
    ["捏造ゼロは構成的に成立させる", "「気をつける」では守れない。証拠の無い要素が出力に到達できない構造にする（第5幕の証拠閉包はその極致）"],
    ["モデルを良く見せる機構ほど台帳に載せる", "接続・解ける・完全に見せる19機構すべてに根拠とOFFスイッチ。介入を隠すとバグと区別がつかなくなる"],
    ["収束は正しさではない", "served_frac を結果に同梱。誇っていた数字を自分で解体できるプローブ（変種比較・プロセス分離）を常備する"],
    ["欠測は隠さず、測って作業リストにする", "被覆・棄権率・欠測は報告値。測った欠測はOSMコミュニティへの貢献リストになる — 欠測が資産に変わる"],
  ];
  lessons.forEach(([t, b], i) => {
    const x = 0.9 + (i % 2) * 5.95, y = 1.35 + Math.floor(i / 2) * 2.15;
    s.addShape(pres.ShapeType.roundRect, { x, y, w: 5.65, h: 1.95,
      fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.06 });
    s.addText(`${i + 1}`, { x: x + 0.2, y: y + 0.18, w: 0.5, h: 0.5,
      fontFace: FL, fontSize: 22, bold: true, color: NAVY, margin: 0 });
    s.addText(t, { x: x + 0.75, y: y + 0.18, w: 4.75, h: 0.65, fontFace: F,
      fontSize: 13.5, bold: true, color: INK, lineSpacing: 18, margin: 0 });
    s.addText(b, { x: x + 0.75, y: y + 0.88, w: 4.75, h: 1.0, fontFace: F,
      fontSize: 11, color: MUT, lineSpacing: 15, margin: 0, valign: "top" });
  });
  s.addShape(pres.ShapeType.roundRect, { x: 0.9, y: 5.75, w: 11.6, h: 0.95,
    fill: { color: NAVY }, line: { type: "none" }, rectRadius: 0.06 });
  s.addText("この4つはどれも、一度「良い数字」を出してから学び直したものである。", {
    x: 1.2, y: 5.75, w: 11.0, h: 0.95, fontFace: F, fontSize: 14.5,
    bold: true, color: "FFFFFF", margin: 0, valign: "middle" });
  foot(s, 21, "1:00");
  s.addNotes("各原則が生まれた事件と対応：①=v1.8証拠閉包 ②=v1.5介入台帳 ③=v1.5東AC解体 ④=v1.8 issue#49。下帯の一文がこのデッキの結論。");
}

/* ===================== 16. まとめ・論文・今後 ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "結", "まとめと今後", NAVY);
  s.addShape(pres.ShapeType.roundRect, { x: 0.9, y: 1.3, w: 11.6, h: 1.5,
    fill: { color: NAVY }, line: { type: "none" }, rectRadius: 0.08 });
  s.addText("公開データだけから、日本全国の送電網モデルは作れる。\nただしそれを信頼に足るものにするのは、抽出の巧さではなく — 介入の台帳・検証器としての標準・測って報告する欠測である。", {
    x: 1.2, y: 1.3, w: 11.0, h: 1.5, fontFace: F, fontSize: 14.5, bold: true,
    color: "FFFFFF", lineSpacing: 22, margin: 0, valign: "middle" });
  // 論文2本
  s.addText("論文", { x: 0.9, y: 3.05, w: 2, h: 0.3, fontFace: F,
    fontSize: 12.5, bold: true, color: NAVY, margin: 0 });
  card(s, 0.9, 3.4, 5.65, 1.7, "① データセット論文（IEEE OA体裁・5p）",
    "抽出パイプライン・7段補完・UC/潮流/AGC連鎖。papers/ieee-openaccess.tex\n※ 8,164誤記は修正済(6,962)。残る宿題=文献整備と著者名", ACT[1], 11.5);
  card(s, 6.85, 3.4, 5.65, 1.7, "② SubSLD論文（IEEEtran 6p・ビルド済）",
    "変電所内部構成の実証的機械生成。papers/subsld/\n※ 参考文献が未記載（\\cite 0件）— 両論文とも投稿先未定", ACT[4], 11.5);
  // 今後
  s.addText("今後", { x: 0.9, y: 5.3, w: 2, h: 0.3, fontFace: F,
    fontSize: 12.5, bold: true, color: NAVY, margin: 0 });
  [["論文2本の文献・投稿先", "BibTeX整備と体裁確定が先頭"],
   ["西日本フルAC", "66 kVメッシュ表現（並列回線・変圧器容量・無効電力支援）"],
   ["OSMへの還流", "issue #49 の編集候補リスト10件を実行 — 欠測を貢献に変える"]]
    .forEach(([t, b], i) => {
      const x = 0.9 + i * 3.95;
      s.addText(`${i + 1}. ${t}`, { x, y: 5.65, w: 3.75, h: 0.3, fontFace: F,
        fontSize: 11.5, bold: true, color: INK, margin: 0 });
      s.addText(b, { x, y: 5.95, w: 3.75, h: 0.6, fontFace: F, fontSize: 10.5,
        color: MUT, lineSpacing: 14, margin: 0, valign: "top" });
    });
  s.addText("github.com/lutelute/All-Japan-Grid　|　lutelute.github.io/All-Japan-Grid　|　データ: ODbL（OSM由来）・コード: MIT　|　航空写真: 国土地理院", {
    x: 0.9, y: 6.62, w: 11.6, h: 0.28, fontFace: FM, fontSize: 9, color: MUT,
    margin: 0 });
  foot(s, 22, "0:30");
  s.addNotes("論文カードの※は正直に残す（既知の宿題を隠さない — それ自体がこのプロジェクトの流儀）。質疑へ。");
}

pres.writeFile({ fileName: "AllJapanGrid_story.pptx" })
  .then(() => console.log("written: AllJapanGrid_story.pptx"));
