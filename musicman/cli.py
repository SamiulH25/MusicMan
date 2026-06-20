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
from .engine import CategorisationEngine
from .executor import dry_run as print_dry_run, execute
from .models import FileResult
from .utils import read_tags

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
# Internal helpers
# ---------------------------------------------------------------------------


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
