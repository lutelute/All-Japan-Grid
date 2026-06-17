#!/usr/bin/env python3
"""提案版エディタテンプレを生成: src/server/templates/editor.html(正)の
**パネルHTML + CSS のみ刷新 + 編集ロックJS追記**。JSロジックは完全保存(全ID/ハンドラ温存)。
→ src/server/templates/editor.proposal.html を書く。build_pages_editor.py --template で
docs/editor.proposal.html に派生(本番 editor.html は不変=見て頂いてから反映)。"""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if "__file__" in dir() else os.getcwd()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src", "server", "templates", "editor.html")
OUT = os.path.join(ROOT, "src", "server", "templates", "editor.proposal.html")

with open(SRC, encoding="utf-8") as f:
    html = f.read()

NEW_STYLE = """<style>
  :root{
    --bg:#0d1117;--card:#161b22;--card2:#1c2230;--bd:#262d38;--bd2:#30363d;
    --tx:#e6edf3;--mut:#8b949e;--acc:#388bfd;--acc2:#1f6feb;--go:#2ea043;
    --warn:#d29922;--dang:#da3633;--isl:#f0883e;--sub:#a371f7;--teal:#2dd4bf;
  }
  *{box-sizing:border-box}
  body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;color:var(--tx)}
  #map{position:absolute;top:0;bottom:0;left:0;right:382px;cursor:crosshair;background:#0a0d12}
  #panel{position:absolute;top:0;bottom:0;right:0;width:382px;background:linear-gradient(180deg,#0f141b,#0d1117);
    border-left:1px solid var(--bd);overflow-y:auto;font-size:13px;line-height:1.5}
  #panel::-webkit-scrollbar{width:9px}#panel::-webkit-scrollbar-thumb{background:#21262d;border-radius:5px}
  #panel::-webkit-scrollbar-track{background:transparent}
  .hd{position:sticky;top:0;z-index:5;background:rgba(13,17,23,.9);backdrop-filter:blur(10px);
    padding:13px 16px 11px;border-bottom:1px solid var(--bd)}
  .hd h1{font-size:15px;margin:0;font-weight:650;letter-spacing:.2px;display:flex;align-items:center;gap:7px}
  .hd p{margin:4px 0 0;font-size:11px;color:var(--mut);line-height:1.45}
  .body{padding:6px 16px 92px}
  .sec{margin-top:16px}
  .sec-t{font-size:10.5px;text-transform:uppercase;letter-spacing:.7px;color:var(--mut);
    margin:0 0 8px;font-weight:650;display:flex;align-items:center;gap:7px}
  .sec-t .badge{margin-left:auto}
  .card{background:var(--card);border:1px solid var(--bd);border-radius:11px;padding:11px 13px}
  .tools{display:flex;gap:9px;align-items:stretch}
  select#region{flex:1;padding:9px 11px;background:var(--card);color:var(--tx);border:1px solid var(--bd2);
    border-radius:10px;font-size:13px;font-weight:600;cursor:pointer;
    appearance:none;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%238b949e' d='M2 4l4 4 4-4'/%3E%3C/svg%3E");
    background-repeat:no-repeat;background-position:right 11px center}
  .lockbtn{flex:0 0 46px;border-radius:10px;background:var(--card);border:1px solid var(--bd2);
    color:var(--mut);font-size:17px;cursor:pointer;transition:.15s;display:flex;align-items:center;justify-content:center}
  .lockbtn:hover{border-color:var(--mut);color:var(--tx)}
  .lockbtn.on{background:#3a2a0f;border-color:var(--warn);color:var(--warn);box-shadow:0 0 0 1px var(--warn) inset}
  .stat{display:flex;gap:9px}
  .pill{flex:1;background:var(--card2);border:1px solid var(--bd);border-radius:11px;padding:9px 8px;text-align:center}
  .pill .n{font-size:19px;font-weight:750;line-height:1.05;letter-spacing:-.3px}
  .pill .l{font-size:9.5px;color:var(--mut);margin-top:3px;text-transform:uppercase;letter-spacing:.4px}
  .pill.main .n{color:var(--acc)}.pill.isl .n{color:var(--isl)}.pill.sub .n{color:var(--sub)}
  .statline{display:block;font-size:11px;color:var(--mut);margin-top:9px;line-height:1.5;cursor:pointer}
  .statline input{vertical-align:-1px}
  .modes{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}
  .mode{background:var(--card);border:1px solid var(--bd2);color:var(--tx);border-radius:11px;padding:10px 4px;
    font-size:11.5px;font-weight:550;cursor:pointer;transition:.13s;display:flex;flex-direction:column;
    align-items:center;gap:4px}
  .mode .ic{font-size:17px;line-height:1}
  .mode:hover{border-color:var(--mut);transform:translateY(-1px)}
  .mode.on{background:var(--acc2);border-color:var(--acc);color:#fff;box-shadow:0 3px 11px rgba(31,111,235,.4)}
  .notebtn{width:100%;flex-direction:row!important;gap:8px;border-style:dashed;font-weight:600;font-size:12px}
  .notebtn.on{background:#2a2140;border-color:var(--sub);color:#d9c2ff;box-shadow:none}
  .util{display:flex;gap:7px;margin-top:8px}
  .util button{flex:1;background:var(--card);border:1px solid var(--bd2);color:var(--tx);border-radius:9px;
    padding:8px;font-size:11.5px;font-weight:550;cursor:pointer;transition:.12s}
  .util button:hover{border-color:var(--mut)}
  .util button.on{background:#2a2140;border-color:var(--sub);color:#d9c2ff}
  .hint{background:#0e2238;border:1px solid #173a5c;border-radius:9px;padding:9px 11px;font-size:11.5px;
    color:#9cc4f0;margin-top:9px;min-height:15px;line-height:1.5}
  .hint:empty{display:none}
  .sel{color:#f0c674;font-size:11.5px;margin-top:7px;min-height:14px}
  .sel:empty{display:none}
  details{margin-top:11px;background:var(--card);border:1px solid var(--bd);border-radius:11px;overflow:hidden}
  summary{padding:10px 13px;cursor:pointer;font-size:11.5px;font-weight:600;color:var(--tx);
    list-style:none;display:flex;align-items:center;letter-spacing:.3px}
  summary::-webkit-details-marker{display:none}
  summary::after{content:"▾";color:var(--mut);font-size:12px;margin-left:auto;transition:.2s}
  details[open] summary::after{transform:rotate(180deg)}
  .det{padding:2px 13px 12px}
  .lg{display:flex;align-items:center;gap:7px;margin:6px 0;font-size:11px;color:var(--mut);flex-wrap:wrap}
  .dot{width:11px;height:11px;border-radius:50%;flex:0 0 auto}
  .ln{width:17px;height:3px;border-radius:2px;flex:0 0 auto}
  .ln.dash{background-image:repeating-linear-gradient(90deg,currentColor 0 5px,transparent 5px 9px);height:2px}
  .ring{width:11px;height:11px;border-radius:50%;border:1.5px solid #c9d1d9;flex:0 0 auto}
  .badge{display:inline-flex;align-items:center;background:var(--acc2);color:#fff;border-radius:20px;
    padding:1px 9px;font-size:11px;font-weight:650;letter-spacing:.2px}
  .badge.zero{background:#21262d;color:var(--mut)}
  .cnt{font-size:11px;color:var(--mut);font-weight:500;text-transform:none;letter-spacing:0}
  .btn-row{display:flex;gap:7px;margin-top:9px}
  .btn{flex:1;border-radius:9px;padding:9px;font-size:12px;font-weight:600;cursor:pointer;
    border:1px solid var(--bd2);background:var(--card);color:var(--tx);transition:.12s}
  .btn:hover{border-color:var(--mut)}
  .btn.go{background:var(--go);border-color:var(--go);color:#fff}
  .btn.go:hover{filter:brightness(1.08)}
  .btn.warn{background:#3a2f0f;border-color:#5a4a16;color:#f0c674}
  #editlist{font-family:ui-monospace,SFMono-Regular,monospace;font-size:10px;max-height:148px;overflow:auto;
    background:#0b0f15;border:1px solid var(--bd);border-radius:9px;padding:9px;margin-top:9px;line-height:1.6}
  textarea#memo{width:100%;background:#0b0f15;color:var(--tx);border:1px solid var(--bd2);border-radius:9px;
    padding:9px;font-size:12px;resize:vertical;font-family:inherit;line-height:1.5}
  textarea#memo:focus{outline:none;border-color:var(--acc)}
  .statusbar{position:fixed;bottom:0;right:0;width:382px;background:rgba(13,17,23,.96);backdrop-filter:blur(10px);
    border-top:1px solid var(--bd);padding:8px 16px;font-size:10.5px;color:var(--mut);z-index:6;line-height:1.4;
    white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  body.locked .modes,body.locked .util,body.locked .btn.go,body.locked .btn.warn{opacity:.4;pointer-events:none}
  body.locked .mode#m_view{opacity:1;pointer-events:auto}
  .lockbar{display:none;background:#3a2a0f;border:1px solid var(--warn);border-radius:9px;
    padding:7px 11px;margin-top:11px;font-size:11.5px;color:#f0c674;font-weight:600}
  body.locked .lockbar{display:block}
  .leaflet-control-layers{background:var(--card)!important;color:var(--tx)!important;
    border:1px solid var(--bd)!important;border-radius:10px!important;font-size:12px;box-shadow:0 4px 14px #0007!important}
  .leaflet-control-layers-expanded{padding:9px 12px}
  .leaflet-control-layers label{margin:3px 0}
  .leaflet-bar a{background:var(--card)!important;color:var(--tx)!important;border-color:var(--bd)!important}
</style></head>"""

