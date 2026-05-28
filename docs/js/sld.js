'use strict';
/* ─────────────────────────────────────────────────────────────────────────
   sld.js  –  Obsidian-style force-directed network graph for All-Japan Grid
   Rendered on <canvas> using a custom Verlet force simulation.
   Nodes = buses (draggable), Edges = branches (thickness = loading).
   ───────────────────────────────────────────────────────────────────────── */

// ── kV color palette ──────────────────────────────────────────────────────
const KV_COLOR = {
    500: '#ff4444',
    275: '#4488ff',
    154: '#22cc55',
    110: '#ff9900',
    77:  '#cc44cc',
    66:  '#66aacc',
};
const KV_RADIUS = { 500: 8, 275: 6, 154: 5, 110: 4, 77: 4, 66: 3 };

// ── Module state ──────────────────────────────────────────────────────────
let _data      = null;
let _canvas    = null;
let _ctx       = null;
let _tooltip   = null;
let _animFrame = null;
let _simNodes  = [];   // simulation node objects {id, x, y, vx, vy, kv, name, vm, Pd, gen, fx, fy}
let _simLinks  = [];   // {source, target, loading, xfmr}
let _simRunning = false;
let _dragNode  = null;
let _cam       = { tx: 0, ty: 0, scale: 1 };
let _panStart  = null;
let _hovNode   = null;

// Visible kV sets
let _visKv = new Set([500, 275]);

// ── Simulation parameters ─────────────────────────────────────────────────
const SIM = {
    repulsion:  300,    // node repulsion strength
    linkLen:    60,     // target link length (px)
    linkStr:    0.18,   // spring stiffness
    gravity:    0.03,   // pull toward center
    tierForce:  0.12,   // soft pull to tier Y-band
    damping:    0.75,   // velocity damping
    maxV:       12,     // max velocity
    alpha:      1.0,    // current heat
    alphaDec:   0.006,  // cooling per frame
    alphaMin:   0.001,
};

// Tier Y target (world units, canvas height = 1)
const TIER_Y = { 500: 0.15, 275: 0.32, 154: 0.52, 110: 0.65, 77: 0.76, 66: 0.87 };

/* ── Public API ──────────────────────────────────────────────────────────*/
async function sldShow() {
    // Make canvas visible BEFORE _initCanvas() so offsetWidth/Height are non-zero
    const el = document.getElementById('sld-canvas');
    if (el) el.style.display = 'block';
    if (!_canvas) _initCanvas();
    if (!_data) await _load();
    _rebuildSim();
    _startSim();
}

function sldHide() {
    if (_canvas) _canvas.style.display = 'none';
    if (_tooltip) _tooltip.style.display = 'none';
    _stopSim();
}

function sldToggleKv(kv, checked) {
    if (checked) _visKv.add(kv);
    else         _visKv.delete(kv);
    if (_data) { _rebuildSim(); _startSim(); }
}

function sldFitAll() { _fitAll(); }

