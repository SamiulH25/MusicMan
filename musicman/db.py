"""Local SQLite database built from the MusicBrainz canonical dump."""

from __future__ import annotations

import csv
import json
import logging
import sqlite3
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default location for the local DB
DEFAULT_DB_DIR = Path.home() / ".config" / "musicman"
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "canonical.db"


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def import_canonical_dump(
    csv_path: Path,
    db_path: Path = DEFAULT_DB_PATH,
    *,
    max_rows: int | None = None,
) -> int:
    """Import the canonical dump CSV into a SQLite database.

    Creates tables for artists and recordings with indexes for fast
    lookup.  Returns the number of rows imported.

    *max_rows* is useful for testing with a subset.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA cache_size=-8000000")  # ~8GB cache
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA locking_mode=EXCLUSIVE")

    _create_schema(conn)

    imported = 0
    t0 = time.monotonic()
    conn.execute("BEGIN TRANSACTION")
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        batch: list[tuple] = []
        for row in reader:
            artist_mbids = row.get("artist_mbids", "") or ""
            artist_mbid = artist_mbids.split("|")[0] if artist_mbids else ""

            batch.append((
                int(row["id"]),
                artist_mbid,
                row.get("artist_credit_name", ""),
                row.get("release_mbid", ""),
                row.get("release_name", ""),
                row.get("recording_mbid", ""),
                row.get("recording_name", ""),
                int(row.get("score", 0)),
            ))
            imported += 1

            if len(batch) >= 50000:
                conn.executemany("""
                    INSERT INTO recordings (id, artist_mbid, artist_name, release_mbid,
                                            release_name, recording_mbid, recording_name, score)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, batch)
                # Also insert unique artists
                artists_seen = set()
                for row_b in batch:
                    key = (row_b[1], row_b[2])
                    if key not in artists_seen:
                        artists_seen.add(key)
                        conn.execute(
                            "INSERT OR IGNORE INTO artists (artist_mbid, artist_name) VALUES (?, ?)",
                            (row_b[1], row_b[2]),
                        )
                batch = []

            if max_rows and imported >= max_rows:
                break

        if batch:
            conn.executemany("""
                INSERT INTO recordings (id, artist_mbid, artist_name, release_mbid,
                                        release_name, recording_mbid, recording_name, score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, batch)
            artists_seen2 = set()
            for row_b in batch:
                key = (row_b[1], row_b[2])
                if key not in artists_seen2:
                    artists_seen2.add(key)
                    conn.execute(
                        "INSERT OR IGNORE INTO artists (artist_mbid, artist_name) VALUES (?, ?)",
                        (row_b[1], row_b[2]),
                    )

    conn.execute("COMMIT")
    _create_indexes(conn)
    conn.close()

    elapsed = time.monotonic() - t0
    logger.info(
        "Imported %d rows in %.1fs (%.0f rows/s)",
        imported, elapsed, imported / elapsed if elapsed else 0,
    )
    return imported


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS artists (
            artist_mbid TEXT NOT NULL,
            artist_name TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS recordings (
            id INTEGER PRIMARY KEY,
            artist_mbid TEXT NOT NULL,
            artist_name TEXT NOT NULL,
            recording_mbid TEXT NOT NULL,
            recording_name TEXT NOT NULL,
            release_mbid TEXT NOT NULL,
            release_name TEXT NOT NULL,
            score INTEGER DEFAULT 0
        );
    """)


