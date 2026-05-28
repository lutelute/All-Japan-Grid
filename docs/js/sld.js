'use strict';
/* ─────────────────────────────────────────────────────────────────────────
   sld.js  –  IEEE-style Single Line Diagram (単線結線図) for All-Japan Grid
   Rendered on a <canvas> element overlaid on the Leaflet map.
   ───────────────────────────────────────────────────────────────────────── */

// ── Tier config: each voltage level's layout parameters ──────────────────
const SLD_TIER = {
    500: { y: 100,  gapMin: 22,  color: '#b20000', barHalf: 12, barW: 4,   fs: 10 },
    275: { y: 310,  gapMin: 16,  color: '#0044bb', barHalf: 9,  barW: 3,   fs: 8  },
    154: { y: 490,  gapMin: 11,  color: '#006622', barHalf: 7,  barW: 2.5, fs: 7  },
    110: { y: 620,  gapMin: 9,   color: '#885500', barHalf: 6,  barW: 2,   fs: 7  },
    77:  { y: 710,  gapMin: 8,   color: '#660077', barHalf: 5,  barW: 2,   fs: 6  },
    66:  { y: 790,  gapMin: 7,   color: '#334455', barHalf: 4,  barW: 1.5, fs: 5  },
};
const SLD_VIRTUAL_W = 5200;   // virtual canvas width (world units)
const SLD_MARGIN_L  = 70;
const SLD_LON_MIN   = 125.5;
const SLD_LON_MAX   = 145.5;

// ── Module state ──────────────────────────────────────────────────────────
let _data      = null;   // loaded JSON
let _canvas    = null;
let _ctx       = null;
let _tooltip   = null;
let _cam       = { tx: 0, ty: 0, scale: 1 };
let _drag      = null;
let _layout    = null;   // cached Map: id -> {x,y}
let _layoutKey = '';

// Visible kV levels (user can toggle checkboxes)
let _visKv = new Set([500, 275]);

/* ── Public: called when the SLD tab becomes active ──────────────────────*/
async function sldShow() {
    if (!_canvas) _initCanvas();
    _canvas.style.display = 'block';
    if (!_data) {
        await _load();
    }
    _fitAll();
}

function sldHide() {
    if (_canvas) _canvas.style.display = 'none';
    if (_tooltip) _tooltip.style.display = 'none';
}

/* ── Toggle kV visibility (called from sidebar checkboxes) ───────────────*/
function sldToggleKv(kv, checked) {
    if (checked) _visKv.add(kv);
    else         _visKv.delete(kv);
    _layout    = null;   // invalidate cache
    _layoutKey = '';
    if (_data) _fitAll();
}

/* ── Fit-all / reset view ────────────────────────────────────────────────*/
function sldFitAll() { _fitAll(); }

/* ═══════════════════════════════════════════════════════════════════════
   Private helpers
═══════════════════════════════════════════════════════════════════════ */

async function _load() {
    const r = await fetch('./data/powerflow/sld_data.json');
    _data = await r.json();
}