/* ── Init canvas ─────────────────────────────────────────────────────────*/
function _initCanvas() {
    _canvas  = document.getElementById('sld-canvas');
    _ctx     = _canvas.getContext('2d');
    _tooltip = document.getElementById('sld-tooltip');

    const resize = () => {
        _canvas.width  = _canvas.offsetWidth;
        _canvas.height = _canvas.offsetHeight;
        _draw();
    };
    window.addEventListener('resize', resize);
    resize();

    // ── Pan ──
    _canvas.addEventListener('mousedown', e => {
        if (e.button !== 0) return;
        const w = _toWorld(e.clientX, e.clientY);
        const n = _nearestNode(w.x, w.y, 20 / _cam.scale);
        if (n) {
            _dragNode = n;
            n.fx = n.x; n.fy = n.y;
            SIM.alpha = Math.max(SIM.alpha, 0.4);
            if (!_simRunning) _startSim();
        } else {
            _panStart = { mx: e.clientX, my: e.clientY, tx: _cam.tx, ty: _cam.ty };
        }
        e.stopPropagation();
    }, { passive: false });

    _canvas.addEventListener('mousemove', e => {
        if (_dragNode) {
            const w = _toWorld(e.clientX, e.clientY);
            _dragNode.fx = w.x; _dragNode.fy = w.y;
        } else if (_panStart) {
            _cam.tx = _panStart.tx + (e.clientX - _panStart.mx);
            _cam.ty = _panStart.ty + (e.clientY - _panStart.my);
            _draw();
        } else {
            // Hover
            const w = _toWorld(e.clientX, e.clientY);
            const n = _nearestNode(w.x, w.y, 18 / _cam.scale);
            if (n !== _hovNode) { _hovNode = n; _draw(); }
            if (n && _tooltip) {
                _tooltip.style.display = 'block';
                _tooltip.style.left = (e.clientX + 14) + 'px';
                _tooltip.style.top  = (e.clientY - 10) + 'px';
                _tooltip.innerHTML =
                    '<b>' + n.name + '</b><br>' +
                    _kvLabel(n.kv) + '<br>' +
                    'Vm: ' + (n.vm || 1).toFixed(4) + ' pu<br>' +
                    (n.Pd ? 'Load: ' + n.Pd.toFixed(0) + ' MW' : '') +
                    (n.gen ? ' <span style="color:#ffcc00">⚡ Gen</span>' : '');
            } else if (_tooltip) {
                _tooltip.style.display = 'none';
            }
        }
    });

    _canvas.addEventListener('mouseup', () => {
        if (_dragNode) { _dragNode.fx = null; _dragNode.fy = null; _dragNode = null; }
        _panStart = null;
    });

    _canvas.addEventListener('wheel', e => {
        e.preventDefault();
        const factor = e.deltaY < 0 ? 1.12 : 0.89;
        const rect = _canvas.getBoundingClientRect();
        const cx = e.clientX - rect.left;
        const cy = e.clientY - rect.top;
        _cam.tx = cx - (cx - _cam.tx) * factor;
        _cam.ty = cy - (cy - _cam.ty) * factor;
        _cam.scale *= factor;
        _draw();
        e.stopPropagation();
    }, { passive: false });
}

/* ── Load data ───────────────────────────────────────────────────────────*/
async function _load() {
    const r = await fetch('./data/powerflow/sld_data.json?v=' + Date.now());
    _data = await r.json();
}

/* ── Rebuild simulation nodes/links ─────────────────────────────────────*/
function _rebuildSim() {
    if (!_data || !_canvas) return;
    const W = _canvas.width, H = _canvas.height;

    const prevPos = {};
    _simNodes.forEach(n => { prevPos[n.id] = { x: n.x, y: n.y }; });

    // Filter buses by visible kV
    const visBuses = _data.buses.filter(b => _visKv.has(Math.round(b.kv)));
    const visSet   = new Set(visBuses.map(b => b.id));

    _simNodes = visBuses.map(b => {
        const kv  = Math.round(b.kv);
        const old = prevPos[b.id];
        // Initial position: tier Y + geographic X scatter
        const tx  = W * 0.1 + (b.lon - 125.5) / 20 * W * 0.8;
        const ty  = H * (TIER_Y[kv] || 0.5) + (Math.random() - 0.5) * H * 0.08;
        return {
            id:   b.id,
            name: b.name,
            kv:   kv,
            vm:   b.vm,
            Pd:   b.Pd,
            gen:  b.gen,
            x:    old ? old.x : tx,
            y:    old ? old.y : ty,
            vx:   0, vy: 0,
            fx:   null, fy: null,
        };
    });

    const nodeIdx = {};
    _simNodes.forEach((n, i) => { nodeIdx[n.id] = i; });

    _simLinks = _data.branches
        .filter(br => visSet.has(br.from) && visSet.has(br.to))
        .map(br => ({
            source:  nodeIdx[br.from],
            target:  nodeIdx[br.to],
            loading: br.loading || 0,
            xfmr:    br.xfmr || false,
        }))
        .filter(l => l.source !== undefined && l.target !== undefined);

    SIM.alpha = 1.0;
}

