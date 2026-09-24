"""带广告主约束求解器：穷举交叉校验最优值与平局、零报价、相接窗口、
前驱跨越多条未选窗口、确定性。"""

import random

import pytest

from app.advertiser_solver import solve_advertiser
from app.solver import solve


def brute_force_advertiser(limit, windows):
    """枚举子集的参考实现（仅用于小 n 交叉校验）。

    返回 (最大收益, 规范 id 列表, 规范广告主列表)；规范裁决与旧模式一致：
    总收益最大者中，按 (end, start, 输入下标) 编号的选择掩码最小者。
    """
    n = len(windows)
    order = sorted(range(n), key=lambda j: (windows[j][2], windows[j][1], j))
    best = (0, 0)  # 空集恒可行：收益 0、掩码 0
    for mask in range(1 << n):
        if mask.bit_count() > limit:
            continue
        chosen = [order[i] for i in range(n) if mask >> i & 1]
        chosen_sorted = sorted(chosen, key=lambda j: (windows[j][2], windows[j][1]))
        ok = True
        for a, b in zip(chosen_sorted, chosen_sorted[1:]):
            # 半开区间重叠；或播出序列相邻两条同广告主（空档/未选不算隔断）
            if windows[a][2] > windows[b][1] or windows[a][4] == windows[b][4]:
                ok = False
                break
        if not ok:
            continue
        profit = sum(windows[j][3] for j in chosen)
        if profit > best[0] or (profit == best[0] and mask < best[1]):
            best = (profit, mask)
    profit, mask = best
    ids = [windows[order[i]][0] for i in range(n) if mask >> i & 1]
    advs = [windows[order[i]][4] for i in range(n) if mask >> i & 1]
    return profit, ids, advs


def test_empty_batch():
    assert solve_advertiser(1, []) == (0, [], [])
    assert solve_advertiser(20, []) == (0, [], [])


def test_touching_endpoints_are_not_overlap():
    # 端点相接不冲突：不同广告主可相接连播
    windows = [("a", 0, 10, 10, "X"), ("b", 10, 20, 20, "Y")]
    assert solve_advertiser(2, windows) == (30, ["a", "b"], ["X", "Y"])
    # 真正重叠（9 < 10）即使广告主不同也不能同选
    windows = [("a", 0, 10, 10, "X"), ("b", 9, 20, 20, "Y")]
    assert solve_advertiser(2, windows) == (20, ["b"], ["Y"])


def test_touching_same_advertiser_still_forbidden():
    # 端点相同不算重叠，但相邻同主仍被合同禁止：只能取报价高者
    windows = [("a", 0, 10, 10, "X"), ("b", 10, 20, 20, "X")]
    assert solve_advertiser(2, windows) == (20, ["b"], ["X"])


def test_gap_and_unselected_are_not_separators():
    # 空档不算隔断：两窗之间有大段空档，同主仍算相邻
    windows = [("a", 0, 10, 10, "X"), ("b", 500, 510, 20, "X")]
    assert solve_advertiser(2, windows) == (20, ["b"], ["X"])
    # 中间夹一条已选的其它广告主窗口才算隔断
    windows = [
        ("a", 0, 10, 10, "X"),
        ("m", 20, 30, 1, "Y"),
        ("b", 40, 50, 10, "X"),
    ]
    assert solve_advertiser(3, windows) == (21, ["a", "m", "b"], ["X", "Y", "X"])


def test_not_filtered_from_unconstrained_optimum():
    # 无约束最优 a+b=20 含相邻同主；若算完再删只剩 10。
    # 约束最优是 a+c=19（换一条广告），必须由 DP 直接求出。
    windows = [
        ("a", 0, 10, 10, "X"),
        ("b", 10, 20, 10, "X"),
        ("c", 10, 20, 9, "Y"),
    ]
    plain = [(w[0], w[1], w[2], w[3]) for w in windows]
    assert solve(2, plain) == (20, ["a", "b"])  # 旧模式不受广告主约束
    assert solve_advertiser(2, windows) == (19, ["a", "c"], ["X", "Y"])


def test_predecessor_spans_multiple_unselected_windows():
    # w1 与 w4 之间隔着多条未选窗口，二者仍是播出序列相邻，同主不能同选
    windows = [
        ("w1", 0, 10, 10, "X"),
        ("w2", 10, 20, 1, "Y"),
        ("w3", 20, 30, 1, "Y"),
        ("w4", 30, 40, 10, "X"),
    ]
    # {w1,w4} 非法（相邻同主 X），{w2,w3} 非法（相邻同主 Y）；
    # {w1,w2,w4} 与 {w1,w3,w4} 同分 21，掩码裁决取编号掩码最小的 {w1,w2,w4}。
    assert solve_advertiser(4, windows) == (21, ["w1", "w2", "w4"], ["X", "Y", "X"])


