from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import click

from . import __version__
from .config import (
    SAMPLE_CONFIG,
    ConfigError,
    load_config,
    resolve_output_base,
    validate_config,
)
from .db import CanonicalDB
from .engine import CategorisationEngine
from .executor import dry_run as print_dry_run, execute
from .models import EnrichResult, FileResult
from .sources import guess_tags as fetch_tags
from .sources.musicbrainz import MusicBrainzSource
from .utils import read_tags, scan_files, write_tags

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Main group
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(version=__version__, prog_name="musicman")
def cli() -> None:
    """musicman - Organise your music library by tag-based rules."""


# ---------------------------------------------------------------------------
# organise
# ---------------------------------------------------------------------------


@cli.command()
@click.argument(
    "sources",
    nargs=-1,
    type=click.Path(exists=True, path_type=Path),
)
@click.option(
    "--config", "-c",
    type=click.Path(exists=True, path_type=Path),
    help="Path to rules JSON file.",
)
@click.option(
    "--dry-run", "-n",
    is_flag=True,
    help="Preview only - no files are changed.",
)
@click.option(
    "--output", "-o",
    type=click.Path(path_type=Path),
    help="Override output base directory.",
)
@click.option(
    "--fetch",
    is_flag=True,
    help="Look up missing genre from MusicBrainz before organising.",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Show matched tags per file.",
)
@click.option(
    "--quiet",
    is_flag=True,
    help="Suppress per-file output; show summary only.",
)
def organise(
    sources: tuple[Path, ...],
    config: Path | None,
    dry_run: bool,
    output: Path | None,
    fetch: bool,
    verbose: bool,
    quiet: bool,
) -> None:
    """Categorise and organise music files according to rules.

    SOURCES can be one or more files and/or directories.  Directories are
    scanned recursively for supported audio files.
    """
    _setup_logging(verbose)

    try:
        cfg = load_config(config)
    except ConfigError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    # CLI --output overrides config setting.
    if output is not None:
        cfg.settings.output_base_dir = str(output.resolve())

    engine = CategorisationEngine(cfg)
    source_list = list(sources)

    if not source_list:
        click.echo("Error: at least one source path is required", err=True)
        sys.exit(1)

    # Optional: enrich files with the canonical dump before organising
    if fetch and not dry_run:
        _enrich_with_canonical(source_list, cfg, verbose, quiet)
    elif fetch and dry_run:
        _preview_canonical(source_list, cfg, verbose, quiet)

    try:
        results = list(engine.categorise(source_list))
    except Exception as exc:
        click.echo(f"Error during categorisation: {exc}", err=True)
        sys.exit(1)

    if not quiet:
        click.echo(f"Output base: {engine.base_dir}")
        if dry_run:
            click.echo("\n-- Dry run - no files will be changed --\n")
        else:
            click.echo()

        if verbose:
            for r in results:
                _print_verbose(r)
        else:
            print_dry_run(results)

    # Summary
    total = len(results)
    matched = sum(1 for r in results if r.destination is not None and not r.error and not r.skipped)
    skipped = sum(1 for r in results if r.skipped)
    errors = sum(1 for r in results if r.error)

    click.echo(
        f"\nProcessed {total} file{'s' if total != 1 else ''}: "
        f"{matched} organised, "
        f"{skipped} skipped, "
        f"{errors} error{'s' if errors != 1 else ''}"
    )

    if not dry_run and matched:
        moved, copied, errs = execute(results, cfg)
        total_ok = moved + copied
        click.echo(
            f"Done: {total_ok} file{'s' if total_ok != 1 else ''} "
            f"({moved} moved, {copied} copied), "
            f"{errs} error{'s' if errs != 1 else ''}"
        )


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@cli.command()
@click.argument(
    "path",
    type=click.Path(path_type=Path),
    default=None,
    required=False,
)
def init(path: Path | None) -> None:
    """Generate a sample musicman-rules.json config file."""
    if path is None:
        path = Path.cwd() / "musicman-rules.json"

    if path.exists():
        click.echo(
            f"Error: {path} already exists - not overwriting.", err=True
        )
        sys.exit(1)

    path.write_text(SAMPLE_CONFIG, encoding="utf-8")
    click.echo(f"Wrote sample config to {path}")
    click.echo("Edit the file to define your rules, then run:")
    click.echo(f"  musicman organise . --config {path} --dry-run")


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


