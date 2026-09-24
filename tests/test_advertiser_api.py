"""带广告主约束排期接口：正确响应、稳定错误码、整批拒绝不留部分结果，
且旧 /api/v1/schedules 行为逐项不变。"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

URL = "/api/v1/schedules/advertiser-constrained"


def test_happy_path_returns_ids_advertisers_profit():
    payload = {
        "limit": 2,
        "windows": [
            {"id": "a", "start": 0, "end": 10, "value": 10, "advertiser": "X"},
            {"id": "b", "start": 10, "end": 20, "value": 20, "advertiser": "Y"},
        ],
    }
    r = client.post(URL, json=payload)
    assert r.status_code == 200, r.text
    assert r.json() == {"profit": 30, "ids": ["a", "b"], "advertisers": ["X", "Y"]}


def test_adjacent_same_advertiser_constraint_via_api():
    payload = {
        "limit": 2,
        "windows": [
            {"id": "a", "start": 0, "end": 10, "value": 10, "advertiser": "X"},
            {"id": "b", "start": 10, "end": 20, "value": 20, "advertiser": "X"},
        ],
    }
    r = client.post(URL, json=payload)
    assert r.status_code == 200
    assert r.json() == {"profit": 20, "ids": ["b"], "advertisers": ["X"]}


def test_empty_windows_allowed():
    r = client.post(URL, json={"limit": 1, "windows": []})
    assert r.status_code == 200
    assert r.json() == {"profit": 0, "ids": [], "advertisers": []}


def _codes(payload):
    r = client.post(URL, json=payload)
    assert r.status_code == 422, r.text
    body = r.json()
    assert body["error"]["code"] == "VALIDATION_FAILED"
    return r, [(d["code"], tuple(d["loc"])) for d in body["error"]["details"]]


def test_invalid_advertiser_identifiers_rejected():
    # 空标识
    _, codes = _codes(
        {"limit": 1, "windows": [
            {"id": "a", "start": 0, "end": 1, "value": 0, "advertiser": ""}]}
    )
    assert ("INVALID_VALUE", ("windows", 0, "advertiser")) in codes
    # 非字符串（含 bool 冒充、null）
    for bad in (1, True, None):
        _, codes = _codes(
            {"limit": 1, "windows": [
                {"id": "a", "start": 0, "end": 1, "value": 0, "advertiser": bad}]}
        )
        assert any(
            loc == ("windows", 0, "advertiser") for _, loc in codes
        ), (bad, codes)
    # 缺 advertiser 字段
    _, codes = _codes(
        {"limit": 1, "windows": [{"id": "a", "start": 0, "end": 1, "value": 0}]}
    )
    assert ("MISSING_FIELD", ("windows", 0, "advertiser")) in codes


def test_too_many_advertisers_rejected_as_whole():
    windows = [
        {"id": f"w{j}", "start": j * 10, "end": j * 10 + 5, "value": 1,
         "advertiser": f"adv{j}"}
        for j in range(9)
    ]
    r, codes = _codes({"limit": 2, "windows": windows})
    assert ("TOO_MANY_ADVERTISERS", ("windows",)) in codes
    d = r.json()["error"]["details"][0]
    assert d["params"] == {"max_advertisers": 8, "actual": 9}
    # 恰好 8 个不同广告主合法
    ok = client.post(URL, json={"limit": 2, "windows": windows[:8]})
    assert ok.status_code == 200, ok.text


def test_mode_specific_caps():
    # limit 上限 20（旧模式为 50，互不影响）
    _, codes = _codes({"limit": 21, "windows": []})
    assert codes == [("OUT_OF_RANGE", ("limit",))]
    _, codes = _codes({"limit": 0, "windows": []})
    assert codes == [("OUT_OF_RANGE", ("limit",))]
    # 窗口上限 2000
    windows = [
        {"id": f"w{j}", "start": j, "end": j + 1, "value": 0, "advertiser": "X"}
        for j in range(2001)
    ]
    r, codes = _codes({"limit": 1, "windows": windows})
    assert ("TOO_MANY_WINDOWS", ("windows",)) in codes
    assert r.json()["error"]["details"][0]["params"] == {
        "max_windows": 2000,
        "actual": 2001,
    }


def test_shared_window_errors_reused():
    # 重复 id、start >= end、多余字段：与旧模式同一稳定错误码
    _, codes = _codes(
        {"limit": 1, "windows": [
            {"id": "x", "start": 0, "end": 1, "value": 1, "advertiser": "X"},
            {"id": "x", "start": 2, "end": 3, "value": 1, "advertiser": "Y"},
        ]}
    )
    assert ("DUPLICATE_ID", ("windows",)) in codes
    _, codes = _codes(
        {"limit": 1, "windows": [
            {"id": "x", "start": 5, "end": 5, "value": 1, "advertiser": "X"}]}
    )
    assert ("INVALID_INTERVAL", ("windows", 0)) in codes
    _, codes = _codes(
        {"limit": 1, "windows": [
            {"id": "x", "start": 0, "end": 1, "value": 1, "advertiser": "X",
             "extra": 1}]}
    )
    assert ("EXTRA_FIELD", ("windows", 0, "extra")) in codes


def test_invalid_batch_leaves_no_partial_result():
    # 整批拒绝：非法请求后服务无状态，后续合法请求结果不受任何影响
    bad = {"limit": 1, "windows": [
        {"id": "a", "start": 0, "end": 1, "value": 1, "advertiser": ""}]}
    assert client.post(URL, json=bad).status_code == 422
    good = {"limit": 1, "windows": [
        {"id": "a", "start": 0, "end": 1, "value": 42, "advertiser": "X"}]}
    r = client.post(URL, json=good)
    assert r.status_code == 200
    assert r.json() == {"profit": 42, "ids": ["a"], "advertisers": ["X"]}


def test_maximum_size_batch_via_api():
    # 最大规模 2000 窗 / 8 广告主 / limit 20，已知唯一规范最优
    windows = [
        {"id": f"w{j}", "start": j * 10, "end": j * 10 + 10, "value": 1,
         "advertiser": f"adv{j % 8}"}
        for j in range(2000)
    ]
    r = client.post(URL, json={"limit": 20, "windows": windows})
    assert r.status_code == 200, r.text[:500]
    body = r.json()
    assert body["profit"] == 20
    assert body["ids"] == [f"w{j}" for j in range(20)]
    assert body["advertisers"] == [f"adv{j % 8}" for j in range(20)]
    # 可重算：再请求一次逐字节一致
    r2 = client.post(URL, json={"limit": 20, "windows": windows})
    assert r2.json() == body


def test_original_endpoint_unchanged():
    # 旧接口请求/响应形态不变：不接受 advertiser 字段，响应无 advertisers
    r = client.post(
        "/api/v1/schedules",
        json={
            "limit": 2,
            "windows": [
                {"id": "a", "start": 0, "end": 10, "value": 10},
                {"id": "b", "start": 10, "end": 20, "value": 20},
            ],
        },
    )
    assert r.status_code == 200
    assert r.json() == {"profit": 30, "ids": ["a", "b"]}
    r = client.post(
        "/api/v1/schedules",
        json={
            "limit": 1,
            "windows": [{"id": "a", "start": 0, "end": 1, "value": 1,
                         "advertiser": "X"}],
        },
    )
    assert r.status_code == 422
    codes = [d["code"] for d in r.json()["error"]["details"]]
    assert "EXTRA_FIELD" in codes
    # 旧接口 limit 上限仍是 50（不是新模式的 20）
    r = client.post("/api/v1/schedules", json={"limit": 50, "windows": []})
    assert r.status_code == 200
    r = client.post("/api/v1/schedules", json={"limit": 51, "windows": []})
    assert r.status_code == 422
