"""変電所の構内結線(node-breaker)— OSM の node ID で結ぶ観測の層。

方法は All-AU-Grid(``docs/SUBSTATION_METHOD.md``)、実装は All-EU-Grid が欧州全体で
足した 5 規則を含む版(``src/all_eu_grid/stations.py`` ほか)を、2026-10-07 に移植した。
日本で変えた点と、SubSLD(``data/structures``)との関係は ``docs/STATION_NODE_BREAKER.md``。

モジュール:
    core         ``model(sites, lines, elements)`` — 行だけを返す純関数(移植元 stations.py)
    views        端子の根拠・ベイの機能・全閉仮定の接続点・変圧器の電圧の組(station_views.py)
    tags         電圧・回線数・周波数の読み方(tags.py。日本は 50/60 Hz を同じ ``ac``)
    extract_pbf  電力だけに絞った PBF から入力を読む(station_extract.py。pyosmium が要る)

移植元: All-EU-Grid commit 90280d7(2026-10-08 02:48 JST、eu-station-3)。9b4be87 → 3d253de → 5d85ba9 → 90280d7 と
取り込んだ。ファイルと SHA-256 の先頭:
    src/all_eu_grid/stations.py        1e056a69a0632358   → core.py
    src/all_eu_grid/station_views.py   5d64fc41b82985b3   → views.py
    src/all_eu_grid/station_extract.py 6ecafda48dfae03c   → extract_pbf.py
    src/all_eu_grid/tags.py            0d6af978c3df1a67   → tags.py(必要な部分だけ・日本の周波数)
    tests/test_stations.py             9d773510112935bf   → tests/test_stations_core.py
取り込み方: 移植元の前回のコミットから今回のコミットまでの差分を、"ac50"→"ac" と import 先を
読み替えて当てる(3-way マージ)。日本の追加(internal_extension 等)と衝突したら両方を残す。

3 つのリポジトリで規則が分かれないよう、移植元との差分は docs/STATION_NODE_BREAKER.md の
「移植元との差分」にすべて書く。差分の無い規則を勝手に変えない。
"""
