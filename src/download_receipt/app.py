"""Tk desktop interface for Download Receipt."""

from __future__ import annotations

import csv
import json
import os
import queue
import subprocess
import threading
import tkinter as tk
import webbrowser
from dataclasses import asdict
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .database import ReceiptRepository
from .formatting import format_bytes, format_timestamp
from .i18n import resolve_language, translator
from .models import Receipt
from .paths import app_data_folder
from .provenance import safe_source_url
from .scanner import DownloadScanner, ScanResult
from .sorting import SORT_OPTIONS, sort_receipts
from .settings import SettingsStore
from .startup import set_startup_enabled

try:
    from .tray import TrayController
except ImportError:  # Source checkouts can still run before optional UI deps are installed.
    TrayController = None  # type: ignore[assignment,misc]


FILTER_NAMES = (
    ("All receipts", "all"),
    ("With source", "with_source"),
    ("Needs a note", "needs_note"),
    ("Duplicates", "duplicates"),
    ("Missing files", "missing"),
    ("Replaced versions", "replaced"),
    ("Download inbox", "inbox"),
    ("Marked for removal", "remove"),
)

DISPOSITIONS = (
    ("Inbox", "inbox"),
    ("Keep", "keep"),
    ("Later", "later"),
    ("Remove", "remove"),
)


