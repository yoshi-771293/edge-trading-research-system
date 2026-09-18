import os, stat
from pathlib import Path
import pytest
from referee import manifest


def test_manifest_round_trip(tmp_path):
    d = tmp_path / "ref"; d.mkdir()
    (d / "a.py").write_text("x = 1\n"); (d / "b.py").write_text("y = 2\n")
    manifest.write(d)
    assert manifest.verify(d).ok


def test_one_byte_change_is_detected(tmp_path):
    d = tmp_path / "ref"; d.mkdir()
    (d / "a.py").write_text("x = 1\n")
    manifest.write(d)
    (d / "a.py").write_text("x = 2\n")
    res = manifest.verify(d)
    assert not res.ok and "a.py" in res.detail


def test_added_file_is_detected(tmp_path):
    d = tmp_path / "ref"; d.mkdir()
    (d / "a.py").write_text("x = 1\n")
    manifest.write(d)
    (d / "z.py").write_text("evil = True\n")
    assert not manifest.verify(d).ok


def test_lock_makes_files_read_only(tmp_path):
    d = tmp_path / "ref"; d.mkdir()
    (d / "a.py").write_text("x = 1\n")
    manifest.write(d); manifest.lock(d)
    assert not os.access(d / "a.py", os.W_OK)
    manifest.unlock(d)
    assert os.access(d / "a.py", os.W_OK)
