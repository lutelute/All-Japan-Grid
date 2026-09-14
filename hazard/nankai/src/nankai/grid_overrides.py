"""公表台帳で系統モデルの設備値を上書きする(読み込み時・既定は設定で切り替え)。

東京電力パワーグリッドの空容量一覧(基幹系統・都県別の変電所 CSV)の「台数」と「設備容量(100%×台数)」で、
東 50 Hz の 275 kV 以上の変圧器の容量を置き換える。元の系統モデルは多くの変電所で 1 バンク分(約 953 MW)しか持っていなかった。
中部電力パワーグリッドの空容量一覧(500/275 kV 変電所)でも同じ置き換えをする(西 60 Hz・照合 8 変電所でモデル 8.6 GW 対 台帳 23.1 GW)。

台帳の生値は送配電事業者の公表物で再配布しない(docs 側には集計だけを書く)。値は pws-160core で取得した
hazard_support.sqlite(git 管理外)から読み、無ければ何もしない。
"""
from __future__ import annotations
import os, re, sqlite3, unicodedata
import numpy as np
import pandas as pd

BANK_SUFFIX = re.compile(r"[0-9・,\-~〜]+[BU]$")


def _norm_site(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s)).strip()
    s = s.replace("変電所", "").replace("開閉所", "").strip()
    s = BANK_SUFFIX.sub("", s).strip()
    return s


def ledger_transformers(db_path: str, utility: str = "東京電力パワーグリッド", min_hi_kv: float = 275.0) -> pd.DataFrame:
    """(site, hi, lo) → 台数・設備容量の合計。同じ変電所が基幹と都県の両方の CSV に出るので生の名前で重複を除いてから、バンク群の行を足す。"""
    con = sqlite3.connect(db_path)
    t = pd.read_sql_query("select substation, voltage_hi_kv hi, voltage_lo_kv lo, n_banks, capacity_total from hv_transformers "
                          "where utility = ? and source_kind like '空容量一覧CSV%' and voltage_hi_kv >= ?", con, params=(utility, min_hi_kv))
    con.close()
    t["raw"] = t.substation.map(lambda s: unicodedata.normalize("NFKC", str(s)).replace("変電所", "").strip())
    t = t.drop_duplicates(["raw", "hi", "lo"])
    t["site"] = t.raw.map(_norm_site)
    t = t[(t.capacity_total > 0) & (t.n_banks > 0)]
    return t.groupby(["site", "hi", "lo"], as_index=False).agg(n_banks=("n_banks", "sum"), capacity_total=("capacity_total", "sum"), rows=("raw", "size"))


ZONE_UTILITY = {"tokyo": "東京電力パワーグリッド", "chubu": "中部電力パワーグリッド"}


def apply_transformer_capacity(case, db_path: str, zone: str = "tokyo", scale_impedance: bool = True, min_hi_kv: float = 275.0):
    """case.branch の変圧器の cap_mw(と任意で x_pu)を台帳で置き換える。戻り: 帳簿(DataFrame, 変更した枝ごと)。
    zone = tokyo(東京電力 空容量一覧の変電所 CSV)/ chubu(中部電力 空容量一覧の 500/275 kV 変電所表・単位 MW 明記)。"""
    if not db_path or not os.path.exists(db_path):
        return pd.DataFrame()
    led = ledger_transformers(db_path, utility=ZONE_UTILITY[zone], min_hi_kv=min_hi_kv)
    br = case.branch; bus = case.bus
    kv = bus.kv.to_numpy(float); zn = bus.zone.to_numpy(); site = bus.site.astype(str).map(_norm_site).to_numpy()
    m = (br.kind == "trafo").to_numpy()
    f = br.f.to_numpy(); t = br.t.to_numpy()
    hi = np.maximum(kv[f], kv[t]); lo = np.minimum(kv[f], kv[t])
    hs = np.where(kv[f] >= kv[t], site[f], site[t])
    cand = pd.DataFrame({"i": np.where(m)[0]})
    cand["site"] = hs[cand.i]; cand["hi"] = hi[cand.i]; cand["lo"] = lo[cand.i]; cand["zone"] = zn[f[cand.i]]
    cand = cand[(cand.zone == zone) & (cand.hi >= min_hi_kv)]
    j = cand.merge(led, on=["site", "hi", "lo"], how="inner")
    if j.empty:
        return pd.DataFrame()
    rows = []
    cap = br.cap_mw.to_numpy(float).copy(); x = br.x_pu.to_numpy(float).copy()
    par = br["parallel"].to_numpy(float) if "parallel" in br else np.ones(len(br))
    for (s, h, l), g in j.groupby(["site", "hi", "lo"]):
        idx = g.i.to_numpy(); old = cap[idx]; w = np.where(np.isfinite(old) & (old > 0), old, 1.0); w = w / w.sum()
        new_total = float(g.capacity_total.iloc[0]); nb = float(g.n_banks.iloc[0]); npar = float(np.nansum(np.maximum(par[idx], 1)))
        for k, i in enumerate(idx):
            rows.append(dict(branch=int(i), site=s, hi_kv=h, lo_kv=l, cap_old=float(cap[i]), cap_new=new_total * w[k], x_old=float(x[i]),
                             x_new=float(x[i] * (npar / nb)) if scale_impedance and nb > 0 else float(x[i]), n_banks=nb, model_parallel=npar))
            cap[i] = new_total * w[k]
            if scale_impedance and nb > 0:
                x[i] = x[i] * (npar / nb)
    br["cap_mw"] = cap; br["x_pu"] = x
    return pd.DataFrame(rows)
