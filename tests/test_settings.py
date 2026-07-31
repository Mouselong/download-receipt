from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from download_receipt.settings import Settings, SettingsStore


class SettingsStoreTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            store = SettingsStore(path)
            expected = Settings(
                watch_folder=Path(r"D:\Downloads"),
                automatic_scan=False,
                scan_interval_seconds=45,
                recursive_scan=True,
                minimize_to_tray=False,
                start_with_windows=True,
                language="zh_CN",
            )

            store.save(expected)
            actual = store.load()

            self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