i = html.index("<style>"); j = html.index("</style></head>")
html = html[:i] + NEW_STYLE + html[j + len("</style></head>"):]
assert NEW_STYLE in html, "style replace failed"

NEW_PANEL = """<div id="panel">
  <div class="hd">
    <h1>🔌 接続編集</h1>
    <p>OSM(実在)とモデル(build後)を並列表示。<b style="color:var(--isl)">島=未接続</b>を見つけ、繋ぐ/切るを下書き→検証。</p>
  </div>
  <div class="body">

    <div class="sec">
      <div class="sec-t">地域</div>
      <div class="tools">
        <select id="region">
          <option value="all">🗾 全国(概観・≥66kV)</option>
          <option>tokyo</option><option>hokkaido</option><option>tohoku</option><option>chubu</option>
          <option>hokuriku</option><option>kansai</option><option>chugoku</option><option>shikoku</option>
          <option>kyushu</option><option>okinawa</option>
        </select>
        <button id="m_lock" class="lockbtn" onclick="toggleLock()" title="編集ロック(閲覧専用)">🔓</button>
      </div>
      <div class="lockbar">🔒 編集ロック中 — 閲覧のみ(右上🔒で解除)</div>
    </div>

    <div class="sec">
      <div class="sec-t">モデル状態</div>
      <div class="card" id="modelstat">読込中…</div>
      <label class="statline"><input type="checkbox" id="joinuntagged" onchange="loadRegion()"> 🔗 無タグ鉄塔tipも接続(島が減る/ρ維持)</label>
    </div>

    <div class="sec">
      <div class="sec-t">編集モード</div>
      <div class="modes">
        <button id="m_view" class="mode on" onclick="setMode('view')"><span class="ic">👆</span>閲覧</button>
        <button id="m_connect" class="mode" onclick="setMode('connect')"><span class="ic">🔗</span>接続</button>
        <button id="m_chain" class="mode" onclick="setMode('chain')"><span class="ic">⛓</span>連続接続</button>
        <button id="m_cut" class="mode" onclick="setMode('cut')"><span class="ic">✂️</span>切断</button>
        <button id="m_add" class="mode" onclick="setMode('add')"><span class="ic">➕</span>点追加</button>
        <button id="m_attr" class="mode" onclick="setMode('attr')"><span class="ic">✎</span>属性</button>
      </div>
      <div class="util">
        <button onclick="undoLast()">↩ 直前を取消</button>
        <button id="m_cand" onclick="toggleCandidates()">➕ 追加候補</button>
      </div>
      <div class="util" style="margin-top:7px">
        <button id="m_note" class="mode notebtn" onclick="setMode('note')">📍 地点メモを置く → GitHub issue</button>
      </div>
      <div class="hint" id="hint"></div>
      <div class="sel" id="selinfo"></div>
    </div>

    <details>
      <summary>凡例</summary>
      <div class="det">
        <div class="lg"><span class="ring"></span>OSM変電所(スナップ可)<span class="ln" style="background:#8b949e"></span>OSM送電線</div>
        <div class="lg"><span class="dot" style="background:#388bfd"></span>本系統<span class="dot" style="background:#f0883e"></span>島(孤立)<span class="dot" style="background:#a371f7"></span>連結サブクラスタ<span class="dot" style="background:#c98a3a"></span>鉄塔分岐</div>
        <div class="lg"><span class="ln" style="background:#2dd4bf"></span>モデル接続線<span class="ln dash" style="color:#d29922"></span>編集pending<span class="ln" style="background:#3fb950"></span>adopted</div>
        <div class="lg"><span class="ln dash" style="color:#a371f7"></span>追加候補(島→最寄り本系統)</div>
      </div>
    </details>

    <div class="sec">
      <div class="sec-t">下書き <span class="cnt" id="counts"></span></div>
      <div class="btn-row">
        <button class="btn" onclick="loadEdits()">↻ 再読込</button>
        <button class="btn warn" onclick="verifyEdits()">検証(島A/B)</button>
        <button class="btn go" onclick="adoptEdits()">⬇ 反映</button>
      </div>
      <div id="editlist">—</div>
    </div>

    <details>
      <summary>🐙 GitHubに提案(issue)</summary>
      <div class="det">
        <div class="lg" style="display:block;margin-bottom:7px">pending接続を<b>まとめて1 issue</b>に。メモを添えてレビュー・採用・OSM還元の単位に。</div>
        <textarea id="memo" rows="3" placeholder="メモ(例: 井の頭通り沿いの66kVがOSMで連続。モデルでは分断。)"></textarea>
        <div class="btn-row">
          <button class="btn" onclick="previewIssue()">本文プレビュー</button>
          <button class="btn go" onclick="submitIssue()">🐙 issue送信</button>
        </div>
        <div class="lg" id="issuestat" style="margin-top:7px"></div>
      </div>
    </details>

  </div>
  <div class="statusbar" id="status">読込中…</div>
</div>"""

