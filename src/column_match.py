# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Yamamoto Yota

"""Column name matching heuristics used for union mapping suggestions."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass
class ColumnMatchSuggestion:
    """Suggested mapping from a right column to a left column."""

    right_column: str
    suggested_left_column: str | None
    score: float
    reason: str


_TOKEN_ALIASES = {
    "cust": "customer",
    "customerid": "customer id",
    "custid": "customer id",
    "client": "customer",
    "dt": "date",
    "datetime": "date time",
    "amt": "amount",
    "price": "amount",
    "sales": "sale",
    "qty": "quantity",
    "num": "number",
    "code": "id",
    "cd": "id",
    "namejp": "name",
    "fullname": "name",
}


def _normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).strip().lower()
    return text


def _canonical(value: str) -> str:
    text = _normalize_text(value)
    text = re.sub(r"[\s\-\./\\]+", "_", text)
    text = re.sub(r"[^0-9a-zA-Z_]+", "", text)
    return text.strip("_")


def _tokenize(value: str) -> list[str]:
    text = _normalize_text(value)
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    tokens = re.split(r"[^0-9a-zA-Z]+", text)
    out: list[str] = []
    for token in tokens:
        if not token:
            continue
        alias_text = _TOKEN_ALIASES.get(token, token)
        out.extend([t for t in alias_text.split() if t])
    return out


def _score_columns(left_col: str, right_col: str) -> tuple[float, str]:
    left_norm = _normalize_text(left_col)
    right_norm = _normalize_text(right_col)
    if left_norm == right_norm:
        return 1.0, "exact (case-insensitive)"

    left_c = _canonical(left_col)
    right_c = _canonical(right_col)
    if left_c == right_c and left_c:
        return 0.97, "canonical exact"

    left_tokens = set(_tokenize(left_col))
    right_tokens = set(_tokenize(right_col))
    if left_tokens and right_tokens:
        inter = left_tokens & right_tokens
        union = left_tokens | right_tokens
        jaccard = len(inter) / len(union)
        if jaccard >= 0.5:
            return 0.8 + (0.15 * jaccard), f"token overlap ({', '.join(sorted(inter))})"

    seq = SequenceMatcher(a=left_c or left_norm, b=right_c or right_norm).ratio()
    if seq >= 0.75:
        return min(0.89, seq), "string similarity"
    return seq * 0.6, "low confidence"


def suggest_union_column_mapping(
    left_columns: list[str],
    right_columns: list[str],
    *,
    min_score: float = 0.72,
) -> dict[str, ColumnMatchSuggestion]:
    """Suggest a left-column mapping for each right column."""
    suggestions: dict[str, ColumnMatchSuggestion] = {}
    used_left: set[str] = set()

    # Exact/canonical pass to avoid ambiguous assignment.
    for right in right_columns:
        best_exact: tuple[str, float, str] | None = None
        for left in left_columns:
            score, reason = _score_columns(left, right)
            if score >= 0.95:
                if best_exact is None or score > best_exact[1]:
                    best_exact = (left, score, reason)
        if best_exact and best_exact[0] not in used_left:
            left, score, reason = best_exact
            suggestions[right] = ColumnMatchSuggestion(right, left, score, reason)
            used_left.add(left)

    # Best-effort pass for remaining columns.
    for right in right_columns:
        if right in suggestions:
            continue
        best: tuple[str | None, float, str] = (None, 0.0, "no match")
        for left in left_columns:
            if left in used_left:
                continue
            score, reason = _score_columns(left, right)
            if score > best[1]:
                best = (left, score, reason)
        if best[0] is not None and best[1] >= min_score:
            suggestions[right] = ColumnMatchSuggestion(right, best[0], best[1], best[2])
            used_left.add(best[0])
        else:
            suggestions[right] = ColumnMatchSuggestion(right, None, best[1], best[2])

    return suggestions

