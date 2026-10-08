"""静的地図(PNG)・GIF・軽量HTML。matplotlib のみ(ベースマップ不要・県境は data/reference の簡略GeoJSON)。"""
from __future__ import annotations
import json, os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm, LinearSegmentedColormap

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
PREF = os.path.join(ROOT, "data", "reference", "japan_prefectures_simplified.geojson")
NANKAI = os.path.abspath(os.path.join(HERE, "..", ".."))
MUNI = os.path.join(NANKAI, "data", "derived", "municipalities_simplified.geojson")

# 気象庁 震度階級の配色(気象庁ウェブ配色に準拠)
JMA_COLORS = {"0": "#ffffff", "1": "#f2f2ff", "2": "#00aaff", "3": "#0041ff", "4": "#fae696", "5弱": "#ffe600",
              "5強": "#ff9900", "6弱": "#ff2800", "6強": "#a50021", "7": "#b40068"}
JMA_ORDER = ["0", "1", "2", "3", "4", "5弱", "5強", "6弱", "6強", "7"]
EXTENT_WEST = (129.5, 139.5, 30.8, 37.2)
EXTENT_ALL = (129.0, 141.5, 30.8, 37.5)

_pref_cache = None


def _jp_font():
    import matplotlib.font_manager as fm
    for name in ("Hiragino Sans", "Hiragino Maru Gothic Pro", "Noto Sans CJK JP", "IPAexGothic", "Yu Gothic"):
        if any(f.name == name for f in fm.fontManager.ttflist):
            plt.rcParams["font.family"] = name
            return name
    return None


_jp_font()
plt.rcParams["axes.unicode_minus"] = False


def _prefs():
    global _pref_cache
    if _pref_cache is None:
        g = json.load(open(PREF, encoding="utf-8"))
        polys = []
        for f in g["features"]:
            geom = f["geometry"]
            if geom["type"] == "Polygon":
                polys += [np.array(r) for r in geom["coordinates"][:1]]
            elif geom["type"] == "MultiPolygon":
                polys += [np.array(p[0]) for p in geom["coordinates"]]
        _pref_cache = polys
    return _pref_cache


def base_axes(extent=EXTENT_WEST, figsize=(11, 8.2), title=None):
    fig, ax = plt.subplots(figsize=figsize, dpi=110)
    for p in _prefs():
        ax.fill(p[:, 0], p[:, 1], color="#f3f1ea", ec="#9a9a9a", lw=0.5, zorder=0)
    ax.set_xlim(extent[0], extent[1]); ax.set_ylim(extent[2], extent[3])
    ax.set_aspect(1 / np.cos(np.radians((extent[2] + extent[3]) / 2)))
    ax.set_facecolor("#dbe9f4")
    ax.set_xticks([]); ax.set_yticks([])
    if title:
        ax.set_title(title, fontsize=13, loc="left")
    return fig, ax


def draw_fault(ax, scenario: dict):
    ax_ = np.array(scenario["trough_axis"]); dd = np.array(scenario["downdip_edge"])
    ax.plot(ax_[:, 1], ax_[:, 0], color="#333", lw=1.2, ls="--", zorder=3, label="トラフ軸(近似)")
    ax.plot(dd[:, 1], dd[:, 0], color="#333", lw=0.8, ls=":", zorder=3, label="想定震源域下端(近似)")


def hazard_map(bus, out_png, scenario=None, extent=EXTENT_WEST, title="想定震度(計測震度の平均・GMPE合成場)"):
    fig, ax = base_axes(extent, title=title)
    if scenario:
        draw_fault(ax, scenario)
    cmap = ListedColormap([JMA_COLORS[k] for k in JMA_ORDER])
    norm = BoundaryNorm([-0.5, 0.5, 1.5, 2.5, 3.5, 4.5, 5.0, 5.5, 6.0, 6.5, 7.5], cmap.N)
    order = np.argsort(bus.intensity_mean.values)
    sc = ax.scatter(bus.lon.values[order], bus.lat.values[order], c=bus.intensity_mean.values[order], cmap=cmap, norm=norm,
                    s=6, lw=0, zorder=4)
    cb = fig.colorbar(sc, ax=ax, fraction=0.03, pad=0.01, ticks=[0, 1, 2, 3, 4, 4.75, 5.25, 5.75, 6.25, 7])
    cb.ax.set_yticklabels(JMA_ORDER); cb.set_label("震度階級")
    if "tsunami_rank" in bus and (bus.tsunami_rank > 0).any():
        t = bus[bus.tsunami_rank > 0]
        ax.scatter(t.lon, t.lat, s=30, facecolors="none", edgecolors="#0055ff", lw=0.8, zorder=5, label=f"津波浸水域内の母線 ({len(t)})")
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout(); fig.savefig(out_png); plt.close(fig)


