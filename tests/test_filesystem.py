from __future__ import annotations

from pathlib import Path

import pytest

from trinetx_preprocessing import filesystem


def test_write_text_atomic_replaces_completed_file(tmp_path: Path) -> None:
    path = tmp_path / "status.json"
    path.write_text("old")

    filesystem.write_text_atomic(path, "new")

    assert path.read_text() == "new"
    assert not list(tmp_path.glob(".status.json.tmp-*"))


def test_write_text_atomic_preserves_existing_file_when_replace_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "status.json"
    path.write_text("old")

    def fail_replace(source, destination):
        raise OSError("replace failed")

    monkeypatch.setattr(filesystem.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        filesystem.write_text_atomic(path, "new")

    assert path.read_text() == "old"
    assert not list(tmp_path.glob(".status.json.tmp-*"))


def test_remove_tree_strict_deletes_directory(tmp_path: Path) -> None:
    scratch = tmp_path / ".trinetx-hash-test"
    scratch.mkdir()
    (scratch / "chunk-000001.csv").write_text("rows")

    filesystem.remove_tree_strict(scratch, context="Scratch directory")

    assert not scratch.exists()


def test_remove_tree_strict_tolerates_missing_nested_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scratch = tmp_path / ".trinetx-hash-test"
    scratch.mkdir()
    nested = scratch / "chunk-000001.csv"
    nested.write_text("rows")
    original_rmtree = filesystem.shutil.rmtree

    def rmtree_with_missing_nested(path, *, onexc=None, onerror=None):
        nested.unlink()
        error = FileNotFoundError(nested)
        if onexc is not None:
            onexc(nested.unlink, str(nested), error)
        elif onerror is not None:
            onerror(nested.unlink, str(nested), (FileNotFoundError, error, None))
        original_rmtree(path, onexc=onexc)

    monkeypatch.setattr(filesystem.shutil, "rmtree", rmtree_with_missing_nested)

    filesystem.remove_tree_strict(scratch, context="Scratch directory")

    assert not scratch.exists()


def test_remove_tree_strict_fallback_tolerates_missing_nested_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scratch = tmp_path / ".trinetx-hash-test"
    scratch.mkdir()
    nested = scratch / "chunk-000001.csv"
    nested.write_text("rows")
    original_rmtree = filesystem.shutil.rmtree

    def rmtree_with_missing_nested(path, *, onexc=None, onerror=None):
        if onexc is not None:
            raise TypeError("onexc is unsupported")
        nested.unlink()
        if onerror is not None:
            error = FileNotFoundError(nested)
            onerror(nested.unlink, str(nested), (FileNotFoundError, error, None))
        original_rmtree(path, onerror=onerror)

    monkeypatch.setattr(filesystem.shutil, "rmtree", rmtree_with_missing_nested)

    filesystem.remove_tree_strict(scratch, context="Scratch directory")

    assert not scratch.exists()


def test_remove_tree_strict_propagates_delete_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scratch = tmp_path / ".trinetx-hash-test"
    scratch.mkdir()
    (scratch / "chunk-000001.csv").write_text("rows")

    def failing_rmtree(path, *, onexc=None, onerror=None):
        error = PermissionError("denied")
        if onexc is not None:
            onexc(path.rmdir, str(path), error)
            return
        if onerror is not None:
            onerror(path.rmdir, str(path), (PermissionError, error, None))
            return
        raise error

    monkeypatch.setattr(filesystem.shutil, "rmtree", failing_rmtree)

    with pytest.raises(PermissionError, match="denied"):
        filesystem.remove_tree_strict(scratch, context="Scratch directory")

    assert scratch.exists()


def test_remove_tree_strict_raises_when_directory_remains(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scratch = tmp_path / ".trinetx-hash-test"
    scratch.mkdir()
    (scratch / "chunk-000001.csv").write_text("rows")

    def noop_rmtree(path, *, onexc=None, onerror=None):
        return None

    monkeypatch.setattr(filesystem.shutil, "rmtree", noop_rmtree)

    with pytest.raises(OSError, match="Scratch directory was not deleted"):
        filesystem.remove_tree_strict(scratch, context="Scratch directory")

    assert scratch.exists()
