from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterator

import mutagen

from .models import MusicTags

logger = logging.getLogger(__name__)

# Map extension → mutagen top-level type for fast bail-out.
EXTENSIONS_MAP: dict[str, str] = {
    ".mp3":  "MPEG",
    ".flac": "FLAC",
    ".m4a":  "MP4",
    ".aac":  "MP4",
    ".ogg":  "OggVorbis",
    ".opus": "OggOpus",
    ".wav":  "Wave",
    ".wma":  "ASF",
}


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def scan_files(
    sources: list[Path],
    extensions: list[str] | None = None,
    follow_symlinks: bool = False,
) -> Iterator[Path]:
    """Walk *sources* (files and/or directories) and yield audio file paths.

    Only files whose extension (case-insensitive) is in *extensions* (or
    ``EXTENSIONS_MAP`` when *extensions* is ``None``) are yielded.
    """
    allowed = set(
        ext.lower() for ext in (extensions or list(EXTENSIONS_MAP))
    )

    for src in sources:
        src = src.resolve()
        if src.is_file():
            if src.suffix.lower() in allowed:
                yield src
            continue

        # Directory – walk recursively.
        for path in src.rglob("*"):
            if not path.is_file():
                continue
            if not follow_symlinks and path.is_symlink():
                continue
            if path.suffix.lower() in allowed:
                yield path


# ---------------------------------------------------------------------------
# Tag reading
# ---------------------------------------------------------------------------

class UnsupportedFileError(ValueError):
    """Raised for file types that cannot be read by mutagen."""


def read_tags(path: Path) -> MusicTags:
    """Read and normalise metadata from *path* using mutagen.

    Returns a :class:`MusicTags` instance.  Missing fields are ``None``.

    Raises
    ------
    UnsupportedFileError
        File type is not in ``EXTENSIONS_MAP``.
    mutagen.MutagenError
        File is corrupt or unreadable.
    """
    ext = path.suffix.lower()
    if ext not in EXTENSIONS_MAP:
        raise UnsupportedFileError(
            f"Unsupported file type {ext!r}: {path.name}"
        )

    audio = mutagen.File(str(path), easy=True)
    if audio is None:
        # mutagen returned None for MP3-without-ID3, FLAC-without-VorbisComment …
        # Return empty tags rather than crashing.
        return MusicTags(raw={})

    raw_tags: dict[str, list[str]] = dict(audio.tags or {})
    info = audio.info

    tags = MusicTags(
        title=_first(raw_tags, "title"),
        artist=_first(raw_tags, "artist"),
        album=_first(raw_tags, "album"),
        albumartist=_first(raw_tags, "albumartist"),
        genre=_first(raw_tags, "genre"),
        date=_parse_year(_first(raw_tags, "date")),
        track=_parse_track(_first(raw_tags, "tracknumber")),
        track_total=_parse_track_total(_first(raw_tags, "tracknumber")),
        disc=_parse_int(_first(raw_tags, "discnumber")),
        composer=_first(raw_tags, "composer"),
        duration=info.length if info is not None else None,
        bitrate=getattr(info, "bitrate", None),
        raw=_raw_dict(raw_tags),
    )

    # Fallback: try the non-easy "date" key (some formats store 'TDRC' etc.)
    if tags.date is None:
        full = mutagen.File(str(path))
        if full is not None and hasattr(full, "tags") and full.tags is not None:
            for key in ("TDRC", "©day", "date", "year"):
                val = full.tags.get(key)
                if val is not None:
                    parsed = _parse_year(str(val))
                    if parsed is not None:
                        tags.date = parsed
                        break

    return tags


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _first(d: dict[str, list[str]], key: str) -> str | None:
    values = d.get(key)
    if values and len(values) > 0:
        return values[0]
    return None


def _raw_dict(d: dict[str, list[str]]) -> dict[str, Any]:
    """Flatten ``{k: [v]}`` → ``{k: v}`` for the ``raw`` field."""
    return {k: v[0] if len(v) == 1 else v for k, v in d.items()}


def _parse_year(value: str | None) -> int | None:
    if value is None:
        return None
    # "1987", "1987-01-01", "1987/01/01" → 1987
    for sep in ("-", "/", " "):
        if sep in value:
            value = value.split(sep)[0]
            break
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _parse_track(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value.split("/")[0])
    except (ValueError, TypeError, IndexError):
        return None


def _parse_track_total(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parts = value.split("/")
        if len(parts) > 1:
            return int(parts[1])
    except (ValueError, TypeError, IndexError):
        pass
    return None


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value.split("/")[0])
    except (ValueError, TypeError, IndexError):
        return None


def format_duration(seconds: float) -> str:
    """Return ``M:SS`` string."""
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}:{secs:02d}"


# ---------------------------------------------------------------------------
# Tag writing
# ---------------------------------------------------------------------------

class UnsupportedFormatError(ValueError):
    """Raised when mutagen can't save this file format."""


def write_tags(
    path: Path,
    *,
    genre: str | None = None,
    title: str | None = None,
    artist: str | None = None,
    album: str | None = None,
    albumartist: str | None = None,
    date: str | None = None,
) -> None:
    """Write metadata tags to *path* using mutagen's easy API.

    Only non-``None`` values are written; existing tags are preserved.

    Raises
    ------
    UnsupportedFormatError
        Format doesn't support tag writing.
    mutagen.MutagenError
        File is corrupt or write failed.
    """
    ext = path.suffix.lower()
    if ext not in EXTENSIONS_MAP:
        raise UnsupportedFileError(
            f"Unsupported file type {ext!r}: {path.name}"
        )

    audio = mutagen.File(str(path), easy=True)
    if audio is None:
        raise UnsupportedFormatError(
            f"Cannot open {path.name} for tag writing"
        )

    changed = False
    if genre is not None:
        audio["genre"] = genre
        changed = True
    if title is not None:
        audio["title"] = title
        changed = True
    if artist is not None:
        audio["artist"] = artist
        changed = True
    if album is not None:
        audio["album"] = album
        changed = True
    if albumartist is not None:
        audio["albumartist"] = albumartist
        changed = True
    if date is not None:
        audio["date"] = date
        changed = True

    if changed:
        audio.save()
