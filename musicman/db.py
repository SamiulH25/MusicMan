"""Local SQLite database built from the MusicBrainz canonical dump."""

from __future__ import annotations

import csv
import logging
import sqlite3
import time
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
