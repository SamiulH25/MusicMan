"""Metadata source abstraction for enriching music files."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..models import MusicTags


@dataclass
class MetadataResult:
    """Tags fetched from a metadata source."""

    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    genre: Optional[str] = None
    date: Optional[str] = None
    albumartist: Optional[str] = None
    source: str = ""


class MetadataSource:
    """Base class for metadata sources.

    Subclasses implement ``fetch()`` to return tags for a given file
    based on its existing metadata.
    """

    name: str = "base"

    def fetch(self, path: Path, existing: MusicTags) -> MetadataResult:
        """Return enriched metadata for *path*.

        *existing* contains whatever tags the file already has.
        Return an empty ``MetadataResult()`` if no data can be found.
        """
        raise NotImplementedError


def guess_tags(
    path: Path,
    existing: MusicTags,
    sources: list[MetadataSource],
) -> MetadataResult:
    """Try each *sources* in order until one returns data."""
    for source in sources:
        result = source.fetch(path, existing)
        if result.title or result.artist or result.album or result.genre or result.date:
            return result
    return MetadataResult()
