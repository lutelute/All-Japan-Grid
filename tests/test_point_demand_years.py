"""介入#30 の地点需要: 同じ年度のバンクは足し、年度は変電所ごとに最新の 1 年だけ使う(2026-10-24 訂正)。"""
import csv

import src.powerflow.point_demand as pdm

COLS = ["utility", "scope", "year", "substation", "primary_kv", "secondary_kv",
        "peak_mw", "p95_mw", "mean_mw", "min_mw", "n_obs", "source_file", "substation_no"]


def _write(path, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({**dict.fromkeys(COLS, ""), **r})


def _row(util, year, name, mean, sec="6.6", peak="10"):
    return {"utility": util, "year": year, "substation": name, "secondary_kv": sec,
            "peak_mw": peak, "mean_mw": str(mean)}


def test_latest_year_only_and_banks_summed(tmp_path, monkeypatch):
    p = tmp_path / "point_demand.csv"
    _write(p, [
        _row("tohoku", "2022", "泉変電所", 20), _row("tohoku", "2023", "泉変電所", 19),
        _row("tohoku", "2024", "泉変電所", 10), _row("tohoku", "2024", "泉変電所", 8),   # 2024 のバンク 2 台
        _row("chubu", "2024", "松島変電所", 27),                                         # 1 年だけ
        _row("tohoku", "2024", "高電圧", 50, sec="66"),                                 # 配電用でない→除外
    ])
    monkeypatch.setattr(pdm, "CSV", p)
    monkeypatch.setattr(pdm, "ALIAS", tmp_path / "missing.yaml")
    d = pdm.load_point_demand()
    assert d == {("tohoku", "泉"): 18.0, ("chubu", "松島"): 27.0}
    # 旧来(年度をまたいで足す)も再現できる
    assert pdm.load_point_demand(all_years=True)[("tohoku", "泉")] == 57.0
