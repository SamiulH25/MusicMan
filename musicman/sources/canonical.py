"""Metadata source using the local MusicBrainz canonical dump.

Queries the local SQLite database (built from the canonical dump) for
artist and recording MBIDs, then fetches tags from the MusicBrainz API
using those IDs instead of searching by name.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

import musicbrainzngs

from ..db import CanonicalDB
from ..models import MusicTags
from . import MetadataResult, MetadataSource

logger = logging.getLogger(__name__)

# Rate limiter for API calls
_last_request: float = 0.0
_MIN_INTERVAL = 1.0


def _rate_limit() -> None:
    global _last_request
    now = time.monotonic()
    elapsed = now - _last_request
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_request = now


_NON_GENRE_TAGS = frozenset({
    "live", "compilation", "remix", "cover", "instrumental", "acoustic",
    "electric", "unplugged", "demo", "bootleg", "single", "ep", "album",
    "mixtape", "soundtrack", "score", "cast", "spoken word",
    "christmas", "holiday", "novelty", "parody", "tribute",
    "remastered", "bonus track", "b-side", "promo", "sampler",
    "interview", "podcast", "ringtone", "jingle",
    "favorite", "seen live", "own", "want", "collection", "indie",
})


def _best_genre_tag(tags: list[dict]) -> Optional[str]:
    """Pick the highest-count tag that looks like a genre."""
    best: tuple[str, int] | None = None
    for t in tags:
        name: str = t.get("name", "").lower().strip()
        count: int = int(t.get("count", 0))
        if count < 2:
            continue
        if name in _NON_GENRE_TAGS:
            continue
        if best is None or count > best[1]:
            best = (t["name"], count)
    return best[0] if best else None


class CanonicalDumpSource(MetadataSource):
    """Metadata source that queries the local canonical dump + MusicBrainz API."""

    name = "canonical"

    def __init__(
        self,
        db_path: Path | None = None,
        app_name: str = "musicman",
        app_version: str = "0.1.0",
        contact: str = "",
    ) -> None:
        self.db = CanonicalDB(db_path) if db_path else CanonicalDB()
        musicbrainzngs.set_useragent(app_name, app_version, contact)

    def fetch(self, path: Path, existing: MusicTags) -> MetadataResult:
        artist = existing.artist
        title = existing.title
        if not artist or not title:
            return MetadataResult()

        # Step 1: Look up artist in local DB to get MBID
        artist_mbid = self.db.lookup_artist(artist)
        recording = None

        if artist_mbid:
            # Step 2: Find recording by artist + title
            recording = self.db.lookup_recording(artist, title)

        # Step 3: If we have an MBID, query the API for tags
        mb_id = recording["recording_mbid"] if recording else None
        if not mb_id and artist_mbid:
            # Try getting artist-level tags
            return self._fetch_artist_tags(artist_mbid, artist)

        if mb_id:
            return self._fetch_recording_tags(mb_id, recording)

        return MetadataResult()

    def _fetch_artist_tags(
        self, artist_mbid: str, artist_name: str,
    ) -> MetadataResult:
        _rate_limit()
        try:
            detail = musicbrainzngs.get_artist_by_id(
                artist_mbid, includes=["tags"],
            )
            if "tag-list" in detail.get("artist", {}):
                genre = _best_genre_tag(detail["artist"]["tag-list"])
                if genre:
                    return MetadataResult(genre=genre, source=self.name)
        except Exception as exc:
            logger.debug("Artist tag fetch failed: %s", exc)
        return MetadataResult()

    def _fetch_recording_tags(
        self, recording_mbid: str, recording: dict,
    ) -> MetadataResult:
        result = MetadataResult(source=self.name)
        if recording.get("recording_name"):
            result.title = recording["recording_name"]
        if recording.get("release_name"):
            result.album = recording["release_name"]
        if recording.get("artist_name"):
            result.artist = recording["artist_name"]

        _rate_limit()
        try:
            detail = musicbrainzngs.get_recording_by_id(
                recording_mbid, includes=["tags", "releases"],
            )
            rec = detail.get("recording", {})

            # Tags on the recording
            if "tag-list" in rec:
                genre = _best_genre_tag(rec["tag-list"])
                if genre:
                    result.genre = genre
                    return result

            # Tags on the first release
            if "release-list" in rec:
                release = rec["release-list"][0]
                if release.get("date", ""):
                    result.date = release["date"][:4]
                _rate_limit()
                rdetail = musicbrainzngs.get_release_by_id(
                    release["id"], includes=["tags"],
                )
                if "tag-list" in rdetail.get("release", {}):
                    genre = _best_genre_tag(rdetail["release"]["tag-list"])
                    if genre:
                        result.genre = genre
                        return result
        except Exception as exc:
            logger.debug("Recording tag fetch failed: %s", exc)

        return result