i = html.index('<div id="panel">'); k = html.index("</div>\n<script>")
assert html.count("</div>\n<script>") == 1, "panel close anchor not unique"
html = html[:i] + NEW_PANEL + "\n<script>" + html[k + len("</div>\n<script>"):]
assert NEW_PANEL in html, "panel replace failed"

# ── 編集ロック JS(追記のみ・既定OFF=:8088挙動不変) ──
def rep(a, b):
    global html
    assert html.count(a) == 1, f"anchor not unique/found: {a[:50]!r}"
    html = html.replace(a, b)

rep("let snapPts=[], pendingPts=[], mode='view', pick=[], pickMarkers=[];",
    "let snapPts=[], pendingPts=[], mode='view', pick=[], pickMarkers=[], editLocked=false;")

rep("function setMode(m){ endChain(); mode=m; clearPick();",
    "function setMode(m){\n  if(editLocked && m!=='view'){ flash('\U0001F512 編集ロック中 — 右上の\U0001F512で解除してから編集', false); m='view'; }\n  endChain(); mode=m; clearPick();")

rep("async function postEdit(body, skipReload){\n  let reg=REGION;",
    "async function postEdit(body, skipReload){\n  if(editLocked){ flash('\U0001F512 編集ロック中(閲覧のみ)。右上の\U0001F512で解除を', false); return null; }\n  let reg=REGION;")

