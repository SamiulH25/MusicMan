from __future__ import annotations

from pathlib import Path

import pytest

from musicman.engine import CategorisationEngine
from musicman.models import (
    Config,
    Condition,
    Conditions,
    MusicTags,
    Rule,
)


class TestConditionEvaluation:
    """Direct tests of _apply_operator."""

    @pytest.mark.parametrize(
        ("op", "tag_value", "expected", "result"),
        [
            ("eq", "Jazz", "jazz", True),
            ("eq", "Jazz", "Rock", False),
            ("neq", "Jazz", "Rock", True),
            ("neq", "Jazz", "jazz", False),
            ("contains", "Heavy Metal", "metal", True),
            ("contains", "Jazz", "metal", False),
            ("matches", "Heavy Metal", r"(?i)metal", True),
            ("matches", "Jazz", r"^Rock", False),
            ("gt", 2000, 1999, True),
            ("gt", 2000, 2000, False),
            ("gte", 2000, 2000, True),
            ("lt", 1990, 2000, True),
            ("lte", 1990, 1990, True),
            ("in", "Rock", ["rock", "metal"], True),
            ("in", "Jazz", ["rock", "metal"], False),
            ("exists", "something", True, True),
            ("exists", None, True, False),
            ("not_exists", None, True, True),
            ("not_exists", "something", True, False),
        ],
    )
    def test_operator(
        self,
        op: str,
        tag_value: str | int | None,
        expected: object,
        result: bool,
    ) -> None:
        assert (
            CategorisationEngine._apply_operator(op, tag_value, expected)
            == result
        )


class TestCategorise:
    def test_first_rule_wins(self, sample_tags: MusicTags, minimal_config: Config) -> None:
        """First matching rule's template is used."""
        engine = CategorisationEngine(minimal_config)
        assert engine._match_rule(sample_tags) == (minimal_config.rules[0], "move")

    def test_rock_matches_second_rule(
        self, rock_tags: MusicTags, minimal_config: Config,
    ) -> None:
        engine = CategorisationEngine(minimal_config)
        assert engine._match_rule(rock_tags) == (minimal_config.rules[1], "move")

    def test_fallback_to_defaults(
        self, sparse_tags: MusicTags, minimal_config: Config,
    ) -> None:
        engine = CategorisationEngine(minimal_config)
        rule, action = engine._match_rule(sparse_tags)
        assert rule is None
        assert action is None

    def test_nested_all_and_any(self) -> None:
        """Test nested Conditions.all + Conditions.any."""
        cfg = Config(
            rules=[
                Rule(
                    name="Nested",
                    conditions=Conditions(
                        all=[
                            Condition(tag="genre", op="contains", value="rock"),
                            Conditions(
                                any=[
                                    Condition(tag="date", op="gte", value=2000),
                                    Condition(tag="date", op="lt", value=1990),
                                ],
                            ),
                        ],
                    ),
                    output="Nested/{artist}{ext}",
                ),
            ],
        )
        engine = CategorisationEngine(cfg)

        # Rock from 1980 -> date >= 2000? no. date < 1990? yes -> matches.
        tags = MusicTags(genre="Rock", date=1980, artist="A")
        rule, _ = engine._match_rule(tags)
        assert rule is not None
        assert rule.name == "Nested"

        # Rock from 1995 -> neither any-branch matches.
        tags2 = MusicTags(genre="Rock", date=1995, artist="A")
        rule2, _ = engine._match_rule(tags2)
        assert rule2 is None

    def test_empty_conditions_always_match(self) -> None:
        """A rule with no conditions (empty Conditions) always matches."""
        cfg = Config(
            rules=[
                Rule(
                    name="Catch-all",
                    conditions=Conditions(),
                    output="All/{artist}{ext}",
                ),
            ],
        )
        engine = CategorisationEngine(cfg)
        rule, _ = engine._match_rule(MusicTags(artist="X"))
        assert rule is not None
        assert rule.name == "Catch-all"

    def test_missing_tag_not_crash(self) -> None:
        """Missing tag value returns None -> condition doesn't match (crash-free)."""
        cfg = Config(
            rules=[
                Rule(
                    name="Genre rule",
                    conditions=Conditions(
                        all=[Condition(tag="genre", op="eq", value="Jazz")]
                    ),
                    output="{genre}/{artist}{ext}",
                ),
            ],
        )
        engine = CategorisationEngine(cfg)
        tags = MusicTags(artist="No Genre")  # genre is None
        rule, _ = engine._match_rule(tags)
        assert rule is None
