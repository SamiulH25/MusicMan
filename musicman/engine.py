from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterator, Optional

from .config import resolve_output_base
from .formatter import format_path
from .models import (
    Config,
    Condition,
    Conditions,
    MusicTags,
    Rule,
    FileResult,
)
from .utils import scan_files, read_tags

_TAG_VALUE_TYPES = Optional[str | int | float | list[str] | list[int]]


class CategorisationEngine:
    """Core rules engine.

    Scans source paths, reads metadata, evaluates rules, and yields
    :class:`FileResult` instances describing what should happen to each
    file.
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self.base_dir = resolve_output_base(config.settings.output_base_dir)

    def categorise(self, sources: list[Path]) -> Iterator[FileResult]:
        """Scan, read, match, resolve destination — yield one result per
        file."""
        for source_path in scan_files(
            sources,
            self.config.settings.supported_extensions,
            self.config.settings.follow_symlinks,
        ):
            try:
                tags = read_tags(source_path)
            except Exception as exc:
                yield FileResult(
                    source=source_path,
                    error=f"Failed to read tags: {exc}",
                )
                continue

            matched_rule, matched_action = self._match_rule(tags)
            template = (
                matched_rule.output
                if matched_rule
                else self.config.defaults.output
            )
            action = (
                matched_action or self.config.defaults.action
            )

            relative_path = format_path(
                template, tags, source_path.suffix,
            )
            destination = self.base_dir / relative_path

            # Skip if source == destination (already organised).
            if source_path.resolve() == destination.resolve():
                yield FileResult(
                    source=source_path,
                    destination=destination,
                    rule=matched_rule.name if matched_rule else "defaults",
                    action=action,
                    tags=tags,
                    skipped=True,
                )
                continue

            yield FileResult(
                source=source_path,
                destination=destination,
                rule=matched_rule.name if matched_rule else "defaults",
                action=action,
                tags=tags,
            )

    # ------------------------------------------------------------------
    # Rule matching
    # ------------------------------------------------------------------

    def _match_rule(
        self, tags: MusicTags,
    ) -> tuple[Optional[Rule], Optional[str]]:
        """Return ``(rule, action)`` for the first matching rule, or
        ``(None, None)`` if none match."""
        for rule in self.config.rules:
            if self._evaluate_conditions(rule.conditions, tags):
                return rule, rule.action
        return None, None

    # ------------------------------------------------------------------
    # Condition evaluation
    # ------------------------------------------------------------------

    def _evaluate_conditions(
        self, conditions: Conditions, tags: MusicTags,
    ) -> bool:
        if conditions.all is not None:
            return all(
                self._evaluate_single(c, tags)
                if isinstance(c, Condition)
                else self._evaluate_conditions(c, tags)
                for c in conditions.all
            )
        if conditions.any is not None:
            return any(
                self._evaluate_single(c, tags)
                if isinstance(c, Condition)
                else self._evaluate_conditions(c, tags)
                for c in conditions.any
            )
        # Empty conditions → always matches.
        return True

    def _evaluate_single(
        self, cond: Condition, tags: MusicTags,
    ) -> bool:
        tag_value = tags.get(cond.tag)
        return self._apply_operator(cond.op, tag_value, cond.value)

    # ------------------------------------------------------------------
    # Operators
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_operator(
        op: str,
        tag_value: _TAG_VALUE_TYPES,
        expected: Any,
    ) -> bool:
        if tag_value is None:
            return op == "not_exists"

        tag_str = str(tag_value)

        match op:
            case "eq":
                return tag_str.lower() == str(expected).lower()
            case "neq":
                return tag_str.lower() != str(expected).lower()
            case "contains":
                return str(expected).lower() in tag_str.lower()
            case "matches":
                return bool(re.search(str(expected), tag_str))
            case "gt" | "gte" | "lt" | "lte":
                return _compare_numeric(op, tag_value, expected)
            case "in":
                if not isinstance(expected, list):
                    return tag_str.lower() == str(expected).lower()
                return tag_str.lower() in (
                    str(e).lower() for e in expected
                )
            case "exists":
                return tag_value is not None
            case "not_exists":
                return tag_value is None
            case _:
                raise ValueError(f"Unknown operator: {op!r}")


# ---------------------------------------------------------------------------
# Numeric comparison helper
# ---------------------------------------------------------------------------

def _to_number(value: Any) -> Optional[int | float]:
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _compare_numeric(
    op: str,
    tag_value: _TAG_VALUE_TYPES,
    expected: Any,
) -> bool:
    num_tag = _to_number(tag_value)
    num_exp = _to_number(expected)
    if num_tag is None or num_exp is None:
        return False

    match op:
        case "gt":
            return num_tag > num_exp
        case "gte":
            return num_tag >= num_exp
        case "lt":
            return num_tag < num_exp
        case "lte":
            return num_tag <= num_exp
        case _:
            return False
