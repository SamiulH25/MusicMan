from __future__ import annotations

from pathlib import Path

import pytest

from musicman.models import (
    Config,
    Condition,
    Conditions,
    Defaults,
    MusicTags,
    Rule,
    Settings,
)


@pytest.fixture
def sample_tags() -> MusicTags:
    return MusicTags(
        title="Take Five",
        artist="Dave Brubeck",
        album="Time Out",
        genre="Jazz",
        date=1959,
        track=1,
    )


@pytest.fixture
def rock_tags() -> MusicTags:
    return MusicTags(
        title="Back in Black",
        artist="AC/DC",
        album="Back in Black",
        genre="Rock",
        date=1980,
        track=1,
    )


@pytest.fixture
def sparse_tags() -> MusicTags:
    """Tags with only a few fields — to test fallback behaviour."""
    return MusicTags(
        title="No Metadata",
        artist=None,
        album=None,
        genre=None,
        date=None,
    )


@pytest.fixture
def minimal_config() -> Config:
    return Config(
        rules=[
            Rule(
                name="Jazz",
                conditions=Conditions(
                    all=[Condition(tag="genre", op="contains", value="jazz")]
                ),
                output="Jazz/{artist}/{album}/{track:02d} - {title}{ext}",
                action="move",
            ),
            Rule(
                name="Rock",
                conditions=Conditions(
                    all=[Condition(tag="genre", op="contains", value="rock")]
                ),
                output="Rock/{artist}/{album}/{track:02d} - {title}{ext}",
                action="move",
            ),
        ],
        defaults=Defaults(
            output="Unsorted/{artist} - {title}{ext}",
            action="move",
        ),
        settings=Settings(
            output_base_dir="/tmp/musicman-test-output",
        ),
    )


@pytest.fixture
def temp_audio_dir(tmp_path: Path) -> Path:
    """Create a temp directory with dummy files that look like audio files."""
    dst = tmp_path / "inbox"
    dst.mkdir()
    # Create a few file stubs (not real audio, just for scan tests).
    for name in ("song1.mp3", "song2.flac", "readme.txt", "cover.jpg"):
        (dst / name).write_text("")
    # Nested directory
    sub = dst / "subfolder"
    sub.mkdir()
    (sub / "nested.ogg").write_text("")
    (sub / "notes.md").write_text("")
    return dst
