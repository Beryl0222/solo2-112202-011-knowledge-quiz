"""命令行入口：编审、变体、审计、组卷和候选校验。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .assessment import assess_all, correction_impact
from .candidates import check_candidate, load_candidate
from .planning import evaluate_paper, plan_for_learner
from .report import (
    as_json,
    audit_text,
    cohort_paper_text,
    correction_impact_text,
    full_report_text,
    paper_text,
    plan_text,
    review_text,
    variants_text,
)
from .repository import Pack
from .review import review_pack
from .variants import scan_variants
from pack_check import DEFAULT_DATA, read_tables


def _print_json(value: Any) -> None:
    print(as_json(value))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="assess.py",
        description="车间文字物料状态题的编审、独立考核证据与补考材料工具",
    )
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="materials 目录")
    parser.add_argument("--annotations", type=Path, default=None, help="编审标注 JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check-pack", help="只校验 TSV 资料包格式和引用")

    cohorts = sub.add_parser("cohorts", help="列出已登记班组/学员组")
    cohorts.add_argument("--json", action="store_true")

    review = sub.add_parser("review", help="核对所有拟选答案和干扰项")
    review.add_argument("--json", action="store_true")

    variants = sub.add_parser("variants", help="扫描原案变体、改写和否定反事实")
    variants.add_argument("--json", action="store_true")

    audit = sub.add_parser("audit", help="按学员时间线审计能力签发")
    audit.add_argument("learner", nargs="?", help="学员编号；省略则全部")
    audit.add_argument("--json", action="store_true")

    impact = sub.add_parser("corrections", help="追踪更正影响")
    impact.add_argument("correction", nargs="?", help="更正记录号；省略则全部")
    impact.add_argument("--json", action="store_true")

    plan = sub.add_parser("plan", help="为学员组卷或列出缺口/补考材料")
    plan.add_argument("learner")
    plan.add_argument("--max-items", type=int, default=None)
    plan.add_argument("--strict-case-family", action="store_true",
                      help="连不同线索但共享原案/改写案例族的题也避开")
    plan.add_argument("--candidate-dir", type=Path,
                      default=Path(__file__).resolve().parent.parent / "candidates",
                      help="已编审候选 JSON 目录，用于提示可提升的补考材料")
    plan.add_argument("--json", action="store_true")

    paper = sub.add_parser("paper", help="解释一份给定卷为何适用/不适用")
    paper.add_argument("questions", nargs="+")
    paper.add_argument("--learner")
    paper.add_argument("--cohort", help="annotations.json 中登记的班组/学员组 id")
    paper.add_argument("--strict-case-family", action="store_true")
    paper.add_argument("--json", action="store_true")

    candidate = sub.add_parser("check-candidate", help="校验 JSON 候选新案例/问答")
    candidate.add_argument("path", type=Path)
    candidate.add_argument("--json", action="store_true")

    promote = sub.add_parser("promote-candidate", help="把通过校验的候选追加到 TSV 和标注库")
    promote.add_argument("path", type=Path)
    promote.add_argument("--question-id", default=None, help="正式题号；默认用 candidate.question.id")
    promote.add_argument("--json", action="store_true")

    report = sub.add_parser("report", help="输出完整中文编审/审计/组卷报告")
    report.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "check-pack":
        tables = read_tables(args.data)
        for filename, rows in tables.items():
            print(f"{filename}  共 {len(rows)} 条")
        return 0

    pack = Pack.load(args.data, args.annotations)

    if args.command == "cohorts":
        cohorts = pack.annotations.get("cohorts", [])
        if args.json:
            _print_json(cohorts)
        else:
            for cohort in cohorts:
                print(f"{cohort['id']}｜{cohort.get('name', '')}｜{', '.join(cohort['learner_ids'])}")
            if not cohorts:
                print("（annotations.json 未登记班组；可用 paper --learner 做单人适用核对）")
        return 0

    if args.command == "review":
        result = review_pack(pack)
        if args.json:
            _print_json(result)
        else:
            print(review_text(pack))
        return 0 if not result["returned"] else 2

    if args.command == "variants":
        result = scan_variants(pack)
        if args.json:
            _print_json(result)
        else:
            print(variants_text(pack))
        return 0

    if args.command == "audit":
        if args.learner:
            result = assess_all(pack)[args.learner]
        else:
            result = assess_all(pack)
        if args.json:
            _print_json(result)
        else:
            print(audit_text(pack, args.learner))
        return 0

    if args.command == "corrections":
        if args.correction:
            result = correction_impact(pack, args.correction)
        else:
            result = [correction_impact(pack, row["id"]) for row in pack.corrections]
        if args.json:
            _print_json(result)
        else:
            print(correction_impact_text(pack, args.correction))
        return 0

    if args.command == "plan":
        result = plan_for_learner(
            pack, args.learner, max_items=args.max_items,
            strict_case_family=args.strict_case_family,
            candidate_dir=args.candidate_dir,
        )
        if args.json:
            _print_json(result)
        else:
            print(plan_text(
                pack, args.learner, args.max_items,
                strict_case_family=args.strict_case_family,
                candidate_dir=args.candidate_dir,
            ))
        return 0 if result["feasible"] else 3

    if args.command == "paper":
        if args.cohort:
            from .planning import evaluate_cohort_paper
            result = evaluate_cohort_paper(
                pack, args.cohort, args.questions, args.strict_case_family
            )
            if args.json:
                _print_json(result)
            else:
                print(cohort_paper_text(pack, args.cohort, args.questions, args.strict_case_family))
            return 0 if result["applicable"] else 4
        result = evaluate_paper(
            pack, args.questions, learner_id=args.learner,
            strict_case_family=args.strict_case_family,
        )
        if args.json:
            _print_json(result)
        else:
            print(paper_text(pack, args.questions, args.learner))
        return 0 if result["applicable"] else 4

    if args.command == "check-candidate":
        candidate = load_candidate(args.path)
        result = check_candidate(candidate, pack)
        if args.json:
            _print_json(result)
        else:
            print(f"{result['candidate']}：{result['decision']}")
            for blocker in result["blockers"]:
                print(f"  [退回/{blocker['code']}] {blocker['message']}")
            for warning in result["warnings"]:
                print(f"  [提示/{warning['code']}] {warning['message']}")
        return 0 if result["ok"] else 5

    if args.command == "promote-candidate":
        from .promotion import promote_candidate
        if args.annotations is None:
            args.annotations = Path(__file__).resolve().parent.parent / "editorial" / "annotations.json"
        result = promote_candidate(
            args.path, args.data, args.annotations, question_id=args.question_id
        )
        if args.json:
            _print_json(result)
        else:
            print(f"已提升 {result['promoted_question']}，案例：{', '.join(result['promoted_cases'])}")
        return 0

    if args.command == "report":
        candidate_dir = Path(__file__).resolve().parent.parent / "candidates"
        if args.json:
            _print_json({
                "review": review_pack(pack),
                "variants": scan_variants(pack),
                "assessments": assess_all(pack),
                "plans": {
                    row["id"]: plan_for_learner(
                        pack, row["id"], candidate_dir=candidate_dir
                    )
                    for row in pack.learners
                },
            })
        else:
            print(full_report_text(pack, candidate_dir=candidate_dir))
        return 0

    parser.error(f"未知命令 {args.command}")
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