/* ── Simulation tick ─────────────────────────────────────────────────────*/
function _tick() {
    if (SIM.alpha < SIM.alphaMin) { _simRunning = false; return; }
    const W = _canvas.width, H = _canvas.height;
    const cx = W / 2, cy = H / 2;
    const N  = _simNodes.length;
    const a  = SIM.alpha;

    // Reset forces
    _simNodes.forEach(n => { n.ax = 0; n.ay = 0; });

    // Link spring
    _simLinks.forEach(l => {
        const s = _simNodes[l.source], t = _simNodes[l.target];
        if (!s || !t) return;
        const dx = t.x - s.x, dy = t.y - s.y;
        const d  = Math.sqrt(dx * dx + dy * dy) || 1;
        const f  = (d - SIM.linkLen) * SIM.linkStr * a;
        const fx = (dx / d) * f, fy = (dy / d) * f;
        s.ax += fx; s.ay += fy;
        t.ax -= fx; t.ay -= fy;
    });

    // Repulsion (Barnes-Hut approximation skipped, direct O(N²) for N≤400)
    for (let i = 0; i < N; i++) {
        for (let j = i + 1; j < N; j++) {
            const a_ = _simNodes[i], b_ = _simNodes[j];
            const dx = b_.x - a_.x, dy = b_.y - a_.y;
            const d2 = dx * dx + dy * dy + 1;
            const f  = -SIM.repulsion * a / d2;
            const fx = (dx / Math.sqrt(d2)) * f;
            const fy = (dy / Math.sqrt(d2)) * f;
            a_.ax += fx; a_.ay += fy;
            b_.ax -= fx; b_.ay -= fy;
        }
    }

    // Gravity to center + tier-Y pull
    _simNodes.forEach(n => {
        n.ax += (cx - n.x) * SIM.gravity * a;
        n.ay += (cy - n.y) * SIM.gravity * a;
        const ty = H * (TIER_Y[n.kv] || 0.5);
        n.ay += (ty - n.y) * SIM.tierForce * a;
    });

    // Integrate
    _simNodes.forEach(n => {
        if (n.fx !== null) { n.x = n.fx; n.y = n.fy; n.vx = 0; n.vy = 0; return; }
        n.vx = (n.vx + n.ax) * SIM.damping;
        n.vy = (n.vy + n.ay) * SIM.damping;
        const spd = Math.sqrt(n.vx * n.vx + n.vy * n.vy);
        if (spd > SIM.maxV) { n.vx *= SIM.maxV / spd; n.vy *= SIM.maxV / spd; }
        n.x += n.vx;
        n.y += n.vy;
        // Boundary
        n.x = Math.max(10, Math.min(W - 10, n.x));
        n.y = Math.max(10, Math.min(H - 10, n.y));
    });

    SIM.alpha -= SIM.alphaDec;
    _draw();
}

function _startSim() {
    if (_simRunning) return;
    _simRunning = true;
    SIM.alpha = Math.max(SIM.alpha, 0.6);
    const loop = () => {
        if (!_simRunning) return;
        _tick();
        if (_simRunning) _animFrame = requestAnimationFrame(loop);
    };
    _animFrame = requestAnimationFrame(loop);
}

function _stopSim() {
    _simRunning = false;
    if (_animFrame) { cancelAnimationFrame(_animFrame); _animFrame = null; }
}

/* ── Draw ────────────────────────────────────────────────────────────────*/
function _draw() {
    if (!_canvas || !_ctx) return;
    const ctx = _ctx;
    const W = _canvas.width, H = _canvas.height;

    ctx.clearRect(0, 0, W, H);
    ctx.save();
    ctx.translate(_cam.tx, _cam.ty);
    ctx.scale(_cam.scale, _cam.scale);

    // Draw edges
    _simLinks.forEach(l => {
        const s = _simNodes[l.source], t = _simNodes[l.target];
        if (!s || !t) return;
        ctx.beginPath();
        ctx.moveTo(s.x, s.y);
        ctx.lineTo(t.x, t.y);
        ctx.strokeStyle = l.xfmr ? '#888' : _loadColor(l.loading);
        ctx.lineWidth   = l.xfmr ? 0.6 / _cam.scale : Math.max(0.5, l.loading / 40) / _cam.scale;
        ctx.setLineDash(l.xfmr ? [4 / _cam.scale, 3 / _cam.scale] : []);
        ctx.globalAlpha = 0.55;
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.globalAlpha = 1;
    });

    // Draw nodes
    _simNodes.forEach(n => {
        const r = (KV_RADIUS[n.kv] || 4) / _cam.scale * Math.max(1, _cam.scale * 0.7);
        const col = KV_COLOR[n.kv] || '#aaa';
        ctx.beginPath();
        ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
        ctx.fillStyle = col;
        ctx.globalAlpha = n === _hovNode ? 1.0 : 0.85;
        ctx.fill();
        if (n === _hovNode || n.kv >= 500) {
            ctx.strokeStyle = '#fff';
            ctx.lineWidth   = 1.5 / _cam.scale;
            ctx.stroke();
        }
        if (n.gen) {
            ctx.fillStyle = '#ffee00';
            ctx.font = (8 / _cam.scale) + 'px sans-serif';
            ctx.fillText('G', n.x + r * 0.6, n.y - r * 0.6);
        }
        // Label for high-voltage or hovered
        if (n === _hovNode || (n.kv >= 500 && _cam.scale > 0.3)) {
            ctx.fillStyle = '#fff';
            ctx.font = (9 / _cam.scale) + 'px sans-serif';
            ctx.fillText(n.name.replace(/_\d+$/, '').replace(/_\d+kV$/, ''), n.x + r + 1, n.y + 3 / _cam.scale);
        }
        ctx.globalAlpha = 1;
    });

    ctx.restore();

    // kV legend (screen-space, not scaled)
    _drawLegend(ctx, W, H);
}

