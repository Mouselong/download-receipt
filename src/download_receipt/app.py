"""Tk desktop interface for Download Receipt."""

from __future__ import annotations

import os
import queue
import subprocess
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .database import ReceiptRepository
from .formatting import format_bytes, format_timestamp
from .models import Receipt
from .paths import app_data_folder
from .scanner import DownloadScanner, ScanResult
from .settings import Settings, SettingsStore


FILTERS = {
    "All receipts": "all",
    "With source": "with_source",
    "Needs a note": "needs_note",
    "Duplicates": "duplicates",
}


class ReceiptApp(tk.Tk):
    """Main application window."""

    def __init__(self, data_folder: Path | None = None) -> None:
        super().__init__()
        self.title("Download Receipt")
        self.geometry("1180x720")
        self.minsize(920, 600)

        self.data_folder = data_folder or app_data_folder()
        self.repository = ReceiptRepository(self.data_folder / "receipts.db")
        self.scanner = DownloadScanner(self.repository)
        self.settings_store = SettingsStore(self.data_folder / "settings.json")
        self.settings = self.settings_store.load()

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.receipts: dict[int, Receipt] = {}
        self.selected_id: int | None = None
        self.scan_running = False
        self.scan_timer: str | None = None
        self.search_timer: str | None = None

        self.search_var = tk.StringVar()
        self.filter_var = tk.StringVar(value="All receipts")
        self.folder_var = tk.StringVar(value=str(self.settings.watch_folder))
        self.status_var = tk.StringVar(value="Ready")
        self.summary_var = tk.StringVar(value="0 receipts")

        self._configure_style()
        self._build_menu()
        self._build_ui()
        self.search_var.trace_add("write", self._queue_refresh)
        self.protocol("WM_DELETE_WINDOW", self._close)

        self.after(100, self._poll_events)
        self.refresh_receipts()
        if self.settings.automatic_scan:
            self.after(700, lambda: self.begin_scan(silent=True))

    def _configure_style(self) -> None:
        self.configure(background="#F4F5F1")
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#F4F5F1")
        style.configure("Surface.TFrame", background="#FFFFFF")
        style.configure(
            "TLabel", background="#F4F5F1", foreground="#25302D", font=("Segoe UI", 10)
        )
        style.configure(
            "Muted.TLabel", background="#F4F5F1", foreground="#65716D", font=("Segoe UI", 9)
        )
        style.configure(
            "Header.TLabel",
            background="#183C34",
            foreground="#FFFFFF",
            font=("Segoe UI Semibold", 19),
        )
        style.configure(
            "HeaderSub.TLabel",
            background="#183C34",
            foreground="#C7D8D2",
            font=("Segoe UI", 9),
        )
        style.configure(
            "PanelTitle.TLabel",
            background="#FFFFFF",
            foreground="#25302D",
            font=("Segoe UI Semibold", 12),
        )
        style.configure(
            "DetailKey.TLabel",
            background="#FFFFFF",
            foreground="#77827E",
            font=("Segoe UI", 8),
        )
        style.configure(
            "DetailValue.TLabel",
            background="#FFFFFF",
            foreground="#25302D",
            font=("Segoe UI", 10),
        )
        style.configure(
            "Accent.TButton",
            background="#1E765F",
            foreground="#FFFFFF",
            borderwidth=0,
            padding=(14, 8),
            font=("Segoe UI Semibold", 9),
        )
        style.map("Accent.TButton", background=[("active", "#185F4D")])
        style.configure("TButton", padding=(11, 7), font=("Segoe UI", 9))
        style.configure(
            "Treeview",
            background="#FFFFFF",
            fieldbackground="#FFFFFF",
            foreground="#25302D",
            rowheight=36,
            borderwidth=0,
            font=("Segoe UI", 9),
        )
        style.configure(
            "Treeview.Heading",
            background="#EEF1ED",
            foreground="#4C5A55",
            padding=(7, 8),
            relief="flat",
            font=("Segoe UI Semibold", 9),
        )
        style.map("Treeview", background=[("selected", "#D9EBE4")], foreground=[("selected", "#19362F")])
        style.configure("TEntry", padding=8)
        style.configure("TCombobox", padding=6)

    def _build_menu(self) -> None:
        menu = tk.Menu(self)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Add file...", command=self.add_file)
        file_menu.add_command(label="Choose watch folder...", command=self.choose_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._close)
        menu.add_cascade(label="File", menu=file_menu)

        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="About", command=self.show_about)
        menu.add_cascade(label="Help", menu=help_menu)
        self.config(menu=menu)

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg="#183C34", height=86)
        header.pack(fill="x")
        header.pack_propagate(False)

        header_text = tk.Frame(header, bg="#183C34")
        header_text.pack(side="left", fill="y", padx=(24, 16), pady=15)
        ttk.Label(header_text, text="Download Receipt", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            header_text,
            text="Local history for the files you download",
            style="HeaderSub.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        header_actions = tk.Frame(header, bg="#183C34")
        header_actions.pack(side="right", padx=24, pady=21)
        ttk.Button(header_actions, text="Add file", command=self.add_file).pack(
            side="left", padx=(0, 8)
        )
        self.scan_button = ttk.Button(
            header_actions, text="Scan now", style="Accent.TButton", command=self.begin_scan
        )
        self.scan_button.pack(side="left")

        body = ttk.Frame(self, padding=(20, 16, 20, 0))
        body.pack(fill="both", expand=True)

        toolbar = ttk.Frame(body)
        toolbar.pack(fill="x", pady=(0, 12))
        ttk.Label(toolbar, textvariable=self.summary_var).pack(side="left")

        folder_button = ttk.Button(toolbar, text="Watch folder", command=self.choose_folder)
        folder_button.pack(side="right")
        ttk.Label(toolbar, textvariable=self.folder_var, style="Muted.TLabel").pack(
            side="right", padx=(12, 8)
        )

        controls = ttk.Frame(body)
        controls.pack(fill="x", pady=(0, 10))
        ttk.Label(controls, text="Search").pack(side="left", padx=(0, 8))
        search = ttk.Entry(controls, textvariable=self.search_var)
        search.pack(side="left", fill="x", expand=True, padx=(0, 10))
        search.insert(0, "")
        filter_box = ttk.Combobox(
            controls,
            textvariable=self.filter_var,
            values=list(FILTERS),
            state="readonly",
            width=18,
        )
        filter_box.pack(side="right")
        filter_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh_receipts())

        panes = ttk.Panedwindow(body, orient="horizontal")
        panes.pack(fill="both", expand=True)

        list_panel = ttk.Frame(panes, style="Surface.TFrame")
        detail_panel = ttk.Frame(panes, style="Surface.TFrame", padding=18)
        panes.add(list_panel, weight=3)
        panes.add(detail_panel, weight=2)

        self.tree = ttk.Treeview(
            list_panel,
            columns=("source", "seen", "size", "note"),
            show="tree headings",
            selectmode="browse",
        )
        self.tree.heading("#0", text="File")
        self.tree.heading("source", text="Source")
        self.tree.heading("seen", text="Saved")
        self.tree.heading("size", text="Size")
        self.tree.heading("note", text="Note")
        self.tree.column("#0", width=255, minwidth=160)
        self.tree.column("source", width=155, minwidth=110)
        self.tree.column("seen", width=132, minwidth=115)
        self.tree.column("size", width=75, minwidth=65, anchor="e")
        self.tree.column("note", width=190, minwidth=100)
        self.tree.tag_configure("duplicate", foreground="#B14E2F")
        self.tree.tag_configure("no_source", foreground="#6D7773")
        scrollbar = ttk.Scrollbar(list_panel, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._select_receipt)
        self.tree.bind("<Double-1>", lambda _event: self.open_file())

        self._build_detail_panel(detail_panel)

        status = ttk.Frame(self, padding=(20, 7))
        status.pack(fill="x")
        ttk.Label(status, textvariable=self.status_var, style="Muted.TLabel").pack(side="left")
        ttk.Label(status, text=f"v{__version__}", style="Muted.TLabel").pack(side="right")

    def _build_detail_panel(self, panel: ttk.Frame) -> None:
        ttk.Label(panel, text="Receipt details", style="PanelTitle.TLabel").pack(anchor="w")
        self.detail_name = self._detail_field(panel, "FILE", "Select a receipt")
        self.detail_source = self._detail_field(panel, "SOURCE", "Not available")
        self.detail_time = self._detail_field(panel, "FIRST SAVED", "-")
        self.detail_path = self._detail_field(panel, "LOCAL PATH", "-", wrap=350)
        self.detail_url = self._detail_field(panel, "SOURCE URL", "-", wrap=350)
        self.detail_hash = self._detail_field(panel, "SHA-256", "-", wrap=350)

        ttk.Label(panel, text="NOTE", style="DetailKey.TLabel").pack(anchor="w", pady=(13, 4))
        self.note_text = tk.Text(
            panel,
            height=4,
            wrap="word",
            relief="solid",
            borderwidth=1,
            highlightthickness=0,
            font=("Segoe UI", 9),
            background="#FAFBF9",
            foreground="#25302D",
        )
        self.note_text.pack(fill="x")

        action_row = ttk.Frame(panel, style="Surface.TFrame")
        action_row.pack(fill="x", pady=(12, 0))
        self.save_note_button = ttk.Button(
            action_row, text="Save note", style="Accent.TButton", command=self.save_note
        )
        self.save_note_button.pack(side="left")
        ttk.Button(action_row, text="Open source", command=self.open_source).pack(
            side="left", padx=8
        )

        action_row_two = ttk.Frame(panel, style="Surface.TFrame")
        action_row_two.pack(fill="x", pady=(8, 0))
        ttk.Button(action_row_two, text="Open file", command=self.open_file).pack(side="left")
        ttk.Button(action_row_two, text="Show in folder", command=self.open_folder).pack(
            side="left", padx=8
        )
        ttk.Button(action_row_two, text="Remove receipt", command=self.remove_receipt).pack(
            side="right"
        )

    @staticmethod
    def _detail_field(
        parent: ttk.Frame, key: str, value: str, *, wrap: int | None = None
    ) -> ttk.Label:
        ttk.Label(parent, text=key, style="DetailKey.TLabel").pack(anchor="w", pady=(13, 2))
        label = ttk.Label(
            parent,
            text=value,
            style="DetailValue.TLabel",
            wraplength=wrap or 0,
            justify="left",
        )
        label.pack(anchor="w", fill="x")
        return label

    def refresh_receipts(self, select_id: int | None = None) -> None:
        filter_name = FILTERS.get(self.filter_var.get(), "all")
        receipts = self.repository.list(self.search_var.get(), filter_name)
        self.receipts = {receipt.id: receipt for receipt in receipts}
        current = select_id or self.selected_id

        self.tree.delete(*self.tree.get_children())
        for receipt in receipts:
            tags: tuple[str, ...] = ()
            if receipt.is_duplicate:
                tags = ("duplicate",)
            elif not receipt.source_domain:
                tags = ("no_source",)
            self.tree.insert(
                "",
                "end",
                iid=str(receipt.id),
                text=receipt.file_name,
                values=(
                    receipt.source_domain or "Unknown",
                    format_timestamp(receipt.first_seen_at),
                    format_bytes(receipt.file_size),
                    receipt.note,
                ),
                tags=tags,
            )

        stats = self.repository.stats()
        self.summary_var.set(
            f"{stats['total']} receipts  |  {stats['sourced']} with source  |  "
            f"{stats['noted']} with notes"
        )
        if current is not None and str(current) in self.tree.get_children():
            self.tree.selection_set(str(current))
            self.tree.focus(str(current))
            self.tree.see(str(current))
        elif receipts:
            first_id = str(receipts[0].id)
            self.tree.selection_set(first_id)
            self.tree.focus(first_id)
        else:
            self._show_receipt(None)

    def _queue_refresh(self, *_args: object) -> None:
        if self.search_timer:
            self.after_cancel(self.search_timer)
        self.search_timer = self.after(220, self.refresh_receipts)

    def _select_receipt(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        self.selected_id = int(selection[0])
        self._show_receipt(self.receipts.get(self.selected_id))

    def _show_receipt(self, receipt: Receipt | None) -> None:
        if receipt is None:
            values = ("Select a receipt", "Not available", "-", "-", "-", "-")
            note = ""
        else:
            source_url = receipt.referrer_url or receipt.host_url
            hash_text = receipt.sha256 or "Not calculated for files over 200 MB"
            if receipt.is_duplicate:
                hash_text += "  (duplicate found)"
            values = (
                receipt.file_name,
                receipt.source_domain or "Unknown",
                format_timestamp(receipt.first_seen_at),
                receipt.path,
                source_url or "Not stored by the browser",
                hash_text,
            )
            note = receipt.note

        for label, value in zip(
            (
                self.detail_name,
                self.detail_source,
                self.detail_time,
                self.detail_path,
                self.detail_url,
                self.detail_hash,
            ),
            values,
            strict=True,
        ):
            label.configure(text=value)
        self.note_text.delete("1.0", "end")
        self.note_text.insert("1.0", note)

    def begin_scan(self, silent: bool = False) -> None:
        if self.scan_running:
            return
        if self.scan_timer:
            self.after_cancel(self.scan_timer)
            self.scan_timer = None
        folder = self.settings.watch_folder
        if not folder.is_dir():
            if not silent:
                messagebox.showerror("Folder not found", f"The folder does not exist:\n{folder}")
            self._schedule_scan()
            return

        self.scan_running = True
        self.scan_button.configure(state="disabled", text="Scanning...")
        self.status_var.set(f"Scanning {folder}")
        threading.Thread(target=self._scan_worker, args=(folder,), daemon=True).start()

    def _scan_worker(self, folder: Path) -> None:
        try:
            self.events.put(("scan_done", self.scanner.scan_folder(folder)))
        except Exception as error:
            self.events.put(("scan_error", error))

    def add_file(self) -> None:
        selected = filedialog.askopenfilename(title="Add a download receipt")
        if not selected:
            return
        self.status_var.set(f"Reading {Path(selected).name}")

        def worker() -> None:
            try:
                receipt_id = self.scanner.scan_file(Path(selected))
                self.events.put(("file_done", receipt_id))
            except Exception as error:
                self.events.put(("file_error", error))

        threading.Thread(target=worker, daemon=True).start()

    def choose_folder(self) -> None:
        selected = filedialog.askdirectory(
            title="Choose the folder to watch", initialdir=self.settings.watch_folder
        )
        if not selected:
            return
        self.settings.watch_folder = Path(selected)
        self.settings_store.save(self.settings)
        self.folder_var.set(selected)
        self.status_var.set("Watch folder updated")
        self.begin_scan()

    def save_note(self) -> None:
        if self.selected_id is None:
            return
        self.repository.update_note(self.selected_id, self.note_text.get("1.0", "end"))
        self.status_var.set("Note saved")
        self.refresh_receipts(select_id=self.selected_id)

    def open_file(self) -> None:
        receipt = self._selected_receipt()
        if not receipt:
            return
        path = Path(receipt.path)
        if not path.exists():
            messagebox.showerror("File not found", "The file has been moved or deleted.")
            return
        os.startfile(path)  # type: ignore[attr-defined]

    def open_folder(self) -> None:
        receipt = self._selected_receipt()
        if not receipt:
            return
        path = Path(receipt.path)
        if not path.exists():
            messagebox.showerror("File not found", "The file has been moved or deleted.")
            return
        subprocess.Popen(["explorer", "/select,", str(path)])

    def open_source(self) -> None:
        receipt = self._selected_receipt()
        if not receipt:
            return
        url = receipt.referrer_url or receipt.host_url
        if not url:
            messagebox.showinfo("No source URL", "This browser did not store a source URL.")
            return
        webbrowser.open(url)

    def remove_receipt(self) -> None:
        receipt = self._selected_receipt()
        if not receipt:
            return
        confirmed = messagebox.askyesno(
            "Remove receipt",
            "Remove this receipt from the local history?\n\nThe file itself will not be deleted.",
        )
        if not confirmed:
            return
        self.repository.delete(receipt.id)
        self.selected_id = None
        self.status_var.set("Receipt removed; the file was not changed")
        self.refresh_receipts()

    def _selected_receipt(self) -> Receipt | None:
        if self.selected_id is None:
            return None
        return self.repository.get(self.selected_id)

    def _poll_events(self) -> None:
        try:
            while True:
                event_name, payload = self.events.get_nowait()
                if event_name == "scan_done":
                    result = payload
                    assert isinstance(result, ScanResult)
                    self.scan_running = False
                    self.scan_button.configure(state="normal", text="Scan now")
                    self.status_var.set(
                        f"Scan complete: {result.added} new, {result.updated} refreshed, "
                        f"{result.failed} unavailable"
                    )
                    self.refresh_receipts()
                    self._schedule_scan()
                elif event_name == "scan_error":
                    self.scan_running = False
                    self.scan_button.configure(state="normal", text="Scan now")
                    self.status_var.set("Scan failed")
                    messagebox.showerror("Scan failed", str(payload))
                    self._schedule_scan()
                elif event_name == "file_done":
                    receipt_id = int(payload)
                    self.status_var.set("Receipt saved")
                    self.refresh_receipts(select_id=receipt_id)
                elif event_name == "file_error":
                    self.status_var.set("Could not read file")
                    messagebox.showerror("Could not add file", str(payload))
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _schedule_scan(self) -> None:
        if self.settings.automatic_scan:
            milliseconds = self.settings.scan_interval_seconds * 1000
            self.scan_timer = self.after(milliseconds, lambda: self.begin_scan(silent=True))

    def show_about(self) -> None:
        messagebox.showinfo(
            "About Download Receipt",
            f"Download Receipt {__version__}\n\n"
            "A local, open-source history for Windows downloads.\n"
            "No file data is uploaded.",
        )

    def _close(self) -> None:
        self.settings_store.save(self.settings)
        self.destroy()


def run() -> None:
    app = ReceiptApp()
    app.mainloop()
