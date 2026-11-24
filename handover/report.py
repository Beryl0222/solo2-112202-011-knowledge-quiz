"""面向教员和评审的中文文本报告。"""
from __future__ import annotations

import json
from typing import Any

from .assessment import assess_all, correction_impact
from .planning import evaluate_paper, plan_for_learner
from .review import review_pack
from .variants import scan_variants


def _bullet_list(items: list[str], indent: str = "  - ") -> str:
    return "\n".join(f"{indent}{item}" for item in items) if items else f"{indent}（无）"


def review_text(pack) -> str:
    report = review_pack(pack)
    lines = ["# 编审核对", ""]
    lines.append(f"可用：{', '.join(report['approved']) or '无'}")
    lines.append(f"退回：{', '.join(report['returned']) or '无'}")
    lines.append("")
    for review in report["reviews"]:
        lines.append(f"## {review['question']}｜{review['ability']}｜{review['decision']}")
        if review["unique_supported_option"] is not None:
            lines.append(f"- 唯一证据支持选项：{review['unique_supported_option']}；拟选 key：{review['proposed_key']}")
        if review["clue_ids"]:
            lines.append(f"- 判断线索：{', '.join(review['clue_ids'])}")
        if review["memory_group"]:
            lines.append(f"- 记忆题组：{review['memory_group']}")
        visibility = review.get("material_visibility")
        if visibility and visibility.get("later"):
            lines.append(
                f"- 时点截断：{visibility['as_of']} 时可见 {','.join(visibility['visible'])}；"
                f"后出记录 {','.join(visibility['later'])} 不能回填当时判断"
            )
        if review["blockers"]:
            lines.append("- 退回原因：")
            for blocker in review["blockers"]:
                lines.append(f"  - [{blocker['code']}] {blocker['message']}")
                if blocker.get("repair_direction"):
                    lines.append(f"    修编方向：{blocker['repair_direction']}")
        if review["warnings"]:
            lines.append("- 提示/边界：")
            for warning in review["warnings"]:
                lines.append(f"  - [{warning['code']}] {warning['message']}")
        if not review["blockers"] and not review["warnings"]:
            lines.append("- 未发现阻断项；干扰项均登记了实际误读来源。")
        lines.append("")
    return "\n".join(lines)


def audit_text(pack, learner_id: str | None = None) -> str:
    assessments = assess_all(pack)
    if learner_id:
        assessments = {learner_id: assessments[learner_id]}
    lines = ["# 学员证据与签发核对", ""]
    for lid, assessment in assessments.items():
        lines.append(f"## {lid}｜约定能力：{'|'.join(assessment['needed'])}")
        lines.append("")
        lines.append("### 时间线")
        for exposure in assessment["exposures"]:
            when = exposure["time"] or "时间未填（按已声明入场前接触处理）"
            lines.append(
                f"- {when}｜{exposure['kind']}｜{exposure['question']}｜"
                f"{exposure['source']}｜{exposure['detail']}"
            )
        lines.append("")
        lines.append("### 作答核对")
        for response in assessment["responses"]:
            selected = "未作答" if response["selected"] is None else f"选{response['selected']}"
            lines.append(
                f"- {response['question']}（{response['sitting_id'] or '无签到'} / "
                f"{response['seated'] or '无时间'}）：{selected}，拟选 key={response['proposed_key']}，"
                f"机械匹配={response['matched_proposed_key']}，"
                f"独立性={response['independence']}，答案有效性={response['answer_status']}，"
                f"当前计为证据={response['counts_as_evidence']}"
            )
            for conflict in response["prior_exposure_conflicts"]:
                relation_label = {
                    "exact": "原题",
                    "memory_variant": "记忆改写组",
                    "same_case": "共享已见案件原文",
                }.get(conflict.get("relation"), conflict.get("relation"))
                lines.append(
                    f"  - 独立性失效：入场前已在 {conflict['time'] or '未填时间'} "
                    f"经 {conflict['source']} 见到 {conflict['question']}（{relation_label}）"
                )
            for defect in response["answer_defects"]:
                lines.append(f"  - 答案失效/缺陷：[{defect['code']}] {defect['message']}")
            if response.get("duplicate_shared_clue"):
                lines.append(f"  - 重复证据：{response['evidence_downgrade_reason']}")
            if response.get("shared_clue_note"):
                lines.append(f"  - 线索计数：{response['shared_clue_note']}")
            for note in response.get("notes", []):
                lines.append(f"  - 现场材料边界：{note}")
        lines.append("")
        lines.append("### 能力签发")
        for ability, result in assessment["abilities"].items():
            lines.append(f"- **{ability}：{result['status']}｜{result['decision']}**")
            if result.get("issuable_from"):
                lines.append(f"  - 可据当前证据签发的时间：{result['issuable_from']}")
            if result.get("retake_or_withdrawal_after"):
                lines.append(f"  - 更正后须撤回/重考的时间点：{result['retake_or_withdrawal_after']}")
            lines.append(f"  - {result['reason']}")
            if result["evidence"]:
                ev = "；".join(
                    f"{e['question']}@{e['sitting']}({','.join(e['clue_ids'])})"
                    for e in result["evidence"]
                )
                lines.append(f"  - 继续证明：{ev}")
            if result["withdrawn_answers"]:
                lines.append(f"  - 更正后撤回的答对作答：{', '.join(result['withdrawn_answers'])}")
            if result.get("defective_answers"):
                lines.append(f"  - 受题目缺陷影响、不能再判语义对错的作答：{', '.join(result['defective_answers'])}")
            if result["independence_failed_answers"]:
                lines.append(f"  - 只发生独立性失效的作答：{', '.join(result['independence_failed_answers'])}")
        lines.append("")
    return "\n".join(lines)


