from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from download_receipt.database import ReceiptRepository
from download_receipt.provenance import ZoneInfo
from download_receipt.scanner import DownloadScanner


class DownloadScannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.repository = ReceiptRepository(self.root / "data" / "receipts.db")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @staticmethod
    def fake_provenance(_path: Path) -> ZoneInfo:
        return ZoneInfo(
            zone_id=3,
            host_url="https://cdn.example.com/item.zip",
            referrer_url="https://example.com/downloads",
        )

    def test_scan_file_creates_searchable_receipt(self) -> None:
        file_path = self.root / "manual.pdf"
        file_path.write_bytes(b"same content")
        scanner = DownloadScanner(
            self.repository, provenance_reader=self.fake_provenance
        )

        receipt_id = scanner.scan_file(file_path)
        receipt = self.repository.get(receipt_id)

        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertEqual(receipt.source_domain, "example.com")
        self.assertEqual(receipt.file_size, 12)
        self.assertIsNotNone(receipt.sha256)

    def test_folder_scan_ignores_partial_downloads(self) -> None:
        (self.root / "finished.zip").write_bytes(b"done")
        (self.root / "waiting.crdownload").write_bytes(b"partial")
        scanner = DownloadScanner(
            self.repository, provenance_reader=self.fake_provenance
        )

        result = scanner.scan_folder(self.root)

        self.assertEqual(result.scanned, 1)
        self.assertEqual(result.added, 1)
        self.assertEqual(len(self.repository.list()), 1)

    def test_same_content_is_reported_as_duplicate(self) -> None:
        first = self.root / "first.txt"
        second = self.root / "second.txt"
        first.write_text("repeat", encoding="utf-8")
        second.write_text("repeat", encoding="utf-8")
        scanner = DownloadScanner(
            self.repository, provenance_reader=self.fake_provenance
        )

        scanner.scan_file(first)
        scanner.scan_file(second)

        self.assertEqual(len(self.repository.list(filter_name="duplicates")), 2)


if __name__ == "__main__":
    unittest.main()
