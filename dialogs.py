"""
dialogs.py — ArgsReferenceDialog, ArgValuePopup, SettingsDialog.
"""

import tkinter as tk
from tkinter import ttk, filedialog
from datetime import datetime
import threading

import theme as th
from scanner import (
    probe_tool, build_args_db, load_args_db, save_args_db,
    IMAGE_FORMATS, VIDEO_FORMATS, AUDIO_FORMATS,
)
from persistence import save_prefs


# ── Arg value popup ───────────────────────────────────────────────────────────

class ArgValuePopup(tk.Toplevel):
    """
    Small transient popup that appears near the clicked arg row.
    Shows the flag, its argument hint, and a text entry for the value.
    On confirm: appends  "-flag [value]"  to parent.extra_args widget.
    """

    def __init__(self, parent_dialog, entry_data, click_x, click_y):
        super().__init__(parent_dialog)
        self.pd        = parent_dialog          # ArgsReferenceDialog
        self.app       = parent_dialog.parent   # ConverterApp
        self.entry_data = entry_data
        self.overrideredirect(True)             # borderless
        self.configure(bg=th.BORDER)

        self._build()
        self.update_idletasks()

        # Position near the click, nudged so it doesn't clip screen edge
        w, h = self.winfo_width(), self.winfo_height()
        sw   = self.winfo_screenwidth()
        sh   = self.winfo_screenheight()
        x    = min(click_x + 12, sw - w - 8)
        y    = min(click_y - 10, sh - h - 8)
        self.geometry(f"+{x}+{y}")

        self.val_entry.focus_set()
        self.val_entry.select_range(0, "end")

        # Dismiss on click outside
        self.bind("<FocusOut>", self._on_focus_out)

    def _build(self):
        flag     = self.entry_data["flag"]
        arg_hint = self.entry_data.get("args", "")
        desc     = self.entry_data.get("desc", "")
        needs_val = bool(arg_hint)

        outer = tk.Frame(self, bg=th.PANEL, padx=14, pady=10)
        outer.pack(fill="both", expand=True, padx=1, pady=1)

        # Flag + hint header
        hdr = tk.Frame(outer, bg=th.PANEL)
        hdr.pack(fill="x")
        tk.Label(hdr, text=flag, font=th.FONT_BOLD,
                 bg=th.PANEL, fg=th.ACCENT).pack(side="left")
        if arg_hint:
            tk.Label(hdr, text=f"  {arg_hint}", font=th.FONT_LABEL,
                     bg=th.PANEL, fg=th.FG_DIM).pack(side="left")

        # Description (truncated)
        short_desc = desc[:72] + "…" if len(desc) > 72 else desc
        tk.Label(outer, text=short_desc, font=th.FONT_SMALL,
                 bg=th.PANEL, fg=th.FG_DIM, wraplength=320,
                 justify="left").pack(anchor="w", pady=(2, 8))

        th.sep(outer, bg=th.BORDER).pack(fill="x", pady=(0, 8))

        if needs_val:
            # Value entry row
            val_row = tk.Frame(outer, bg=th.PANEL)
            val_row.pack(fill="x")
            tk.Label(val_row, text="value:", font=th.FONT_LABEL,
                     bg=th.PANEL, fg=th.MUTED).pack(side="left")
            self.val_var = tk.StringVar()
            self.val_entry = th.entry(val_row, self.val_var, width=18)
            self.val_entry.pack(side="left", padx=(6, 8))
            self.val_entry.bind("<Return>", self._confirm)
            self.val_entry.bind("<Escape>", lambda _: self.destroy())
        else:
            # Boolean flag — no value needed, just confirm
            self.val_var   = None
            self.val_entry = tk.Frame(outer)  # dummy so _confirm works

        btn_row = tk.Frame(outer, bg=th.PANEL)
        btn_row.pack(fill="x", pady=(8, 0))

        label = "add  →" if needs_val else f"add  {flag}"
        th.button(btn_row, label, self._confirm,
                  style="primary", padx=10, pady=4).pack(side="left")
        th.button(btn_row, "cancel", self.destroy,
                  style="ghost", padx=8, pady=4).pack(side="left", padx=(6, 0))

        if needs_val:
            hint_txt = f"Enter: confirm  ·  Esc: cancel"
            tk.Label(btn_row, text=hint_txt, font=th.FONT_SMALL,
                     bg=th.PANEL, fg=th.MUTED).pack(side="right")

    def _confirm(self, _=None):
        flag  = self.entry_data["flag"]
        value = self.val_var.get().strip() if self.val_var else ""

        token = flag if not value else f"{flag} {value}"

        current = self.app.extra_args_text.get("1.0", "end").strip()
        # Avoid exact duplicate flag entries
        existing_flags = [t for t in current.split() if t.startswith("-")]
        if flag not in existing_flags:
            sep = " " if current and not current.endswith("\n") else ""
            self.app.extra_args_text.configure(state="normal")
            self.app.extra_args_text.insert("end", sep + token)
            self.app.extra_args_text.configure(state="normal")

        self.destroy()

    def _on_focus_out(self, event):
        # Delay slightly so button clicks inside still register
        self.after(100, lambda: self.destroy() if self.winfo_exists() else None)


