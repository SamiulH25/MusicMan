from __future__ import annotations

from pathlib import Path

from musicman.formatter import format_path, validate_template
from musicman.models import MusicTags


class TestFormatPath:
    def test_basic_path(self, sample_tags: MusicTags) -> None:
        template = "{artist}/{album}/{track:02d} - {title}{ext}"
        result = format_path(template, sample_tags, ".mp3")
        expected = Path("Dave Brubeck/Time Out/01 - Take Five.mp3")
        assert result == expected

    def test_missing_tag_uses_unknown(self, sparse_tags: MusicTags) -> None:
        template = "{artist}/{album}/{title}{ext}"
        result = format_path(template, sparse_tags, ".flac")
        expected = Path("Unknown/Unknown/No Metadata.flac")
        assert result == expected

    def test_slash_in_tag_value_sanitised(self) -> None:
        tags = MusicTags(
            title="Song A / Song B",
            artist="Artist / Band",
            album="Album",
        )
        template = "{artist}/{title}{ext}"
        result = format_path(template, tags, ".mp3")
        assert " - " in str(result)
        assert "/" not in str(result).lstrip(".")

    def test_ext_placeholder(self, sample_tags: MusicTags) -> None:
        result = format_path("{artist}/{title}{ext}", sample_tags, ".flac")
        assert str(result).endswith(".flac")

    def test_fmt_spec_pads_track(self, sample_tags: MusicTags) -> None:
        template = "{track:03d} - {title}{ext}"
        result = format_path(template, sample_tags, ".mp3")
        assert str(result).startswith("001")

    def test_fmt_spec_error_fallback(self) -> None:
        """Applying :02d to a string should fallback gracefully."""
        tags = MusicTags(title="Song", track=None, date=None)
        template = "{track:02d} - {title}{ext}"
        result = format_path(template, tags, ".mp3")
        assert "Unknown" in str(result)

    def test_unknown_placeholder_preserved(self) -> None:
        tags = MusicTags(artist="A")
        result = format_path("{artist}/{unknown}{ext}", tags, ".mp3")
        assert "{unknown}" in str(result)

    def test_year_via_date_field(self) -> None:
        tags = MusicTags(title="Song", artist="A", date=1999)
        result = format_path("{year}/{artist}/{title}{ext}", tags, ".mp3")
        assert str(result).startswith("1999")

    def test_albumartist(self) -> None:
        tags = MusicTags(title="Song", artist="A", albumartist="Various", date=2000)
        result = format_path("{albumartist}/{artist} - {title}{ext}", tags, ".mp3")
        assert str(result).startswith("Various")


class TestValidateTemplate:
    def test_all_known(self) -> None:
        errors = validate_template("{artist}/{album}/{title}{ext}")
        assert errors == []

    def test_unknown_placeholder(self) -> None:
        errors = validate_template("{artist}/{foobar}{ext}")
        assert "foobar" in errors

    def test_multiple_unknowns(self) -> None:
        errors = validate_template("{foo}/{bar}/{artist}{ext}")
        assert len(errors) == 2