function _initCanvas() {
    _canvas  = document.getElementById('sld-canvas');
    _ctx     = _canvas.getContext('2d');
    _tooltip = document.getElementById('sld-tooltip');

    _resize();
    window.addEventListener('resize', _resize);

    // Wheel zoom (stopPropagation prevents Leaflet zoom interference)
    _canvas.addEventListener('wheel', e => {
        e.preventDefault();
        e.stopPropagation();
        const rect = _canvas.getBoundingClientRect();
        const mx   = e.clientX - rect.left;
        const my   = e.clientY - rect.top;
        const f    = e.deltaY < 0 ? 1.13 : 1 / 1.13;
        _cam.tx    = mx - (mx - _cam.tx) * f;
        _cam.ty    = my - (my - _cam.ty) * f;
        _cam.scale *= f;
        _render();
    }, { passive: false });

    // Pan – mousedown
    _canvas.addEventListener('mousedown', e => {
        e.stopPropagation();
        _drag = { sx: e.clientX, sy: e.clientY, tx0: _cam.tx, ty0: _cam.ty };
        _canvas.style.cursor = 'grabbing';
    });
    window.addEventListener('mousemove', e => {
        if (_drag) {
            _cam.tx = _drag.tx0 + (e.clientX - _drag.sx);
            _cam.ty = _drag.ty0 + (e.clientY - _drag.sy);
            _render();
        } else {
            _hoverCheck(e);
        }
    });
    window.addEventListener('mouseup', () => {
        _drag = null;
        if (_canvas) _canvas.style.cursor = 'grab';
    });
    _canvas.addEventListener('mouseleave', () => {
        if (_tooltip) _tooltip.style.display = 'none';
    });
    _canvas.style.cursor = 'grab';

    // Touch pan
    let tLast = null;
    _canvas.addEventListener('touchstart', e => {
        if (e.touches.length === 1)
            tLast = { x: e.touches[0].clientX, y: e.touches[0].clientY, tx: _cam.tx, ty: _cam.ty };
    }, { passive: true });
    _canvas.addEventListener('touchmove', e => {
        if (e.touches.length === 1 && tLast) {
            _cam.tx = tLast.tx + (e.touches[0].clientX - tLast.x);
            _cam.ty = tLast.ty + (e.touches[0].clientY - tLast.y);
            _render();
        }
    }, { passive: true });
    _canvas.addEventListener('touchend', () => { tLast = null; });
}

function _resize() {
    if (!_canvas) return;
    _canvas.width  = _canvas.parentElement.clientWidth;
    _canvas.height = _canvas.parentElement.clientHeight;
    _render();
}

// ── Layout: computed once per kV-filter set ──────────────────────────────
function _getLayout() {
    const key = [..._visKv].sort((a,b)=>a-b).join(',');
    if (_layout && _layoutKey === key) return _layout;

    const lonRange = SLD_LON_MAX - SLD_LON_MIN;

    function geoX(lon) {
        return SLD_MARGIN_L + ((lon - SLD_LON_MIN) / lonRange) * (SLD_VIRTUAL_W - SLD_MARGIN_L * 2);
    }

    const pos = new Map();

    for (const [kvStr, tier] of Object.entries(SLD_TIER)) {
        const kv = parseInt(kvStr);
        if (!_visKv.has(kv)) continue;

        const group = _data.buses.filter(b => Math.round(b.kv) === kv);

        // Use sld_rank (crossing-minimized) if present, otherwise fall back to longitude
        const hasRank = group.length > 0 && group[0].sld_rank !== undefined;
        if (hasRank) {
            group.sort((a, b) => a.sld_rank - b.sld_rank);
        } else {
            group.sort((a, b) => a.lon - b.lon);
        }

        // x positions: use sorted geographic lons (geography preserved) but assign
        // them in rank order (crossing minimization order)
        const sortedLons = group.map(b => geoX(b.lon)).sort((a, b) => a - b);

        // push-apart: guarantee minimum horizontal gap
        for (let i = 1; i < sortedLons.length; i++) {
            if (sortedLons[i] < sortedLons[i-1] + tier.gapMin)
                sortedLons[i] = sortedLons[i-1] + tier.gapMin;
        }

        for (let i = 0; i < group.length; i++)
            pos.set(group[i].id, { x: sortedLons[i], y: tier.y });
    }

    _layout    = pos;
    _layoutKey = key;
    return pos;
}

// ── Fit-all view ─────────────────────────────────────────────────────────
function _fitAll() {
    if (!_data || !_canvas) return;
    const pos = _getLayout();
    if (!pos.size) return;

    let minX = Infinity, maxX = -Infinity,
        minY = Infinity, maxY = -Infinity;
    for (const { x, y } of pos.values()) {
        minX = Math.min(minX, x); maxX = Math.max(maxX, x);
        minY = Math.min(minY, y); maxY = Math.max(maxY, y);
    }

    const padX = 80, padY = 60;
    const scaleX = (_canvas.width  - padX * 2) / (maxX - minX || 1);
    const scaleY = (_canvas.height - padY * 2) / (maxY - minY || 1);
    _cam.scale = Math.min(scaleX, scaleY);
    _cam.tx    = padX - minX * _cam.scale;
    _cam.ty    = padY - minY * _cam.scale;
    _render();
}

