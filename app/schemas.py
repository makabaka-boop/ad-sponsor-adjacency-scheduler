"""Pydantic v2 请求模型：求解之前完成全部整体校验。

任何类型错误、越界、start >= end、重复 id、多余字段、窗口数超限，
以及广告主模式下的非法标识 / 广告主数超限，都会在进入动态规划之前
被拒绝，不会产生任何部分结果（服务本身无状态）。

自定义违规使用 PydanticCustomError，其 type 即稳定错误码：
  - start_end_order_error
  - duplicate_window_id
  - too_many_windows
  - too_many_advertisers
"""

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    model_validator,
)
from pydantic_core import PydanticCustomError

from .advertiser_solver import (
    MAX_ADVERTISER_LIMIT,
    MAX_ADVERTISER_WINDOWS,
    MAX_ADVERTISERS,
)
from .solver import MAX_LIMIT, MAX_TIME_MS, MAX_VALUE, MAX_WINDOWS

ERR_START_END_ORDER = "start_end_order_error"
ERR_DUPLICATE_ID = "duplicate_window_id"
ERR_TOO_MANY_WINDOWS = "too_many_windows"
ERR_TOO_MANY_ADVERTISERS = "too_many_advertisers"

# 错误信息里重复 id 最多列出的数量，避免响应体无界
_REPORT_LIMIT = 100


def _raise_if_duplicates(windows) -> None:
    """窗口 id 唯一性检查（两种模式共用，错误输出完全一致）。"""
    seen: set[str] = set()
    dup: set[str] = set()
    for w in windows:
        if w.id in seen:
            dup.add(w.id)
        else:
            seen.add(w.id)
    if not dup:
        return
    dup_list = sorted(dup)
    shown = dup_list[:_REPORT_LIMIT]
    extra = len(dup_list) - len(shown)
    detail = ", ".join(shown)
    if extra:
        detail += f" (and {extra} more)"
    raise PydanticCustomError(
        ERR_DUPLICATE_ID,
        "duplicate window id(s): {ids}",
        {"ids": detail, "duplicate_count": len(dup_list)},
    )


class Window(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: StrictStr = Field(min_length=1)
    start: StrictInt = Field(ge=0, le=MAX_TIME_MS)
    end: StrictInt = Field(ge=0, le=MAX_TIME_MS)
    value: StrictInt = Field(ge=0, le=MAX_VALUE)

    @model_validator(mode="after")
    def _validate_half_open(self):
        if self.start >= self.end:
            raise PydanticCustomError(
                ERR_START_END_ORDER,
                "start must be strictly smaller than end (half-open [start, end))",
                {"start": self.start, "end": self.end},
            )
        return self


class Batch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: StrictInt = Field(ge=1, le=MAX_LIMIT)
    windows: list[Window]

    @model_validator(mode="after")
    def _validate_batch(self):
        if len(self.windows) > MAX_WINDOWS:
            raise PydanticCustomError(
                ERR_TOO_MANY_WINDOWS,
                "number of windows exceeds the maximum of {max_windows}",
                {"max_windows": MAX_WINDOWS, "actual": len(self.windows)},
            )
        _raise_if_duplicates(self.windows)
        return self


class AdvertiserWindow(Window):
    """带广告主标识的窗口；id/start/end/value 语义与旧模式完全一致。"""

    advertiser: StrictStr = Field(min_length=1)


class AdvertiserBatch(BaseModel):
    """带广告主约束的排期批次：规模上限独立于旧模式（2000 窗 / 8 主 / 20 条）。"""

    model_config = ConfigDict(extra="forbid")

    limit: StrictInt = Field(ge=1, le=MAX_ADVERTISER_LIMIT)
    windows: list[AdvertiserWindow]

    @model_validator(mode="after")
    def _validate_batch(self):
        if len(self.windows) > MAX_ADVERTISER_WINDOWS:
            raise PydanticCustomError(
                ERR_TOO_MANY_WINDOWS,
                "number of windows exceeds the maximum of {max_windows}",
                {"max_windows": MAX_ADVERTISER_WINDOWS, "actual": len(self.windows)},
            )
        _raise_if_duplicates(self.windows)

        advertisers = {w.advertiser for w in self.windows}
        if len(advertisers) > MAX_ADVERTISERS:
            raise PydanticCustomError(
                ERR_TOO_MANY_ADVERTISERS,
                "number of distinct advertisers exceeds the maximum of {max_advertisers}",
                {"max_advertisers": MAX_ADVERTISERS, "actual": len(advertisers)},
            )
        return self
