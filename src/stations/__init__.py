"""変電所の構内結線(node-breaker)— OSM の node ID で結ぶ観測の層。

方法は All-AU-Grid(``docs/SUBSTATION_METHOD.md``)、実装は All-EU-Grid が欧州全体で
足した 5 規則を含む版(``src/all_eu_grid/stations.py`` ほか)を、2026-10-07 に移植した。
日本で変えた点と、SubSLD(``data/structures``)との関係は ``docs/STATION_NODE_BREAKER.md``。

モジュール:
    core         ``model(sites, lines, elements)`` — 行だけを返す純関数(移植元 stations.py)
    views        端子の根拠・ベイの機能・全閉仮定の接続点・変圧器の電圧の組(station_views.py)
    tags         電圧・回線数・周波数の読み方(tags.py。日本は 50/60 Hz を同じ ``ac``)
    extract_pbf  電力だけに絞った PBF から入力を読む(station_extract.py。pyosmium が要る)

移植元のファイルと SHA-256(移植時点。どちらのリポジトリでも未コミットだった):
    All-EU-Grid src/all_eu_grid/stations.py        61428a0d2a89c324…
    All-EU-Grid src/all_eu_grid/station_views.py   e1fc82d89924dacd…
    All-EU-Grid src/all_eu_grid/station_extract.py 6ecafda48dfae03c…
    All-EU-Grid src/all_eu_grid/tags.py            0d6af978c3df1a67…
    All-EU-Grid tests/test_stations.py             a2b95b13870c87e9…

3 つのリポジトリで規則が分かれないよう、移植元との差分は docs/STATION_NODE_BREAKER.md の
「移植元との差分」にすべて書く。差分の無い規則を勝手に変えない。
"""