# ── Args reference dialog ─────────────────────────────────────────────────────

class ArgsReferenceDialog(tk.Toplevel):
    """
    Searchable args reference for the current output format.
    Click a row → ArgValuePopup to insert flag (+ value) into extra args.
    """

    def __init__(self, parent, fmt):
        super().__init__(parent)
        self.parent = parent
        self.fmt    = fmt
        self.title(f"Args Reference — {fmt.upper()}")
        self.geometry("860x620")
        self.minsize(600, 400)
        self.configure(bg=th.BG)

        self.db          = load_args_db()
        self._all_entries = {}   # tool_name → [(row, flag_lbl, desc_lbl, entry)]
        self._tabs        = {}

        self._build()
        th.center_window(self, parent)

    # ── Build ──────────────────────────────────────────────────────────────

    def _build(self):
        fmt = self.fmt

        # Header
        hdr = tk.Frame(self, bg=th.BG, pady=14)
        hdr.pack(fill="x", padx=20)
        tk.Label(hdr, text="ARGS REFERENCE", font=th.FONT_BIG,
                 bg=th.BG, fg=th.ACCENT).pack(side="left")
        engine = "ImageMagick" if fmt in IMAGE_FORMATS else "FFmpeg"
        tk.Label(hdr, text=f"  {fmt}  ·  {engine}",
                 font=th.FONT_LABEL, bg=th.BG, fg=th.FG_DIM).pack(side="left")

        # Search bar
        sf = tk.Frame(self, bg=th.PANEL,
                      highlightthickness=1, highlightbackground=th.BORDER,
                      pady=8, padx=12)
        sf.pack(fill="x", padx=20, pady=(0, 8))
        tk.Label(sf, text="search:", font=th.FONT_LABEL,
                 bg=th.PANEL, fg=th.MUTED).pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search)
        th.entry(sf, self.search_var, width=30).pack(side="left", padx=(8, 0))
        th.button(sf, "✕", lambda: self.search_var.set(""),
                  style="ghost", padx=6, pady=2).pack(side="left", padx=(4, 0))
        self.count_lbl = tk.Label(sf, text="", font=th.FONT_LABEL,
                                  bg=th.PANEL, fg=th.FG_DIM)
        self.count_lbl.pack(side="right")

        th.sep(self).pack(fill="x", padx=20)

        # Notebook
        self.nb = ttk.Notebook(self, style="Dark.TNotebook")
        self.nb.pack(fill="both", expand=True, padx=20, pady=8)

        no_db = not self.db or ("im" not in self.db and "ff" not in self.db)
        if no_db:
            self._no_db_tab(); return

        show_im = fmt in IMAGE_FORMATS and "im" in self.db
        show_ff = (not show_im and "ff" in self.db) \
               or (fmt in IMAGE_FORMATS and "im" not in self.db and "ff" in self.db) \
               or fmt in VIDEO_FORMATS or fmt in AUDIO_FORMATS

        if show_im: self._build_tab("ImageMagick", self.db.get("im", {}))
        if show_ff: self._build_tab("FFmpeg",       self.db.get("ff", {}))
        if not self._tabs: self._no_db_tab()

    def _build_tab(self, tool_name, tool_db):
        frame = tk.Frame(self.nb, bg=th.BG)
        self.nb.add(frame, text=f"  {tool_name}  ")
        self._tabs[tool_name]       = frame
        self._all_entries[tool_name] = []

        _, inner = th.scrolled_canvas(frame)

        fmt_args = tool_db.get("formats", {}).get(self.fmt, [])
        if fmt_args:
            th.section_header(inner, f"{self.fmt.upper()}-SPECIFIC  ({len(fmt_args)})")
            for e in fmt_args:
                self._all_entries[tool_name].append(self._arg_row(inner, e))

        general = tool_db.get("general", [])
        if general:
            th.section_header(inner, f"GENERAL  ({len(general)})")
            for e in general:
                self._all_entries[tool_name].append(self._arg_row(inner, e))

        if not fmt_args and not general:
            tk.Label(inner, text="No data — run Rebuild in Settings.",
                     font=th.FONT_LABEL, bg=th.BG, fg=th.MUTED,
                     pady=24).pack(anchor="w", padx=20)

    def _arg_row(self, parent, entry):
        flag_str = entry["flag"]
        if entry.get("args"):
            flag_str += f"  {entry['args']}"

        row = tk.Frame(parent, bg=th.PANEL,
                       highlightthickness=0, pady=5, padx=12, cursor="hand2")
        row.pack(fill="x", padx=16, pady=1)

        flag_lbl = tk.Label(row, text=flag_str, font=th.FONT_BOLD,
                            bg=th.PANEL, fg=th.ACCENT, anchor="w",
                            width=28, cursor="hand2")
        flag_lbl.pack(side="left")

        desc_lbl = tk.Label(row, text=entry.get("desc", ""),
                            font=th.FONT_LABEL, bg=th.PANEL, fg=th.FG,
                            anchor="w", justify="left", wraplength=500,
                            cursor="hand2")
        desc_lbl.pack(side="left", fill="x", expand=True)

        flash = tk.Label(row, text="", font=th.FONT_LABEL,
                         bg=th.PANEL, fg=th.SUCCESS, width=8)
        flash.pack(side="right")

        def _click(e):
            self._open_value_popup(entry, e.x_root, e.y_root, flash)

        def _hover_in(_=None):
            for w in (row, flag_lbl, desc_lbl):
                w.configure(bg=th.PANEL_HV)

        def _hover_out(_=None):
            for w in (row, flag_lbl, desc_lbl):
                w.configure(bg=th.PANEL)

        for w in (row, flag_lbl, desc_lbl):
            w.bind("<Button-1>", _click)
            w.bind("<Enter>",    _hover_in)
            w.bind("<Leave>",    _hover_out)

        return (row, flag_lbl, desc_lbl, entry)

    def _open_value_popup(self, entry, x, y, flash_lbl):
        popup = ArgValuePopup(self, entry, x, y)
        # Flash confirmation after popup closes
        def _watch():
            self.after(200, _check)
        def _check():
            if not popup.winfo_exists():
                flash_lbl.configure(text="+ added")
                self.after(1000, lambda: flash_lbl.configure(text=""))
        _watch()

    def _no_db_tab(self):
        frame = tk.Frame(self.nb, bg=th.BG)
        self.nb.add(frame, text="  No data  ")
        tk.Label(frame,
                 text="No args reference data found.\n\n"
                      "Open  ⚙ Settings  →  Rebuild Args Reference.",
                 font=th.FONT_LABEL, bg=th.BG, fg=th.FG_DIM,
                 justify="left", pady=40).pack(expand=True)

    def _on_search(self, *_):
        query   = self.search_var.get().strip().lower()
        total   = visible = 0
        for entries in self._all_entries.values():
            for (row, _, __, entry) in entries:
                total += 1
                match = (not query) or any(
                    query in (entry.get(k) or "").lower()
                    for k in ("flag", "desc", "args"))
                if match:
                    row.pack(fill="x", padx=16, pady=1); visible += 1
                else:
                    row.pack_forget()
        self.count_lbl.configure(
            text=f"{visible} / {total} shown" if query else "")


