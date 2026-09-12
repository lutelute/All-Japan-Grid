// Story revision: research question, substation semantics, evidence, verification.
// Usage: RUNTIME_NODE_MODULES=.../node_modules node build_story_revised.mjs
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath,pathToFileURL} from 'node:url';
const here=path.dirname(fileURLToPath(import.meta.url));
const root=path.resolve(here,'../../..');
const modules=process.env.RUNTIME_NODE_MODULES ?? path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
process.env.RUNTIME_NODE_MODULES=modules;
const {Presentation,PresentationFile}=await import(pathToFileURL(path.join(modules,'@oai/artifact-tool/dist/artifact_tool.mjs')));
const SKILL=path.join(os.homedir(),'.codex/plugins/cache/openai-primary-runtime/presentations/26.905.11957/skills/presentations');
const {finalizePresentation}=await import(pathToFileURL(path.join(SKILL,'container_tools/artifact_tool_utils.mjs')));
const work=path.join(here,'revised');const build=path.join(work,'.build');
await fs.mkdir(build,{recursive:true});await fs.mkdir(path.join(work,'output'),{recursive:true});
const p=Presentation.create({slideSize:{width:1280,height:720}});
const F='Hiragino Sans';const C={ink:'#132A3E',mut:'#566A7C',blue:'#147F91',red:'#C53D45',navy:'#0A0D1A',light:'#ECF2F4'};
let num=0;let noteRows=[];const tableOwners=[];
const paper='投稿用PDF：papers/ieej_submit.pdf';
const subsld='SubSLD原稿：papers/subsld/subsld.tex（v1.8の評価値）';
const audit=JSON.parse(await fs.readFile(path.join(root,'docs/reports/codex_connection_audit_2026-09-12/connections.json'),'utf8'));
const freq=JSON.parse(await fs.readFile(path.join(work,'assets/frequency_summary.json'),'utf8'));
function tx(s,text,x,y,w,h,size=27,color=C.ink,bold=false){
 const t=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 t.text=text;t.text.style={typeface:F,fontSize:size,color,bold,autoFit:'none',verticalAlignment:'top',wrap:true};return t;
}
function slide(title,chapter,notes,source='',dark=false){
 const s=p.slides.add();num++;s.background.fill=dark?C.navy:'#FFFFFF';
 tx(s,chapter,64,25,1100,26,16,dark?'#68CED3':C.blue,true);
 tx(s,title,60,68,1160,100,43,dark?'#FFFFFF':C.ink,true);
 tx(s,source,64,664,1090,36,14,dark?'#A6B6C6':C.mut);
 tx(s,String(num).padStart(2,'0'),1175,669,48,28,17,dark?'#A6B6C6':C.mut);
 s.speakerNotes.textFrame.setText(notes+'\n\n出典：'+source);
 noteRows.push({n:num,title,notes,source});return s;
}
async function img(s,rel,x,y,w,h){
 const file=path.resolve(root,rel);const ext=path.extname(file).toLowerCase();
 return s.images.add({blob:new Uint8Array(await fs.readFile(file)),contentType:ext==='.gif'?'image/gif':ext==='.jpg'?'image/jpeg':'image/png',fit:'contain',alt:path.basename(file),position:{left:x,top:y,width:w,height:h}});
}
function note(s,text,y=596,color=C.blue){tx(s,text,64,y,1145,54,26,color,true);}
function rows(s,items,{x=64,y=175,w=1135,gap=125}={}){
 items.forEach(([title,body],i)=>{tx(s,title,x,y+i*gap,w,48,29,C.ink,true);tx(s,body,x,y+i*gap+47,w,76,25,C.mut);});
}
function table(s,values,x,y,w,h,widths,size=24){
 const t=s.tables.add({rows:values.length,columns:values[0].length,left:x,top:y,width:w,height:h,values,columnWidths:widths});
 t.borders.assign({fill:'#DCE5E9',width:1,style:'solid'});
 for(let i=0;i<values.length;i++)for(let j=0;j<values[0].length;j++){
  const c=t.getCell(i,j);c.fill=i===0?C.ink:'#FFFFFF';c.text.style={typeface:F,fontSize:size,color:i===0?'#FFFFFF':C.ink,bold:i===0};
 }
 tableOwners.push(num);return t;
}

