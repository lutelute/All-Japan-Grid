/* AGJ 接続編集エディタの共有レンダリングコア(全面改修 Phase5)。
 *
 * :8088 サーバ版(src/server/templates/editor.html)と Pages 静的版(docs/editor.html)で
 * 別々にハードコードされ乖離していた「島/本系統の色分け」を**単一の正**にする。
 * 物理(色の意味)は connectivity.py(Phase3)が決めた島判定に対応:
 *   本系統(その周波数島の最大成分) / 孤立変電所(deg0=線なし) / 連結サブクラスタ(deg≥1=本系統外) /
 *   鉄塔分岐(変電所でない junction)。
 *
 * 配信: Pages は docs/js/editor_core.js を相対 `js/editor_core.js` で、:8088 は app.py が
 * `/js` → docs/js を mount するので `/js/editor_core.js` で、**同一の物理ファイル**を読む
 * (コピー不要・drift不能=正が1つ)。値は :8088 の従来パレットに一致(=:8088 は見た目不変)。
 */
(function (g) {
  var AGJ_COLORS = {
    main: '#388bfd',       // 本系統(連結)
    islandIso: '#f0883e',  // 孤立変電所(deg0・線なし→繋ぐ/別系統)
    islandSub: '#a371f7',  // 連結サブクラスタ(deg≥1・本系統外=越境/鉄道/OSM欠落=終端バス)
    junction: '#c98a3a',   // 鉄塔分岐(変電所でない)
    tie: '#a371f7'         // 地域間連系(OCCTO ACタイ)
  };

  // 連結性に基づく節点色(単一の正)。n = {sub, main, deg}
  function agjNodeColor(n) {
    if (!n.sub) return AGJ_COLORS.junction;
    if (n.main) return AGJ_COLORS.main;
    return (n.deg || 0) > 0 ? AGJ_COLORS.islandSub : AGJ_COLORS.islandIso;
  }

  // 節点の分類ラベル(ツールチップ等)
  function agjNodeKind(n) {
    if (!n.sub) return '鉄塔分岐(変電所でない)';
    if (n.main) return '本系統(連結)';
    return (n.deg || 0) > 0 ? '連結(本系統外サブクラスタ/終端バス)' : '孤立(線なし)';
  }

  g.AGJ_COLORS = AGJ_COLORS;
  g.agjNodeColor = agjNodeColor;
  g.agjNodeKind = agjNodeKind;
})(typeof window !== 'undefined' ? window : this);