def test_zero_values():
    # 全零报价：任何纳入都只增大掩码，规范最优为空清单
    windows = [("z1", 0, 10, 0, "X"), ("z2", 10, 20, 0, "Y")]
    assert solve_advertiser(2, windows) == (0, [], [])
    # 零报价窗口可作为两条同主广告之间的已选隔断进入最优清单
    windows = [
        ("a", 0, 10, 5, "X"),
        ("z", 10, 20, 0, "Y"),
        ("b", 20, 30, 5, "X"),
    ]
    assert solve_advertiser(3, windows) == (10, ["a", "z", "b"], ["X", "Y", "X"])


def test_tie_keeps_lowest_number_regardless_of_input_order():
    # 同 end 时 start 小者编号小；互斥同分保留它，与输入顺序无关
    w1 = ("a", 0, 10, 10, "X")
    w2 = ("b", 5, 10, 10, "Y")
    assert solve_advertiser(1, [w1, w2]) == (10, ["a"], ["X"])
    assert solve_advertiser(1, [w2, w1]) == (10, ["a"], ["X"])


def test_tie_same_end_and_start_uses_input_index():
    # end、start 都相同：编号按输入下标，同分保留先出现者
    w1 = ("first", 0, 10, 7, "X")
    w2 = ("second", 0, 10, 7, "Y")
    assert solve_advertiser(1, [w1, w2]) == (7, ["first"], ["X"])
    assert solve_advertiser(1, [w2, w1]) == (7, ["second"], ["Y"])


def test_result_sorted_by_number_with_parallel_advertisers():
    # 乱序输入：ids 按编号升序，advertisers 与 ids 平行
    windows = [
        ("late", 50, 60, 9, "X"),
        ("mid", 20, 30, 9, "Y"),
        ("early", 0, 10, 9, "Z"),
    ]
    assert solve_advertiser(3, windows) == (
        27,
        ["early", "mid", "late"],
        ["Z", "Y", "X"],
    )


@pytest.mark.parametrize("seed", range(300))
def test_brute_force_random_small(seed):
    """小输入穷举：同时核对最优值与同分平局下的唯一清单。"""
    rng = random.Random(seed)
    n = rng.randint(0, 7)
    limit = rng.randint(1, 4)
    pool = ["A", "B", "C"][: rng.randint(1, 3)]
    windows = []
    for j in range(n):
        s = rng.randint(0, 12)
        e = rng.randint(s + 1, 15)
        windows.append((f"id{j}", s, e, rng.randint(0, 5), rng.choice(pool)))
    assert solve_advertiser(limit, windows) == brute_force_advertiser(limit, windows)


@pytest.mark.parametrize("seed", range(100))
def test_all_distinct_advertisers_matches_unconstrained(seed):
    """每窗一个不同广告主时约束不起作用，结果须与旧求解器一致。"""
    rng = random.Random(10_000 + seed)
    n = rng.randint(0, 7)
    limit = rng.randint(1, 4)
    plain = []
    tagged = []
    for j in range(n):
        s = rng.randint(0, 12)
        e = rng.randint(s + 1, 15)
        v = rng.randint(0, 5)
        plain.append((f"id{j}", s, e, v))
        tagged.append((f"id{j}", s, e, v, f"adv{j}"))
    profit, ids, advs = solve_advertiser(limit, tagged)
    assert (profit, ids) == solve(limit, plain)
    assert advs == [f"adv{i[2:]}" for i in ids]


def test_maximum_size_known_optimum():
    # 最大规模 2000 窗 / 8 广告主 / limit 20：全部相接不冲突、同价，
    # 相邻广告主循环相异，唯一规范最优为编号最小的 20 条。
    windows = [
        (f"w{j}", j * 10, j * 10 + 10, 1, f"adv{j % 8}") for j in range(2000)
    ]
    profit, ids, advs = solve_advertiser(20, windows)
    assert profit == 20
    assert ids == [f"w{j}" for j in range(20)]
    assert advs == [f"adv{j % 8}" for j in range(20)]


def test_determinism_across_repeated_runs():
    rng = random.Random(7)
    windows = []
    for j in range(200):
        s = rng.randint(0, 900)
        windows.append(
            (f"i{j}", s, s + rng.randint(1, 100), rng.randint(0, 100), f"adv{j % 8}")
        )
    first = solve_advertiser(20, windows)
    for _ in range(3):
        assert solve_advertiser(20, windows) == first
