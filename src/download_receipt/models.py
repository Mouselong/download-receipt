"""Application data models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Receipt:
    """A locally stored receipt for one downloaded file."""

    id: int
    path: str
    file_name: str
    file_size: int
    modified_at: str
    first_seen_at: str
    last_seen_at: str
    host_url: str | None
    referrer_url: str | None
    source_domain: str | None
    zone_id: int | None
    sha256: str | None
    file_identity: str | None
    disposition: str
    note: str
    is_missing: bool
    is_current: bool = True
    superseded_at: str | None = None
    is_duplicate: bool = False
