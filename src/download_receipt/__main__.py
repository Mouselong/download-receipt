"""Launch Download Receipt with ``python -m download_receipt``."""

import argparse

from download_receipt.app import run


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="download-receipt")
    parser.add_argument("--minimized", action="store_true")
    parser.add_argument("--version", action="store_true")
    arguments = parser.parse_args()
    if arguments.version:
        from download_receipt import __version__

        print(__version__)
    else:
        run(start_minimized=arguments.minimized)
