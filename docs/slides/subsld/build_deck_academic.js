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


// ネイティブ display 数式: Cambria Math + 下付き/上付きの実テキスト(編集可能)
// runs: [text, opts] opts: i=italic, sub, sup, jp(和文), c=色, fs=級数
function meq(s, x, y, w, runs, fs, align) {
  const rr = runs.map(([t, o]) => {
    o = o || {};
    return { text: t, options: {
      fontFace: o.jp ? F : "Cambria Math",
      italic: !!o.i, subscript: !!o.sub, superscript: !!o.sup,
      color: o.c || INK, fontSize: o.fs || fs || 21,
    } };
  });
  s.addText(rr, { x, y, w, h: 0.62, margin: 0, valign: "middle",
    align: align || "center" });
}
// 数式の注釈行(小さく・薄く・中央)
function mnote(s, x, y, w, txt) {
  s.addText(txt, { x, y, w, h: 0.34, fontFace: F, fontSize: 11,
    color: MUT, align: "center", margin: 0 });
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
  s.addShape(pres.ShapeType.roundRect, { x: 0.7, y: 2.4, w: 12.0, h: 1.5,
    fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.06 });
  meq(s, 0.9, 2.52, 5.6, [
    ["q", {i:1}], ["(", {}], ["p", {i:1}], [") = ( round(", {}],
    ["φ", {i:1}], [", 5),  round(", {}], ["λ", {i:1}], [", 5) )", {}],
  ]);
  mnote(s, 0.9, 3.18, 5.6, "約1m格子への量子化 — 同一設備の融合キー");
  meq(s, 6.9, 2.52, 5.6, [
    ["G", {i:1}], ["I", {i:1, sub:1}], [" = ( ", {}], ["V", {i:1}],
    ["I", {i:1, sub:1}], [",  ", {}], ["E", {i:1}], ["I", {i:1, sub:1}],
    [" )", {}],
  ]);
  mnote(s, 6.9, 3.18, 5.6, "同期島 I ごとの座標グラフ");
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
  // 上向き矢印: 負の高さはOOXML不正(PowerPointが修復要求)。beginArrowで代替
  s.addShape(pres.ShapeType.line, { x: 11.3, y: 4.34, w: 0, h: 0.26,
    line: { color: MUT, width: 1.6, beginArrowType: "triangle" } });
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

// ---------- 4b. 概念図 ----------
{
  const s = pres.addSlide(); base(s);
  head(s, "3", "CONCEPT", "概念図 — 観測から証拠閉包、実証ペア図へ");
  const L = (x1,y1,x2,y2,o)=>{o=o||{};s.addShape(pres.ShapeType.line,{x:Math.min(x1,x2),y:Math.min(y1,y2),w:Math.abs(x2-x1),h:Math.abs(y2-y1),flipH:x2<x1,flipV:y2<y1,line:Object.assign({color:o.c||INK,width:o.w||1.5},o.d?{dashType:"dash"}:{}, o.a?{endArrowType:"triangle"}:{})});};
  // ===== 左: 観測 O =====
  s.addShape(pres.ShapeType.roundRect,{x:0.6,y:1.6,w:4.6,h:4.9,fill:{color:PANEL},line:{type:"none"},rectRadius:0.08});
  s.addText("観測 O（OSM）",{x:0.85,y:1.75,w:3.5,h:0.35,fontFace:F,fontSize:13,bold:true,color:NAVY,margin:0});
  // δ_lead帯(破線六角形の代わりに破線角丸)と敷地
  s.addShape(pres.ShapeType.roundRect,{x:1.25,y:2.5,w:3.2,h:2.6,fill:{type:"none"},line:{color:"9A9AA6",width:1.2,dashType:"dash"},rectRadius:0.25});
  s.addShape(pres.ShapeType.roundRect,{x:1.75,y:2.95,w:2.2,h:1.7,fill:{color:"FFFDF2"},line:{color:"E0A800",width:2.2},rectRadius:0.12});
  // 母線way(赤太線)
  L(2.0,3.5,3.7,3.5,{c:V500,w:4});
  s.addText("母線 way",{x:2.55,y:3.05,w:1.6,h:0.3,fontFace:F,fontSize:9.5,color:V500,margin:0});
  // 線1: vertex共有(端点=母線上の●)
  L(0.75,2.2,2.55,3.5,{c:V66,w:1.8});
  s.addShape(pres.ShapeType.ellipse,{x:2.47,y:3.42,w:0.16,h:0.16,fill:{color:V500},line:{color:"FFFFFF",width:1}});
  // 線2: polygon内包(端点=敷地内の■)
  L(0.75,4.9,3.15,4.15,{c:V66,w:1.8});
  s.addShape(pres.ShapeType.rect,{x:3.07,y:4.07,w:0.16,h:0.16,fill:{color:"1F77B4"},line:{color:"FFFFFF",width:1}});
  // 線3: leadin(帯内で途切れる・▲)
  L(4.95,2.1,4.05,2.75,{c:V66,w:1.8,d:1});
  s.addShape(pres.ShapeType.triangle,{x:3.95,y:2.66,w:0.18,h:0.16,fill:{color:V275},line:{color:"FFFFFF",width:1}});
  // 凡例
  s.addText([{text:"● vertex（頂点共有）  ",options:{color:V500}},{text:"■ polygon（内包）  ",options:{color:"1F77B4"}},{text:"▲ leadin（帯 δ）",options:{color:V275}}],{x:0.85,y:5.35,w:4.2,h:0.6,fontFace:F,fontSize:10,margin:0,lineSpacing:14});
  s.addText("黄=敷地 Poly(s) ／ 破線=引込帯 0.6km",{x:0.85,y:5.95,w:4.2,h:0.3,fontFace:F,fontSize:10,color:MUT,margin:0});
  // ===== 中央: F =====
  s.addShape(pres.ShapeType.rightArrow,{x:5.35,y:3.5,w:1.5,h:0.85,fill:{color:NAVY},line:{type:"none"}});
  s.addText("F",{x:5.35,y:3.5,w:1.3,h:0.85,fontFace:"Cambria Math",fontSize:20,italic:true,bold:true,color:"FFFFFF",align:"center",valign:"middle",margin:0});
  s.addText("証拠閉包",{x:5.25,y:4.45,w:1.7,h:0.3,fontFace:F,fontSize:10.5,color:NAVY,align:"center",margin:0});
  // ===== 右: 構造 S* とミニSLD =====
  s.addShape(pres.ShapeType.roundRect,{x:7.05,y:1.6,w:5.6,h:4.9,fill:{color:PANEL},line:{type:"none"},rectRadius:0.08});
  s.addText("構造 S*（node-breaker） → SubSLD",{x:7.3,y:1.75,w:5.1,h:0.35,fontFace:F,fontSize:13,bold:true,color:NAVY,margin:0});
  // 構造ツリー
  const tx=7.45, ty=2.25;
  s.addText("Site s",{x:tx,y:ty,w:1.5,h:0.3,fontFace:FM,fontSize:11,color:INK,margin:0});
  L(tx+0.12,ty+0.32,tx+0.12,ty+1.32,{c:MUT,w:1});
  L(tx+0.12,ty+0.52,tx+0.42,ty+0.52,{c:MUT,w:1});
  s.addText("VL 500kV ─ Busbar ─ Terminal(●)",{x:tx+0.5,y:ty+0.36,w:4.6,h:0.3,fontFace:FM,fontSize:10.5,color:V500,margin:0});
  L(tx+0.12,ty+0.92,tx+0.42,ty+0.92,{c:MUT,w:1});
  s.addText("VL 66kV  ─ Terminal(▲)",{x:tx+0.5,y:ty+0.76,w:4.6,h:0.3,fontFace:FM,fontSize:10.5,color:V66,margin:0});
  L(tx+0.12,ty+1.32,tx+0.42,ty+1.32,{c:MUT,w:1});
  s.addText("Trafo(structural)",{x:tx+0.5,y:ty+1.16,w:4.6,h:0.3,fontFace:FM,fontSize:10.5,color:"444444",margin:0});
  // ミニSLD
  const bx=7.6, by=4.5, bw=3.6;
  L(bx,by,bx+bw,by,{c:V500,w:3.5});
  L(bx+0.5,by,bx+0.5,by-0.45,{c:V500,w:1.5}); L(bx+0.64,by,bx+0.64,by-0.45,{c:V500,w:1.5});
  L(bx+1.6,by,bx+1.6,by-0.45,{c:V500,w:1.5});
  L(bx,by+1.15,bx+bw,by+1.15,{c:V66,w:3.5});
  L(bx+0.9,by+1.15,bx+0.9,by+1.6,{c:V66,w:1.5,d:1});
  const txx=bx+2.9;
  L(txx,by,txx,by+1.15,{c:"444444",w:1.5});
  s.addShape(pres.ShapeType.ellipse,{x:txx-0.14,y:by+0.32,w:0.28,h:0.28,fill:{type:"none"},line:{color:"444444",width:1.5}});
  s.addShape(pres.ShapeType.ellipse,{x:txx-0.14,y:by+0.52,w:0.28,h:0.28,fill:{type:"none"},line:{color:"444444",width:1.5}});
  s.addText("2回線=2ストローク ／ 破線=leadin ／ 二重円=変圧器",{x:7.45,y:6.05,w:5.0,h:0.3,fontFace:F,fontSize:10,color:MUT,margin:0});
  // 証人の対応(点線)
  L(3.05,4.15,7.42,2.62,{c:"9A9AA6",w:1,d:1});
  s.addText("witnesses（全要素が観測へ遡れる）",{x:4.7,y:3.05,w:2.6,h:0.55,fontFace:F,fontSize:9.5,color:MUT,align:"center",margin:0,lineSpacing:13});
  s.addText("観測に証人を持つ要素だけが構造になり、その構造だけが描かれる — 概念図の全要素が §4-7 の定義に対応する。",{x:0.7,y:6.62,w:12.2,h:0.4,fontFace:F,fontSize:11.5,color:MUT,margin:0});
  foot(s, 5);
}

// ---------- 5. 定式化: 証拠閉包作用素 ----------
{
  const s = pres.addSlide(); base(s);
  head(s, "4", "FORMULATION", "定式化 — 構造抽出は「証拠閉包」作用素");
  s.addText("観測 O =（敷地ポリゴン, way集合, タグ）から構造 S への写像 F を、「証拠に支持される要素すべてからなる最大の構造」として定義する。ルールの列挙ではなく、この閉包が手法の本体である。", {
    x: 0.7, y: 1.58, w: 12.0, h: 0.8, fontFace: F, fontSize: 13.5,
    color: INK, lineSpacing: 21, margin: 0 });
  s.addShape(pres.ShapeType.roundRect, { x: 0.7, y: 2.5, w: 12.0, h: 1.05,
    fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.06 });
  meq(s, 0.9, 2.72, 11.6, [
    ["F", {i:1}], ["(", {}], ["O", {i:1}], [")  =  S", {}],
    ["*", {sup:1}], ["  =  { ", {}], ["x", {i:1}],
    ["  |  witnesses(", {}], ["x", {i:1}], [", ", {}], ["O", {i:1}],
    [") ≠ ∅ }", {}],
  ], 22);
  // 命題1
  s.addShape(pres.ShapeType.roundRect, { x: 0.7, y: 3.85, w: 12.0, h: 2.3,
    fill: { color: "FFFFFF" }, line: { color: NAVY, width: 1.2 },
    rectRadius: 0.06 });
  s.addText("命題 1（Fの性質）", { x: 1.0, y: 4.05, w: 5, h: 0.4,
    fontFace: F, fontSize: 14, bold: true, color: NAVY, margin: 0 });
  s.addText([
    { text: "(i) 決定性: ", options: { bold: true } },
    { text: "F は関数（同一入力→同一出力・全国テストで機械検証）　", options: {} },
    { text: "(ii) 冪等性: ", options: { bold: true, breakLine: false } },
    { text: "F の再適用は構造を変えない（regen 安全）", options: { breakLine: true } },
    { text: "(iii) 健全性: ", options: { bold: true } },
    { text: "S* の全要素は証拠の証人を持つ（構成より直ちに成立 — 「捏造ゼロ」の形式的表現）。逆に完全性は OSM 被覆に依存し、これは主張せず測定して報告する（§10）", options: {} },
  ], { x: 1.0, y: 4.55, w: 11.4, h: 1.5, fontFace: F, fontSize: 12.5,
    color: INK, lineSpacing: 21, margin: 0 });
  s.addText("Algorithm 1（構内wayの連結成分分解＋端子束縛）は F の計算的実現である。擬似コードは補遺に。", {
    x: 0.7, y: 6.4, w: 12, h: 0.4, fontFace: F, fontSize: 11.5,
    color: MUT, margin: 0 });
  foot(s, 6);
}

// ---------- 6. 証拠の辞書式順序とゲート ----------
{
  const s = pres.addSlide(); base(s);
  head(s, "5", "EVIDENCE ORDER", "端子束縛 — 証拠の辞書式最大化と整合制約");
  s.addText("線端 t の束縛は、証拠クラスの全順序 ≻ の下で成立する最強の証拠を選ぶ argmax として定義する。弱い証拠は図でも弱く（破線で）描かれ、証拠の強さが可視化まで貫通する。", {
    x: 0.7, y: 1.58, w: 12.0, h: 0.8, fontFace: F, fontSize: 13.5,
    color: INK, lineSpacing: 21, margin: 0 });
  s.addShape(pres.ShapeType.roundRect, { x: 0.7, y: 2.55, w: 12.0, h: 1.5,
    fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.06 });
  meq(s, 0.9, 2.7, 11.6, [
    ["binding(", {}], ["t", {i:1}], [")  =  max", {}], ["≻", {sub:1}],
    ["  { ", {}], ["e", {i:1}], ["  |  ", {}], ["e", {i:1}],
    [" は t の証人 }", {jp:1, fs:15}],
  ], 21);
  meq(s, 0.9, 3.4, 11.6, [
    ["vertex  ≻  polygon  ≻  leadin", {}],
    ["    （頂点共有 ≻ 敷地内包 ≻ 引込帯 0.6 km）", {jp:1, fs:12, c:MUT}],
  ], 17);
  s.addText("整合制約 — 電圧整合ゲート", { x: 0.7, y: 4.4, w: 6, h: 0.4,
    fontFace: F, fontSize: 14, bold: true, color: NAVY, margin: 0 });
  s.addShape(pres.ShapeType.roundRect, { x: 0.7, y: 4.85, w: 12.0, h: 0.95,
    fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.06 });
  meq(s, 0.9, 5.03, 11.6, [
    ["admit(", {}], ["ℓ", {i:1}], [", ", {}], ["n", {i:1}],
    [")  ⇔  witnesses ≠ ∅  ∧  ¬( |", {}], [" kv", {i:1}],
    ["ℓ", {i:1, sub:1}], [" − ", {}], ["kv", {i:1}], ["n", {i:1, sub:1}],
    [" | > 0.25 ⋅ max(", {}], ["kv", {i:1}], ["n", {i:1, sub:1}],
    [", 1) )", {}],
  ], 19);
  // 2ケースの事例図: 適合 / 棄却
  const caseBox = (x, title, ok) => {
    s.addShape(pres.ShapeType.roundRect, { x, y: 5.95, w: 5.85, h: 1.05,
      fill: { color: "FFFFFF" }, line: { color: ok ? "2E7D32" : V500,
      width: 1.1 }, rectRadius: 0.06 });
    s.addText(title, { x: x + 0.85, y: 6.03, w: 2.2, h: 0.3, fontFace: F,
      fontSize: 10.5, bold: true, color: ok ? "2E7D32" : V500, margin: 0 });
    s.addText(ok ? "✓" : "✗", { x: x + 0.2, y: 6.15, w: 0.55, h: 0.6,
      fontFace: F, fontSize: 26, bold: true,
      color: ok ? "2E7D32" : V500, margin: 0 });
  };
  caseBox(0.7, "ケースA 適合（接続）", true);
  s.addShape(pres.ShapeType.line, { x: 1.7, y: 6.62, w: 1.7, h: 0,
    line: { color: V66, width: 2.2 } });
  s.addShape(pres.ShapeType.ellipse, { x: 3.38, y: 6.54, w: 0.16, h: 0.16,
    fill: { color: V66 }, line: { type: "none" } });
  s.addText([{ text: "66kV線 → 66kVノード:  ", options: { color: INK } },
    { text: "|66−66| = 0 ≤ 25%", options: { color: "2E7D32" } }],
    { x: 3.7, y: 6.5, w: 2.8, h: 0.42, fontFace: F, fontSize: 10.5,
      margin: 0 });
  caseBox(6.85, "ケースB 棄却（c1 実例）", false);
  s.addShape(pres.ShapeType.line, { x: 7.85, y: 6.62, w: 1.7, h: 0,
    line: { color: V66, width: 2.2 } });
  s.addShape(pres.ShapeType.ellipse, { x: 9.53, y: 6.54, w: 0.16, h: 0.16,
    fill: { color: V154 }, line: { type: "none" } });
  s.addText([{ text: "66kV線 → 154kVノード:  ", options: { color: INK } },
    { text: "乖離133% > 25%", options: { color: V500 } }],
    { x: 9.85, y: 6.5, w: 2.9, h: 0.42, fontFace: F, fontSize: 10.5,
      margin: 0 });
  s.addText("ケースBは併架・並走回廊の物理近接（80m以内）だったが棄却が正解 — 後に断片側が登録人工物と判明（2026-08-20 c1）。", {
    x: 0.7, y: 7.06, w: 12.2, h: 0.32, fontFace: F, fontSize: 10,
    color: MUT, margin: 0 });
}

// ---------- 7. 下界性命題 ----------
{
  const s = pres.addSlide(); base(s);
  head(s, "6", "ESTIMATION", "回線数推定 — 証明付き下界推定器");
  s.addText("「無タグを推測で埋めない」を、推定器の下界性として定式化する。タグ意味論の仮定の下で、集約値は真値を決して過大評価しない。", {
    x: 0.7, y: 1.58, w: 12.0, h: 0.7, fontFace: F, fontSize: 13.5,
    color: INK, lineSpacing: 21, margin: 0 });
  s.addShape(pres.ShapeType.roundRect, { x: 0.7, y: 2.45, w: 12.0, h: 1.05,
    fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.06 });
  meq(s, 0.9, 2.67, 11.6, [
    ["ĉ", {i:1}], ["(", {}], ["w", {i:1}], [")  =  ", {}],
    ["c", {i:1}], ["tag", {sub:1}], ["   |   ⌊ ", {}], ["n", {i:1}],
    ["cables", {sub:1}], [" / 3 ⌋   |   1", {}],
    ["      （タグあり／cablesのみ／証拠なし）", {jp:1, fs:12, c:MUT}],
  ], 21);
  // 命題2
  s.addShape(pres.ShapeType.roundRect, { x: 0.7, y: 3.8, w: 12.0, h: 2.75,
    fill: { color: "FFFFFF" }, line: { color: NAVY, width: 1.2 },
    rectRadius: 0.06 });
  s.addText("命題 2（下界性）", { x: 1.0, y: 3.98, w: 5, h: 0.4,
    fontFace: F, fontSize: 14, bold: true, color: NAVY, margin: 0 });
  meq(s, 1.0, 4.42, 11.2, [
    ["c", {i:1}], ["sum", {sub:1}], ["(", {}], ["s", {i:1}], [", ", {}],
    ["v", {i:1}], [")   ≤   ", {}],
    ["c", {i:1}], ["est", {sub:1}], ["(", {}], ["s", {i:1}], [", ", {}],
    ["v", {i:1}], [")   ≤   ", {}],
    ["c", {i:1}], ["true", {sub:1}], ["(", {}], ["s", {i:1}], [", ", {}],
    ["v", {i:1}], [")", {}],
  ], 22, "center");
  s.addText("∵ 各線で ĉ(w) ≤ c_true(w)：タグ値は真値（仮定A1: circuitsタグは正しい）、⌊cables/3⌋ は3相導体数からの下界（A2）、実在する線は1回線以上。", {
    x: 1.0, y: 5.0, w: 11.4, h: 0.4, fontFace: F, fontSize: 11.5,
    color: MUT, margin: 0 });
  // 下界性の数直線(概念図)
  s.addShape(pres.ShapeType.line, { x: 2.2, y: 5.62, w: 8.9, h: 0,
    line: { color: INK, width: 1.5, endArrowType: "triangle" } });
  const tick = (x, lab, col, it) => {
    s.addShape(pres.ShapeType.line, { x, y: 5.5, w: 0, h: 0.24,
      line: { color: col, width: 2.2 } });
    s.addText(lab, { x: x - 0.7, y: 5.8, w: 1.4, h: 0.3,
      fontFace: "Cambria Math", italic: true, fontSize: 13, color: col,
      align: "center", margin: 0 });
  };
  tick(3.4, "c sum", V66); tick(5.6, "c est", NAVY); tick(9.2, "c true", V500);
  s.addShape(pres.ShapeType.rect, { x: 5.6, y: 5.54, w: 3.6, h: 0.16,
    fill: { color: "F2C4C4" }, line: { type: "none" } });
  s.addText("未観測ぶん（欠測）— 推測で埋めず、この幅自体を測って報告", {
    x: 5.3, y: 6.12, w: 5.5, h: 0.3, fontFace: F, fontSize: 10,
    color: MUT, margin: 0 });
  s.addText("系: 表示回線数は「少なくともこれだけ存在する」の主張 — 系統計算でも容量を過大評価しない側に誤る（導体数 wires も同構成で下界）。", {
    x: 0.7, y: 6.7, w: 12.0, h: 0.4, fontFace: F, fontSize: 12,
    color: INK, margin: 0 });
  foot(s, 8);
}

// ---------- 8. 三値流向推定器 ----------
{
  const s = pres.addSlide(); base(s);
  head(s, "7", "INFERENCE", "流向推定 — 電圧半順序上の三値推定器");
  s.addText("変電所集合に「最大電圧階級」による半順序を入れ、線グループ g の流向を三値推定器 d̂ で与える。判定不能は無理に埋めず、棄権 ⊥ を第三の出力として原理化する（図では灰）。", {
    x: 0.7, y: 1.58, w: 12.0, h: 0.8, fontFace: F, fontSize: 13.5,
    color: INK, lineSpacing: 21, margin: 0 });
  s.addShape(pres.ShapeType.roundRect, { x: 0.7, y: 2.6, w: 8.35, h: 2.35,
    fill: { color: PANEL }, line: { type: "none" }, rectRadius: 0.06 });
  // 概念図: 電圧半順序の梯子
  s.addShape(pres.ShapeType.roundRect, { x: 9.3, y: 2.6, w: 3.4, h: 2.35,
    fill: { color: "FFFFFF" }, line: { color: "D8D8DE", width: 0.9 },
    rectRadius: 0.06 });
  s.addText("s′ ≻ v", { x: 9.55, y: 2.75, w: 1.3, h: 0.3, fontFace: "Cambria Math",
    italic: true, fontSize: 12, color: V500, margin: 0 });
  s.addShape(pres.ShapeType.line, { x: 10.9, y: 2.98, w: 0, h: 0.5,
    line: { color: V500, width: 2, endArrowType: "triangle" } });
  s.addText("in", { x: 11.05, y: 3.05, w: 0.6, h: 0.3, fontFace: FL,
    fontSize: 11, bold: true, color: V500, margin: 0 });
  s.addShape(pres.ShapeType.line, { x: 9.55, y: 3.62, w: 2.9, h: 0,
    line: { color: INK, width: 2.5 } });
  s.addText("v（自所の階級）", { x: 9.55, y: 3.7, w: 2.5, h: 0.28,
    fontFace: F, fontSize: 9.5, color: INK, margin: 0 });
  s.addText("s′ ∼ v", { x: 9.55, y: 4.08, w: 1.3, h: 0.3, fontFace: "Cambria Math",
    italic: true, fontSize: 12, color: V66, margin: 0 });
  s.addShape(pres.ShapeType.line, { x: 10.9, y: 4.05, w: 0, h: 0.5,
    line: { color: V66, width: 2, beginArrowType: "triangle" } });
  s.addText("out", { x: 11.05, y: 4.25, w: 0.7, h: 0.3, fontFace: FL,
    fontSize: 11, bold: true, color: V66, margin: 0 });
  s.addText("far=∅ → ⊥（灰）", { x: 11.55, y: 4.6, w: 1.4, h: 0.3,
    fontFace: F, fontSize: 9, color: MUT, margin: 0 });
  meq(s, 0.9, 2.75, 7.9, [
    ["d̂", {i:1}], [" :  ", {}], ["G", {i:1}],
    ["  →  { in,  out,  ⊥ }", {}],
  ], 21);
  meq(s, 0.9, 3.38, 7.9, [
    ["d̂", {i:1}], ["(", {}], ["g", {i:1}], [") = in", {}],
    ["   ⇔   ∃", {}], ["s′", {i:1}], ["∈far(", {}], ["g", {i:1}],
    ["):  ", {}], ["s′", {i:1}], [" ≻ ", {}], ["v", {i:1}],
    ["      ∨      ", {c:MUT}], ["kv", {i:1}], ["v", {i:1, sub:1}],
    [" = kv", {}], ["top", {sub:1}], ["(", {}], ["s", {i:1}], [")", {}],
  ], 18);
  meq(s, 0.9, 3.98, 7.9, [
    ["d̂", {i:1}], ["(", {}], ["g", {i:1}], [") = ⊥", {}],
    ["   ⇔   far(", {}], ["g", {i:1}], [") = ∅", {}],
    ["      （対向が解決できない時は棄権 — 埋めない）", {jp:1, fs:12, c:MUT}],
  ], 18);
  s.addText("far(g) は connections（両端束縛線）を第一資料とし、欠測時のみ線名の name-evidence（「A~B線」等）で補完する。棄権率は隠さず評価指標として報告する — 棄権の主因は対向変電所自体の OSM 欠測であり、手法の誤りではなくデータ被覆の測定値である。", {
    x: 0.7, y: 5.2, w: 12.0, h: 1.0, fontFace: F, fontSize: 12.5,
    color: INK, lineSpacing: 20, margin: 0 });
  foot(s, 9);
}

// ---------- 9. 結果: 実証ペア図 ----------
{
  const s = pres.addSlide(); base(s);
  head(s, "8", "RESULTS", "実証ペア図 — 新京葉変電所（500/275/154/66kV）");
  s.addImage({ path: "assets/pair_full.png", x: 0.85, y: 1.62, w: 11.6,
    h: 5.15, sizing: { type: "contain", w: 11.6, h: 5.15 } });
  s.addText("図1  実証ペア図（新京葉変電所）。左: GeoPane（構内幾何・端子根拠・鉄塔・インセット）　右: SLDPane（母線セクション・回線ストローク・流向・変圧器・スルー）", {
    x: 0.85, y: 6.78, w: 11.8, h: 0.35, fontFace: F, fontSize: 11,
    color: MUT, margin: 0 });
  foot(s, 10);
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
  s.addText("図2  各地域の代表例（GeoPane 抜粋）。バッチ生成器（再開可能・タイルキャッシュ）により全所を一括描画 — 約1〜6秒/所・10地域並列で全国約1時間（pws-160core 実測）。", {
    x: 0.7, y: 6.25, w: 12.2, h: 0.65, fontFace: F, fontSize: 12,
    color: MUT, lineSpacing: 18, margin: 0 });
  foot(s, 11);
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
  foot(s, 12);
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
  foot(s, 13);
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
  foot(s, 14);
}

pres.writeFile({ fileName: "SubSLD_academic.pptx" }).then(() => console.log("written"));
