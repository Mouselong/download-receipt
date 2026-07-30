"""Platform-specific application paths."""

from __future__ import annotations

import os
from pathlib import Path


DOWNLOADS_FOLDER_ID = "{374DE290-123F-4565-9164-39C4925E467B}"


def default_downloads_folder() -> Path:
    """Resolve the user's configured Windows Downloads folder."""

    if os.name == "nt":
        try:
            import winreg

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                value, _ = winreg.QueryValueEx(key, DOWNLOADS_FOLDER_ID)
            return Path(os.path.expandvars(value)).expanduser()
        except (OSError, ValueError):
            pass
    return Path.home() / "Downloads"


def app_data_folder() -> Path:
    """Return the private per-user directory for the database and settings."""

    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "DownloadReceipt"
    return Path.home() / ".download-receipt"
