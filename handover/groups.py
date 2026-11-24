"""题组、判断线索与学员暴露历史。"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .repository import Pack, split_pipe


def memory_group_of(pack: Pack, qid: str) -> str | None:
    group = pack.profile(qid).get("memory_group")
    if group:
        return group
    for group_id, group in pack.annotations.get("memory_groups", {}).items():
        if qid in group.get("questions", []):
            return group_id
    return None


def memory_group_members(pack: Pack, qid: str) -> set[str]:
    group_id = memory_group_of(pack, qid)
    if not group_id:
        return {qid}
    group = pack.annotations.get("memory_groups", {}).get(group_id, {})
    return set(group.get("questions", [])) | {qid}


def questions_in_memory_group(pack: Pack, group_id: str) -> list[str]:
    return list(pack.annotations.get("memory_groups", {}).get(group_id, {}).get("questions", []))


def clue_ids_of(pack: Pack, qid: str) -> list[str]:
    return list(pack.profile(qid).get("clue_ids", []))


def questions_sharing_clue(pack: Pack, qid: str) -> dict[str, list[str]]:
    target_clues = set(clue_ids_of(pack, qid))
    result: dict[str, list[str]] = {}
    if not target_clues:
        return result
    for row in pack.questions:
        other = row["id"]
        if other == qid:
            continue
        shared = target_clues & set(clue_ids_of(pack, other))
        for clue in shared:
            result.setdefault(clue, []).append(other)
    return result


def clue_index(pack: Pack) -> dict[str, list[str]]:
    index: dict[str, list[str]] = defaultdict(list)
    for row in pack.questions:
        for clue in clue_ids_of(pack, row["id"]):
            index[clue].append(row["id"])
    return dict(index)


def learner_exposures(
    pack: Pack, learner_id: str, at: str | None = None
) -> list[dict[str, Any]]:
    """合并所有有时间/无时间的“已见到题”来源。

    ``at`` 为 ISO 时间上界。无时间的 ``learners.seen`` / ``sheet`` 是来件
    已声明事实，按入场前已知处理；练习回执和现场签到则使用各自时间。
    """
    learner = pack.learner(learner_id)
    exposures: list[dict[str, Any]] = []

    def allowed(time: str | None) -> bool:
        return at is None or time is None or time <= at

    for qid in split_pipe(learner.get("seen", "")):
        if allowed(None):
            exposures.append({
                "learner": learner_id, "question": qid, "time": None,
                "kind": "declared_seen", "source": "learners.tsv:seen",
                "detail": "学员表声明已公开见到",
            })

    for qid in split_pipe(learner.get("sheet", "")):
        if allowed(None):
            exposures.append({
                "learner": learner_id, "question": qid, "time": None,
                "kind": "actual_sheet", "source": "learners.tsv:sheet",
                "detail": "学员表保留的考核实际材料",
            })

    for row in pack.study_log:
        if row["learner"] != learner_id:
            continue
        seen_at = row["seen_at"]
        if not allowed(seen_at):
            continue
        exposures.append({
            "learner": learner_id, "question": row["question"], "time": seen_at,
            "kind": "practice", "source": row["id"],
            "detail": row["note"],
        })

    for row in pack.sittings:
        if row["learner"] != learner_id:
            continue
        seated = row["seated"]
        if not allowed(seated):
            continue
        for qid in split_pipe(row["handed"]):
            exposures.append({
                "learner": learner_id, "question": qid, "time": seated,
                "kind": "assessment", "source": row["id"],
                "detail": row["medium"], "sitting_id": row["id"],
            })

    exposures.sort(key=lambda item: (item["time"] or "", item["source"], item["question"]))
    return exposures


def exposed_question_ids(exposures: list[dict[str, Any]]) -> set[str]:
    return {item["question"] for item in exposures}


def memory_blocked_questions(
    pack: Pack, exposed_qids: set[str]
) -> dict[str, list[dict[str, Any]]]:
    """返回因本人已见而同记忆组不可用于独立考核的题及原因。"""
    blocked: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for seen_qid in sorted(exposed_qids):
        for candidate in memory_group_members(pack, seen_qid):
            if candidate == seen_qid:
                blocked[candidate].append({
                    "seen_question": seen_qid,
                    "relation": "exact",
                    "memory_group": memory_group_of(pack, candidate),
                })
            else:
                blocked[candidate].append({
                    "seen_question": seen_qid,
                    "relation": "memory_variant",
                    "memory_group": memory_group_of(pack, candidate),
                })
    return dict(blocked)


def exposed_case_ids(pack: Pack, exposed_qids: set[str]) -> set[str]:
    cases: set[str] = set()
    for qid in exposed_qids:
        cases.update(pack.basis_ids(qid))
    return cases


def case_family_of_question(pack: Pack, qid: str) -> set[str]:
    families = set(pack.basis_ids(qid))
    group_id = memory_group_of(pack, qid)
    if group_id:
        families.update(pack.annotations.get("memory_groups", {})
                        .get(group_id, {}).get("case_families", []))
    return families
