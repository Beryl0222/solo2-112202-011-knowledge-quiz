"""时间解析与按点截断工具。"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

_CLOCK_RE = re.compile(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)")


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def clock_minutes(value: str | None) -> int | None:
    if not value:
        return None
    match = _CLOCK_RE.fullmatch(value.strip())
    if not match:
        # 允许从一段记录的开头提取，但显式字段应尽量给 HH:MM。
        found = _CLOCK_RE.search(value.strip())
        if not found:
            return None
        hour, minute = found.groups()
    else:
        hour, minute = match.groups()
    return int(hour) * 60 + int(minute)


def leading_clock(text: str) -> str | None:
    match = _CLOCK_RE.match(text.strip())
    return match.group(0) if match else None


def clock_le(left: str | None, right: str | None) -> bool:
    """比较两个 HH:MM；缺时间时不做截断，交由编审证据检查处理。"""
    lm, rm = clock_minutes(left), clock_minutes(right)
    if lm is None or rm is None:
        return False
    return lm <= rm


def is_before(a: str | None, b: str | None) -> bool:
    da, db = parse_dt(a), parse_dt(b)
    if da is None or db is None:
        return False
    return da < db