rep("function clearPick(){ pick=[];",
    "function toggleLock(){\n  editLocked=!editLocked;\n  document.body.classList.toggle('locked', editLocked);\n  const b=document.getElementById('m_lock');\n  if(b){ b.textContent=editLocked?'\U0001F512':'\U0001F513'; b.classList.toggle('on', editLocked); b.title=editLocked?'編集ロック中(クリックで解除)':'編集ロック(閲覧専用)'; }\n  if(editLocked) setMode('view');\n  if(typeof flash==='function') flash(editLocked?'\U0001F512 編集ロック(閲覧専用)':'\U0001F513 編集可', !editLocked);\n}\nfunction clearPick(){ pick=[];")

# ── 📍 地点メモ → GitHub issue 機能(編集とは別系統の注釈・localStorage保存・:8088/Pages両対応) ──
PIN_JS = r"""// ── 📍 地点メモ → GitHub issue(自由な地点にピン+メモ・localStorage保存・バックエンド不要) ──
let notePinLayer=null;
function _pins(){ try{ return JSON.parse(localStorage.getItem('agj_pins')||'[]'); }catch(e){ return []; } }
function _savePins(a){ localStorage.setItem('agj_pins', JSON.stringify(a)); }
function _pinEsc(s){ return String(s).replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c])); }
function addNotePin(latlng){
  const memo=prompt('この地点のメモ(GitHub issue にします):','');
  if(memo===null || !memo.trim()) return;
  const a=_pins(); a.push({id:'p'+Date.now().toString(36)+Math.random().toString(36).slice(2,5),
    lat:latlng.lat, lon:latlng.lng, memo:memo.trim(), ts:Date.now()});
  _savePins(a); renderPins();
  if(typeof flash==='function') flash('📍 地点メモを記録(ピンをクリックで issue 化)', true);
}
function renderPins(){
  if(!notePinLayer){ notePinLayer=L.layerGroup().addTo(map); } else { notePinLayer.clearLayers(); }
  _pins().forEach(p=>{
    const mk=L.marker([p.lat,p.lon],{icon:L.divIcon({className:'',
      html:'<div style="font-size:24px;line-height:1;filter:drop-shadow(0 1px 2px #000a);cursor:pointer">📍</div>',
      iconSize:[24,24],iconAnchor:[12,22]})});
    mk.bindPopup('<b>📍 地点メモ</b><br>'+_pinEsc(p.memo)+'<br><small>'+p.lat.toFixed(5)+', '+p.lon.toFixed(5)+'</small><br>'
      +'<button onclick="pinToIssue(\''+p.id+'\')" style="margin-top:6px">🐙 issue にする</button> '
      +'<button onclick="deletePin(\''+p.id+'\')">🗑 削除</button>');
    mk.addTo(notePinLayer);
  });
}
function pinToIssue(id){
  const p=_pins().find(x=>x.id===id); if(!p) return;
  const title='[現地メモ] '+p.memo.split('\n')[0].slice(0,50);
  const body=p.memo+'\n\n地点: '+p.lat.toFixed(5)+', '+p.lon.toFixed(5)+'\n'
    +'地図(OSM): https://www.openstreetmap.org/?mlat='+p.lat+'&mlon='+p.lon+'#map=16/'+p.lat+'/'+p.lon+'\n'
    +'Google: https://maps.google.com/?q='+p.lat+','+p.lon+'\n\n> AGJ 接続編集の「地点メモ」から作成。物理接続=真・捏造禁止のもとレビューしてください。';
  const url='https://github.com/lutelute/All-Japan-Grid/issues/new?labels='+encodeURIComponent('note,location')
    +'&title='+encodeURIComponent(title)+'&body='+encodeURIComponent(body);
  window.open(url,'_blank');
}
function deletePin(id){
  if(!confirm('この地点メモを削除しますか?')) return;
  _savePins(_pins().filter(x=>x.id!==id)); renderPins();
}
function addPoint(latlng){"""

