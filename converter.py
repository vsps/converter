"""
converter.py — Batch File Converter TUI (Textual).

Run with:  python converter.py

Modules:
    converter.tcss — styling
    persistence.py — prefs, format tables
    scanner.py     — tool probing, help parsing, args DB
    dialogs.py     — ArgsReferenceScreen, ArgValueModal, SettingsScreen
"""

import re
import subprocess
from pathlib import Path
from datetime import datetime

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, HorizontalScroll, VerticalScroll
from textual.widgets import (
    Static, Input, Button, Select, Checkbox,
    ProgressBar, RichLog, TextArea, RadioSet, RadioButton,
)
from textual.reactive import reactive
from textual.worker import get_current_worker
from textual import work
from rich.text import Text

from persistence import (
    load_prefs, save_prefs, format_badge,
    load_presets, save_presets,
    IMAGE_FORMATS, VIDEO_FORMATS, AUDIO_FORMATS,
    ALL_FORMATS, ALL_EXTENSIONS, IMAGE_EXTENSIONS,
)
from scanner import probe_tool
from dialogs import ArgsReferenceScreen, SettingsScreen, BrowseScreen


def _plabel(name: str) -> str:
    """Pad preset name to 12 chars with dots for left-aligned appearance."""
    return name[:30].ljust(30, ".")


def _preset_sort_key(p):
    """Sort presets: image first, then video/audio, alphabetically within."""
    fmt = p.get("format", "")
    if fmt in IMAGE_FORMATS:
        group = 0
    elif fmt in VIDEO_FORMATS:
        group = 1
    else:
        group = 2
    return (group, p.get("name", "").lower())