// ── Render ────────────────────────────────────────────────────────────────
function _render() {
    if (!_canvas || !_data) return;
    const ctx = _ctx;
    const W   = _canvas.width;
    const H   = _canvas.height;

    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, W, H);

    ctx.save();
    ctx.translate(_cam.tx, _cam.ty);
    ctx.scale(_cam.scale, _cam.scale);

    const pos     = _getLayout();
    const busById = new Map(_data.buses.map(b => [b.id, b]));

    // ── Voltage-tier horizontal guide lines ───────────────────────────
    for (const [kvStr, tier] of Object.entries(SLD_TIER)) {
        if (!_visKv.has(parseInt(kvStr))) continue;
        ctx.save();
        ctx.setLineDash([6, 4]);
        ctx.beginPath();
        ctx.moveTo(0, tier.y);
        ctx.lineTo(SLD_VIRTUAL_W, tier.y);
        ctx.strokeStyle = tier.color;
        ctx.lineWidth   = 0.4;
        ctx.globalAlpha = 0.15;
        ctx.stroke();
        ctx.restore();

        // Tier label on left margin
        ctx.fillStyle  = tier.color;
        ctx.font       = 'bold 13px sans-serif';
        ctx.textAlign  = 'right';
        ctx.textBaseline = 'middle';
        ctx.fillText(`${kvStr} kV`, SLD_MARGIN_L - 5, tier.y);
    }

    // ── Branches (draw first, behind bus bars) ────────────────────────
    for (const br of _data.branches) {
        const p0 = pos.get(br.from);
        const p1 = pos.get(br.to);
        if (!p0 || !p1) continue;

        const ld  = br.loading;
        const col = ld < 30  ? '#1a6e1a'
                  : ld < 60  ? '#b8900a'
                  : ld < 90  ? '#cc4400'
                  :             '#cc0000';

        ctx.beginPath();
        ctx.moveTo(p0.x, p0.y);
        ctx.lineTo(p1.x, p1.y);
        ctx.strokeStyle  = col;
        ctx.lineWidth    = br.xfmr ? 1.8 : 1.1;
        ctx.globalAlpha  = 0.65;
        if (br.xfmr) ctx.setLineDash([5, 2]);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.globalAlpha = 1;
    }

    // ── Bus bars + IEEE symbols ───────────────────────────────────────
    for (const b of _data.buses) {
        const p = pos.get(b.id);
        if (!p) continue;

        const kv   = Math.round(b.kv);
        const tier = SLD_TIER[kv];
        if (!tier) continue;

        const { x, y }   = p;
        const col         = tier.color;
        const bh          = tier.barHalf;

        // ── Bus bar ──────────────────────────────────────────────────
        ctx.beginPath();
        ctx.moveTo(x - bh, y);
        ctx.lineTo(x + bh, y);
        ctx.strokeStyle = col;
        ctx.lineWidth   = tier.barW;
        ctx.lineCap     = 'butt';
        ctx.stroke();

        // ── Generator ⊙ G  (IEEE: circle with G, below bus bar) ─────
        if (b.gen) {
            const r   = Math.max(bh * 0.52, 3.5);
            const cy  = y + r + 4;

            // vertical stub bus → circle
            ctx.beginPath();
            ctx.moveTo(x, y);
            ctx.lineTo(x, y + 4);
            ctx.strokeStyle = col;
            ctx.lineWidth   = 1.2;
            ctx.stroke();

            // circle
            ctx.beginPath();
            ctx.arc(x, cy, r, 0, Math.PI * 2);
            ctx.fillStyle   = '#ffffff';
            ctx.fill();
            ctx.strokeStyle = col;
            ctx.lineWidth   = 1.6;
            ctx.stroke();

            // G label
            ctx.fillStyle    = col;
            ctx.font         = `bold ${Math.round(r * 1.65)}px monospace`;
            ctx.textAlign    = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText('G', x, cy);

        // ── Load triangle ▽  (IEEE: downward open triangle) ──────────
        } else if (b.Pd > 0.1) {
            const s = bh * 0.5;
            const ty2 = y + 3;
            ctx.beginPath();
            ctx.moveTo(x - s, ty2);
            ctx.lineTo(x + s, ty2);
            ctx.lineTo(x,     ty2 + s * 1.7);
            ctx.closePath();
            ctx.fillStyle   = '#555555';
            ctx.globalAlpha = 0.75;
            ctx.fill();
            ctx.globalAlpha = 1;
        }

        // ── Bus name label ────────────────────────────────────────────
        if (kv >= 275) {
            ctx.save();
            ctx.translate(x, y - tier.barW / 2 - 2);
            if (kv < 500) {
                // Rotated 55° to save space for denser 275 kV tier
                ctx.rotate(-0.96);
                ctx.textAlign = 'left';
            } else {
                ctx.textAlign = 'center';
            }
            ctx.fillStyle    = col;
            ctx.font         = `${tier.fs}px monospace`;
            ctx.textBaseline = 'bottom';
            ctx.fillText(b.name.slice(0, 13), 0, 0);
            ctx.restore();
        }

        // ── Vm label ─────────────────────────────────────────────────
        if (kv >= 275) {
            const vm    = b.vm;
            const vmCol = vm < 0.93 ? '#cc0000'
                        : vm > 1.07 ? '#0044cc'
                        :              '#666666';
            const yBase = b.gen
                ? y + Math.max(tier.barHalf * 0.52, 3.5) * 2 + 10
                : b.Pd > 0.1
                ? y + tier.barHalf * 0.5 * 1.7 + 7
                : y + 5;
            ctx.fillStyle    = vmCol;
            ctx.font         = '6.5px monospace';
            ctx.textAlign    = 'center';
            ctx.textBaseline = 'top';
            ctx.fillText(vm.toFixed(3) + ' pu', x, yBase);
        }
    }

    ctx.restore();
}

