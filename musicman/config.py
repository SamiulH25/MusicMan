from __future__ import annotations

import json
import logging
import re
from importlib.resources import files as _resources_files
from pathlib import Path
from typing import Any, Optional

from .models import (
    Config,
    Condition,
    Conditions,
    Defaults,
    Rule,
    Settings,
)
from .formatter import TAG_ALIASES

logger = logging.getLogger(__name__)

def _config_search_paths() -> list[Path]:
    """Ordered list of paths to search when no explicit config is given."""
    return [
        Path.cwd() / "musicman-rules.json",
        Path.cwd() / "musicman.json",
        Path.home() / ".config" / "musicman" / "rules.json",
        Path.home() / ".musicman.json",
    ]

KNOWN_OPERATORS = frozenset({
    "eq", "neq", "contains", "matches",
    "gt", "gte", "lt", "lte",
    "in", "exists", "not_exists",
})

_DEFAULT_EXTENSIONS = [
    ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".wma",
]

def _load_default_rules() -> str:
    """Return the bundled default-rules.json as a string."""
    return (
        _resources_files("musicman.data")
        .joinpath("default-rules.json")
        .read_text(encoding="utf-8")
    )


SAMPLE_CONFIG = _load_default_rules()



# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_config(path: Optional[Path] = None) -> Config:
    """Load configuration from *path* or discover it via
    :data:`CONFIG_SEARCH_PATHS`.

    Falls back to the bundled default rules when no file is found.
    """
    if path is not None:
        return _parse_file(path)
    for search_path in _config_search_paths():
        if search_path.exists():
            logger.info("Loading config from %s", search_path)
            return _parse_file(search_path)
    logger.info("No config file found; using bundled default rules")
    return _parse_default_rules()


def _parse_default_rules() -> Config:
    """Parse the bundled default-rules.json into a Config object."""
    raw = json.loads(_load_default_rules())
    return _deserialise(raw)


def _parse_file(path: Path) -> Config:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        msg = f"Invalid JSON in {path}: {exc}"
        raise ConfigError(msg) from exc
    errors = validate_config(raw)
    if errors:
        raise ConfigError(
            f"Config validation failed for {path}:\n" + "\n".join(errors)
        )
    return _deserialise(raw)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_config(raw: dict[str, Any]) -> list[str]:
    """Validate *raw* config dict.  Returns a list of error strings
    (empty = valid)."""
    errors: list[str] = []

    rules_list = raw.get("rules", [])
    if not isinstance(rules_list, list):
        errors.append("'rules' must be a list")

    for i, rule in enumerate(rules_list):
        if not isinstance(rule, dict):
            errors.append(f"rules[{i}]: expected object")
            continue
        errors += _validate_rule(rule, f"rules[{i}]")

    defaults = raw.get("defaults", {})
    if isinstance(defaults, dict):
        if "output" in defaults:
            errors += _validate_output_template(
                defaults["output"], "defaults.output"
            )

    settings = raw.get("settings", {})
    if isinstance(settings, dict):
        exts = settings.get("supported_extensions")
        if exts is not None:
            if not isinstance(exts, list) or not all(
                    isinstance(e, str) and e.startswith(".") for e in exts):
                errors.append("settings.supported_extensions must be a list "
                              "of extension strings starting with '.'")

    return errors


def _validate_rule(rule: dict, prefix: str) -> list[str]:
    errors: list[str] = []
    if "name" not in rule or not isinstance(rule["name"], str):
        errors.append(f"{prefix}: missing or invalid 'name' (str)")
    if "output" not in rule or not isinstance(rule["output"], str):
        errors.append(f"{prefix}: missing or invalid 'output' (str)")
    else:
        errors += _validate_output_template(rule["output"], f"{prefix}.output")
    if "conditions" not in rule:
        errors.append(f"{prefix}: missing 'conditions'")
    else:
        errors += _validate_conditions(rule["conditions"], f"{prefix}.conditions")
    action = rule.get("action", "move")
    if action not in ("copy", "move", "symlink"):
        errors.append(f"{prefix}.action: must be 'copy', 'move', or 'symlink'")
    return errors