def plan_text(
    pack,
    learner_id: str,
    max_items: int | None = None,
    strict_case_family: bool = False,
    candidate_dir=None,
) -> str:
    plan = plan_for_learner(
        pack, learner_id, max_items=max_items,
        strict_case_family=strict_case_family,
        candidate_dir=candidate_dir,
    )
    lines = [f"# {learner_id} 组卷建议", ""]
    lines.append(
        f"题数上限={plan['item_limit']}；可行={plan['feasible']}；"
        f"选中={', '.join(plan['selected_questions']) or '无'}；"
        f"覆盖={', '.join(plan['covered']) or '无'}；缺项={', '.join(plan['missing']) or '无'}"
    )
    lines.append("")
    lines.append("## 选题理由")
    if plan["selected"]:
        for item in plan["selected"]:
            lines.append(f"- {item['why']}")
    else:
        lines.append("- 未选出题目。")
    lines.append("")
    lines.append("## 已避开的题及原因")
    for qid, blocked in plan["eligibility"]["blocked"].items():
        reason_codes = []
        for reason in blocked["reasons"]:
            if reason["code"] == "already_seen":
                reason_codes.append("本人已见过原题")
            elif reason["code"] == "memory_variant":
                seen = ",".join(x["seen_question"] for x in reason["relations"])
                reason_codes.append(f"与已见题 {seen} 同记忆组")
            elif reason["code"] == "seen_case":
                reason_codes.append("引用了本人已见过的案件原文 " + ",".join(reason["shared_cases"]))
            elif reason["code"] == "review_returned":
                reason_codes.append("编审退回/更正失效")
            elif reason["code"] == "strict_case_family_exposure":
                reason_codes.append("严格案例族已暴露")
        lines.append(f"- {qid}：{'；'.join(reason_codes)}")
    lines.append("")
    if plan["missing"]:
        lines.append("## 缺口与后续补考材料")
        for ability, makeup in plan["makeup_for_missing"].items():
            lines.append(f"### {ability}：{makeup['status']}")
            lines.append(f"- {makeup['note']}")
            if makeup["next_session_materials"]:
                lines.append(f"- 可用于后续补考：{', '.join(makeup['next_session_materials'])}")
            for candidate in makeup.get("ready_candidates", []):
                lines.append(
                    f"  - 候选库中已通过编审：{candidate['candidate']}（{candidate['path']}）；"
                    f"{candidate['note']}"
                )
            for nearest in makeup.get("nearest_blocked_materials", []):
                lines.append(f"  - 邻近材料 {nearest['question']}：{nearest['action']}")
    else:
        lines.append("约定能力已由当前卷完整覆盖；无需用重复题补分。")
    return "\n".join(lines)


