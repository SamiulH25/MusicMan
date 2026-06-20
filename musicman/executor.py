from __future__ import annotations

import logging
import shutil
from pathlib import Path

from .models import Config, FileResult

logger = logging.getLogger(__name__)


def dry_run(results: list[FileResult]) -> None:
    """Pretty-print planned operations without executing anything."""
    for r in results:
        if r.error:
            print(f"  [!] {r.source.name}: ERROR - {r.error}")
        elif r.skipped:
            print(f"  [-] {r.source.name}: skipped (already at destination)")
        elif r.action == "move":
            print(f"  -> {r.source.name}  ->  {r.destination}")
        elif r.action == "copy":
            print(f"  +  {r.source.name}  ->  {r.destination}")
        elif r.action == "symlink":
            print(f"  => {r.source.name}  ->  {r.destination}")


def execute(results: list[FileResult], config: Config) -> tuple[int, int, int]:
    """Execute the planned operations.

    Returns ``(moved_count, copied_count, error_count)``.
    """
    moved = copied = errors = 0
    overwrite = config.settings.overwrite
    delete_empty = config.settings.delete_empty_sources

    for r in results:
        if r.error or r.skipped or r.destination is None:
            continue

        try:
            r.destination.parent.mkdir(parents=True, exist_ok=True)

            if r.destination.exists():
                match overwrite:
                    case "skip":
                        logger.info("Skipping existing: %s", r.destination)
                        continue
                    case "rename":
                        r.destination = _unique_path(r.destination)
                    case "overwrite":
                        r.destination.unlink()

            match r.action:
                case "move":
                    _move(r.source, r.destination, delete_empty)
                    moved += 1
                case "copy":
                    shutil.copy2(str(r.source), str(r.destination))
                    copied += 1
                case "symlink":
                    r.destination.symlink_to(r.source.resolve())
                    copied += 1
        except Exception as exc:
            logger.error("Failed to %s %s: %s", r.action, r.source, exc)
            errors += 1

    return moved, copied, errors


def _move(src: Path, dst: Path, delete_empty: bool) -> None:
    src_parent = src.parent
    shutil.move(str(src), str(dst))
    if delete_empty:
        _remove_if_empty(src_parent)


def _remove_if_empty(directory: Path) -> None:
    try:
        if directory.exists() and not any(directory.iterdir()):
            directory.rmdir()
            _remove_if_empty(directory.parent)
    except (OSError, PermissionError):
        pass


def _unique_path(path: Path) -> Path:
    """Append a counter to *path* until it doesn't exist."""
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1
