"""Sorting helpers for the receipt list."""

from __future__ import annotations

from collections.abc import Iterable

from .models import Receipt


SORT_OPTIONS = (
    ("Newest first", "newest"),
    ("Oldest first", "oldest"),
    ("Largest first", "largest"),
    ("Smallest first", "smallest"),
    ("Name A-Z", "name_asc"),
    ("Name Z-A", "name_desc"),
)


def sort_receipts(receipts: Iterable[Receipt], sort_name: str) -> list[Receipt]:
    """Return receipts in a stable, user-selected order."""

    items = list(receipts)
    if sort_name == "oldest":
        return sorted(items, key=lambda receipt: receipt.first_seen_at)
    if sort_name == "largest":
        return sorted(items, key=lambda receipt: receipt.file_size, reverse=True)
    if sort_name == "smallest":
        return sorted(items, key=lambda receipt: receipt.file_size)
    if sort_name == "name_asc":
        return sorted(items, key=lambda receipt: receipt.file_name.casefold())
    if sort_name == "name_desc":
        return sorted(items, key=lambda receipt: receipt.file_name.casefold(), reverse=True)
    return sorted(items, key=lambda receipt: receipt.first_seen_at, reverse=True)