@cli.command()
@click.argument(
    "path",
    type=click.Path(exists=True, path_type=Path),
)
def validate(path: Path) -> None:
    """Validate a rules JSON config file."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        click.echo(f"!! Invalid JSON: {exc}", err=True)
        sys.exit(1)

    errors = validate_config(raw)
    if errors:
        click.echo(f"[!] Config validation failed for {path}:", err=True)
        for err in errors:
            click.echo(f"   * {err}", err=True)
        sys.exit(1)

    rule_count = len(raw.get("rules", []))
    click.echo(
        f"[OK] Config valid - {rule_count} rule"
        f"{'s' if rule_count != 1 else ''} defined."
    )


# ---------------------------------------------------------------------------
# tags
# ---------------------------------------------------------------------------


@cli.command()
@click.argument(
    "file",
    type=click.Path(exists=True, path_type=Path),
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Also show raw (un-normalised) tags.",
)
def tags(file: Path, verbose: bool) -> None:
    """Display all metadata tags from a single audio file."""
    try:
        tags = read_tags(file)
    except Exception as exc:
        click.echo(f"Error reading tags: {exc}", err=True)
        sys.exit(1)

    click.echo(f"File: {file.resolve()}")
    if tags.duration is not None:
        from .utils import format_duration
        click.echo(f"Duration: {format_duration(tags.duration)}")

    click.echo("\nTags:")
    shown = 0
    for field in (
        "title", "artist", "album", "albumartist", "genre",
        "date", "track", "track_total", "disc", "disc_total",
        "composer", "bitrate",
    ):
        value = getattr(tags, field, None)
        if value is not None:
            click.echo(f"  {field:14s} = {value}")
            shown += 1

    if shown == 0:
        click.echo("  (no recognised tags found)")

    if verbose and tags.raw:
        click.echo("\nRaw tags (all):")
        for k, v in tags.raw.items():
            click.echo(f"  {k:14s} = {v}")


# ---------------------------------------------------------------------------
# db
# ---------------------------------------------------------------------------


@click.group()
def db() -> None:
    """Manage the local MusicBrainz canonical database."""


@db.command()
@click.argument(
    "csv_path",
    type=click.Path(exists=True, path_type=Path),
)
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=None,
    help="Output database path (default: ~/.config/musicman/canonical.db)",
)
def import_cmd(csv_path: Path, db_path: Path | None) -> None:
    """Import the canonical MusicBrainz dump CSV into a local database.

    CSV_PATH should point to canonical_musicbrainz_data.csv.
    """
    from .db import DEFAULT_DB_PATH, import_canonical_dump

    target = db_path or DEFAULT_DB_PATH
    click.echo(f"Importing {csv_path.name} into {target} ...")
    click.echo("This will take a few minutes for the full 7GB dump.")

    try:
        count = import_canonical_dump(csv_path, target)
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        raise click.Abort()

    click.echo(f"Imported {count:,} rows.")
    click.echo("Done.  Use 'musicman organise --fetch' for local lookups.")


@db.command()
def status() -> None:
    """Show import status of the local canonical database."""
    from .db import DEFAULT_DB_PATH

    db_path = DEFAULT_DB_PATH
    if not db_path.exists():
        click.echo("No local database found.  Run 'musicman db import' first.")
        return

    db_conn = CanonicalDB(db_path)
    artists = db_conn.artist_count()
    recordings = db_conn.recording_count()
    size_mb = db_path.stat().st_size / 1024 / 1024
    click.echo(
        f"Database: {db_path} ({size_mb:.0f} MB)\n"
        f"Artists:  {artists:,}\n"
        f"Recordings: {recordings:,}"
    )


# ---------------------------------------------------------------------------
# enrich
# ---------------------------------------------------------------------------


def _enrich_file(
    source: Path,
    engine: CategorisationEngine,
    tags,
    force: bool,
    fetch: bool = False,
    mb_source: MusicBrainzSource | None = None,
) -> EnrichResult:
    """Match *source* against rules and write genre tag if missing.

    If *fetch* is True, query MusicBrainz first for genre and other
    missing tags.
    """
    genre_to_write = None
    extra_tags: dict[str, str] = {}
    tags_written: list[str] = []
    rule_name = None

    # 1. Try MusicBrainz if requested
    if fetch and mb_source is not None:
        fetched = mb_source.fetch(source, tags)
        if fetched.source:
            rule_name = fetched.source
            if fetched.genre and (force or not tags.genre):
                genre_to_write = fetched.genre
                tags_written.append("genre")
            for field in ("title", "artist", "album", "date", "albumartist"):
                val = getattr(fetched, field, None)
                if val and not getattr(tags, field, None):
                    extra_tags[field] = val
                    tags_written.append(field)

    # 2. Fall back to rule matching (for genre)
    if not genre_to_write:
        rule, _ = engine._match_rule(tags)
        rule_name = rule.name if rule else None
        if rule_name is None and not tags_written:
            return EnrichResult(source=source, error="no matching rule")
        if rule_name and (force or not tags.genre):
            genre_to_write = rule_name
            if "genre" not in tags_written:
                tags_written.append("genre")

    if not genre_to_write and not extra_tags:
        return EnrichResult(source=source, rule=rule_name or "", skipped=True)

    try:
        write_tags(source, genre=genre_to_write, **extra_tags)
        return EnrichResult(
            source=source, rule=rule_name or "", tags_written=tags_written,
        )
    except Exception as exc:
        return EnrichResult(
            source=source, rule=rule_name or "", error=str(exc),
        )


@cli.command()
@click.argument(
    "sources",
    nargs=-1,
    type=click.Path(exists=True, path_type=Path),
)
@click.option(
    "--config", "-c",
    type=click.Path(exists=True, path_type=Path),
    help="Path to rules JSON file.",
)
@click.option(
    "--dry-run", "-n",
    is_flag=True,
    help="Preview only - no tags are written.",
)
@click.option(
    "--force", "-f",
    is_flag=True,
    help="Overwrite existing genre tags.",
)
@click.option(
    "--fetch",
    is_flag=True,
    help="Look up missing tags from MusicBrainz (artist+title required).",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Show matched rule per file.",
)
@click.option(
    "--quiet",
    is_flag=True,
    help="Suppress per-file output; show summary only.",
)
def enrich(
    sources: tuple[Path, ...],
    config: Path | None,
    dry_run: bool,
    force: bool,
    fetch: bool,
    verbose: bool,
    quiet: bool,
) -> None:
    """Write genre tags to music files based on matching rules.

    Reads each file, matches it against your rules or fetches metadata
    from MusicBrainz, and writes missing tags back to the file.

    By default uses rule-based genre matching.  Add --fetch to also
    look up artist, album, year, and genre from MusicBrainz for files
    that have artist and title tags.
    """
    _setup_logging(verbose)

    try:
        cfg = load_config(config)
    except ConfigError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    engine = CategorisationEngine(cfg)
    mb_source = MusicBrainzSource() if fetch else None
    source_list = list(sources)

    if not source_list:
        click.echo("Error: at least one source path is required", err=True)
        sys.exit(1)

    if not quiet:
        if dry_run:
            click.echo("-- Dry run - no tags will be written --\n")
        else:
            click.echo()

    results: list[EnrichResult] = []
    for source_path in scan_files(
        source_list,
        cfg.settings.supported_extensions,
        cfg.settings.follow_symlinks,
    ):
        try:
            tags = read_tags(source_path)
        except Exception as exc:
            results.append(
                EnrichResult(source=source_path, error=f"failed to read: {exc}")
            )
            continue

        if dry_run:
            # Simulate enrichment in dry-run mode
            mb_tags = None
            if fetch and mb_source is not None:
                mb_tags = mb_source.fetch(source_path, tags)
            if mb_tags and mb_tags.genre and (force or not tags.genre):
                rule_name = mb_tags.source
                tags_written = ["genre"]
                if mb_tags.title and not tags.title:
                    tags_written.append("title")
                if mb_tags.artist and not tags.artist:
                    tags_written.append("artist")
                if mb_tags.album and not tags.album:
                    tags_written.append("album")
                if mb_tags.date and not tags.date:
                    tags_written.append("date")
                results.append(
                    EnrichResult(source=source_path, rule=rule_name, tags_written=tags_written)
                )
                continue

            rule, _ = engine._match_rule(tags)
            rule_name = rule.name if rule else None
            if rule_name is None:
                results.append(
                    EnrichResult(source=source_path, error="no matching rule")
                )
                continue
            if tags.genre and not force:
                results.append(
                    EnrichResult(source=source_path, rule=rule_name, skipped=True)
                )
                continue
            results.append(
                EnrichResult(
                    source=source_path,
                    rule=rule_name,
                    tags_written=["genre"],
                )
            )
            continue

        result = _enrich_file(source_path, engine, tags, force, fetch=fetch, mb_source=mb_source)
        results.append(result)

    for r in results:
        if not quiet:
            _print_enrich(r, verbose, dry_run)

    enriched = sum(1 for r in results if r.tags_written)
    skipped = sum(1 for r in results if r.skipped)
    errors = sum(1 for r in results if r.error)

    click.echo(
        f"\nProcessed {len(results)} file{'s' if len(results) != 1 else ''}: "
        f"{enriched} enriched, "
        f"{skipped} skipped, "
        f"{errors} error{'s' if errors != 1 else ''}"
    )


def _print_enrich(r: EnrichResult, verbose: bool, dry_run: bool) -> None:
    if r.error:
        click.echo(f"  [!] {r.source.name}: {r.error}")
        return
    if r.skipped:
        if verbose:
            click.echo(f"  [-] {r.source.name}: already has genre ({r.rule})")
        return
    prefix = "  [w]" if not dry_run else "  [.]"
    click.echo(f"{prefix} {r.source.name} -> genre={r.rule}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
# Canonical enrichment helpers
# ---------------------------------------------------------------------------


def _enrich_with_canonical(
    source_list: list[Path],
    cfg,
    verbose: bool,
    quiet: bool,
) -> None:
    """Enrich files with genre from the local canonical dump."""
    from .sources.canonical import CanonicalDumpSource
    from .utils import scan_files, read_tags, write_tags

    source = CanonicalDumpSource()
    enriched = 0
    for path in scan_files(source_list, cfg.settings.supported_extensions):
        tags = read_tags(path)
        if not tags.artist or not tags.title:
            continue
        if tags.genre:
            continue
        result = source.fetch(path, tags)
        if result.genre:
            write_tags(path, genre=result.genre)
            enriched += 1
            if not quiet:
                click.echo(f"  [MB] {path.name} -> genre={result.genre}")
    if not quiet and enriched:
        click.echo(f"\nEnriched {enriched} file(s) from MusicBrainz.\n")


def _preview_canonical(
    source_list: list[Path],
    cfg,
    verbose: bool,
    quiet: bool,
) -> None:
    """Preview what canonical enrichment would do without writing."""
    from .sources.canonical import CanonicalDumpSource
    from .utils import scan_files, read_tags

    source = CanonicalDumpSource()
    click.echo("\n-- MusicBrainz enrichment preview (dry run) --")
    for path in scan_files(source_list, cfg.settings.supported_extensions):
        tags = read_tags(path)
        if tags.genre:
            continue
        if not tags.artist or not tags.title:
            click.echo(f"  [-] {path.name}: no artist+title, skipping")
            continue
        result = source.fetch(path, tags)
        if result.genre:
            click.echo(f"  [.] {path.name} -> genre={result.genre}")
        else:
            click.echo(f"  [-] {path.name}: no genre found in MusicBrainz")


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )


def _print_verbose(r: FileResult) -> None:
    prefix = ""
    if r.error:
        prefix = "!"
    elif r.skipped:
        prefix = "-"
    elif r.action == "move":
        prefix = ">"
    elif r.action == "copy":
        prefix = "+"
    elif r.action == "symlink":
        prefix = "="

    tag_str = ""
    if r.tags:
        parts = []
        for f in ("title", "artist", "album", "genre", "date"):
            v = getattr(r.tags, f, None)
            if v is not None:
                parts.append(f"{f}={v}")
        tag_str = "  [" + ", ".join(parts) + "]"

    rule_str = f"  rule={r.rule}" if r.rule else ""

    if r.error:
        click.echo(f"  {prefix}  {r.source.name}: {r.error}")
    elif r.skipped:
        click.echo(f"  {prefix}  {r.source.name}{tag_str}{rule_str}")
    else:
        click.echo(
            f"  {prefix}  {r.source.name}  ->  {r.destination}"
            f"{tag_str}{rule_str}"
        )