// Main talk: 26 slides, about 28 minutes. Four appendices follow.
{
 const s=slide('OSMから、日本全国の\n送電網モデルを作る','ALL-JAPAN-GRID',
 '研究・教育で使える公開モデルを、地図からどう組み上げたかを話す。焦点は規模だけではなく、接続の意味と、その根拠を計算まで追跡する方法にある。変電所内部、解析への接続、今回の再監査までを一本の話としてつなぐ。約40秒。',paper);
 await img(s,'docs/slides/ajg/assets/fig_national_all.png',760,155,455,472);
 tx(s,'地理・変電所内部・計算結果を\n根拠でつなぐ',64,277,665,116,35,C.blue,true);
 tx(s,'重信 颯人\n福井大学',64,478,650,96,25,C.mut);
}
{
 const s=slide('公開モデルで、何を確かめたいのか','問い',
 '再エネを増やす場所、送電線の混雑、発電所停止時の応答。これらは別々の計算に見えるが、同じ接続モデルを共有する。目的は実系統の安全性を断言することではなく、仮定を変えて同じ条件で追試できる研究基盤を作ること。次に、地図だけで足りない情報を整理する。約60秒。',paper+' §1・§6');
 rows(s,[['再エネを増やす','発電の場所と需要の場所を、送電網の上で対応づける'],['送電できる量を調べる','接続・電圧・線路パラメータを与えて潮流を計算する'],['発電所の停止を試す','運転点と動特性の仮定をそろえ、時間応答を比較する']],{gap:126});
 note(s,'共通の出発点は「何と何が、電気的につながるか」',593);
}
{
 const s=slide('地図だけでは、電気の接続は決まらない','1　地理を接続モデルにする',
 '位置や線形はOSMから観測できる。電圧や回線数もタグがある場合に限り取得できる。一方、インピーダンス・負荷・母線内部の接続には欠測がある。このため観測、推定、未確認を混ぜないことが研究の設計条件になる。約60秒。',paper+' Table 1／docs/SUBSLD_METHOD.md');
 table(s,[['情報','公開地理データで得られるもの','追加で必要なもの'],['場所・経路','送電線の線形、設備の座標','端点と実設備の対応'],['設備の属性','電圧・回線数などの記載タグ','欠測の識別と出典による補完'],['電気的な接続','敷地、母線、引込の一部','電圧間の結合、母線・遮断器状態'],['計算条件','公開統計・一部の開示値','線路定数、需要配分、動特性']],64,181,1152,354,[220,455,477],23);
 note(s,'観測値・推定値・未確認を、値ごとに区別する',585);
}
{
 const s=slide('全国データの規模と、3つの地理レイヤ','1　地理を接続モデルにする',
 '全国規模は投稿用PDFの測定版を示す。変電所6,962はOSM featureの数で、後で説明するSubSLDサイト7,239や電圧別母線数とは別の単位。数を混ぜると改善前後の比較そのものが崩れる。約50秒。',paper+' Table 5（現在のbuilt件数とは別）');
 await img(s,'docs/slides/ajg/assets/fig_layer_combined.png',70,158,1140,362);
 [['6,962','変電所 feature'],['40,077','送電線 feature'],['19,138','発電所 feature']].forEach(([v,l],i)=>{tx(s,v,98+i*395,535,355,65,46,C.blue,true);tx(s,l,98+i*395,600,355,37,23,C.mut);});
}
{
 const s=slide('地理データを、計算入力へ変える手順','1　地理を接続モデルにする',
 '各段が次段の入力を決める。まず観測を保存し、線と設備を同定する。変電所では電圧と端子の単位へ分解する。電気定数と運転条件を与えて初めて計算モデルになる。単に線を延ばす処理ではない。約75秒。',paper+' Algorithm 1／SubSLD原稿 §III–IV');
 table(s,[['段階','作るもの','次の段に渡す根拠'],['1　取得・補完','名称・位置・電圧タグ','元のOSM要素と補完元'],['2　端点の同定','線と設備の対応','頂点共有、敷地、引込'],['3　変電所の構造化','電圧階級・母線・端子','接続根拠と推定の区別'],['4　電気モデル化','線路定数、発電・負荷','定数の出典と運転条件'],['5　計算・照合','潮流、UC、動揺の結果','計算版、給電率、残差']],64,171,1152,423,[244,405,503],24);
}
{
 const s=slide('接続の誤りは、計算結果にも現れる','1　地理を接続モデルにする',
 '二重登録すると、1本の設備が並列回線として数えられインピーダンスや容量が変わる。近傍の別母線へ接続すると、存在しない電力経路ができる。だから綺麗な線画や計算収束だけでは、接続が正しいか判断できない。変電所を一つの点として扱う限界につなぐ。約60秒。','docs/reports/osm_grid_pitfalls_methodology_2026-07-10.md');
 rows(s,[['同じ設備を2回数える','並列回線・容量・損失が変わり、別の系統を計算してしまう'],['近くの設備へつなぐ','電圧や母線が違えば、存在しない経路を作ってしまう'],['孤立を隠して計算する','負荷を落としたりslackを増やしたりすると、収束の意味が変わる']],{gap:126});
 note(s,'接続を確かめるには、変電所の内部まで見る必要がある');
}
{
 const s=slide('変電所を「1点」より細かく考える','2　変電所の内部を表す',
 '変電所は単なる点ではない。同じ電圧の回線を受ける母線があり、回線が接続する区画であるベイがあり、電圧を変える変圧器がある。異なる電圧の線が同じ敷地に入っても、変圧器なしで同じ母線にはできない。写真から開閉状態まで分かるとは限らない。約90秒。','papers/figs/嶺南変電所.png／docs/SUBSLD_METHOD.md');
 await img(s,'papers/figs/嶺南変電所.png',64,178,637,426);
 rows(s,[['母線','同じ電圧の回線が接続する場所'],['ベイ・端子','各回線が、どの母線へ入るか'],['変圧器','異なる電圧階級を結ぶ設備']],{x:754,y:182,w:452,gap:136});
}
{
 const s=slide('構内の位置と単線結線図を対応づける','2　変電所の内部を表す',
 '左は新京葉の構内位置、右は同じ観測から生成した単線結線図。線の曲がりや距離を捨てても、どの電圧の端子がどの母線に入るかは残す。色が電圧階級に対応する。図は原稿に収録された測定版で、66/77kVの表記はソース版間に差があるため図自身の表記を読む。約90秒。',subsld+' Fig.2／航空写真：国土地理院');
 await img(s,'papers/subsld/figs/fig_pair_geo.png',72,175,540,400);
 await img(s,'papers/subsld/figs/fig_pair_sld.png',656,175,540,400);
 tx(s,'構内幾何：どこにあるか',90,598,515,40,27,C.blue,true);
 tx(s,'単線結線図：どこにつながるか',656,598,545,40,27,C.blue,true);
}
{
 const s=slide('端子を結ぶ根拠には、強弱がある','2　変電所の内部を表す',
 'SubSLDの中心は根拠の序列。頂点共有を優先し、次に線端が敷地内にあること、その次に近傍の引込を使う。近傍引込は弱い根拠なので破線で示す。根拠が記録されていることと、物理的な接続が正しいことは同義ではない。異電圧や併走線を別途点検する。約75秒。',subsld+' §IV（lead-inしきい値 0.6 km）');
 table(s,[['根拠','見ていること','読み方'],['頂点共有','線と構内設備が同じOSM頂点を共有','直接的な接続証拠'],['敷地内包','線の端点が変電所ポリゴンの内側','敷地への接続証拠'],['近傍引込','線端が敷地に近い','弱い根拠。誤接続の確認対象']],64,180,1152,319,[225,460,467],25);
 note(s,'距離だけで結ばず、電圧の整合と端子の対応も確認する',560);
}
{
 const s=slide('観測された構造と推定を分けて渡す','2　変電所の内部を表す',
 '原稿の証拠閉包という式は、出力された要素から観測根拠へ戻れるという規律を表す。ただし推定母線などは推定として明示される。47,979端子の根拠が存在しても、47,979端子が現場照合済みという意味ではない。欠測も値として渡す。約75秒。',subsld+' Table I／§IV・§VIII');
 tx(s,'観測',66,183,245,57,35,C.blue,true);tx(s,'OSMの母線way・接続端子・記載タグ',335,187,865,55,30);
 tx(s,'推定',66,295,245,57,35,C.blue,true);tx(s,'推定母線や流向には、推定の印を残す',335,299,865,70,30);
 tx(s,'未確認',66,410,245,57,35,C.blue,true);tx(s,'回線数・銘板・対向端子の欠測を保持する',335,414,865,74,30);
 note(s,'「根拠に戻れる」と「実系統と一致する」は、別の確認事項',583);
}
{
 const s=slide('欠測を測ると、次に調べる場所が決まる','2　変電所の内部を表す',
 'SubSLD原稿の評価時点の値を示す。母線wayがあるのはサイトの14.2%、流向を決められない線グループは39.4%。推定した流向は実潮流ではない。14所の判読では約64%が修正可能なOSM欠測とされたが、この小標本を全国へ外挿しない。全国の7,239サイト生成と、現物確認の範囲を分けて伝える。約70秒。',subsld+' §VII（後日の構造DB再生成とは測定時点が異なる）');
 tx(s,'14.2%',70,193,535,110,76,C.blue,true);tx(s,'母線wayが記載されたサイトの割合',73,319,533,86,28);
 tx(s,'39.4%',692,193,507,110,76,C.red,true);tx(s,'流向推定を棄権した線グループの割合',695,319,507,86,28);
 tx(s,'母線の位置、引込、対向端子を確認する作業リストへ',70,493,1138,79,33,C.ink,true);
 tx(s,'全サイト数 7,239 ／ 流向の母数 18,851線グループ（原稿評価版）',72,599,1115,40,22,C.mut);
}
{
 const s=slide('二重登録を直すと、損失が増えた','3　計算結果を確かめる',
 '歴史的な転換点を一つだけ示す。地域抽出の重なりで同じ設備が二重に入り、断片や並列回線として見えていた。統合すると成分数が減り、東日本のAC損失は5.7%増えた。損失が増えた理由は性能悪化ではなく、誤った並列経路を取り除いたこと。この値はv1.6の比較実験。約90秒。','story原版 S13／CHANGELOG v1.6／2026-07-10 方法論レポート');
 table(s,[['v1.6での比較','訂正前','訂正後'],['西日本の連結成分','2,531','544'],['西日本の枝数','9,793','8,353']],66,182,1145,270,[565,290,290],30);
 tx(s,'東日本のAC損失  +5.7%',73,502,1110,67,44,C.red,true);
 tx(s,'二重計上によるインピーダンスの過小評価を訂正した結果',73,586,1120,58,27,C.mut);
}
{
 const s=slide('収束だけで、正しさを判定しない','3　計算結果を確かめる',
 '収束したか、元の需要が残っているか、電圧と電力収支が妥当かは別の確認。served_fracは解前需要に対する給電割合で、95%の閾値はこのプロジェクトのガードである。slackは需給差を受け持つ基準電源で、極端な値は入力や配分の問題を示す場合がある。約75秒。','docs/MODEL_INTERVENTIONS.md／docs/YBUS_SOLVABILITY.md');
 rows(s,[['数値が収束したか','残差とソルバ状態を保存する。DC代替とAC解を区別する'],['計算対象が残っているか','解前需要に対する給電率を確認する（既存ガード：95%以上）'],['電気的に妥当か','電圧・負荷率・slack負担を、計算条件と一緒に確認する']],{gap:126});
 note(s,'接続を変えたら、同じ需要・発電条件で再計算する');
}
{
 const s=slide('標準形式を、独立した検証に使う','3　計算結果を確かめる',
 'CIM/CGMESはモデル交換の標準。モデルを書き出し、独立実装cim2ppで読み、潮流を再計算する。この往復は単位や参照関係のバグを発見できるが、入力自体の実在性を保証するわけではない。地域別10件の往復検証と、4同期島を統合したAC成立は別の主張。約60秒。','story原版 S10・S36／dist/cim_level2/cim_level2_index.json');
 rows(s,[['モデルの意味を残して出力する','母線・端子・線・変圧器と、推定の注記をCIM/CGMESへ'],['別の実装で読み戻す','pandapower cim2ppで解釈し、同じ計算条件を再現する'],['往復前後を比較する','過去の検証：全10地域、電圧差 10⁻⁴ pu 未満']],{gap:124});
 note(s,'形式と数値の整合を検証する。現場照合は別に行う');
}
{
 const s=slide('投稿用PDFのUC結果','3　計算結果を確かめる',
 'UCは発電機の起動停止計画。投稿用PDF Table6は783機・24時間・9連系線の実験。この表の単一起動コストと3状態起動コストは目的関数が違うため、費用差を同一問題の改善率として語らない。旧storyの757機や現在のTeXの646機は別版。約80秒。',paper+' Table 6（図6の機数表記とは不一致が残る）');
 tx(s,'783機 × 24時間',71,174,1120,80,50,C.blue,true);
 table(s,[['定式化','目的関数値 [億円/日]','求解時間 [s]'],['単一起動コスト','76.51','9'],['3状態起動コスト','84.00','39']],65,288,1150,248,[490,380,280],28);
 note(s,'異なる起動コストモデル。費用の単純な優劣比較はしない',582);
}
{
 const s=slide('起動計画が、潮流と動揺の条件を決める','3　計算結果を確かめる',
 'UCで稼働機と出力を決めると、潮流計算の注入電力が決まる。潮流で電圧と相差角を解き、動揺計算の初期値にする。事故時には出力余力や慣性の仮定が応答を決める。蓄電池を含む需給調整は、各設備のモデルと制約条件を明示して扱う。約70秒。',paper+' §3–5／docs/reports/how_to_read_dynamics_2026-08-17.md');
 table(s,[['計算','主な入力','次へ渡すもの'],['起動停止計画（UC）','需要、電源制約、連系線容量','稼働機と時間別の出力'],['交流潮流（AC PF）','接続、線路定数、発電・需要','電圧と相差角、線路潮流'],['動揺・周波数応答','運転点、慣性・制御定数、脱落条件','周波数と相差角の時間変化']],65,193,1150,330,[310,420,420],25);
 note(s,'同じモデル版と運転条件を引き継ぐことが重要',583);
}
{
 const s=slide('西日本の発散を、場所から診断した','3　計算結果を確かめる',
 'これは2026年8月30日の診断実験。ニュートン反復を一回ずつ止め、どの地点から電圧が不自然になるか観察した。周波数の地域帰属や下流への負荷配分を点検する入口になった。収束するようにパラメータを動かすのではなく、何が不整合かを確認する。約75秒。','2026-08-30診断版：assets/west_ac_onset.gif／介入#37–39',true);
 await img(s,'docs/slides/ajg/assets/west_ac_onset.gif',132,170,1016,468);
}
{
 const s=slide('ACが収束しても、低電圧は残る','3　計算結果を確かめる',
 '8月30日の西日本AC図。給電が成立しても、低電圧地点やslack負担が残っている。原図には江田島0.67pu、大阪三国0.73puの注記がある。この図は過去の診断断面であり、現時点の運用状態を示さない。接続の正しさ、配分、変圧器の仮定を引き続き調べる必要がある。約60秒。','2026-08-30診断版：fig_west_ac_map.png／story原版 S35');
 await img(s,'docs/slides/ajg/assets/fig_west_ac_map.png',65,172,804,450);
 tx(s,'低電圧地点\nslackの負担\n給電対象の残り方',925,241,286,196,30,C.red,true);
 tx(s,'収束後に見るべき\n確認項目',925,488,286,105,27,C.mut);
}
{
 const s=slide('1つの事故条件で、応答を追う','3　計算結果を確かめる',
 '東日本のピーク断面で3発電所を同時脱落させるモデル実験。10,618MWはプラント単位の大擾乱で、実事故再現やユニットN-1の検証ではない。慣性や制御には典型値を用いる。図の負荷消灯位置は集約UFLS量の可視化用配置で、実際に停電する地点の予測ではない。この同じ事故条件の周波数曲線を次で読む。約70秒。','2026-08-30モデル実験：east_incident.gif／AGC-N 東N-3',true);
 await img(s,'docs/slides/ajg/assets/east_incident.gif',196,162,889,442);
 tx(s,'3プラント同時脱落 10,618 MW。消灯地点は集約遮断量の表示用配置',66,611,1144,43,23,'#FFFFFF');
}
{
 const s=slide('急低下と回復を、同じ時間軸で読む','3　計算結果を確かめる',
 `直前と同じ東N-3モデル実験。平均は稼働機の慣性で重み付けしたCOI周波数。底は${freq.nadir_hz.toFixed(2)}Hz、900秒付近でも${freq.end_hz.toFixed(2)}Hzで50Hzに戻りきっていない。曲線の形だけで特定の制御機器の寄与を断定しない。曲線は保存された時系列に基づく。図の時刻はシミュレーション時刻で事故はt=1秒。約80秒。`,freq.source+'（元storyと同じ保存時系列）');
 await img(s,'docs/slides/ajg/revised/assets/east_frequency_explained.gif',73,173,1135,423);
 note(s,`最低 ${freq.nadir_hz.toFixed(2)} Hz ／ 約15分後 ${freq.end_hz.toFixed(2)} Hz。完全復帰は未確認`,607);
}
{
 const s=slide('現在の接続状態を数え直す','4　今回の再監査と、次の改善',
 'ここからは2026年9月12日に読み込んだbuilt/all.jsonの監査。保存済み統計やmainフラグを信用せず、所属同期島ごとに既存枝で成分を再計算した。525は地理座標グラフの断片で、525箇所の実系統故障という意味ではない。変電所も座標キー単位で、サイト数や電気母線数とは別。保存統計のノード17,841/枝19,529は実体17,738/19,944と不一致。約80秒。','2026-09-12監査：入力SHA256 '+audit.source_sha256.slice(0,16)+'…');
 table(s,[['同期島','断片成分','断片の変電所座標'],...Object.entries(audit.islands).map(([k,v])=>[({hokkaido:'北海道',east:'東日本',west:'西日本',okinawa:'沖縄'})[k],String(v.fragment_components),String(v.fragment_substation_keys)])],66,181,1150,334,[454,310,386],27);
 note(s,'計525成分・313変電所座標。候補を現場の欠落と断定しない',570);
 tx(s,'定義：所属島内の座標キー、既存枝のみ。追加stitch/tieなし',68,618,1125,32,20,C.mut);
}
{
 const s=slide('秩父周辺に残る、12ノードの断片','4　今回の再監査と、次の改善',
 '断片の秩父変電所と本系統の同名ノードは46.2m、横瀬は78.8m。断片のノードはchubu由来IDを持つがregionはtokyoに変わっている。地域再帰属後の重複同定漏れが仮説になる。ただし同名・近接だけでは同一設備と確定できず、母線・OSM同一性を確認する。既存の回収枝もこの成分内にあり、保存mainがTrueでも自島の最大成分ではない。約100秒。','2026-09-12：connections.json／chichibu_review.gif（既存データのみ）');
 await img(s,'docs/slides/ajg/revised/assets/chichibu_review.gif',65,170,1148,430);
 tx(s,'同一設備の重複か、別の母線か。OSM要素と引込を照合する',70,613,1138,43,26,C.blue,true);
}
{
 const s=slide('電圧不明が、異電圧の経路を通していた','4　今回の再監査と、次の改善',
 '今回コードから見つけた再現可能な不具合。始点電圧が不明だと各wayを始点だけと比較するチェックが素通りし、途中で66kVから154kVへ乗り換えられた。変圧器の根拠を持たない線路連鎖なので不正な候補となる。全経路の既知電圧を保持するガードへ修正した。既存正典の枝は自動変更していない。約100秒。','scripts/hunt_fragment_{osm_chains,third_wave}.py／回帰テスト');
 table(s,[['通過順','電圧の情報','旧判定'],['始点','不明','電圧比較を通過'],['way 1','66 kV','始点が不明なので通過'],['way 2・到達先','154 kV','始点が不明なので通過']],66,177,1150,328,[255,415,480],28);
 note(s,'修正：途中で得た電圧証拠を、経路全体で照合する',559);
 tx(s,'66 kVと154 kVをつなぐには、変圧器を含む別の根拠が必要',71,614,1134,39,24,C.mut);
}
{
 const s=slide('本四連系線の端点定義にも不一致','4　今回の再監査と、次の改善',
 '現行ic_008は東山口と讃岐を結ぶ195.7kmの直線。四国電力の公表系統図と設備資料が示す本四連系線の端点は東岡山と讃岐。グラフ上でつながることは、端点が正しいことを保証しない。緑の破線は端点比較用で実際の線形ではない。builtには合成tieが残り、connectivity.py/national.pyにも生成経路がある。計算経路ごとの利用有無と二重計上を確認して訂正する。約100秒。','現行ic_008／デンロ技報 No.19（電源開発・日本電炉）／四国電力送配電 系統図');
 await img(s,'docs/slides/ajg/revised/assets/honshi_endpoint_audit.png',67,177,1146,428);
 note(s,'公開資料の端点は「東岡山・讃岐」。線形と利用経路も再確認',611);
 s.speakerNotes.textFrame.setText(noteRows.at(-1).notes+'\n\n一次資料：https://www.yonden.co.jp/nw/assets/line_access/mapping1.pdf\nhttps://www.enecho.meti.go.jp/category/electricity_and_gas/electricity_measures/005/pdf/08shikoku2025.pdf\n本四連系線の施工者による設備記述：https://denro.co.jp/jp/blog/2022/01/19/denrotec19-2/\n現行定義：data/reference/interconnections.yaml ic_008');
}
{
 const s=slide('改善は、根拠と再計算を1組にする','4　今回の再監査と、次の改善',
 '候補をまとめて接続すると、改善に見える誤接続が混ざり原因を追えなくなる。まず元要素と端子を確認し、複製モデルで一件ずつ変更する。周波数跨ぎや異電圧短絡が増えていないか、同じ運転点で給電率、残差、slack、電圧がどう変わるかを比較する。今回修正したのは検出・回収コードのガードで、正典の設備接続は未変更。約80秒。','docs/MODEL_INTERVENTIONS.md／2026-09-12接続監査');
 rows(s,[['1　設備と接続先を確定する','OSM要素、電圧、母線、引込、公式開示を照合する'],['2　複製モデルで1件ずつ試す','同定・端点修正・変圧器追加を区別し、根拠を台帳に残す'],['3　同じ条件で前後を比べる','成分、給電率、slack、電圧、残差を比較し、退行なら戻す']],{gap:126});
}
{
 const s=slide('線の根拠を、計算結果まで追跡する','結論',
 '結論を三点に絞る。公開地理から研究用の全国モデルは構築できる。変電所内部を分け、観測と推定を分けることで接続の意味を説明できる。そして計算結果を根拠と一緒に検証できる。今回の追加監査は完成宣言ではなく、再現できる改善対象を具体化した。質問は接続・変電所・解析のどこからでも受ける。約45秒。','All-Japan-Grid／研究・教育用のモデル');
 rows(s,[['全国の地理を、解析に接続できた','送電線・設備・運転条件を、再現可能な手順で組み上げる'],['変電所の内部と、不明点を表せる','電圧階級・母線・端子を分け、観測と推定を明示する'],['接続の改善を、根拠から検証できる','断片・誤帰属・異電圧経路・端点定義を継続して監査する']],{gap:126});
 tx(s,'github.com/lutelute/All-Japan-Grid',68,609,1130,38,24,C.blue,true);
}

