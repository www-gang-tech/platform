"""Filesystem helpers for Studio content mutations."""

from __future__ import annotations

import os
from pathlib import Path


def rename_content_file_exclusive(old_file: Path, new_file: Path) -> None:
    """
    Rename old_file → new_file without silently overwriting an existing target.

    Linux os.rename replaces destinations; a prior exists() check is racy with
    concurrent Studio writes. Create the destination exclusively first.
    """
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(new_file), flags)
    except FileExistsError as exc:
        raise FileExistsError(f'Destination already exists: {new_file}') from exc
    os.close(fd)
    try:
        os.replace(str(old_file), str(new_file))
    except Exception:
        try:
            new_file.unlink(missing_ok=True)
        except TypeError:
            if new_file.exists():
                new_file.unlink()
        raise
