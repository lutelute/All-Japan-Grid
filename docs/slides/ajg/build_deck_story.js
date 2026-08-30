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
// 本編19枚で 22:00(第6幕3枚を2026-08-30追加)。
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
// GIF全画面スライド + 編集できるタイトル帯。
// GIF内に文字を焼き込むとPowerPointで直せない(オーナー指摘)ため、見出しは
// スライド側のテキストボックスに置く。GIFは16:9を保ったまま帯の下に敷く。
function gifSlide(file, title, sub) {
  const s = pres.addSlide();
  s.background = { color: "0A0D1A" };
  const H = 6.86, W = H * 16 / 9;                 // 帯0.64インチ分を空ける
  s.addImage({ path: A + file, x: (13.33 - W) / 2, y: 0.64, w: W, h: H });
  s.addText(title, { x: 0.55, y: 0.10, w: 11.4, h: 0.44, fontFace: F,
    fontSize: 19, bold: true, color: "FFFFFF", margin: 0, valign: "middle" });
  if (sub) s.addText(sub, { x: 0.55, y: 0.10, w: 12.3, h: 0.44, fontFace: F,
    fontSize: 11, color: "8E96B8", margin: 0, valign: "middle",
    align: "right" });
  return s;
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
  s.addText("— 6ヶ月・1,080コミット・10リリースの記録(2026-08-30時点)", { x: 0.75, y: 3.6,
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
  s.addNotes("【尺の設計 — 実測41枚45.3分】枠に応じて3トラックで運用する(構成はcodex助言で改稿: 位置づけは早く・検証は遅く・第6幕は検証の前)。■コア(約22分): p1,2,3,4,5(先行研究の位置),7(年表),8(第1幕),12(収束は正しさではない),14(公式開示と照合),16(SubSLD),19(事故),23(東N-3 GIF),32,33,35(西点灯),36(検証と限界),38(失敗も台帳に),40,41。■標準(約31分): コア+6(組み上げGIF),11(解ける化),17(SubSLDフリップ),25(逆位相),26(回復),29(UC),30(潮流),31(SCR)。■フル(45分): 全41枚。削る順(codex助言): ①深掘り29-31を付録へ ②動揺の実験カタログ20-28を代表2件に ③第6幕32-35を1-2枚に圧縮 ④年表+第1〜5幕を圧縮(つまずきは各幕1文で残す)。削ってはいけないもの: 全国モデルの定義・CGMES化・SubSLD・検証・限界・先行研究上の位置。失敗談は量を減らしても『失敗→台帳→修正→再検証』の因果を1本残せば意図は伝わる。0:30");
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
  s.addNotes("[コア]30秒黙って見せてから一言。「素材はただの線。ここから解ける系統までが本発表」。数字はbuilt正典の実測。");
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
  s.addNotes("[コア]論文（ieee-openaccess）§I の構図そのまま。日本だけ赤。下段で OSM に橋を架けると宣言。");
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
  s.addNotes("[コア]3層（線・変電所・発電所）を見せて、下2枚で線引き。「捏造ゼロ」はここで一度だけ宣言し、以後は行動で見せる。");
}

/* ============ 23.1 位置づけ: 先行研究の中で ============ */
{
  const s = pres.addSlide(); base(s);
  head(s, "現在", "先行研究の中での位置 — 勝っている軸と、負けている軸", NAVY,
    "OSM由来の公開系統データセット10件と全軸で照合した(2026-06-27・出典URL付き)");
  const rows = [
    ["データセット", "地域", "源泉", "CGMES", "検証", "DOI/査読"],
    ["All-Japan-Grid", "日本 全10広域(50/60Hz)", "OSM+P03", "○ L1+L2 10/10", "実測潮流ρ・電圧クラス", "✗ 未出版"],
    ["PyPSA-Eur", "欧州35カ国", "OSM", "✗", "構造統計ρ=0.96-0.998", "○ Nature SD'25"],
    ["SciGRID", "ドイツ", "OSM", "✗", "カバレッジのみ", "○ Energy Rep'17"],
    ["osmTGmod/eGo", "ドイツ EHV/HV", "OSM", "✗", "モデル対モデルAC", "○ IET GTD'20"],
    ["KPG-193", "韓国", "合成(OSM位相)", "✗", "自己無撞着のみ", "✗ arXiv"],
  ];
  const cw = [2.35, 2.5, 1.45, 1.7, 2.15, 1.45];
  rows.forEach((r, ri) => {
    let x = 0.9;
    r.forEach((c, ci) => {
      if (ri === 0) {
        s.addShape(pres.ShapeType.rect, { x, y: 1.5, w: cw[ci], h: 0.4,
          fill: { color: NAVY }, line: { type: "none" } });
      } else if (ri === 1) {
        s.addShape(pres.ShapeType.rect, { x, y: 1.5 + ri * 0.52, w: cw[ci],
          h: 0.52, fill: { color: "E8F0FA" }, line: { type: "none" } });
      }
      s.addText(c, { x: x + 0.08, y: 1.5 + (ri ? ri * 0.52 : 0), w: cw[ci] - 0.12,
        h: ri ? 0.52 : 0.4, fontFace: F, fontSize: ri ? 10.5 : 10.5,
        bold: ri <= 1, color: ri === 0 ? "FFFFFF" : INK, margin: 0,
        valign: "middle" });
      x += cw[ci];
    });
  });
  card(s, 0.9, 4.75, 5.7, 1.5, "正当に主張できる優位(組合せの初出)",
    "日本全国(全10広域・50/60Hz) × CGMESネイティブ(本セット唯一) × 事業者公表の実測潮流への順位相関 × 値単位の出典 — この組合せ", "0F7B6C", 12.5);
  card(s, 6.8, 4.75, 5.7, 1.5, "明確に負けている軸",
    "再現DAG(Snakemake等)・DOI寄託・査読出版・ネットワーク連結性・検証の広さ。特にPyPSA-Eurには大差 — 「first openly available」とは言わない", "C0392B", 12.5);
  foot(s, 5, "1:15");
  s.addText("検証は公式開示との照合・実測潮流への代理相関・CGMES適合の3層で行う(終盤で回収する)", { x: 0.9, y: 6.45, w: 11.6, h: 0.32, fontFace: F, fontSize: 11, color: NAVY, bold: true, margin: 0 });
  s.addNotes("[コア]『日本に無い』だけでは位置づけにならないので、10件と全軸照合したスコアカードを1枚に圧縮。優位はCGMESと組合せの初出に限定し、劣位(DAG/DOI/査読/連結性)は自分から言う。出典: docs/reports/international_benchmark_2026-06-27.md(比較値は一次出典で照合済)。質疑で『PyPSA-Eurとどう違う』は必ず来るので、この1枚で受ける。1:15");
}

/* ============ 3.5 動: OSM→モデルの組み上げ(GIF) ============ */
{
  const s = pres.addSlide();
  s.background = { color: "0A0D1A" };
  s.addImage({ path: A + "pipeline_buildup.gif", x: 0, y: 0, w: 13.33, h: 7.5 });
  s.addNotes("[標準]【手順の本体】OSM→モデルの6段階を1本のアニメで。①送電線の幾何(西→東に描画) ②電圧を7段補完で決定(色が付く) ③端点マッチングで結線(黄点=ジャンクション) ④変電所(白丸)と変圧器 ⑤発電所(★)を最寄り接続 ⑥県別需要×電圧重みで需要配分。全フレーム実データ。ここで手順の全体像を掴ませてから年表へ。1:30");
}

/* ===================== 4. 年表（5幕） ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "序", "6ヶ月の道筋：5幕 — すんなりは、行っていない", NAVY);
  const acts = [
    ["第1幕", "v1.0", "地理を掘る", "OSM抽出・7段補完・UC/PF 一式",
     "✗ 電圧タグ欠測87%・断片だらけから開始", "「地図はある」→ モデルにした"],
    ["第2幕", "v1.1–1.4", "電気にして\n標準で渡す", "CIM/CGMES・統一DB・全10地域AC",
     "✗ 並列回線・電圧タグのバグを潰すまで解けず", "作れた → 解けるのか？"],
    ["第3幕", "v1.5–1.6", "誠実さを\n制度にする", "介入台帳・fake-AC検出・二重抽出根治",
     "✗ 「解けた」が嘘だった・西2,531成分の謎", "解けた → 本当か？"],
    ["第4幕", "v1.7", "公式開示と\n接続する", "様式5・OCCTO容量・実測突合",
     "✗ 開示とずれる地域 — 上書きせず照合", "正した → 現実と合うか？"],
    ["第5幕", "v1.8", "変電所の\n中へ", "SubSLD法・実証ペア図・node-breaker",
     "✗ 変電所内部はOSMに無い — 方法から発明", "網はできた → 最後の暗箱へ"],
  ];
  acts.forEach(([act, ver, title, body, fail, q], i) => {
    const x = 0.72 + i * 2.42;
    s.addShape(pres.ShapeType.roundRect, { x, y: 1.35, w: 2.28, h: 3.15,
      fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.07 });
    s.addShape(pres.ShapeType.rect, { x, y: 1.35, w: 2.28, h: 0.12,
      fill: { color: ACT[i] }, line: { type: "none" } });
    s.addText(`${act}　${ver}`, { x: x + 0.15, y: 1.58, w: 2.0, h: 0.3,
      fontFace: FL, fontSize: 10.5, bold: true, color: MUT, margin: 0 });
    s.addText(title, { x: x + 0.15, y: 1.9, w: 2.0, h: 0.85, fontFace: F,
      fontSize: 14.5, bold: true, color: INK, lineSpacing: 19, margin: 0 });
    s.addText(body, { x: x + 0.15, y: 2.85, w: 2.0, h: 0.62, fontFace: F,
      fontSize: 9.5, color: MUT, lineSpacing: 13, margin: 0 });
    s.addText(fail, { x: x + 0.15, y: 3.5, w: 2.0, h: 0.55, fontFace: F,
      fontSize: 9, bold: true, color: "C0392B", lineSpacing: 12, margin: 0 });
    s.addText(q, { x: x + 0.15, y: 4.06, w: 2.0, h: 0.42, fontFace: F,
      fontSize: 9, italic: true, color: NAVY, lineSpacing: 12, margin: 0 });
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
    ["v1.0.0", 3, 0], ["v1.1.0", 94, 1], ["v1.2.0", 97, 1], ["v1.2.1", 99, 1], ["v1.3.0", 100, 1],
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
  foot(s, 6, "1:00");
  s.addNotes("[コア]この1枚が地図 — 各幕カードに赤の✗=つまずきを明記(『すんなり行っていない』の骨格)。以降のスライドは左上バッジ(幕色つき)で現在地を示す。赤✗→斜体の問いの順に読み上げる。※旧skip①指定を解除: 苦闘の年表は本編の核。");
}

/* ===================== 5. 第1幕: 抽出パイプライン ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "第1幕 v1.0", "地理を掘る：抽出から解析まで、最初から一本のパイプライン", ACT[0]);
  s.addImage({ path: A + "fig_pipeline_flow.png", x: 0.62, y: 1.3, w: 12.1,
    h: 5.02 });
  // 図中UCブロックの旧値「783機×24h」(v1.0期のモデル)を現行757機に訂正表示
  s.addShape(pres.ShapeType.rect, { x: 4.86, y: 4.58, w: 0.64, h: 0.24,
    fill: { color: "C4461F" }, line: { type: "none" } });
  s.addText("757機×24h", { x: 4.80, y: 4.58, w: 0.76, h: 0.24, fontFace: F,
    fontSize: 9, color: "FFECB3", align: "center", valign: "middle",
    margin: 0 });
  s.addText("Overpassタイル分割抽出 → 7段の属性補完（Nominatim / MLIT P03、欠損87%削減）→ Haversine端点マッチング → 電圧クラス別の合成パラメータ → pandapower / MATPOWER / Ybus / UC", {
    x: 0.9, y: 6.4, w: 11.6, h: 0.55, fontFace: F, fontSize: 11.5, color: INK,
    lineSpacing: 16, margin: 0 });
  foot(s, 7, "1:30");
  s.addNotes("[コア]論文 §III–VI をこの1枚に圧縮。「電気パラメータは合成＝推定と明記」を図の緑ブロックを指して言う。87%は補完の欠損削減率（論文値）。");
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
  foot(s, 8, "1:30");
  s.addNotes("[標準]数値は論文 Table I / II。本文の 8,164 は誤記（同論文の表合計は 6,962）で、この版から 6,962 に統一している。限界の明記が第3幕への伏線。");
}

/* ===================== 7. 第2幕: 標準で渡す ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "第2幕 v1.2", "標準で渡す：CIM/CGMES は輸出先ではなく検証器だった", ACT[1]);
  card(s, 0.9, 1.3, 5.6, 1.45, "IEC 61970 CIM (CGMES 2.4.15) 書き出し",
    "EQ + GL の全10地域。決定的 UUIDv5 mRID・dangling参照 0。\n独立実装 pandapower cim2pp で読み戻して検証", ACT[1], 13.5);
  card(s, 0.9, 3.0, 5.6, 1.45, "Level-2：解ける潮流ケース",
    "EQ/TP/SSH/SV。cim2pp ラウンドトリップ後に runpp が収束\n（初出 okinawa 81母線 → 境界セット整備で全10地域）", ACT[1], 13.5);
  card(s, 0.9, 4.7, 5.6, 1.45, "統一DB（R/C/D 3層・SQLite）",
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
  foot(s, 9, "1:30");
  s.addNotes("[フル]この枚の主張は右の赤枠。「標準対応しました」ではなく「標準が検証器になった」。5つのバグはどれも自前レンダラだけなら気づけない。");
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
  s.addText("全国ACPF：14,647母線・10/10地域が解けた（v1.4・CGMES往復後）", {
    x: 7.35, y: 6.5, w: 5.3, h: 0.5, fontFace: F, fontSize: 10.5, color: MUT,
    lineSpacing: 14, margin: 0 });
  foot(s, 10, "1:30");
  s.addNotes("[標準]【25分版はスキップ可②】左下の衛星3連画像は v1.1 の比較タブ（衛星写真で位置を目視検証）。右図は自慢の1枚だが、次の幕でこれを自分で疑いにいく。");
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
  s.addText("誇っていた「フルAC 99.0 % 給電」を7変種プローブで解体したら、bboxで誤配置された需要地理の上に立っていた。地理を正した時点ではフルACは解けず、dc_fallback と報告する側に倒した(この判断は第6幕でひっくり返る)。\n\n途中「復活した」と見えた解も、飛騨回廊に偶然2.3 GWのバラストを置く重み付けバグだった。出荷前に棄却。", {
    x: 7.15, y: 3.05, w: 5.15, h: 2.3, fontFace: F, fontSize: 11.5,
    color: INK, lineSpacing: 17, margin: 0 });
  s.addText("結果を良くする変更より、結果を悪くする訂正の方が価値がある。", {
    x: 7.15, y: 5.35, w: 5.15, h: 0.4, fontFace: F, fontSize: 11.5,
    bold: true, color: NAVY, margin: 0 });
  s.addText("あわせて v1.5 で配布基盤も整備：自己完結バンドル（SHA256 MANIFEST）・pandapower/MATLAB両チュートリアルを実ダウンロード→新環境E2Eで検証してから公開。", {
    x: 0.9, y: 6.05, w: 11.6, h: 0.6, fontFace: F, fontSize: 11.5, color: MUT,
    lineSpacing: 16, margin: 0 });
  foot(s, 11, "2:00");
  s.addNotes("[コア]プロジェクトの転回点。8枚目の全国AC図を自分で解体した話。「結果を悪くする訂正」の一文をゆっくり。ここが第5幕の『完全性を主張せず測定する』の源流。");
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
  foot(s, 12, "1:30");
  s.addNotes("[フル]デバッグ譚として一番話せる枚。「+5.7%が訂正」の反直感を丁寧に。方法論文書は osm_grid_pitfalls_methodology_2026-07-10.md。");
}

/* ===================== 11. 第4幕: 公式開示と接続 ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "第4幕 v1.7", "公式開示と接続する：開示データは「上書き」ではなく「照合」", ACT[3]);
  card(s, 0.9, 1.3, 5.6, 1.45, "様式5 インピーダンス表（全10 TSO）",
    "1,009線・213変圧器を正規化し、実証接続89本を canon に適用。\n再生成のたびに再適用されるパイプライン段として組込（黙って消えない）", ACT[3], 13);
  card(s, 0.9, 2.95, 5.6, 1.45, "EGGC：証拠ゲート付きの線形照合",
    "開示コードがOSM実線形に吸着するのは「断片＝開示線そのもの」\n（off-main比 ≥ 0.7）のときだけ。幾何の捏造なし・14本を台帳化", ACT[3], 13);
  card(s, 0.9, 4.6, 5.6, 1.45, "UC定式の訂正",
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
  foot(s, 13, "1:30");
  s.addNotes("[コア]第3幕の規律が開示データにも適用される、が主題。「開示があるから正しい」ではなく開示も証拠ゲートを通す（EGGC）。UC訂正は開示容量と突き合わせて初めて見えた。");
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
    "10エリアのうち9エリアのTSO需給実績から燃料構成と原子力停止が日次断面へ自動反映。ゾーン純位置は公表連系実績と39–129 MWで一致（v1.7検証）", GRN, 11.5);
  card(s, 8.4, 3.3, 4.1, 1.55, "リアルタイム断面",
    "でんき予報の実績需要スナップショットでNOW断面PFを毎時再計算（launchd常駐・v1.8後）", ACT[3], 11.5);
  card(s, 8.4, 5.05, 4.1, 1.55, "観測方向の照合",
    "モデル潮流の向きを公表実績の向きと突合し、一致/不一致を地図に描く — 隠さず可視化", ACT[3], 11.5);
  foot(s, 14, "1:00");
  s.addNotes("[フル]【25分版はスキップ可③】静的データセットが「動く系統の観測器」になった枚。39–129 MWの一致幅は検証時点の実測。デモできるならここで flow_map を開く。");
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
  foot(s, 15, "2:00");
  s.addNotes("[コア]7,239 は構造DBのサイト数で、第1幕の 6,962（データセットfeature・v1.2測定）とは定義が違う — 聞かれたら即答する。深掘りは姉妹デッキへ誘導。");
}

/* ============ 14.5 動: SubSLDの読み方と全国展開(GIF) ============ */
{
  const s = pres.addSlide();
  s.background = { color: "0A0D1A" };
  s.addImage({ path: A + "subsld_flipbook.gif", x: 0.17, y: 0, w: 13.0, h: 7.5 });
  s.addNotes("[標準]SubSLDを動きで: 読み方3段(左=構内幾何/右=単線結線図/捏造ゼロ)→全国406所の機械生成を流す。第5幕の実物提示。詳細はSubSLD論文デッキへ。1:00");
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
  foot(s, 16, "1:00");
  s.addNotes("[フル]AGCを知らない聴衆向けの1枚。「電気は貯められない」から始める。次の枚で実際に事故らせる。");
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
  s.addText("小さな北海道(4.4 GW)は苫東厚真を失うと負荷遮断まで落ち込む。大きな東日本(59 GW)は3倍の規模(富津 5,040 MW)を失っても踏みとどまる — 系統の大きさ(慣性)の差が、そのまま運命の差になる。(この層はプラント全体5,040 MWを落とす上界評価 — 次章の多機層は同じ富津をUC運転点3,893 MWで落とす)", {
    x: 5.15, y: 6.2, w: 7.6, h: 0.6, fontFace: F, fontSize: 11,
    color: MUT, lineSpacing: 16, margin: 0 });
  foot(s, 17, "1:30");
  s.addNotes("[コア]2018年9月6日の実話(北海道ブラックアウト)から入る。「あの構図が、地図から作ったモデルで出る」。動特性は典型値の構造実証、プラント粒度=ユニットN-1の上界、は聞かれたら答える。");
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
  s.addText("下段=各機の相差角(±40°の動揺→減衰整定)。多機版はCOI簡約版よりやや深く沈む(−2.7 vs −2.5 Hz) — 定Z負荷とGF幅の実装差で、帳簿に開示。", {
    x: 0.9, y: 6.82, w: 11.6, h: 0.3, fontFace: F, fontSize: 10.5, color: MUT,
    margin: 0 });
  foot(s, 18, "1:00");
  s.addNotes("[フル]【25分版はスキップ可④】「動揺がないのが違和感」への回答。UFLSの3段が1.6/2.0/2.7秒に入るのが拡大で見える。AGC100の話が出たら『これはAGC-54。Nは任意で、東なら数百機』。");
}

/* ===================== 18. 全国・全機の動揺 ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "終幕 v1.9へ", "系統ごと、全部解く：4島・541機の動揺", NAVY);
  s.addImage({ path: A + "fig_swing_national.png", x: 1.9, y: 1.02, w: 9.55,
    h: 5.52 });
  s.addText("東183機は富津3,893MWを失っても−0.44Hzで踏みとどまり、全機がうねりながら回復する。西298機は±0.3Hzの機間動揺が10秒で減衰。弱結合の小規模機7機は脱調保護が切り離す(切離しの瞬間まで描画・全経過は帳簿)。", {
    x: 0.9, y: 6.62, w: 11.6, h: 0.42, fontFace: F, fontSize: 10.5,
    color: INK, lineSpacing: 13.5, margin: 0 });
  foot(s, 19, "1:00");
  s.addNotes("[標準]541=54+183+298+6(図の小見出しは脱落後の生存機数)。west は多機層のみDC断面初期化 — 第6幕でフルAC成立済みだが動揺実験への反映は未実施、と役割分担で開示する。「AGC100?」→「これはAGC-541」。");
}

/* ===================== 19. 波が走る(GIF) ===================== */
{
  const s = pres.addSlide();
  s.background = { color: "0A0D1A" };
  s.addImage({ path: A + "agc_east_wave.gif", x: 3.53, y: 0.15, w: 9.3,
    h: 6.98 });
  s.addText("波が、走る。", { x: 0.55, y: 0.7, w: 2.9, h: 0.5, fontFace: F,
    fontSize: 24, bold: true, color: "FFFFFF", margin: 0 });
  s.addText("富津で3,893MWが消えた瞬間、\n周波数低下の波が実網インピーダンス\nを伝って東北へ駆け上がる。", {
    x: 0.57, y: 1.35, w: 2.95, h: 1.1, fontFace: F, fontSize: 12.5,
    color: "C8CDD8", lineSpacing: 18, margin: 0 });
  [["丸", "発電機(実座標・大きさ=定格)"],
   ["色", "その機のローカル周波数\n(青=50Hz → 赤=低下)"],
   ["✕", "落ちた発電所(富津)"],
   ["右下", "全機波形+現在時刻カーソル"]].forEach(([k, v], i) => {
    const y = 2.75 + i * 0.72;
    s.addText(k, { x: 0.57, y, w: 1.2, h: 0.3, fontFace: F, fontSize: 11.5,
      bold: true, color: "FFFFFF", margin: 0 });
    s.addText(v, { x: 0.57, y: y + 0.27, w: 2.95, h: 0.55, fontFace: F,
      fontSize: 10, color: "8E96B8", lineSpacing: 13, margin: 0 });
  });
  s.addText("事故直後は超スローモーション(ミリ秒表示)。\n遠い機ほど遅れて落ちる=同期化力の伝播。", {
    x: 0.57, y: 5.8, w: 2.95, h: 0.7, fontFace: F, fontSize: 10,
    color: "5A648F", lineSpacing: 14, margin: 0 });
  s.addText("スライドショー再生で動きます(GIF)", { x: 0.57, y: 6.6, w: 2.9,
    h: 0.3, fontFace: F, fontSize: 10, italic: true, color: "8E96B8",
    margin: 0 });
  foot(s, 20, "0:45");
  s.addNotes("[フル]30秒流す。「地図はここまで語れる」の頂点。伝播速度の定量化は今後(位相計測PMU比較の話が出たら乗る)。");
}

/* ============ 19.5 動: 東全域N-3とUFLS(GIF) ============ */
{
  const s = gifSlide("east_incident.gif",
    "東日本全域 N-3実験 — 富津+東新潟+千葉 10,618MW同時脱落(設計外デモ)",
    "UCピーク断面 59.4GW");
  s.addNotes("[コア]東全域の大擾乱(設計外N-3デモ): ピーク断面59.4GWで富津+東新潟+千葉10,618MWを同時脱落、900秒の全アーク。負荷遮断の見せ方(オーナー指摘「黄色の数の変更が見えない」への対応): モデルのUFLSは全負荷を一律10%/段で削減する集約近似で、面積比10%の縮小は目に見えない → 等価なMW量を『個別負荷の消灯』として描く(361件・5,935MW)。実系統はフィーダ単位の遮断なので見た目はむしろ実態に近いが、どの負荷が落ちるかはモデルの主張ではないため選定は再現可能な擬似乱数、その旨を画面に明記。左下の需給パネルで『脱落10,618 → UFLS遮断5,935 → 残り4,683はガバナ+LFCが埋める』の因果を数量で見せる。4局面: ①慣性で急落 ②UFLS第1段が底48.49Hzを打つ ③高速登坂 ④停滞(60-180s) ⑤緩回復(15分で49.84)。1:15");
}

/* ============ 19.6 動: 全系統動揺(GIF) ============ */
{
  const s = gifSlide("eastwest_swing.gif",
    "東西動揺 — ほぼ同じ4GW級の脱落。なぜ落ち方が違うのか",
    "東 富津3,893MW / 西 川越3,990MW");
  s.addNotes("[標準]東西動揺 — 主題は『ほぼ同じ4GW級の脱落なのに、なぜ落ち方が違うのか』(オーナー指摘「考察がない」への対応)。右下の比較表は全てnpz実測: 脱落量3,893/3,990MW、需要比6.56%/5.70%、慣性ΣM 7,079/8,151 pu·s、最大偏差−0.436/−0.276Hz。西が浅い理由は①系統が大きく脱落比が小さい②慣性が1.15倍③速い余力(水力)が1.7倍(UC断面で東2.7GW・西4.5GW)。重要な落とし穴として『60Hz系は同じpu変化でもHz表示が1.2倍大きく出る — Hzのまま直接比べると誤読する』を明示(pu換算では東−0.872%/西−0.461%で約1.9倍の差)。東西はFC経由の直流連系のみで動揺は伝わらないため、独立実験の同時刻表示である旨も明記。1:00");
}

/* ============ 19.7 動: 逆位相動揺(GIF) ============ */
{
  const s = gifSlide("interarea_mode.gif",
    "逆位相動揺 — 九州側と関西側の綱引き",
    "西日本298機・最大機トリップ後");
  s.addNotes("[標準]逆位相動揺+綱引きの機構: 右下に新設した『綱の張り=群間位相角差Δδ』パネルと、地図上の電力矢印(位相の進んだ群→遅れた群、振れ幅で太さが変わる)で、なぜ逆位相になるかを説明 — 2つの慣性群が長い送電回廊(ばね)で繋がれた2重り系。西G(九州側61機)×東G(関西以東181機)、相関−0.999・周期2.4s。オーナー指摘『綱引きがわかりにくい』への応答。1:00");
}

/* ============ 19.8 動: 周波数が戻るさま(GIF) ============ */
{
  const s = gifSlide("freq_recovery_east.gif",
    "周波数が戻るさま — 東N-3(10,618MW脱落)から15分",
    "多機層(AGC-N)・第10波LFC修正済み");
  s.addNotes("[標準]周波数が戻るさま(東N-3・900秒に一本化): 前スライドと同じ事故・同じデータで、COI曲線が左から描かれ局面バナーが順に出る進行チャート — ①慣性急落 ②UFLS底打ち(48.49Hz) ③高速登坂 ④停滞 ⑤緩回復。終端で『15分で49.84Hz、50.00への完全復帰はさらに数十分先』を正直に。オーナー指摘『p25がわからない』への応答: 北海道・COI層2,400秒の別実験(旧版)は文脈が飛ぶため差し替え。旧freq_recovery.gifはリポジトリに残置。1:00");
}

/* ===================== 20. 24時間の断面 ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "終幕 v1.9へ", "24時間の断面：同じ事故でも、夜がいちばん危ない", NAVY);
  s.addImage({ path: A + "fig_agc_24h.png", x: 2.5, y: 1.05, w: 8.35,
    h: 5.48 });
  s.addText("UCの24時間コミットメントを1時刻ずつ断面にして最大オンラインプラントを落とす。夜間はオンライン機が減る→慣性が3割落ちる→同じ事故でも深く速く落ちる。北海道の最悪は深夜3時＝実際の2018年ブラックアウト(3:08)と同じ時間帯。", {
    x: 0.9, y: 6.62, w: 11.6, h: 0.42, fontFace: F, fontSize: 10.5, color: INK,
    lineSpacing: 13.5, margin: 0 });
  foot(s, 21, "1:00");
  s.addNotes("[フル]「夜が危ない」の古典を、地図から作ったモデルが自力で言い直す枚。3:08の一致は構図の一致(モデルは同日のUC断面・実事故は2018/9/6)と断ってから言う。");
}

/* ===================== 20. 実況: 事故が地図の上を走る ===================== */
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
  foot(s, 22, "1:00");
  s.addNotes("[フル]ここは喋らず30秒流す。止め絵になる環境ではPDF版の1コマ目が出るので「動画はGIF参照」と言う。");
}

/* ============ 22.3 深掘り①: UC 24時間ディスパッチ(GIF) ============ */
{
  const s = gifSlide("uc_dispatch_stack.gif",
    "一日の起動停止計画(UC) — 757機・9連系線・fy2023r2",
    "全国UC最適解(求解約10秒)");
  s.addNotes("[標準]深掘り① 計画(UC): fy2023r2・757機・9連系線UCの24時間ディスパッチを燃料別積み上げで掃引。需要線との一致・揚水/スピルも正直に描く。以降の潮流・動揺実験は全てこの解を土台にしている、という位置づけを一言。1:00");
}

/* ============ 22.5 深掘り②: ピーク断面ローディング(静止画) ============ */
{
  const s = gifSlide("loading_map_peak.png",
    "ピーク断面の線路負荷率 — 東西フル網のAC潮流(UC断面注入)",
    "定格は電圧階級の推定 — 相対的な混雑指標");
  s.addNotes("[標準]深掘り② 流れ(潮流): UCピーク断面のAC解による送電線負荷率マップ。混んでいる回廊(赤・太)に名前ラベル。UCが検出した混雑費用+1.4%が『どこの線の話か』を地図で回収。1:00");
}

/* ============ 22.7 深掘り③: 系統の強さ(SCC/SCR・静止画) ============ */
{
  const s = gifSlide("scr_map.png",
    "系統の強さの地図 — 全バス短絡容量(SCC)",
    "UCピーク断面・古典近似(図中に開示)");
  s.addNotes("[フル]深掘り③ 強さ(SCR): 全4島・全バスの短絡容量SCCマップ(古典近似: 運転中機のXd'背後V=1.0・負荷除外・実網Ybus — 近似は図中に開示)。青=強い/赤=弱い。SCR=SCC÷設備容量なので、赤い場所ほどインバータ電源の連系が難しい。『負荷があるのに弱い』全国ワーストに注記。逆位相動揺の連系剛性ともつながる話。1:00");
}

/* ===================== 第6幕A. 最後のDC島 ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "第6幕 2026-08-30", "最後のDC島 — 西のACを一夜で正典にする", "0F7B6C",
    "4島のうち西日本だけがAC不成立のまま「今後」に残っていた — その宿題を今夜のうちに");
  card(s, 0.9, 1.35, 7.0, 1.45, "謎: バックボーンでも解けない",
    "≥154 kVに絞っても dc_fallback。プローブ第1〜4波(サイト変圧器・無効電力・時刻別シャント)は全て空振り。NR最終ミスマッチは右図のとおり全域が瓦礫で、震源が読めない → 反復を1回で止めて観察する onset 診断に切替", RED, 12);
  s.addShape(pres.ShapeType.roundRect, { x: 8.05, y: 1.35, w: 4.50, h: 3.85,
    fill: { color: "FFFFFF" }, line: { color: "D9D9E0", width: 1 },
    rectRadius: 0.05 });
  s.addImage({ path: A + "fig_west_wreckage.png", x: 8.16, y: 1.45,
    w: 4.28, h: 3.59 });
  s.addText("証拠物件: 発散後の最終ミスマッチ — 全域瓦礫(ここから犯人は読めない)", {
    x: 8.16, y: 5.06, w: 4.28, h: 0.32, fontFace: F, fontSize: 8.5,
    color: MUT, margin: 0 });
  card(s, 0.9, 2.95, 7.0, 1.45, "第一容疑者: 大阪都心154 kVクラスタ",
    "梅田・北浜・小曽根…上位(≥275 kV)への変圧器がゼロ。関西の275 kV地中網はOSM未収載で、開示系統図は実名匿名化=出典回復が不可能(#28型が使えない)", ACT[3], 12);
  s.addShape(pres.ShapeType.roundRect, { x: 0.9, y: 5.42, w: 11.6, h: 1.28,
    fill: { color: "0F7B6C" }, line: { type: "none" }, rectRadius: 0.08 });
  s.addText([
    { text: "介入#37「都心給電の必然接続(仮)」 — ", options: { fontFace: F, fontSize: 13.5, bold: true, color: "FFFFFF" } },
    { text: "負荷が現に供給されている以上、給電経路の存在は電気的必然。存在のみ主張し、経路・容量は(仮)明記+全件台帳。", options: { fontFace: F, fontSize: 11.5, color: "E6F4F1" } },
    { text: "オーナー裁定「仮が事実でないかもしれないなら、それを明記しておけば正典として良い」", options: { fontFace: F, fontSize: 11.5, bold: true, color: "FFE082" } },
  ], { x: 1.2, y: 5.42, w: 11.0, h: 1.28, margin: 0, valign: "middle", lineSpacing: 16 });
  s.addText("→ (仮)のみで西バックボーンAC初成立(served 96.5%)。ならばフルの犯人は154 kV未満の層 — 捜査は66/77 kVへ", {
    x: 0.9, y: 6.76, w: 11.6, h: 0.3, fontFace: F, fontSize: 11.5, bold: true,
    color: GRN, margin: 0 });
  foot(s, 23, "1:00");
  s.addNotes("[コア]第6幕は一夜のデバッグ記。(仮)の哲学=推定母線と同じ「存在の必然性だけ主張」。承認の一文がこの幕の転回点。数値の出典: provisional_infeed_decision_2026-08-30.md");
}

/* ===================== 第6幕B. 犯人は大阪ではなかった ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "第6幕 2026-08-30", "犯人は大阪ではなかった — 50Hz設備の混入", "0F7B6C",
    "onset診断: NRを反復1回で止めて観察 → 最初に暴れたのは軽井沢・御代田・嬬恋の66/77 kV(|V|→6.6)");
  const steps = [
    ["観察", "発散の初動は長野東信〜群馬の66/77 kVポケット。大阪はもう鎮まっていた", ACT[1]],
    ["裏取り(3方向並列)", "コード: 島分けはregionラベルのみ / データ: 群馬・埼玉座標なのにregion=chubuが混在 / 実世界: 軽井沢一帯は中部電力領で、東西は新信濃FCでしか繋がらない(出典つき)", ACT[2]],
    ["機序(3変種)", "①抽出bboxこぼれ(嬬恋・神保原・榛名・鴨宮・都留) ②座標是正ロジックが「周波数跨ぎ全面禁止」ガードで恒久スキップ ③衛生介入#35にガードが無く逆流8件", ACT[3]],
    ["介入#38", "ガードを精緻化: 周波数が県内で一意な県(関東+山梨/愛知以西+北陸)への是正だけ跨ぎを許可。混在県(長野・新潟・静岡)は従来どおり保護 — 安曇幹線は切らない", "0F7B6C"],
  ];
  steps.forEach(([t, b, c], i) => {
    const y = 1.35 + i * 1.32;
    s.addShape(pres.ShapeType.roundRect, { x: 0.9, y, w: 11.6, h: 1.18,
      fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.06 });
    s.addShape(pres.ShapeType.rect, { x: 1.1, y: y + 0.15, w: 0.14, h: 0.88,
      fill: { color: c }, line: { type: "none" } });
    s.addText(t, { x: 1.45, y: y + 0.1, w: 2.6, h: 0.98, fontFace: F,
      fontSize: 13, bold: true, color: INK, margin: 0, valign: "middle" });
    s.addText(b, { x: 4.15, y: y + 0.1, w: 8.2, h: 0.98, fontFace: F,
      fontSize: 10.5, color: MUT, lineSpacing: 14, margin: 0, valign: "middle" });
  });
  s.addText("誤帰属ノードは是正後もregion_srcに原ラベルを退避 — 何を動かしたかは常に監査可能", {
    x: 0.9, y: 6.7, w: 11.6, h: 0.3, fontFace: F, fontSize: 10.5, color: MUT, margin: 0 });
  foot(s, 24, "1:15");
  s.addNotes("[コア]探偵編の核心。裏取りは3エージェント並列(コード読解/生データ/Web出典)。#38の設計原則=ガードの動機(混在県の飛び地保護)を殺さずに過剰防衛だけ解く。証跡: west_ac_wave6_2026-08-30.md");
}

/* ============ 第6幕B2 動: 発散が育つ→収束する(GIF) ============ */
{
  const s = pres.addSlide();
  s.background = { color: "0A0D1A" };
  s.addImage({ path: A + "west_ac_onset.gif", x: 0, y: 0, w: 13.33, h: 7.5 });
  s.addNotes("[フル]第6幕の核心を動きで: ニュートン反復を1回ずつ止めて電圧場を観察。介入前(#37/#38なし)=大阪都心と軽井沢・嬬恋から逸脱が育ち発散 / 介入後=(仮)12件+誤帰属275点の是正だけで5回収束。補足(2026-08-30再検証): #37v2(下流込み集計)実装後は#38なしでも収束する — 両介入は独立に正当(regionの正しさはAC以前の問題)だが、AC成立の必要条件としては#37v2が主。『反復を止めて観察する』手法そのものが見える。1:00");
}

/* ===================== 第6幕C. 西日本AC点灯 ===================== */
{
  const s = pres.addSlide();
  s.background = { color: "0A0D1A" };
  s.addImage({ path: A + "fig_west_ac_map.png", x: 0.15, y: 0.75, w: 13.03, h: 5.95 });
  s.addText("そして、西日本が点灯する", { x: 0.7, y: 0.12, w: 9.0, h: 0.55,
    fontFace: F, fontSize: 22, bold: true, color: "FFFFFF", margin: 0 });
  s.addText("4島フルAC / 西も24時間全時刻AC(第8波: 下流専属負荷の見逃しを塞いで昼間帯も点灯) / slack 13%と局所低電圧も正直に開示",
    { x: 0.7, y: 6.76, w: 11.0, h: 0.28, fontFace: F, fontSize: 11,
      color: "8E96B8", margin: 0 });
  foot(s, 25, "0:45");
  s.addNotes("[コア]クライマックス。左=初のAC解の電圧分布(7,928バス・6.6s)。右=介入#38の検挙簿(誤帰属275点)。「点灯」の演出で締め、総括へ。数値出典: west_ac_wave6/wave7_2026-08-30.md");
}

/* ============ 22.9 検証: このモデルは正しいのか ============ */
{
  const s = pres.addSlide(); base(s);
  head(s, "現在", "このモデルは正しいのか — 3つの検証と、その限界", NAVY,
    "「解けた」は正しさではない(第3幕)。ならば外の実測と突き合わせる — 限界を同じ文で開示する");
  card(s, 0.9, 1.45, 3.85, 1.95, "① 実測潮流との順位相関(東京)",
    "事業者公表の線路別潮流と突合。ρ=0.721。\nただしこれは容量/トポロジの代理指標であって潮流の一致ではない。実測ACでの相関は ρ≈0.46-0.60", ACT[3], 12.5);
  card(s, 5.0, 1.45, 3.85, 1.95, "② 電圧クラスの突合(関西)",
    "開示系統図と電圧階級を照合し 37/38 が一致(97%)。\nただし母数は開示182本中、照合が成立した38本のみ。クラス限定の検証", ACT[3], 12.5);
  card(s, 9.1, 1.45, 3.4, 1.95, "③ 標準による自己検証",
    "CGMES(EQ+TP+SSH+SV+GL)を全10地域で書き出し、独立実装 pandapower cim2pp で読み戻す。10/10 VALID・dangling参照 0・往復後 vm差<1e-4 pu", ACT[1], 12.5);
  s.addShape(pres.ShapeType.roundRect, { x: 0.9, y: 3.72, w: 11.6, h: 1.35,
    fill: { color: "7A1F1F" }, line: { type: "none" }, rectRadius: 0.08 });
  s.addText([
    { text: "言ってはいけないこと(自戒) — ", options: { fontFace: F, fontSize: 13, bold: true, color: "FFFFFF" } },
    { text: "「ρ=0.721 は潮流が一致した」「実測突合そのものが新規」。ρは代理指標であり、PyPSA-Eur の ρ=0.96-0.998(回路長/ルート長)とは物理量が違うので横並べできない。", options: { fontFace: F, fontSize: 11.5, color: "FFE0E0" } },
  ], { x: 1.2, y: 3.72, w: 11.0, h: 1.35, margin: 0, valign: "middle", lineSpacing: 16 });
  s.addText("検証の弱さも成果物として開示している: 容量の訂正値は表示専用で潮流には未伝播(辞書に明記)/連結性・検証の広さは先行勢に劣る/DAG・DOIは未整備 — 次スライドの位置づけへ", {
    x: 0.9, y: 5.32, w: 11.6, h: 0.5, fontFace: F, fontSize: 11, color: MUT,
    lineSpacing: 15, margin: 0 });
  foot(s, 26, "1:30");
  s.addNotes("[コア]『解けた=正しい』ではない、を第3幕で言った以上、外部実測との突合をここで正面から出す。3つとも限界を同じ文に書いてあるのが本プロジェクトの流儀。出典: docs/reports/international_benchmark_2026-06-27.md / data_paper_readiness_2026-06-27.md。質疑で『精度は?』と来たら①の数字と、それが代理指標である理由(実測潮流が線路別に公開されているのは東京のみ)を答える。1:30");
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
  foot(s, 27, "1:00");
  s.addNotes("[フル]年表（S4）の5幕がそのまま5層に堆積している、という視覚的な回収。層の色＝幕の色。");
}

/* ===================== 第6幕E. 失敗も台帳に載せる ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "第6幕 2026-08-30", "失敗も、台帳に載せる", "C0392B",
    "成功だけを並べたスライドは、開発の実像ではない — 直近2週間だけでもこれだけ転んだ");
  card(s, 0.9, 1.4, 5.7, 1.95, "✗ 介入#40 人口傾斜 — 退行して不採用",
    "国勢調査メッシュで需要配分を人口比に傾斜 → 手元データは全国人口の39%しか覆っておらず、被覆内だけ歪んで東西フルACがdc_fallbackに退行。採用せず既定OFF — 『負の結果』も理由つきでレジストリに残した。皮肉なことに、動機だった江田島(広島66kV・4バス137.9MW vs 実勢ピーク≈30MW)は被覆外で無変化だった", "C0392B", 12.5);
  card(s, 6.8, 1.4, 5.7, 1.95, "✗ 第10波 多機LFCバグ — 全成果物を作り直し",
    "二次制御のACEに周波数バイアスが欠落=実質無効(900秒たっても47Hz台に張り付き)。COI層と同形のB=K_SYS·負荷·f0を導入して修正。検証: 北海道900秒で47.29→49.81Hzに回復(修正前は47.05で張り付き) → 正典4島+N-3+GIF群を一括再生成し、依存する図・スライドも作り直した", "C0392B", 12.5);
  card(s, 0.9, 3.55, 5.7, 1.95, "✗ 動揺GIFは3回作り直し",
    "『リニアに回復するのは違和感、停滞するはず』→ 停滞は実在(60-180s・速い水力余力の枯渇)、900秒窓で開示。『矢印が合っていない・位相シフト?』→ 速度と位相は90°ずれる(振り子と同じ) — 色を位相に揃え、90°のずれ自体を注記と『綱引きの4拍子』で説明に変えた", "1F4E79", 12.5);
  card(s, 6.8, 3.55, 5.7, 1.95, "○ だから台帳がある",
    "介入#1〜#40: 全件に理由・出典・可逆手順。(仮)は(仮)と明記し、オーナー裁定を記録。失敗を隠すと次の失敗が見えなくなる — 誠実さは態度ではなく、仕組み。このスライド自体が、その仕組みの出力", "0F7B6C", 12.5);
  s.addText("つまずき → 観察 → 介入(台帳) → 検証 → だめなら戻す — このループが6ヶ月分、全部残っている", {
    x: 0.9, y: 5.85, w: 11.6, h: 0.4, fontFace: F, fontSize: 13.5, bold: true,
    color: INK, align: "center", margin: 0 });
  foot(s, 28, "0:50");
  s.addNotes("[コア]『意外とすんなり行っていない』の直球スライド。#40の負の結果・第10波LFCバグ・GIF作り直し3回を隠さず並べ、台帳の存在理由に落とす。0:50");
}

/* ============ 第6幕D 動: 全史トレーラー(GIF) ============ */
{
  const s = pres.addSlide();
  s.background = { color: "0A0D1A" };
  s.addImage({ path: A + "grand_trailer.gif", x: 0, y: 0, w: 13.33, h: 7.5 });
  s.addNotes("[標準]全史トレーラー第2版(20フレーム・37秒): 従来の5幕(組み上げ→UC→3島AC→探偵編→点灯→東N-3)に、第6幕『綱引き』(西の逆位相2カット、電力矢印はΔδ実符号で反転)と第7幕『戻るさま』(東N-3の900秒アーク・4局面チャート)を追加。締めは『いまは、ある。』。0:45");
}

/* ===================== 15. 6ヶ月で学んだこと ===================== */
{
  const s = pres.addSlide(); base(s);
  head(s, "総括", "6ヶ月で学んだこと：正直さは態度ではなく、仕組み", NAVY);
  const lessons = [
    ["捏造ゼロは構成的に成立させる", "「気をつける」では守れない。証拠の無い要素が出力に到達できない構造にする（第5幕の証拠閉包はその極致）"],
    ["モデルを良く見せる機構ほど台帳に載せる", "接続・解ける・完全に見せる介入#1〜#40すべてに根拠とOFFスイッチ。介入を隠すとバグと区別がつかなくなる"],
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
  foot(s, 29, "1:00");
  s.addNotes("[コア]各原則が生まれた事件と対応：①=v1.8証拠閉包 ②=v1.5介入台帳 ③=v1.5東AC解体 ④=v1.8 issue#49。最新の実例(2026-08-30深夜): 介入#40(人口傾斜)は実装→検証行列が退行を検出→既定OFFで台帳化、介入#39は帳簿の旧ID事故を名前アサートで修復 — どちらも③『収束は正しさではない』と②『台帳』が数字を守った夜。下帯の一文がこのデッキの結論。");
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
   ["負荷配分の粒度を上げる", "西は24/24全時刻AC達成済(第8波)。次は市区町村粒度化 — 全国メッシュ人口(#40)は部分被覆で退行し既定OFF、全国分の取得が前提"],
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
  foot(s, 30, "0:30");
  s.addNotes("[コア]論文カードの※は正直に残す（既知の宿題を隠さない — それ自体がこのプロジェクトの流儀）。質疑へ。");
}

// ── 上書き事故の防止(2026-08-30) ──────────────────────────────
// オーナーもPowerPointで直接編集・保存する。ビルドは既存pptxを問答無用で
// 上書きするため、書き出す前に必ず退避しておく(直近5世代)。
// オーナーの編集が入っていた場合は .bak から戻せる。
const fs = require("fs");
const path = require("path");
const OUT = "AllJapanGrid_story.pptx";
const BAKDIR = ".deck_backups";
if (fs.existsSync(OUT)) {
  if (!fs.existsSync(BAKDIR)) fs.mkdirSync(BAKDIR);
  const st = fs.statSync(OUT);
  const stamp = new Date(st.mtimeMs).toISOString()
    .replace(/[-:]/g, "").replace("T", "_").slice(0, 15);
  const bak = path.join(BAKDIR, `AllJapanGrid_story_${stamp}.pptx`);
  if (!fs.existsSync(bak)) fs.copyFileSync(OUT, bak);
  const olds = fs.readdirSync(BAKDIR).filter(f => f.endsWith(".pptx")).sort();
  olds.slice(0, Math.max(0, olds.length - 5))
      .forEach(f => fs.unlinkSync(path.join(BAKDIR, f)));
  const age = (Date.now() - st.mtimeMs) / 60000;
  console.log(`退避: ${bak}  (既存pptxの更新は${age.toFixed(0)}分前)`);
  if (age < 20) {
    console.log("  ⚠️  20分以内に更新されています — 手編集が入っていた場合は");
    console.log("      上の .deck_backups/ から復元してください");
  }
}
pres.writeFile({ fileName: OUT })
  .then(() => console.log("written: " + OUT));
