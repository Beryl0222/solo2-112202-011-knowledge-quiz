"""查找原案变体、改写和只替换否定词的反事实。

自动扫描只负责提示；是否构成“可靠记忆认出”的题组仍由教员在
``editorial/annotations.json`` 中确认。这样不会把同能力但表面和线索
均不同的题误判成记忆题。
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Iterable

from .repository import Pack

_PUNCT_RE = re.compile(r"[\s，。！？；：、“”‘’\"'（）()\[\]【】,.!?;:_\-/\\|]+")
_NEGATION_WORDS = ("没有", "并非", "并不", "没", "未", "不", "无", "非")
_NEGATION_RE = re.compile("|".join(sorted(_NEGATION_WORDS, key=len, reverse=True)))
_POLARITY_MARKERS = ("已经", "曾經", "曾经", "已", "曾", "还")
_POLARITY_RE = re.compile("|".join(sorted(_POLARITY_MARKERS, key=len, reverse=True)))
_ID_RE = re.compile(r"[A-Za-z]{1,4}\s*\d+|[一二三四五六七八九十两\d]+[盒袋件托框]?")


def normalize_text(text: str, mask_ids: bool = False) -> str:
    text = _PUNCT_RE.sub("", text)
    if mask_ids:
        text = _ID_RE.sub("#", text)
    return text


def remove_negation(text: str) -> str:
    return _NEGATION_RE.sub("", normalize_text(text))


def canonical_polarity_stem(text: str) -> str:
    """去掉否定词和“已/已经/还”等随极性改写出现的标记，便于比对反事实。"""
    text = remove_negation(text)
    return _POLARITY_RE.sub("", text)


def similarity(a: str, b: str, mask_ids: bool = True) -> float:
    na = normalize_text(a, mask_ids=mask_ids)
    nb = normalize_text(b, mask_ids=mask_ids)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def is_negation_counterfactual(a: str, b: str) -> bool:
    """两段文字仅差否定/极性标记，去掉这些标记后相同或几乎相同。"""
    na, nb = normalize_text(a), normalize_text(b)
    if not na or not nb:
        return False
    neg_a = any(word in na for word in _NEGATION_WORDS)
    neg_b = any(word in nb for word in _NEGATION_WORDS)
    if neg_a == neg_b:
        return False
    ca, cb = canonical_polarity_stem(a), canonical_polarity_stem(b)
    if not ca or not cb:
        return False
    if ca == cb:
        return True
    return SequenceMatcher(None, ca, cb).ratio() >= 0.94


def _pairs(items: list[dict[str, str]]) -> Iterable[tuple[dict[str, str], dict[str, str]]]:
    for i, left in enumerate(items):
        for right in items[i + 1:]:
            yield left, right


def scan_variants(pack: Pack, similarity_threshold: float = 0.62) -> dict[str, Any]:
    explicit = pack.annotations.get("memory_groups", {})
    lineage_groups: dict[str, list[str]] = {}
    for case in pack.cases:
        lineage = case.get("lineage", "")
        if lineage:
            lineage_groups.setdefault(lineage, []).append(case["id"])

    similar_cases = []
    negation_candidates = []
    for left, right in _pairs(pack.cases):
        score = similarity(left["text"], right["text"])
        if score >= similarity_threshold:
            similar_cases.append({
                "left": left["id"], "right": right["id"], "similarity": round(score, 3),
                "lineage_shared": left.get("lineage") == right.get("lineage") and bool(left.get("lineage")),
            })
        if is_negation_counterfactual(left["text"], right["text"]):
            negation_candidates.append({"left": left["id"], "right": right["id"], "kind": "case_negation"})

    similar_questions = []
    for left, right in _pairs(pack.questions):
        left_options = " ".join(text for _, text in pack.option_pairs(left["id"]))
        right_options = " ".join(text for _, text in pack.option_pairs(right["id"]))
        left_text = left["stem"] + " " + left_options
        right_text = right["stem"] + " " + right_options
        score = similarity(left_text, right_text)
        if score >= similarity_threshold:
            similar_questions.append({
                "left": left["id"], "right": right["id"], "similarity": round(score, 3),
                "same_ability": left["ability"] == right["ability"],
            })
        if is_negation_counterfactual(left["stem"], right["stem"]):
            negation_candidates.append({"left": left["id"], "right": right["id"], "kind": "stem_negation"})

    return {
        "explicit_memory_groups": explicit,
        "declared_lineage_groups": lineage_groups,
        "similar_cases": sorted(similar_cases, key=lambda x: -x["similarity"]),
        "similar_questions": sorted(similar_questions, key=lambda x: -x["similarity"]),
        "negation_candidates": negation_candidates,
        "note": "自动相似度只是编审提示；考核隔离以确认后的 memory_group 和暴露时间为准。",
    }