function _drawLegend(ctx, W, H) {
    const items = [[500,'#ff4444'],[275,'#4488ff'],[154,'#22cc55'],[110,'#ff9900'],[77,'#cc44cc'],[66,'#66aacc']];
    const pad = 10, lineH = 18;
    const x0 = 10, y0 = H - items.length * lineH - pad;
    ctx.fillStyle = 'rgba(20,20,30,0.7)';
    ctx.fillRect(x0 - 4, y0 - 4, 90, items.length * lineH + 8);
    items.forEach(([kv, col], i) => {
        if (!_visKv.has(kv)) return;
        const y = y0 + i * lineH + 12;
        ctx.beginPath();
        ctx.arc(x0 + 6, y - 4, 5, 0, 2 * Math.PI);
        ctx.fillStyle = col;
        ctx.fill();
        ctx.fillStyle = '#ddd';
        ctx.font = '11px sans-serif';
        ctx.fillText(kv + ' kV', x0 + 16, y - 0);
    });
}

/* ── Helpers ─────────────────────────────────────────────────────────────*/
function _loadColor(pct) {
    if (pct <= 0)   return '#555';
    if (pct < 30)   return '#2ecc71';
    if (pct < 50)   return '#27ae60';
    if (pct < 70)   return '#f1c40f';
    if (pct < 90)   return '#e67e22';
    if (pct < 120)  return '#e74c3c';
    return '#8e44ad';
}

function _kvLabel(kv) {
    return { 500:'500 kV バックボーン', 275:'275 kV 地域幹線',
             154:'154 kV 基幹', 110:'110 kV', 77:'77 kV', 66:'66 kV 配電' }[kv] || kv + ' kV';
}

function _toWorld(cx, cy) {
    const rect = _canvas.getBoundingClientRect();
    return {
        x: (cx - rect.left - _cam.tx) / _cam.scale,
        y: (cy - rect.top  - _cam.ty) / _cam.scale,
    };
}

function _nearestNode(wx, wy, thresh) {
    let best = null, bestD = thresh * thresh;
    _simNodes.forEach(n => {
        const d = (n.x - wx) ** 2 + (n.y - wy) ** 2;
        if (d < bestD) { best = n; bestD = d; }
    });
    return best;
}

function _fitAll() {
    if (!_simNodes.length || !_canvas) return;
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    _simNodes.forEach(n => {
        minX = Math.min(minX, n.x); maxX = Math.max(maxX, n.x);
        minY = Math.min(minY, n.y); maxY = Math.max(maxY, n.y);
    });
    const W = _canvas.width, H = _canvas.height;
    const pad = 40;
    const sx = (W - pad * 2) / (maxX - minX || 1);
    const sy = (H - pad * 2) / (maxY - minY || 1);
    _cam.scale = Math.min(sx, sy, 3);
    _cam.tx = pad - minX * _cam.scale;
    _cam.ty = pad - minY * _cam.scale;
    _draw();
}

/* ── Tab hook ────────────────────────────────────────────────────────────*/
function sldInitTabHook() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            if (btn.dataset.tab === 'tab-sld') sldShow();
            else sldHide();
        });
    });
}

document.addEventListener('DOMContentLoaded', sldInitTabHook);
