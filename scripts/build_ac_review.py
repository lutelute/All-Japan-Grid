#!/usr/bin/env python3
"""Render the AC evidence as offline, inspectable Before/After HTML."""
from pathlib import Path
import html
import json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'docs/reports/codex_ac_diagnosis_2026-09-15'


def build():
    result = json.loads((OUT/'results.json').read_text())
    labels = {'before':'Before：元モデル', 'split_only':'対照：幹線の分割のみ',
              'branch_restored':'After 1：宮城中央支線を復元',
              'branch_and_identity_load':'After 2：同一設備の需要重みも補正'}
    rows = []
    for key, label in labels.items():
        v = result['variants'][key]; q = v['unbounded_q_diagnostic']
        rows.append(f'<tr><th>{label}</th><td>{v["buses"]:,}</td><td>{v["lines"]:,}</td>'
                    f'<td>{q["served_mw"]:,.0f}</td><td>{q["vm_min"]:.3f}</td>'
                    f'<td>{q["osato_line_1129"]["loading_percent"]:.1f}%</td>'
                    f'<td>{q["loss_mw"]:,.1f}</td><td>{q["q_violations"]:,}</td><td class="bad">未収束</td></tr>')
    evidence = []
    for name in sorted((OUT/'exploration').glob('*.json')):
        evidence.append(f'<details><summary>{name.name}</summary><pre>{html.escape(name.read_text())}</pre></details>')
    files = ['src/powerflow/ac_validation.py','scripts/review_ac_solvability.py',
             'scripts/build_ac_review.py','tests/test_ac_validation.py','docs/AC_DIAGNOSIS_TOOL.md','docs/slides/ajg/build_ac_diagnosis.mjs']
    registration = '<details><summary>既存の索引・属性ファイルのBefore / After</summary><pre>'+html.escape((OUT/'registration.diff').read_text())+'</pre></details>'
    code = registration + ''.join(f'<details><summary>{p} — Before：未実装 → After：追加</summary><pre>{html.escape((ROOT/p).read_text())}</pre></details>' for p in files)
    page = TEMPLATE.replace('@@ROWS@@',''.join(rows)).replace('@@EXPLORATION@@',''.join(evidence)).replace('@@CODE@@',code)
    page = page.replace('@@DATA@@', json.dumps(result,ensure_ascii=False).replace('</','<\\/'))
    (OUT/'index.html').write_text(page)


