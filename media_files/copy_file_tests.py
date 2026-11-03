"""Tests for media_files.utils.copy_file_with_progress partial-file handling.

An update restarts the copy worker; an interrupted copy must never leave a
truncated file under the real destination name.
"""

from media_files.utils import copy_file_with_progress
from unittest.mock import patch
import pytest
import shutil


CONTENT = b"x" * (3 * 1024 * 1024)


def _leftovers(directory):
    return sorted(p.name for p in directory.iterdir() if p.name.endswith('.part'))


@pytest.fixture
def source(tmp_path):
    src = tmp_path / "src" / "18952_video.mp4"
    src.parent.mkdir()
    src.write_bytes(CONTENT)
    return src


@pytest.fixture
def dest_dir(tmp_path):
    directory = tmp_path / "playout" / "2026_KW_45"
    directory.mkdir(parents=True)
    return directory


def _write_half_then(exc):
    """Mimic a copy that is interrupted after writing part of the data."""
    def fake_copy(src_file, dst_file, *args, **kwargs):
        dst_file.write(src_file.read(len(CONTENT) // 2))
        raise exc
    return fake_copy


@pytest.mark.parametrize("verify", [False, True, "md5"])
def test_copy_file_with_progress__1(source, dest_dir, verify):
    """A successful copy lands under the final name with no .part left over."""
    dest = dest_dir / source.name
    with patch("media_files.utils.calculate_checksum", return_value=None):
        ok, message = copy_file_with_progress(str(source), str(dest), verify_checksum=verify)
    assert ok, message
    assert dest.read_bytes() == CONTENT
    assert _leftovers(dest_dir) == []


def test_copy_file_with_progress__2(source, dest_dir):
    """Size-only verification also renames into place without leftovers."""
    dest = dest_dir / source.name
    ok, message = copy_file_with_progress(
        str(source), str(dest), verify_by_size_only=True)
    assert ok, message
    assert dest.read_bytes() == CONTENT
    assert _leftovers(dest_dir) == []


def test_copy_file_with_progress__3(source, dest_dir):
    """An I/O error mid-copy returns False and leaves no partial file."""
    dest = dest_dir / source.name
    with patch("media_files.utils.shutil.copyfileobj",
               side_effect=_write_half_then(OSError("NAS went away"))):
        ok, message = copy_file_with_progress(str(source), str(dest), verify_checksum=False)
    assert not ok
    assert "NAS went away" in message
    assert not dest.exists()
    assert _leftovers(dest_dir) == []


def test_copy_file_with_progress__4(source, dest_dir):
    """A worker shutdown mid-copy propagates and leaves no partial file."""
    dest = dest_dir / source.name
    with patch("media_files.utils.shutil.copyfileobj",
               side_effect=_write_half_then(SystemExit(1))):
        with pytest.raises(SystemExit):
            copy_file_with_progress(str(source), str(dest), verify_checksum=False)
    assert not dest.exists()
    assert _leftovers(dest_dir) == []


def test_copy_file_with_progress__5(source, dest_dir):
    """An interrupted size-only copy leaves no partial file either."""
    dest = dest_dir / source.name

    def fake_copy2(src, dst, *args, **kwargs):
        with open(dst, "wb") as fh:
            fh.write(CONTENT[: len(CONTENT) // 2])
        raise SystemExit(1)

    with patch("media_files.utils.shutil.copy2", side_effect=fake_copy2):
        with pytest.raises(SystemExit):
            copy_file_with_progress(str(source), str(dest), verify_by_size_only=True)
    assert not dest.exists()
    assert _leftovers(dest_dir) == []


def test_copy_file_with_progress__6(source, dest_dir):
    """A failed copy does not touch a file already at the destination."""
    dest = dest_dir / source.name
    dest.write_bytes(b"previous complete file")
    with patch("media_files.utils.shutil.copyfileobj",
               side_effect=_write_half_then(OSError("disk full"))):
        ok, _ = copy_file_with_progress(str(source), str(dest), verify_checksum=False)
    assert not ok
    assert dest.read_bytes() == b"previous complete file"
    assert _leftovers(dest_dir) == []


def test_copy_file_with_progress__7(source, dest_dir):
    """While copying, data only exists under the hidden .part name."""
    dest = dest_dir / source.name
    seen = {}
    real_copyfileobj = shutil.copyfileobj

    def spying_copy(src_file, dst_file, *args, **kwargs):
        seen["final_exists"] = dest.exists()
        seen["partials"] = _leftovers(dest_dir)
        return real_copyfileobj(src_file, dst_file, *args, **kwargs)

    with patch("media_files.utils.shutil.copyfileobj", side_effect=spying_copy):
        ok, message = copy_file_with_progress(str(source), str(dest), verify_checksum=False)
    assert ok, message
    assert seen["final_exists"] is False
    assert len(seen["partials"]) == 1
    assert seen["partials"][0].startswith(f".{source.name}.")