def _validate_conditions(
    cond: Any, prefix: str,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(cond, dict):
        errors.append(f"{prefix}: must be an object with 'all' and/or 'any'")
        return errors

    for key in ("all", "any"):
        items = cond.get(key)
        if items is not None:
            if not isinstance(items, list):
                errors.append(f"{prefix}.{key}: must be a list")
                continue
            for j, item in enumerate(items):
                errors += _validate_condition_item(
                    item, f"{prefix}.{key}[{j}]"
                )
    return errors


def _validate_condition_item(item: Any, prefix: str) -> list[str]:
    if not isinstance(item, dict):
        return [f"{prefix}: must be an object"]
    # It's either a Condition or a nested Conditions group.
    if "tag" in item:
        return _validate_condition(item, prefix)
    if "all" in item or "any" in item:
        return _validate_conditions(item, prefix)
    return [f"{prefix}: must have 'tag' (condition) or 'all'/'any' (group)"]


def _validate_condition(cond: dict, prefix: str) -> list[str]:
    errors: list[str] = []
    tag = cond.get("tag")
    if not isinstance(tag, str):
        errors.append(f"{prefix}.tag: must be a string")
    op = cond.get("op")
    if op not in KNOWN_OPERATORS:
        errors.append(f"{prefix}.op: unknown operator {op!r}; "
                       f"known: {', '.join(sorted(KNOWN_OPERATORS))}")
    if "value" not in cond:
        errors.append(f"{prefix}.value: required")
    return errors


def _validate_output_template(template: str, prefix: str) -> list[str]:
    from .formatter import validate_template
    unknowns = validate_template(template)
    return [
        f"{prefix}: unknown placeholder {{{u}}}; "
        f"known: {', '.join(sorted(TAG_ALIASES))}, ext"
        for u in unknowns
    ]


# ---------------------------------------------------------------------------
# Deserialisation
# ---------------------------------------------------------------------------

def _deserialise(raw: dict[str, Any]) -> Config:
    defaults_data = raw.get("defaults", {})
    settings_data = raw.get("settings", {})

    defaults = Defaults(
        output=defaults_data.get("output", Defaults.output),
        action=defaults_data.get("action", Defaults.action),
    )
    settings = Settings(
        output_base_dir=settings_data.get(
            "output_base_dir", Settings.output_base_dir
        ),
        overwrite=settings_data.get("overwrite", Settings.overwrite),
        delete_empty_sources=settings_data.get(
            "delete_empty_sources", Settings.delete_empty_sources
        ),
        follow_symlinks=settings_data.get(
            "follow_symlinks", Settings.follow_symlinks
        ),
        supported_extensions=settings_data.get(
            "supported_extensions", _DEFAULT_EXTENSIONS
        ),
    )

    rules = [_deserialise_rule(r) for r in raw.get("rules", [])]

    return Config(rules=rules, defaults=defaults, settings=settings)


def _deserialise_rule(raw: dict[str, Any]) -> Rule:
    return Rule(
        name=str(raw["name"]),
        conditions=_deserialise_conditions(raw["conditions"]),
        output=str(raw["output"]),
        action=str(raw.get("action", "move")),
    )


def _deserialise_conditions(raw: dict[str, Any]) -> Conditions:
    conds = Conditions()
    if "all" in raw:
        conds.all = [_deserialise_condition_item(item) for item in raw["all"]]
    if "any" in raw:
        conds.any = [_deserialise_condition_item(item) for item in raw["any"]]
    return conds


def _deserialise_condition_item(raw: dict[str, Any]) -> Condition | Conditions:
    if "tag" in raw:
        return Condition(
            tag=str(raw["tag"]),
            op=str(raw["op"]),
            value=raw["value"],
        )
    return _deserialise_conditions(raw)


# ---------------------------------------------------------------------------
# Output base resolution
# ---------------------------------------------------------------------------

def resolve_output_base(base_dir: str) -> Path:
    """Expand ``~`` and resolve to absolute :class:`~pathlib.Path`."""
    return Path(base_dir).expanduser().resolve()


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ConfigError(Exception):
    """Configuration loading or validation failure."""