def outage_map(bus, col, out_png, title, extent=EXTENT_WEST, vmin=0, vmax=1, cmap="magma_r", label="停電確率", size_by_load=True, note=None):
    fig, ax = base_axes(extent, title=title)
    v = bus[col].values
    s = 4 + 40 * np.sqrt(np.clip(bus.pd_mw.values, 0, 500) / 500) if size_by_load else 6
    order = np.argsort(v)
    sc = ax.scatter(bus.lon.values[order], bus.lat.values[order], c=v[order], cmap=cmap, vmin=vmin, vmax=vmax,
                    s=np.asarray(s)[order] if size_by_load else s, lw=0, alpha=0.9, zorder=4)
    cb = fig.colorbar(sc, ax=ax, fraction=0.03, pad=0.01); cb.set_label(label)
    if note:
        ax.text(0.01, 0.01, note, transform=ax.transAxes, fontsize=8, va="bottom", ha="left",
                bbox=dict(boxstyle="round", fc="white", ec="#999", alpha=0.9))
    fig.tight_layout(); fig.savefig(out_png); plt.close(fig)


def restoration_gif(bus, timeline, out_gif, summ=None, extent=EXTENT_WEST, title_prefix="南海トラフ地震 停電確率", fps=1.2, col_prefix="pout_phys_t"):
    """時系列 GIF: 各 t の停電確率(母線; 既定は物理停電=設備損傷・系統崩壊・孤立)。summ があれば復旧曲線を添える。"""
    import imageio.v2 as imageio
    frames = []
    tmp = out_gif + ".frames"; os.makedirs(tmp, exist_ok=True)
    for i, t in enumerate(timeline):
        col = f"{col_prefix}{t:g}"
        if col not in bus:
            col = f"pout_t{t:g}"
        fig = plt.figure(figsize=(12.5, 8.2), dpi=100)
        gs = fig.add_gridspec(1, 2, width_ratios=[3.2, 1.0])
        ax = fig.add_subplot(gs[0, 0])
        for p in _prefs():
            ax.fill(p[:, 0], p[:, 1], color="#f3f1ea", ec="#9a9a9a", lw=0.5, zorder=0)
        ax.set_xlim(extent[0], extent[1]); ax.set_ylim(extent[2], extent[3])
        ax.set_aspect(1 / np.cos(np.radians((extent[2] + extent[3]) / 2))); ax.set_facecolor("#dbe9f4")
        ax.set_xticks([]); ax.set_yticks([])
        v = bus[col].values; order = np.argsort(v)
        s = 4 + 40 * np.sqrt(np.clip(bus.pd_mw.values, 0, 500) / 500)
        sc = ax.scatter(bus.lon.values[order], bus.lat.values[order], c=v[order], cmap="magma_r", vmin=0, vmax=1, s=s[order], lw=0, alpha=0.9, zorder=4)
        lab = f"t = {t:g} 日" if t >= 1 else f"t = {t*24:g} 時間"
        served = phys = None
        if summ is not None:
            row = summ[np.isclose(summ.t_days, t)]
            if len(row):
                served = float(row.served_frac.iloc[0]); phys = float(row.phys_frac.iloc[0]) if "phys_frac" in row else None
        sub = (f"   受電可能 {phys:.0%} / 供給率 {served:.0%}" if phys is not None else (f"   供給率 {served:.0%}" if served is not None else ""))
        ax.set_title(f"{title_prefix}  {lab}{sub}", fontsize=13, loc="left")
        cb = fig.colorbar(sc, ax=ax, fraction=0.03, pad=0.01); cb.set_label("停電確率(設備損傷・系統崩壊・孤立; 需要加重サイズ)")
        ax2 = fig.add_subplot(gs[0, 1])
        if summ is not None:
            x = summ.t_days.values
            if "phys_frac" in summ:
                ax2.plot(x, summ.phys_frac.values * 100, color="#d62728", lw=2, label="受電可能(物理)")
            ax2.plot(x, summ.served_frac.values * 100, color="#1f77b4", lw=2, label="供給率(供給力不足込み)")
            ax2.fill_between(x, summ.served_mw_p10 / summ.load_mw * 100, summ.served_mw_p90 / summ.load_mw * 100, color="#1f77b4", alpha=0.15)
            ax2.axvline(t, color="#333", lw=1.2, ls="--")
            ax2.set_xscale("symlog", linthresh=1); ax2.set_ylim(0, 100); ax2.set_xlim(0, max(x))
            ax2.set_xlabel("経過日数"); ax2.set_ylabel("[%]"); ax2.grid(alpha=0.3); ax2.legend(fontsize=8, loc="lower right")
            ax2.set_title("復旧曲線(平均, 帯=10-90%)", fontsize=10)
        fig.tight_layout()
        fp = os.path.join(tmp, f"f{i:02d}.png"); fig.savefig(fp); plt.close(fig)
        frames.append(imageio.imread(fp))
    # 最終フレームを長めに
    durations = [1 / fps] * len(frames); durations[0] = 2.0; durations[-1] = 2.5
    imageio.mimsave(out_gif, frames, duration=[d * 1000 for d in durations], loop=0)
    return out_gif