# ── Settings dialog ───────────────────────────────────────────────────────────

class SettingsDialog(tk.Toplevel):

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Settings — Tool Paths")
        self.resizable(False, False)
        self.configure(bg=th.BG)
        self.grab_set()
        self._build()
        th.center_window(self, parent)

    def _build(self):
        p = self.parent
        tk.Label(self, text="SETTINGS", font=th.FONT_BIG,
                 bg=th.BG, fg=th.ACCENT).pack(anchor="w", padx=24, pady=(20, 4))
        th.sep(self).pack(fill="x", padx=24, pady=(0, 12))

        self._tool_row("IMAGEMAGICK EXECUTABLE",
                       "e.g.  magick   or   C:\\Program Files\\ImageMagick\\magick.exe",
                       "im_exe_var", "im_exe", "magick")
        self._tool_row("FFMPEG EXECUTABLE",
                       "e.g.  ffmpeg   or   C:\\tools\\ffmpeg\\bin\\ffmpeg.exe",
                       "ff_exe_var", "ff_exe", "ffmpeg")

        self._rebuild_panel()

        th.sep(self).pack(fill="x", padx=24, pady=(4, 0))

        footer = tk.Frame(self, bg=th.BG)
        footer.pack(fill="x", padx=24, pady=16)
        th.button(footer, "✓  SAVE & CLOSE", self._save,
                  style="primary", padx=16, pady=8).pack(side="left")
        th.button(footer, "cancel", self.destroy,
                  style="normal", padx=14, pady=8).pack(side="left", padx=(8, 0))

    def _tool_row(self, label, hint, attr, saved_key, default):
        p     = self.parent
        frame = th.panel(self)
        frame.pack(fill="x", padx=24, pady=(0, 10))

        tk.Label(frame, text=label, font=th.FONT_LABEL,
                 bg=th.PANEL, fg=th.MUTED).pack(anchor="w")
        tk.Label(frame, text=hint, font=th.FONT_SMALL,
                 bg=th.PANEL, fg=th.MUTED).pack(anchor="w")

        row = tk.Frame(frame, bg=th.PANEL)
        row.pack(fill="x", pady=(6, 0))

        var = tk.StringVar(value=p.prefs.get(saved_key, default))
        setattr(self, attr, var)

        th.entry(row, var, width=42).pack(side="left", fill="x", expand=True)

        status = tk.Label(row, text="", font=th.FONT_LABEL,
                          bg=th.PANEL, fg=th.FG_DIM, width=14, anchor="w")
        status.pack(side="left", padx=(8, 0))

        def _probe(*_):
            ok, ver = probe_tool(var.get().strip())
            short   = ver[:36] + "…" if len(ver) > 36 else ver
            status.configure(text=f"✓ {short}" if ok else f"✗  {ver}",
                             fg=th.SUCCESS if ok else th.DANGER)

        def _browse():
            f = filedialog.askopenfilename(
                title=f"Locate {label}",
                filetypes=[("Executable", "*.exe *.cmd *.bat"), ("All files", "*")])
            if f:
                var.set(f); _probe()

        th.button(row, "browse", _browse, style="ghost",
                  padx=10, pady=4).pack(side="left", padx=(6, 0))
        th.button(row, "test", _probe, style="ghost",
                  padx=8, pady=4).pack(side="left", padx=(4, 0))
        self.after(80, _probe)

    def _rebuild_panel(self):
        frame = th.panel(self)
        frame.pack(fill="x", padx=24, pady=(0, 10))

        top = tk.Frame(frame, bg=th.PANEL)
        top.pack(fill="x")
        tk.Label(top, text="ARGS REFERENCE DATABASE", font=th.FONT_LABEL,
                 bg=th.PANEL, fg=th.MUTED).pack(side="left")

        db         = load_args_db()
        raw_ts     = db.get("scanned_at", "never")
        scanned_at = raw_ts
        if raw_ts != "never":
            try:
                scanned_at = datetime.fromisoformat(raw_ts).strftime("%d %b %Y  %H:%M")
            except Exception:
                pass
        self.scan_lbl = tk.Label(top, text=f"last built: {scanned_at}",
                                 font=th.FONT_LABEL, bg=th.PANEL, fg=th.FG_DIM)
        self.scan_lbl.pack(side="right")

        tk.Label(frame,
                 text="Scans installed tools and saves all args to  ~/.converter_args.json",
                 font=th.FONT_SMALL, bg=th.PANEL, fg=th.MUTED,
                 justify="left").pack(anchor="w", pady=(2, 8))

        btn_row = tk.Frame(frame, bg=th.PANEL)
        btn_row.pack(anchor="w")
        self.rebuild_btn = th.button(btn_row, "⟳  Rebuild Args Reference",
                                     self._rebuild, padx=12, pady=6)
        self.rebuild_btn.pack(side="left")
        self.rebuild_lbl = tk.Label(btn_row, text="", font=th.FONT_LABEL,
                                    bg=th.PANEL, fg=th.FG_DIM, padx=12)
        self.rebuild_lbl.pack(side="left")

    def _rebuild(self):
        im_exe = self.im_exe_var.get().strip() or "magick"
        ff_exe = self.ff_exe_var.get().strip() or "ffmpeg"
        self.rebuild_btn.configure(state="disabled")
        self.rebuild_lbl.configure(text="scanning…", fg=th.ACCENT)

        def _do():
            def _cb(msg):
                self.after(0, lambda m=msg: self.rebuild_lbl.configure(text=m))
            db = build_args_db(im_exe, ff_exe, progress_cb=_cb)
            save_args_db(db)
            ts = datetime.now().strftime("%d %b %Y  %H:%M")
            im_n = len(db.get("im", {}).get("general", []))
            ff_n = len(db.get("ff", {}).get("general", []))
            def _done():
                self.rebuild_btn.configure(state="normal")
                self.rebuild_lbl.configure(
                    text=f"✓  {im_n} IM  ·  {ff_n} FF general args", fg=th.SUCCESS)
                self.scan_lbl.configure(text=f"last built: {ts}")
            self.after(0, _done)

        threading.Thread(target=_do, daemon=True).start()

    def _save(self):
        p = self.parent
        p.prefs["im_exe"] = self.im_exe_var.get().strip() or "magick"
        p.prefs["ff_exe"] = self.ff_exe_var.get().strip() or "ffmpeg"
        p._check_tools()
        save_prefs(p.prefs)
        self.destroy()
