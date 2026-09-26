"""Filesystem paths scoped to an authenticated Alf user."""

import os
import stat
from pathlib import Path


def ensure_user_directory(data_path: str | Path, user_id: str) -> Path:
    user_id = str(user_id)
    if not user_id or user_id in {".", ".."} or "/" in user_id or "\\" in user_id or "\0" in user_id:
        raise ValueError("invalid user id")

    root = Path(data_path)
    if root.is_symlink():
        raise ValueError("DATA_PATH must not be a symlink")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or not stat.S_ISDIR(root.lstat().st_mode):
        raise ValueError("DATA_PATH must be a directory")
    root.chmod(0o700)

    user_path = root / user_id
    if user_path.is_symlink():
        raise ValueError("user data path must not be a symlink")
    user_path.mkdir(mode=0o700, exist_ok=True)
    if user_path.is_symlink() or not stat.S_ISDIR(user_path.lstat().st_mode):
        raise ValueError("user data path must be a directory")
    user_path.chmod(0o700)
    return user_path