rep("add:'地図をクリックで点追加(緯度経度は自動取得)。名称・電圧を入力。',\n    attr:'変電所をクリックで属性(電圧・名称等)を編集。'};",
    "add:'地図をクリックで点追加(緯度経度は自動取得)。名称・電圧を入力。',\n    attr:'変電所をクリックで属性(電圧・名称等)を編集。',\n    note:'地図をクリックして\U0001F4CDメモを置く→ピンをクリックで GitHub issue 化(ブラウザ保存)。'};")

rep("map.on('click', e=>{\n  if(mode==='add'){ addPoint(e.latlng); return; }",
    "map.on('click', e=>{\n  if(mode==='note'){ addNotePin(e.latlng); return; }\n  if(mode==='add'){ addPoint(e.latlng); return; }")

rep("function addPoint(latlng){", PIN_JS)

rep("setMode('view');\nloadRegion();", "setMode('view');\nrenderPins();\nloadRegion();")

# ── 既定表示の改善: 「モデル接続線(水)」「モデル本系統(青)」を既定ONに ──
#   (従来は addOverlay のみ=OFF → 見えるのが島(橙)とOSM線だけで「変電所が孤立」に見えた)
rep("    if(mainLayer){ layerCtl.addOverlay(mainLayer,'モデル 本系統(青)'); }\n    if(edgeLayer){ layerCtl.addOverlay(edgeLayer,'モデル 接続線(水)'); }",
    "    if(edgeLayer){ edgeLayer.addTo(map); layerCtl.addOverlay(edgeLayer,'モデル 接続線(水)'); }\n    if(mainLayer){ mainLayer.addTo(map); layerCtl.addOverlay(mainLayer,'モデル 本系統(青)'); }")

