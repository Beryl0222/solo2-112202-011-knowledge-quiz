"""在题数上限内组卷，并明确无法覆盖的能力和补考材料。"""
from __future__ import annotations

from itertools import combinations
from pathlib import Path
from typing import Any

from .candidates import check_candidate, load_candidate
from .groups import (
    case_family_of_question,
    clue_ids_of,
    exposed_case_ids,
    exposed_question_ids,
    learner_exposures,
    memory_blocked_questions,
)
from .repository import PROJECT_ROOT, Pack
from .review import review_pack


def _item_limit(pack: Pack, learner_id: str, max_items: int | None) -> int:
    if max_items is not None:
        return max_items
    raw = pack.learner(learner_id).get("max_items", "")
    if raw:
        return int(raw)
    return len(pack.needs(learner_id))


def _coverage_abilities(pack: Pack, qid: str) -> set[str]:
    abilities = {pack.question(qid)["ability"]}
    abilities.update(pack.profile(qid).get("also_covers", []))
    return abilities


def _collision_count(pack: Pack, qids: tuple[str, ...]) -> int:
    count = 0
    for i, left in enumerate(qids):
        left_clues = set(clue_ids_of(pack, left))
        for right in qids[i + 1:]:
            if left_clues & set(clue_ids_of(pack, right)):
                count += 1
    return count


def eligibility_report(
    pack: Pack,
    learner_id: str,
    strict_case_family: bool = False,
) -> dict[str, Any]:
    review = {item["question"]: item for item in review_pack(pack)["reviews"]}
    exposures = learner_exposures(pack, learner_id)
    exposed = exposed_question_ids(exposures)
    memory_blocked = memory_blocked_questions(pack, exposed)
    seen_cases = exposed_case_ids(pack, exposed)

    exposed_families: set[str] = set()
    for qid in exposed:
        try:
            exposed_families.update(case_family_of_question(pack, qid))
        except KeyError:
            # 引用完整性已由 pack_check 保证；保留防御分支。
            pass

    eligible: list[str] = []
    blocked: dict[str, dict[str, Any]] = {}
    for row in pack.questions:
        qid = row["id"]
        reasons: list[dict[str, Any]] = []
        if review[qid]["decision"] != "approved":
            reasons.append({
                "code": "review_returned",
                "messages": [b["message"] for b in review[qid]["blockers"]],
            })
        if qid in exposed:
            seen_records = [e for e in exposures if e["question"] == qid]
            reasons.append({
                "code": "already_seen",
                "records": seen_records,
            })
        elif qid in memory_blocked:
            reasons.append({
                "code": "memory_variant",
                "relations": memory_blocked[qid],
            })
        shared_cases = sorted(set(pack.basis_ids(qid)) & seen_cases)
        if shared_cases:
            reasons.append({
                "code": "seen_case",
                "shared_cases": shared_cases,
            })
        family = case_family_of_question(pack, qid)
        shared_families = sorted(family & exposed_families)
        if strict_case_family and qid not in exposed and shared_families:
            reasons.append({
                "code": "strict_case_family_exposure",
                "shared_case_families": shared_families,
            })
        if reasons:
            blocked[qid] = {"question": qid, "reasons": reasons}
        else:
            eligible.append(qid)

    return {
        "learner": learner_id,
        "exposed": sorted(exposed),
        "exposures": exposures,
        "eligible": eligible,
        "blocked": blocked,
        "strict_case_family": strict_case_family,
    }


def plan_for_learner(
    pack: Pack,
    learner_id: str,
    max_items: int | None = None,
    strict_case_family: bool = False,
    candidate_dir: Path | str | None = None,
) -> dict[str, Any]:
    needed = pack.needs(learner_id)
    limit = _item_limit(pack, learner_id, max_items)
    eligibility = eligibility_report(pack, learner_id, strict_case_family)
    eligible = eligibility["eligible"]

    by_ability: dict[str, list[str]] = {ability: [] for ability in needed}
    for qid in eligible:
        for ability in _coverage_abilities(pack, qid) & set(needed):
            by_ability[ability].append(qid)

    candidates = [qid for qid in eligible if _coverage_abilities(pack, qid) & set(needed)]
    best: tuple[Any, ...] | None = None
    best_qids: tuple[str, ...] = ()
    upper = min(limit, len(candidates))
    for size in range(0, upper + 1):
        for combo in combinations(candidates, size):
            covered: set[str] = set()
            for qid in combo:
                covered.update(_coverage_abilities(pack, qid) & set(needed))
            collisions = _collision_count(pack, combo)
            score = (-len(covered), len(combo), collisions, combo)
            if best is None or score < best:
                best = score
                best_qids = combo

    covered: set[str] = set()
    for qid in best_qids:
        covered.update(_coverage_abilities(pack, qid) & set(needed))
    missing = [ability for ability in needed if ability not in covered]

    makeup: dict[str, Any] = {}
    for ability in missing:
        usable = list(by_ability.get(ability, []))
        ready_candidates = _ready_candidates(pack, ability, candidate_dir)
        if usable:
            makeup[ability] = {
                "status": "exists_but_not_selected_within_limit",
                "next_session_materials": usable,
                "ready_candidates": ready_candidates,
                "note": "这些题当前可用；本场题数不足，应优先安排后续补考，不能用重复得分补齐。",
            }
        else:
            nearest = []
            for row in pack.questions:
                qid = row["id"]
                if row["ability"] != ability and ability not in pack.profile(qid).get("also_covers", []):
                    continue
                blocked = eligibility["blocked"].get(qid)
                nearest.append({
                    "question": qid,
                    "eligible": qid in eligible,
                    "blocked": blocked["reasons"] if blocked else [],
                    "action": _authoring_action(qid, blocked),
                })
            makeup[ability] = {
                "status": "no_unexposed_approved_material",
                "next_session_materials": [],
                "ready_candidates": ready_candidates,
                "nearest_blocked_materials": nearest,
                "note": (
                    "没有可直接用于该学员独立补考的现成题；须按未暴露的新 lineage/新文本编题并重新编审。"
                    + ("候选目录中已有通过校验、可提升的材料。" if ready_candidates else "")
                ),
            }

    selected = [_selection_reason(pack, qid, needed) for qid in best_qids]
    return {
        "learner": learner_id,
        "needed": needed,
        "item_limit": limit,
        "feasible": not missing,
        "selected_questions": list(best_qids),
        "selected": selected,
        "covered": sorted(covered),
        "missing": missing,
        "materials_by_ability": by_ability,
        "makeup_for_missing": makeup,
        "eligibility": eligibility,
        "shared_clue_collisions": _collision_count(pack, best_qids),
    }