def _create_indexes(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS idx_artists_name ON artists(artist_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_artists_mbid ON artists(artist_mbid)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_recordings_artist ON recordings(artist_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_recordings_name ON recordings(recording_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_recordings_mbid ON recordings(recording_mbid)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_recordings_combined ON recordings(artist_name, recording_name)")


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

class CanonicalDB:
    """Query the local canonical MusicBrainz database."""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path

    def lookup_artist(self, name: str) -> Optional[str]:
        """Return the artist MBID for *name*, or ``None``."""
        if not self.db_path.exists():
            return None
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT artist_mbid FROM artists WHERE artist_name = ? LIMIT 1",
                (name,),
            ).fetchone()
            return row["artist_mbid"] if row else None
        finally:
            conn.close()

    def search_artist(self, name: str, limit: int = 10) -> list[dict]:
        """Search artists by name (LIKE match), return up to *limit* rows."""
        if not self.db_path.exists():
            return []
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT DISTINCT artist_name, artist_mbid FROM artists "
                "WHERE artist_name LIKE ? ORDER BY artist_name LIMIT ?",
                (f"%{name}%", limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Build rules from MusicBrainz genre tags
# ---------------------------------------------------------------------------

# Map MusicBrainz tag names to our genre categories.
# Keys are lowercased; values are rule names from default-rules.json.
GENRE_MAP: dict[str, str] = {}

# Category -> tag patterns to match
_CATEGORY_TAGS: dict[str, list[str]] = {
    "Pop": ["pop", "synthpop", "synth pop", "k-pop", "kpop", "dance-pop", "teen pop", "power pop", "indie pop", "dream pop", "j-pop", "c-pop", "mandopop", "cantopop"],
    "Rock": ["rock", "alternative", "indie", "punk", "grunge", "emo", "progressive rock", "psychedelic", "post-rock", "garage rock", "hard rock", "classic rock", "stoner rock", "surf rock", "new wave", "ska punk", "pop punk", "post-punk", "noise rock", "math rock"],
    "Metal": ["metal", "heavy metal", "death metal", "black metal", "doom metal", "thrash metal", "power metal", "metalcore", "deathcore", "nu metal", "progressive metal", "speed metal", "symphonic metal", "folk metal", "groove metal", "industrial metal", "grindcore", "sludge", "djent"],
    "Hip-Hop & Rap": ["hip-hop", "hip hop", "rap", "trap", "grime", "boom bap", "conscious hip hop", "gangsta rap", "hardcore hip hop", "turntablism", "underground hip hop"],
    "R&B & Soul": ["r&b", "r and b", "soul", "neo soul", "funk", "motown", "quiet storm", "new jack swing", "contemporary r&b", "gospel soul"],
    "Electronic": ["electronic", "edm", "dance", "house", "techno", "trance", "dubstep", "drum and bass", "drum & bass", "dnb", "ambient", "idm", "electro", "synthwave", "vaporwave", "chiptune", "glitch", "breakbeat", "downtempo", "trip-hop", "trip hop", "deep house", "tropical house", "progressive house", "progressive trance", "hardstyle", "happy hardcore", "uk garage", "lo-fi", "lofi"],
    "Jazz": ["jazz", "bebop", "swing", "fusion", "bossa nova", "ragtime", "smooth jazz", "free jazz", "cool jazz", "hard bop", "modal jazz", "latin jazz", "jazz funk", "jazz fusion", "acid jazz", "contemporary jazz"],
    "Classical": ["classical", "orchestral", "symphony", "opera", "baroque", "chamber music", "choral", "romantic", "contemporary classical", "minimalism", "avant-garde", "liturgical", "neoclassical"],
    "Country & Folk": ["country", "folk", "bluegrass", "americana", "country rock", "outlaw country", "nashville", "honky tonk", "singer-songwriter", "indie folk", "celtic folk", "traditional folk", "folk rock", "country pop", "country folk"],
    "Blues": ["blues", "delta blues", "chicago blues", "electric blues", "blues rock", "texas blues", "piedmont blues", "jump blues", "blues fusion"],
    "Reggae & Caribbean": ["reggae", "ska", "dancehall", "dub", "reggaeton", "rocksteady", "lovers rock", "roots reggae", "ragga"],
    "Latin": ["latin", "salsa", "bachata", "merengue", "tango", "flamenco", "samba", "bossa nova", "cumbia", "reggaeton", "latin pop", "latin rock", "latin jazz", "mariachi", "norteño", "banda", "vallenato", "fado"],
    "Soundtracks & Scores": ["soundtrack", "score", "musical", "broadway", "film score", "video game music", "anime", "tv soundtrack"],
    "Christian & Gospel": ["christian", "gospel", "worship", "praise", "spiritual", "hymn", "ccm", "contemporary christian", "praise & worship"],
    "World & International": ["world", "celtic", "afrobeat", "bollywood", "bhangra", "klezmer", "polka", "african", "middle eastern", "flamenco", "fado", "french", "italian", "german", "japanese", "korean", "chinese", "indian", "brazilian", "mexican", "caribbean"],
    "Children's & Holiday": ["children", "christmas", "holiday", "seasonal", "novelty", "lullaby", "kids", "nursery", "disney"],
    "Comedy & Spoken Word": ["comedy", "spoken word", "podcast", "audiobook", "poetry", "talk show", "interview", "storytelling"],
}


def _fetch_artist_tags(mbid: str) -> list[str]:
    """Fetch genre tags for an artist MBID from MusicBrainz."""
    url = f"https://musicbrainz.org/ws/2/artist/{mbid}?fmt=json"
    req = urllib.request.Request(url, headers={
        "User-Agent": "musicman/0.1.0 (https://github.com/SamiulH25/MusicMan)",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return []

    tags = data.get("tags", [])
    return [t["name"].lower() for t in tags if t.get("count", 0) > 0]


def _classify_artist(tags: list[str]) -> Optional[str]:
    """Given a list of artist tag names, return the best-matching genre category."""
    tags_lower = " ".join(tags)
    for category, patterns in _CATEGORY_TAGS.items():
        for pattern in patterns:
            if pattern in tags_lower:
                return category
    return None


def build_rules(
    db_path: Path = DEFAULT_DB_PATH,
    output_path: Path | None = None,
    top_n: int = 10000,
    cache_path: Path | None = None,
) -> dict:
    """Query MusicBrainz for top artists, fetch genres, build rules JSON.

    Returns the full rules config dict.
    """
    from .config import load_config

    # Load existing default rules
    if output_path and output_path.exists():
        with open(output_path, encoding="utf-8") as f:
            config = json.load(f)
    else:
        # Load bundled defaults
        config = load_config(None)
        # We need the raw dict, so load from the package data
        from importlib import resources
        default_json = resources.files("musicman.data").joinpath("default-rules.json").read_text(encoding="utf-8")
        config = json.loads(default_json)

    canonical = CanonicalDB(db_path)
    top = canonical.top_artists(top_n)

    if cache_path and cache_path.exists():
        with open(cache_path, encoding="utf-8") as f:
            genre_cache = json.load(f)
    else:
        genre_cache = {}

    # Build artist -> genre mapping
    artist_genres: dict[str, list[str]] = {}
    fetched = 0
    t0 = time.monotonic()

    for artist in top:
        name = artist["artist_name"]
        mbid = artist["artist_mbid"]

        if name in genre_cache:
            artist_genres[name] = genre_cache[name]
            continue

        if not mbid:
            continue

        tags = _fetch_artist_tags(mbid)
        fetched += 1

        if tags:
            genre_cache[name] = tags
            artist_genres[name] = tags
        else:
            genre_cache[name] = []

        if fetched % 100 == 0:
            elapsed = time.monotonic() - t0
            rate = fetched / elapsed if elapsed else 0
            print(f"  Fetched {fetched} artists ({rate:.1f}/s), caching...")

        # Save cache periodically
        if fetched % 500 == 0 and cache_path:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(genre_cache, f, ensure_ascii=False)

        # MusicBrainz rate limit: 1 req/sec
        time.sleep(1.1)

    # Save final cache
    if cache_path:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(genre_cache, f, ensure_ascii=False)

    # Group artists by genre category
    genre_artists: dict[str, set[str]] = {cat: set() for cat in _CATEGORY_TAGS}
    for name, tags in genre_cache.items():
        category = _classify_artist(tags)
        if category:
            genre_artists[category].add(name)

    # Update rules with discovered artists
    for rule in config.get("rules", []):
        rule_name = rule["name"]
        if rule_name in genre_artists:
            existing = set()
            for cond in rule.get("conditions", {}).get("any", []):
                if cond.get("op") == "in":
                    existing.update(cond.get("value", []))

            existing.update(genre_artists[rule_name])

            # Replace the artist condition with the merged list
            for cond in rule.get("conditions", {}).get("any", []):
                if cond.get("op") == "in":
                    cond["value"] = sorted(existing)
                    break

    elapsed = time.monotonic() - t0
    total_artists = sum(len(v) for v in genre_artists.values() if v)
    print(f"\nDone. Classified {total_artists} artists into {len([c for c in genre_artists.values() if c])} genres ({fetched} API calls, {elapsed:.0f}s).")

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        print(f"Rules written to {output_path}")

    return config

    def lookup_recording(
        self, artist_name: str, recording_name: str,
    ) -> Optional[dict]:
        """Find a recording by artist + title match."""
        if not self.db_path.exists():
            return None
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT recording_mbid, recording_name, release_mbid, "
                "       release_name, artist_mbid, artist_name, score "
                "FROM recordings WHERE artist_name = ? AND recording_name = ? "
                "ORDER BY score DESC LIMIT 1",
                (artist_name, recording_name),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def recording_count(self) -> int:
        """Return the number of recordings in the database."""
        if not self.db_path.exists():
            return 0
        conn = sqlite3.connect(str(self.db_path))
        try:
            return conn.execute("SELECT COUNT(*) FROM recordings").fetchone()[0]
        finally:
            conn.close()

    def artist_count(self) -> int:
        """Return the number of unique artists in the database."""
        if not self.db_path.exists():
            return 0
        conn = sqlite3.connect(str(self.db_path))
        try:
            return conn.execute("SELECT COUNT(*) FROM artists").fetchone()[0]
        finally:
            conn.close()

    def top_artists(self, limit: int = 10000) -> list[dict]:
        """Return the top *limit* artists by recording count."""
        if not self.db_path.exists():
            return []
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT a.artist_name, a.artist_mbid, COUNT(*) as cnt "
                "FROM artists a "
                "JOIN recordings r ON a.artist_mbid = r.artist_mbid "
                "WHERE a.artist_mbid != '' "
                "GROUP BY a.artist_mbid "
                "ORDER BY cnt DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
