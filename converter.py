"""
converter.py — Batch File Converter TUI (Textual).

Run with:  python converter.py

Modules:
    converter.tcss — styling
    persistence.py — prefs, format tables
    scanner.py     — tool probing, help parsing, args DB
    dialogs.py     — ArgsReferenceScreen, ArgValueModal, SettingsScreen
"""

import os
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
    resolve_theme_tokens,
    IMAGE_FORMATS, VIDEO_FORMATS, AUDIO_FORMATS,
    ALL_FORMATS, ALL_EXTENSIONS, IMAGE_EXTENSIONS, IMAGE_INPUT_FORMATS,
)
from scanner import probe_tool
from dialogs import ArgsReferenceScreen, SettingsScreen, BrowseScreen, SplashScreen


def _plabel(name: str) -> str:
    return f"\\[{name[:28]}]".ljust(30)


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
    CSS_PATH = ["converter.tcss"]
    TITLE = "Batch File Converter"

    def __init__(self):
        self.prefs = load_prefs()
        super().__init__()

    BINDINGS = [
        ("ctrl+q", "quit_app", "Quit"),
        ("ctrl+s", "open_settings", "Settings"),
    ]

    running = reactive(False)
    _ui_ready = False
    _current_preset: str = ""

    def compose(self) -> ComposeResult:
        # Header
        with Horizontal(id="header-bar"):
            yield Static("BATCH CONVERTER", id="title")
            yield Static("", id="tool-status")
            with Horizontal(id="header-btns"):
                yield Button("settings", id="settings-btn", classes="ghost")
                yield Button("quit", id="quit-btn", classes="ghost")

        # Three columns
        with Horizontal(id="columns"):
            # Col 1 — input + output + options
            with Vertical(id="col1"):
                inp_panel = Vertical(classes="panel", id="input-panel")
                inp_panel.border_title = "INPUT"
                with inp_panel:
                    yield RadioSet(
                        RadioButton("FOLDER", value=True, id="rb-folder"),
                        RadioButton("FILE", id="rb-file"),
                        RadioButton("SEQ", id="rb-seq"),
                        id="input-mode",
                    )
                    with Horizontal(classes="browse-row"):
                        yield Input(placeholder="folder / file path", id="input-source")
                        yield Button("\U0001F4C4", id="browse-input")
                out_panel = Vertical(classes="panel")
                out_panel.border_title = "OUTPUT"
                with out_panel:
                    yield Checkbox("Output to same folder", False, id="same-folder")
                    with Horizontal(classes="browse-row"):
                        yield Input(placeholder="output folder", id="output-path")
                        yield Button("\U0001F4C4", id="browse-output")
                    yield Checkbox("Overwrite existing", True, id="overwrite")
                    yield Checkbox("Skip if src = target fmt", True, id="skip-same")
                    yield Checkbox("Include subfolders", False, id="recurse")
                    yield Input(placeholder="[inputFile]", id="output-template")
                    with Vertical(id="token-btns"):
                        with Horizontal():
                            yield Button(r"\[YYYYMMDD]", id="tok-YYYYMMDD", classes="token")
                            yield Button(r"\[inputFile]", id="tok-inputFile", classes="token")
                            yield Button(r"\[sequence]",  id="tok-sequence",  classes="token")
                        # with Horizontal():
                            yield Button(r"\[username]",  id="tok-username",  classes="token")
                            yield Button(r"\[codec]",     id="tok-codec",     classes="token")
                            yield Button(r"\[preset]",    id="tok-preset",    classes="token")
                    yield Static("", id="name-preview")
                fmt_panel = Vertical(classes="panel", id="format-panel")
                fmt_panel.border_title = "FORMAT"
                with fmt_panel:
                    yield Select(
                        [(f, f) for f in ALL_FORMATS],
                        value="png", id="format-select",
                    )
                    yield Static("img", id="fmt-badge")

            # Col 2 — presets
            with Vertical(id="col2"):
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
                        yield Button("ARGUMENT LIBRARY", id="args-btn")
                    with Horizontal(id="save-preset-row"):               
                        preset_input =  Input(placeholder="name", id="preset-name", max_length=30)
                        preset_input.border_title = "PRESET NAME"
                        yield preset_input
                        yield Button("save", id="save-preset-btn")
                        yield Button("del", id="del-preset-btn", classes="danger")
                yield ProgressBar(id="progress", total=100, show_eta=False)
                with Horizontal(classes="btn-row"):
                    yield Button("CONVERT", id="convert-btn")
                    yield Button("CANCEL", id="cancel-btn", disabled=True)
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

    def get_css_variables(self) -> dict[str, str]:
        return {**super().get_css_variables(), **resolve_theme_tokens(self.prefs)}

    def on_mount(self) -> None:
        self._check_tools()
        self._restore_prefs()
        self._load_user_presets()
        self._ui_ready = True
        self.push_screen(SplashScreen())

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
        if v := p.get("input_source"):
            self.query_one("#input-source", Input).value = v
        if v := p.get("input_mode"):
            if v == "file":
                self.query_one("#rb-file", RadioButton).value = True
            elif v == "sequence":
                self.query_one("#rb-seq", RadioButton).value = True
        if p.get("same_folder"):
            self.query_one("#same-folder", Checkbox).value = True
            self._apply_same_folder(True)
        if v := p.get("output_path"):
            self.query_one("#output-path", Input).value = v
        if v := p.get("format"):
            self.query_one("#format-select", Select).value = v
            self._update_badge(v)
        if v := p.get("output_template"):
            self.query_one("#output-template", Input).value = v
        if v := p.get("extra_args"):
            self.query_one("#extra-args", TextArea).text = v

    def _save_session(self):
        self.prefs.update({
            "input_source":  self.query_one("#input-source", Input).value,
            "input_mode":    self._get_input_mode(),
            "same_folder":   self.query_one("#same-folder", Checkbox).value,
            "output_path":   self.query_one("#output-path", Input).value,
            "format":        self._get_format(),
            "output_template": self.query_one("#output-template", Input).value,
            "extra_args":    self.query_one("#extra-args", TextArea).text.strip(),
        })
        save_prefs(self.prefs)

    def _apply_theme(self):
        self.refresh_css(animate=False)

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
        if self.query_one("#rb-file", RadioButton).value:
            return "file"
        if self.query_one("#rb-seq", RadioButton).value:
            return "sequence"
        return "folder"

    def _update_badge(self, fmt: str):
        self.query_one("#fmt-badge", Static).update(format_badge(fmt))

    def _resolve_codec(self) -> str:
        args = self._extra_args()
        flags = {"-c:v", "-c:a", "-vcodec", "-acodec"}
        for i, a in enumerate(args):
            if a in flags and i + 1 < len(args):
                return args[i + 1]
        return ""

    @staticmethod
    def _resolve_token(template, src, fmt, index, codec, preset_name) -> str:
        date_str = datetime.now().strftime("%Y%m%d")
        try:
            username = os.getlogin()
        except Exception:
            username = ""
        result = template or "[inputFile]"
        result = result.replace("[YYYYMMDD]", date_str)
        result = result.replace("[inputFile]", src.stem)
        result = result.replace("[sequence]", f"{index + 1:04d}")
        result = result.replace("[username]", username)
        result = result.replace("[codec]", codec)
        result = result.replace("[preset]", preset_name)
        return re.sub(r'[()\[\]{}]', '_', result)

    def _update_name_preview(self):
        fmt = self._get_format()
        fake = Path("filename.ext")
        preview = self._output_name(fake, fmt, index=0)
        self.query_one("#name-preview", Static).update(f"e.g.  {preview}")

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
        out = self.query_one("#output-path", Input).value.strip()
        inp = self.query_one("#input-source", Input).value.strip()
        extra = self._extra_args()

        if mode == "sequence":
            if inp and Path(inp).exists() and out:
                seq = self._resolve_sequence(Path(inp))
                if seq:
                    template = self.query_one("#output-template", Input).value
                    dst_stem = self._resolve_token(template,
                                                   Path(seq["stem_prefix"]), fmt, 0,
                                                   self._resolve_codec(),
                                                   self._current_preset)
                    dst = Path(out) / f"{dst_stem}.{fmt}"
                    pat = self._short_path(seq["pattern"])
                    short_dst = self._short_path(dst)
                    exe = Path(self._ff_cmd()).name
                    if not self.has_ffmpeg:
                        self.query_one("#cmd-preview", Static).update(""); return
                    t = Text()
                    t.append(exe, style="bold blue")
                    t.append(" -y", style="bold yellow")
                    t.append(f" -start_number {seq['start']}", style="bold yellow")
                    t.append(" -i ", style="bold yellow")
                    t.append(pat, style="green")
                    for a in extra:
                        t.append(f" {a}", style="bold yellow")
                    t.append(f" {short_dst}", style="green")
                    self.query_one("#cmd-preview", Static).update(t)
                    return
            self.query_one("#cmd-preview", Static).update(""); return

        if mode == "file":
            src = Path(inp) if inp else None
        else:
            if inp and Path(inp).is_dir():
                files = sorted(p for p in Path(inp).glob("*")
                               if p.is_file() and p.suffix.lower() in ALL_EXTENSIONS)
                src = files[0] if files else None
            else:
                src = None
        if not src or not out:
            self.query_one("#cmd-preview", Static).update(""); return
        dst = Path(out) / self._output_name(src, fmt)
        src_ext = src.suffix.lower().lstrip(".")
        use_im = self.has_magick and (
            src_ext in IMAGE_INPUT_FORMATS and fmt in IMAGE_FORMATS)
        short_src = self._short_path(src)
        short_dst = self._short_path(dst)
        exe = Path(self._im_cmd() if use_im else self._ff_cmd()).name
        if not use_im and not self.has_ffmpeg:
            self.query_one("#cmd-preview", Static).update(""); return

        t = Text()
        t.append(exe, style="bold blue")
        if use_im:
            t.append(f" {short_src}", style="green")
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
        if event.input.id == "output-template":
            self._update_name_preview()
        if event.input.id in ("input-source", "output-path", "output-template"):
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

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if not self._ui_ready:
            return
        if event.checkbox.id == "same-folder":
            self._apply_same_folder(event.value)

    def _apply_same_folder(self, enabled: bool) -> None:
        self.query_one("#output-path", Input).disabled = enabled
        self.query_one("#browse-output", Button).disabled = enabled

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
        elif btn_id.startswith("tok-"):
            token = "[" + btn_id[4:] + "]"
            inp = self.query_one("#output-template", Input)
            cur = inp.value
            sep = "_" if cur and not cur.endswith("_") else ""
            inp.value = cur + sep + token
            inp.focus()
        elif btn_id == "browse-input":
            browse_mode = "folder" if self._get_input_mode() == "folder" else "file"
            self._browse(browse_mode, "#input-source")
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
        self._current_preset = preset_name
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
        if not result:
            return
        self.query_one(target_id, Input).value = result
        if target_id == "#input-source":
            if not self.query_one("#output-path", Input).value:
                p = Path(result)
                self.query_one("#output-path", Input).value = (
                    str(p.parent) if p.is_file() else result
                )

    # ── Dialogs ───────────────────────────────────────────────────────────

    def _open_settings(self):
        self.push_screen(SettingsScreen(self.prefs), self._on_settings_close)

    def _on_settings_close(self, result) -> None:
        if result:
            self.prefs = result
            self._apply_theme()
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
        if recurse:
            return sorted(p for p in folder.glob("**/*")
                          if p.is_file() and p.suffix.lower() in ALL_EXTENSIONS)
        # Use os.scandir for the flat case — pathlib.glob can silently resolve
        # drive-letter paths to UNC on Windows, breaking network-drive scans.
        import os
        try:
            result = []
            for entry in os.scandir(str(folder)):
                if entry.is_file(follow_symlinks=False):
                    if os.path.splitext(entry.name)[1].lower() in ALL_EXTENSIONS:
                        result.append(Path(entry.path))
            return sorted(result)
        except OSError:
            return []

    def _resolve_sequence(self, file_path: Path):
        m = re.match(r'^(.*?)(\d+)$', file_path.stem)
        if not m:
            return None
        prefix, digits = m.group(1), m.group(2)
        pad = len(digits)
        ext = file_path.suffix
        files = sorted(
            p for p in file_path.parent.glob(f"*{ext}")
            if re.match(rf'^{re.escape(prefix)}\d+$', p.stem, re.IGNORECASE)
        )
        if not files:
            return None
        nums = [int(re.search(r'\d+$', p.stem).group()) for p in files]
        return {
            "pattern": file_path.parent / f"{prefix}%0{pad}d{ext}",
            "start":   min(nums),
            "count":   len(files),
            "stem_prefix": prefix.rstrip("_"),
        }

    def _output_name(self, src: Path, fmt: str, index: int = 0) -> str:
        template = self.query_one("#output-template", Input).value
        name = self._resolve_token(template, src, fmt, index,
                                   self._resolve_codec(), self._current_preset)
        return f"{name}.{fmt}"

    def _start_conversion(self):
        mode = self._get_input_mode()
        inp_raw = self.query_one("#input-source", Input).value.strip()
        out = self.query_one("#output-path", Input).value.strip()
        fmt = self._get_format()

        same_folder = self.query_one("#same-folder", Checkbox).value
        if not inp_raw:
            self.notify("Select an input folder or file", severity="error"); return
        if not same_folder and not out:
            self.notify("Set an output folder", severity="error"); return
        if not fmt:
            self.notify("Select an output format", severity="error"); return
        if not self.has_magick and not self.has_ffmpeg:
            self.notify("No tools found — open Settings", severity="error"); return
        inp_path = Path(inp_raw)
        if mode == "folder" and inp_path.is_file():
            inp_path = inp_path.parent
        if not inp_path.exists():
            self.notify(f"Input not found: {inp_raw}", severity="error"); return

        if not same_folder:
            Path(out).mkdir(parents=True, exist_ok=True)
        self._save_session()
        self.running = True
        self.query_one("#convert-btn", Button).disabled = True
        self.query_one("#cancel-btn", Button).disabled = False
        self.query_one("#status", Static).update("converting...")

        overwrite = self.query_one("#overwrite", Checkbox).value
        skip_same = self.query_one("#skip-same", Checkbox).value
        recurse = self.query_one("#recurse", Checkbox).value
        output_template = self.query_one("#output-template", Input).value
        codec = self._resolve_codec()
        preset_name = self._current_preset
        extra = self._extra_args()

        seq_info = None
        if mode == "sequence":
            seq_info = self._resolve_sequence(inp_path)
            if seq_info is None:
                self.notify("No numbered sequence found", severity="error")
                self._done(); return

        self._run_conversion(inp_path, out, fmt, mode,
                             overwrite, skip_same, recurse,
                             output_template, codec, preset_name, extra,
                             seq_info, same_folder)

    @work(exclusive=True, thread=True)
    def _run_conversion(self, inp, out, fmt, mode,
                        overwrite, skip_same, recurse,
                        output_template, codec, preset_name, extra,
                        seq_info=None, same_folder=False):
        worker = get_current_worker()

        if mode == "sequence":
            dst_stem = self._resolve_token(output_template,
                                           Path(seq_info["stem_prefix"]), fmt, 0,
                                           codec, preset_name)
            out_dir = inp.parent if same_folder else Path(out)
            dst = out_dir / f"{dst_stem}.{fmt}"
            ff_exe = self._ff_cmd()
            cmd = ([ff_exe, "-y",
                    "-start_number", str(seq_info["start"]),
                    "-i", str(seq_info["pattern"])]
                   + extra + [str(dst)])
            pb = self.query_one("#progress", ProgressBar)
            self.call_from_thread(setattr, pb, "total", 1)
            self.call_from_thread(pb.update, progress=0)
            self.call_from_thread(
                self._log,
                f"SEQ:  {seq_info['pattern'].name}  ({seq_info['count']} frames) -> .{fmt}",
                "header")
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                self.call_from_thread(
                    self._log, f"$  {subprocess.list2cmdline(cmd)}", "dim")
                if r.returncode != 0:
                    lines = [l for l in
                             (r.stderr or r.stdout or "error").strip().splitlines()
                             if l.strip()]
                    err = lines[-1] if lines else "conversion failed"
                    self.call_from_thread(self._log, f"X  {err}", "err")
                    self.call_from_thread(
                        self.query_one("#summary", Static).update,
                        "0 converted  |  0 skipped  |  1 failed")
                else:
                    self.call_from_thread(
                        self._log, f"OK  {dst.name}", "ok")
                    self.call_from_thread(
                        self.query_one("#summary", Static).update,
                        "1 converted  |  0 skipped  |  0 failed")
            except subprocess.TimeoutExpired:
                self.call_from_thread(self._log, "X  timed out (>300s)", "err")
            except Exception as e:
                self.call_from_thread(self._log, f"X  {e}", "err")
            self.call_from_thread(pb.update, advance=1)
            self.call_from_thread(self._done)
            return

        if mode == "file":
            if inp.suffix.lower() not in ALL_EXTENSIONS:
                self.call_from_thread(self._log,
                                      f"Unsupported: {inp.suffix}", "err")
                self.call_from_thread(self._done); return
            files = [inp]
        else:
            files = self._collect_files(inp, recurse)

        if not files:
            import os
            inp_str = str(inp)
            self.call_from_thread(self._log, f"Scanned: {inp_str}", "dim")
            try:
                entries   = list(os.scandir(inp_str))
                all_files = [e for e in entries if e.is_file(follow_symlinks=False)]
                subdirs   = [e for e in entries if e.is_dir(follow_symlinks=False)]
                if all_files:
                    exts = ", ".join(sorted({os.path.splitext(e.name)[1].lower()
                                             for e in all_files}))
                    self.call_from_thread(
                        self._log,
                        f"No compatible files. Extensions found: {exts}", "warn")
                elif subdirs and not recurse:
                    self.call_from_thread(
                        self._log,
                        "No files in folder root — enable Include subfolders.", "warn")
                else:
                    self.call_from_thread(self._log, "Folder appears empty.", "warn")
            except OSError as e:
                self.call_from_thread(self._log, f"Cannot read folder: {e}", "err")
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

            if skip_same and src_ext == fmt and output_template.strip() in ("", "[inputFile]"):
                self.call_from_thread(
                    self._log, f"skip  {src.name}  (already {fmt})", "dim")
                skip += 1
                self.call_from_thread(pb.update, advance=1)
                continue

            name = self._resolve_token(output_template, src, fmt, i, codec, preset_name)
            out_dir = src.parent if same_folder else Path(out)
            dst = out_dir / f"{name}.{fmt}"

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
            src_ext in IMAGE_INPUT_FORMATS and fmt in IMAGE_FORMATS)
        try:
            if use_im:
                cmd = [self._im_cmd(), str(src)] + extra + [str(dst)]
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
