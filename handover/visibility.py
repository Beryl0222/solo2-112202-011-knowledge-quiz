"""按被问时点还原学员/值班员当时可见的案件片段。"""
from __future__ import annotations

from typing import Any

from .repository import Pack
from .timeutil import clock_minutes, leading_clock


def visible_materials(
    pack: Pack, qid: str, as_of: str | None = None
) -> dict[str, Any]:
    """返回 basis 中每条案件在被问时点是否已经可见。

    样例案件没有独立时间列，时间以正文开头的 HH:MM 为准。没有时间戳的
    片段按“书面材料已在题面中”处理；若它实际是后出结论，编审应在
    profile.contrast_evidence 中说明其对照角色。
    """
    profile = pack.profile(qid)
    as_of = as_of or profile.get("as_of")
    items = []
    for case_id in pack.basis_ids(qid):
        case = pack.case(case_id)
        clock = leading_clock(case["text"])
        if as_of and clock and clock_minutes(clock) > clock_minutes(as_of):
            status = "later_record_not_visible_for_historical_judgment"
            usable = False
        else:
            status = "visible_or_undated_in_handout"
            usable = True
        items.append({
            "case": case_id,
            "record_clock": clock,
            "as_of": as_of,
            "status": status,
            "usable_for_as_of_answer": usable,
            "phase": case.get("phase"),
            "lineage": case.get("lineage"),
        })
    return {
        "question": qid,
        "as_of": as_of,
        "visible": [item["case"] for item in items if item["usable_for_as_of_answer"]],
        "later": [item["case"] for item in items if not item["usable_for_as_of_answer"]],
        "items": items,
    }