# ── 変電所を鉄塔分岐と区別してはっきり描く(本系統): 変電所=白縁の青丸(大)/鉄塔分岐=小さく淡く ──
rep("      L.circleMarker([n.lat,n.lon],{radius:3,color:AGJ_COLORS.main,weight:0,fillOpacity:.85})\n        .on('click',e=>{L.DomEvent.stop(e); onModelNode(n);}).addTo(mainLayer);",
    "      L.circleMarker([n.lat,n.lon], n.sub\n        ? {radius:5,color:'#fff',weight:1.6,fillColor:AGJ_COLORS.main,fillOpacity:1}\n        : {radius:2.5,color:AGJ_COLORS.main,weight:0,fillOpacity:.55})\n        .on('click',e=>{L.DomEvent.stop(e); onModelNode(n);}).addTo(mainLayer);")

# ── クリック→個別の単線結線図(SLD・嶺南方式): build モデルから自動導出してSVG表示 ──
SLD_JS = r"""// ── 単線結線図(SLD draft): クリックした変電所の接続(電圧/回線数/接続先)から自動導出してSVG描画 ──
function _esc(s){ return String(s).replace(/[<>&]/g,function(c){return {'<':'&lt;','>':'&gt;','&':'&amp;'}[c];}); }
function _kvcol(kv){ if(kv>=500)return '#d62728'; if(kv>=220)return '#ff7f0e'; if(kv>=154)return '#9467bd';
  if(kv>=110)return '#1f77b4'; if(kv>=77)return '#8c564b'; if(kv>=66)return '#2ca02c'; return '#8b949e'; }
function _sldNodeAt(lat,lon){ const b=window._built; if(!b||!b.nodes) return null;
  let best=null,bd=(0.0006)*(0.0006);
  for(const n of b.nodes){ const d=(n.lat-lat)*(n.lat-lat)+(n.lon-lon)*(n.lon-lon); if(d<bd){bd=d;best=n;} } return best; }
function showSLDAt(lat,lon){ showSLD(_sldNodeAt(lat,lon) || {lat:lat,lon:lon,name:null,kv:0}); }
function _sldKey(p){ return p[0].toFixed(5)+','+p[1].toFixed(5); }
function _sldAdj(b){ if(b.__adj) return; const adj={}, nbk={};
  for(const n of b.nodes) nbk[_sldKey([n.lat,n.lon])]=n;
  for(const e of b.edges){ const ka=_sldKey(e.a), kb=_sldKey(e.b);
    (adj[ka]=adj[ka]||[]).push(kb); (adj[kb]=adj[kb]||[]).push(ka); }
  b.__adj=adj; b.__nbk=nbk; }
function _sldFollow(sub, firstEdge, b){   // 鉄塔網を辿り最寄りの接続先変電所名を返す(分岐対応BFS)
  _sldAdj(b); const nbk=b.__nbk, adj=b.__adj;
  const subK=_sldKey([sub.lat,sub.lon]);
  const far=(Math.abs(firstEdge.a[0]-sub.lat)<1e-5 && Math.abs(firstEdge.a[1]-sub.lon)<1e-5)?firstEdge.b:firstEdge.a;
  const seen={}; seen[subK]=1; let fr=[_sldKey(far)];
  for(let hop=0; hop<25 && fr.length; hop++){ const nx=[];
    for(let i=0;i<fr.length;i++){ const k=fr[i]; if(seen[k]) continue; seen[k]=1;
      const nd=nbk[k]; if(nd && nd.sub) return nd.name||'変電所';
      const ns=adj[k]||[]; for(let j=0;j<ns.length;j++){ if(!seen[ns[j]]) nx.push(ns[j]); } }
    fr=nx; }
  return null; }
function showSLD(node){
  const b=window._built; if(!b||!b.edges){ alert('モデル未読込(地域を選択してください)'); return; }
  const inc=[];
  for(const e of b.edges){ const ends=[e.a,e.b];
    for(let i=0;i<2;i++){ const p=ends[i];
      if(p && Math.abs(p[0]-node.lat)<1e-5 && Math.abs(p[1]-node.lon)<1e-5){
        inc.push({kv:Math.round(e.kv||0)||0, par:e.par||1, to:_sldFollow(node,e,b)||'(経由先)'}); } } }
  const merged={}; inc.forEach(function(x){ if(!x.kv) return; const k=x.kv+'|'+x.to;
    if(!merged[k]) merged[k]={kv:x.kv,to:x.to,n:0}; merged[k].n+=x.par; });
  const byKv={}; Object.keys(merged).forEach(function(k){ const m=merged[k]; (byKv[m.kv]=byKv[m.kv]||[]).push(m); });
  Object.keys(byKv).forEach(function(kv){ byKv[kv].sort(function(a,b){return b.n-a.n;}); });
  const nkv=Math.round(node.kv||0); if(nkv && !byKv[nkv]) byKv[nkv]=[];
  const kvs=Object.keys(byKv).map(Number).sort(function(a,b){return b-a;});
  if(!kvs.length){ alert('この点に接続線が見つかりません(鉄塔/孤立の可能性)'); return; }
  const W=720, rowH=108, H=120+rowH*kvs.length, bx0=178, bx1=560;
  const ys={}; kvs.forEach(function(kv,i){ ys[kv]=100+rowH*i; });
  let s='<svg width="'+W+'" height="'+H+'" viewBox="0 0 '+W+' '+H+'">';
  s+='<rect width="'+W+'" height="'+H+'" fill="#0d1117" rx="8"/>';
  s+='<text x="'+(W/2)+'" y="32" fill="#e6edf3" font-size="17" font-weight="700" text-anchor="middle">'+_esc(node.name||'(無名変電所)')+' 単線結線図(draft)</text>';
  s+='<text x="'+(W/2)+'" y="52" fill="#8b949e" font-size="11" text-anchor="middle">電圧階級ごと1母線・隣接をカスケード変圧器で接続(モデルから自動導出・要OSM確認)</text>';
  kvs.forEach(function(kv){ const y=ys[kv], col=_kvcol(kv), fs=byKv[kv]||[];
    s+='<line x1="'+bx0+'" y1="'+y+'" x2="'+bx1+'" y2="'+y+'" stroke="'+col+'" stroke-width="7" stroke-linecap="round"/>';
    s+='<text x="'+(bx0-12)+'" y="'+(y+4)+'" fill="'+col+'" font-size="13" font-weight="700" text-anchor="end">'+kv+'kV 母線</text>';
    fs.slice(0,8).forEach(function(f,j){ const x=bx0+42+j*46;
      s+='<line x1="'+x+'" y1="'+y+'" x2="'+x+'" y2="'+(y-32)+'" stroke="'+col+'" stroke-width="2"/>';
      s+='<circle cx="'+x+'" cy="'+(y-32)+'" r="4" fill="'+col+'"/>';
      const lbl=(f.to||'')+(f.n>1?(' ×'+f.n):'');
      if(lbl) s+='<text x="'+x+'" y="'+(y-38)+'" fill="#c9d1d9" font-size="9" text-anchor="start" transform="rotate(-32 '+x+' '+(y-38)+')">'+_esc(lbl.slice(0,16))+'</text>'; });
    if(fs.length>8) s+='<text x="'+(bx0+42+8*46)+'" y="'+(y-8)+'" fill="#8b949e" font-size="10">+'+(fs.length-8)+'先</text>';
    s+='<text x="'+(bx1+12)+'" y="'+(y+4)+'" fill="#8b949e" font-size="10">'+fs.reduce(function(a,f){return a+f.n;},0)+'回線</text>'; });
  for(let i=0;i<kvs.length-1;i++){ const y1=ys[kvs[i]], y2=ys[kvs[i+1]], ym=(y1+y2)/2, tx=bx1-46;
    s+='<line x1="'+tx+'" y1="'+y1+'" x2="'+tx+'" y2="'+y2+'" stroke="#8b949e" stroke-width="1.5"/>';
    s+='<circle cx="'+tx+'" cy="'+(ym-9)+'" r="11" fill="none" stroke="#c9d1d9" stroke-width="2"/>';
    s+='<circle cx="'+tx+'" cy="'+(ym+9)+'" r="11" fill="none" stroke="#c9d1d9" stroke-width="2"/>';
    s+='<text x="'+(tx+20)+'" y="'+(ym+4)+'" fill="#c9d1d9" font-size="11">T '+kvs[i]+'/'+kvs[i+1]+'</text>'; }
  s+='</svg>';
  let m=document.getElementById('sld-modal');
  if(!m){ m=document.createElement('div'); m.id='sld-modal';
    m.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.62);z-index:100000;display:flex;align-items:center;justify-content:center;padding:18px';
    document.body.appendChild(m); }
  m.style.display='flex';
  m.innerHTML='<div style="background:#0d1117;border:1px solid #30363d;border-radius:12px;padding:12px;max-height:92vh;overflow:auto;box-shadow:0 12px 44px #000b">'
    +'<div style="text-align:right;margin-bottom:6px"><button id="sld-close" style="background:#30363d;color:#e6edf3;border:1px solid #444c56;border-radius:7px;padding:6px 13px;cursor:pointer;font-size:12px">✕ 閉じる</button></div>'
    +s+'<div style="color:#8b949e;font-size:11px;margin-top:8px;max-width:700px;line-height:1.5">※ build モデルの接続(電圧・回線数・接続先)から自動導出した <b>draft</b>。複母線/区分/正確な母線構成は OSM 忠実層で要確認(物理接続=真・捏造禁止)。</div></div>';
  const cl=function(e){ if(e.target===m||e.target.id==='sld-close') m.style.display='none'; };
  m.onclick=cl;
}
function onModelNode(n){"""

