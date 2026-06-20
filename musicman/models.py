from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional


# ---------- Config models ----------


@dataclass
class Condition:
    tag: str
    op: str
    value: Any


@dataclass
class Conditions:
    all: Optional[list[Condition | Conditions]] = None
    any: Optional[list[Condition | Conditions]] = None


@dataclass
class Rule:
    name: str
    conditions: Conditions
    output: str
    action: Literal["copy", "move", "symlink"] = "move"


@dataclass
class Defaults:
    output: str = "Unsorted/{artist} - {title}{ext}"
    action: Literal["copy", "move", "symlink"] = "move"


@dataclass
class Settings:
    output_base_dir: str = "~/Music/Organized"
    overwrite: Literal["skip", "overwrite", "rename"] = "skip"
    delete_empty_sources: bool = False
    follow_symlinks: bool = False
    supported_extensions: list[str] = field(default_factory=lambda: [
        ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".wav", ".wma",
    ])


@dataclass
class Config:
    rules: list[Rule] = field(default_factory=list)
    defaults: Defaults = field(default_factory=Defaults)
    settings: Settings = field(default_factory=Settings)


# ---------- Runtime models ----------


@dataclass
class MusicTags:
    """Normalised music metadata read from a file via mutagen."""

    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    albumartist: Optional[str] = None
    genre: Optional[str] = None
    date: Optional[int] = None
    track: Optional[int] = None
    track_total: Optional[int] = None
    disc: Optional[int] = None
    disc_total: Optional[int] = None
    composer: Optional[str] = None
    duration: Optional[float] = None
    bitrate: Optional[int] = None
    raw: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str) -> Any:
        """Case-insensitive lookup; checks known fields then raw tags."""
        normalized = key.lower()
        known = {
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "albumartist": self.albumartist,
            "genre": self.genre,
            "date": self.date,
            "year": self.date,
            "track": self.track,
            "track_total": self.track_total,
            "disc": self.disc,
            "disc_total": self.disc_total,
            "composer": self.composer,
            "duration": self.duration,
            "bitrate": self.bitrate,
        }
        if normalized in known:
            return known[normalized]
        return self.raw.get(normalized)


@dataclass
class FileResult:
    """Outcome of categorising a single file."""

    source: Path
    destination: Optional[Path] = None
    rule: Optional[str] = None
    action: Optional[str] = None
    tags: Optional[MusicTags] = None
    error: Optional[str] = None
    skipped: bool = False


@dataclass
class EnrichResult:
    """Outcome of enriching a single file's tags."""

    source: Path
    rule: Optional[str] = None
    tags_written: list[str] = field(default_factory=list)
    error: Optional[str] = None
    skipped: bool = False
