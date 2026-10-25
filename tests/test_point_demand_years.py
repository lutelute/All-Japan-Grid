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


def test_missing_csv_means_no_pinning(tmp_path, monkeypatch, capsys):
    # clone しただけの手元(git の外の CSV が無い)では落とさず、ピン留めなしで組む(2026-10-24)
    monkeypatch.setattr(pdm, "CSV", tmp_path / "data" / "point_demand.csv")
    monkeypatch.setattr(pdm, "ROOT", tmp_path)
    assert pdm.load_point_demand() == {}
    assert "ピン留めなし" in capsys.readouterr().err


def test_fingerprint_has_hashes_and_counts_but_no_values(tmp_path, monkeypatch):
    import hashlib
    import json

    monkeypatch.setattr(pdm, "ROOT", tmp_path)
    monkeypatch.setattr(pdm, "CSV", tmp_path / "point_demand.csv")
    assert pdm.fingerprint() == {"path": "point_demand.csv", "present": False}
    rows = ["utility,substation,secondary_kv,peak_mw,mean_mw,fiscal_year",
            "tohoku,甲,6.6,12.5,7.25,2024", "chubu,乙,6.6,3.0,1.5,2023", "tohoku,丙,22,9.0,4.0,2024"]
    raw = ("\n".join(rows) + "\n").encode("utf-8")
    pdm.CSV.write_bytes(raw)
    f = pdm.fingerprint()
    assert f["sha256"] == hashlib.sha256(raw).hexdigest() and f["bytes"] == len(raw) and f["rows"] == 3
    assert {u: v["rows"] for u, v in f["by_utility"].items()} == {"chubu": 1, "tohoku": 2}
    # 事業者ごとの sha256 は、その社の行だけで決まる(ほかの社の差し替えに動かない)
    pdm.CSV.write_bytes(raw.replace(b"3.0,1.5", b"3.5,1.5"))
    g = pdm.fingerprint()
    assert g["by_utility"]["tohoku"] == f["by_utility"]["tohoku"]
    assert g["by_utility"]["chubu"] != f["by_utility"]["chubu"]
    # 地点の名前や値は載らない
    s = json.dumps(g, ensure_ascii=False)
    assert "甲" not in s and "12.5" not in s


def test_stamp_compare_names_the_utility_that_differs():
    from scripts.check_point_demand_stamp import compare

    rec = {"present": True, "sha256": "a" * 64, "rows": 3,
           "by_utility": {"chubu": {"rows": 1, "sha256": "c"}, "tohoku": {"rows": 2, "sha256": "t"}}}
    assert compare(dict(rec), rec) == []
    assert "記録が無い" in compare(rec, None)[0]
    assert "無い" in compare({"present": False}, rec)[0]
    now = {**rec, "sha256": "b" * 64, "rows": 5,
           "by_utility": {"chubu": {"rows": 1, "sha256": "c"}, "tohoku": {"rows": 4, "sha256": "T"}}}
    d = compare(now, rec)
    assert len(d) == 2 and "tohoku" in d[1] and "4 行" in d[1]
