#!/usr/bin/env python3
"""equations_play.html に「用語の解析」を足す: 板書ごとの用語パネル(意味・単位と典型値・この解析での役割・注意)、
本文の用語にポップオーバー、13 枚目に用語集。式・計算・既存の文章は変えない(鉄塔の相関の向きの誤りだけ直す)。"""
import json, re, sys

SRC = sys.argv[1]; DST = sys.argv[2]
html = open(SRC, encoding="utf-8").read()

# ── 用語集 ─────────────────────────────────────────────────────────────
# id, t=用語, en=英語/記号, m=意味, u=単位・典型値, r=この解析での役割, w=注意(混同しやすい語・限界), pat=本文で下線を引く語
G = [
 # 1 距離減衰式
 dict(id="gmpe", t="距離減衰式", en="GMPE (ground motion prediction equation)", m="地震の規模と距離から地震動の強さ(PGA・PGV など)を推定する経験式。観測記録を回帰して作る。", u="出力は cm/s(PGV)や g(PGA)。司・翠川(1999)の係数が本式。", r="感度ケースの震度場を作る。一次の震度場は J-SHIS の計算結果。", w="「減衰」は距離で弱まる意味で、振動の減衰定数とは別。回帰範囲外(Mw 9)は外挿になる。", pat=["距離減衰式", "経験式"]),
 dict(id="pgv", t="最大速度 PGV", en="peak ground velocity / PGV₆₀₀", m="地震動の速度波形の絶対値の最大。PGV₆₀₀ は S 波速度 600 m/s 相当の硬い地盤(工学的基盤)での値。", u="cm/s。震度 5弱で 10 cm/s 台、6強で 100 cm/s 前後。", r="式の出力。増幅率を掛けて地表の PGV にし、計測震度へ変換する。", w="PGA(加速度)より計測震度との相関が良い。建物被害と相性が良いのは PGV、機器は PGA。", pat=["PGV"]),
 dict(id="mw", t="モーメントマグニチュード Mw", en="moment magnitude", m="断層のずれの大きさ(剛性率 × 断層面積 × すべり量 = 地震モーメント)から決まる規模。", u="単位なし。0.2 上がるとエネルギー約 2 倍。南海トラフ最大クラスは 9.1。", r="式の入力。飽和項の中にも入る。", w="気象庁マグニチュード Mj とは別で、巨大地震では Mj が頭打ちする。", pat=["マグニチュード"]),
 dict(id="faultdist", t="断層最短距離 X", en="closest distance to fault rupture", m="地点から断層面までの最短距離。", u="km。静岡変電所 27 km、大阪 40 km、福岡 200 km。", r="式の距離項。", w="震央距離(震央までの水平距離)や震源距離とは違う。巨大地震は断層面が広いので、震央から遠くても X は小さい。", pat=["断層最短距離"]),
 dict(id="amp", t="地盤増幅率 A / AVS30", en="site amplification / Vs30", m="表層の軟らかい地盤で地震動が増幅する倍率。AVS30 は地表から 30 m の平均 S 波速度で、小さいほど軟らかく増幅が大きい。", u="倍。1.0〜2.5。感度ケースは一様 1.6。", r="PGV₆₀₀ に掛けて地表の値にする。J-SHIS 場は地点ごとの微地形区分で持つ。", w="増幅は周期に依存するので、PGV に一つの係数を掛けるのは近似。", pat=["地表増幅", "地盤増幅"]),
 dict(id="jma", t="計測震度と震度階級", en="JMA seismic intensity", m="気象庁の震度計が加速度波形から計算する連続値(計測震度)を、0〜7 の 10 階級(5 と 6 は弱・強)に丸めたもの。", u="階級の境界は 4.5 / 5.0 / 5.5 / 6.0 / 6.5。", r="火力の停止率・電柱の折損率・人員の不在率の入力。", w="本式(藤本・翠川 2005)は PGV からの推定で、震度計の計算そのものではない。", pat=["計測震度", "震度階級"]),
 dict(id="saturation", t="飽和項", en="magnitude saturation term", m="式の log(X + 0.0028·10^0.5Mw) の第 2 項。断層が大きいほど近距離の実効距離が伸び、震源近くの地震動が Mw に比例して増えなくなる効果。", u="Mw 8.5 で 0.0028·10^4.25 ≈ 50 km。", r="近距離で震度が頭打ちになる理由。", w="有効 Mw を 8.3〜8.5 に留める「較正」とは別の、式の中の項。", pat=["飽和項"]),
 dict(id="geomatt", t="幾何減衰と内部減衰", en="geometric / anelastic attenuation", m="−log₁₀X は波面が広がってエネルギーが薄まる幾何減衰。−0.002X は岩石の内部摩擦で熱に変わる非弾性減衰。", u="内部減衰は 100 km で 10^−0.2 ≈ 0.63 倍。", r="遠方の減り方が 2 段階になる理由。", w="どちらも「減衰」だが仕組みが違う。", pat=["幾何減衰"]),
 dict(id="effmw", t="有効 Mw", en="effective magnitude (calibrated)", m="経験式に入れるマグニチュードを回帰範囲内(8.3〜8.5)に留めた値。", u="内閣府 2012 は 8.3、本モデルの感度ケースは 8.5。", r="Mw 9.1 を直入れしたときの遠方の過大を避ける。", w="理論ではなく較正。J-SHIS 場を一次にしたのはこのため。", pat=["有効 Mw"]),
 dict(id="directivity", t="ディレクティビティ", en="rupture directivity", m="断層の破壊が進む方向で地震動が強くなる効果。", u="—", r="本モデルには入っていない(弱い点)。", w="内閣府の強震断層モデルは破壊開始点を複数置いてこの効果を見ている。", pat=["ディレクティビティ"]),
 # 2 脆弱性曲線
 dict(id="fragility", t="脆弱性曲線", en="fragility curve", m="地震動の強さに対して「ある損傷状態以上になる確率」を描いた曲線。", u="横軸 PGA [g]、縦軸 0〜1。", r="変電所の停止確率を決める。", w="建物では「被害率曲線」と呼ぶ同じ考え方。金額の損失を出す vulnerability curve とは区別する。", pat=["脆弱性曲線"]),
 dict(id="ds", t="損傷状態 DS", en="damage state (slight / moderate / extensive / complete)", m="HAZUS の 4 段階: 軽微・中程度・大規模・全損。", u="DS1〜DS4。", r="DS ごとに停止する確率 q と修理日数(1 / 3 / 7 / 30 日)を対応づける。", w="損傷 ≠ 停止。slight は止まらず、moderate は 3 割が止まる仮定。", pat=["損傷状態"]),
 dict(id="lognormal", t="対数正規分布・中央値 θ・対数標準偏差 β", en="lognormal, median, log-standard deviation", m="対数を取ると正規分布になる分布。θ は 50% が壊れる強さ、β は曲線の緩さ(大きいほど寝る)。", u="θ は g、β は単位なしで 0.4〜0.7。", r="脆弱性曲線と修理日数の両方に使う。", w="β は「対数の標準偏差」なので、値そのものの標準偏差ではない。", pat=["対数正規", "対数標準偏差"]),
 dict(id="phi", t="標準正規分布の累積分布 Φ", en="standard normal CDF", m="平均 0・分散 1 の正規分布で「z 以下になる確率」。", u="Φ(0)=0.5、Φ(1)=0.84、Φ(−1)=0.16。", r="脆弱性曲線・木造全壊率曲線・モンテカルロの誤差の帯、すべてに出る。", w="ln を中に入れると対数正規になる。", pat=["標準正規分布の累積分布", "標準正規分布"]),
 dict(id="hazus", t="HAZUS", en="FEMA Hazus", m="米国 FEMA の自然災害損失評価手法。変電所・発電所の脆弱性曲線の標準的な出典。", u="Technical Manual 4.2 §8.5。", r="変電所の θ・β の元。", w="米国設備の値なので日本補正が要る。", pat=["HAZUS"]),
 dict(id="alpha", t="日本補正 α", en="calibration factor on median PGA", m="HAZUS の中央値 PGA に掛ける係数。曲線を右へ滑らせて日本の設備の耐震性を表す。", u="倍。本モデル 5(感度 3〜8)。", r="震度階級ごとの停止率の表と同じ水準になるよう合わせた較正。", w="PGA の換算方法(距離減衰式・増幅)と切り離せない。", pat=["日本補正"]),
 dict(id="pout", t="停止確率 P_out と q_k", en="probability of functional failure", m="損傷状態ごとの「機能を失う確率」q=(0, 0.3, 1, 1) を掛けて足した、変電所が止まる確率。", u="0〜1。275 kV・0.6 g で 0.144。", r="乱数と比べて 1 回の停止を決める。", w="q は仮定。損傷と機能停止の対応は日本の実績で確かめていない。", pat=["停止確率"]),
 dict(id="urand", t="一様乱数 u と乱数判定", en="uniform random draw", m="0〜1 の一様乱数を確率と比べ、u < P なら「起きた」とする操作。", u="—", r="モンテカルロの各サンプルで損傷・停止を決める基本操作。", w="1 回の結果は当たり外れ。何回も引いた割合が確率に戻る。", pat=["乱数"]),
 dict(id="clt", t="中心極限定理", en="central limit theorem", m="多数の独立な要因の和は正規分布に近づく、という定理。積なら対数を取って和にする。", u="—", r="対数正規が自然な形になる理由、モンテカルロの誤差が √N で縮む理由。", w="要因が独立でないと近づき方が鈍る。", pat=["中心極限定理"]),
 # 3 鉄塔
 dict(id="series", t="直列系", en="series system", m="どれか 1 つが壊れると全体が止まる構成。生存確率は各要素の生存確率の積。", u="—", r="線路 = 鉄塔の直列、経路 = 変電所と線路の直列。", w="対義は並列系(どれか 1 つ残れば動く)。2 回線・迂回路は並列。", pat=["直列系", "直列"]),
 dict(id="span", t="径間", en="span", m="隣り合う鉄塔の間隔。", u="本モデル 350 m。", r="線路長 ÷ 径間 = 鉄塔の基数 n。", w="実際は 300〜500 m で電圧階級と地形で変わる。", pat=["径間"]),
 dict(id="circuits", t="2 回線", en="double circuit", m="同じ鉄塔に 2 組の三相回路を架ける構成。片方が止まっても片方で送れる。", u="並列低減 0.5(仮定)。", r="線路の停止確率を半分にする。", w="同じ鉄塔なので、鉄塔倒壊は両方を止める。", pat=["2 回線"]),
 dict(id="spatialcorr", t="空間相関", en="spatial correlation", m="近い地点の地震動や被害が似た値になる性質。", u="—", r="本モデルは鉄塔ごとに独立に引く。", w="独立を仮定すると「どれか 1 基が倒れる」確率は相関がある場合より大きく出る(安全側の過大評価)。", pat=["空間相関"]),
 dict(id="liquefaction", t="液状化・斜面崩壊", en="liquefaction / slope failure", m="地盤が液体のようになる現象と、斜面が崩れる現象。鉄塔倒壊の実際の主因。", u="—", r="本モデルには入っていない(弱い点)。", w="揺れ単独での鉄塔倒壊は観測ゼロなので、中央値 12 g を置いている。", pat=["液状化"]),
 # 4 停止率曲線
 dict(id="stoprate", t="停止率曲線 f_c(t)", en="outage-fraction table by intensity class", m="震度階級 c の地点にある火力が、発災後 t 日に止まっている割合の表。時間とともに減る(非増加)。", u="6弱・6強で 3 週間 0.90、1 か月 0.23。", r="火力の停止期間を決める入力。内閣府 2025 と同じ表。", w="原典は経産省 H26 調査で、東日本大震災(津波・石炭火力)の経験に依存する。", pat=["停止率曲線", "停止率の表"]),
 dict(id="invtransform", t="逆変換サンプリング", en="inverse transform sampling", m="一様乱数 u を累積分布(または生存関数)の逆関数に通し、その分布に従う乱数を作る方法。", u="—", r="表を「機ごとの停止期間」に翻訳する。", w="確率積分変換とも言う。乱数を引き直せば別の運命になる。", pat=["逆変換サンプリング", "逆変換"]),
 dict(id="survival", t="生存関数", en="survival function S(t)=1−F(t)", m="「寿命が t より長い確率」。停止率曲線は「t 日にまだ止まっている割合」なので生存関数の形。", u="0〜1、非増加。", r="sup{t: u < f(t)} がその逆関数になる根拠。", w="累積分布関数 F と足すと 1。", pat=["生存関数"]),
 dict(id="sup", t="sup(上限)", en="supremum", m="集合の最小の上界。「条件を満たす t のうち最大」の意味で使っている。", u="—", r="停止期間 τ の定義。", w="max と違い、境界を含まない集合でも定義できる。", pat=["sup"]),
 # 5 周波数
 dict(id="coi", t="慣性中心 COI", en="center of inertia", m="系統内の全同期機の回転を慣性で重み付けして平均した「系統としての 1 つの周波数」。", u="Hz。", r="島ごとに 1 本の周波数で解く近似の根拠。", w="実際は場所ごとに周波数が少し違い、機どうしの振動(動揺)もある。", pat=["慣性中心"]),
 dict(id="inertia", t="系統慣性定数 H_sys", en="system inertia constant", m="運転中の同期機の回転運動エネルギーを定格容量で割った時間。", u="s。火力 3〜5、水力 2〜4、系統として 3〜6。", r="ROCOF(初期の傾き)を決める。脱落後は残った機で下がる。", w="インバータ電源(太陽光・風力・直流連系)は慣性を持たない。", pat=["系統慣性定数", "慣性定数", "慣性"]),
 dict(id="swing", t="swing 方程式(動揺方程式)", en="swing equation", m="発電機の回転子の運動方程式。機械入力と電気出力の差が回転速度(周波数)を変える。", u="—", r="周波数の式の出発点。1929 年から形は同じ。", w="本モデルは島ごとに集約した 1 本で解く。", pat=["swing 方程式"]),
 dict(id="rocof", t="ROCOF(周波数変化率)", en="rate of change of frequency", m="事故直後の周波数の傾き。−ΔP·f₀/(2H)。", u="Hz/s。H=4 s・不足 20% で −1.5 Hz/s。", r="UFLS が間に合うかを決める最初の量。", w="慣性が半分なら傾きは 2 倍。", pat=["ROCOF"]),
 dict(id="dpl", t="供給不足 ΔP_L", en="power imbalance", m="需要に対して足りない発電の割合。", u="pu(需要を 1 とした単位)または %。", r="周波数を下げる駆動力。", w="発電機の脱落だけでなく、系統分離で島に取り残された需要でも生じる。", pat=["供給不足"]),
 dict(id="loadD", t="負荷の周波数特性 D", en="load damping", m="周波数が下がると回転機負荷の消費電力が減る割合。", u="%/Hz。1〜3。本モデル 2。", r="復元力の一部(系統定数の D)。", w="インバータ負荷が増えると小さくなる。", pat=["負荷の周波数特性"]),
 dict(id="governor", t="ガバナ(調速機)・一次調整・速度調定率 R", en="governor / primary control / droop", m="周波数の偏差に応じて発電機の出力を自動で増減する装置(一次調整)。R は「出力を 100% 変えるのに必要な周波数変化の割合」。", u="R は 4〜5%。応答は数秒、上げ代(予備力)で頭打ち。", r="不足を数 % 補って周波数を戻す。", w="上げ代は運転中の機の余裕分だけ。止まった機は寄与しない。", pat=["ガバナ"]),
 dict(id="sysconst", t="系統定数 K", en="system stiffness / frequency bias", m="需給が 1% 変わったときの周波数変化の逆数。負荷の周波数特性と一次調整の和。", u="日本の慣用単位は %MW/0.1 Hz。", r="落ち着く先の周波数を決める。", w="単位が慣用なので、pu/Hz との換算に注意。", pat=["系統定数"]),
 dict(id="ufls", t="UFLS / UFR(周波数低下リレーによる負荷遮断)", en="under-frequency load shedding / relay", m="周波数が整定値を下回ったとき、負荷を段階的に切って崩壊を防ぐ仕組み。", u="北海道 2018: 48.5 Hz(時限 0.1〜21 s)と 48.0 Hz(0.1〜6 s)、計 130 万 kW。", r="崩壊を止める最後の自動装置。遮断分は停電になる。", w="計算では島内で一様に削るが、実際は指定の配電線を丸ごと切る。シナリオ卓の夜景は変電所ごとの消灯で表示。", pat=["UFLS"]),
 dict(id="genuf", t="発電機の低周波数保護", en="generator under-frequency protection", m="周波数が下がりすぎるとタービンの共振や補機の不調を避けるため発電機を切り離す保護。", u="50 Hz 系で 46〜47 Hz 台(水力 46.0 Hz は北海道の実績)。", r="動作すると不足がさらに増えて全停に至る。", w="UFLS(負荷側)と混同しない。こちらは発電側。", pat=["低周波数保護"]),
 dict(id="overshed", t="過遮断", en="over-shedding", m="UFLS で必要以上に負荷を切り、周波数が定格を超えて上がること。", u="—", r="慣性が小さいと段が続けて動いて起きやすい。", w="上がりすぎると発電機の周波数上昇保護(OF)が動く。", pat=["過遮断"]),
 dict(id="nadir", t="最下点と整定周波数", en="frequency nadir / settling frequency", m="最下点は落ち込みの底、整定周波数は落ち着く先。", u="Hz。北海道 2018 の最下点は 46.13 Hz。", r="最下点が保護の整定値を割るかどうかで全停が決まる。", w="ROCOF(傾き)・最下点(深さ)・整定(落ち着き)は別々に読む。", pat=["最下点"]),
 dict(id="pu", t="単位法 pu", en="per unit", m="基準値(定格容量・需要など)で割った無次元の値。", u="1 pu = 基準値。", r="式の ΔP や D の単位。", w="基準を何にしたかを常に確認する。", pat=["pu"]),
 dict(id="synchronous", t="同期機とインバータ電源", en="synchronous machine / inverter-based resource", m="同期機は回転子が系統周波数と同期して回る発電機(火力・水力・原子力)。インバータ電源は太陽光・風力・直流連系で、慣性を持たない。", u="—", r="H_sys は同期機だけで数える。", w="インバータ電源の増加で慣性が下がり、UFLS の整定の見直しが進む。", pat=["同期機"]),
 # 6 DC 潮流
 dict(id="dcflow", t="DC 潮流(直流法潮流)", en="DC power flow", m="交流潮流の線形近似。電圧一定・角度差小・抵抗無視で、有効電力だけを解く。", u="—", r="連鎖の各手で潮流を解く。7,000 母線でもミリ秒。", w="直流送電とは無関係の名前。電圧・無効電力は扱えない。", pat=["DC 潮流"]),
 dict(id="theta", t="電圧位相角 θ", en="voltage angle", m="各母線の電圧の位相。潮流は位相差に比例して流れる。", u="rad。", r="B θ = P の未知数。", w="角度の絶対値に意味はなく、差だけが効く(1 つを基準 0 に置く)。", pat=["電圧位相角", "位相角"]),
 dict(id="reactance", t="リアクタンス x", en="reactance", m="送電線・変圧器の交流抵抗のうち、電流の位相を遅らせる成分。", u="pu。", r="潮流の分かれ方(1/x に比例)を決める。", w="抵抗 r は DC 潮流で無視する。", pat=["リアクタンス"]),
 dict(id="bus", t="母線と枝", en="bus / branch", m="母線は変電所内の電気的な接続点、枝は母線をつなぐ送電線・変圧器。", u="本モデル 西 7,985・東 6,253 母線。", r="系統モデルの節点と辺。", w="1 つの変電所に電圧階級ごとの母線がある。", pat=["母線"]),
 dict(id="injection", t="注入 P", en="bus injection", m="母線の発電 − 負荷。", u="MW。", r="B θ = P の右辺。", w="合計は 0(損失を無視)。", pat=["注入"]),
 dict(id="bmatrix", t="B 行列(グラフラプラシアン)", en="susceptance matrix / graph Laplacian", m="1/x を重みとした接続行列。対角は隣接する枝の和、非対角は −1/x。", u="—", r="解くと θ が出る。", w="1 行 1 列を落とさないと特異(基準母線を決める)。", pat=["グラフラプラシアン", "B 行列"]),
 dict(id="lodf", t="LODF(線路開放分布係数)", en="line outage distribution factor", m="枝 k を止めたとき、その潮流が枝 l にどれだけ乗るかの係数。", u="−1〜1。直通 1 本に迂回路 1 本なら 1。", r="1 本止めた後の再配分を行列で出す。", w="橋(落とすと網が割れる枝)では定義できない。", pat=["LODF"]),
 dict(id="ptdf", t="PTDF(電力転送分布係数)", en="power transfer distribution factor", m="ある母線対に 1 MW 送ったとき、各枝に現れる潮流の割合。", u="−1〜1。", r="LODF の元。本プロジェクトの感度行列と同じ。", w="DC 潮流の枠内でだけ厳密。", pat=["PTDF"]),
 dict(id="reactivep", t="有効電力と無効電力", en="active / reactive power", m="有効電力は仕事をする電力、無効電力は電圧を支えるために行き来する電力。", u="MW / Mvar。", r="DC 潮流は有効電力だけ。", w="電圧崩壊は無効電力の話なので、本モデルには見えない。", pat=["無効電力"]),
 dict(id="fastdecoupled", t="高速分解法", en="fast decoupled load flow", m="有効電力−位相角、無効電力−電圧に分けて交流潮流を速く解く方法。", u="—", r="DC 潮流はその B' 行列そのもの。", w="Stott & Alsac (1974)。", pat=["高速分解法"]),
 # 7 過負荷
 dict(id="thermal", t="熱容量 S_ij", en="thermal rating", m="導体の温度上限で決まる、送れる電力の上限。", u="MVA。", r="過負荷の判定の基準。", w="運用容量(安定度・電圧で決まる)は熱容量より小さいことが多い。本プロジェクトの実測で理論値は運用容量の約 2 倍。", pat=["熱容量"]),
 dict(id="emergency", t="緊急定格 γ", en="emergency rating", m="短時間なら熱容量を超えて流してよい倍率。", u="本モデル 1.25。", r="γ·S を超えた枝を切る。", w="実際は時間とともに許容が下がる(温度上昇)。", pat=["緊急定格"]),
 dict(id="loadfactor", t="負荷率", en="loading", m="潮流 ÷ 容量。", u="%。100% 超が過負荷。", r="図の線路の色(緑→黄→赤)。", w="発電の「負荷率」(稼働率)と同じ言葉で別の意味。", pat=["負荷率"]),
 dict(id="relay", t="保護リレー(過負荷リレー)", en="protective relay", m="電流や潮流が整定値を超えると遮断器を開かせる装置。", u="—", r="連鎖の各手で「切る」役。", w="実際の過負荷保護は時間特性を持ち、運転員が先に手を打つことも多い。", pat=["保護リレー"]),
 dict(id="bridge", t="橋と孤立", en="bridge / islanding", m="取り除くと網が二つに分かれる枝が橋。橋が切れると片側が電源から孤立する。", u="本プロジェクトの実測で枝の約 3 割が橋。", r="孤立(灰色の母線)が生まれる仕組み。", w="孤立は損傷していない設備でも起きる。", pat=["橋(", "孤立"]),
 dict(id="cascade", t="連鎖(カスケード)", en="cascading outage", m="1 本の停止が潮流の再配分で次の過負荷を生み、停止が連鎖する現象。", u="2003 年北米大停電が典型。", r="「切る → 解き直す」の繰り返しで追う。", w="8 反復で打ち切る。運転員の介入は入っていない。", pat=["連鎖"]),
 dict(id="superposition", t="重ね合わせの原理", en="superposition", m="線形系では、複数の入力に対する応答が個々の応答の和になる。", u="—", r="枝停止の効果を「打ち消す注入」の重ね合わせで計算できる根拠。", w="交流潮流(非線形)では厳密には成り立たない。", pat=["重ね合わせの原理"]),
 # 8 復旧
 dict(id="lnrepair", t="修理時間の対数正規分布", en="lognormal repair time", m="中央値 μ 日・対数標準偏差 β の分布から修理日数を引く。", u="変電所 DS1〜4 で中央値 1 / 3 / 7 / 30 日。", r="各ジョブの所要時間。", w="中央値は仮定。主変圧器のリードタイム(180 日)は別勘定。", pat=["修理日数"]),
 dict(id="listsched", t="リストスケジューリング", en="list scheduling", m="優先順に並べたジョブを、空いた作業者から順に割り当てる単純な規則。", u="Graham (1966)。最適の 2 倍以内が保証される。", r="班へのジョブの割当。", w="順序を変えると完了時刻が変わる(規律)。", pat=["リストスケジューリング"]),
 dict(id="queue", t="待ち行列 M/M/c と Erlang C", en="queueing model", m="到着がポアソン(M)、処理が指数(M)、c 台のサーバの待ち行列モデル。Erlang C は「待たされる確率」。", u="Kendall の記法。", r="待ち時間と修理時間を分けて読む枠組み。", w="地震は一括到着なので定常の公式は目安。", pat=["待ち行列"]),
 dict(id="lambda", t="到着率 λ・処理率 μ・利用率 ρ", en="arrival rate / service rate / utilization", m="λ は単位時間あたりの到着数、μ は 1 台の処理率(1/平均修理時間)、ρ = λ/(cμ) はサーバの忙しさ。", u="ρ は 0〜1。1 に近いと待ちが急増。", r="人手が律速か資材が律速かを切り分ける。", w="ρ ≥ 1 では定常状態が存在しない。", pat=["利用率"]),
 dict(id="little", t="Little の公式 L = λW", en="Little's law", m="系内の平均数 = 到着率 × 平均滞在時間。", u="—", r="停電の総量(要素 × 日)を人手と時間に分解する検算。", w="定常でなくても平均で成り立つ。", pat=["Little"]),
 dict(id="wq", t="平均待ち時間 W_q と滞在時間 W", en="waiting / sojourn time", m="W_q は着手までの待ち、W = W_q + 修理時間。", u="日。", r="班を増やせば W_q が縮み、資材が律速なら縮まない。", w="復旧曲線は W の分布の帰結。", pat=["待ち時間"]),
 dict(id="batcharrival", t="一括到着と過渡", en="batch arrival / transient", m="地震では全ジョブが t=0 に来るので、時間とともに変わる過渡の挙動になる。", u="—", r="定常状態の公式が使えない理由。", w="シミュレーション(リストスケジューリング)で数える。", pat=["一括到着"]),
 dict(id="discipline", t="規律(discipline)", en="queue discipline", m="待ち行列でどの順に処理するかの規則。FIFO、優先度順など。", u="—", r="復旧の優先順(電圧が高い順 → 需要大)に当たる。", w="順序だけで完了時刻が大きく変わる。", pat=["規律"]),
 dict(id="leadtime", t="リードタイム", en="lead time", m="資材を発注して届くまでの時間。", u="主変圧器で 180 日級。", r="班を増やしても縮まない仕事の代表。", w="本モデルは完了時刻に反映していない(弱い点)。", pat=["リードタイム"]),
 dict(id="gantt", t="ガント図", en="Gantt chart", m="横軸に時間、行に担当を取って作業の割当を示す図。", u="—", r="班ごとの担当の可視化。", w="—", pat=["ガント"]),
 # 9 モンテカルロ
 dict(id="montecarlo", t="モンテカルロ法", en="Monte Carlo method", m="乱数で多数の仮想シナリオを作り、平均で確率や期待値を求める方法。", u="本番 N=200。", r="損傷 → 系統 → 復旧の全体を確率として出す。", w="誤差は 1/√N でしか縮まない。", pat=["モンテカルロ"]),
 dict(id="se", t="標準誤差 SE", en="standard error", m="推定値のばらつきの標準偏差。", u="√(p(1−p)/N)。p=0.3・N=200 で ±0.032。", r="母線 1 点の確率がどれだけ揺れるかの目安。", w="標準偏差(データのばらつき)と混同しない。", pat=["標準誤差"]),
 dict(id="lln", t="大数の法則", en="law of large numbers", m="独立な試行を増やすと平均が真の値に近づく。", u="—", r="平均で確率が出る根拠。", w="近づく速さは中心極限定理が決める。", pat=["大数の法則"]),
 dict(id="expected", t="期待停電日数 E[T_i]", en="expected outage duration", m="停電確率を時間で積分した値。", u="日(90 日まで)。", r="母線ごとの停電の重さを 1 つの数にする。", w="平均なので、長期の停電が少数あると引き上げられる。", pat=["期待停電日数"]),
 dict(id="quantile", t="分位(10〜90% 帯)", en="quantile band", m="サンプルを並べて下から 10% と 90% の値の間。", u="—", r="復旧曲線の帯。", w="平均が帯の中央にあるとは限らない。", pat=["分位"]),
 dict(id="indicator", t="指示関数 𝟙[·]", en="indicator function", m="条件が真なら 1、偽なら 0。", u="—", r="平均を取ると確率になる。", w="—", pat=["𝟙"]),
 # 10 ポテンシャル法
 dict(id="pathsurv", t="経路の生存率 S", en="path survival probability", m="電源から母線までの経路上の要素が全部生き残る確率。", u="0〜1。", r="ポテンシャル法の中心の量。", w="直列だけを見るので、長い経路で 0 に飽和する。", pat=["生存率"]),
 dict(id="logweight", t="重み w = −ln(1−p)", en="log-survival weight", m="積を和に変える変換。停止確率が大きいほど大きい重み。", u="p=0.1 で 0.105。", r="最短路で解けるようにする。", w="p が 1 に近いと重みが無限大に近づく。", pat=["重み"]),
 dict(id="dijkstra", t="Dijkstra 法・最短路", en="Dijkstra's algorithm", m="重み付きグラフで始点から各点への最短経路長を求める算法。", u="全母線 0.8 秒。", r="「最も生き残りやすい経路」を一括で出す。", w="負の重みは扱えない(ここでは常に正)。", pat=["Dijkstra", "最短路"]),
 dict(id="supply", t="供給余力 A^sup", en="supply surplus", m="半径 80 km の発電の余力で、経路の生存率に掛ける因子。", u="0〜1。", r="ポテンシャル法固有の需給の代理。", w="解析法の需給崩壊とは別の近似。", pat=["供給余力"]),
 dict(id="redundancy", t="冗長経路・並列 m", en="redundant paths", m="同じ地点へ行く別経路の本数。", u="1−(1−S)^m。", r="v0 は m=1 しか見ていない(飽和の原因)。", w="厳密な網信頼度は計算不能なので近似が要る。", pat=["冗長経路"]),
 dict(id="sharpP", t="網信頼度と #P", en="network reliability / #P-completeness", m="ネットワーク全体の接続確率を厳密に求める問題は #P 完全で、計算量が指数的に増える。", u="Valiant (1979)、Ball (1986)。", r="最短路で近似する理由。", w="—", pat=["#P"]),
 dict(id="weightedcorr", t="需要加重相関", en="demand-weighted correlation", m="母線ごとの指標の相関を需要で重み付けしたもの。", u="ポテンシャル法と解析法で 0.56。", r="指標の妥当性の目安。", w="順位の一致であって、確率の絶対値の一致ではない。", pat=["需要加重相関"]),
 # 11 全体
 dict(id="upstream", t="上流孤立", en="upstream isolation", m="母線自体は無事でも、電源へつながる上流の設備が止まって受電できない状態。", u="—", r="停電の原因の 1 つとして分けて数える。", w="内閣府の想定には無い勘定。", pat=["上流孤立"]),
 dict(id="areacollapse", t="需給崩壊と供給力不足", en="area collapse / supply shortfall", m="発電が需要に対して不足して周波数が保てない状態(需給崩壊)と、不足分を計画的に遮断する状態(供給力不足)。", u="—", r="v0 は「エリア不足率 25% 超で崩壊」のしきい値、その後の版は動的に解く。", w="2011 年の計画停電は供給力不足の側。", pat=["需給崩壊", "供給力不足"]),
 dict(id="fiveregion", t="五地域", en="five regions", m="内閣府の想定の集計単位(東海・近畿・山陽・四国・九州)。", u="—", r="内閣府と同じ土俵で軒数を突き合わせる。", w="本解析は供給地点数、内閣府は電灯軒数で、定義が約 2 割違う。", pat=["五地域"]),
 dict(id="hindcast", t="ハインドキャスト", en="hindcast", m="過去に起きた事象を同じモデルで再現して検証すること。", u="—", r="北海道 2018・2022 福島県沖で実施(その後の版)。", w="較正に使った事象で検証しても独立の裏付けにならない。", pat=["ハインドキャスト"]),
 dict(id="distribution", t="配電", en="distribution network", m="6.6 kV 以下の電柱・配電線と柱上変圧器。", u="全国の支持物 約 2,000 万基。", r="v0 には無い。その後の版で電柱の折損と復旧人員のモデルを追加。", w="内閣府が 1〜2 週間見ている停電はここが主因。", pat=["配電"]),
]
SLIDE_TERMS = {
 1: ["gmpe", "pgv", "mw", "faultdist", "amp", "jma", "saturation", "geomatt", "effmw", "directivity"],
 2: ["fragility", "ds", "pga_ref", "lognormal", "phi", "hazus", "alpha", "pout", "urand", "clt"],
 3: ["series", "span", "circuits", "spatialcorr", "liquefaction", "lognormal"],
 4: ["stoprate", "invtransform", "survival", "sup", "jma", "urand"],
 5: ["coi", "inertia", "swing", "rocof", "dpl", "loadD", "governor", "sysconst", "ufls", "genuf", "overshed", "nadir", "pu", "synchronous"],
 6: ["dcflow", "theta", "reactance", "bus", "injection", "bmatrix", "lodf", "ptdf", "reactivep", "fastdecoupled"],
 7: ["thermal", "emergency", "loadfactor", "relay", "lodf", "ptdf", "bridge", "cascade", "superposition"],
 8: ["lnrepair", "listsched", "queue", "lambda", "little", "wq", "batcharrival", "discipline", "leadtime", "gantt"],
 9: ["montecarlo", "se", "lln", "clt", "expected", "quantile", "indicator"],
 10: ["pathsurv", "logweight", "dijkstra", "supply", "redundancy", "sharpP", "weightedcorr", "series"],
 11: ["upstream", "areacollapse", "fiveregion", "hindcast", "distribution", "ufls", "montecarlo"],
}
G.append(dict(id="pga_ref", t="最大加速度 PGA", en="peak ground acceleration", m="地震動の加速度波形の絶対値の最大。", u="g(重力加速度 9.8 m/s²)または gal(cm/s²)。1 g = 980 gal。", r="脆弱性曲線の入力。PGV から換算する。", w="短周期に敏感で機器の損傷と相性が良い。建物は PGV・震度の方が合う。", pat=["PGA"]))
ids = {g["id"] for g in G}
for n, lst in SLIDE_TERMS.items():
    for t in lst:
        assert t in ids, (n, t)

