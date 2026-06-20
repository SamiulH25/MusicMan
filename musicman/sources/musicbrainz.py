"""Metadata source that queries the MusicBrainz API."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

import musicbrainzngs

from ..models import MusicTags
from . import MetadataResult, MetadataSource

logger = logging.getLogger(__name__)

# --- Rate limiter ---

_last_request: float = 0.0
_MIN_INTERVAL = 1.0  # MusicBrainz allows ~1 req/sec


def _rate_limit() -> None:
    global _last_request
    now = time.monotonic()
    elapsed = now - _last_request
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_request = time.monotonic()


# --- Tag scoring ---

# Tags that describe a role or format rather than a genre.
_NON_GENRE_TAGS = frozenset({
    "live", "compilation", "remix", "cover", "instrumental", "acoustic",
    "electric", "unplugged", "demo", "bootleg", "single", "ep", "album",
    "mixtape", "soundtrack", "score", "cast", "female vocalist",
    "male vocalist", "screaming", "death growl", "falsetto", "spoken word",
    "instrumental rock", "instrumental hip hop", "instrumental pop",
    "christmas", "holiday", "easter", "children's music", "kids",
    "novelty", "parody", "tribute", "cover", "remix", "reissue",
    "remastered", "bonus track", "hidden track", "outtake", "b-side",
    "promo", "sampler", "field recording", "interview", "live album",
    "studio album", "compilation album", "audio drama", "podcast",
    "ringtone", "jingle", "theme music", "signature tune", "fan club",
    "self-released", "independent", "underground", "indie",
    "favorite", "seen live", "own", "want", "collection",
    "experimental", "concept album", "psychedelic", "trippy",
    "mellow", "chill", "relaxing", "energetic", "aggressive",
    "heavy", "melodic", "catchy", "complex", "simple",
    "beautiful", "dark", "happy", "sad", "angry",
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


# --- MusicBrainz source ---


class MusicBrainzSource(MetadataSource):
    """Fetch metadata from MusicBrainz using existing artist + title."""

    name = "musicbrainz"

    def __init__(
        self,
        app_name: str = "musicman",
        app_version: str = "0.1.0",
        contact: str = "",
    ) -> None:
        musicbrainzngs.set_useragent(app_name, app_version, contact)

    def fetch(self, path: Path, existing: MusicTags) -> MetadataResult:
        artist = existing.artist
        title = existing.title
        if not artist or not title:
            return MetadataResult()

        logger.debug("Looking up %s - %s on MusicBrainz", artist, title)

        try:
            return self._search(artist, title)
        except Exception as exc:
            logger.warning("MusicBrainz lookup failed for %s - %s: %s",
                           artist, title, exc)
            return MetadataResult()

    def _search(self, artist: str, title: str) -> MetadataResult:
        _rate_limit()
        result = musicbrainzngs.search_recordings(
            artist=artist, recording=title, limit=1,
        )
        rec_list = result.get("recording-list")
        if not rec_list:
            return MetadataResult()

        rec = rec_list[0]
        rid = rec["id"]
        result = MetadataResult(source="musicbrainz")

        # Title (MusicBrainz often has cleaner titles)
        result.title = rec.get("title") or None

        # Artist
        artist_credit = rec.get("artist-credit")
        if artist_credit:
            result.artist = artist_credit[0].get("artist", {}).get("name")

        # Get full details with tags and release info
        _rate_limit()
        detail = musicbrainzngs.get_recording_by_id(
            rid, includes=["tags", "artists", "releases"],
        )
        recording = detail.get("recording", {})

        # Genre from tags on the recording
        genre = None
        if "tag-list" in recording:
            genre = _best_genre_tag(recording["tag-list"])

        # Release-level tags and metadata (use first release)
        if not genre:
            release_list = recording.get("release-list", [])
            if release_list:
                _rate_limit()
                rdetail = musicbrainzngs.get_release_by_id(
                    release_list[0]["id"], includes=["tags"],
                )
                release = rdetail.get("release", {})
                if "tag-list" in release:
                    genre = _best_genre_tag(release["tag-list"])
                if not result.album:
                    result.album = release.get("title")

                # Year
                date = release.get("date", "")
                if date:
                    result.date = date[:4]

        if not genre:
            # Fall back to artist-level tags
            artist_id = artist_credit[0]["artist"]["id"] if artist_credit else None
            if artist_id:
                _rate_limit()
                adetail = musicbrainzngs.get_artist_by_id(
                    artist_id, includes=["tags"],
                )
                if "tag-list" in adetail.get("artist", {}):
                    genre = _best_genre_tag(adetail["artist"]["tag-list"])

        if genre:
            result.genre = genre

        return result
