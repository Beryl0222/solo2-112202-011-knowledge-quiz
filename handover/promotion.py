"""把编审通过的候选案例提升到正式 TSV 资料包和标注库。"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from pack_check import read_tables

from .candidates import check_candidate
from .repository import Pack


def _ensure_trailing_newline(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if text and not text.endswith("\n"):
        path.write_text(text + "\n", encoding="utf-8")


def _append_tsv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    _ensure_trailing_newline(path)
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fieldnames, delimiter="\t",
            lineterminator="\n", extrasaction="ignore",
        )
        for row in rows:
            writer.writerow(row)


def promote_candidate(
    candidate_path: Path | str,
    data_dir: Path | str,
    annotation_path: Path | str,
    question_id: str | None = None,
) -> dict[str, Any]:
    candidate_path = Path(candidate_path)
    data_dir = Path(data_dir)
    annotation_path = Path(annotation_path)
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))

    pack = Pack.load(data_dir, annotation_path)
    review = check_candidate(candidate, pack)
    if not review["ok"]:
        raise ValueError("候选问答未通过编审，不能提升：" + json.dumps(review, ensure_ascii=False))

    question = candidate["question"]
    qid = question_id or question["id"]
    if qid in {row["id"] for row in pack.questions}:
        raise ValueError(f"题号 {qid} 已存在")
    if len(question.get("options", [])) != 2:
        raise ValueError("当前 TSV 契约只有 option_1/option_2；请先扩展 tables.json 后再提升多选项题")

    case_ids = [case["id"] for case in candidate["cases"]]
    existing_cases = {row["id"] for row in pack.cases}
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("候选案例 id 重复")
    if set(case_ids) & existing_cases:
        raise ValueError(f"案例 id 与正式库重复：{sorted(set(case_ids) & existing_cases)}")

    contract = json.loads((data_dir / "tables.json").read_text(encoding="utf-8"))
    case_columns = contract["columns"]["cases.tsv"]
    question_columns = contract["columns"]["questions.tsv"]

    case_rows = []
    for case in candidate["cases"]:
        case_rows.append({column: case.get(column, "") for column in case_columns})

    options = sorted(question["options"], key=lambda item: item["id"])
    question_row = {
        "id": qid,
        "basis": "|".join(question["basis"]),
        "ability": question["ability"],
        "stem": question["stem"],
        "option_1": options[0]["text"],
        "option_2": options[1]["text"],
        "key": str(question["key"]),
    }
    question_row = {column: question_row.get(column, "") for column in question_columns}

    _append_tsv(data_dir / "cases.tsv", case_columns, case_rows)
    _append_tsv(data_dir / "questions.tsv", question_columns, [question_row])

    annotations = pack.annotations
    for section in ("rules", "clues", "misread_codes"):
        annotations.setdefault(section, {})
        for key, value in candidate.get(section, {}).items():
            if key in annotations[section] and annotations[section][key] != value:
                raise ValueError(f"{section}.{key} 已存在但定义不同")
            annotations[section][key] = value

    profile: dict[str, Any] = {}
    for source_key, target_key in (
        ("as_of", "as_of"),
        ("target", "target"),
        ("clue_ids", "clue_ids"),
        ("memory_group", "memory_group"),
        ("decision_contexts", "decision_contexts"),
        ("ambiguity_witness", "ambiguity_witness"),
        ("medium_review_notes", "medium_review_notes"),
        ("distractor_readings", "distractor_readings"),
        ("also_covers", "also_covers"),
        ("supersedes", "supersedes"),
    ):
        if source_key in question:
            profile[target_key] = question[source_key]
    annotations.setdefault("questions", {})[qid] = profile
    annotation_path.write_text(
        json.dumps(annotations, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # 立即按正式资料包契约复查。
    read_tables(data_dir)
    return {
        "promoted_question": qid,
        "promoted_cases": case_ids,
        "data_dir": str(data_dir),
        "annotation_path": str(annotation_path),
    }