# ── 既存文の誤り 1 か所(鉄塔の空間相関の向き) ─────────────────────────────
old = "<li>各基の独立を仮定(地震動は空間相関するので過小評価の方向)</li>"
new = "<li>各基の独立を仮定(地震動は空間相関するので「どれか 1 基」の確率は大きく出る。安全側の過大評価)</li>"
assert old in html; html = html.replace(old, new)

# ── 枚数 12 → 13 ────────────────────────────────────────────────────────
html = re.sub(r'<span class="no">(\d+) / 12</span>', r'<span class="no">\1 / 13</span>', html)
assert html.count("/ 13</span>") == 12

# ── 13 枚目(用語集)の器 ───────────────────────────────────────────────
gloss_section = '''<section class="slide" id="sl13">
<div class="hd"><span class="no">13 / 13</span><h2>用語集 — 1 つずつ</h2></div>
<p class="note" style="margin:0">板書ごとに、意味・単位と典型値・この解析での役割・注意。本文の下線つきの語にカーソルを載せても同じ説明が出る。</p>
<div id="glossary"></div>
</section>
'''
anchor = "</section>\n</div>\n<script>"
assert anchor in html
html = html.replace(anchor, "</section>\n" + gloss_section + "</div>\n<script>", 1)

# ── CSS ────────────────────────────────────────────────────────────────
css = '''
.terms{border:1px solid var(--line);border-radius:8px;background:#fbfaf5;padding:8px 12px}
.terms-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:12.5px;color:var(--muted)}
.terms-head b{color:var(--ink);font-family:"Zen Kaku Gothic New",sans-serif;font-size:13px}
.terms-head .btn{margin-left:auto;padding:3px 9px;font-size:12px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.chip{font:inherit;font-size:12.5px;padding:3px 10px;border-radius:14px;border:1px solid #cfd8e3;background:#fff;color:var(--acc);cursor:pointer}
.chip[aria-expanded="true"]{background:var(--acc);color:#fff;border-color:var(--acc)}
.tcards{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:8px;margin-top:8px}
.tcards:empty{display:none}
.tcard{border:1px solid var(--line);border-radius:8px;background:#fff;padding:9px 11px;font-size:13px;line-height:1.55}
.tcard h4{margin:0 0 4px;font-family:"Zen Kaku Gothic New",sans-serif;font-size:14px;color:var(--ink)}
.tcard h4 small{font-family:"IBM Plex Mono",monospace;font-weight:400;color:var(--muted);font-size:11px;margin-left:6px}
.tcard dl{margin:0;display:grid;grid-template-columns:5.2em 1fr;gap:2px 8px}
.tcard dt{color:var(--muted);font-size:11.5px;padding-top:2px}.tcard dd{margin:0}
.tcard dd.w{color:#8a3b2c}
button.term{font:inherit;background:none;border:0;padding:0;margin:0;color:inherit;cursor:help;border-bottom:1px dotted var(--acc);color:var(--acc)}
button.term:hover,button.term:focus-visible{background:#e8f0f7;outline:none;border-bottom-style:solid}
.pop{position:absolute;z-index:60;max-width:340px;background:#fff;border:1px solid var(--line);border-radius:8px;box-shadow:0 6px 24px rgba(30,30,20,.16);padding:9px 11px;font-size:12.5px;line-height:1.5;color:var(--ink)}
.pop h5{margin:0 0 3px;font-size:13px;font-family:"Zen Kaku Gothic New",sans-serif}.pop h5 small{font-family:"IBM Plex Mono",monospace;font-weight:400;color:var(--muted);font-size:10.5px;margin-left:5px}
.pop p{margin:2px 0}.pop .u{color:var(--muted)}.pop .go{display:inline-block;margin-top:4px;font-size:11.5px;color:var(--acc)}
.gl-group{margin:10px 0 4px}.gl-group h3{font-family:"Zen Kaku Gothic New",sans-serif;font-size:15px;margin:0 0 6px;padding-left:8px;border-left:4px solid var(--acc)}
@media (max-width:760px){.tcard dl{grid-template-columns:1fr}.tcards{grid-template-columns:1fr}}
'''
html = html.replace("@media (prefers-reduced-motion: reduce){.anim{transition:none}}\n</style>", "@media (prefers-reduced-motion: reduce){.anim{transition:none}}\n" + css + "</style>", 1)
assert ".tcard{" in html

