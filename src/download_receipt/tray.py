"""System-tray integration kept separate from the Tk interface."""

from __future__ import annotations

from collections.abc import Callable

from PIL import Image, ImageDraw
from pystray import Icon, Menu, MenuItem


class TrayController:
    def __init__(
        self,
        *,
        show: Callable[[], None],
        scan: Callable[[], None],
        quit_app: Callable[[], None],
        labels: tuple[str, str, str],
    ) -> None:
        self.show_callback = show
        self.scan_callback = scan
        self.quit_callback = quit_app
        show_label, scan_label, quit_label = labels
        self.icon = Icon(
            "DownloadReceipt",
            _make_icon(),
            "Download Receipt",
            Menu(
                MenuItem(show_label, self._show, default=True),
                MenuItem(scan_label, self._scan),
                MenuItem(quit_label, self._quit),
            ),
        )

    def start(self) -> None:
        self.icon.run_detached()

    def stop(self) -> None:
        self.icon.stop()

    def _show(self, _icon: Icon, _item: MenuItem) -> None:
        self.show_callback()

    def _scan(self, _icon: Icon, _item: MenuItem) -> None:
        self.scan_callback()

    def _quit(self, _icon: Icon, _item: MenuItem) -> None:
        self.quit_callback()


def _make_icon() -> Image.Image:
    image = Image.new("RGBA", (64, 64), "#183C34")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((15, 9, 49, 55), radius=4, fill="white")
    draw.rectangle((22, 19, 42, 23), fill="#1E765F")
    draw.rectangle((22, 30, 42, 34), fill="#7AAE9F")
    draw.rectangle((22, 41, 36, 45), fill="#7AAE9F")
    return image
