from __future__ import annotations

import re
from pathlib import Path

from .models import MusicTags

# Mapping from template placeholder → MusicTags field name.
# Lower-case keys; checked case-insensitively in the template.
TAG_ALIASES: dict[str, str] = {
    "title":       "title",
    "artist":      "artist",
    "album":       "album",
    "albumartist": "albumartist",
    "genre":       "genre",
    "year":        "date",
    "date":        "date",
    "track":       "track",
    "track_total": "track_total",
    "disc":        "disc",
    "disc_total":  "disc_total",
    "composer":    "composer",
    "duration":    "duration",
    "bitrate":     "bitrate",
    "ext":         "__ext__",       # special — injected from source suffix
}

_PLACEHOLDER_RE = re.compile(r"\{(\w+)(?::(.+?))?\}")


def format_path(template: str, tags: MusicTags, source_ext: str) -> Path:
    """Expand a path *template* using *tags* and return a relative
    :class:`~pathlib.Path`.

    Supports Python format-spec mini-language after a colon::
        {track:02d}
        {date}

    ``{ext}`` is replaced with *source_ext* (e.g. ``.mp3``).

    Missing or ``None`` tag values are replaced with ``"Unknown"``.

    Forward-slashes in tag values are replaced with ``" - "`` to prevent
    unintended sub-directory injection.
    """
    def _replacer(m: re.Match) -> str:
        name = m.group(1).lower()
        fmt = m.group(2) or ""

        # Special case: source extension.
        if name == "ext":
            return source_ext

        # Resolve tag alias → MusicTags field name → value.
        field = TAG_ALIASES.get(name)
        if field is None:
            return f"{{{m.group(1)}}}"  # leave unknown placeholders as-is

        value = tags.get(field) if field != "__ext__" else source_ext
        if value is None:
            value = "Unknown"

        # Apply format spec BEFORE converting to string
        # so numeric format specs like :02d work on int values.
        if fmt:
            try:
                value = format(value, fmt)
            except (ValueError, TypeError):
                pass  # fall back to un-formatted value

        # Now convert to string and sanitise.
        if isinstance(value, float):
            value = str(round(value, 2))
        else:
            value = str(value)
        value = value.replace("/", " - ")  # prevent path injection

        return value

    expanded = _PLACEHOLDER_RE.sub(_replacer, template)
    return Path(expanded)


def validate_template(template: str) -> list[str]:
    """Return a list of unknown placeholders in *template*.

    An empty list means the template is valid.
    """
    unknowns: list[str] = []
    for m in _PLACEHOLDER_RE.finditer(template):
        name = m.group(1).lower()
        if name != "ext" and name not in TAG_ALIASES:
            unknowns.append(m.group(1))
    return unknowns
