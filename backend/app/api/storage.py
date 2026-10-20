"""Storage overview: honest measurement of the application's own data area.

The summary is produced by a bounded walk of the configured data directory
only. Nothing outside it is ever scanned, absolute paths are never returned,
and the walk stops after ``MAX_ENTRIES`` visited entries so a huge directory
can never turn this request into expensive work.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter

from ..config import get_config

router = APIRouter(prefix="/api/storage", tags=["storage"])

# Bounds for the walk: visited entries and descent depth.
MAX_ENTRIES = 20_000
MAX_DEPTH = 8

# (id, label, description, subdirectory of the data dir — None means the
# data dir itself minus the other categories' subdirectories)
CATEGORIES = (
    ("persistent", "Persistent data", "Application data that survives restarts.", None),
    ("temporary", "Temporary files", "Scratch files created while processing.", "tmp"),
    ("uploads", "Job uploads", "Input files owned by queued or processing jobs.", "uploads"),
    ("reports", "Reports", "Generated correction reports.", "reports"),
    ("cache", "Cached assets", "Reusable local assets.", "cache"),
)


def _measure(root: Path, skip: set[str], budget: list[int]) -> tuple[int, int, bool]:
    """Count files and bytes under ``root``; stop when the budget runs out."""
    files = 0
    size = 0
    truncated = False
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        directory, depth = stack.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError:
            continue
        for entry in entries:
            if budget[0] <= 0:
                return files, size, True
            budget[0] -= 1
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if entry.name in skip:
                        continue
                    if depth + 1 <= MAX_DEPTH:
                        stack.append((Path(entry.path), depth + 1))
                    else:
                        truncated = True
                elif entry.is_file(follow_symlinks=False):
                    files += 1
                    size += entry.stat(follow_symlinks=False).st_size
            except OSError:
                continue
    return files, size, truncated


@router.get("/summary")
def storage_summary() -> dict:
    """Per-category file counts and byte totals for the application data dir."""
    data_dir = get_config().data_dir
    category_dirs = {sub for _, _, _, sub in CATEGORIES if sub}
    budget = [MAX_ENTRIES]
    any_truncated = False
    total_files = 0
    total_bytes = 0
    out = []

    for cat_id, label, description, sub in CATEGORIES:
        if sub is None:
            root = data_dir
            skip = set(category_dirs) | {"__pycache__"}
        else:
            root = data_dir / sub
            skip = set()
        if root.is_dir():
            files, size, truncated = _measure(root, skip, budget)
        else:
            files, size, truncated = 0, 0, False
        any_truncated = any_truncated or truncated
        total_files += files
        total_bytes += size
        out.append(
            {
                "id": cat_id,
                "label": label,
                "description": description,
                "files": files,
                "bytes": size,
                "truncated": truncated,
            }
        )

    return {
        "categories": out,
        "total": {"files": total_files, "bytes": total_bytes},
        "truncated": any_truncated,
    }
