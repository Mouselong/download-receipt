# Changelog

All notable changes to this project will be documented here.

## [0.2.0] - 2026-07-31

### Added

- Detect missing files and reconnect a receipt after a file is moved.
- Preserve replaced files as historical receipt versions instead of overwriting them.
- Scan subfolders when recursive scanning is enabled.
- Export the complete local history to CSV or JSON.
- Configure automatic scanning, interval, language, tray behavior, and Windows startup.
- Run in the Windows system tray and provide a first-run guide.
- Automatically use Simplified Chinese on Chinese Windows installations.
- Organize downloads as inbox, keep, later, or remove items.

### Changed

- Restrict source links to normal HTTP and HTTPS addresses.
- Expand the automated test suite to cover migration and file lifecycle behavior.
- Smoke-test the packaged Windows executable before publishing a release.

## [0.1.0] - 2026-07-29

### Added

- Read `HostUrl`, `ReferrerUrl`, and `ZoneId` from Windows download metadata.
- Scan a Downloads folder and preserve receipts in local SQLite storage.
- Search and filter receipts by file, source, date, and note.
- Add personal notes and open the original file, folder, or source page.
- Detect duplicate files with SHA-256 fingerprints up to 200 MB.
- Build a standalone Windows executable from a version tag on GitHub.
