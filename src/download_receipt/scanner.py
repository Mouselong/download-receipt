"""Discover files and turn them into download receipts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .database import ReceiptRepository
from .provenance import ZoneInfo, domain_from_url, read_zone_identifier


TEMPORARY_SUFFIXES = {".crdownload", ".download", ".part", ".partial", ".tmp"}


@dataclass(frozen=True, slots=True)
class ScanResult:
    scanned: int = 0
    added: int = 0
    updated: int = 0
    failed: int = 0


class DownloadScanner:
    """Scan files without holding a long-lived database connection."""

    def __init__(
        self,
        repository: ReceiptRepository,
        *,
        hash_limit_bytes: int = 200 * 1024 * 1024,
        provenance_reader: Callable[[Path], ZoneInfo] = read_zone_identifier,
    ) -> None:
        self.repository = repository
        self.hash_limit_bytes = hash_limit_bytes
        self.provenance_reader = provenance_reader

    def scan_folder(self, folder: Path, *, recursive: bool = False) -> ScanResult:
        if not folder.is_dir():
            raise NotADirectoryError(folder)

        entries = folder.rglob("*") if recursive else folder.iterdir()
        scanned = added = updated = failed = 0
        present_paths: set[str] = set()
        for path in entries:
            if not path.is_file() or self._should_skip(path):
                continue
            resolved_path = str(path.resolve())
            present_paths.add(resolved_path)
            scanned += 1
            try:
                existed = self.repository.get_by_path(resolved_path) is not None
                self.scan_file(path)
                if existed:
                    updated += 1
                else:
                    added += 1
            except (OSError, PermissionError):
                failed += 1

        self.repository.mark_missing_in_folder(folder, present_paths, recursive=recursive)
        return ScanResult(scanned, added, updated, failed)

    def scan_file(self, path: Path) -> int:
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        if self._should_skip(path):
            raise ValueError(f"Temporary downloads are ignored: {path.name}")

        stat = path.stat()
        existing = self.repository.get_by_path(str(path))
        modified_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        file_identity = _file_identity(stat)
        zone = self.provenance_reader(path)
        source_url = zone.referrer_url or zone.host_url

        digest: str | None = None
        unchanged = (
            existing is not None
            and (existing.file_identity is None or existing.file_identity == file_identity)
            and existing.file_size == stat.st_size
            and existing.modified_at == modified_at
        )
        if unchanged:
            digest = existing.sha256
        elif stat.st_size <= self.hash_limit_bytes:
            digest = _sha256(path)

        return self.repository.upsert(
            path=str(path),
            file_name=path.name,
            file_size=stat.st_size,
            modified_at=modified_at,
            seen_at=datetime.now(tz=timezone.utc).isoformat(),
            host_url=zone.host_url,
            referrer_url=zone.referrer_url,
            source_domain=domain_from_url(source_url),
            zone_id=zone.zone_id,
            sha256=digest,
            file_identity=file_identity,
        )

    def relocate(self, receipt_id: int, path: Path) -> int:
        """Reconnect a missing receipt to the same file at a new path."""

        receipt = self.repository.get(receipt_id)
        if receipt is None or not receipt.is_current or not receipt.is_missing:
            raise ValueError("Only a missing current receipt can be relocated.")
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        stat = path.stat()
        digest = _sha256(path) if stat.st_size <= self.hash_limit_bytes else None
        if receipt.sha256 and digest and receipt.sha256 != digest:
            raise ValueError("The selected file does not match the saved receipt.")
        if receipt.sha256 is None and receipt.file_size != stat.st_size:
            raise ValueError("The selected file size does not match the saved receipt.")
        modified_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        seen_at = datetime.now(tz=timezone.utc).isoformat()
        self.repository.relocate(
            receipt_id,
            new_path=str(path),
            file_size=stat.st_size,
            modified_at=modified_at,
            file_identity=_file_identity(stat),
            sha256=digest,
            seen_at=seen_at,
        )
        return receipt_id

    @staticmethod
    def _should_skip(path: Path) -> bool:
        return path.suffix.lower() in TEMPORARY_SUFFIXES or path.name.endswith(
            ":Zone.Identifier"
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_identity(stat: object) -> str | None:
    device = int(getattr(stat, "st_dev", 0))
    inode = int(getattr(stat, "st_ino", 0))
    if not inode:
        return None
    return f"{device:x}:{inode:x}"
