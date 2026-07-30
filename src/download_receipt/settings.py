"""Tiny JSON-backed user settings store."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .paths import default_downloads_folder


@dataclass(slots=True)
class Settings:
    watch_folder: Path
    automatic_scan: bool = True
    scan_interval_seconds: int = 30


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> Settings:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return Settings(
                watch_folder=Path(payload["watch_folder"]),
                automatic_scan=bool(payload.get("automatic_scan", True)),
                scan_interval_seconds=max(
                    10, int(payload.get("scan_interval_seconds", 30))
                ),
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return Settings(watch_folder=default_downloads_folder())

    def save(self, settings: Settings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "watch_folder": str(settings.watch_folder),
            "automatic_scan": settings.automatic_scan,
            "scan_interval_seconds": settings.scan_interval_seconds,
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