def restoration_curve_png(summ, out_png, targets=None, title="復旧曲線(平均と10-90%帯)"):
    fig, ax = plt.subplots(figsize=(7, 4.2), dpi=120)
    x = summ.t_days.values
    if "phys_frac" in summ:
        ax.plot(x, summ.phys_frac * 100, lw=2, color="#d62728", label="受電可能(設備・系統崩壊・孤立のみ)")
    ax.plot(x, summ.served_frac * 100, lw=2, color="#1f77b4", label="供給率(供給力不足の遮断込み)")
    ax.fill_between(x, summ.served_mw_p10 / summ.load_mw * 100, summ.served_mw_p90 / summ.load_mw * 100, color="#1f77b4", alpha=0.15, label="10-90%")
    if targets:
        for name, pts in targets.items():
            pts = np.array(pts)
            ax.plot(pts[:, 0], pts[:, 1], "o--", lw=1, ms=4, label=name)
    ax.set_xscale("symlog", linthresh=1); ax.set_xlim(0, max(x)); ax.set_ylim(0, 100)
    ax.set_xlabel("経過日数"); ax.set_ylabel("供給率 [%]"); ax.grid(alpha=0.3); ax.legend(fontsize=8)
    ax.set_title(title, fontsize=11)
    fig.tight_layout(); fig.savefig(out_png); plt.close(fig)


def naikakufu_comparison_png(ours: dict, targets: dict, out_png, title="内閣府2013想定との比較(五地域・停電軒数)"):
    """ours: {(region, t): 軒} (物理停電) / targets: {"基本": {region: [t0,t1,t4,t7]}, "陸側": {...}}"""
    regions = ["tokai", "kinki", "sanyo", "shikoku", "kyushu"]; labels = ["東海", "近畿", "山陽", "四国", "九州(大分宮崎)"]
    ts = [0, 1, 4, 7]
    fig, axes = plt.subplots(1, 4, figsize=(13, 3.6), dpi=120, sharey=True)
    w = 0.27
    for ai, t in enumerate(ts):
        ax = axes[ai]; xi = np.arange(len(regions))
        ax.bar(xi - w, [targets["基本"][r][ai] / 1e4 for r in regions], w, color="#999", label="内閣府 基本ケース")
        ax.bar(xi, [targets["陸側"][r][ai] / 1e4 for r in regions], w, color="#555", label="内閣府 陸側ケース")
        ax.bar(xi + w, [ours.get((r, t), 0) / 1e4 for r in regions], w, color="#d62728", label="本解析(物理停電)")
        ax.set_xticks(xi); ax.set_xticklabels(labels, fontsize=8, rotation=20)
        ax.set_title("直後" if t == 0 else f"{t}日後", fontsize=10); ax.grid(axis="y", alpha=0.3)
        ax.set_yscale("symlog", linthresh=10)
    axes[0].set_ylabel("停電軒数 [万軒]"); axes[0].legend(fontsize=7, loc="upper right")
    fig.suptitle(title, fontsize=11); fig.tight_layout(); fig.savefig(out_png); plt.close(fig)


def html_map(muni_geojson_path, bus_df, timeline, out_html, title="南海トラフ地震 電力ハザードマップ"):
    """Leaflet(CDN) の単独 HTML。自治体の停電率(時刻スライダー)+ 母線点(クリックで時系列)。データはインライン。"""
    import json as _json
    muni = _json.load(open(muni_geojson_path, encoding="utf-8")) if muni_geojson_path and os.path.exists(muni_geojson_path) else None
    ts = [float(t) for t in timeline]
    keep = ["muni_code", "pref_name", "muni_name", "load_mw", "customers", "intensity_mean", "expected_outage_days"] + [f"served_t{t:g}" for t in ts] + [f"phys_t{t:g}" for t in ts]
    if muni:
        for f in muni["features"]:
            f["properties"] = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in f["properties"].items() if k in keep}
    cols = ["lat", "lon", "name", "kv", "pd_mw", "intensity_mean", "site_pfail", "expected_outage_days"] + [f"pout_phys_t{t:g}" for t in ts if f"pout_phys_t{t:g}" in bus_df]
    b = bus_df[~bus_df.is_junction][cols].round(3)
    pts = b.values.tolist()
    html = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.js"></script>
