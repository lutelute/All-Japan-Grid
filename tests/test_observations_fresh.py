"""観測(各社の系統情報公表の潮流実績)と OCCTO の公表を最新に保つ仕組み(2026-10-21).

それまで、取得は手で回していて、OCCTO の 30 分値は 2026-06 で止まっていた(API は約 14 か月で消える)。
各社の潮流実績も、関西 2025-06・東北 2025-02 の公表を取り込んでいなかった。さらに潮流マップの
「観測と比べる」は、同じ線を公表の年ごとに重ねて数えていた(1,752 本のうち 908 本が重なり)。
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_realtime_cycle_keeps_external_data_fresh():
    sh = (ROOT / "scripts" / "realtime_cycle.sh").read_text(encoding="utf-8")
    assert "fetch_occto_kohyo.py" in sh, "OCCTO の 30 分値を毎日取る段が無い"
    assert "fetch_system_disclosure --kind flow_actual --changed-file" in sh, "潮流実績を週 1 回確かめる段が無い"
    assert "build_line_observations.py" in sh and "export_obs_compare.py" in sh and "export_obs_local.py" in sh
    pub = (ROOT / "scripts" / "realtime_publish.sh").read_text(encoding="utf-8")
    assert "obs_compare.json" in pub and "obs_local.json" in pub, "作り直した観測が公開されない"


def test_fetcher_reads_direct_url_lists():
    """中部は設定が direct_urls(一覧)なのに、単数形しか読まず一度も自動では取られていなかった。"""
    src = (ROOT / "scripts" / "fetch_system_disclosure.py").read_text(encoding="utf-8")
    assert 'k.get("direct_urls")' in src


def test_obs_compare_does_not_stack_publication_years():
    d = json.loads((ROOT / "docs" / "data" / "flow_map" / "obs_compare.json").read_text(encoding="utf-8"))
    keys = [(l["util"], l["name"], l["from"], l["to"]) for l in d["lines"]]
    dup = len(keys) - len(set(keys))
    # 残る重なりは別の線(電圧違い・電圧別と県別の両方に載る東京の形式など)。年の重ねは 52% あった
    assert dup <= 0.1 * len(keys), f"同じ線が {dup} 本重なっている"
    assert all(l.get("src") for l in d["lines"]), "どの公表から来たか(src)が無い"


def test_fetcher_exits_nonzero_on_network_failure(tmp_path, monkeypatch):
    # 通信の失敗は終了コード 2。「該当リンクなし」(いつもの未発見)は 0 のまま(2026-10-24)
    import sys
    import scripts.fetch_system_disclosure as fsd

    cfg = tmp_path / "cfg.yaml"
    cfg.write_text("utilities:\n  t:\n    name: T\n    kinds:\n      flow_actual:\n"
                   "        direct_urls: [\"https://example.invalid/a.csv\"]\n", encoding="utf-8")
    monkeypatch.setattr(fsd, "CONFIG", cfg)
    monkeypatch.setattr(fsd, "OUTDIR", tmp_path / "out")
    monkeypatch.setattr(fsd, "PROVENANCE", tmp_path / "prov.jsonl")

    def boom(url):
        raise OSError("network down")
    monkeypatch.setattr(fsd, "get", boom)
    ch = tmp_path / "changed.txt"
    monkeypatch.setattr(sys, "argv", ["x", "--changed-file", str(ch)])
    assert fsd.main() == 2
    assert ch.exists() and ch.read_text(encoding="utf-8") == ""

    cfg.write_text("utilities:\n  t:\n    name: T\n    kinds:\n      flow_actual:\n"
                   "        index_url: https://example.invalid/\n        link_pattern: 'nomatch'\n", encoding="utf-8")
    monkeypatch.setattr(fsd, "find_links", lambda u, p: [])
    assert fsd.main() == 0


def test_cycle_retries_flow_actual_three_times():
    sh = (ROOT / "scripts" / "realtime_cycle.sh").read_text(encoding="utf-8")
    assert ".try_flow_actual_$WEEK" in sh and "-ge 3" in sh