class ConverterApp(App):
    CSS_PATH = "converter.tcss"
    TITLE = "Batch File Converter"

    BINDINGS = [
        ("ctrl+q", "quit_app", "Quit"),
        ("ctrl+s", "open_settings", "Settings"),
    ]

    running = reactive(False)
    _ui_ready = False

    def compose(self) -> ComposeResult:
        # Header
        with Horizontal(id="header-bar"):
            yield Static("BATCH CONVERTER", id="title")
            yield Static("", id="tool-status")
            yield Button("settings", id="settings-btn")

        # Three columns
        with Horizontal(id="columns"):
            # Col 1 — input + output + options
            with Vertical(id="col1"):
                inp_panel = Vertical(classes="panel", id="input-panel")
                inp_panel.border_title = "INPUT SOURCE"
                with inp_panel:
                    yield RadioSet(
                        RadioButton("FOLDER", value=True, id="rb-folder"),
                        RadioButton("FILE", id="rb-file"),
                        id="input-mode",
                    )
                    with Horizontal(classes="browse-row"):
                        yield Input(placeholder="folder path", id="input-path")
                        yield Button("..", id="browse-input-folder")
                    with Horizontal(classes="browse-row"):
                        yield Input(placeholder="file path", id="input-file")
                        yield Button("..", id="browse-input-file")
                out_panel = Vertical(classes="panel")
                out_panel.border_title = "OUTPUT"
                with out_panel:
                    with Horizontal(classes="browse-row"):
                        yield Input(placeholder="output folder", id="output-path")
                        yield Button("..", id="browse-output")
                    yield Static("", classes="sep")
                    yield Checkbox("Overwrite existing", True, id="overwrite")
                    yield Checkbox("Skip if src = target fmt", True, id="skip-same")
                    yield Checkbox("Include subfolders", False, id="recurse")
                    yield Static("", classes="sep")
                    with Horizontal(id="ps-row"):
                        with Vertical(classes="ps-col"):
                            yield Static("PREFIX", classes="panel-label")
                            yield Input(placeholder="", id="prefix")
                        with Vertical(classes="ps-col"):
                            yield Static("SUFFIX", classes="panel-label")
                            yield Input(placeholder="", id="suffix")
                    yield Static("e.g.  filename.png", id="name-preview")

            # Col 2 — format + presets
            with Vertical(id="col2"):
                fmt_panel = Vertical(classes="panel", id="format-panel")
                fmt_panel.border_title = "FORMAT"
                with fmt_panel:
                    yield Select(
                        [(f, f) for f in ALL_FORMATS],
                        value="png", id="format-select",
                    )
                    yield Static("img", id="fmt-badge")
                preset_panel = Vertical(classes="panel", id="preset-panel")
                preset_panel.border_title = "PRESETS"
                with preset_panel:
                    with VerticalScroll(id="preset-scroll"):
                        yield Static("IMAGE", classes="preset-group-hdr")
                        with Vertical(id="preset-img-row"):
                            yield Button(_plabel("jpg"), id="preset-jpg")
                            yield Button(_plabel("gif"), id="preset-gif")
                        yield Static("VIDEO", classes="preset-group-hdr")
                        with Vertical(id="preset-vid-row"):
                            yield Button(_plabel("mp4"), id="preset-mp4")

            # Col 3 — args + progress + buttons
            with Vertical(id="col3"):
                args_panel = Vertical(classes="panel")
                args_panel.border_title = "EXTRA ARGS"
                with args_panel:
                    yield TextArea(id="extra-args")
                    with Horizontal(classes="btn-row"):
                        yield Button("ADD ARGS", id="args-btn")
                    with Horizontal(id="save-preset-row"):
                        yield Input(placeholder="name", id="preset-name",
                                    max_length=30)
                        yield Button("save", id="save-preset-btn")
                        yield Button("del", id="del-preset-btn", classes="danger")
                yield ProgressBar(id="progress", total=100, show_eta=False)
                with Horizontal(classes="btn-row"):
                    yield Button("CONVERT", id="convert-btn", classes="primary")
                    yield Button("CANCEL", id="cancel-btn", disabled=True)
                    yield Button("QUIT", id="quit-btn", classes="ghost")
                yield Static("ready", id="status")

        # Command preview + log
        yield Static("", id="cmd-preview")
        log_area = Vertical(id="log-area")
        log_area.border_title = "LOG"
        with log_area:
            yield RichLog(id="log", highlight=True, markup=True)
            with Horizontal(id="log-bar"):
                yield Static("", id="summary")
                yield Button("clear", id="clear-btn", classes="ghost")
        

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        self.prefs = load_prefs()
        self._check_tools()
        self._restore_prefs()
        self._load_user_presets()
        self._ui_ready = True

    def action_quit_app(self) -> None:
        self._save_session()
        self.exit()

    def action_open_settings(self) -> None:
        self._open_settings()

    # ── Tool detection ────────────────────────────────────────────────────

    def _check_tools(self):
        im_exe = self.prefs.get("im_exe", "magick")
        ff_exe = self.prefs.get("ff_exe", "ffmpeg")

        im_ok, _ = probe_tool(im_exe)
        self.has_magick = im_ok
        self.im_exe = im_exe if im_ok else None
        if not im_ok:
            ok, _ = probe_tool("convert")
            if ok:
                self.has_magick, self.im_exe = True, "convert"

        ff_ok, _ = probe_tool(ff_exe)
        self.has_ffmpeg = ff_ok
        self.ff_exe = ff_exe if ff_ok else None

        status = (f"IM {'OK' if self.has_magick else 'X'}  |  "
                  f"FFmpeg {'OK' if self.has_ffmpeg else 'X'}")
        self.query_one("#tool-status", Static).update(status)

    def _im_cmd(self): return self.im_exe or "magick"
    def _ff_cmd(self): return self.ff_exe or "ffmpeg"

    # ── Prefs ─────────────────────────────────────────────────────────────

    def _restore_prefs(self):
        p = self.prefs
        if v := p.get("input_path"):
            self.query_one("#input-path", Input).value = v
        if v := p.get("input_file"):
            self.query_one("#input-file", Input).value = v
        if v := p.get("input_mode"):
            if v == "file":
                self.query_one("#rb-file", RadioButton).value = True
        if v := p.get("output_path"):
            self.query_one("#output-path", Input).value = v
        if v := p.get("format"):
            self.query_one("#format-select", Select).value = v
            self._update_badge(v)
        if v := p.get("prefix"):
            self.query_one("#prefix", Input).value = v
        if v := p.get("suffix"):
            self.query_one("#suffix", Input).value = v
        if v := p.get("extra_args"):
            self.query_one("#extra-args", TextArea).text = v

    def _save_session(self):
        mode = "file" if self.query_one("#rb-file", RadioButton).value else "folder"
        self.prefs.update({
            "input_path":  self.query_one("#input-path", Input).value,
            "input_file":  self.query_one("#input-file", Input).value,
            "input_mode":  mode,
            "output_path": self.query_one("#output-path", Input).value,
            "format":      self._get_format(),
            "prefix":      self.query_one("#prefix", Input).value,
            "suffix":      self.query_one("#suffix", Input).value,
            "extra_args":  self.query_one("#extra-args", TextArea).text.strip(),
        })
        save_prefs(self.prefs)

    # ── User presets ──────────────────────────────────────────────────────

    def _load_user_presets(self):
        presets = sorted(load_presets(), key=_preset_sort_key)
        img_row = self.query_one("#preset-img-row", Vertical)
        vid_row = self.query_one("#preset-vid-row", Vertical)
        for p in presets:
            btn = Button(_plabel(p["name"]), id=f"upreset-{p['name']}")
            if p.get("format", "") in IMAGE_FORMATS:
                img_row.mount(btn)
            else:
                vid_row.mount(btn)

    def _save_user_preset(self):
        name = self.query_one("#preset-name", Input).value.strip()
        if not name:
            self.notify("Enter a preset name", severity="error"); return
        name = name[:30]
        fmt = self._get_format()
        args = self.query_one("#extra-args", TextArea).text.strip()
        presets = load_presets()
        presets = [p for p in presets if p["name"] != name]
        presets.append({"name": name, "format": fmt, "args": args})
        save_presets(presets)
        self._rebuild_preset_buttons()
        self.query_one("#preset-name", Input).value = ""
        self.notify(f"Preset '{name}' saved")

    def _delete_user_preset(self):
        name = self.query_one("#preset-name", Input).value.strip()
        if not name:
            self.notify("Enter preset name to delete", severity="error"); return
        presets = load_presets()
        new = [p for p in presets if p["name"] != name]
        if len(new) == len(presets):
            self.notify(f"Preset '{name}' not found", severity="error"); return
        save_presets(new)
        self._rebuild_preset_buttons()
        self.query_one("#preset-name", Input).value = ""
        self.notify(f"Preset '{name}' deleted")

    def _rebuild_preset_buttons(self):
        """Remove all user preset buttons and re-add sorted into correct groups."""
        for btn in list(self.query("#preset-img-row Button, #preset-vid-row Button")):
            if btn.id and btn.id.startswith("upreset-"):
                btn.remove()
        presets = sorted(load_presets(), key=_preset_sort_key)
        def _remount():
            img_row = self.query_one("#preset-img-row", Vertical)
            vid_row = self.query_one("#preset-vid-row", Vertical)
            for p in presets:
                btn = Button(_plabel(p["name"]), id=f"upreset-{p['name']}")
                if p.get("format", "") in IMAGE_FORMATS:
                    img_row.mount(btn)
                else:
                    vid_row.mount(btn)
        self.call_after_refresh(_remount)

    # ── Helpers ───────────────────────────────────────────────────────────

    def _get_format(self) -> str:
        v = self.query_one("#format-select", Select).value
        return str(v) if v != Select.BLANK else "png"

    def _get_input_mode(self) -> str:
        return "file" if self.query_one("#rb-file", RadioButton).value else "folder"

    def _update_badge(self, fmt: str):
        self.query_one("#fmt-badge", Static).update(format_badge(fmt))

    def _update_name_preview(self):
        pre = self.query_one("#prefix", Input).value
        suf = self.query_one("#suffix", Input).value
        fmt = self._get_format()
        self.query_one("#name-preview", Static).update(
            f"e.g.  {pre}filename{suf}.{fmt}")

    @staticmethod
    def _short_path(p):
        s = str(p)
        if len(s) <= 25:
            return s
        parent = str(Path(p).parent)
        name = Path(p).name
        if len(parent) > 15:
            parent = parent[:5] + "..." + parent[-10:]
        return parent + "/" + name

    def _update_cmd_preview(self):
        fmt = self._get_format()
        if not fmt:
            self.query_one("#cmd-preview", Static).update(""); return
        mode = self._get_input_mode()
        if mode == "file":
            inp = self.query_one("#input-file", Input).value.strip()
            src = Path(inp) if inp else None
        else:
            inp = self.query_one("#input-path", Input).value.strip()
            if inp and Path(inp).is_dir():
                files = sorted(p for p in Path(inp).glob("*")
                               if p.is_file() and p.suffix.lower() in ALL_EXTENSIONS)
                src = files[0] if files else None
            else:
                src = None
        out = self.query_one("#output-path", Input).value.strip()
        if not src or not out:
            self.query_one("#cmd-preview", Static).update(""); return
        dst = Path(out) / self._output_name(src, fmt)
        extra = self._extra_args()
        src_ext = src.suffix.lower().lstrip(".")
        use_im = self.has_magick and (
            src_ext in IMAGE_FORMATS and fmt in IMAGE_FORMATS)
        short_src = self._short_path(src)
        short_dst = self._short_path(dst)
        exe = Path(self._im_cmd() if use_im else self._ff_cmd()).name
        if not use_im and not self.has_ffmpeg:
            self.query_one("#cmd-preview", Static).update(""); return

        t = Text()
        t.append(exe, style="bold blue")
        if use_im:
            t.append(f" file:{short_src}", style="green")
        else:
            t.append(" -y -i ", style="bold yellow")
            t.append(short_src, style="green")
        for a in extra:
            t.append(f" {a}", style="bold yellow")
        t.append(f" {short_dst}", style="green")
        self.query_one("#cmd-preview", Static).update(t)

    # ── Event handlers ────────────────────────────────────────────────────

    def on_select_changed(self, event: Select.Changed) -> None:
        if not self._ui_ready:
            return
        if event.select.id == "format-select":
            fmt = str(event.value) if event.value != Select.BLANK else "png"
            self._update_badge(fmt)
            self._update_name_preview()
            self._update_cmd_preview()

    def on_input_changed(self, event: Input.Changed) -> None:
        if not self._ui_ready:
            return
        if event.input.id in ("prefix", "suffix"):
            self._update_name_preview()
        if event.input.id in ("input-path", "input-file", "output-path",
                               "prefix", "suffix"):
            self._update_cmd_preview()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if not self._ui_ready:
            return
        if event.text_area.id == "extra-args":
            self._update_cmd_preview()

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if not self._ui_ready:
            return
        if event.radio_set.id == "input-mode":
            self._update_cmd_preview()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id == "convert-btn":
            self._start_conversion()
        elif btn_id == "cancel-btn":
            self._cancel()
        elif btn_id == "quit-btn":
            self.action_quit_app()
        elif btn_id == "clear-btn":
            self._clear_log()
        elif btn_id == "settings-btn":
            self._open_settings()
        elif btn_id == "args-btn":
            self._open_args_reference()
        elif btn_id == "save-preset-btn":
            self._save_user_preset()
        elif btn_id == "del-preset-btn":
            self._delete_user_preset()
        elif btn_id == "browse-input-folder":
            self._browse("folder", "#input-path")
        elif btn_id == "browse-input-file":
            self._browse("file", "#input-file")
        elif btn_id == "browse-output":
            self._browse("folder", "#output-path")
        elif btn_id == "preset-jpg":
            self._apply_preset("jpg", "-quality 85", "jpg")
        elif btn_id == "preset-mp4":
            self._apply_preset("mp4", "-c:v libx264 -crf 23 -preset fast", "mp4")
        elif btn_id == "preset-gif":
            self._apply_preset("gif", "", "gif")
        elif btn_id.startswith("upreset-"):
            self._apply_user_preset(btn_id[8:])

    def _apply_preset(self, fmt: str, args: str, preset_name: str = ""):
        self.query_one("#format-select", Select).value = fmt
        self.query_one("#extra-args", TextArea).text = args
        if preset_name:
            self.query_one("#preset-name", Input).value = preset_name
        self._update_badge(fmt)
        self._update_name_preview()
        self._update_cmd_preview()

    def _apply_user_preset(self, name: str):
        presets = load_presets()
        for p in presets:
            if p["name"] == name:
                self._apply_preset(p["format"], p.get("args", ""), name)
                return

    # ── Browse ────────────────────────────────────────────────────────────

    def _browse(self, mode: str, target_id: str):
        current = self.query_one(target_id, Input).value.strip()
        start = current if current else "."
        self.push_screen(
            BrowseScreen(mode=mode, start_path=start),
            lambda result: self._on_browse_result(result, target_id, mode))

    def _on_browse_result(self, result, target_id, mode):
        if result:
            self.query_one(target_id, Input).value = result
            if target_id == "#input-path":
                self.query_one("#rb-folder", RadioButton).value = True
                if not self.query_one("#output-path", Input).value:
                    self.query_one("#output-path", Input).value = result
            elif target_id == "#input-file":
                self.query_one("#rb-file", RadioButton).value = True
                if not self.query_one("#output-path", Input).value:
                    self.query_one("#output-path", Input).value = str(
                        Path(result).parent)

    # ── Dialogs ───────────────────────────────────────────────────────────

    def _open_settings(self):
        self.push_screen(SettingsScreen(self.prefs), self._on_settings_close)

    def _on_settings_close(self, result) -> None:
        if result:
            self.prefs = result
            self._check_tools()

    def _open_args_reference(self):
        fmt = self._get_format()
        self.push_screen(ArgsReferenceScreen(fmt), self._on_args_close)

    def _on_args_close(self, result) -> None:
        if result:
            ta = self.query_one("#extra-args", TextArea)
            current = ta.text.strip()
            sep = " " if current and not current.endswith("\n") else ""
            ta.text = current + sep + result if current else result

    # ── Logging ───────────────────────────────────────────────────────────

    def _log(self, msg: str, style: str = ""):
        ts = datetime.now().strftime("%H:%M:%S")
        log_widget = self.query_one("#log", RichLog)
        if style == "ok":
            log_widget.write(Text(f"[{ts}] {msg}", style="green"))
        elif style == "warn":
            log_widget.write(Text(f"[{ts}] {msg}", style="yellow"))
        elif style == "err":
            log_widget.write(Text(f"[{ts}] {msg}", style="red"))
        elif style == "dim":
            log_widget.write(Text(f"[{ts}] {msg}", style="dim"))
        elif style == "header":
            log_widget.write(Text(f"[{ts}] {msg}", style="bold yellow"))
        else:
            log_widget.write(f"[{ts}] {msg}")

    def _clear_log(self):
        self.query_one("#log", RichLog).clear()
        self.query_one("#summary", Static).update("")

    # ── Conversion ────────────────────────────────────────────────────────

    def _extra_args(self):
        raw = self.query_one("#extra-args", TextArea).text.strip()
        return raw.split() if raw else []

    def _collect_files(self, folder, recurse):
        folder = Path(folder)
        return sorted(p for p in folder.glob("**/*" if recurse else "*")
                      if p.is_file() and p.suffix.lower() in ALL_EXTENSIONS)

    def _output_name(self, src: Path, fmt: str) -> str:
        pre = self.query_one("#prefix", Input).value
        suf = self.query_one("#suffix", Input).value
        name = re.sub(r'[()\[\]{}]', '_', f"{pre}{src.stem}{suf}")
        return f"{name}.{fmt}"

    def _start_conversion(self):
        mode = self._get_input_mode()
        inp = (self.query_one("#input-file", Input).value if mode == "file"
               else self.query_one("#input-path", Input).value).strip()
        out = self.query_one("#output-path", Input).value.strip()
        fmt = self._get_format()

        if not inp:
            self.notify("Select an input folder or file", severity="error"); return
        if not out:
            self.notify("Set an output folder", severity="error"); return
        if not fmt:
            self.notify("Select an output format", severity="error"); return
        if not self.has_magick and not self.has_ffmpeg:
            self.notify("No tools found — open Settings", severity="error"); return
        inp_path = Path(inp)
        if not inp_path.exists():
            self.notify(f"Input not found: {inp}", severity="error"); return

        Path(out).mkdir(parents=True, exist_ok=True)
        self._save_session()
        self.running = True
        self.query_one("#convert-btn", Button).disabled = True
        self.query_one("#cancel-btn", Button).disabled = False
        self.query_one("#status", Static).update("converting...")

        overwrite = self.query_one("#overwrite", Checkbox).value
        skip_same = self.query_one("#skip-same", Checkbox).value
        recurse = self.query_one("#recurse", Checkbox).value
        prefix = self.query_one("#prefix", Input).value
        suffix = self.query_one("#suffix", Input).value
        extra = self._extra_args()

        self._run_conversion(inp_path, out, fmt, mode,
                             overwrite, skip_same, recurse, prefix, suffix, extra)

    @work(exclusive=True, thread=True)
    def _run_conversion(self, inp, out, fmt, mode,
                        overwrite, skip_same, recurse, prefix, suffix, extra):
        worker = get_current_worker()

        if mode == "file":
            if inp.suffix.lower() not in ALL_EXTENSIONS:
                self.call_from_thread(self._log,
                                      f"Unsupported: {inp.suffix}", "err")
                self.call_from_thread(self._done); return
            files = [inp]
        else:
            files = self._collect_files(inp, recurse)

        if not files:
            self.call_from_thread(self._log, "No compatible files.", "warn")
            self.call_from_thread(self._done); return

        src_desc = inp.name if mode == "file" else str(inp)
        self.call_from_thread(
            self._log,
            f"{'File' if mode == 'file' else 'Folder'}:  {src_desc}  "
            f"-> {len(files)} file(s) -> .{fmt}", "header")

        ok = skip = fail = 0
        pb = self.query_one("#progress", ProgressBar)
        self.call_from_thread(setattr, pb, "total", len(files))
        self.call_from_thread(pb.update, progress=0)

        for i, src in enumerate(files):
            if worker.is_cancelled:
                self.call_from_thread(self._log, "Cancelled.", "warn")
                break

            src_ext = src.suffix.lower().lstrip(".")

            if skip_same and src_ext == fmt and not prefix and not suffix:
                self.call_from_thread(
                    self._log, f"skip  {src.name}  (already {fmt})", "dim")
                skip += 1
                self.call_from_thread(pb.update, advance=1)
                continue

            name = re.sub(r'[()\[\]{}]', '_',
                          f"{prefix}{src.stem}{suffix}")
            dst = Path(out) / f"{name}.{fmt}"

            if not overwrite and dst.exists():
                self.call_from_thread(
                    self._log, f"skip  {src.name}  (exists)", "dim")
                skip += 1
                self.call_from_thread(pb.update, advance=1)
                continue

            self.call_from_thread(
                self.query_one("#status", Static).update,
                f"converting {src.name}")

            success, err, cmd = self._convert_file(src, dst, fmt, extra)
            if cmd:
                self.call_from_thread(
                    self._log,
                    f"$  {subprocess.list2cmdline(cmd)}", "dim")
            if success:
                self.call_from_thread(
                    self._log, f"OK  {src.name}  ->  {dst.name}", "ok")
                ok += 1
            else:
                self.call_from_thread(
                    self._log, f"X  {src.name}  --  {err}", "err")
                fail += 1
            self.call_from_thread(pb.update, advance=1)

        summary = f"{ok} converted  |  {skip} skipped  |  {fail} failed"
        self.call_from_thread(self._log, f"Done.  {summary}", "header")
        self.call_from_thread(
            self.query_one("#summary", Static).update, summary)
        self.call_from_thread(self._done)

    def _convert_file(self, src, dst, fmt, extra):
        src_ext = src.suffix.lower().lstrip(".")
        use_im = self.has_magick and (
            src_ext in IMAGE_FORMATS and fmt in IMAGE_FORMATS)
        try:
            if use_im:
                cmd = [self._im_cmd(), f"file:{src}"] + extra + [str(dst)]
            elif self.has_ffmpeg:
                cmd = [self._ff_cmd(), "-y", "-i", str(src)] + extra + [str(dst)]
            else:
                return False, "no suitable tool", None
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                lines = [l for l in
                         (r.stderr or r.stdout or "error").strip().splitlines()
                         if l.strip()]
                return False, lines[-1] if lines else "conversion failed", cmd
            return True, None, cmd
        except subprocess.TimeoutExpired:
            return False, "timed out (>120s)", cmd
        except Exception as e:
            return False, str(e), None

    def _cancel(self):
        self.workers.cancel_group(self, "default")
        self.query_one("#cancel-btn", Button).disabled = True

    def _done(self):
        self.running = False
        self.query_one("#convert-btn", Button).disabled = False
        self.query_one("#cancel-btn", Button).disabled = True
        self.query_one("#status", Static).update("done")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = ConverterApp()
    app.run()