<style>body{{margin:0;font-family:system-ui,sans-serif}}#map{{height:100vh}}.panel{{position:absolute;top:10px;right:10px;z-index:1000;background:#fff;padding:10px 12px;border-radius:8px;box-shadow:0 1px 6px rgba(0,0,0,.3);width:300px;font-size:13px}}
.legend i{{display:inline-block;width:14px;height:14px;margin-right:4px;vertical-align:middle}}</style></head><body>
<div id="map"></div><div class="panel"><b>{title}</b><br><small>解析ベース(モンテカルロ平均)。色=自治体の停電率(物理: 設備損傷・系統崩壊・孤立)、点=変電所(需要加重)。</small>
<div style="margin-top:8px">時刻: <span id="tl"></span><br><input id="sl" type="range" min="0" max="{len(ts)-1}" value="0" style="width:100%"></div>
<div><label><input type="checkbox" id="shortage"> 供給力不足の遮断も含める</label></div>
<div class="legend" style="margin-top:6px"><i style="background:#ffffb2"></i>0-10% <i style="background:#fd8d3c"></i>10-40% <i style="background:#bd0026"></i>40-80% <i style="background:#4a0012"></i>80-100%</div>
<div id="info" style="margin-top:6px;color:#333"></div></div>
<script>
const TS={ts};const MUNI={_json.dumps(muni, ensure_ascii=False) if muni else 'null'};const PTS={_json.dumps(pts, ensure_ascii=False)};const PCOLS={_json.dumps(cols)};
const map=L.map('map').setView([34.2,135.5],6);
L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{attribution:'&copy; OpenStreetMap'}}).addTo(map);
function col(v){{return v<0.1?'#ffffb2':v<0.4?'#fd8d3c':v<0.8?'#bd0026':'#4a0012';}}
let ti=0;let useTot=false;let layer=null;
function tlabel(t){{return t>=1?t+' 日後':(t*24)+' 時間後';}}
function outage(p){{const t=TS[ti];const key=(useTot?'served_t':'phys_t')+(Number.isInteger(t)?t:t.toString());const v=p[key];return v==null?null:1-v;}}
function render(){{document.getElementById('tl').textContent=tlabel(TS[ti]);if(layer)map.removeLayer(layer);if(!MUNI)return;
layer=L.geoJSON(MUNI,{{style:f=>{{const o=outage(f.properties);return {{color:'#666',weight:0.4,fillColor:o==null?'#ddd':col(o),fillOpacity:0.65}};}},
onEachFeature:(f,l)=>{{l.on('click',()=>{{const p=f.properties;let s='<b>'+p.pref_name+' '+p.muni_name+'</b><br>需要 '+p.load_mw+' MW / 需要家 '+Math.round(p.customers/1e4*10)/10+' 万 / 震度 '+p.intensity_mean+'<br>期待停電日数 '+p.expected_outage_days+' 日<br>';
TS.forEach(t=>{{const k=Number.isInteger(t)?t:t.toString();s+=tlabel(t)+': 停電 '+Math.round((1-p['phys_t'+k])*100)+'% (不足込 '+Math.round((1-p['served_t'+k])*100)+'%)<br>';}});document.getElementById('info').innerHTML=s;}});}}}}).addTo(map);}}
render();
const pl=L.layerGroup().addTo(map);
PTS.forEach(r=>{{const o={{}};PCOLS.forEach((c,i)=>o[c]=r[i]);const rad=2+Math.sqrt(Math.min(o.pd_mw,500)/500)*8;
const m=L.circleMarker([o.lat,o.lon],{{radius:rad,color:'#222',weight:0.5,fillColor:col(o['pout_phys_t0']||0),fillOpacity:0.85}});
m.bindPopup('<b>'+o.name+'</b><br>'+o.kv+' kV / 需要 '+o.pd_mw+' MW<br>震度(平均) '+o.intensity_mean+' / 変電所故障率 '+o.site_pfail+'<br>期待停電日数 '+o.expected_outage_days+' 日');pl.addLayer(m);}});
document.getElementById('sl').oninput=e=>{{ti=+e.target.value;render();pl.eachLayer(m=>{{}});}};
document.getElementById('shortage').onchange=e=>{{useTot=e.target.checked;render();}};
</script></body></html>"""
    open(out_html, "w", encoding="utf-8").write(html)
    return out_html
