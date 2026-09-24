"""限额加权区间调度（weighted interval scheduling with a cardinality limit）。

输入窗口已由上层（Pydantic 模型）校验：id 唯一、字段合法。

编号规则（题目要求）：窗口按 (end, start, 输入下标) 升序排列后编号 1..n。

递推式
------
令 p(i) = |{ j < i : end_j <= start_i }|，即编号 i 之前与 i 不冲突的窗口数
（半开区间 [start, end)，end == start 不算冲突）。

    dp[i][k] = max(
        dp[i - 1][k],            # 排除编号 i
        dp[p(i)][k - 1] + v_i,   # 纳入编号 i
    )

基例：dp[0][k] = 0，dp[i][0] = 0。
同分裁决：仅当“纳入”严格大于“排除”时才纳入，相等时固定排除编号 i，
从而总收益相同的方案有唯一清单（数值上等价于在最优子集中取编号掩码最小者）。

回溯：i = n, k = limit；若 dp[i][k] == dp[i-1][k] 则 i--，
否则选中 i、k--、i = p(i)。

复杂度：排序 O(n log n)，前驱 O(n log n)，动态规划 O(n * limit)，
回溯 O(n)；收益使用滚动 int64 层，选择决策使用位图。
最大总收益 50 * 10^9 = 5e10，int64 足够。
"""

from array import array
from bisect import bisect_right

MAX_LIMIT = 50
MAX_WINDOWS = 200_000
MAX_TIME_MS = 86_400_000
MAX_VALUE = 1_000_000_000


def solve(limit, windows):
    """求唯一最优清单。

    参数
    ----
    limit: 最多选择的窗口数（1..50，由上层校验）。
    windows: [(id, start, end, value), ...]，保持输入顺序。

    返回
    ----
    (profit, ids)：总收益，以及按窗口编号升序排列的 id 列表。
    """
    n = len(windows)

    # 编号：按 (end, start, 输入下标) 升序
    order = sorted(range(n), key=lambda j: (windows[j][2], windows[j][1], j))
    ids = [None] * n
    starts = [0] * n
    ends = [0] * n
    values = [0] * n
    for pos, src in enumerate(order):
        wid, st, en, va = windows[src]
        ids[pos] = wid
        starts[pos] = st
        ends[pos] = en
        values[pos] = va

    # p(i)：ends 已随编号升序，直接二分统计 end_j <= start_i 的前驱个数。
    # 半开端点相接不冲突，故用 bisect_right（<= 而非 <）。
    # 注意 starts 并不随编号单调，不能用单向游标批量扫描。
    pred = array("I", [0]) * n
    for i, start in enumerate(starts):
        pred[i] = bisect_right(ends, start, 0, i)

    # 按选择数量转置 DP；只保留上一收益层，并用位图保存回溯决策。
    # 每个窗口都要填：k > i 时 dp[i][k] = dp[i][i]，并非零值。
    stride = n + 1
    previous = array("q", [0]) * stride
    choices = bytearray((n * limit + 7) // 8)

    for k in range(1, limit + 1):
        current = array("q", [0]) * stride
        layer_offset = (k - 1) * n
        for i in range(1, n + 1):
            vi = values[i - 1]
            take = previous[pred[i - 1]] + vi
            skip = current[i - 1]
            bit_index = layer_offset + i - 1
            # 位图直接记录获胜分支，回溯无需保留全部收益层。
            # 同分裁决：仅严格更优才纳入，相等时固定排除编号 i。
            if take > skip:
                current[i] = take
                choices[bit_index >> 3] |= 1 << (bit_index & 7)
            else:
                current[i] = skip
        previous = current

    # 按位图回溯规范清单。
    chosen = []
    i = n
    k = limit
    while i > 0 and k > 0:
        bit_index = (k - 1) * n + i - 1
        took = choices[bit_index >> 3] & (1 << (bit_index & 7))
        if not took:
            i -= 1
            continue
        i -= 1
        chosen.append(i)
        k -= 1
        i = pred[i]
    chosen.reverse()

    return int(previous[n]), [ids[pos] for pos in chosen]