def correction_impact_text(pack, correction_id: str | None = None) -> str:
    ids = [correction_id] if correction_id else [row["id"] for row in pack.corrections]
    lines = ["# 更正影响追踪", ""]
    for cid in ids:
        impact = correction_impact(pack, cid)
        correction = impact["correction"]
        lines.append(f"## {cid}｜{correction['ref']}｜录入 {correction['logged']}")
        lines.append(f"- 范围：{correction['scope']}")
        if impact["effect"]:
            lines.append(f"- 处理：{impact['effect'].get('effect')}；{impact['effect'].get('repair_direction', '')}")
        lines.append("- 受影响作答：")
        for item in impact["affected_responses"]:
            still = ", ".join(e["question"] for e in item["still_proven_by"]) or "无"
            lines.append(
                f"  - {item['learner']} / {item['sitting']} / {item['seated']}："
                f"选{item['selected']}，原key={item['proposed_key']}，"
                f"当时机械匹配={item['matched_proposed_key']}，独立性={item['independence']}；"
                f"{item['ability']}现状={item['ability_status_after_correction']}，"
                f"仍可由 {still} 证明"
            )
        lines.append("")
    return "\n".join(lines)


def variants_text(pack) -> str:
    report = scan_variants(pack)
    lines = ["# 原案变体与题组扫描", ""]
    lines.append("## 已确认记忆组")
    for group_id, group in report["explicit_memory_groups"].items():
        lines.append(f"- {group_id}：{', '.join(group['questions'])}；案例族 {', '.join(group.get('case_families', []))}")
        lines.append(f"  - {group.get('note', '')}")
    lines.append("")
    lines.append("## 已声明 lineage 聚类")
    for lineage, cases in report["declared_lineage_groups"].items():
        lines.append(f"- {lineage}：{', '.join(cases)}")
    lines.append("")
    lines.append("## 高相似案例（待教员确认）")
    for item in report["similar_cases"]:
        lines.append(f"- {item['left']}~{item['right']}：{item['similarity']}")
    if not report["similar_cases"]:
        lines.append("- 无超过阈值的自由文本相似对；改写关系以 R2/标注为准。")
    lines.append("")
    lines.append("## 否定词反事实候选")
    for item in report["negation_candidates"]:
        lines.append(f"- {item['left']}~{item['right']}（{item['kind']}）")
    if not report["negation_candidates"]:
        lines.append("- 未发现只替换否定词的高相似候选。")
    return "\n".join(lines)


def paper_text(pack, qids: list[str], learner_id: str | None = None) -> str:
    result = evaluate_paper(pack, qids, learner_id)
    title = f"卷 {','.join(qids)}" + (f" 对 {learner_id}" if learner_id else "")
    lines = [f"# {title} 的适用理由", ""]
    lines.append(f"可直接使用：{result['applicable']}")
    if result["needed"]:
        lines.append(f"约定能力：{', '.join(result['needed'])}；未覆盖：{', '.join(result['missing']) or '无'}")
    for item in result["items"]:
        lines.append(f"- {item['question']}｜{item['ability']}｜线索 {','.join(item['clue_ids']) or '未标注'}")
        for blocker in item["blockers"]:
            lines.append(f"  - 不适用：{blocker}")
    if result["shared_clues"]:
        lines.append("同场共享线索（只计一次独立证据）：")
        for pair in result["shared_clues"]:
            lines.append(f"- {pair['questions'][0]}~{pair['questions'][1]}：{', '.join(pair['shared_clues'])}")
    return "\n".join(lines)


def cohort_paper_text(pack, cohort_id: str, qids: list[str], strict: bool = False) -> str:
    from .planning import evaluate_cohort_paper

    result = evaluate_cohort_paper(pack, cohort_id, qids, strict)
    cohort = result["cohort"]
    lines = [
        f"# 班组 {cohort_id}（{cohort.get('name', '')}）使用卷 {','.join(qids)} 的理由",
        "",
        f"全组适用：{result['applicable']}",
    ]
    for learner_id, member in result["members"].items():
        lines.append(
            f"- {learner_id}：applicable={member['applicable']}；"
            f"覆盖 {','.join(member['covered']) or '无'}；"
            f"缺口 {','.join(member['missing']) or '无'}"
        )
        for blocker in member["blockers"]:
            lines.append(f"  - {blocker}")
    if not result["applicable"]:
        lines.append("")
        lines.append("结论：同一份卷不能仅凭班组名称套用；应按上述学员暴露史改题或分别组卷。")
    return "\n".join(lines)


def full_report_text(pack, candidate_dir=None) -> str:
    learner_ids = [row["id"] for row in pack.learners]
    parts = [
        review_text(pack),
        variants_text(pack),
        audit_text(pack),
        correction_impact_text(pack),
        "# 各学员组卷/补考建议",
        "",
    ]
    for learner_id in learner_ids:
        parts.append(plan_text(pack, learner_id, candidate_dir=candidate_dir))
        parts.append("")
    return "\n".join(parts)


def as_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False)
