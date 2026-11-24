"""资料包与编审标注的装载。

原始 TSV 的物理校验仍由仓库根目录的 ``pack_check.py`` 负责；本模块在其
已校验的表之上提供领域访问。编审标注是可选 JSON，用来保存教员/评审对
线索、证据时点和误读类型的结构化结论。
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pack_check import DEFAULT_DATA, read_tables  # noqa: E402


def split_pipe(value: str | None) -> list[str]:
    if value is None or value == "":
        return []
    return [part.strip() for part in value.split("|") if part.strip()]


def parse_responses(value: str | None) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in split_pipe(value):
        if "=" not in item:
            raise ValueError(f"作答组 {item!r} 必须写成 题号=选项号")
        qid, raw_option = item.split("=", 1)
        result[qid.strip()] = int(raw_option.strip())
    return result


@dataclass
class Pack:
    directory: Path
    tables: dict[str, list[dict[str, str]]]
    annotations: dict[str, Any] = field(default_factory=dict)
    annotation_path: Path | None = None

    @classmethod
    def load(
        cls,
        directory: Path | str = DEFAULT_DATA,
        annotation_path: Path | str | None = None,
    ) -> "Pack":
        directory = Path(directory)
        tables = read_tables(directory)
        if annotation_path is None:
            annotation_path = PROJECT_ROOT / "editorial" / "annotations.json"
        annotation_path = Path(annotation_path)
        annotations: dict[str, Any] = {}
        if annotation_path.exists():
            annotations = json.loads(annotation_path.read_text(encoding="utf-8"))
        return cls(directory=directory, tables=tables, annotations=annotations,
                   annotation_path=annotation_path)

    @property
    def cases(self) -> list[dict[str, str]]:
        return self.tables["cases.tsv"]

    @property
    def questions(self) -> list[dict[str, str]]:
        return self.tables["questions.tsv"]

    @property
    def learners(self) -> list[dict[str, str]]:
        return self.tables["learners.tsv"]

    @property
    def corrections(self) -> list[dict[str, str]]:
        return self.tables["correction_log.tsv"]

    @property
    def sittings(self) -> list[dict[str, str]]:
        return self.tables["sittings.tsv"]

    @property
    def study_log(self) -> list[dict[str, str]]:
        return self.tables["study_log.tsv"]

    def by_id(self, table: str, identifier: str) -> dict[str, str]:
        for row in self.tables[table]:
            if row["id"] == identifier:
                return row
        raise KeyError(f"{table} 中找不到 {identifier}")

    def case(self, identifier: str) -> dict[str, str]:
        return self.by_id("cases.tsv", identifier)

    def question(self, identifier: str) -> dict[str, str]:
        return self.by_id("questions.tsv", identifier)

    def learner(self, identifier: str) -> dict[str, str]:
        return self.by_id("learners.tsv", identifier)

    def correction(self, identifier: str) -> dict[str, str]:
        return self.by_id("correction_log.tsv", identifier)

    def basis_ids(self, question: dict[str, str] | str) -> list[str]:
        qid = question["id"] if isinstance(question, dict) else question
        return split_pipe(self.question(qid)["basis"])

    def option_pairs(self, qid: str) -> list[tuple[int, str]]:
        row = self.question(qid)
        pairs = []
        for key, value in row.items():
            if key.startswith("option_"):
                try:
                    number = int(key.removeprefix("option_"))
                except ValueError:
                    continue
                pairs.append((number, value))
        return sorted(pairs)

    def response_map(self, learner_id: str) -> dict[str, int]:
        return parse_responses(self.learner(learner_id)["responses"])

    def needs(self, learner_id: str) -> list[str]:
        return split_pipe(self.learner(learner_id)["needs"])

    def profile(self, qid: str) -> dict[str, Any]:
        return self.annotations.get("questions", {}).get(qid, {})

    def active_corrections(self, at: str | None = None) -> list[dict[str, str]]:
        if at is None:
            return list(self.corrections)
        return [row for row in self.corrections if row["logged"] <= at]


def load_pack(directory: Path | str = DEFAULT_DATA) -> Pack:
    return Pack.load(directory)
