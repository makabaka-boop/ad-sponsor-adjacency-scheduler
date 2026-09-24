"""带广告主约束的限额加权区间调度。

在旧模式（`app.solver`）的窗口、报价与数量上限语义之上增加一条合同约束：
**实际播出的相邻两条广告不得来自同一广告主**。相邻按“已选序列的播出顺序”
判定——空档与未选中的窗口都不算隔断，因此约束只依赖上一个*已选*窗口的
广告主。本模块把该状态纳入动态规划，直接求约束下的最优；绝不先算无约束
最优清单再删去连续同主广告（那会丢失更优的可行组合）。

编号规则与旧模式一致：窗口按 (end, start, 输入下标) 升序编号 1..n；
前驱 p(i) = |{ j < i : end_j <= start_i }|，半开区间端点相接不冲突。

状态
----
广告主编码为 1..A（A <= 8），0 表示“尚未选择任何窗口”。

    dp[i][k][a] = 只看前 i 个编号、至多选 k 条、且最后一条已选窗口的
                  广告主为 a（a=0 表示一条都未选）时的最优收益。

转移（编号 i 的广告主为 c_i、报价 v_i）：

    排除 i：dp[i-1][k][a]
    纳入 i（结果状态 a == c_i）：max_{a' != c_i} dp[p(i)][k-1][a'] + v_i

同分裁决：每个状态记录 (收益, 达到该收益的编号选择掩码最小者)，按
(收益降序, 掩码升序) 字典序取优。掩码第 i-1 位对应编号 i，与旧模式
“同分固定排除当前编号”的裁决数值等价。纳入转移给所有候选加上相同的
v_i、或上相同的 bit(i-1)（该位高于前驱掩码的所有位），保字典序，
因此逐状态取优是精确的，最终答案在 a 上再取一次同一字典序，
全局清单唯一且可重算。

复杂度：状态 (n+1) * (limit+1) * (A+1)；每个 (i, k) 只扫描一次 a'
（O(A)）再填 A+1 个状态，总时间 O(n * limit * A)，
空间 O(n * limit * A)（掩码为 Python 大整数，n <= 2000）。
最大总收益 20 * 10^9 = 2e10，int64 足够。
"""

from array import array
from bisect import bisect_right

MAX_ADVERTISER_LIMIT = 20
MAX_ADVERTISER_WINDOWS = 2_000
MAX_ADVERTISERS = 8


def solve_advertiser(limit, windows):
    """求广告主约束下的唯一最优清单。

    参数
    ----
    limit: 最多选择的窗口数（1..20，由上层校验）。
    windows: [(id, start, end, value, advertiser), ...]，保持输入顺序。

    返回
    ----
    (profit, ids, advertisers)：总收益、按窗口编号升序排列的 id 列表，
    以及与 ids 平行的广告主列表。
    """
    n = len(windows)

    # 编号：按 (end, start, 输入下标) 升序，与旧模式同一规则。
    order = sorted(range(n), key=lambda j: (windows[j][2], windows[j][1], j))
    ids = [None] * n
    starts = [0] * n
    ends = [0] * n
    values = [0] * n
    adv_code = [0] * n  # 编号 pos+1 的广告主编码（1..A）
    code_of = {}
    names = []
    for pos, src in enumerate(order):
        wid, st, en, va, adv = windows[src]
        ids[pos] = wid
        starts[pos] = st
        ends[pos] = en
        values[pos] = va
        code = code_of.get(adv)
        if code is None:
            code = len(code_of) + 1
            code_of[adv] = code
            names.append(adv)
        adv_code[pos] = code

    # p(i)：ends 已随编号升序；半开端点相接不冲突，用 bisect_right（<=）。
    pred = array("I", [0]) * n
    for i, start in enumerate(starts):
        pred[i] = bisect_right(ends, start, 0, i)

    width = len(code_of) + 1  # 状态维度 a：0..A
    kstride = (limit + 1) * width
    vals = array("q", [0]) * ((n + 1) * kstride)
    masks = [0] * ((n + 1) * kstride)  # 每状态达到最优收益的最小编号掩码

    for i in range(1, n + 1):
        base_i = i * kstride
        base_prev = base_i - kstride
        base_p = pred[i - 1] * kstride
        ci = adv_code[i - 1]
        vi = values[i - 1]
        bit = 1 << (i - 1)
        for k in range(1, limit + 1):
            row_i = base_i + k * width
            row_prev = base_prev + k * width
            row_p = base_p + (k - 1) * width
            # 纳入编号 i：上一个已选广告主 a' 不能等于 c_i（空档与未选
            # 窗口不算隔断，所以只需排除 a' == c_i，与中间隔多少窗口无关）。
            # 同分取子掩码最小者；bit(i-1) 对所有候选相同，无需参与比较。
            take_v = -1
            take_m = 0
            for ap in range(width):
                if ap == ci:
                    continue
                v = vals[row_p + ap] + vi
                m = masks[row_p + ap]
                if v > take_v or (v == take_v and m < take_m):
                    take_v = v
                    take_m = m
            take_m |= bit
            for a in range(width):
                skip_v = vals[row_prev + a]
                skip_m = masks[row_prev + a]
                # 纳入只可能落在状态 a == c_i；同分按掩码最小裁决。
                if a == ci and (
                    take_v > skip_v or (take_v == skip_v and take_m < skip_m)
                ):
                    vals[row_i + a] = take_v
                    masks[row_i + a] = take_m
                else:
                    vals[row_i + a] = skip_v
                    masks[row_i + a] = skip_m

    # 最终答案：dp[n][limit][a] 在 a 上取 (收益降序, 掩码升序) 最优。
    row = n * kstride + limit * width
    best_v = -1
    best_m = 0
    for a in range(width):
        v = vals[row + a]
        m = masks[row + a]
        if v > best_v or (v == best_v and m < best_m):
            best_v = v
            best_m = m

    chosen_ids = []
    chosen_advs = []
    for pos in range(n):
        if best_m >> pos & 1:
            chosen_ids.append(ids[pos])
            chosen_advs.append(names[adv_code[pos] - 1])
    return best_v, chosen_ids, chosen_advs
