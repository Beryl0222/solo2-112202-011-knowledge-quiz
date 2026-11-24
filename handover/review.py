"""编卷前语义核对。

这里不假装能从任意中文自由文本中自动发现所有歧义；评审把证据摘录、
适用规则和可接受上下文结构化后，本模块负责核对：

* 拟选答案是否被当场文字中的证据支持；
* 在所有已登记/可补充的上下文里是否仍只有一个答案；
* 干扰项是否对应已编码的实际误读；
* 证据是否晚于被问时点；
* 后续更正是否已使旧题/旧作答失效。
"""
from __future__ import annotations

from typing import Any

from .repository import Pack
from .timeutil import clock_minutes
from .visibility import visible_materials


def _finding(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **extra}


def correction_effect(pack: Pack, correction_id: str) -> dict[str, Any]:
    row = pack.correction(correction_id)
    effect = dict(pack.annotations.get("correction_effects", {}).get(correction_id, {}))
    effect.setdefault("correction_id", correction_id)
    effect.setdefault("logged", row["logged"])
    effect.setdefault("question", effect.get("question") or row["ref"])
    effect.setdefault("scope", row["scope"])
    return effect


def corrections_for_question(
    pack: Pack, qid: str, at: str | None = None
) -> list[dict[str, Any]]:
    result = []
    for row in pack.corrections:
        if row["ref"] != qid:
            continue
        if at is not None and row["logged"] > at:
            continue
        result.append(correction_effect(pack, row["id"]))
    return result


