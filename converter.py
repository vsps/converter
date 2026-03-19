"""
converter.py — Batch File Converter (main application).

Run with:  python converter.py

Modules:
    theme.py       — colours, fonts, ttk styles, widget factories
    persistence.py — prefs, format tables
    scanner.py     — tool probing, help parsing, args DB
    dialogs.py     — ArgsReferenceDialog, ArgValuePopup, SettingsDialog
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import subprocess
import threading
from pathlib import Path
from datetime import datetime

import theme as th
from persistence import (
    load_prefs, save_prefs, format_badge,
    IMAGE_FORMATS, VIDEO_FORMATS, AUDIO_FORMATS,
    ALL_FORMATS, ALL_EXTENSIONS, IMAGE_EXTENSIONS,
)
from scanner import probe_tool
from dialogs import ArgsReferenceDialog, SettingsDialog


class ConverterApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Batch File Converter")
        self.geometry("1060x600")
        self.minsize(900, 500)
        self.configure(bg=th.BG)

        self.prefs       = load_prefs()
        self.running     = False
        self.cancel_flag = threading.Event()

        th.apply_ttk_styles(self)
        self._build_ui()
        self._check_tools()
        self._restore_prefs()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Python 3.14 changed Tk.__getattr__ behaviour — capture a plain
        # reference to self so method lookups in callbacks bypass __getattr__.
        app = self

        # ── Header ──
        hdr = tk.Frame(self, bg=th.BG, pady=14)
        hdr.pack(fill="x", padx=24)
        tk.Label(hdr, text="BATCH CONVERTER", font=th.FONT_BIG,
                 bg=th.BG, fg=th.ACCENT).pack(side="left")
        th.button(hdr, "⚙  settings", lambda: app._open_settings(),
                  style="normal", padx=10, pady=5).pack(side="right")
        self.tool_status = tk.Label(hdr, text="", font=th.FONT_LABEL,
                                    bg=th.BG, fg=th.FG_DIM)
        self.tool_status.pack(side="right", padx=(0, 16))
        th.sep(self).pack(fill="x", padx=24)

        # ── Top row: three columns ──
        top = tk.Frame(self, bg=th.BG)
        top.pack(fill="both", expand=True, padx=24, pady=(14, 0))

        # Col 1 — input source + output folder
        c1 = tk.Frame(top, bg=th.BG)
        c1.pack(side="left", fill="both", expand=True, padx=(0, 12))
        self._build_input_panel(c1)
        self._folder_row(c1, "OUTPUT FOLDER", "output_path",
                         lambda: app._browse_output())

        # Col 2 — format + options
        c2 = tk.Frame(top, bg=th.BG)
        c2.pack(side="left", fill="both", expand=True, padx=(0, 12))

        fmt_panel = th.panel(c2)
        fmt_panel.pack(fill="both", expand=True, pady=(0, 8))
        tk.Label(fmt_panel, text="OUTPUT FORMAT", font=th.FONT_LABEL,
                 bg=th.PANEL, fg=th.MUTED).pack(anchor="w")
        fmt_inner = tk.Frame(fmt_panel, bg=th.PANEL)
        fmt_inner.pack(fill="x", pady=(6, 0))
        self.format_var = tk.StringVar(value="png")
        self.fmt_combo  = ttk.Combobox(fmt_inner, textvariable=self.format_var,
                                       values=ALL_FORMATS, state="readonly",
                                       font=th.FONT_UI, width=10)
        self.fmt_combo.pack(side="left")
        self.fmt_combo.bind("<<ComboboxSelected>>",
                            lambda e: app._on_format_change())
        self.fmt_badge = tk.Label(fmt_inner, text="🖼 image", font=th.FONT_LABEL,
                                  bg=th.PANEL, fg=th.FG_DIM, padx=8)
        self.fmt_badge.pack(side="left")

        # Quick-format preset buttons
        quick_row = tk.Frame(fmt_panel, bg=th.PANEL)
        quick_row.pack(anchor="w", pady=(10, 0))
        tk.Label(quick_row, text="quick:", font=th.FONT_SMALL,
                 bg=th.PANEL, fg=th.MUTED).pack(side="left", padx=(0, 6))

        PRESETS = [
            ("jpg", "jpg",  "-quality 85"),
            ("mp4", "mp4",  "-c:v libx264 -crf 23 -preset fast"),
            ("gif", "gif",  ""),
        ]
        for _lbl, _fmt, _args in PRESETS:
            def _make_preset(f=_fmt, a=_args):
                def _apply():
                    app.format_var.set(f)
                    app._on_format_change()
                    app.extra_args_text.delete("1.0", "end")
                    if a:
                        app.extra_args_text.insert("1.0", a)
                return _apply
            tk.Button(quick_row, text=_lbl,
                      font=th.FONT_SMALL, bg=th.BORDER, fg=th.FG,
                      activebackground=th.ACCENT, activeforeground=th.BG,
                      relief="flat", bd=0, padx=10, pady=3,
                      cursor="hand2", command=_make_preset()
                      ).pack(side="left", padx=(0, 4))

        opt_panel = th.panel(c2)
        opt_panel.pack(fill="both", expand=True, pady=(0, 8))
        tk.Label(opt_panel, text="OPTIONS", font=th.FONT_LABEL,
                 bg=th.PANEL, fg=th.MUTED).pack(anchor="w", pady=(0, 6))
        self.overwrite_var = tk.BooleanVar(value=True)
        th.checkbox(opt_panel, "Overwrite existing files",
                    self.overwrite_var).pack(anchor="w", pady=2)
        self.skip_same_var = tk.BooleanVar(value=True)
        th.checkbox(opt_panel, "Skip if source = target format",
                    self.skip_same_var).pack(anchor="w", pady=2)
        self.recurse_var = tk.BooleanVar(value=False)
        th.checkbox(opt_panel, "Include subfolders",
                    self.recurse_var).pack(anchor="w", pady=2)

        # Prefix / suffix filename fields
        th.sep(opt_panel, bg=th.BORDER).pack(fill="x", pady=(10, 8))
        ps_row = tk.Frame(opt_panel, bg=th.PANEL)
        ps_row.pack(fill="x")

        pre_col = tk.Frame(ps_row, bg=th.PANEL)
        pre_col.pack(side="left", fill="x", expand=True, padx=(0, 6))
        tk.Label(pre_col, text="PREFIX", font=th.FONT_SMALL,
                 bg=th.PANEL, fg=th.MUTED).pack(anchor="w")
        self.prefix_var = tk.StringVar()
        th.entry(pre_col, self.prefix_var).pack(fill="x", pady=(2, 0))

        suf_col = tk.Frame(ps_row, bg=th.PANEL)
        suf_col.pack(side="left", fill="x", expand=True)
        tk.Label(suf_col, text="SUFFIX", font=th.FONT_SMALL,
                 bg=th.PANEL, fg=th.MUTED).pack(anchor="w")
        self.suffix_var = tk.StringVar()
        th.entry(suf_col, self.suffix_var).pack(fill="x", pady=(2, 0))

        self.name_preview_var = tk.StringVar(value="")
        tk.Label(opt_panel, textvariable=self.name_preview_var,
                 font=th.FONT_SMALL, bg=th.PANEL, fg=th.FG_DIM,
                 anchor="w").pack(fill="x", pady=(4, 0))

        def _update_preview(*_):
            pre = app.prefix_var.get()
            suf = app.suffix_var.get()
            fmt = app.format_var.get() or "ext"
            app.name_preview_var.set(f"e.g.  {pre}filename{suf}.{fmt}")

        self.prefix_var.trace_add("write", _update_preview)
        self.suffix_var.trace_add("write", _update_preview)
        self.format_var.trace_add("write", _update_preview)
        _update_preview()

        # Col 3 — extra args + progress + buttons
        c3 = tk.Frame(top, bg=th.BG)
        c3.pack(side="left", fill="both", expand=True)

        args_panel = th.panel(c3)
        args_panel.pack(fill="both", expand=True, pady=(0, 8))
        args_hdr = tk.Frame(args_panel, bg=th.PANEL)
        args_hdr.pack(fill="x")
        tk.Label(args_hdr, text="EXTRA ARGS", font=th.FONT_LABEL,
                 bg=th.PANEL, fg=th.MUTED).pack(side="left")
        tk.Label(args_hdr, text="(passed to engine)", font=th.FONT_SMALL,
                 bg=th.PANEL, fg=th.MUTED).pack(side="left", padx=(4, 0))
        th.button(args_hdr, "?", lambda: app._open_args_reference(),
                  bg=th.BORDER, fg=th.ACCENT, padx=6, pady=1).pack(side="right")

        self.extra_args_text = tk.Text(
            args_panel, font=th.FONT_MONO,
            bg=th.BG, fg=th.FG, insertbackground=th.ACCENT,
            relief="flat", highlightthickness=1,
            highlightbackground=th.BORDER,
            height=3, wrap="word", padx=4, pady=4)
        self.extra_args_text.pack(fill="both", expand=True, pady=(6, 0))

        prog_frame = tk.Frame(c3, bg=th.BG)
        prog_frame.pack(fill="x")
        self.progress = ttk.Progressbar(prog_frame, mode="determinate")
        self.progress.pack(fill="x", pady=(0, 8))
        btn_row = tk.Frame(prog_frame, bg=th.BG)
        btn_row.pack(fill="x")
        self.run_btn = th.button(btn_row, "▶  CONVERT",
                                 lambda: app._start_conversion(),
                                 style="primary")
        self.run_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.cancel_btn = th.button(btn_row, "✕  CANCEL",
                                    lambda: app._cancel())
        self.cancel_btn.pack(side="left")
        self.cancel_btn.configure(state="disabled")
        self.status_var = tk.StringVar(value="ready")
        tk.Label(prog_frame, textvariable=self.status_var, font=th.FONT_LABEL,
                 bg=th.BG, fg=th.FG_DIM, anchor="w").pack(fill="x", pady=(6, 0))

        # ── Log strip ──
        th.sep(self).pack(fill="x", padx=24, pady=(12, 0))
        log_bar = tk.Frame(self, bg=th.BG)
        log_bar.pack(fill="x", padx=24, pady=(6, 0))
        tk.Label(log_bar, text="LOG", font=th.FONT_LABEL,
                 bg=th.BG, fg=th.MUTED).pack(side="left")
        self.summary_var = tk.StringVar(value="")
        tk.Label(log_bar, textvariable=self.summary_var, font=th.FONT_LABEL,
                 bg=th.BG, fg=th.FG_DIM).pack(side="left", padx=(12, 0))
        th.button(log_bar, "clear", lambda: app._clear_log(),
                  style="ghost", padx=6, pady=2).pack(side="right")

        log_wrap = tk.Frame(self, bg=th.PANEL,
                            highlightthickness=1, highlightbackground=th.BORDER)
        log_wrap.pack(fill="both", expand=True, padx=24, pady=(4, 12))
        self.log, _, _ = th.scrolled_text(log_wrap)
        self.log.tag_configure("ok",     foreground=th.SUCCESS)
        self.log.tag_configure("warn",   foreground=th.ACCENT)
        self.log.tag_configure("err",    foreground=th.DANGER)
        self.log.tag_configure("dim",    foreground=th.FG_DIM)
        self.log.tag_configure("header", foreground=th.ACCENT, font=th.FONT_BOLD)

    # ── Widget helpers ────────────────────────────────────────────────────

    def _build_input_panel(self, parent):
        """Build the INPUT SOURCE panel with folder/file radio rows."""
        app = self
        self.input_mode = tk.StringVar(value="folder")

        inp_panel = th.panel(parent)
        inp_panel.pack(fill="both", expand=True, pady=(0, 10))
        tk.Label(inp_panel, text="INPUT SOURCE", font=th.FONT_LABEL,
                 bg=th.PANEL, fg=th.MUTED).pack(anchor="w")

        # Each source row: indicator + label + browse + entry
        # Returns (StringVar, indicator_widget, entry_widget)
        def _source_row(mode, label_text, browse_cmd):
            row = tk.Frame(inp_panel, bg=th.PANEL)
            row.pack(fill="x", pady=(8, 0))

            ind = tk.Label(row, text="◉" if mode == "folder" else "○",
                           font=th.FONT_LABEL, bg=th.PANEL,
                           fg=th.ACCENT if mode == "folder" else th.MUTED,
                           cursor="hand2", width=2)
            ind.pack(side="left")

            lbl = tk.Label(row, text=label_text, font=th.FONT_LABEL,
                           bg=th.PANEL, fg=th.FG, cursor="hand2")
            lbl.pack(side="left")

            th.button(row, "browse", browse_cmd,
                      style="ghost", padx=8, pady=2).pack(side="right")

            var = tk.StringVar(value="")
            ent = th.entry(inp_panel, var)
            ent.pack(fill="x", pady=(3, 0))

            return var, ind, ent

        folder_var, folder_ind, folder_ent = _source_row(
            "folder", "FOLDER", lambda: app._browse_input_folder())
        file_var,   file_ind,   file_ent   = _source_row(
            "file",   "FILE",   lambda: app._browse_input_file())

        self.input_path_var = folder_var
        self.input_file_var = file_var

        def _refresh_input_ui(*_):
            active = self.input_mode.get()
            folder_ind.configure(
                text="◉" if active == "folder" else "○",
                fg=th.ACCENT if active == "folder" else th.MUTED)
            folder_ent.configure(
                highlightbackground=th.ACCENT if active == "folder" else th.BORDER)
            file_ind.configure(
                text="◉" if active == "file" else "○",
                fg=th.ACCENT if active == "file" else th.MUTED)
            file_ent.configure(
                highlightbackground=th.ACCENT if active == "file" else th.BORDER)

        self._refresh_input_ui = _refresh_input_ui

        def _select_folder(*_):
            self.input_mode.set("folder")
            _refresh_input_ui()

        def _select_file(*_):
            self.input_mode.set("file")
            _refresh_input_ui()

        # Bind click-to-activate on each row's widgets
        for w in (folder_ind, folder_ent):
            w.bind("<Button-1>", _select_folder)
        for w in (file_ind, file_ent):
            w.bind("<Button-1>", _select_file)

        _refresh_input_ui()  # set initial visual state

    def _folder_row(self, parent, label, attr, cmd):
        frame = th.panel(parent)
        frame.pack(fill="both", expand=True, pady=(0, 10))
        top = tk.Frame(frame, bg=th.PANEL)
        top.pack(fill="x")
        tk.Label(top, text=label, font=th.FONT_LABEL,
                 bg=th.PANEL, fg=th.MUTED).pack(side="left")
        th.button(top, "browse", cmd,
                  style="ghost", padx=8, pady=2).pack(side="right")
        var = tk.StringVar(value="")
        setattr(self, attr + "_var", var)
        th.entry(frame, var).pack(fill="x", pady=(6, 0))

    # ── Dialogs ───────────────────────────────────────────────────────────

    def _open_settings(self):
        SettingsDialog(self)

    def _open_args_reference(self):
        ArgsReferenceDialog(self, self.format_var.get())

    # ── Tool detection ────────────────────────────────────────────────────

    def _check_tools(self):
        im_exe = self.prefs.get("im_exe", "magick")
        ff_exe = self.prefs.get("ff_exe", "ffmpeg")

        im_ok, _ = probe_tool(im_exe)
        self.has_magick = im_ok
        self.im_exe     = im_exe if im_ok else None
        if not im_ok:
            ok, _ = probe_tool("convert")
            if ok:
                self.has_magick, self.im_exe = True, "convert"

        ff_ok, _       = probe_tool(ff_exe)
        self.has_ffmpeg = ff_ok
        self.ff_exe     = ff_exe if ff_ok else None

        self.tool_status.configure(
            text=f"IM {'✓' if self.has_magick else '✗'}  ·  "
                 f"FFmpeg {'✓' if self.has_ffmpeg else '✗'}")

    def _im_cmd(self): return self.im_exe or "magick"
    def _ff_cmd(self): return self.ff_exe or "ffmpeg"

    # ── Prefs ─────────────────────────────────────────────────────────────

    def _restore_prefs(self):
        if v := self.prefs.get("input_path"):  self.input_path_var.set(v)
        if v := self.prefs.get("input_file"):  self.input_file_var.set(v)
        if v := self.prefs.get("input_mode"):
            self.input_mode.set(v)
            self._refresh_input_ui()
        if v := self.prefs.get("output_path"): self.output_path_var.set(v)
        if v := self.prefs.get("format"):
            self.format_var.set(v)
            self._on_format_change()
        if v := self.prefs.get("prefix"):      self.prefix_var.set(v)
        if v := self.prefs.get("suffix"):      self.suffix_var.set(v)
        if v := self.prefs.get("extra_args"):
            self.extra_args_text.configure(state="normal")
            self.extra_args_text.insert("1.0", v)

    def _save_session(self):
        self.prefs.update({
            "input_path":  self.input_path_var.get(),
            "input_file":  self.input_file_var.get(),
            "input_mode":  self.input_mode.get(),
            "output_path": self.output_path_var.get(),
            "format":      self.format_var.get(),
            "prefix":      self.prefix_var.get(),
            "suffix":      self.suffix_var.get(),
            "extra_args":  self.extra_args_text.get("1.0", "end").strip(),
        })
        save_prefs(self.prefs)

    def _on_close(self):
        self._save_session()
        self.destroy()

    # ── Browse / format ───────────────────────────────────────────────────

    def _browse_input_folder(self):
        d = filedialog.askdirectory(title="Select input folder")
        if d:
            self.input_path_var.set(d)
            self.input_mode.set("folder")
            self._refresh_input_ui()
            if not self.output_path_var.get():
                self.output_path_var.set(d)

    def _browse_input_file(self):
        f = filedialog.askopenfilename(title="Select input file")
        if f:
            self.input_file_var.set(f)
            self.input_mode.set("file")
            self._refresh_input_ui()
            if not self.output_path_var.get():
                self.output_path_var.set(str(Path(f).parent))

    def _browse_output(self):
        d = filedialog.askdirectory(title="Select output folder")
        if d:
            self.output_path_var.set(d)

    def _on_format_change(self, *_):
        self.fmt_badge.configure(text=format_badge(self.format_var.get()))

    # ── Logging ───────────────────────────────────────────────────────────

    def _log(self, msg, tag=""):
        def _inner():
            self.log.configure(state="normal")
            self.log.insert("end",
                f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n", tag)
            self.log.see("end")
            self.log.configure(state="disabled")
        self.after(0, _inner)

    def _clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.summary_var.set("")

    # ── Conversion ────────────────────────────────────────────────────────

    def _extra_args(self):
        raw = self.extra_args_text.get("1.0", "end").strip()
        return raw.split() if raw else []

    def _collect_files(self, folder, recurse):
        folder = Path(folder)
        return sorted(p for p in folder.glob("**/*" if recurse else "*")
                      if p.is_file() and p.suffix.lower() in ALL_EXTENSIONS)

    def _output_name(self, src: Path, fmt: str) -> str:
        """Build output filename applying prefix and suffix."""
        pre = self.prefix_var.get()
        suf = self.suffix_var.get()
        return f"{pre}{src.stem}{suf}.{fmt}"

    def _run(self, inp: Path, out: str, fmt: str, mode: str):
        # Build file list
        if mode == "file":
            if inp.suffix.lower() not in ALL_EXTENSIONS:
                self._log(f"Unsupported file type: {inp.suffix}", "err")
                self._done(); return
            files = [inp]
        else:
            files = self._collect_files(inp, self.recurse_var.get())

        if not files:
            self._log("No compatible files found.", "warn")
            self._done(); return

        src_desc = inp.name if mode == "file" else str(inp)
        self._log(f"{'File' if mode == 'file' else 'Folder'}:  {src_desc}  "
                  f"→  {len(files)} file(s)  →  .{fmt}", "header")
        ok = skip = fail = 0
        self.after(0, lambda: self.progress.configure(
            maximum=len(files), value=0))

        for i, src in enumerate(files):
            if self.cancel_flag.is_set():
                self._log("Cancelled.", "warn"); break

            src_ext = src.suffix.lower().lstrip(".")

            if self.skip_same_var.get() and src_ext == fmt \
                    and not self.prefix_var.get() and not self.suffix_var.get():
                self._log(f"skip  {src.name}  (already {fmt})", "dim")
                skip += 1
                self.after(0, lambda v=i+1: self.progress.configure(value=v))
                continue

            dst = Path(out) / self._output_name(src, fmt)
            if not self.overwrite_var.get() and dst.exists():
                self._log(f"skip  {src.name}  (exists)", "dim")
                skip += 1
                self.after(0, lambda v=i+1: self.progress.configure(value=v))
                continue

            self.after(0, lambda n=src.name: self.status_var.set(
                f"converting {n}"))
            success, err = self._convert_file(src, dst, fmt)
            if success:
                self._log(f"✓  {src.name}  →  {dst.name}", "ok"); ok += 1
            else:
                self._log(f"✗  {src.name}  —  {err}", "err"); fail += 1
            self.after(0, lambda v=i+1: self.progress.configure(value=v))

        summary = f"{ok} converted  ·  {skip} skipped  ·  {fail} failed"
        self._log(f"Done.  {summary}", "header")
        self.after(0, lambda: self.summary_var.set(summary))
        self._done()
        mode = self.input_mode.get()
        inp  = (self.input_file_var.get() if mode == "file"
                else self.input_path_var.get()).strip()
        out  = self.output_path_var.get().strip()
        fmt  = self.format_var.get().strip().lower()

        if not inp:
            messagebox.showerror("Missing input",
                "Please select an input folder or file.")
            return
        if not out:
            messagebox.showerror("Missing output",
                "Please set an output folder.")
            return
        if not fmt:
            messagebox.showerror("No format", "Please select an output format.")
            return
        if not self.has_magick and not self.has_ffmpeg:
            messagebox.showerror("No tools found",
                "Neither ImageMagick nor FFmpeg could be found.\n\n"
                "Open ⚙ Settings and point to your installed executables.")
            return

        # Validate input exists
        inp_path = Path(inp)
        if not inp_path.exists():
            messagebox.showerror("Not found",
                f"Input does not exist:\n{inp}")
            return

        Path(out).mkdir(parents=True, exist_ok=True)
        self._save_session()
        self.running = True
        self.cancel_flag.clear()
        self.run_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        threading.Thread(target=self._run,
                         args=(inp_path, out, fmt, mode), daemon=True).start()

    def _convert_file(self, src, dst, fmt):
        src_ext = src.suffix.lower().lstrip(".")
        extra   = self._extra_args()
        use_im  = self.has_magick and (
            src_ext in IMAGE_FORMATS or fmt in IMAGE_FORMATS)
        try:
            if use_im:
                cmd = [self._im_cmd(), str(src)] + extra + [str(dst)]
            elif self.has_ffmpeg:
                cmd = [self._ff_cmd(), "-y", "-i", str(src)] + extra + [str(dst)]
            else:
                return False, "no suitable tool — check Settings"
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                lines = [l for l in
                         (r.stderr or r.stdout or "error").strip().splitlines()
                         if l.strip()]
                return False, lines[-1] if lines else "conversion failed"
            return True, None
        except subprocess.TimeoutExpired:
            return False, "timed out (>120s)"
        except Exception as e:
            return False, str(e)

    def _cancel(self):
        self.cancel_flag.set()
        self.cancel_btn.configure(state="disabled")

    def _done(self):
        self.running = False
        self.after(0, lambda: self.run_btn.configure(state="normal"))
        self.after(0, lambda: self.cancel_btn.configure(state="disabled"))
        self.after(0, lambda: self.status_var.set("done"))


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = ConverterApp()
    app.mainloop()
