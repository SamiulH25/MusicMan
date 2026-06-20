from __future__ import annotations

from musicman.utils import UnsupportedFileError


class TestWriteTags:
    def test_write_tags_unsupported_extension(self, tmp_path) -> None:
        """Unsupported file types raise UnsupportedFileError."""
        from musicman.utils import write_tags

        path = tmp_path / "test.txt"
        path.write_text("hello")
        try:
            write_tags(path, genre="Test")
            assert False, "should have raised"
        except UnsupportedFileError:
            pass
