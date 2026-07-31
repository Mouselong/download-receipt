"""Manage the optional per-user Windows startup entry."""

from __future__ import annotations

import os
import sys


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "DownloadReceipt"


def startup_command() -> str:
    executable = os.path.abspath(sys.executable)
    if getattr(sys, "frozen", False):
        return f'"{executable}" --minimized'
    return f'"{executable}" -m download_receipt --minimized'


def set_startup_enabled(enabled: bool) -> None:
    if os.name != "nt":
        return
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