def _ready_candidates(
    pack: Pack, ability: str, candidate_dir: Path | str | None
) -> list[dict[str, Any]]:
    if candidate_dir is None:
        return []
    directory = Path(candidate_dir)
    if not directory.exists():
        return []
    ready = []
    for path in sorted(directory.glob("*.json")):
        data = load_candidate(path)
        result = check_candidate(data, pack)
        if not result["ok"]:
            continue
        question = data.get("question", {})
        abilities = {question.get("ability"), *question.get("also_covers", [])}
        if ability not in abilities:
            continue
        display_path = str(path)
        try:
            display_path = str(path.relative_to(PROJECT_ROOT))
        except ValueError:
            pass
        ready.append({
            "candidate": result["candidate"],
            "path": display_path,
            "stem": question.get("stem", ""),
            "promote_as": question.get("id"),
            "note": "尚未进入正式 TSV；须 promote-candidate 后才能排入正式卷。",
        })
    return ready


def _selection_reason(pack: Pack, qid: str, needed: list[str]) -> dict[str, Any]:
    row = pack.question(qid)
    return {
        "question": qid,
        "ability": row["ability"],
        "covers": sorted(_coverage_abilities(pack, qid) & set(needed)),
        "clue_ids": clue_ids_of(pack, qid),
        "basis": pack.basis_ids(qid),
        "why": (
            f"{qid} 已通过编审；能力为{row['ability']}，"
            f"引用 {','.join(pack.basis_ids(qid))}，且未出现在该学员的已见题/记忆组中。"
        ),
    }


def _authoring_action(qid: str, blocked: dict[str, Any] | None) -> str:
    if not blocked:
        return "可复核后使用"
    codes = {reason["code"] for reason in blocked["reasons"]}
    if "review_returned" in codes:
        return "先按退回意见补齐条件并重新编审；旧版不得直接用于考核。"
    if "memory_variant" in codes or "already_seen" in codes:
        return "该学员已接触原题或记忆改写组；只能作为教员改编线索，须换未暴露案例。"
    if "strict_case_family_exposure" in codes:
        return "严格案例族策略下已暴露；应换 lineage 和表面情境均不同的新案。"
    return "先排除组卷阻塞原因。"


def evaluate_cohort_paper(
    pack: Pack,
    cohort_id: str,
    qids: list[str],
    strict_case_family: bool = False,
) -> dict[str, Any]:
    cohort = next(
        (item for item in pack.annotations.get("cohorts", []) if item["id"] == cohort_id),
        None,
    )
    if cohort is None:
        raise KeyError(f"未知班组/学员组 {cohort_id}")
    member_reports = {
        learner_id: evaluate_paper(pack, qids, learner_id, strict_case_family)
        for learner_id in cohort["learner_ids"]
    }
    return {
        "cohort": cohort,
        "questions": qids,
        "applicable": all(report["applicable"] for report in member_reports.values()),
        "members": member_reports,
    }


def evaluate_paper(
    pack: Pack,
    qids: list[str],
    learner_id: str | None = None,
    strict_case_family: bool = False,
) -> dict[str, Any]:
    needed = pack.needs(learner_id) if learner_id else []
    eligibility = (
        eligibility_report(pack, learner_id, strict_case_family)
        if learner_id else None
    )
    review = {item["question"]: item for item in review_pack(pack)["reviews"]}
    items = []
    blockers = []
    for qid in qids:
        item_blockers = []
        if review[qid]["decision"] != "approved":
            item_blockers.extend(b["message"] for b in review[qid]["blockers"])
        if eligibility and qid in eligibility["blocked"]:
            for reason in eligibility["blocked"][qid]["reasons"]:
                if reason["code"] != "review_returned":
                    item_blockers.append(reason["code"])
        items.append({
            "question": qid,
            "ability": pack.question(qid)["ability"],
            "clue_ids": clue_ids_of(pack, qid),
            "blockers": item_blockers,
        })
        blockers.extend(f"{qid}: {message}" for message in item_blockers)

    covered: set[str] = set()
    for qid in qids:
        covered.update(_coverage_abilities(pack, qid) & set(needed))
    missing = [ability for ability in needed if ability not in covered]
    collisions = []
    for i, left in enumerate(qids):
        clues_left = set(clue_ids_of(pack, left))
        for right in qids[i + 1:]:
            shared = clues_left & set(clue_ids_of(pack, right))
            if shared:
                collisions.append({"questions": [left, right], "shared_clues": sorted(shared)})

    return {
        "learner": learner_id,
        "questions": qids,
        "items": items,
        "needed": needed,
        "covered": sorted(covered),
        "missing": missing,
        "shared_clues": collisions,
        "applicable": not blockers and not missing,
        "blockers": blockers,
    }
