"""Human-readable display formatting."""

from __future__ import annotations

from datetime import datetime


def format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def format_timestamp(value: str) -> str:
    try:
        timestamp = datetime.fromisoformat(value).astimezone()
    except ValueError:
        return value
    return timestamp.strftime("%Y-%m-%d %H:%M")
