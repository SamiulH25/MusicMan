from __future__ import annotations

import json
import logging
import re
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

SAMPLE_CONFIG: str = """\
{
  "$schema": "musicman-config-v1",
  "rules": [
    {
      "name": "Pop",
      "conditions": {
        "any": [
          { "tag": "genre", "op": "matches", "value": "(?i)^pop" },
          { "tag": "genre", "op": "matches", "value": "(?i)^bubblegum" },
          { "tag": "genre", "op": "matches", "value": "(?i)^synthpop" },
          { "tag": "genre", "op": "matches", "value": "(?i)^dream.?pop" },
          { "tag": "genre", "op": "matches", "value": "(?i)^art.?pop" },
          { "tag": "genre", "op": "matches", "value": "(?i)^k.?pop" },
          { "tag": "genre", "op": "matches", "value": "(?i)^j.?pop" },
          { "tag": "genre", "op": "matches", "value": "(?i)^dance.?pop" },
          { "tag": "genre", "op": "matches", "value": "(?i)^teen.?pop" }
        ]
      },
      "output": "Pop/{artist}/{album}/{track:02d} - {title}{ext}",
      "action": "move"
    },
    {
      "name": "Rock",
      "conditions": {
        "any": [
          { "tag": "genre", "op": "matches", "value": "(?i)^rock" },
          { "tag": "genre", "op": "matches", "value": "(?i)^alternative" },
          { "tag": "genre", "op": "matches", "value": "(?i)^indie.?rock" },
          { "tag": "genre", "op": "matches", "value": "(?i)^punk" },
          { "tag": "genre", "op": "matches", "value": "(?i)^grunge" },
          { "tag": "genre", "op": "matches", "value": "(?i)^emo" },
          { "tag": "genre", "op": "matches", "value": "(?i)^progressive.?rock" },
          { "tag": "genre", "op": "matches", "value": "(?i)^psychedelic" },
          { "tag": "genre", "op": "matches", "value": "(?i)^post.?rock" },
          { "tag": "genre", "op": "matches", "value": "(?i)^garage.?rock" },
          { "tag": "genre", "op": "matches", "value": "(?i)^surf.?rock" },
          { "tag": "genre", "op": "matches", "value": "(?i)^blues.?rock" },
          { "tag": "genre", "op": "matches", "value": "(?i)^folk.?rock" },
          { "tag": "genre", "op": "matches", "value": "(?i)^southern.?rock" },
          { "tag": "genre", "op": "matches", "value": "(?i)^stoner.?rock" },
          { "tag": "genre", "op": "matches", "value": "(?i)^math.?rock" },
          { "tag": "genre", "op": "matches", "value": "(?i)^industrial.?rock" }
        ]
      },
      "output": "Rock/{artist}/{album}/{track:02d} - {title}{ext}",
      "action": "move"
    },
    {
      "name": "Metal",
      "conditions": {
        "any": [
          { "tag": "genre", "op": "matches", "value": "(?i)^metal" },
          { "tag": "genre", "op": "matches", "value": "(?i)^heavy.?metal" },
          { "tag": "genre", "op": "matches", "value": "(?i)^death.?metal" },
          { "tag": "genre", "op": "matches", "value": "(?i)^black.?metal" },
          { "tag": "genre", "op": "matches", "value": "(?i)^doom.?metal" },
          { "tag": "genre", "op": "matches", "value": "(?i)^thrash" },
          { "tag": "genre", "op": "matches", "value": "(?i)^power.?metal" },
          { "tag": "genre", "op": "matches", "value": "(?i)^symphonic.?metal" },
          { "tag": "genre", "op": "matches", "value": "(?i)^folk.?metal" },
          { "tag": "genre", "op": "matches", "value": "(?i)^progressive.?metal" },
          { "tag": "genre", "op": "matches", "value": "(?i)^groove.?metal" },
          { "tag": "genre", "op": "matches", "value": "(?i)^sludge" },
          { "tag": "genre", "op": "matches", "value": "(?i)^post.?metal" },
          { "tag": "genre", "op": "matches", "value": "(?i)^djent" },
          { "tag": "genre", "op": "matches", "value": "(?i)^industrial.?metal" },
          { "tag": "genre", "op": "matches", "value": "(?i)^nu.?metal" },
          { "tag": "genre", "op": "matches", "value": "(?i)^metalcore" },
          { "tag": "genre", "op": "matches", "value": "(?i)^deathcore" }
        ]
      },
      "output": "Metal/{artist}/{album}/{track:02d} - {title}{ext}",
      "action": "move"
    },
    {
      "name": "Hip-Hop & Rap",
      "conditions": {
        "any": [
          { "tag": "genre", "op": "matches", "value": "(?i)^hip.?hop" },
          { "tag": "genre", "op": "matches", "value": "(?i)^rap" },
          { "tag": "genre", "op": "matches", "value": "(?i)^trap" },
          { "tag": "genre", "op": "matches", "value": "(?i)^drill" },
          { "tag": "genre", "op": "matches", "value": "(?i)^grime" },
          { "tag": "genre", "op": "matches", "value": "(?i)^boom.?bap" },
          { "tag": "genre", "op": "matches", "value": "(?i)^g.?funk" },
          { "tag": "genre", "op": "matches", "value": "(?i)^cloud.?rap" },
          { "tag": "genre", "op": "matches", "value": "(?i)^mumble.?rap" },
          { "tag": "genre", "op": "matches", "value": "(?i)^conscious.?hip" },
          { "tag": "genre", "op": "matches", "value": "(?i)^east.?coast" },
          { "tag": "genre", "op": "matches", "value": "(?i)^west.?coast" },
          { "tag": "genre", "op": "matches", "value": "(?i)^southern.?hip" },
          { "tag": "genre", "op": "matches", "value": "(?i)^abstract.?hip" }
        ]
      },
      "output": "Hip-Hop & Rap/{artist}/{album}/{track:02d} - {title}{ext}",
      "action": "move"
    },
    {
      "name": "R&B & Soul",
      "conditions": {
        "any": [
          { "tag": "genre", "op": "matches", "value": "(?i)^r.?.?b" },
          { "tag": "genre", "op": "matches", "value": "(?i)^rhythm.?and.?blues" },
          { "tag": "genre", "op": "matches", "value": "(?i)^soul" },
          { "tag": "genre", "op": "matches", "value": "(?i)^neo.?soul" },
          { "tag": "genre", "op": "matches", "value": "(?i)^funk" },
          { "tag": "genre", "op": "matches", "value": "(?i)^motown" },
          { "tag": "genre", "op": "matches", "value": "(?i)^new.?jack.?swing" },
          { "tag": "genre", "op": "matches", "value": "(?i)^quiet.?storm" }
        ]
      },
      "output": "R&B & Soul/{artist}/{album}/{track:02d} - {title}{ext}",
      "action": "move"
    },
    {
      "name": "Electronic",
      "conditions": {
        "any": [
          { "tag": "genre", "op": "matches", "value": "(?i)^electronic" },
          { "tag": "genre", "op": "matches", "value": "(?i)^edm" },
          { "tag": "genre", "op": "matches", "value": "(?i)^dance" },
          { "tag": "genre", "op": "matches", "value": "(?i)^house" },
          { "tag": "genre", "op": "matches", "value": "(?i)^techno" },
          { "tag": "genre", "op": "matches", "value": "(?i)^trance" },
          { "tag": "genre", "op": "matches", "value": "(?i)^dubstep" },
          { "tag": "genre", "op": "matches", "value": "(?i)^drum.?and.?bass" },
          { "tag": "genre", "op": "matches", "value": "(?i)^ambient" },
          { "tag": "genre", "op": "matches", "value": "(?i)^idm" },
          { "tag": "genre", "op": "matches", "value": "(?i)^breakbeat" },
          { "tag": "genre", "op": "matches", "value": "(?i)^garage" },
          { "tag": "genre", "op": "matches", "value": "(?i)^uk.?garage" },
          { "tag": "genre", "op": "matches", "value": "(?i)^2.?step" },
          { "tag": "genre", "op": "matches", "value": "(?i)^downtempo" },
          { "tag": "genre", "op": "matches", "value": "(?i)^trip.?hop" },
          { "tag": "genre", "op": "matches", "value": "(?i)^chillout" },
          { "tag": "genre", "op": "matches", "value": "(?i)^vaporwave" },
          { "tag": "genre", "op": "matches", "value": "(?i)^synthwave" },
          { "tag": "genre", "op": "matches", "value": "(?i)^electro" },
          { "tag": "genre", "op": "matches", "value": "(?i)^minimal" },
          { "tag": "genre", "op": "matches", "value": "(?i)^future.?bass" },
          { "tag": "genre", "op": "matches", "value": "(?i)^progressive.?house" },
          { "tag": "genre", "op": "matches", "value": "(?i)^deep.?house" },
          { "tag": "genre", "op": "matches", "value": "(?i)^tech.?house" }
        ]
      },
      "output": "Electronic/{artist}/{album}/{track:02d} - {title}{ext}",
      "action": "move"
    },
    {
      "name": "Jazz",
      "conditions": {
        "any": [
          { "tag": "genre", "op": "matches", "value": "(?i)^jazz" },
          { "tag": "genre", "op": "matches", "value": "(?i)^bebop" },
          { "tag": "genre", "op": "matches", "value": "(?i)^swing" },
          { "tag": "genre", "op": "matches", "value": "(?i)^fusion" },
          { "tag": "genre", "op": "matches", "value": "(?i)^smooth.?jazz" },
          { "tag": "genre", "op": "matches", "value": "(?i)^acid.?jazz" },
          { "tag": "genre", "op": "matches", "value": "(?i)^free.?jazz" },
          { "tag": "genre", "op": "matches", "value": "(?i)^cool.?jazz" },
          { "tag": "genre", "op": "matches", "value": "(?i)^latin.?jazz" },
          { "tag": "genre", "op": "matches", "value": "(?i)^bossa.?nova" },
          { "tag": "genre", "op": "matches", "value": "(?i)^big.?band" },
          { "tag": "genre", "op": "matches", "value": "(?i)^dixieland" },
          { "tag": "genre", "op": "matches", "value": "(?i)^ragtime" }
        ]
      },
      "output": "Jazz/{artist}/{album}/{track:02d} - {title}{ext}",
      "action": "move"
    },
    {
      "name": "Classical",
      "conditions": {
        "any": [
          { "tag": "genre", "op": "matches", "value": "(?i)^classical" },
          { "tag": "genre", "op": "matches", "value": "(?i)^orchestral" },
          { "tag": "genre", "op": "matches", "value": "(?i)^symphony" },
          { "tag": "genre", "op": "matches", "value": "(?i)^concerto" },
          { "tag": "genre", "op": "matches", "value": "(?i)^opera" },
          { "tag": "genre", "op": "matches", "value": "(?i)^baroque" },
          { "tag": "genre", "op": "matches", "value": "(?i)^romantic.?era" },
          { "tag": "genre", "op": "matches", "value": "(?i)^chamber" },
          { "tag": "genre", "op": "matches", "value": "(?i)^choral" },
          { "tag": "genre", "op": "matches", "value": "(?i)^sacred" },
          { "tag": "genre", "op": "matches", "value": "(?i)^gregorian" },
          { "tag": "genre", "op": "matches", "value": "(?i)^renaissance" },
          { "tag": "genre", "op": "matches", "value": "(?i)^minimalist" },
          { "tag": "genre", "op": "matches", "value": "(?i)^avant.?garde" }
        ]
      },
      "output": "Classical/{artist}/{album}/{track:02d} - {title}{ext}",
      "action": "move"
    },
    {
      "name": "Country & Folk",
      "conditions": {
        "any": [
          { "tag": "genre", "op": "matches", "value": "(?i)^country" },
          { "tag": "genre", "op": "matches", "value": "(?i)^folk" },
          { "tag": "genre", "op": "matches", "value": "(?i)^bluegrass" },
          { "tag": "genre", "op": "matches", "value": "(?i)^americana" },
          { "tag": "genre", "op": "matches", "value": "(?i)^outlaw.?country" },
          { "tag": "genre", "op": "matches", "value": "(?i)^alt.?country" },
          { "tag": "genre", "op": "matches", "value": "(?i)^honky.?tonk" },
          { "tag": "genre", "op": "matches", "value": "(?i)^bluegrass" },
          { "tag": "genre", "op": "matches", "value": "(?i)^singer.?songwriter" },
          { "tag": "genre", "op": "matches", "value": "(?i)^indie.?folk" },
          { "tag": "genre", "op": "matches", "value": "(?i)^neofolk" }
        ]
      },
      "output": "Country & Folk/{artist}/{album}/{track:02d} - {title}{ext}",
      "action": "move"
    },
    {
      "name": "Blues",
      "conditions": {
        "any": [
          { "tag": "genre", "op": "matches", "value": "(?i)^blues" },
          { "tag": "genre", "op": "matches", "value": "(?i)^delta.?blues" },
          { "tag": "genre", "op": "matches", "value": "(?i)^chicago.?blues" },
          { "tag": "genre", "op": "matches", "value": "(?i)^electric.?blues" },
          { "tag": "genre", "op": "matches", "value": "(?i)^piedmont" },
          { "tag": "genre", "op": "matches", "value": "(?i)^texas.?blues" }
        ]
      },
      "output": "Blues/{artist}/{album}/{track:02d} - {title}{ext}",
      "action": "move"
    },
    {
      "name": "Reggae & Caribbean",
      "conditions": {
        "any": [
          { "tag": "genre", "op": "matches", "value": "(?i)^reggae" },
          { "tag": "genre", "op": "matches", "value": "(?i)^ska" },
          { "tag": "genre", "op": "matches", "value": "(?i)^dancehall" },
          { "tag": "genre", "op": "matches", "value": "(?i)^dub" },
          { "tag": "genre", "op": "matches", "value": "(?i)^rocksteady" },
          { "tag": "genre", "op": "matches", "value": "(?i)^reggaeton" },
          { "tag": "genre", "op": "matches", "value": "(?i)^calypso" },
          { "tag": "genre", "op": "matches", "value": "(?i)^soca" }
        ]
      },
      "output": "Reggae & Caribbean/{artist}/{album}/{track:02d} - {title}{ext}",
      "action": "move"
    },
    {
      "name": "Latin",
      "conditions": {
        "any": [
          { "tag": "genre", "op": "matches", "value": "(?i)^latin" },
          { "tag": "genre", "op": "matches", "value": "(?i)^salsa" },
          { "tag": "genre", "op": "matches", "value": "(?i)^bachata" },
          { "tag": "genre", "op": "matches", "value": "(?i)^merengue" },
          { "tag": "genre", "op": "matches", "value": "(?i)^cumbia" },
          { "tag": "genre", "op": "matches", "value": "(?i)^samba" },
          { "tag": "genre", "op": "matches", "value": "(?i)^bossa.?nova" },
          { "tag": "genre", "op": "matches", "value": "(?i)^reggaeton" },
          { "tag": "genre", "op": "matches", "value": "(?i)^dembow" },
          { "tag": "genre", "op": "matches", "value": "(?i)^norte" },
          { "tag": "genre", "op": "matches", "value": "(?i)^mariachi" },
          { "tag": "genre", "op": "matches", "value": "(?i)^ranchera" },
          { "tag": "genre", "op": "matches", "value": "(?i)^tango" },
          { "tag": "genre", "op": "matches", "value": "(?i)^flamenco" },
          { "tag": "genre", "op": "matches", "value": "(?i)^latin.?pop" },
          { "tag": "genre", "op": "matches", "value": "(?i)^latin.?trap" },
          { "tag": "genre", "op": "matches", "value": "(?i)^latin.?rock" },
          { "tag": "genre", "op": "matches", "value": "(?i)^latin.?alternative" }
        ]
      },
      "output": "Latin/{artist}/{album}/{track:02d} - {title}{ext}",
      "action": "move"
    },
    {
      "name": "Soundtracks & Scores",
      "conditions": {
        "any": [
          { "tag": "genre", "op": "matches", "value": "(?i)^soundtrack" },
          { "tag": "genre", "op": "matches", "value": "(?i)^score" },
          { "tag": "genre", "op": "matches", "value": "(?i)^film.?score" },
          { "tag": "genre", "op": "matches", "value": "(?i)^video.?game.?music" },
          { "tag": "genre", "op": "matches", "value": "(?i)^game.?soundtrack" },
          { "tag": "genre", "op": "matches", "value": "(?i)^cinematic" },
          { "tag": "genre", "op": "matches", "value": "(?i)^theme" },
          { "tag": "genre", "op": "matches", "value": "(?i)^musical" },
          { "tag": "genre", "op": "matches", "value": "(?i)^show.?tune" },
          { "tag": "genre", "op": "matches", "value": "(?i)^broadway" }
        ]
      },
      "output": "Soundtracks & Scores/{artist}/{album}/{track:02d} - {title}{ext}",
      "action": "move"
    },
    {
      "name": "World & International",
      "conditions": {
        "any": [
          { "tag": "genre", "op": "matches", "value": "(?i)^world" },
          { "tag": "genre", "op": "matches", "value": "(?i)^international" },
          { "tag": "genre", "op": "matches", "value": "(?i)^african" },
          { "tag": "genre", "op": "matches", "value": "(?i)^afrobeat" },
          { "tag": "genre", "op": "matches", "value": "(?i)^highlife" },
          { "tag": "genre", "op": "matches", "value": "(?i)^mbira" },
          { "tag": "genre", "op": "matches", "value": "(?i)^rai" },
          { "tag": "genre", "op": "matches", "value": "(?i)^bhangra" },
          { "tag": "genre", "op": "matches", "value": "(?i)^bollywood" },
          { "tag": "genre", "op": "matches", "value": "(?i)^carnatic" },
          { "tag": "genre", "op": "matches", "value": "(?i)^hindustani" },
          { "tag": "genre", "op": "matches", "value": "(?i)^gamelan" },
          { "tag": "genre", "op": "matches", "value": "(?i)^celtic" },
          { "tag": "genre", "op": "matches", "value": "(?i)^klezmer" },
          { "tag": "genre", "op": "matches", "value": "(?i)^polka" },
          { "tag": "genre", "op": "matches", "value": "(?i)^zydeco" },
          { "tag": "genre", "op": "matches", "value": "(?i)^cajun" }
        ]
      },
      "output": "World & International/{artist}/{album}/{track:02d} - {title}{ext}",
      "action": "move"
    },
    {
      "name": "Christian & Gospel",
      "conditions": {
        "any": [
          { "tag": "genre", "op": "matches", "value": "(?i)^christian" },
          { "tag": "genre", "op": "matches", "value": "(?i)^gospel" },
          { "tag": "genre", "op": "matches", "value": "(?i)^worship" },
          { "tag": "genre", "op": "matches", "value": "(?i)^praise" },
          { "tag": "genre", "op": "matches", "value": "(?i)^contemporary.?christian" },
          { "tag": "genre", "op": "matches", "value": "(?i)^southern.?gospel" },
          { "tag": "genre", "op": "matches", "value": "(?i)^spiritual" },
          { "tag": "genre", "op": "matches", "value": "(?i)^hymn" }
        ]
      },
      "output": "Christian & Gospel/{artist}/{album}/{track:02d} - {title}{ext}",
      "action": "move"
    },
    {
      "name": "Comedy & Spoken Word",
      "conditions": {
        "any": [
          { "tag": "genre", "op": "matches", "value": "(?i)^comedy" },
          { "tag": "genre", "op": "matches", "value": "(?i)^spoken.?word" },
          { "tag": "genre", "op": "matches", "value": "(?i)^comic" },
          { "tag": "genre", "op": "matches", "value": "(?i)^stand.?up" },
          { "tag": "genre", "op": "matches", "value": "(?i)^podcast" },
          { "tag": "genre", "op": "matches", "value": "(?i)^audiobook" },
          { "tag": "genre", "op": "matches", "value": "(?i)^story" },
          { "tag": "genre", "op": "matches", "value": "(?i)^poetry" }
        ]
      },
      "output": "Comedy & Spoken Word/{artist}/{album}/{track:02d} - {title}{ext}",
      "action": "move"
    },
    {
      "name": "Children's & Holiday",
      "conditions": {
        "any": [
          { "tag": "genre", "op": "matches", "value": "(?i)^children" },
          { "tag": "genre", "op": "matches", "value": "(?i)^kids" },
          { "tag": "genre", "op": "matches", "value": "(?i)^lullaby" },
          { "tag": "genre", "op": "matches", "value": "(?i)^nursery" },
          { "tag": "genre", "op": "matches", "value": "(?i)^holiday" },
          { "tag": "genre", "op": "matches", "value": "(?i)^christmas" },
          { "tag": "genre", "op": "matches", "value": "(?i)^hanukkah" },
          { "tag": "genre", "op": "matches", "value": "(?i)^easter" },
          { "tag": "genre", "op": "matches", "value": "(?i)^seasonal" },
          { "tag": "genre", "op": "matches", "value": "(?i)^novelty" }
        ]
      },
      "output": "Children's & Holiday/{artist}/{album}/{track:02d} - {title}{ext}",
      "action": "move"
    }
  ],
  "defaults": {
    "output": "Other/{artist}/{album}/{track:02d} - {title}{ext}",
    "action": "move"
  },
  "settings": {
    "output_base_dir": "~/Music/Organized",
    "overwrite": "skip",
    "delete_empty_sources": false,
    "follow_symlinks": false,
    "supported_extensions": [
      ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".wma"
    ]
  }
}
"""


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_config(path: Optional[Path] = None) -> Config:
    """Load configuration from *path* or discover it via
    :data:`CONFIG_SEARCH_PATHS`.

    Returns a default :class:`Config` when no file is found.
    """
    if path is not None:
        return _parse_file(path)
    for search_path in _config_search_paths():
        if search_path.exists():
            logger.info("Loading config from %s", search_path)
            return _parse_file(search_path)
    logger.info("No config file found; using default rules")
    return Config()


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