// Appendices: scope and sources, kept apart from the main narrative.
{
 const s=slide('数値の版と、数える対象','補足 A',
 '数の不一致を隠さず、比較の単位を示す。投稿用PDFの図6には635機、Table6には783機と残るため、スライドは表6の明示条件を引用。646機版TeXも別の原稿版として扱う。比較に使う条件はTable 6にそろえる。',paper+'／papers/ieej.tex／原story／SubSLD原稿');
 table(s,[['数値','出典・版','数えているもの'],['6,962','投稿用PDF Table 5','変電所 feature'],['7,239','SubSLD v1.8原稿','構造抽出サイト'],['783機','投稿用PDF Table 6','UCの計算規模'],['757機','原storyの開発実験','別版のUC規模'],['646機','現在のieej.tex Table 6','OCCTO参照モデルのUC']],65,180,1150,425,[220,480,450],25);
}
{
 const s=slide('検証が確かめることと、残る限界','補足 B',
 'rho0.721は実測潮流への代理指標で、AC潮流値そのものの一致率ではない。関西37/38も照合が成立した標本に限定される。CGMES往復は同一性の確認。これらを全国の精度の一数字にまとめない。','story原版 S36／docs/reports/international_benchmark_2026-06-27.md');
 table(s,[['検証','過去の結果','結論の範囲'],['東京の順位相関','代理指標 ρ = 0.721','AC潮流値そのものの一致ではない'],['関西の電圧階級','照合38本中37本一致','照合可能標本に限定'],['CGMES往復','全10地域・電圧差10⁻⁴ pu未満','独立実装での数値同一性'],['今回の接続監査','525断片・132近接候補ペア','候補列挙。現場接続の確定ではない']],65,184,1150,378,[310,345,495],24);
}
{
 const s=slide('同じ座標でも、同じ電気母線ではない','補足 C',
 '今回の監査は地理座標グラフであり電気母線グラフではない。現行builtの自己ループ2,181件の大半2,172件はintra-substation stubとして明示された構内表現。これを接続ミスとして一括削除してはいけない。端点には座標だけでなく電圧と母線IDを持たせることが、将来の監査・表示の改善になる。','built/all.json／scripts/audit_story_connections.py');
 tx(s,'地図上では1つの敷地',68,191,485,49,29,C.ink,true);
 tx(s,'電気モデルでは電圧を分ける',632,191,584,49,29,C.ink,true);
 const bar=(x,y,w,h,color)=>s.shapes.add({geometry:'rect',position:{left:x,top:y,width:w,height:h},fill:color,line:{fill:'none',width:0}});
 const circle=(x,y,size,color,filled=false)=>s.shapes.add({geometry:'ellipse',position:{left:x,top:y,width:size,height:size},fill:filled?color:'none',line:{fill:color,width:3}});
 circle(249,350,50,C.blue,true);
 tx(s,'変電所の代表座標',107,426,367,47,27,C.mut);
 tx(s,'場所の集約点',172,489,281,44,25,C.mut);
 bar(677,301,470,5,C.blue);bar(677,520,470,5,C.red);
 tx(s,'500 kV 母線',683,250,392,46,28,C.blue,true);
 tx(s,'66 kV 母線',683,534,392,46,28,C.red,true);
 bar(897,306,3,60,C.ink);bar(897,446,3,74,C.ink);
 circle(870,365,56,C.ink);circle(870,393,56,C.ink);
 tx(s,'変圧器',963,385,203,47,28,C.ink,true);
 tx(s,'概念図：実設備の構成・開閉状態を示すものではない',68,607,1145,45,23,C.mut);
}
{
 const s=slide('参照資料と、再現方法','補足 D',
 '発表の数値は資料ごとの版を残した。投稿用PDF、SubSLD原稿、開発実験の保存時系列、今回の監査を区別して追跡できる。スライドノートには各ページの説明と出典がある。', '2026-09-12 story改善版');
 rows(s,[['投稿原稿','papers/ieej_submit.pdf ／ papers/ieej.tex（別版）'],['変電所の構造化','papers/subsld/subsld.tex ／ docs/SUBSLD_METHOD.md'],['接続監査の再現','python3 scripts/audit_story_connections.py'],['今回の図・GIFの再現','python3 scripts/gen_story_review_figures.py']],{gap:109});
}

