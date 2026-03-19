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
        # ── Header ──
        hdr = tk.Frame(self, bg=th.BG, pady=14)
        hdr.pack(fill="x", padx=24)
        tk.Label(hdr, text="BATCH CONVERTER", font=th.FONT_BIG,
                 bg=th.BG, fg=th.ACCENT).pack(side="left")
        th.button(hdr, "⚙  settings", self._open_settings,
                  style="normal", padx=10, pady=5).pack(side="right")
        self.tool_status = tk.Label(hdr, text="", font=th.FONT_LABEL,
                                    bg=th.BG, fg=th.FG_DIM)
        self.tool_status.pack(side="right", padx=(0, 16))
        th.sep(self).pack(fill="x", padx=24)

        # ── Top row: three columns ──
        top = tk.Frame(self, bg=th.BG)
        top.pack(fill="both", expand=True, padx=24, pady=(14, 0))

        # Col 1 — folders
        c1 = tk.Frame(top, bg=th.BG)
        c1.pack(side="left", fill="both", expand=True, padx=(0, 12))
        self._folder_row(c1, "INPUT FOLDER",  "input_path",  self._browse_input)
        self._folder_row(c1, "OUTPUT FOLDER", "output_path", self._browse_output)

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
        self.fmt_combo.bind("<<ComboboxSelected>>", self._on_format_change)
        self.fmt_badge = tk.Label(fmt_inner, text="🖼 image", font=th.FONT_LABEL,
                                  bg=th.PANEL, fg=th.FG_DIM, padx=8)
        self.fmt_badge.pack(side="left")

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
        th.button(args_hdr, "?", self._open_args_reference,
                  bg=th.BORDER, fg=th.ACCENT, padx=6, pady=1).pack(side="right")

        # Multiline text widget for extra args (3 rows default)
        self.extra_args_text = tk.Text(
            args_panel, font=th.FONT_MONO,
            bg=th.BG, fg=th.FG, insertbackground=th.ACCENT,
            relief="flat", highlightthickness=1,
            highlightbackground=th.BORDER,
            height=3, wrap="word",
            padx=4, pady=4)
        self.extra_args_text.pack(fill="both", expand=True, pady=(6, 0))

        prog_frame = tk.Frame(c3, bg=th.BG)
        prog_frame.pack(fill="x")
        self.progress = ttk.Progressbar(prog_frame, mode="determinate")
        self.progress.pack(fill="x", pady=(0, 8))
        btn_row = tk.Frame(prog_frame, bg=th.BG)
        btn_row.pack(fill="x")
        self.run_btn = th.button(btn_row, "▶  CONVERT",
                                 self._start_conversion, style="primary")
        self.run_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.cancel_btn = th.button(btn_row, "✕  CANCEL", self._cancel)
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
        th.button(log_bar, "clear", self._clear_log,
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
        if v := self.prefs.get("output_path"): self.output_path_var.set(v)
        if v := self.prefs.get("format"):
            self.format_var.set(v)
            self._on_format_change()
        if v := self.prefs.get("extra_args"):
            self.extra_args_text.configure(state="normal")
            self.extra_args_text.insert("1.0", v)

    def _save_session(self):
        self.prefs.update({
            "input_path":  self.input_path_var.get(),
            "output_path": self.output_path_var.get(),
            "format":      self.format_var.get(),
            "extra_args":  self.extra_args_text.get("1.0", "end").strip(),
        })
        save_prefs(self.prefs)

    def _on_close(self):
        self._save_session()
        self.destroy()

    # ── Browse / format ───────────────────────────────────────────────────

    def _browse_input(self):
        d = filedialog.askdirectory(title="Select input folder")
        if d:
            self.input_path_var.set(d)
            if not self.output_path_var.get():
                self.output_path_var.set(d)

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

    def _start_conversion(self):
        inp = self.input_path_var.get().strip()
        out = self.output_path_var.get().strip()
        fmt = self.format_var.get().strip().lower()
        if not inp or not out:
            messagebox.showerror("Missing paths",
                                 "Please set input and output folders.")
            return
        if not fmt:
            messagebox.showerror("No format", "Please select an output format.")
            return
        if not self.has_magick and not self.has_ffmpeg:
            messagebox.showerror("No tools found",
                "Neither ImageMagick nor FFmpeg could be found.\n\n"
                "Open ⚙ Settings and point to your installed executables.")
            return
        Path(out).mkdir(parents=True, exist_ok=True)
        self._save_session()
        self.running = True
        self.cancel_flag.clear()
        self.run_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        threading.Thread(target=self._run,
                         args=(inp, out, fmt), daemon=True).start()

    def _run(self, inp, out, fmt):
        files = self._collect_files(inp, self.recurse_var.get())
        if not files:
            self._log("No compatible files found.", "warn")
            self._done(); return

        self._log(f"Found {len(files)} file(s) → .{fmt}", "header")
        ok = skip = fail = 0
        self.after(0, lambda: self.progress.configure(
            maximum=len(files), value=0))

        for i, src in enumerate(files):
            if self.cancel_flag.is_set():
                self._log("Cancelled.", "warn"); break

            src_ext = src.suffix.lower().lstrip(".")

            if self.skip_same_var.get() and src_ext == fmt:
                self._log(f"skip  {src.name}  (already {fmt})", "dim")
                skip += 1
                self.after(0, lambda v=i+1: self.progress.configure(value=v))
                continue

            dst = Path(out) / (src.stem + f".{fmt}")
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