# ── JS ─────────────────────────────────────────────────────────────────
js = '''
// ── 用語の解析(板書ごとのパネル・本文のポップオーバー・用語集)
const GLOSS=''' + json.dumps({g["id"]: g for g in G}, ensure_ascii=False) + ''';
const SLIDE_TERMS=''' + json.dumps({str(k): v for k, v in SLIDE_TERMS.items()}, ensure_ascii=False) + ''';
const esc=s=>String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;");
function tcard(id){const g=GLOSS[id];return `<div class="tcard" id="tc-${id}"><h4>${esc(g.t)}<small>${esc(g.en)}</small></h4><dl><dt>意味</dt><dd>${esc(g.m)}</dd><dt>単位・典型値</dt><dd>${esc(g.u)}</dd><dt>この解析では</dt><dd>${esc(g.r)}</dd><dt>注意</dt><dd class="w">${esc(g.w)}</dd></dl></div>`;}
Object.entries(SLIDE_TERMS).forEach(([n,ids])=>{const sec=document.getElementById("sl"+n);const board=sec&&sec.querySelector(".tex");if(!board)return;
 const box=document.createElement("div");box.className="terms";box.innerHTML=`<div class="terms-head"><b>この板書の用語 ${ids.length} 語</b><span>クリックで 1 つずつ開く</span><button class="btn" type="button" data-all="0">すべて開く</button></div><div class="chips">${ids.map(id=>`<button class="chip" type="button" data-t="${id}" aria-expanded="false">${esc(GLOSS[id].t)}</button>`).join("")}</div><div class="tcards"></div>`;
 board.insertAdjacentElement("afterend",box);
 const cards=box.querySelector(".tcards");
 const toggle=(id,on)=>{const chip=box.querySelector(`.chip[data-t="${id}"]`);const ex=cards.querySelector(`#tc-${id}`);const want=on??!ex;if(want&&!ex){cards.insertAdjacentHTML("beforeend",tcard(id));}if(!want&&ex)ex.remove();chip.setAttribute("aria-expanded",want?"true":"false");};
 box.querySelectorAll(".chip").forEach(c=>c.addEventListener("click",()=>toggle(c.dataset.t)));
 const all=box.querySelector("[data-all]");all.addEventListener("click",()=>{const on=all.dataset.all!=="1";ids.forEach(id=>toggle(id,on));all.dataset.all=on?"1":"0";all.textContent=on?"すべて閉じる":"すべて開く";});
 box._toggle=toggle;});
// 用語集(13 枚目)
(function(){const g=document.getElementById("glossary");if(!g)return;const titles={};document.querySelectorAll(".slide").forEach(s=>{const h=s.querySelector("h2");if(h)titles[s.id]=h.textContent;});
 let s="";const seen=new Set();Object.entries(SLIDE_TERMS).forEach(([n,ids])=>{const fresh=ids.filter(id=>!seen.has(id));if(!fresh.length)return;s+=`<div class="gl-group"><h3>${n} ${esc(titles["sl"+n]||"")}</h3><div class="tcards" style="margin-top:0">${fresh.map(id=>{seen.add(id);return tcard(id).replace(`id="tc-${id}"`,`id="gl-${id}"`);}).join("")}</div></div>`;});
 g.innerHTML=s;})();
// 本文の用語にポップオーバー(MathJax の後で、数式の外だけ)
const pop=document.createElement("div");pop.className="pop";pop.hidden=true;pop.setAttribute("role","tooltip");document.body.appendChild(pop);
let popTimer=null;
function showPop(btn){const g=GLOSS[btn.dataset.t];if(!g)return;pop.innerHTML=`<h5>${esc(g.t)}<small>${esc(g.en)}</small></h5><p>${esc(g.m)}</p><p class="u">${esc(g.u)}</p><p>この解析では: ${esc(g.r)}</p><a class="go" href="#gl-${btn.dataset.t}">用語集で見る →</a>`;pop.hidden=false;
 const r=btn.getBoundingClientRect();const pw=Math.min(340,window.innerWidth-24);pop.style.maxWidth=pw+"px";let x=window.scrollX+r.left,y=window.scrollY+r.bottom+6;if(x+pw>window.scrollX+window.innerWidth-12)x=window.scrollX+window.innerWidth-12-pw;pop.style.left=x+"px";pop.style.top=y+"px";}
function hidePop(){pop.hidden=true;}
function linkTerms(){const skip=el=>el.closest("mjx-container,svg,script,style,.terms,.lab,.pop,.hd,.refs,#glossary,.tcard");
 Object.entries(SLIDE_TERMS).forEach(([n,ids])=>{const sec=document.getElementById("sl"+n);if(!sec)return;
  ids.forEach(id=>{const pats=GLOSS[id].pat||[];const walker=document.createTreeWalker(sec,NodeFilter.SHOW_TEXT,{acceptNode:t=>{if(!t.nodeValue.trim()||skip(t.parentElement))return NodeFilter.FILTER_REJECT;return NodeFilter.FILTER_ACCEPT;}});
   let node;outer:while((node=walker.nextNode())){for(const p of pats){const k=node.nodeValue.indexOf(p);if(k<0)continue;const before=node.nodeValue.slice(0,k),after=node.nodeValue.slice(k+p.length);const btn=document.createElement("button");btn.type="button";btn.className="term";btn.dataset.t=id;btn.textContent=p;btn.setAttribute("aria-describedby","");
    const par=node.parentNode;par.insertBefore(document.createTextNode(before),node);par.insertBefore(btn,node);node.nodeValue=after;break outer;}}});});
 document.querySelectorAll("button.term").forEach(b=>{b.addEventListener("mouseenter",()=>{clearTimeout(popTimer);showPop(b);});b.addEventListener("mouseleave",()=>{popTimer=setTimeout(hidePop,250);});b.addEventListener("focus",()=>showPop(b));b.addEventListener("blur",()=>{popTimer=setTimeout(hidePop,250);});
  b.addEventListener("click",e=>{e.preventDefault();const sec=b.closest(".slide");const box=sec&&sec.querySelector(".terms");if(box&&box._toggle){box._toggle(b.dataset.t,true);const c=box.querySelector(`#tc-${b.dataset.t}`);if(c)c.scrollIntoView({block:"nearest",behavior:"smooth"});}hidePop();});});
 pop.addEventListener("mouseenter",()=>clearTimeout(popTimer));pop.addEventListener("mouseleave",()=>{popTimer=setTimeout(hidePop,250);});
 document.addEventListener("keydown",e=>{if(e.key==="Escape")hidePop();});}
(window.MathJax&&MathJax.startup&&MathJax.startup.promise?MathJax.startup.promise:Promise.resolve()).then(linkTerms).catch(linkTerms);
'''
anchor2 = "// ── slide navigation"
assert anchor2 in html
html = html.replace(anchor2, js + "\n" + anchor2, 1)
open(DST, "w", encoding="utf-8").write(html)
print("terms", len(G), "slides", len(SLIDE_TERMS), "bytes", len(html.encode("utf-8")))