class ReceiptApp(tk.Tk):
    """Main application window."""

    def __init__(
        self, data_folder: Path | None = None, *, start_minimized: bool = False
    ) -> None:
        super().__init__()
        self.title("Download Receipt")
        self.geometry("1180x720")
        self.minsize(920, 600)

        self.data_folder = data_folder or app_data_folder()
        self.repository = ReceiptRepository(self.data_folder / "receipts.db")
        self.scanner = DownloadScanner(self.repository)
        self.settings_store = SettingsStore(self.data_folder / "settings.json")
        self.first_run = not self.settings_store.path.exists()
        self.settings = self.settings_store.load()
        self.language = resolve_language(self.settings.language)
        self.tr = translator(self.settings.language)

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.receipts: dict[int, Receipt] = {}
        self.selected_id: int | None = None
        self.scan_running = False
        self.scan_timer: str | None = None
        self.search_timer: str | None = None
        self.exiting = False
        self.tray: TrayController | None = None

        self.filter_codes = {self.tr(label): code for label, code in FILTER_NAMES}
        self.disposition_codes = {self.tr(label): code for label, code in DISPOSITIONS}
        self.disposition_labels = {code: label for label, code in self.disposition_codes.items()}
        self.sort_codes = {self.tr(label): code for label, code in SORT_OPTIONS}
        self.search_var = tk.StringVar()
        self.filter_var = tk.StringVar(value=self.tr("All receipts"))
        self.sort_var = tk.StringVar(value=self.tr("Newest first"))
        self.folder_var = tk.StringVar(value=str(self.settings.watch_folder))
        self.status_var = tk.StringVar(value=self.tr("Ready"))
        self.summary_var = tk.StringVar(value="0")

        self._configure_style()
        self._build_menu()
        self._build_ui()
        self._start_tray()
        self.search_var.trace_add("write", self._queue_refresh)
        self.protocol("WM_DELETE_WINDOW", self._request_close)

        self.after(100, self._poll_events)
        self.refresh_receipts()
        if self.settings.automatic_scan:
            self.after(700, lambda: self.begin_scan(silent=True))
        if self.first_run:
            self.after(350, self.show_welcome)
        if start_minimized:
            self.after(50, self._hide_window)

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
        style.map(
            "Treeview",
            background=[("selected", "#D9EBE4")],
            foreground=[("selected", "#19362F")],
        )
        style.configure("TEntry", padding=8)
        style.configure("TCombobox", padding=6)

    def _build_menu(self) -> None:
        menu = tk.Menu(self)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label=self.tr("Add file..."), command=self.add_file)
        file_menu.add_command(
            label=self.tr("Choose watch folder..."), command=self.choose_folder
        )
        file_menu.add_command(label=self.tr("Export..."), command=self.export_receipts)
        file_menu.add_separator()
        file_menu.add_command(label=self.tr("Settings..."), command=self.show_settings)
        file_menu.add_separator()
        file_menu.add_command(label=self.tr("Exit"), command=self._quit)
        menu.add_cascade(label=self.tr("File"), menu=file_menu)

        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label=self.tr("About"), command=self.show_about)
        menu.add_cascade(label=self.tr("Help"), menu=help_menu)
        self.config(menu=menu)

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg="#183C34", height=86)
        header.pack(fill="x")
        header.pack_propagate(False)
        header_text = tk.Frame(header, bg="#183C34")
        header_text.pack(side="left", fill="y", padx=(24, 16), pady=15)
        ttk.Label(header_text, text=self.tr("Download Receipt"), style="Header.TLabel").pack(
            anchor="w"
        )
        ttk.Label(
            header_text,
            text=self.tr("Local history for the files you download"),
            style="HeaderSub.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        header_actions = tk.Frame(header, bg="#183C34")
        header_actions.pack(side="right", padx=24, pady=21)
        ttk.Button(header_actions, text=self.tr("Add file"), command=self.add_file).pack(
            side="left", padx=(0, 8)
        )
        self.scan_button = ttk.Button(
            header_actions,
            text=self.tr("Scan now"),
            style="Accent.TButton",
            command=self.begin_scan,
        )
        self.scan_button.pack(side="left")

        body = ttk.Frame(self, padding=(20, 16, 20, 0))
        body.pack(fill="both", expand=True)
        toolbar = ttk.Frame(body)
        toolbar.pack(fill="x", pady=(0, 12))
        ttk.Label(toolbar, textvariable=self.summary_var).pack(side="left")
        ttk.Button(toolbar, text=self.tr("Watch folder"), command=self.choose_folder).pack(
            side="right"
        )
        ttk.Label(toolbar, textvariable=self.folder_var, style="Muted.TLabel").pack(
            side="right", padx=(12, 8)
        )

        controls = ttk.Frame(body)
        controls.pack(fill="x", pady=(0, 10))
        ttk.Label(controls, text=self.tr("Search")).pack(side="left", padx=(0, 8))
        search = ttk.Entry(controls, textvariable=self.search_var)
        search.pack(side="left", fill="x", expand=True, padx=(0, 10))
        ttk.Label(controls, text=self.tr("Sort")).pack(side="right", padx=(12, 6))
        sort_box = ttk.Combobox(
            controls,
            textvariable=self.sort_var,
            values=list(self.sort_codes),
            state="readonly",
            width=16,
        )
        sort_box.pack(side="right")
        sort_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh_receipts())
        filter_box = ttk.Combobox(
            controls,
            textvariable=self.filter_var,
            values=list(self.filter_codes),
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
        self.tree.heading("#0", text=self.tr("File"))
        self.tree.heading("source", text=self.tr("Source"))
        self.tree.heading("seen", text=self.tr("Saved"))
        self.tree.heading("size", text=self.tr("Size"))
        self.tree.heading("note", text=self.tr("Note"))
        self.tree.column("#0", width=255, minwidth=160)
        self.tree.column("source", width=155, minwidth=110)
        self.tree.column("seen", width=132, minwidth=115)
        self.tree.column("size", width=75, minwidth=65, anchor="e")
        self.tree.column("note", width=190, minwidth=100)
        self.tree.tag_configure("duplicate", foreground="#B14E2F")
        self.tree.tag_configure("missing", foreground="#9A5A22")
        self.tree.tag_configure("replaced", foreground="#7B7B7B")
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
        ttk.Label(panel, text=self.tr("Receipt details"), style="PanelTitle.TLabel").pack(
            anchor="w"
        )
        fields = ttk.Frame(panel, style="Surface.TFrame")
        fields.pack(fill="x", pady=(6, 0))
        fields.columnconfigure(1, weight=1)
        self.detail_name = self._detail_field(
            fields, 0, self.tr("FILE"), self.tr("Select a receipt")
        )
        self.detail_status = self._detail_field(fields, 1, self.tr("STATUS"), "-")
        self.detail_source = self._detail_field(
            fields, 2, self.tr("SOURCE"), self.tr("Not available")
        )
        self.detail_time = self._detail_field(fields, 3, self.tr("FIRST SAVED"), "-")
        self.detail_path = self._detail_field(fields, 4, self.tr("LOCAL PATH"), "-", wrap=300)
        self.detail_url = self._detail_field(fields, 5, self.tr("SOURCE URL"), "-", wrap=300)
        self.detail_hash = self._detail_field(fields, 6, self.tr("SHA-256"), "-", wrap=300)
        organize = ttk.Frame(panel, style="Surface.TFrame")
        organize.pack(fill="x", pady=(6, 0))
        ttk.Label(organize, text=self.tr("ORGANIZE"), style="DetailKey.TLabel").pack(
            side="left", padx=(0, 10)
        )
        self.disposition_var = tk.StringVar(value=self.tr("Inbox"))
        self.disposition_box = ttk.Combobox(
            organize,
            textvariable=self.disposition_var,
            values=list(self.disposition_codes),
            state="readonly",
            width=16,
        )
        self.disposition_box.pack(side="left")
        self.disposition_box.bind("<<ComboboxSelected>>", self._change_disposition)
        ttk.Label(panel, text=self.tr("NOTE"), style="DetailKey.TLabel").pack(
            anchor="w", pady=(8, 4)
        )
        self.note_text = tk.Text(
            panel,
            height=3,
            wrap="word",
            relief="solid",
            borderwidth=1,
            highlightthickness=0,
            font=("Segoe UI", 9),
            background="#FAFBF9",
            foreground="#25302D",
        )
        self.note_text.pack(fill="x")
        self.bind("<Control-s>", lambda _event: self.save_note())

        action_row = ttk.Frame(panel, style="Surface.TFrame")
        action_row.pack(fill="x", pady=(12, 0))
        self.save_note_button = ttk.Button(
            action_row, text=self.tr("Save note"), style="Accent.TButton", command=self.save_note
        )
        self.save_note_button.pack(side="left")
        self.open_source_button = ttk.Button(
            action_row, text=self.tr("Open source"), command=self.open_source
        )
        self.open_source_button.pack(side="left", padx=8)

        action_row_two = ttk.Frame(panel, style="Surface.TFrame")
        action_row_two.pack(fill="x", pady=(8, 0))
        self.open_file_button = ttk.Button(
            action_row_two, text=self.tr("Open file"), command=self.open_file
        )
        self.open_file_button.pack(side="left")
        self.open_folder_button = ttk.Button(
            action_row_two, text=self.tr("Show in folder"), command=self.open_folder
        )
        self.open_folder_button.pack(side="left", padx=8)
        self.relocate_button = ttk.Button(
            action_row_two, text=self.tr("Relocate"), command=self.relocate_file
        )
        self.relocate_button.pack(side="left")
        ttk.Button(
            action_row_two, text=self.tr("Remove receipt"), command=self.remove_receipt
        ).pack(side="right")

        action_row_three = ttk.Frame(panel, style="Surface.TFrame")
        action_row_three.pack(fill="x", pady=(8, 0))
        self.copy_source_button = ttk.Button(
            action_row_three, text=self.tr("Copy source URL"), command=self.copy_source
        )
        self.copy_source_button.pack(side="left")
        self.copy_path_button = ttk.Button(
            action_row_three, text=self.tr("Copy local path"), command=self.copy_path
        )
        self.copy_path_button.pack(side="left", padx=8)

    @staticmethod
    def _detail_field(
        parent: ttk.Frame,
        row: int,
        key: str,
        value: str,
        *,
        wrap: int | None = None,
    ) -> ttk.Label:
        ttk.Label(parent, text=key, style="DetailKey.TLabel").grid(
            row=row, column=0, sticky="nw", padx=(0, 10), pady=5
        )
        label = ttk.Label(
            parent, text=value, style="DetailValue.TLabel", wraplength=wrap or 0, justify="left"
        )
        label.grid(row=row, column=1, sticky="ew", pady=5)
        return label

    def refresh_receipts(self, select_id: int | None = None) -> None:
        filter_name = self.filter_codes.get(self.filter_var.get(), "all")
        receipts = sort_receipts(
            self.repository.list(self.search_var.get(), filter_name),
            self.sort_codes.get(self.sort_var.get(), "newest"),
        )
        self.receipts = {receipt.id: receipt for receipt in receipts}
        current = select_id or self.selected_id
        self.tree.delete(*self.tree.get_children())
        for receipt in receipts:
            if not receipt.is_current:
                tags = ("replaced",)
            elif receipt.is_missing:
                tags = ("missing",)
            elif receipt.is_duplicate:
                tags = ("duplicate",)
            elif not receipt.source_domain:
                tags = ("no_source",)
            else:
                tags = ()
            self.tree.insert(
                "",
                "end",
                iid=str(receipt.id),
                text=receipt.file_name,
                values=(
                    receipt.source_domain or self.tr("Unknown"),
                    format_timestamp(receipt.first_seen_at),
                    format_bytes(receipt.file_size),
                    receipt.note,
                ),
                tags=tags,
            )
        stats = self.repository.stats()
        if self.language == "zh_CN":
            summary = (
                f"{stats['total']} 条收据  |  {stats['active']} 个当前文件  |  "
                f"{stats['missing']} 个丢失  |  {stats['replaced']} 个历史版本"
            )
        else:
            summary = (
                f"{stats['total']} receipts  |  {stats['active']} current  |  "
                f"{stats['missing']} missing  |  {stats['replaced']} replaced"
            )
        self.summary_var.set(summary)
        children = self.tree.get_children()
        if current is not None and str(current) in children:
            self.tree.selection_set(str(current))
            self.tree.focus(str(current))
            self.tree.see(str(current))
            self._show_receipt(self.receipts.get(current))
        elif receipts:
            first_id = str(receipts[0].id)
            self.tree.selection_set(first_id)
            self.tree.focus(first_id)
            self.selected_id = receipts[0].id
            self._show_receipt(receipts[0])
        else:
            self.selected_id = None
            self._show_receipt(None)

    def _queue_refresh(self, *_args: object) -> None:
        if self.search_timer:
            self.after_cancel(self.search_timer)
        self.search_timer = self.after(220, self.refresh_receipts)

    def _select_receipt(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        selection = self.tree.selection()
        if selection:
            self.selected_id = int(selection[0])
            self._show_receipt(self.receipts.get(self.selected_id))

    def _show_receipt(self, receipt: Receipt | None) -> None:
        if receipt is None:
            values = (self.tr("Select a receipt"), "-", self.tr("Not available"), "-", "-", "-", "-")
            note = ""
            can_open = can_relocate = can_open_source = False
            can_copy_path = can_copy_source = False
            can_organize = False
            disposition_label = self.tr("Inbox")
        else:
            source_url = safe_source_url(receipt.referrer_url or receipt.host_url)
            hash_text = receipt.sha256 or self.tr("Not calculated for files over 200 MB")
            if receipt.is_duplicate:
                hash_text += f"  ({self.tr('duplicate found')})"
            if not receipt.is_current:
                status = self.tr("Replaced")
            elif receipt.is_missing:
                status = self.tr("Missing")
            else:
                status = self.tr("Active")
            values = (
                receipt.file_name,
                status,
                receipt.source_domain or self.tr("Unknown"),
                format_timestamp(receipt.first_seen_at),
                receipt.path,
                source_url or self.tr("Not stored by the browser"),
                hash_text,
            )
            note = receipt.note
            can_open = receipt.is_current and not receipt.is_missing
            can_relocate = receipt.is_current and receipt.is_missing
            can_open_source = source_url is not None
            can_copy_path = True
            can_copy_source = source_url is not None
            can_organize = receipt.is_current
            disposition_label = self.disposition_labels.get(
                receipt.disposition, self.tr("Inbox")
            )

        fields = (
            self.detail_name,
            self.detail_status,
            self.detail_source,
            self.detail_time,
            self.detail_path,
            self.detail_url,
            self.detail_hash,
        )
        for label, value in zip(fields, values, strict=True):
            label.configure(text=value)
        self.note_text.delete("1.0", "end")
        self.note_text.insert("1.0", note)
        self.disposition_var.set(disposition_label)
        self.disposition_box.configure(state="readonly" if can_organize else "disabled")
        self.open_file_button.configure(state="normal" if can_open else "disabled")
        self.open_folder_button.configure(state="normal" if can_open else "disabled")
        self.relocate_button.configure(state="normal" if can_relocate else "disabled")
        self.open_source_button.configure(state="normal" if can_open_source else "disabled")
        self.copy_source_button.configure(state="normal" if can_copy_source else "disabled")
        self.copy_path_button.configure(state="normal" if can_copy_path else "disabled")

    def begin_scan(self, silent: bool = False) -> None:
        if self.scan_running:
            return
        if self.scan_timer:
            self.after_cancel(self.scan_timer)
            self.scan_timer = None
        folder = self.settings.watch_folder
        if not folder.is_dir():
            if not silent:
                messagebox.showerror(self.tr("Folder not found"), str(folder))
            self._schedule_scan()
            return
        self.scan_running = True
        self.scan_button.configure(state="disabled", text=self.tr("Scanning..."))
        self.status_var.set(f"{self.tr('Scanning...')} {folder}")
        threading.Thread(
            target=self._scan_worker,
            args=(folder, self.settings.recursive_scan),
            daemon=True,
        ).start()

    def _scan_worker(self, folder: Path, recursive: bool) -> None:
        try:
            self.events.put(("scan_done", self.scanner.scan_folder(folder, recursive=recursive)))
        except Exception as error:
            self.events.put(("scan_error", error))

    def add_file(self) -> None:
        selected = filedialog.askopenfilename(title=self.tr("Add file"))
        if not selected:
            return
        self.status_var.set(f"{self.tr('Add file')}: {Path(selected).name}")

        def worker() -> None:
            try:
                self.events.put(("file_done", self.scanner.scan_file(Path(selected))))
            except Exception as error:
                self.events.put(("file_error", error))

        threading.Thread(target=worker, daemon=True).start()

    def choose_folder(self) -> None:
        selected = filedialog.askdirectory(
            title=self.tr("Watch folder"), initialdir=self.settings.watch_folder
        )
        if selected:
            self.settings.watch_folder = Path(selected)
            self.settings_store.save(self.settings)
            self.folder_var.set(selected)
            self.status_var.set(self.tr("Watch folder updated"))
            self.begin_scan()

    def save_note(self) -> None:
        if self.selected_id is not None:
            self.repository.update_note(self.selected_id, self.note_text.get("1.0", "end"))
            self.status_var.set(self.tr("Note saved"))
            self.refresh_receipts(select_id=self.selected_id)

    def _change_disposition(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        receipt = self._selected_receipt()
        if not receipt or not receipt.is_current:
            return
        disposition = self.disposition_codes.get(self.disposition_var.get())
        if disposition is None:
            return
        self.repository.update_disposition(receipt.id, disposition)
        self.refresh_receipts(select_id=receipt.id)

    def open_file(self) -> None:
        receipt = self._selected_receipt()
        if not receipt or not receipt.is_current or receipt.is_missing:
            return
        path = Path(receipt.path)
        if not path.exists():
            messagebox.showerror(self.tr("File not found"), self.tr("Missing"))
            return
        os.startfile(path)  # type: ignore[attr-defined]

    def open_folder(self) -> None:
        receipt = self._selected_receipt()
        if not receipt or not receipt.is_current or receipt.is_missing:
            return
        path = Path(receipt.path)
        if not path.exists():
            messagebox.showerror(self.tr("File not found"), self.tr("Missing"))
            return
        subprocess.Popen(["explorer", "/select,", str(path)])

    def open_source(self) -> None:
        receipt = self._selected_receipt()
        if not receipt:
            return
        raw_url = receipt.referrer_url or receipt.host_url
        url = safe_source_url(raw_url)
        if not raw_url:
            messagebox.showinfo(self.tr("No source URL"), self.tr("Not stored by the browser"))
        elif not url:
            messagebox.showwarning(self.tr("Unsafe source URL"), str(raw_url))
        else:
            webbrowser.open(url)

    def _copy_text(self, value: str, status: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(value)
        self.update()
        self.status_var.set(status)

    def copy_source(self) -> None:
        receipt = self._selected_receipt()
        if not receipt:
            return
        raw_url = receipt.referrer_url or receipt.host_url
        url = safe_source_url(raw_url)
        if not raw_url:
            messagebox.showinfo(self.tr("No source URL"), self.tr("Not stored by the browser"))
        elif not url:
            messagebox.showwarning(self.tr("Unsafe source URL"), str(raw_url))
        else:
            self._copy_text(url, self.tr("Source URL copied"))

    def copy_path(self) -> None:
        receipt = self._selected_receipt()
        if receipt:
            self._copy_text(receipt.path, self.tr("Local path copied"))

    def relocate_file(self) -> None:
        receipt = self._selected_receipt()
        if not receipt or not receipt.is_current or not receipt.is_missing:
            return
        selected = filedialog.askopenfilename(
            title=self.tr("Relocate"), initialfile=receipt.file_name
        )
        if not selected:
            return
        try:
            receipt_id = self.scanner.relocate(receipt.id, Path(selected))
        except (OSError, ValueError) as error:
            messagebox.showerror(self.tr("Relocate"), str(error))
            return
        self.status_var.set(self.tr("Receipt saved"))
        self.refresh_receipts(select_id=receipt_id)

    def remove_receipt(self) -> None:
        receipt = self._selected_receipt()
        if not receipt:
            return
        prompt = (
            "从本地历史中删除这条收据？\n\n原文件不会被删除。"
            if self.language == "zh_CN"
            else "Remove this receipt from local history?\n\nThe file itself will not be deleted."
        )
        if messagebox.askyesno(self.tr("Remove receipt"), prompt):
            self.repository.delete(receipt.id)
            self.selected_id = None
            self.refresh_receipts()

    def export_receipts(self) -> None:
        target = filedialog.asksaveasfilename(
            title=self.tr("Export receipts"),
            defaultextension=".csv",
            filetypes=(("CSV", "*.csv"), ("JSON", "*.json")),
            initialfile="download-receipts.csv",
        )
        if not target:
            return
        rows = [asdict(receipt) for receipt in self.repository.export_all()]
        path = Path(target)
        if path.suffix.lower() == ".json":
            path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            with path.open("w", encoding="utf-8-sig", newline="") as output:
                if rows:
                    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
                    writer.writeheader()
                    writer.writerows(rows)
        self.status_var.set(f"{self.tr('Export complete')}: {path}")

    def show_settings(self) -> None:
        window = tk.Toplevel(self)
        window.title(self.tr("Settings"))
        window.transient(self)
        window.resizable(False, False)
        frame = ttk.Frame(window, padding=20)
        frame.pack(fill="both", expand=True)

        automatic = tk.BooleanVar(value=self.settings.automatic_scan)
        recursive = tk.BooleanVar(value=self.settings.recursive_scan)
        tray = tk.BooleanVar(value=self.settings.minimize_to_tray)
        startup = tk.BooleanVar(value=self.settings.start_with_windows)
        interval = tk.IntVar(value=self.settings.scan_interval_seconds)
        language_labels = {
            self.tr("Automatic"): "auto",
            self.tr("English"): "en",
            self.tr("Simplified Chinese"): "zh_CN",
        }
        current_language = next(
            (label for label, value in language_labels.items() if value == self.settings.language),
            self.tr("Automatic"),
        )
        language = tk.StringVar(value=current_language)

        ttk.Checkbutton(frame, text=self.tr("Scan automatically"), variable=automatic).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=4
        )
        ttk.Checkbutton(frame, text=self.tr("Include subfolders"), variable=recursive).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=4
        )
        ttk.Checkbutton(
            frame, text=self.tr("Minimize to system tray when closing"), variable=tray
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=4)
        ttk.Checkbutton(frame, text=self.tr("Start with Windows"), variable=startup).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=4
        )
        ttk.Label(frame, text=self.tr("Scan interval (seconds)")).grid(
            row=4, column=0, sticky="w", pady=(12, 4)
        )
        ttk.Spinbox(frame, from_=10, to=3600, textvariable=interval, width=10).grid(
            row=4, column=1, sticky="e", pady=(12, 4)
        )
        ttk.Label(frame, text=self.tr("Language")).grid(row=5, column=0, sticky="w", pady=4)
        ttk.Combobox(
            frame,
            values=list(language_labels),
            textvariable=language,
            state="readonly",
            width=20,
        ).grid(row=5, column=1, sticky="e", pady=4)

        buttons = ttk.Frame(frame)
        buttons.grid(row=6, column=0, columnspan=2, sticky="e", pady=(18, 0))
        ttk.Button(buttons, text=self.tr("Cancel"), command=window.destroy).pack(side="left")

        def save() -> None:
            previous_language = self.settings.language
            self.settings.automatic_scan = automatic.get()
            self.settings.recursive_scan = recursive.get()
            self.settings.minimize_to_tray = tray.get()
            self.settings.start_with_windows = startup.get()
            self.settings.scan_interval_seconds = max(10, int(interval.get()))
            self.settings.language = language_labels[language.get()]
            try:
                set_startup_enabled(self.settings.start_with_windows)
            except OSError as error:
                messagebox.showerror(self.tr("Settings"), str(error), parent=window)
                return
            self.settings_store.save(self.settings)
            self._schedule_scan()
            window.destroy()
            self.status_var.set(self.tr("Settings saved"))
            if previous_language != self.settings.language:
                messagebox.showinfo(self.tr("Restart required"), self.tr("Restart required"))

        ttk.Button(buttons, text=self.tr("Save"), style="Accent.TButton", command=save).pack(
            side="left", padx=(8, 0)
        )
        window.grab_set()

    def show_welcome(self) -> None:
        window = tk.Toplevel(self)
        window.title(self.tr("Welcome to Download Receipt"))
        window.transient(self)
        window.resizable(False, False)
        frame = ttk.Frame(window, padding=24)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame, text=self.tr("Welcome to Download Receipt"), style="PanelTitle.TLabel"
        ).pack(anchor="w")
        ttk.Label(
            frame,
            text=self.tr("Your Downloads folder will be scanned locally. No data is uploaded."),
            wraplength=420,
        ).pack(anchor="w", pady=(12, 4))
        ttk.Label(
            frame,
            text=self.tr("You can change the folder and scan options at any time in Settings."),
            wraplength=420,
        ).pack(anchor="w")
        ttk.Label(frame, text=str(self.settings.watch_folder), style="Muted.TLabel").pack(
            anchor="w", pady=(12, 18)
        )

        def finish() -> None:
            self.settings_store.save(self.settings)
            window.destroy()

        ttk.Button(
            frame, text=self.tr("Get started"), style="Accent.TButton", command=finish
        ).pack(anchor="e")
        window.protocol("WM_DELETE_WINDOW", finish)
        window.grab_set()

    def _selected_receipt(self) -> Receipt | None:
        return self.repository.get(self.selected_id) if self.selected_id is not None else None

    def _poll_events(self) -> None:
        try:
            while True:
                event_name, payload = self.events.get_nowait()
                if event_name == "scan_done":
                    result = payload
                    assert isinstance(result, ScanResult)
                    self.scan_running = False
                    self.scan_button.configure(state="normal", text=self.tr("Scan now"))
                    if self.language == "zh_CN":
                        status = (
                            f"扫描完成：检查 {result.scanned}，新增 {result.added}，"
                            f"刷新 {result.updated}，失败 {result.failed}"
                        )
                    else:
                        status = (
                            f"Scan complete: {result.scanned} checked, {result.added} new, "
                            f"{result.updated} refreshed, {result.failed} failed"
                        )
                    self.status_var.set(status)
                    self.refresh_receipts()
                    self._schedule_scan()
                elif event_name == "scan_error":
                    self.scan_running = False
                    self.scan_button.configure(state="normal", text=self.tr("Scan now"))
                    self.status_var.set(self.tr("Scan failed"))
                    messagebox.showerror(self.tr("Scan failed"), str(payload))
                    self._schedule_scan()
                elif event_name == "file_done":
                    self.status_var.set(self.tr("Receipt saved"))
                    self.refresh_receipts(select_id=int(payload))
                elif event_name == "file_error":
                    self.status_var.set(self.tr("Could not read file"))
                    messagebox.showerror(self.tr("Could not read file"), str(payload))
        except queue.Empty:
            pass
        if not self.exiting:
            self.after(100, self._poll_events)

    def _schedule_scan(self) -> None:
        if self.scan_timer:
            self.after_cancel(self.scan_timer)
            self.scan_timer = None
        if self.settings.automatic_scan:
            milliseconds = self.settings.scan_interval_seconds * 1000
            self.scan_timer = self.after(milliseconds, lambda: self.begin_scan(silent=True))

    def _start_tray(self) -> None:
        if TrayController is None:
            return
        try:
            self.tray = TrayController(
                show=lambda: self.after(0, self._show_window),
                scan=lambda: self.after(0, self.begin_scan),
                quit_app=lambda: self.after(0, self._quit),
                labels=(
                    self.tr("Show Download Receipt"),
                    self.tr("Scan now"),
                    self.tr("Quit Download Receipt"),
                ),
            )
            self.tray.start()
        except Exception:
            self.tray = None

    def _show_window(self) -> None:
        self.deiconify()
        self.state("normal")
        self.lift()
        self.focus_force()

    def _hide_window(self) -> None:
        if self.tray is not None:
            self.withdraw()
        else:
            self.iconify()

    def _request_close(self) -> None:
        if self.settings.minimize_to_tray and self.tray is not None:
            self._hide_window()
        else:
            self._quit()

    def show_about(self) -> None:
        text = (
            f"Download Receipt {__version__}\n\n"
            + (
                "本地、开源的 Windows 下载历史工具。\n不会上传任何文件数据。"
                if self.language == "zh_CN"
                else "A local, open-source history for Windows downloads.\nNo file data is uploaded."
            )
        )
        messagebox.showinfo(self.tr("About"), text)

    def _quit(self) -> None:
        if self.exiting:
            return
        self.exiting = True
        self.settings_store.save(self.settings)
        if self.tray is not None:
            self.tray.stop()
        self.destroy()


def run(*, start_minimized: bool = False) -> None:
    app = ReceiptApp(start_minimized=start_minimized)
    app.mainloop()
