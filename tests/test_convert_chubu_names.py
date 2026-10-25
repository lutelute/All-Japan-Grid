"""中部の潮流実績は取得したままの名前(rule_NN)から変換できる(2026-10-26)。

それまでは手で名前を付け替えた複製(jisseki_kikan_line_2025.xlsm など)から変換していて、
clone して公表を取った人は中部の地点需要・観測の表を作れなかった。
"""
import scripts.convert_chubu_flow as cc


def test_every_rule_name_maps_to_a_name_the_converter_reads():
    names = cc.rule_names()
    assert len(names) == 8
    for rule, name in names.items():
        assert rule.startswith("rule_") and cc.PATTERN.fullmatch(name), (rule, name)
    assert len(set(names.values())) == len(names)


def test_main_reads_rule_files_and_converts_each_logical_file_once(tmp_path, monkeypatch):
    for n in ("rule_88.xlsm", "rule_92.xlsx", "rule_87.pdf", "rule_99.xlsm",   # 99 は対応に無い → 読まない
              "jisseki_kikan_line_2025.xlsm"):                                 # 88 の付け替えた複製
        (tmp_path / n).write_bytes(b"")
    monkeypatch.setattr(cc, "SRC", tmp_path)
    calls = []
    monkeypatch.setattr(cc, "convert", lambda path, name=None: calls.append((path.name, name)))
    cc.main()
    assert sorted(n for _p, n in calls) == ["jisseki_kikan_line_2025.xlsm", "jisseki_local_tr_2025.xlsx"]