// ── Hover tooltip ─────────────────────────────────────────────────────────
function _hoverCheck(e) {
    if (!_data || !_canvas || !_tooltip) return;
    const rect = _canvas.getBoundingClientRect();
    const wx   = (e.clientX - rect.left  - _cam.tx) / _cam.scale;
    const wy   = (e.clientY - rect.top   - _cam.ty) / _cam.scale;

    const pos   = _getLayout();
    let best    = null;
    let bestD   = 18;   // px hit radius in world coords

    for (const b of _data.buses) {
        const p = pos.get(b.id);
        if (!p) continue;
        const d = Math.hypot(wx - p.x, wy - p.y);
        if (d < bestD) { bestD = d; best = b; }
    }

    if (best) {
        const kv = Math.round(best.kv);
        _tooltip.style.display = 'block';
        _tooltip.style.left    = (e.clientX + 14) + 'px';
        _tooltip.style.top     = (e.clientY -  8) + 'px';
        _tooltip.innerHTML =
            `<strong>${best.name}</strong><br>` +
            `${kv} kV &nbsp;|&nbsp; Vm = ${best.vm.toFixed(4)} pu` +
            (best.vm < 0.93  ? ' ⚠ LOW'  : '') +
            (best.vm > 1.07  ? ' ⚠ HIGH' : '') +
            (best.gen        ? '<br>⚡ Generator' : '') +
            (best.Pd > 0.1   ? `<br>🔌 Load ${best.Pd.toFixed(0)} MW` : '');
    } else {
        _tooltip.style.display = 'none';
    }
}

// ── Wire up tab switching (called by grid_map.js initTabs hook) ───────────
function sldInitTabHook() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            if (btn.dataset.tab === 'tab-sld') sldShow();
            else                               sldHide();
        });
    });
}

// Run when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', sldInitTabHook);
} else {
    sldInitTabHook();
}
