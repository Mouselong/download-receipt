from __future__ import annotations

import unittest

from download_receipt.models import Receipt
from download_receipt.sorting import sort_receipts


def make_receipt(receipt_id: int, name: str, size: int, saved: str) -> Receipt:
    return Receipt(
        id=receipt_id,
        path=f"C:\\Downloads\\{name}",
        file_name=name,
        file_size=size,
        modified_at=saved,
        first_seen_at=saved,
        last_seen_at=saved,
        host_url=None,
        referrer_url=None,
        source_domain=None,
        zone_id=None,
        sha256=None,
        file_identity=None,
        disposition="inbox",
        note="",
        is_missing=False,
    )


class ReceiptSortingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.receipts = [
            make_receipt(1, "Beta.zip", 20, "2026-07-31T10:00:00+00:00"),
            make_receipt(2, "alpha.zip", 40, "2026-07-30T10:00:00+00:00"),
            make_receipt(3, "Gamma.zip", 10, "2026-07-29T10:00:00+00:00"),
        ]

    def test_sort_by_size_and_name(self) -> None:
        self.assertEqual(
            [receipt.id for receipt in sort_receipts(self.receipts, "largest")], [2, 1, 3]
        )
        self.assertEqual(
            [receipt.id for receipt in sort_receipts(self.receipts, "name_asc")], [2, 1, 3]
        )

    def test_default_and_oldest_sort_by_saved_time(self) -> None:
        self.assertEqual(
            [receipt.id for receipt in sort_receipts(self.receipts, "newest")], [1, 2, 3]
        )
        self.assertEqual(
            [receipt.id for receipt in sort_receipts(self.receipts, "oldest")], [3, 2, 1]
        )


if __name__ == "__main__":
    unittest.main()
