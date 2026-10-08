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
const work=path.join(here,'site_trial'),build=path.join(work,'.build'),out=path.join(work,'output');
await fs.mkdir(build,{recursive:true});await fs.mkdir(out,{recursive:true});
const report=path.join(root,'docs/reports/codex_same_site_trial_2026-09-13');
const p=Presentation.create({slideSize:{width:1280,height:720}}),F='Hiragino Sans';
const C={ink:'#132A3E',mut:'#566A7C',blue:'#147F91',red:'#B34147'};let n=0;const owners=[],notes=[];
function tx(s,text,x,y,w,h,size=28,color=C.ink,bold=false){const t=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});t.text=text;t.text.style={typeface:F,fontSize:size,color,bold,autoFit:'none',verticalAlignment:'top',wrap:true};return t;}
function slide(title,note,source){const s=p.slides.add();s.background.fill='#FFFFFF';n++;tx(s,title,60,62,1160,95,43,C.ink,true);tx(s,source,64,667,1090,30,13,C.mut);tx(s,String(n).padStart(2,'0'),1180,665,50,30,17,C.mut);s.speakerNotes.textFrame.setText(note+'\n\n出典：'+source);notes.push({slide:n,title,note,source});return s;}
async function img(s,name,x,y,w,h){s.images.add({blob:new Uint8Array(await fs.readFile(path.join(report,name))),contentType:'image/png',fit:'contain',position:{left:x,top:y,width:w,height:h},alt:name});}
function table(s,values,x,y,w,h,widths,size=26){const t=s.tables.add({rows:values.length,columns:values[0].length,left:x,top:y,width:w,height:h,values,columnWidths:widths});t.borders.assign({fill:'#DCE5E9',width:1,style:'solid'});for(let i=0;i<values.length;i++)for(let j=0;j<values[0].length;j++){const c=t.getCell(i,j);c.fill=i===0?C.ink:'#FFFFFF';c.text.style={typeface:F,fontSize:size,color:i===0?'#FFFFFF':C.ink,bold:i===0};}owners.push(n);}
const gsi='航空写真：国土地理院 https://maps.gsi.go.jp/development/ichiran.html ／ 敷地・線形：© OpenStreetMap contributors';
{
const s=slide('実在する敷地と線端を残す',
'秩父の第三案。紫のS1は元OSM敷地の表示用代表点であり、母線の実測位置ではない。T1/T2は保存線形の端。敷地から離れた代表座標へすべてを吸着すると、設備の実在位置と接続の不確実性が消えてしまう。第三案は元モデルの記録を保持し、設備への所属を別の対応表に持つ。直線の引込を描き足す操作ではない。写真は2024年4月。保存線形には以前の再構成区間も含む。',gsi);
await img(s,'chichibu_terminals.png',62,166,665,490);
tx(s,'敷地は、地図上の位置に残す',764,188,446,95,31,C.blue,true);
tx(s,'線端の位置と、どの母線へ\n属するかを別に記録する',764,314,446,130,29);
tx(s,'不明な接続も消さず、\n追加で調べる根拠を残す',764,492,446,116,29,C.mut);
}
{
const s=slide('同定で断片は減ったが、実配線は未確定',
'最初は同名500m以内の27組をOSM IDと電圧で照合し、13組を複製モデルで同定した。元電圧タグが一致する5組と、欠測の8組を分けて比較した。これは当初の対照実験の記録。その後、航空写真を実際に全27組目視し、別の5組（渋川市・福島・保渡田町・古里・中村）を引込先の再追跡へ戻した。断片の減少を物理精度向上と同一視しない。正典は未適用。','trial.json / visual_review.json / source SHA 955d6e0b…e33b6a');
table(s,[['複製モデルの条件','東日本の地理的断片','AC / 固定条件'],['変更前','221','未収束'],['元電圧タグ一致の5組','216','未収束'],['同一モデル電圧の13組','210','未収束']],65,180,1150,290,[460,320,370],27);
tx(s,'写真による再評価：13組のうち5組は引込先の再追跡へ',67,515,1145,64,31,C.red,true);
tx(s,'残る8組も、端子・電圧を追加確認する調査候補',67,595,1145,45,27,C.mut);
}
{
const s=slide('写真で見直した渋川市の引込先',
'航空写真ではAが河岸の実在敷地に重なる。一方、Bは約398m離れ、鉄道を隔てた耕地側にある。元のOSM IDが同じことは重複レコードの仮説を支持するが、B周辺の枝がすべてAへ入ることの根拠にはならない。このため単純同定の適用候補から再追跡へ戻した。第三案では敷地そのものを保持し、既存の枝端を元wayと結び直す調査対象として残す。撮影期間は2020年5月〜8月。',gsi);
await img(s,'shibukawa_photo.png',62,170,668,479);
tx(s,'A：実在敷地の中',767,189,443,56,31,C.blue,true);
tx(s,'B：約400 m離れた耕地側',767,290,443,98,31,C.red,true);
tx(s,'同じ設備IDでも、\nBの枝の所属は未確定',767,425,443,117,29);
tx(s,'敷地から引込を再追跡する',767,571,443,67,27,C.mut);
}
{
const s=slide('秩父で見つかった保存線形の重複',
'黄色は保存線形の共通区間の局所図。枝5923「宮地線」の9区間すべてが、復元枝19942にも含まれ、共通区間長は約1.350934km。元の回線数は2と1で異なる。復元枝は6wayを連結し、継ぎ目最大194mという来歴を持つ。同形の並列回線もあり得るので、図だけでどちらかを削除してはいけない。元way・回線ID・途中端子を追い、共通区間と専用区間を分けて扱う対象である。同じ基準の周辺監査では42組を検出したが、誤回線42組の確定ではない。',gsi+' / path_overlaps.json OV13');
await img(s,'chichibu_overlap.png',62,170,668,479);
tx(s,'9 / 9 区間が共通',766,187,445,74,36,C.red,true);
tx(s,'約1.351 km',766,282,445,83,48,C.blue,true);
tx(s,'回線数の記録は 2 と 1',766,407,445,80,29);
tx(s,'元way・途中端子・回線IDを\n確認して区間ごとに扱う',766,529,445,111,28,C.mut);
}
{
const s=slide('敷地・線端・母線を別の記録にする',
'第三案の実装はsite_terminals.py。敷地は元の形状と内部代表点、枝端は保存線形の端と既存ビルダーの割当根拠、母線は電圧別ID、欠測は未解決として残す。保存線形から確認できる端と、線形のない推定引込を区別する。画像上で敷地を横断する線も、単に線を切って母線へ自動接続しない。元17,738ノードと19,944枝の記録は保持し、13組の同定仮説を計算用に集約する。','src/powerflow/site_terminals.py / site_terminals.json');
table(s,[['対象','保持する情報','接続との関係'],['敷地','形状・設備ID・表示位置','同じ場所だけでは母線を統合しない'],['枝端','保存線形の端・元の割当','敷地内・敷地外・線形欠測を区別'],['母線','電圧別のID','地図上の位置に依存せず指定'],['未解決','不足する根拠・矛盾','設備・枝を消さずに再調査へ']],64,172,1152,370,[190,415,547],26);
tx(s,'70枝端を記録：保存線形なし21、敷地外終端33など',66,588,1148,62,28,C.blue,true);
}
{
const s=slide('表示位置を戻しても、回路の計算を保てる',
'実際の東日本回路を一度組み、負荷55,250MW、無効電力約18,159.80Mvar、発電P設定58,012.5MWを固定した。単純同定案と第三案の電気テーブルを比較し、バスgeo以外のバス属性、line、trafo、load、gen、sgen、shunt、switchが一致した。第三案では34バスの表示位置を元敷地の代表点へ戻したが、DC最大枝潮流差は0MWだった。同一電気系なので表示変更のためにACは再実行していない。先行する固定NR/DC初期値50反復のAC未収束が残る。地理と回路を分けられることの検証で、実配線の正しさの証明ではない。','site_terminal_verification.json / powerflow.json');
table(s,[['固定したもの','単純同定案と第三案'],['線路 / 変圧器','6,467本 / 677台で一致'],['負荷','55,250 MWで一致'],['電気定数・機器の注入値','全比較テーブルで一致'],['DCの最大枝潮流差','0 MW']],65,176,1150,338,[550,600],28);
tx(s,'ACは先行試行で未収束。表示だけの変更では再計算していない',66,551,1144,89,28,C.red,true);
}
await fs.writeFile(path.join(work,'TALK_NOTES.md'),'# 敷地と線端を残す接続モデル：補足6枚\n\n'+notes.map(r=>`## ${r.slide}. ${r.title}\n\n${r.note}\n\n出典：${r.source}`).join('\n\n')+'\n');
const candidate=path.join(build,'candidate.pptx');await (await PresentationFile.exportPptx(p)).save(candidate);
const finalPath=path.join(out,'AllJapanGrid_site_terminal_review_2026-09-14.pptx');
const result=await finalizePresentation({workspaceDir:work,candidatePath:candidate,finalPath,
pythonExecutable:path.join(runtime,'python/bin/python3.12'),integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),
layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-heading-fit',...owners.flatMap(i=>['--require-native-table-slide',String(i)])],explicitTotalSlideCount:6,requiredNativeTableOwnerSlides:owners,fontPolicy:{basis:'design',families:[F]},verifyArtifactToolImport:true,receiptPath:path.join(build,'validation.json')});
for(let i=0;i<p.slides.items.length;i++){const render=await p.export({slide:p.slides.items[i],format:'png',scale:1});await fs.writeFile(path.join(build,`slide-${i+1}.png`),new Uint8Array(await render.arrayBuffer()));}
console.log(JSON.stringify({finalPath,result},null,2));
