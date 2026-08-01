"""Unit tests for LocalFileStorageBackend (I-M-10), exercised directly
rather than through the HTTP API: the default dev/test stack runs
STORAGE_BACKEND=s3 against MinIO, so nothing else in the suite ever
instantiates the local filesystem backend."""

import pytest

from app.storage_backends.local import LocalFileStorageBackend


def test_save_read_delete_round_trip(tmp_path):
    backend = LocalFileStorageBackend(str(tmp_path))
    backend.save("org/some-key.txt", b"hello world")

    assert backend.read("org/some-key.txt") == b"hello world"

    backend.delete("org/some-key.txt")
    with pytest.raises(FileNotFoundError):
        backend.read("org/some-key.txt")


def test_read_missing_key_raises_file_not_found(tmp_path):
    backend = LocalFileStorageBackend(str(tmp_path))
    with pytest.raises(FileNotFoundError):
        backend.read("does/not/exist.txt")


def test_delete_missing_key_is_a_no_op(tmp_path):
    backend = LocalFileStorageBackend(str(tmp_path))
    backend.delete("never-existed.txt")  # must not raise


def test_nested_keys_create_parent_directories(tmp_path):
    backend = LocalFileStorageBackend(str(tmp_path))
    backend.save("a/b/c/deep.txt", b"data")
    assert backend.read("a/b/c/deep.txt") == b"data"


def test_path_traversal_key_is_rejected(tmp_path):
    backend = LocalFileStorageBackend(str(tmp_path))
    with pytest.raises(ValueError):
        backend.save("../../etc/passwd", b"malicious")


def test_disk_usage_percent_is_a_sane_percentage(tmp_path):
    backend = LocalFileStorageBackend(str(tmp_path))
    usage = backend.disk_usage_percent()
    assert 0.0 <= usage <= 100.0