TEMPLATE = r'''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AC・Ybus診断 — 接続と需要の Before / After</title>
<style>
:root{--ink:#183042;--blue:#176bc3;--teal:#087e7f;--red:#ba3b32;--paper:#f4f7fa}*{box-sizing:border-box}body{margin:0;color:var(--ink);background:var(--paper);font:16px/1.8 -apple-system,BlinkMacSystemFont,'Hiragino Sans',sans-serif}main{max-width:1220px;margin:auto;padding:36px 28px 70px}h1{font-size:clamp(30px,4vw,52px);line-height:1.4;letter-spacing:-.035em;margin:18px 0}h2{font-size:27px;line-height:1.5}h3{font-size:20px;margin:12px 0}p{margin:10px 0 18px}a{color:var(--blue)}nav{display:flex;gap:18px;flex-wrap:wrap;font-size:14px;border-bottom:1px solid #d0dae3;padding:18px 0}.eyebrow{font-weight:750;color:var(--teal);font-size:14px;letter-spacing:.1em}.status{background:#ffebe6;border-left:5px solid var(--red);padding:18px 22px;margin:24px 0}.status strong{display:block;font-size:20px}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}.card,section{background:white;border:1px solid #d9e2e8;border-radius:14px;padding:24px}.card b.big{display:block;font-size:32px;color:var(--teal);margin:6px 0}.small,figcaption{font-size:13px;color:#536777}.small strong{color:var(--red)}section{margin-top:28px}section>h2:first-child{margin-top:0}.two{display:grid;grid-template-columns:1fr 1fr;gap:20px}.note{background:#edf5fc;padding:14px 18px;border-radius:7px}.bad{color:var(--red);font-weight:700}.good{color:var(--teal);font-weight:700}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px;white-space:nowrap}td,th{border-bottom:1px solid #dce4eb;padding:12px 10px;text-align:right}th:first-child{text-align:left}thead{background:#f0f5f9}img{display:block;width:100%;border-radius:8px}figure{margin:0}figcaption{margin-top:8px}button{padding:9px 16px;background:#fff;border:1px solid #6b849a;color:var(--ink);border-radius:6px;cursor:pointer;font-size:14px}button:focus-visible,input:focus-visible{outline:3px solid #db9d00}button.active{background:var(--ink);color:white}.controls{display:flex;gap:10px;margin:12px 0}details{border-top:1px solid #dce4eb;padding:12px 0}summary{cursor:pointer;font-weight:650;overflow-wrap:anywhere}pre{background:#101f2d;color:#e2edf6;padding:18px;max-height:550px;overflow:auto;font:13px/1.6 ui-monospace,monospace;white-space:pre-wrap;overflow-wrap:anywhere}code{background:#eaf0f5;padding:2px 5px}svg text{font-family:inherit}svg{max-width:100%;height:auto}.flow{background:#f5f8fa;border-radius:8px;padding:12px}.flow strong{display:block}input[type=range]{width:100%}.statline{font-size:18px;min-height:110px}.pill{display:inline-block;background:#f1f5f8;border:1px solid #dde6eb;padding:3px 12px;border-radius:20px;font-size:13px}.checklist li{margin-bottom:12px}.footer{margin-top:25px;font-size:13px;color:#536777}@media(max-width:820px){main{padding:22px 15px}.two,.cards{grid-template-columns:1fr}section{padding:20px}h2{font-size:23px}}@media print{body{background:white}section{break-inside:avoid}.controls,nav{display:none}details pre{max-height:none}}
</style><main>
<div class="eyebrow">ALL JAPAN GRID · CODEX REVIEW · 2026.09.15</div>
<h1>不収束を、直せる原因に分ける。</h1>
<p>線を残して接続を復元する。同一設備の需要重みを見直す。YbusとACの結果から、次に調べる場所を絞る。</p>
<div class="status"><strong>目標55,250 MWでの、発電機Q制約付きACは未収束。</strong>接続と需要配分の改善を確認した段階です。下の改善値はQ制約を外した診断値であり、運転可能性や実測誤差の改善率を表しません。</div>
<nav><a href="#mechanism">なぜ変わるか</a><a href="#photo">航空写真と一次資料</a><a href="#compare">Before / After</a><a href="#ybus">Ybus判定</a><a href="#ramp">ACの合格条件</a><a href="#trials">試行錯誤</a><a href="#handoff">Claudeへの引継ぎ</a></nav>
<div class="cards" style="margin-top:24px">
<div class="card"><span class="pill">宮城中央支線の復元</span><b class="big">1,007 → 198%</b><p>大郷66 kV側の問題線路の負荷率。女川からの発電を500 kV側へ流せる経路が戻る。</p></div>
<div class="card"><span class="pill">同じ設備の重みを一回分に</span><b class="big">0.834 → 0.935 pu</b><p>支線復元＋70組の需要配分重み補正後の最低電圧。地域のP/Q合計は維持する。</p></div>
<div class="card"><span class="pill">全設備・全枝を保持</span><b class="big">55,250 MW</b><p>目標需要は変更しない。追加は幹線分岐点と元データにある引込経路。線路の間引きはしない。</p></div></div>
<p class="small">対象：東日本の推定運転点。基準母線220個のうち208は既存の仮想補給。全国の実測運用を再現したという意味ではありません。</p>
<section id="slides"><h2>補足PowerPoint：今回の診断を6枚で確認</h2><p><a href="AllJapanGrid_AC_Ybus_review_2026-09-15.pptx">AC・Ybus診断のPowerPointを開く</a></p><div class="two"><figure><img loading="lazy" src="figures/slide-1.png" alt="AC・Ybus診断スライド 1"><figcaption>1 / 6</figcaption></figure><figure><img loading="lazy" src="figures/slide-2.png" alt="AC・Ybus診断スライド 2"><figcaption>2 / 6</figcaption></figure><figure><img loading="lazy" src="figures/slide-3.png" alt="AC・Ybus診断スライド 3"><figcaption>3 / 6</figcaption></figure><figure><img loading="lazy" src="figures/slide-4.png" alt="AC・Ybus診断スライド 4"><figcaption>4 / 6</figcaption></figure><figure><img loading="lazy" src="figures/slide-5.png" alt="AC・Ybus診断スライド 5"><figcaption>5 / 6</figcaption></figure><figure><img loading="lazy" src="figures/slide-6.png" alt="AC・Ybus診断スライド 6"><figcaption>6 / 6</figcaption></figure></div></section><section id="mechanism"><h2>01 / 「切るか繋ぐか」の前に、通るべき経路を戻す。</h2>
<div class="two"><div><h3>Before：上位の接続が欠けていた</h3><div class="flow"><strong>女川 → 松島幹線275 kV → 大郷</strong>宮城中央500 kV母線には幹線への接続がない。女川側の発電が、推定275/66 kV変圧器と66 kV線を通って主系統へ出る。</div><p>5母線の高電圧側に約628 MWの発電があるのに、接続上は100 MVAと推定された変圧器が出口になっていた。大郷の66 kV側が大需要だったわけではない。</p></div>
<div><h3>After：青葉幹線の分岐と引込を復元</h3><div class="flow"><strong>女川 → 松島幹線 → 宮城中央 → 青葉幹線500 kV</strong>幹線の元のポリライン上に分岐点を置き、宮城中央支線2回線と構内引込を戻す。</div><p>大郷の設備と枝を残したまま潮流が分担される。まだ大郷の推定変圧器の妥当性や局所過負荷は未解決だが、実在の上位経路を回路に戻す効果を分離できた。</p></div></div>
<svg viewBox="0 0 1100 265" role="img" aria-label="支線復元前後の模式図。青葉幹線は残し、宮城中央への分岐だけを追加する。"><defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0 0L6 3L0 6" fill="#087e7f"/></marker></defs>
<rect x="10" y="10" width="525" height="240" rx="12" fill="#f2f5f8"/><rect x="560" y="10" width="525" height="240" rx="12" fill="#ecf8f5"/>
<g font-size="17" fill="#183042"><text x="30" y="40">Before</text><text x="580" y="40">After：元の経路を保持して分岐</text><text x="32" y="83">西仙台</text><text x="424" y="83">宮城</text><text x="582" y="83">西仙台</text><text x="974" y="83">宮城</text>
<path d="M110 77H415M660 77H965" stroke="#176bc3" stroke-width="5"/><path d="M815 77V132" stroke="#087e7f" stroke-width="5" marker-end="url(#arrow)"/>
<text x="193" y="140">宮城中央500</text><text x="743" y="157">宮城中央500</text><text x="240" y="110" fill="#ba3b32">× 接続なし</text><text x="838" y="115" fill="#087e7f">支線2回線</text>
<path d="M270 150V186M820 166V186" stroke="#7f8ea0" stroke-width="3"/><text x="65" y="217">女川 → 松島幹線275 → 大郷 → 66側</text><text x="615" y="217">女川 → 松島幹線275 → 宮城中央</text></g></svg>
<p class="small">模式図であり地理座標ではありません。青＝既存500 kV幹線、緑＝復元した分岐。追加線のR/X/Cは既存500 kV既定値を継承し、実測定数は未取得。</p></section>
<section id="photo"><h2>02 / 背景地図は、実際に見て照合する。</h2>
<figure><div class="controls"><button class="active" data-site="miyagi" data-mode="overlay">元データと重ねる</button><button data-site="miyagi" data-mode="aerial">写真のみ</button></div><img id="miyagi-photo" src="figures/miyagi_overlay.png" alt="宮城中央の航空写真。青葉幹線の分岐支持物から構内へ向かう線形と、変電所設備外形を重ねたもの。"><figcaption>宮城中央：地理院タイル／地点の撮影期間2023年10月～11月。青葉幹線の分岐点と構内引込が対応。写真だけでは回線定数・遮断器状態・内部母線接続を確定しない。</figcaption></figure>
<div class="note" style="margin-top:18px"><strong>元データ＋独立した公開資料</strong><br>OSM way/201966024＝青葉幹線、way/785319810＝宮城中央支線、way/250462658・785319809＝構内引込。<a href="https://nw.tohoku-epco.co.jp/consignment/system/announcement/data/sys_capa_kikan01_line_202607_02.csv">東北電力ネットワークの公開CSV</a>の0005行でも「宮城中央支線、500 kV、2回線、青葉幹線分岐→宮城中央変電所」を確認。<a href="sources/official_branch_row.json">保存した行とSHA</a>。</div>
<div class="two" style="margin-top:24px"><div><h3>安良里：設備の数とモデル点の数を分ける</h3><p>東京側と中部側の点は同じOSM way/409537787を参照する。片方のモデル点は設備外にずれていた。点を消して短絡させる操作はせず、同一設備の合成需要の重みを一回分に補正する。</p><p><b>Before：</b>約23.02 MW × 2点。<br><b>After：</b>約23.02 MWを2点に分担し、地域合計を保つため地域全体で再正規化する。</p><p class="small">70組は同じ元設備・地域・電圧で照合。別電圧の母線は混ぜない。実測需要はこの補正の対象外。最終値は <a href="results.json">需要配分台帳</a> を参照。</p></div>
<figure><div class="controls"><button class="active" data-site="izu" data-mode="overlay">モデル点と重ねる</button><button data-site="izu" data-mode="aerial">写真のみ</button></div><img id="izu-photo" src="figures/izu_overlay.png" alt="安良里の航空写真上に、同じOSM設備を参照する東京・中部のモデル点を表示。"><figcaption>安良里：地理院タイル／撮影期間2020年8月～12月。黄＝元設備の外形。取得日と撮影日は異なる。<a href="sources/photos.json">写真・撮影期間の出典一覧</a>。</figcaption></figure></div>
<details><summary>大郷：推定275/66 kV変圧器も要確認</summary><img src="figures/osato_overlay.png" alt="大郷の設備外形とモデルの275・66kV端点を航空写真上で比較"><p>モデル点が設備外形からずれる。写真だけで変圧器が存在しないとは判断しない。変圧器を保留した別試験も未収束で、最終比較では既存の変圧器を保持した。</p></details></section>
<section id="compare"><h2>03 / どの変更が、どれだけ効いたか。</h2><p>各変更を分けて比較する。特に幹線の分割だけの対照を置き、支線追加の効果と区別する。</p>
<div class="scroll"><table><thead><tr><th>試験</th><th>母線</th><th>線路</th><th>需要MW</th><th>最低電圧pu</th><th>大郷線路</th><th>損失MW</th><th>Q違反行数</th><th>Q制約付きAC</th></tr></thead><tbody>@@ROWS@@</tbody></table></div>
<p class="small"><strong>電圧・負荷率・損失・Q違反数は、Q制約を外したAC診断値。</strong>すべての発電機P・Q上下限、変圧器、基準母線は保持。After 2は需要・推定補償の場所を変更し、地域P/Q合計を保持する。Q違反が残るので、改善値だけで合格にはしない。</p>
<p>幹線の分割だけでは、元の線路のDC潮流差は約1.36×10⁻⁹ MW、AC損失差は約0.0014 MW。支線復元による約104.5 MWの診断損失低下とは分離できた。ACはπ型線路の充電容量の配置が変わるため、分割を完全同値とは呼ばない。</p></section>
<section id="ybus"><h2>04 / Ybusから分かること、分からないこと。</h2><div class="two"><div><h3>基準母線を除いて、数値感度を調べる</h3><p>元モデルのYbusは6,253×6,253、非零要素20,523。220個の基準母線を除いた行列の1ノルム条件数推定は約5.27×10⁷。孤立した基準母線2個の対角ゼロは、今回のAC不収束の根拠にはならない。</p><p>短い500 kV多回線区間は大きいアドミタンスを作る。ただし、実在する短い区間を数値だけで削除しない。</p></div>
<div><h3>次にAC Jacobianで、弱い場所を絞る</h3><p>Q制約適用後にNewtonが失敗したとき、注入量を補間して最後の収束点へ戻る。その点の電圧感度を調べると、Beforeは大郷、修正後は安良里を含む伊豆側が強く反応する。</p><p>修正後のYbus条件数推定は約6.12×10⁷と、むしろ増える。<b>「条件数を下げればモデル精度が上がる」という採点にはしない。</b></p></div></div>
<div class="note">判定の順番：<b>接続と電圧階級 → Ybusの構造・数値感度 → AC不整合 → Q制約 → 電圧・過負荷 → 実測照合</b>。条件数や反復失敗だけでは、AC解の不存在を証明できない。</div>
<details><summary>Ybus・Jacobian・Q制約遷移の数値を表示</summary><pre id="ybus-json"></pre></details></section>
<section id="ramp"><h2>05 / 「ACが回る」を、3段階で確認する。</h2><p>需要・発電・推定補償を同じ比率で変えた診断。線路・変圧器・発電機Q上下限は維持する。目標の100%は55,250 MW（地域ピーク設定×0.85）。</p>
<label for="ramp-slider"><b>試験した運転点を選ぶ</b></label><input id="ramp-slider" type="range" min="0" max="6" value="6" step="1"><div class="statline" id="ramp-result" aria-live="polite"></div>
<div class="cards"><div class="card"><h3>① 方程式</h3><p>全稼働母線の電圧が有限。需要を保持し、最終不整合が1e-4 MVA以内。</p></div><div class="card"><h3>② Q上下限</h3><p>結果の発電機Qを個別に再確認。制約を外した解を成功に数えない。</p></div><div class="card"><h3>③ 運転範囲</h3><p>0.9–1.1 pu・負荷率100%で仮のスクリーニング。①②が通っても③は別に判定。</p></div></div>
<p class="small">80%では①②を通過するが、最低電圧0.686 pu、231線路・103変圧器に過負荷。5%ではこのスクリーニングを通過するが、通常運転の達成とはしない。全点とも既存の仮想補給を含む。0.9–1.1 puは各設備の正式な運用規則ではない。</p></section>
<section id="trials"><h2>06 / うまくいかなかった試験も残す。</h2>
<div class="scroll"><table style="white-space:normal"><thead><tr><th>試したこと</th><th>狙い</th><th>結果と解釈</th></tr></thead><tbody>
<tr><th>DC初期値・flat初期値、制約なし解からの再開</th><td>初期値だけの問題かを分ける</td><td>目標のQ制約付きACは失敗。反復回数だけでは解決しなかった。</td></tr>
<tr><th>220島を個別に解く</th><td>どの島が不収束かを特定</td><td>元モデルは主成分5,831母線が失敗。他219成分は収束。ただし仮想補給を含む。</td></tr>
<tr><th>同じ母線の発電機を集約</th><td>発電機行数とQ配分の影響を分ける</td><td>PとQ上下限の合計を保っても失敗。</td></tr>
<tr><th>補償比率・仮の線路リアクトルを変更</th><td>Q不足・過剰の感度を確認</td><td>設定を変えただけでは失敗。未確認設備を追加したモデルを採用しない。</td></tr>
<tr><th>大郷の推定変圧器を保留／容量増大</th><td>問題の橋枝への依存を確認</td><td>単独では別の島を作るか、未収束。支線復元後に保留しても未収束。</td></tr>
<tr><th>人口による需要傾斜</th><td>地方の過大な一様配分を緩和</td><td>この試験ではQ制約なしでも未収束。別地点への過集中も点検が必要。</td></tr>
<tr><th>伊豆の66 kV線を仮に2回線化</th><td>回線数の未記録が影響するかを調べる</td><td>未収束。各線の同定が未確認なので採用しない。</td></tr>
<tr><th>Q制約の適用・再解放を含む実験solver</th><td>制約適用順による失敗を調べる</td><td>約32–33 MVAの不整合で停止。新solverでも合格を得たとは言えない。</td></tr>
</tbody></table></div>
<p class="small">初期探索の需要補正は68組。上の正式比較はsupplementも含めて照合した70組で再実行している。ホモトピーのαは人工的なQ制約遷移であり、需要倍率ではない。</p>
<details><summary>保存した探索結果をすべて展開できる一覧</summary>@@EXPLORATION@@</details></section>
<section id="handoff"><h2>07 / Claudeが確認・再実行できる形にする。</h2>
<pre>python3 scripts/review_ac_solvability.py summary
python3 scripts/review_ac_solvability.py verify
python3 scripts/review_ac_solvability.py replay --out /tmp/ajg-ac-replay</pre>
<p>保存済み回路はgzip圧縮JSON。入力と計画のSHA256、pandapower 3.4.0を照合し、コピー上で再実行する。各試験に需要、Q違反、最終不整合、母線数、電圧、過負荷を残す。</p>
<ol class="checklist"><li><b>採用候補：</b>元ポリラインから宮城中央支線の分岐を復元する処理。buildのどの段階で枝が消えたかを追い、回帰防止へつなげる。</li><li><b>採用候補：</b>設備IDと需要配分重みを分離する処理。同名だけで母線を統合せず、実測需要を触らない。</li><li><b>次の現地・資料照合：</b>伊豆66 kVの供給端・回線数・地点需要、線路両端電圧の不一致62件、発電機のAVR能力・運転点・補償設備。</li></ol>
<p><a href="../../AC_DIAGNOSIS_TOOL.md">ツール説明</a> · <a href="results.json">全結果JSON</a> · <a href="input_metadata.json">入力の出自</a> · <a href="load_identity_plan.json">70組の照合計画</a> · <a href="sources/osm_extract.geojson">元線形・設備外形</a> · <a href="https://github.com/lutelute/All-Japan-Grid/issues/53">Claude確認用Issue #53</a></p>
<details><summary>実装のBefore / After：今回追加した全ソース</summary>@@CODE@@</details></section>
<p class="footer">写真出典：<a href="https://maps.gsi.go.jp/development/ichiran.html">地理院タイル</a>。地理情報：© OpenStreetMap contributors（<a href="https://www.openstreetmap.org/copyright">ODbL</a>）。<a href="https://pandapower.readthedocs.io/en/latest/powerflow/ac.html">pandapower公式AC説明</a>は概念の参照用。再実行は保存した3.4.0の挙動に固定。コードの実装内容はHTML内に保存し、数値は実行結果から生成。</p>
</main><script>
const data=@@DATA@@;
document.querySelectorAll('[data-site]').forEach(b=>b.addEventListener('click',()=>{const site=b.dataset.site;document.getElementById(site+'-photo').src='figures/'+site+'_'+b.dataset.mode+'.png';document.querySelectorAll('[data-site="'+site+'"]').forEach(x=>x.classList.toggle('active',x===b));}));
const points=data.strict_operating_point_ramp.concat([{...data.variants.branch_and_identity_load.strict_q,operating_point_fraction:1}]);
function showPoint(){const r=points[Number(document.getElementById('ramp-slider').value)];document.getElementById('ramp-result').innerHTML='<b>'+Math.round(r.operating_point_fraction*100)+'% / '+r.requested_load_mw.toLocaleString('ja-JP',{maximumFractionDigits:0})+' MW</b><br>'+(r.converged?'<span class="good">① 方程式・② Q上下限：'+(r.ac_equations_and_q_pass?'合格':'未通過')+'</span><br>③ 電圧・過負荷：<span class="'+(r.voltage_thermal_screen_pass?'good':'bad')+'">'+(r.voltage_thermal_screen_pass?'今回の範囲で通過':'未通過')+'</span>　最低電圧 '+r.vm_min.toFixed(3)+' pu／過負荷 '+r.overloaded_lines+'線路・'+r.overloaded_trafos+'変圧器':'<span class="bad">Q制約付きAC：未収束。運転範囲の合格判定はできない。</span>');}
document.getElementById('ramp-slider').addEventListener('input',showPoint);showPoint();
document.getElementById('ybus-json').textContent=JSON.stringify(Object.fromEntries(['before','branch_and_identity_load'].map(k=>[k,{ybus:data.variants[k].ybus,q_transition:data.variants[k].q_transition_trace}])),null,2);
</script></html>'''

if __name__ == '__main__':
    build()
