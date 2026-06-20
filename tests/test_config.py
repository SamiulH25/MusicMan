from __future__ import annotations

import json
from pathlib import Path

import pytest

from musicman.config import (
    ConfigError,
    _deserialise,
    load_config,
    validate_config,
)
from musicman.models import Config, Defaults, Settings


class TestLoadConfig:
    def test_load_default_when_no_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """No config file on disk - falls back to bundled default rules."""
        monkeypatch.chdir(tmp_path)
        cfg = load_config()
        assert isinstance(cfg, Config)
        # Should have the bundled default rules (not empty)
        assert len(cfg.rules) > 0
        assert isinstance(cfg.defaults, Defaults)
        assert isinstance(cfg.settings, Settings)

    def test_load_from_explicit_path(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "rules.json"
        cfg_path.write_text(json.dumps({
            "rules": [
                {
                    "name": "Test",
                    "conditions": {"all": [{"tag": "genre", "op": "eq", "value": "Jazz"}]},
                    "output": "{genre}/{artist}{ext}",
                },
            ],
        }))
        cfg = load_config(cfg_path)
        assert len(cfg.rules) == 1
        assert cfg.rules[0].name == "Test"

    def test_load_invalid_json_raises(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "bad.json"
        cfg_path.write_text("{invalid json}")
        with pytest.raises(ConfigError, match="Invalid JSON"):
            load_config(cfg_path)

    def test_load_invalid_schema_raises(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "bad.json"
        cfg_path.write_text(json.dumps({
            "rules": [{"name": 42}],  # name must be str
        }))
        with pytest.raises(ConfigError, match="validation failed"):
            load_config(cfg_path)


class TestValidateConfig:
    def test_valid_config_no_errors(self) -> None:
        raw = {
            "rules": [
                {
                    "name": "Jazz",
                    "conditions": {
                        "all": [{"tag": "genre", "op": "contains", "value": "jazz"}],
                    },
                    "output": "{artist}/{title}{ext}",
                },
            ],
        }
        errors = validate_config(raw)
        assert errors == []

    def test_missing_rule_name(self) -> None:
        raw = {
            "rules": [
                {
                    "conditions": {"all": [{"tag": "g", "op": "eq", "value": "x"}]},
                    "output": "{artist}{ext}",
                },
            ],
        }
        errors = validate_config(raw)
        assert any("name" in e for e in errors)

    def test_invalid_operator(self) -> None:
        raw = {
            "rules": [
                {
                    "name": "Bad Op",
                    "conditions": {
                        "all": [{"tag": "genre", "op": "nope", "value": "x"}],
                    },
                    "output": "{artist}{ext}",
                },
            ],
        }
        errors = validate_config(raw)
        assert any("nope" in e for e in errors)

    def test_invalid_action(self) -> None:
        raw = {
            "rules": [
                {
                    "name": "Bad action",
                    "conditions": {
                        "all": [{"tag": "g", "op": "eq", "value": "x"}],
                    },
                    "output": "{artist}{ext}",
                    "action": "delete",
                },
            ],
        }
        errors = validate_config(raw)
        assert any("action" in e and "must be" in e for e in errors)

    def test_unknown_template_placeholder(self) -> None:
        raw = {
            "rules": [
                {
                    "name": "Bad placeholder",
                    "conditions": {
                        "all": [{"tag": "g", "op": "eq", "value": "x"}],
                    },
                    "output": "{foobar}/{artist}{ext}",
                },
            ],
        }
        errors = validate_config(raw)
        assert any("foobar" in e for e in errors)

    def test_invalid_supported_extensions(self) -> None:
        raw = {
            "rules": [],
            "settings": {"supported_extensions": "not_a_list"},
        }
        errors = validate_config(raw)
        assert any("supported_extensions" in e for e in errors)

    def test_nested_conditions_all_and_any(self) -> None:
        raw = {
            "rules": [
                {
                    "name": "Nested",
                    "conditions": {
                        "all": [
                            {"tag": "genre", "op": "eq", "value": "Rock"},
                            {
                                "any": [
                                    {"tag": "date", "op": "gte", "value": 2000},
                                    {"tag": "date", "op": "lt", "value": 1990},
                                ],
                            },
                        ],
                    },
                    "output": "{artist}/{title}{ext}",
                },
            ],
        }
        errors = validate_config(raw)
        assert errors == []

    def test_invalid_nested_condition(self) -> None:
        raw = {
            "rules": [
                {
                    "name": "Bad",
                    "conditions": {
                        "all": [{"tag_only": "no_op_or_value"}],
                    },
                    "output": "{artist}{ext}",
                },
            ],
        }
        errors = validate_config(raw)
        assert errors  # should complain about missing 'tag' or 'all'/'any'


class TestDeserialise:
    def test_basic(self) -> None:
        raw = {
            "rules": [
                {
                    "name": "Test",
                    "conditions": {
                        "all": [{"tag": "genre", "op": "eq", "value": "Jazz"}],
                    },
                    "output": "{genre}/{artist}{ext}",
                },
            ],
            "defaults": {"output": "Unsorted/{artist}{ext}", "action": "copy"},
            "settings": {"output_base_dir": "/custom/path"},
        }
        cfg = _deserialise(raw)
        assert len(cfg.rules) == 1
        assert cfg.rules[0].name == "Test"
        assert cfg.defaults.action == "copy"
        assert cfg.settings.output_base_dir == "/custom/path"

    def test_defaults_filled(self) -> None:
        raw = {}
        cfg = _deserialise(raw)
        assert cfg.rules == []
        assert cfg.defaults.output == Defaults.output
        assert cfg.settings.overwrite == Settings.overwrite
