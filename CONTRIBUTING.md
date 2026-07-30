# Contributing

Thanks for helping improve Download Receipt.

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m unittest discover -s tests -v
python -m download_receipt
```

Keep pull requests focused. New behavior should include a test where practical,
and user-facing changes should be added to `CHANGELOG.md`.

## Reporting bugs

Include your Windows version, browser, the file type involved, and whether the
file still has a `Zone.Identifier` stream. Never attach private downloaded
files or full source URLs containing account tokens.