def review_question(
    pack: Pack, qid: str, at: str | None = None
) -> dict[str, Any]:
    row = pack.question(qid)
    profile = pack.profile(qid)
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []

    options = pack.option_pairs(qid)
    option_ids = {number for number, _ in options}
    try:
        key = int(row["key"])
    except (TypeError, ValueError):
        key = None
        blockers.append(_finding("bad_key", "key 不是整数选项号", key=row.get("key")))
    if key is not None and key not in option_ids:
        blockers.append(_finding("key_out_of_range", "拟选 key 不在现有选项中", key=key))

    ability = row["ability"]
    ability_info = pack.annotations.get("abilities", {}).get(ability)
    if not ability_info:
        blockers.append(_finding("unknown_ability", f"能力 {ability} 未在约定能力表中登记"))
    elif not ability_info.get("agreed", False):
        blockers.append(_finding("ability_not_agreed", f"能力 {ability} 尚未约定签发标准"))

    clue_ids = profile.get("clue_ids", [])
    clue_table = pack.annotations.get("clues", {})
    for clue_id in clue_ids:
        if clue_id not in clue_table:
            blockers.append(_finding("unknown_clue", f"判断线索 {clue_id} 未登记"))

    if not profile:
        blockers.append(_finding(
            "missing_semantic_profile",
            "缺少编审证据表：无法证明答案唯一，须补上下文、证据摘录和误读编码后再用。",
        ))

    as_of = profile.get("as_of")
    contexts = profile.get("decision_contexts", [])
    if profile and not contexts:
        blockers.append(_finding("no_decision_context", "没有任何可核对的答案上下文"))

    supported_by_context: list[tuple[str, int]] = []
    for context in contexts:
        context_id = context.get("id", "<未命名上下文>")
        supported = context.get("supported_option")
        if supported not in option_ids:
            blockers.append(_finding(
                "context_option_missing",
                f"上下文 {context_id} 支持的选项 {supported!r} 不存在",
                context=context_id,
            ))
            continue
        supported_by_context.append((context_id, int(supported)))

        for rule_id in context.get("rule_ids", []):
            if rule_id not in pack.annotations.get("rules", {}):
                blockers.append(_finding(
                    "unknown_rule", f"上下文 {context_id} 引用未知规则 {rule_id}",
                    context=context_id, rule_id=rule_id,
                ))

        for quote_ref in context.get("support", []):
            case_id = quote_ref["case"]
            case_row = pack.case(case_id)
            quote = quote_ref["quote"]
            evidence.append({"context": context_id, **quote_ref})
            if quote not in case_row["text"]:
                blockers.append(_finding(
                    "quote_not_in_visible_text",
                    f"{qid}/{context_id} 的证据摘录不是 {case_id} 原文中的连续文字",
                    case=case_id, quote=quote,
                ))
            evidence_at = quote_ref.get("at")
            if as_of and evidence_at and clock_minutes(evidence_at) is not None:
                if clock_minutes(evidence_at) > clock_minutes(as_of):
                    blockers.append(_finding(
                        "later_evidence_used",
                        f"上下文 {context_id} 使用了 {as_of} 之后的证据 {evidence_at}",
                        context=context_id, evidence_at=evidence_at, as_of=as_of,
                    ))

    supported_options = {option for _, option in supported_by_context}
    unique_answer: int | None = None
    if len(supported_options) > 1:
        witness = profile.get("ambiguity_witness", "不同已允许上下文支持不同选项。")
        blockers.append(_finding(
            "non_unique_answer",
            "拟选答案不能从当场文字唯一推出；补入未被排除的背景后答案会翻转。应回编修并固定条件，不能删选项盖过歧义。",
            supported_by_context=supported_by_context,
            repair_direction=profile.get("repair_direction")
            or "补齐题干/现场材料中的对象、工位和时点；保留全部选项并重新编审。",
            ambiguity_witness=witness,
        ))
    elif len(supported_options) == 1:
        unique_answer = next(iter(supported_options))
        if key is not None and key != unique_answer:
            blockers.append(_finding(
                "key_mismatch",
                f"拟选 key={key}，但证据唯一支持 option_{unique_answer}",
                key=key, supported_option=unique_answer,
            ))

    misread_table = pack.annotations.get("misread_codes", {})
    readings = profile.get("distractor_readings", {})
    if unique_answer is not None and not blockers:
        for option_number, _text in options:
            if option_number == unique_answer:
                continue
            code = readings.get(str(option_number)) or readings.get(option_number)
            if not code:
                blockers.append(_finding(
                    "distractor_without_actual_misread",
                    f"干扰项 option_{option_number} 未登记它对应的实际误读；不能只靠似是而非的表述充数。",
                    option=option_number,
                ))
            elif code not in misread_table:
                blockers.append(_finding(
                    "unknown_misread_code",
                    f"干扰项 option_{option_number} 使用未知误读编码 {code}",
                    option=option_number, code=code,
                ))

    for note in profile.get("review_notes", []):
        warnings.append(_finding("editor_note", note))
    if profile.get("editor_scope"):
        warnings.append(_finding("interpretation_boundary", profile["editor_scope"]))

    active_corrections = corrections_for_question(pack, qid, at)
    for effect in active_corrections:
        if effect.get("kind") == "answer_defect":
            blockers.append(_finding(
                "active_correction_answer_defect",
                effect.get("repair_direction") or effect["scope"],
                correction_id=effect["correction_id"],
                logged=effect["logged"],
                scope=effect["scope"],
            ))
        elif effect.get("kind") == "relation_discovery":
            warnings.append(_finding(
                "relation_discovery_logged",
                effect["scope"],
                correction_id=effect["correction_id"],
                memory_group=effect.get("memory_group"),
            ))

    decision = "returned" if blockers else "approved"
    visibility = visible_materials(pack, qid, as_of=as_of) if as_of else None
    return {
        "question": qid,
        "ability": ability,
        "decision": decision,
        "proposed_key": key,
        "unique_supported_option": unique_answer,
        "clue_ids": clue_ids,
        "memory_group": profile.get("memory_group"),
        "as_of": as_of,
        "material_visibility": visibility,
        "blockers": blockers,
        "warnings": warnings,
        "evidence": evidence,
        "corrections": active_corrections,
    }


def review_pack(pack: Pack, at: str | None = None) -> dict[str, Any]:
    reviews = [review_question(pack, row["id"], at=at) for row in pack.questions]
    return {
        "at": at or "current",
        "total": len(reviews),
        "approved": [r["question"] for r in reviews if r["decision"] == "approved"],
        "returned": [r["question"] for r in reviews if r["decision"] == "returned"],
        "reviews": reviews,
    }