rep("function onModelNode(n){", SLD_JS)

# onModelNode のポップアップに「単線結線図」ボタンを追加(変電所/接続あり節点)
rep("    +(n.main?'':'<br><span class=\"muted\">OSMに近接線があれば接続(2点)で繋げます</span>')\n  ).openOn(map);",
    "    +(n.main?'':'<br><span class=\"muted\">OSMに近接線があれば接続(2点)で繋げます</span>')\n    +((n.sub||(n.deg||0)>0)?('<br><button onclick=\"showSLDAt('+n.lat+','+n.lon+')\" style=\"margin-top:6px;cursor:pointer\">\U0001F4CB 単線結線図</button>'):'')\n  ).openOn(map);")

# OSM変電所クリックのポップアップにも追加
rep("    `OSM変電所 ${pt.node||''}<br>${pt.kv||'?'}kV<br><small>${pt.lat.toFixed(5)}, ${pt.lon.toFixed(5)}</small>`).openOn(map);",
    "    `OSM変電所 ${pt.node||''}<br>${pt.kv||'?'}kV<br><small>${pt.lat.toFixed(5)}, ${pt.lon.toFixed(5)}</small>`+`<br><button onclick=\"showSLDAt(${pt.lat},${pt.lon})\" style=\"margin-top:6px;cursor:pointer\">\U0001F4CB 単線結線図</button>`).openOn(map);")

# ── 衛星/OSM をあと2段ズーム可能に(maxZoom 19→21・maxNativeZoom 19で19超は拡大表示) ──
_nz = html.count("maxZoom:19")
html = html.replace("maxZoom:19", "maxZoom:21, maxNativeZoom:19")

with open(OUT, "w", encoding="utf-8") as f:
    f.write(html)
print(f"wrote {OUT} ({len(html):,} bytes)")
print("sub-distinct marker:", html.count("? {radius:5,color:'#fff'"), "| zoom19->21:", _nz)
print("pin checks: addNotePin", html.count("addNotePin"), "| pinToIssue", html.count("pinToIssue"),
      "| m_note", html.count("m_note"), "| renderPins", html.count("renderPins"))
print("checks: editLocked", html.count("editLocked"), "| toggleLock", html.count("toggleLock"),
      "| lockbar", html.count("lockbar"), "| modes grid", html.count('class="modes"'))