await fs.writeFile(path.join(work,'TALK_NOTES.md'),'# All-Japan-Grid 発表ノート\n\n本編26枚、補足4枚。目安28〜30分。\n\n'+noteRows.map(r=>`## ${r.n}. ${r.title.replaceAll('\n',' ')}\n\n${r.notes}\n\n出典：${r.source}`).join('\n\n')+'\n');
const candidate=path.join(build,'candidate.pptx');await (await PresentationFile.exportPptx(p)).save(candidate);
const finalPath=path.join(work,'output',`AllJapanGrid_story_revised_2026-09-12${process.env.REVISION?'_'+process.env.REVISION:''}.pptx`);
const result=await finalizePresentation({workspaceDir:work,candidatePath:candidate,finalPath,
 pythonExecutable:path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3.12'),
 integrityValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_package_integrity.py'),
 layoutValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_layout_geometry.py'),
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit',...tableOwners.flatMap(n=>['--require-native-table-slide',String(n)])],
 explicitTotalSlideCount:30,requiredNativeTableOwnerSlides:tableOwners,
 fontPolicy:{basis:'design',families:[F]},verifyArtifactToolImport:true,
 receiptPath:path.join(build,`validation${process.env.REVISION?'_'+process.env.REVISION:''}.json`)});
console.log(JSON.stringify({result,finalPath,slides:num},null,2));
