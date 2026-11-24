"""新案例候选问答的编审校验。

候选文件使用 JSON，使教员可以在不改正式 TSV 的情况下反复编修。校验
通过后，再把案件和题目追加进 ``materials``，并把证据表合并到
``editorial/annotations.json``。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .repository import Pack
from .review import _finding
from .timeutil import clock_minutes


def load_candidate(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check_candidate(
    candidate: dict[str, Any] | str | Path,
    pack: Pack | None = None,
) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        candidate = load_candidate(candidate)  # type: ignore[arg-type]

    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    case_rows = candidate.get("cases", [])
    cases = {row.get("id"): row for row in case_rows}
    question = candidate.get("question", {})
    qid = question.get("id", "<候选题>")

    if not case_rows:
        blockers.append(_finding("missing_cases", "至少要提供一条带条件的工单/案件文字"))
    for case_id, case in cases.items():
        if not case_id or not case.get("text"):
            blockers.append(_finding("bad_case", "案件必须有 id 和 text", case=case_id))

    basis = question.get("basis", [])
    if isinstance(basis, str):
        basis = [part for part in basis.split("|") if part]
    if not basis:
        blockers.append(_finding("missing_basis", "题目必须引用至少一条学员当场可见材料"))
    for case_id in basis:
        if case_id not in cases:
            blockers.append(_finding("unknown_basis_case", f"basis 引用了候选包中不存在的 {case_id}"))

    options = question.get("options", [])
    option_ids = {option.get("id") for option in options}
    if len(options) < 2:
        blockers.append(_finding("too_few_options", "至少保留两个选项；歧义题应修编而不是删选项"))
    if len(option_ids) != len(options):
        blockers.append(_finding("duplicate_option_id", "选项 id 不能重复"))

    key = question.get("key")
    if key not in option_ids:
        blockers.append(_finding("key_not_in_options", f"key={key!r} 不在选项 id 中"))

    ability = question.get("ability")
    if pack and ability not in pack.annotations.get("abilities", {}):
        blockers.append(_finding("unknown_agreed_ability", f"能力 {ability!r} 未在 annotations.abilities 约定"))
    elif not ability:
        blockers.append(_finding("missing_ability", "题目必须登记拟签发的能力项"))

    global_rules = pack.annotations.get("rules", {}) if pack else {}
    local_rules = candidate.get("rules", {})
    rules = {**global_rules, **local_rules}
    global_clues = pack.annotations.get("clues", {}) if pack else {}
    local_clues = candidate.get("clues", {})
    clues = {**global_clues, **local_clues}
    misread_codes = pack.annotations.get("misread_codes", {}) if pack else {}
    misread_codes = {**misread_codes, **candidate.get("misread_codes", {})}

    for clue_id in question.get("clue_ids", []):
        if clue_id not in clues:
            blockers.append(_finding("unknown_clue", f"线索 {clue_id} 既不在总表也不在候选 clues 中"))

    as_of = question.get("as_of")
    contexts = question.get("decision_contexts", [])
    if not contexts:
        blockers.append(_finding("missing_decision_context", "必须给出至少一个答案上下文和证据摘录"))

    supported_options: set[Any] = set()
    for context in contexts:
        context_id = context.get("id", "<未命名上下文>")
        supported = context.get("supported_option")
        if supported not in option_ids:
            blockers.append(_finding(
                "context_option_missing",
                f"上下文 {context_id} 支持的选项 {supported!r} 不存在",
            ))
            continue
        supported_options.add(supported)

        for rule_id in context.get("rule_ids", []):
            if rule_id not in rules:
                blockers.append(_finding("unknown_rule", f"引用未知规则 {rule_id}", rule_id=rule_id))

        support = context.get("support", [])
        if not support:
            blockers.append(_finding("missing_support", f"上下文 {context_id} 没有证据摘录"))
        for evidence in support:
            case_id = evidence.get("case")
            quote = evidence.get("quote", "")
            case_text = cases.get(case_id, {}).get("text", "")
            if case_id not in cases:
                blockers.append(_finding("unknown_evidence_case", f"证据引用未知案件 {case_id}"))
            elif quote not in case_text:
                blockers.append(_finding(
                    "quote_not_in_visible_text",
                    f"证据摘录不是 {case_id} 原文连续文字：{quote}",
                ))
            evidence_at = evidence.get("at")
            if as_of and evidence_at and clock_minutes(evidence_at) > clock_minutes(as_of):
                blockers.append(_finding(
                    "later_evidence_used",
                    f"{context_id} 使用了 {as_of} 之后的证据 {evidence_at}",
                ))

    unique_option = next(iter(supported_options)) if len(supported_options) == 1 else None
    if len(supported_options) > 1:
        blockers.append(_finding(
            "non_unique_answer",
            "不同可允许上下文支持不同选项；必须补齐对象/工位/时点条件后重审，不能删选项。",
            supported_options=sorted(supported_options, key=str),
            ambiguity_witness=question.get("ambiguity_witness"),
        ))
    elif unique_option is not None and key != unique_option:
        blockers.append(_finding(
            "key_mismatch",
            f"key={key!r}，证据唯一支持 {unique_option!r}",
        ))

    readings = question.get("distractor_readings", {})
    if unique_option is not None and not blockers:
        for option in options:
            option_id = option.get("id")
            if option_id == unique_option:
                continue
            code = readings.get(str(option_id)) or readings.get(option_id)
            if not code:
                blockers.append(_finding(
                    "distractor_without_actual_misread",
                    f"干扰项 {option_id} 必须登记对应的实际误读编码",
                ))
            elif code not in misread_codes:
                blockers.append(_finding("unknown_misread_code", f"未知误读编码 {code}"))

    if question.get("requires_new_lineage", True) and not question.get("lineage"):
        warnings.append(_finding(
            "lineage_recommended",
            "新考核题建议声明新的 lineage，避免与练习题共用可记忆案例族。",
        ))

    return {
        "candidate": qid,
        "ok": not blockers,
        "decision": "approved" if not blockers else "returned",
        "blockers": blockers,
        "warnings": warnings,
    }
