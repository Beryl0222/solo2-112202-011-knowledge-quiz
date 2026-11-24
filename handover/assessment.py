"""按学员实际时间线评估独立证据并签发/撤回能力。"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .groups import (
    clue_ids_of,
    learner_exposures,
    memory_group_members,
)
from .repository import Pack, split_pipe
from .review import corrections_for_question, review_question


def _prior_memory_exposures(
    pack: Pack, learner_id: str, qid: str, seated: str
) -> list[dict[str, Any]]:
    related = memory_group_members(pack, qid)
    target_cases = set(pack.basis_ids(qid))
    conflicts: list[dict[str, Any]] = []
    for exposure in learner_exposures(pack, learner_id):
        seen_qid = exposure["question"]
        in_memory_group = seen_qid in related
        shared_cases = target_cases & set(pack.basis_ids(seen_qid))
        if not in_memory_group and not shared_cases:
            continue

        kind = exposure["kind"]
        prior = False
        if kind == "practice":
            prior = bool(exposure["time"] and exposure["time"] < seated)
        elif kind == "assessment":
            # 同一场签到记录自身不算“入场前接触”；只取更早场次。
            prior = bool(exposure["time"] and exposure["time"] < seated)
        elif kind == "declared_seen":
            prior = True
        if not prior:
            continue

        conflict = dict(exposure)
        if seen_qid == qid:
            conflict["relation"] = "exact"
        elif in_memory_group:
            conflict["relation"] = "memory_variant"
        else:
            conflict["relation"] = "same_case"
        if shared_cases:
            conflict["shared_cases"] = sorted(shared_cases)
        conflicts.append(conflict)
    return conflicts


def assess_learner(pack: Pack, learner_id: str, at: str | None = None) -> dict[str, Any]:
    learner = pack.learner(learner_id)
    needed = split_pipe(learner["needs"])
    responses = pack.response_map(learner_id)
    response_rows: list[dict[str, Any]] = []

    # 以签到表的实际 handed/time/medium 为准；学员表 responses 保留原答案。
    sittings = [row for row in pack.sittings if row["learner"] == learner_id]
    for sitting in sittings:
        seated = sitting["seated"]
        if at and seated > at:
            continue
        for qid in split_pipe(sitting["handed"]):
            response_rows.append(_assess_response(
                pack, learner_id, qid, responses.get(qid),
                sitting["id"], seated, sitting["medium"], at,
            ))

    # 若只有 learner.sheet/responses 而没有签到，仍不能丢题或丢答案。
    for qid in split_pipe(learner.get("sheet", "")):
        if any(qid == item["question"] for item in response_rows):
            continue
        response_rows.append(_assess_response(
            pack, learner_id, qid, responses.get(qid),
            None, None, "学员表 sheet/responses，无签到时间", at,
        ))
    for qid, selected in responses.items():
        if any(qid == item["question"] for item in response_rows):
            continue
        response_rows.append(_assess_response(
            pack, learner_id, qid, selected,
            None, None, "学员表 responses，无对应 sheet/签到时间", at,
        ))

    _apply_shared_clue_rule(response_rows)

    abilities: dict[str, dict[str, Any]] = {}
    for ability in needed:
        evidence = [
            row for row in response_rows
            if ability in row["covered_abilities"] and row["counts_as_evidence"]
        ]
        mechanical = [
            row for row in response_rows
            if ability in row["covered_abilities"] and row["matched_proposed_key"]
        ]
        withdrawn = [
            row for row in mechanical
            if row.get("answer_status") != "valid"
        ]
        defective = [
            row for row in response_rows
            if ability in row["covered_abilities"] and row.get("answer_status") != "valid"
        ]
        memory_failed = [
            row for row in mechanical
            if row["independence"] != "independent"
        ]
        has_answer_failure = bool(withdrawn or defective)
        has_independence_failure = bool(memory_failed)
        if evidence:
            status = "granted"
            decision = "可签发/继续签发"
            reason = "至少有一份当前有效、未被记忆题组污染且在线索组内不重复的独立证据。"
        elif has_answer_failure and has_independence_failure:
            status = "answer_and_independence_failed"
            decision = "答案失效与独立性失效分别记录，安排新材料重考"
            reason = "既有入场前记忆题组污染，也有后续答案缺陷；两项问题不能互相抵消。"
        elif withdrawn:
            status = "evidence_withdrawn"
            decision = "撤回原签发并安排重考"
            reason = "唯一机械得分所依赖的作答已被后续更正/语义缺陷击穿，更正后不能继续证明该能力。"
        elif defective:
            status = "answer_defect_needs_retake"
            decision = "旧答案不再可判，安排重考"
            reason = "题目在学员所见版本中并不唯一；原对错都不能证明该能力，应使用未暴露的有效材料重考。"
        elif memory_failed:
            status = "independence_failed"
            decision = "不能作为独立证据签发"
            reason = "作答虽可能正确，但学员入场前已接触同记忆题组，能靠重认案例作答。"
        elif mechanical:
            status = "no_surviving_evidence"
            decision = "暂不签发，安排重考"
            reason = "没有当前有效且独立的证据。"
        else:
            status = "not_assessed"
            decision = "缺少考核证据"
            reason = "没有可用于该能力的有效答对记录。"

        correction_events = []
        for row in defective:
            for effect in row.get("correction_effects", []):
                if effect.get("kind") == "answer_defect":
                    correction_events.append({
                        "correction_id": effect["correction_id"],
                        "logged": effect["logged"],
                        "question": row["question"],
                    })
        correction_events.sort(key=lambda event: event["logged"])

        abilities[ability] = {
            "status": status,
            "decision": decision,
            "reason": reason,
            "issuable_from": min(
                (event["seated"] for event in evidence if event["seated"]),
                default=None,
            ),
            "retake_or_withdrawal_after": (
                correction_events[0]["logged"] if correction_events and not evidence else None
            ),
            "correction_events": correction_events,
            "evidence": [
                {
                    "question": row["question"],
                    "sitting": row["sitting_id"],
                    "seated": row["seated"],
                    "clue_ids": row["clue_ids"],
                }
                for row in evidence
            ],
            "withdrawn_answers": [row["question"] for row in withdrawn],
            "defective_answers": [row["question"] for row in defective],
            "independence_failed_answers": [row["question"] for row in memory_failed],
        }

    return {
        "learner": learner_id,
        "needed": needed,
        "at": at or "current",
        "responses": response_rows,
        "abilities": abilities,
        "exposures": learner_exposures(pack, learner_id, at=at),
    }


def _assess_response(
    pack: Pack,
    learner_id: str,
    qid: str,
    selected: int | None,
    sitting_id: str | None,
    seated: str | None,
    medium: str,
    at: str | None,
) -> dict[str, Any]:
    question = pack.question(qid)
    profile = pack.profile(qid)
    review = review_question(pack, qid, at=at)
    key = int(question["key"])
    covered_abilities = [question["ability"]]
    for extra_ability in profile.get("also_covers", []):
        if extra_ability not in covered_abilities:
            covered_abilities.append(extra_ability)
    matched = selected == key
    prior_conflicts = (
        _prior_memory_exposures(pack, learner_id, qid, seated or "")
        if seated else []
    )
    independence = "memory_recognition" if prior_conflicts else "independent"

    correction_effects = corrections_for_question(pack, qid, at=at)
    answer_defects = [
        finding for finding in review["blockers"]
        if finding["code"] in {
            "non_unique_answer", "active_correction_answer_defect",
            "key_mismatch", "missing_semantic_profile",
            "later_evidence_used", "quote_not_in_visible_text",
        }
    ]
    answer_status = "defective" if answer_defects else "valid"

    # 先给初值；_apply_shared_clue_rule 会把同场同线索的重复证据降级。
    initial_counts = bool(
        selected is not None
        and matched
        and independence == "independent"
        and answer_status == "valid"
    )
    return {
        "learner": learner_id,
        "sitting_id": sitting_id,
        "seated": seated,
        "medium": medium,
        "question": qid,
        "ability": question["ability"],
        "covered_abilities": covered_abilities,
        "selected": selected,
        "proposed_key": key,
        "matched_proposed_key": matched,
        "clue_ids": clue_ids_of(pack, qid),
        "clue_evidence": [],
        "prior_exposure_conflicts": prior_conflicts,
        "independence": independence,
        "answer_status": answer_status,
        "answer_defects": answer_defects,
        "correction_effects": correction_effects,
        "initial_counts": initial_counts,
        "counts_as_evidence": initial_counts,
        "shared_clue_representative": None,
        "duplicate_shared_clues": [],
        "notes": list(profile.get("medium_review_notes", [])),
    }


def _apply_shared_clue_rule(rows: list[dict[str, Any]]) -> None:
    """同一场考核内，同一判断线索只保留一份独立证据。

    重复判定在线索级进行：若一道题还提供另一条不重复线索，它仍可作为
    该线索的证据；只有当此题的所有线索都只是同场重复时，才整体不计。
    """
    groups: dict[tuple[str | None, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if not row["initial_counts"]:
            continue
        clues = row["clue_ids"] or ["__unclassified__"]
        for clue in clues:
            groups[(row["sitting_id"], clue)].append(row)

    representatives: dict[tuple[str | None, str], str] = {}
    for key, grouped in groups.items():
        representatives[key] = grouped[0]["question"]
        grouped[0]["shared_clue_representative"] = key[1]

    for row in rows:
        if not row["initial_counts"]:
            row["counts_as_evidence"] = False
            continue
        clue_results = []
        has_independent_clue = False
        for clue in row["clue_ids"] or ["__unclassified__"]:
            representative = representatives[(row["sitting_id"], clue)]
            is_independent = representative == row["question"]
            has_independent_clue = has_independent_clue or is_independent
            clue_results.append({
                "clue": clue,
                "representative_question": representative,
                "counts_once": is_independent,
            })
            if not is_independent:
                row["duplicate_shared_clues"].append(clue)
        row["clue_evidence"] = clue_results
        row["counts_as_evidence"] = has_independent_clue
        if row["duplicate_shared_clues"] and not has_independent_clue:
            rep = representatives[(row["sitting_id"], row["duplicate_shared_clues"][0])]
            row["duplicate_shared_clue"] = row["duplicate_shared_clues"][0]
            row["evidence_downgrade_reason"] = (
                f"与 {rep} 在同一场考核共享线索 {row['duplicate_shared_clues'][0]}，"
                "该线索只计一次独立证据。"
            )
        elif row["duplicate_shared_clues"]:
            row["shared_clue_note"] = (
                "部分线索与同场题共享，共享线索只计一次；本题另有独立线索。"
            )


def assess_all(pack: Pack, at: str | None = None) -> dict[str, dict[str, Any]]:
    return {row["id"]: assess_learner(pack, row["id"], at=at) for row in pack.learners}


def correction_impact(pack: Pack, correction_id: str) -> dict[str, Any]:
    correction = pack.correction(correction_id)
    qid = correction["ref"]
    current = assess_all(pack)
    affected: list[dict[str, Any]] = []
    for learner_id, assessment in current.items():
        for response in assessment["responses"]:
            if response["question"] != qid:
                continue
            ability = response["ability"]
            ability_decision = assessment["abilities"][ability]
            affected.append({
                "learner": learner_id,
                "sitting": response["sitting_id"],
                "seated": response["seated"],
                "selected": response["selected"],
                "proposed_key": response["proposed_key"],
                "matched_proposed_key": response["matched_proposed_key"],
                "independence": response["independence"],
                "ability": ability,
                "ability_status_after_correction": ability_decision["status"],
                "still_proven_by": ability_decision["evidence"],
                "medium": response["medium"],
            })
    return {
        "correction": correction,
        "effect": pack.annotations.get("correction_effects", {}).get(correction_id, {}),
        "affected_responses": affected,
    }
