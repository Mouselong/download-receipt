"""Read download provenance stored by Windows."""

from __future__ import annotations

from configparser import ConfigParser, Error as ConfigParserError
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class ZoneInfo:
    """Values extracted from a Windows Zone.Identifier stream."""

    zone_id: int | None = None
    host_url: str | None = None
    referrer_url: str | None = None


def parse_zone_identifier(content: str) -> ZoneInfo:
    """Parse a Zone.Identifier INI payload without interpolating URL values."""

    parser = ConfigParser(interpolation=None)
    try:
        parser.read_string(content.lstrip("\ufeff"))
    except ConfigParserError:
        return ZoneInfo()

    if not parser.has_section("ZoneTransfer"):
        return ZoneInfo()

    section = parser["ZoneTransfer"]
    zone_id: int | None = None
    try:
        zone_id = section.getint("ZoneId", fallback=None)
    except ValueError:
        pass

    return ZoneInfo(
        zone_id=zone_id,
        host_url=_clean_value(section.get("HostUrl", fallback=None)),
        referrer_url=_clean_value(section.get("ReferrerUrl", fallback=None)),
    )


def read_zone_identifier(file_path: Path) -> ZoneInfo:
    """Read a file's NTFS Zone.Identifier alternate data stream.

    Missing metadata is normal: browsers do not always write URL fields, and
    alternate streams can disappear when a file is copied to another drive.
    """

    stream_path = f"{file_path}:Zone.Identifier"
    try:
        with open(stream_path, "r", encoding="utf-8-sig", errors="replace") as stream:
            return parse_zone_identifier(stream.read())
    except (FileNotFoundError, OSError):
        return ZoneInfo()


def domain_from_url(url: str | None) -> str | None:
    """Return a display-friendly domain for an HTTP(S) URL."""

    safe_url = safe_source_url(url)
    if not safe_url:
        return None
    hostname = urlparse(safe_url).hostname
    if not hostname:
        return None
    hostname = hostname.lower()
    return hostname[4:] if hostname.startswith("www.") else hostname


def safe_source_url(url: str | None) -> str | None:
    """Return a source URL only when it is a normal HTTP(S) web address."""

    if not url:
        return None
    candidate = url.strip()
    parsed = urlparse(candidate)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    return candidate


def _clean_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None
