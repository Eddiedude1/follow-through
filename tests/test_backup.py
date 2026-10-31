from pathlib import Path

import pytest

from follow_through import backup


def test_backup_once_copies_db_with_timestamped_name(tmp_path):
    src = tmp_path / "follow_through.db"
    src.write_text("fake db contents")
    dest_dir = tmp_path / "backups"
    dest_dir.mkdir()
    dest_path = backup.backup_once(str(src), str(dest_dir))
    assert Path(dest_path).read_text() == "fake db contents"
    assert Path(dest_path).parent == dest_dir


def test_backup_once_raises_if_source_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        backup.backup_once(str(tmp_path / "missing.db"), str(tmp_path))
