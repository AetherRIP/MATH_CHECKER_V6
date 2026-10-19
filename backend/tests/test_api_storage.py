"""Tests for /api/storage/summary — real, bounded, path-free measurements."""

from __future__ import annotations

from pathlib import Path


def write(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def category_map(data: dict) -> dict:
    return {item["id"]: item for item in data["categories"]}


def test_empty_data_dir_reports_all_zero(client):
    data = client.get("/api/storage/summary").json()
    assert data["total"] == {"files": 0, "bytes": 0}
    assert data["truncated"] is False
    assert len(data["categories"]) == 4
    for category in data["categories"]:
        assert category["files"] == 0
        assert category["bytes"] == 0


def test_files_are_counted_per_category(client, tmp_path):
    data_dir = tmp_path / "data"
    write(data_dir / "notes.txt", 3)
    write(data_dir / "records.csv", 7)
    write(data_dir / "tmp" / "scratch.bin", 10)
    write(data_dir / "reports" / "report.pdf", 5)
    write(data_dir / "cache" / "blob.dat", 7)
    # Not counted anywhere: cache folders of tooling.
    write(data_dir / "__pycache__" / "mod.pyc", 99)

    data = client.get("/api/storage/summary").json()
    categories = category_map(data)

    assert categories["persistent"]["files"] == 2
    assert categories["persistent"]["bytes"] == 10
    assert categories["temporary"]["files"] == 1
    assert categories["temporary"]["bytes"] == 10
    assert categories["reports"]["files"] == 1
    assert categories["reports"]["bytes"] == 5
    assert categories["cache"]["files"] == 1
    assert categories["cache"]["bytes"] == 7

    assert data["total"]["files"] == 5
    assert data["total"]["bytes"] == 32
    assert data["truncated"] is False


def test_summary_never_returns_filesystem_paths(client, tmp_path):
    data_dir = tmp_path / "data"
    write(data_dir / "secret-looking-file.txt", 3)

    body = client.get("/api/storage/summary").text
    assert str(tmp_path) not in body
    assert str(tmp_path).replace("\\", "/") not in body
    assert "secret-looking-file" not in body
    assert "\\" not in body


def test_walk_is_bounded_and_reports_truncation(client, monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    for index in range(6):
        write(data_dir / "tmp" / f"file-{index}.bin", 1)

    monkeypatch.setattr("app.api.storage.MAX_ENTRIES", 3)
    data = client.get("/api/storage/summary").json()
    assert data["truncated"] is True
    # A lower bound, never an over-count.
    assert data["total"]["files"] <= 6


def test_deep_directories_are_not_endlessly_walked(client, monkeypatch, tmp_path):
    monkeypatch.setattr("app.api.storage.MAX_DEPTH", 2)
    deep = tmp_path / "data" / "a" / "b" / "c" / "d"
    write(deep / "deep-file.bin", 4)

    data = client.get("/api/storage/summary").json()
    # Beyond the depth limit the walk reports truncation rather than crawling on.
    assert data["total"]["files"] == 0 or data["truncated"] is True
