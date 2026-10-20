// Six-slide evidence supplement, matching the existing story deck's typography.
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath,pathToFileURL} from 'node:url';
const here=path.dirname(fileURLToPath(import.meta.url)),root=path.resolve(here,'../../..');
const runtime=path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies');
process.env.RUNTIME_NODE_MODULES=path.join(runtime,'node/node_modules');
const {Presentation,PresentationFile}=await import(pathToFileURL(path.join(process.env.RUNTIME_NODE_MODULES,'@oai/artifact-tool/dist/artifact_tool.mjs')));
const skill=path.join(os.homedir(),'.codex/plugins/cache/openai-primary-runtime/presentations/26.905.11957/skills/presentations');
const {finalizePresentation}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')));
const work=path.join(here,'ac_diagnosis'),build=path.join(work,'.build'),out=path.join(work,'output');
await fs.mkdir(build,{recursive:true});await fs.mkdir(out,{recursive:true});
const report=path.join(root,'docs/reports/codex_ac_diagnosis_2026-09-15');
const p=Presentation.create({slideSize:{width:1280,height:720}}),F='Hiragino Sans';
const C={ink:'#132A3E',mut:'#566A7C',blue:'#147F91',red:'#B34147'};let n=0;const owners=[],notes=[];
function tx(s,text,x,y,w,h,size=28,color=C.ink,bold=false){const t=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});t.text=text;t.text.style={typeface:F,fontSize:size,color,bold,autoFit:'none',verticalAlignment:'top',wrap:true};return t;}
function slide(title,note,source){const s=p.slides.add();s.background.fill='#FFFFFF';n++;tx(s,title,60,62,1160,95,43,C.ink,true);tx(s,source,64,667,1090,30,13,C.mut);tx(s,String(n).padStart(2,'0'),1180,665,50,30,17,C.mut);s.speakerNotes.textFrame.setText(note+'\n\n出典：'+source);notes.push({slide:n,title,note,source});return s;}
async function img(s,name,x,y,w,h){s.images.add({blob:new Uint8Array(await fs.readFile(path.join(report,name))),contentType:'image/png',fit:'contain',position:{left:x,top:y,width:w,height:h},alt:name});}
function table(s,values,x,y,w,h,widths,size=26){const t=s.tables.add({rows:values.length,columns:values[0].length,left:x,top:y,width:w,height:h,values,columnWidths:widths});t.borders.assign({fill:'#DCE5E9',width:1,style:'solid'});for(let i=0;i<values.length;i++)for(let j=0;j<values[0].length;j++){const c=t.getCell(i,j);c.fill=i===0?C.ink:'#FFFFFF';c.text.style={typeface:F,fontSize:size,color:i===0?'#FFFFFF':C.ink,bold:i===0};}owners.push(n);}
const results=JSON.parse(await fs.readFile(path.join(report,"results.json"),"utf8"));
const gsi='航空写真：国土地理院 ／ 元線形・設備外形：© OpenStreetMap contributors';
{
const s=slide('宮城中央支線の復元で、66 kV側の迂回が減る',
'対象は東日本の推定運転点55,250MW。目標需要での発電機Q制約付きACは未収束。写真と元OSM線形にある宮城中央支線がbuiltモデルで欠落していた。青葉幹線の元の経路を保持して分岐点を追加し、2回線の支線と構内引込を復元した。大郷の推定275/66kV変圧器も既存の枝も保持した。元モデルでは5母線の高電圧側に約628MWの発電があり、大郷66kV側へ抜けていた。示した負荷率はQ制約を外した診断値であり、運転可能な解ではない。追加線の定数は既存500kV既定値。撮影期間2023年10月〜11月。公式表 https://nw.tohoku-epco.co.jp/consignment/system/announcement/data/sys_capa_kikan01_line_202607_02.csv の0005行で500kV・2回線・方向を独立照合。',gsi+' / results.json');
await img(s,'figures/miyagi_overlay.png',60,165,730,490);
tx(s,'大郷66 kV線の負荷率',825,180,390,70,28,C.mut);
tx(s,'1,007% → 198%',825,265,390,80,42,C.blue,true);
tx(s,'幹線の分岐と\n構内引込を戻す',825,373,385,125,31);
tx(s,'Q制約なしの診断値\nQ制約付きACは未収束',825,538,385,100,25,C.red,true);
}
{
const s=slide('同一設備の需要重みを一回分にする',
'安良里の東京側・中部側の点は同じOSM way/409537787を参照する。モデル点の片方が敷地外にずれていた。元モデルは各点へ約23.017MWずつ合成需要を配分していた。70組の同じ元設備・同じ地域・同じモデル電圧の組について、需要重みを一設備分にし、複数母線に分担する。地域P/Q合計を保つよう再正規化し、推定80%補償シャントも需要と同じ比率で更新する。設備点・枝・発電機を消す変更は行わない。これは推定需要の事前分布の修正であり、観測需要の重複を証明したものではない。写真は2020年8月〜12月。',gsi+' / load_identity_plan.json');
await img(s,'figures/izu_overlay.png',60,165,580,485);
tx(s,'Before',694,178,500,55,28,C.mut,true);
tx(s,'同じ設備に、約23 MWずつ配分',694,238,500,95,30);
tx(s,'After',694,369,500,55,28,C.blue,true);
tx(s,'一設備分の重みを2点で分担\n地域の需要合計は保持',694,430,500,128,30);
tx(s,'設備IDで照合した70組を試験',694,585,500,55,25,C.mut);
}
{
const s=slide('接続と需要配分の変更を分けて比較する',
'すべて目標需要55,250MW、発電P58012.5MW。AC診断値はQ制約を外した解であり、Q上下限違反が残る。幹線の分割のみの対照ではDCの元線路最大潮流差は1.36e-9MW、AC損失差は0.0014MW。支線復元の効果とπ型線路の分割効果を分離した。需要重み補正は地域P/Q合計を保つが、各地点の注入と推定補償の配置を変える。実測値との誤差改善率は未評価。','results.json / pandapower 3.4.0 / NR 50反復・許容不整合1e-4 MVA');
table(s,[['条件','最低電圧pu','大郷線の負荷率','Q制約付きAC'],['元モデル','0.834','1,007%','未収束'],['幹線の分割のみ','0.834','1,007%','未収束'],['宮城中央支線を復元','0.834','198%','未収束'],['需要重みも補正','0.935','約198%','未収束']],64,176,1152,340,[405,222,280,245],26);
tx(s,'電圧と負荷率はQ制約なしの診断値',67,550,1145,60,30,C.red,true);
tx(s,'全設備・枝・発電機を保持し、地域の需要合計55,250 MWも保持',67,615,1145,43,24,C.mut);
}
{
const s=slide('YbusとAC Jacobianで、異なる問題を調べる',
'元Ybusは6253×6253、nnz20523。220基準母線を除いた行列の疎1ノルム条件数推定が5.27e7。修正後は6.12e7へ増加したため、条件数だけの改善指標は適切でない。元Ybus対角がゼロの2母線は孤立した基準母線であり、それだけでAC不収束とは判定しない。Q制約遷移の内側Newtonが失敗したとき、注入量ホモトピーで最後の収束点まで戻り、Jacobianの局所電圧感度を計算。Beforeは大郷、Afterは安良里・伊豆側が強く反応する。補間係数は需要倍率でも、供給可能率でも、解の存在の証明でもない。','results.json / ybus / q_transition_trace');
table(s,[['診断','Before','支線＋需要重み補正'],['基準母線を除いたYbus\n条件数の推定','5.27 × 10⁷','6.12 × 10⁷'],['Q制約適用後の\n電圧感度が強い場所','大郷66 kV','安良里・伊豆66 kV']],65,184,1150,260,[515,285,350],27);
tx(s,'数値感度と、物理的な経路・運転条件を別々に確認する',67,495,1145,94,31,C.blue,true);
tx(s,'条件数や反復失敗だけでは、AC解が存在しないとは言えない',67,603,1145,52,26,C.mut);
}
{
const s=slide('ACの方程式・Q上下限・運転範囲は別の判定',
'支線復元と70組の需要配分重み補正後に、需要・発電P・推定補償を同じ係数で変えた。線路・変圧器・Q上下限は固定。80%44,200MWでAC方程式とQ上下限を通過したが、最低電圧0.6857pu、231線路と103変圧器に過負荷がある。5%2762.5MWでは0.9〜1.1puと負荷率100%のスクリーニングも通過するが、通常運転達成の意味ではない。100%は地域ピーク設定の0.85倍。全点が220基準母線のうち208の仮想補給を含む。条件達成を現実の運転可能性と混同しない。','results.json / strict_operating_point_ramp');
table(s,[['需要・発電の比率','需要MW','方程式とQ制約','電圧・過負荷'],['100%（目標）','55,250','未収束','合格判定できず'],['80%','44,200','通過','未通過'],['5%','2,762.5','通過','仮の範囲で通過']],64,177,1152,280,[305,240,285,322],27);
tx(s,'80%でも最低電圧0.686 pu、過負荷が残る',67,506,1140,70,32,C.red,true);
tx(s,'電圧0.9–1.1 pu・負荷率100%は本試験の評価範囲\n実設備の正式な運用基準・仮想補給の妥当性は別途確認',67,583,1140,77,23,C.mut);
}
{
const s=slide('失敗した試験と、次に照合する設備',
'初期値変更、同一母線発電機の集約、補償比率の変更、仮のリアクトル、大郷変圧器の保留・容量増大、人口による需要傾斜、伊豆66kVの仮2回線化、Q制約の再解放を含む実験solverも、目標条件での合格は得られなかった。最終比較に採用したのは元データの支線復元と設備IDに基づく合成需要重み補正のみ。次は伊豆の供給端・回線数・地点需要、62件の両端電圧不一致、発電機AVR能力と運転P/Q、補償設備を一次資料で照合する。全探索結果・地図・Before/After・コードをHTMLに保存し、再実行CLIでClaudeが確認できる。','docs/AC_DIAGNOSIS_TOOL.md / Issue #53 / exploration/*.json');
table(s,[['試したこと','結果'],['初期値・発電機集約・補償量の変更','目標条件では未収束'],['人口傾斜・伊豆の仮2回線化','未収束。修正案に採用せず'],['Q制約の再解放を含む実験solver','不整合約32–33 MVAで停止']],65,175,1150,270,[780,370],27);
tx(s,'次の照合先：伊豆の供給端・回線数・地点需要',67,493,1145,73,31,C.blue,true);
tx(s,'再実行：python3 scripts/review_ac_solvability.py replay',67,585,1145,65,25,C.mut);
}
await fs.writeFile(path.join(work,'TALK_NOTES.md'),'# AC・Ybus診断：補足6枚\n\n'+notes.map(r=>`## ${r.slide}. ${r.title}\n\n${r.note}\n\n出典：${r.source}`).join('\n\n')+'\n');
const candidate=path.join(build,'candidate.pptx');await (await PresentationFile.exportPptx(p)).save(candidate);
const finalPath=path.join(out,'AllJapanGrid_AC_Ybus_review_2026-09-15.pptx');
const result=await finalizePresentation({workspaceDir:work,candidatePath:candidate,finalPath,
pythonExecutable:path.join(runtime,'python/bin/python3.12'),integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),
layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-heading-fit',...owners.flatMap(i=>['--require-native-table-slide',String(i)])],explicitTotalSlideCount:6,requiredNativeTableOwnerSlides:owners,fontPolicy:{basis:'design',families:[F]},verifyArtifactToolImport:true,receiptPath:path.join(build,'validation.json')});
for(let i=0;i<p.slides.items.length;i++){const render=await p.export({slide:p.slides.items[i],format:'png',scale:1});await fs.writeFile(path.join(build,`slide-${i+1}.png`),new Uint8Array(await render.arrayBuffer()));}
console.log(JSON.stringify({finalPath,result},null,2));
