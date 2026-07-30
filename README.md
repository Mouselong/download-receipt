# Download Receipt

**A private, searchable history for files downloaded on Windows.**

[中文说明](README.zh-CN.md)

Windows browsers often store the original download address in a hidden NTFS
stream. File Explorer does not show it, and the information may disappear when
the file is moved to another file system. Download Receipt preserves that
context in a local database while it is still available.

![Download Receipt desktop application](docs/screenshot.png)

## What it does

- Watches a chosen Downloads folder and records new files.
- Reads `HostUrl`, `ReferrerUrl`, and `ZoneId` from `Zone.Identifier`.
- Searches by file name, source domain, URL, or personal note.
- Opens the file, its folder, or the source page in one click.
- Finds duplicate files using SHA-256 fingerprints up to 200 MB.
- Keeps all data in a local SQLite database with no account or telemetry.

## Install

The easiest installation method is the standalone `DownloadReceipt.exe` from
the repository's Releases page. It does not require Python.

To run from source on Windows 10 or 11:

```powershell
git clone https://github.com/Mouselong/download-receipt.git
cd download-receipt
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m download_receipt
```

The app stores its database and settings in
`%LOCALAPPDATA%\DownloadReceipt`. Removing a receipt never deletes the file.

## How it works

```text
Downloads folder
      |
      v
folder scanner ----> Zone.Identifier reader
      |                       |
      +-----------+-----------+
                  v
            local SQLite DB
                  |
                  v
       search, notes, duplicates
```

The source URL is selected from `ReferrerUrl` when available, otherwise
`HostUrl`. Files without either value are still recorded and shown as having an
unknown source.

## Limitations

- This is a Windows-first application because alternate data streams are an
  NTFS feature.
- Browsers and download tools are not required to save a source URL.
- Copying a file to FAT/exFAT, unblocking it, or using some archive tools can
  remove `Zone.Identifier` before the app sees it.
- Version 0.1 scans the top level of the chosen folder. Recursive scanning and
  browser-history fallback are planned improvements.

Download Receipt does not claim that a source is safe. It preserves provenance;
it is not an antivirus product.

## Development

The runtime uses only the Python standard library. Run the test suite with:

```powershell
python -m unittest discover -s tests -v
```

The project uses a `src` layout, separates UI, scanning, parsing, and persistence,
and runs tests on Windows through GitHub Actions. Pushing a tag such as `v0.1.0`
builds a standalone executable and attaches it to a GitHub Release.

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and the
[changelog](CHANGELOG.md) for project policies and release history.

## License

MIT
