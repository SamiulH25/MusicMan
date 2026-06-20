from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from musicman.cli import cli


class TestInitCommand:
    def test_init_creates_sample_config(self, tmp_path: Path) -> None:
        runner = CliRunner()
        dest = tmp_path / "my-rules.json"
        result = runner.invoke(cli, ["init", str(dest)])
        assert result.exit_code == 0
        assert dest.exists()
        raw = json.loads(dest.read_text())
        assert "rules" in raw

    def test_init_refuses_overwrite(self, tmp_path: Path) -> None:
        runner = CliRunner()
        dest = tmp_path / "existing.json"
        dest.write_text("{}")
        result = runner.invoke(cli, ["init", str(dest)])
        assert result.exit_code == 1
        assert "already exists" in result.output


class TestValidateCommand:
    def test_valid_config(self, tmp_path: Path) -> None:
        path = tmp_path / "rules.json"
        path.write_text(json.dumps({
            "rules": [
                {
                    "name": "Test",
                    "conditions": {
                        "all": [{"tag": "genre", "op": "eq", "value": "Jazz"}],
                    },
                    "output": "{genre}/{artist}{ext}",
                },
            ],
        }))
        runner = CliRunner()
        result = runner.invoke(cli, ["validate", str(path)])
        assert result.exit_code == 0
        assert "valid" in result.output.lower()

    def test_invalid_config(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({
            "rules": [{"name": 42}],
        }))
        runner = CliRunner()
        result = runner.invoke(cli, ["validate", str(path)])
        assert result.exit_code == 1
        assert "invalid" in result.output.lower() or "failed" in result.output.lower()

    def test_invalid_json_syntax(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{bad json}")
        runner = CliRunner()
        result = runner.invoke(cli, ["validate", str(path)])
        assert result.exit_code == 1
        assert "invalid json" in result.output.lower()


class TestOrganiseCommand:
    def test_dry_run_on_empty_directory(self, tmp_path: Path) -> None:
        """No audio files → processed count should be 0."""
        source = tmp_path / "empty"
        source.mkdir()
        runner = CliRunner()
        result = runner.invoke(cli, ["organise", str(source), "-n"])
        assert result.exit_code == 0
        assert "0" in result.output  # 0 files processed

    def test_dry_run_requires_sources(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["organise", "-n"])
        assert result.exit_code != 0

    def test_dry_run_with_config(self, tmp_path: Path) -> None:
        """A dry run should not error when given a valid config."""
        cfg = tmp_path / "rules.json"
        cfg.write_text(json.dumps({
            "rules": [],
            "defaults": {"output": "{artist} - {title}{ext}", "action": "move"},
            "settings": {"output_base_dir": str(tmp_path / "out")},
        }))
        source = tmp_path / "music"
        source.mkdir()
        (source / "song.mp3").write_text("")

        runner = CliRunner()
        result = runner.invoke(cli, ["organise", str(source), "-c", str(cfg), "-n"])
        # Exit 0 even though the file has no tags and will fail tag-read;
        # the engine should catch the error and continue.
        assert result.exit_code == 0
        # It should report at least 1 file processed.
        assert "Processed" in result.output


class TestTagsCommand:
    def test_tags_on_nonexistent_file(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["tags", str(tmp_path / "nope.mp3")])
        assert result.exit_code != 0

    def test_tags_on_non_audio_file(self, tmp_path: Path) -> None:
        path = tmp_path / "readme.txt"
        path.write_text("hello")
        runner = CliRunner()
        result = runner.invoke(cli, ["tags", str(path)])
        # Should exit with error because mutagen can't read .txt
        assert result.exit_code != 0
