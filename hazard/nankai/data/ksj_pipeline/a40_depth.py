"""A40_003 (津波浸水深の区分, 都道府県ごとの自由文字列) → 数値レンジと標準7区分ランク。"""
import re, math

# 標準7区分 (国交省ハザードマップポータル等で通例の区分). depth_rank は区間の下限 depth_min_m で決める
# (下限規則: 例「1m以上～3m未満」→ rank3 (1-2m) と控えめ側に付ける. depth_max_m に元の上限を残す).
RANKS = [
    (1, 0.0, 0.3),
    (2, 0.3, 1.0),
    (3, 1.0, 2.0),
    (4, 2.0, 5.0),
    (5, 5.0, 10.0),
    (6, 10.0, 20.0),
    (7, 20.0, math.inf),
]
_num = re.compile(r"(\d+(?:\.\d+)?)")  # 「0.01～0.3m」のように m が末尾にしか無い表記があるので数値のみ拾う
_Z = str.maketrans("０１２３４５６７８９．～", "0123456789.~")

def parse_depth(s):
    """returns (depth_min_m, depth_max_m or None(=open-ended), ok)"""
    if s is None:
        return (None, None, False)
    t = str(s).translate(_Z).replace(" ", "").replace("　", "")
    nums = [float(x) for x in _num.findall(t)]
    if len(nums) >= 2:
        lo, hi = min(nums[0], nums[1]), max(nums[0], nums[1])
        return (lo, hi, True)
    if len(nums) == 1:
        n = nums[0]
        if any(k in t for k in ("未満", "以下", "まで")) and not any(k in t for k in ("以上", "超", "から")):
            return (0.0, n, True)
        if any(k in t for k in ("以上", "超", "から", "～")):
            return (n, None, True)
        return (n, None, True)
    return (None, None, False)

def rank_of(lo):
    if lo is None:
        return None
    r = None
    for k, a, b in RANKS:
        if lo >= a - 1e-9:
            r = k
    return r

def rank_label(k):
    a, b = [(a, b) for kk, a, b in RANKS if kk == k][0]
    return f"{a}m以上" if b == math.inf else (f"{b}m未満" if a == 0 else f"{a}m以上{b}m未満")

if __name__ == "__main__":
    for s in ["0.01m以上 ～ 0.3m未満", "～0.3m未満", "0.3m以上 ～ 1.0m未満", "20m以上", "1m以上 ～ 3m未満",
              "3m以上 ～ 4m未満", "5m以上", "0.5m未満", "１ｍ以上～２ｍ未満", "浸水深不明", None,
              "0.01～0.3m", "0.3～1.0m", "5.0m～", "2m以上～3m未満\n", "0.3m未満"]:
        lo, hi, ok = parse_depth(s); print(repr(s), "->", lo, hi, ok, "rank", rank_of(lo))
