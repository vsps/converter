"""
dialogs.py — SettingsScreen, ArgsReferenceScreen, ArgValueModal,
             BrowseScreen, SplashScreen (Textual).
"""

import threading
from pathlib import Path
from datetime import datetime

from textual.app import ComposeResult
from textual.screen import Screen, ModalScreen
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Static, Input, Button, Select, TabbedContent, TabPane, DirectoryTree,
)

from scanner import (
    probe_tool, build_args_db, load_args_db, save_args_db,
    IMAGE_FORMATS, VIDEO_FORMATS, AUDIO_FORMATS,
)
from persistence import (
    THEME_COLOR_KEYS,
    get_last_value,
    load_palettes,
    resolve_theme_state,
    save_prefs,
    set_last_value,
)


# ── Splash Screen ─────────────────────────────────────────────────────────────

_LOGO = """\
 ▄████▄   ▒█████   ███▄    █ ██▒   █▓▓█████  ██▀███  ▄▄▄█████▓▓█████  ██▀███
▒██▀ ▀█  ▒██▒  ██▒ ██ ▀█   █▓██░   █▒▓█   ▀ ▓██ ▒ ██▒▓  ██▒ ▓▒▓█   ▀ ▓██ ▒ ██▒
▒▓█    ▄ ▒██░  ██▒▓██  ▀█ ██▒▓██  █▒░▒███   ▓██ ░▄█ ▒▒ ▓██░ ▒░▒███   ▓██ ░▄█ ▒
▒▓▓▄ ▄██▒▒██   ██░▓██▒  ▐▌██▒ ▒██ █░░▒▓█  ▄ ▒██▀▀█▄  ░ ▓██▓ ░ ▒▓█  ▄ ▒██▀▀█▄
▒ ▓███▀ ░░ ████▓▒░▒██░   ▓██░  ▒▀█░  ░▒████▒░██▓ ▒██▒  ▒██▒ ░ ░▒████▒░██▓ ▒██▒
░ ░▒ ▒  ░░ ▒░▒░▒░ ░ ▒░   ▒ ▒   ░ ▐░  ░░ ▒░ ░░ ▒▓ ░▒▓░  ▒ ░░   ░░ ▒░ ░░ ▒▓ ░▒▓░
  ░  ▒     ░ ▒ ▒░ ░ ░░   ░ ▒░  ░ ░░   ░ ░  ░  ░▒ ░ ▒░    ░     ░ ░  ░  ░▒ ░ ▒░
░        ░ ░ ░ ▒     ░   ░ ░     ░░     ░     ░░   ░   ░         ░     ░░   ░
░ ░          ░ ░           ░      ░     ░  ░   ░                 ░  ░   ░
░                                ░                                            \
"""


_PALETTE = [
    "#e8ff47", "#47ffb0", "#ff4d4d", "#47b0ff", "#ff47e8", "#ffb047",
]

class SplashScreen(Screen):
    """Full-screen splash — dismissed by any key or click."""

    _color_idx = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="splash-content"):
            yield Static(_LOGO, id="splash-logo")
            yield Static("press any key", id="splash-hint")

    def on_mount(self) -> None:
        self.set_interval(0.12, self._cycle)

    def _cycle(self) -> None:
        self._color_idx = (self._color_idx + 1) % len(_PALETTE)
        self.query_one("#splash-logo", Static).styles.color = \
            _PALETTE[self._color_idx]

    def on_key(self) -> None:
        self.dismiss()

    def on_click(self) -> None:
        self.dismiss()


# ── Browse Screen ─────────────────────────────────────────────────────────────

class BrowseScreen(Screen):
    """Simple file/directory browser. mode='folder' or 'file'."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, mode: str = "folder", start_path: str = "."):
        super().__init__()
        self.mode = mode
        self.start_path = start_path
        self._selected = ""

    def compose(self) -> ComposeResult:
        label = "Select Folder" if self.mode == "folder" else "Select File"
        with Horizontal(id="browse-header"):
            yield Static(label, id="browse-title")
            yield Button("[x]", id="browse-close-btn")

        with Horizontal(id="browse-path"):
            yield Input(value=self._resolve_start(),
                        placeholder="path or \\\\server\\share", id="browse-input")
            yield Button("go", id="browse-go-btn")

        yield DirectoryTree(self._resolve_root(), id="browse-tree")

        with Horizontal(id="browse-footer"):
            yield Button("SELECT", id="browse-select-btn", classes="primary")
            yield Button("cancel", id="browse-cancel-btn", classes="ghost")

    def _resolve_start(self) -> str:
        p = Path(self.start_path)
        if p.is_file():
            p = p.parent
        if not p.is_dir():
            p = Path.home()
        return str(p)

    def _resolve_root(self) -> str:
        """Return filesystem root so the tree is never restricted."""
        return str(Path(self._resolve_start()).anchor or "/")

    def _navigate_to(self, raw: str) -> None:
        """Re-root the DirectoryTree to the given path if valid."""
        p = Path(raw.strip())
        if not p.exists():
            return
        if p.is_file():
            p = p.parent
        tree = self.query_one("#browse-tree", DirectoryTree)
        tree.path = p
        self.query_one("#browse-input", Input).value = str(p)
        self._selected = str(p)

    def on_directory_tree_directory_selected(
            self, event: DirectoryTree.DirectorySelected) -> None:
        self.query_one("#browse-input", Input).value = str(event.path)
        self._selected = str(event.path)

    def on_directory_tree_file_selected(
            self, event: DirectoryTree.FileSelected) -> None:
        if self.mode == "file":
            self.query_one("#browse-input", Input).value = str(event.path)
            self._selected = str(event.path)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "browse-select-btn":
            val = self.query_one("#browse-input", Input).value.strip()
            self.dismiss(val if val else None)
        elif bid == "browse-go-btn":
            self._navigate_to(self.query_one("#browse-input", Input).value)
        elif bid in ("browse-cancel-btn", "browse-close-btn"):
            self.action_cancel()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "browse-input":
            self._navigate_to(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


# ── ArgValue Modal ───────────────────────────────────────────────────────────

class ArgValueModal(ModalScreen):
    """Popup to enter a value for a flag, then dismiss with the token string."""

    def __init__(self, entry_data: dict):
        super().__init__()
        self.entry_data = entry_data

    def compose(self) -> ComposeResult:
        flag = self.entry_data["flag"]
        arg_hint = self.entry_data.get("args", "")
        desc = self.entry_data.get("desc", "")
        needs_val = bool(arg_hint)
        last_val = get_last_value(flag)

        short_desc = desc[:80] + "..." if len(desc) > 80 else desc

        with Vertical(id="arg-value-dialog"):
            yield Static(flag, id="av-flag")
            if arg_hint:
                yield Static(arg_hint, id="av-hint")
            yield Static(short_desc, id="av-desc")
            if needs_val:
                if last_val:
                    yield Static(f"last: {last_val}", id="av-last")
                yield Input(value=last_val, placeholder="value",
                            id="av-input")
            with Horizontal(classes="btn-row"):
                yield Button("add", id="av-add", classes="primary")
                yield Button("cancel", id="av-cancel", classes="ghost")

    def on_mount(self) -> None:
        try:
            self.query_one("#av-input", Input).focus()
        except Exception:
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "av-input":
            self._confirm()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "av-add":
            self._confirm()
        elif event.button.id == "av-cancel":
            self.dismiss(None)

    def _confirm(self):
        flag = self.entry_data["flag"]
        try:
            value = self.query_one("#av-input", Input).value.strip()
        except Exception:
            value = ""

        if value:
            set_last_value(flag, value)

        token = flag if not value else f"{flag} {value}"
        self.dismiss(token)


# ── Args Reference Screen ───────────────────────────────────────────────────

class ArgRow(Static):
    """Clickable arg row."""

    def __init__(self, entry_data: dict, **kw):
        super().__init__(**kw)
        self.entry_data = entry_data
        self._flag_text = entry_data["flag"]

    def compose(self) -> ComposeResult:
        flag = self.entry_data["flag"]
        arg_hint = self.entry_data.get("args", "")
        desc = self.entry_data.get("desc", "")
        last_val = get_last_value(flag)

        flag_str = flag + (f"  {arg_hint}" if arg_hint else "")
        with Horizontal(classes="arg-row"):
            yield Static(flag_str, classes="arg-flag")
            yield Static(desc, classes="arg-desc")
            yield Static(last_val if last_val else "", classes="arg-last")

    def on_click(self) -> None:
        self.screen._open_value_popup(self.entry_data)

    def matches_search(self, tokens: list[str]) -> bool:
        if not tokens:
            return True
        haystack = " ".join([
            self.entry_data.get("flag", ""),
            self.entry_data.get("desc", ""),
            self.entry_data.get("args", ""),
        ]).lower()
        return all(t in haystack for t in tokens)


class ArgsReferenceScreen(Screen):
    """Searchable args reference for the current output format."""

    BINDINGS = [("escape", "dismiss_screen", "Back")]

    def __init__(self, fmt: str):
        super().__init__()
        self.fmt = fmt
        self.db = load_args_db()
        self._result_tokens = []

    def compose(self) -> ComposeResult:
        fmt = self.fmt
        engine = "ImageMagick" if fmt in IMAGE_FORMATS else "FFmpeg"

        with Horizontal(id="args-ref-header"):
            yield Static("ARGS REFERENCE", id="args-ref-title")
            yield Static(f"{fmt}  |  {engine}", id="args-ref-info")

        with Horizontal(id="search-bar"):
            yield Input(placeholder="search flags...", id="search-input")
            yield Static("", id="search-count")

        no_db = not self.db or ("im" not in self.db and "ff" not in self.db)
        if no_db:
            yield Static(
                "No args data found.\n\n"
                "Open Settings -> Rebuild Args Reference.",
                id="no-db-msg")
            with Horizontal(id="args-ref-footer"):
                yield Button("CLOSE", id="args-close-btn", classes="ghost")
            return

        show_im = fmt in IMAGE_FORMATS and "im" in self.db
        show_ff = (not show_im and "ff" in self.db) \
               or (fmt in IMAGE_FORMATS and "im" not in self.db and "ff" in self.db) \
               or fmt in VIDEO_FORMATS or fmt in AUDIO_FORMATS

        with TabbedContent():
            if show_im:
                with TabPane("ImageMagick", id="tab-im"):
                    with VerticalScroll():
                        yield from self._build_tab_content(
                            self.db.get("im", {}))
            if show_ff:
                with TabPane("FFmpeg", id="tab-ff"):
                    with VerticalScroll():
                        yield from self._build_tab_content(
                            self.db.get("ff", {}))

        with Horizontal(id="args-ref-footer"):
            yield Button("CLOSE", id="args-close-btn", classes="ghost")

    def _build_tab_content(self, tool_db):
        fmt_args = tool_db.get("formats", {}).get(self.fmt, [])
        general = tool_db.get("general", [])

        if fmt_args:
            yield Static(
                f"{self.fmt.upper()}-SPECIFIC  ({len(fmt_args)})",
                classes="section-hdr")
            for e in fmt_args:
                yield ArgRow(e)

        if general:
            yield Static(
                f"GENERAL  ({len(general)})",
                classes="section-hdr")
            for e in general:
                yield ArgRow(e)

        if not fmt_args and not general:
            yield Static("No data — run Rebuild in Settings.")

    def on_mount(self) -> None:
        self.query_one("#search-input", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search-input":
            self._filter(event.value)

    def _filter(self, raw: str):
        tokens = raw.strip().lower().split() if raw.strip() else []
        total = visible = 0
        for row in self.query(ArgRow):
            total += 1
            matches = row.matches_search(tokens)
            row.display = matches
            if matches:
                visible += 1
        count_text = f"{visible} / {total}" if tokens else ""
        self.query_one("#search-count", Static).update(count_text)

    def _open_value_popup(self, entry_data):
        self.app.push_screen(ArgValueModal(entry_data), self._on_value_result)

    def _on_value_result(self, result) -> None:
        if result:
            self._result_tokens.append(result)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "args-close-btn":
            self.action_dismiss_screen()

    def action_dismiss_screen(self) -> None:
        combined = " ".join(self._result_tokens) if self._result_tokens else None
        self.dismiss(combined)


# ── Settings Screen ──────────────────────────────────────────────────────────

class SettingsScreen(Screen):
    """Theme, tool paths, and args DB rebuild."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, prefs: dict):
        super().__init__()
        self.prefs = dict(prefs)
        self.palette_state = resolve_theme_state(self.prefs)
        self.palettes = self.palette_state["palettes"]

    @staticmethod
    def _normalize_hex(value: str):
        text = value.strip().lower()
        if not text:
            return None
        if not text.startswith("#"):
            text = f"#{text}"
        if len(text) != 7:
            return None
        try:
            int(text[1:], 16)
        except ValueError:
            return None
        return text

    @staticmethod
    def _theme_color_label(key: str) -> str:
        return {
            "bg": "BG",
            "text": "TEXT",
            "accent": "ACCENT",
            "success": "SUCCESS",
            "danger": "DANGER",
        }[key]

    def compose(self) -> ComposeResult:
        yield Static("SETTINGS", id="settings-title")
        with VerticalScroll(id="settings-scroll"):
            with Horizontal(id="settings-columns"):
                with Vertical(id="settings-col-left"):
                    theme_panel = Vertical(classes="theme-panel")
                    theme_panel.border_title = "THEME"
                    with theme_panel:
                        yield Select(
                            [(data["label"], name) for name, data in self.palettes.items()],
                            value=self.palette_state["palette_name"],
                            id="theme-palette",
                        )
                        yield Static("BASE COLORS", classes="section-label")
                        for key in THEME_COLOR_KEYS:
                            with Horizontal(classes="theme-color-row"):
                                yield Static(self._theme_color_label(key), classes="theme-key")
                                yield Input(value=self.palette_state["colors"][key], id=f"theme-{key}-input")
                        yield Static("DERIVED", classes="section-label")
                        with Horizontal(classes="theme-color-row"):
                            yield Static("OFFSET %", classes="theme-key")
                            yield Input(value=str(self.palette_state["brightness"]), id="theme-brightness-input")
                        with Horizontal(classes="btn-row"):
                            yield Button("Reset Theme", id="theme-reset-btn", classes="ghost")

                with Vertical(id="settings-col-right"):
                    im_panel = Vertical(classes="tool-panel")
                    im_panel.border_title = "IMAGEMAGICK"
                    with im_panel:
                        yield Static("e.g.  magick  or  full path", classes="tool-hint")
                        with Horizontal(classes="tool-row"):
                            yield Input(
                                value=self.prefs.get("im_exe", "magick"),
                                id="im-exe-input")
                            yield Button("test", id="im-test-btn", classes="ghost")
                        yield Static("", id="im-status", classes="tool-status")

                    ff_panel = Vertical(classes="tool-panel")
                    ff_panel.border_title = "FFMPEG"
                    with ff_panel:
                        yield Static("e.g.  ffmpeg  or  full path", classes="tool-hint")
                        with Horizontal(classes="tool-row"):
                            yield Input(
                                value=self.prefs.get("ff_exe", "ffmpeg"),
                                id="ff-exe-input")
                            yield Button("test", id="ff-test-btn", classes="ghost")
                        yield Static("", id="ff-status", classes="tool-status")

                    rebuild_panel = Vertical(classes="rebuild-panel")
                    rebuild_panel.border_title = "ARGS DATABASE"
                    with rebuild_panel:
                        db = load_args_db()
                        raw_ts = db.get("scanned_at", "never")
                        scanned_at = raw_ts
                        if raw_ts != "never":
                            try:
                                scanned_at = datetime.fromisoformat(raw_ts).strftime(
                                    "%d %b %Y  %H:%M")
                            except Exception:
                                pass
                        yield Static(f"last built: {scanned_at}", id="scan-ts")
                        yield Static(
                            "Scans tools and saves all args to converter_args.json",
                            classes="tool-hint")
                        with Horizontal(classes="btn-row"):
                            yield Button("Rebuild Args", id="rebuild-btn")
                        yield Static("", id="rebuild-status", classes="rebuild-status")

        with Horizontal(id="settings-footer"):
            yield Button("SAVE & CLOSE", id="save-btn", classes="primary")
            yield Button("cancel", id="cancel-btn", classes="ghost")

    def on_mount(self) -> None:
        self._probe_tool("im")
        self._probe_tool("ff")
        self.call_after_refresh(
            lambda: self._load_palette_into_controls(self.palette_state["palette_name"])
        )

    def _load_palette_into_controls(self, palette_name: str) -> None:
        if palette_name not in self.palettes:
            return
        palette = self.palettes[palette_name]
        try:
            for key in THEME_COLOR_KEYS:
                self.query_one(f"#theme-{key}-input", Input).value = palette["colors"][key]
        except Exception:
            return

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "theme-palette" and event.value != Select.BLANK:
            name = str(event.value)
            self.call_after_refresh(lambda: self._load_palette_into_controls(name))

    def _probe_tool(self, which: str):
        inp = self.query_one(f"#{which}-exe-input", Input)
        status = self.query_one(f"#{which}-status", Static)
        ok, ver = probe_tool(inp.value.strip())
        short = ver[:40] + "..." if len(ver) > 40 else ver
        if ok:
            status.update(f"OK  {short}")
        else:
            status.update(f"X  {short}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn = event.button.id
        if btn == "theme-reset-btn":
            palette_value = self.query_one("#theme-palette", Select).value
            if palette_value != Select.BLANK:
                self._load_palette_into_controls(str(palette_value))
        elif btn == "im-test-btn":
            self._probe_tool("im")
        elif btn == "ff-test-btn":
            self._probe_tool("ff")
        elif btn == "rebuild-btn":
            self._rebuild()
        elif btn == "save-btn":
            self._save()
        elif btn == "cancel-btn":
            self.action_cancel()

    def _rebuild(self):
        im_exe = self.query_one("#im-exe-input", Input).value.strip() or "magick"
        ff_exe = self.query_one("#ff-exe-input", Input).value.strip() or "ffmpeg"
        self.query_one("#rebuild-btn", Button).disabled = True
        status = self.query_one("#rebuild-status", Static)
        status.update("scanning...")

        def _do():
            def _cb(msg):
                self.app.call_from_thread(status.update, msg)
            db = build_args_db(im_exe, ff_exe, progress_cb=_cb)
            save_args_db(db)
            ts = datetime.now().strftime("%d %b %Y  %H:%M")
            im_n = len(db.get("im", {}).get("general", []))
            ff_n = len(db.get("ff", {}).get("general", []))

            def _done():
                self.query_one("#rebuild-btn", Button).disabled = False
                status.update(f"OK  {im_n} IM  |  {ff_n} FF general args")
                self.query_one("#scan-ts", Static).update(f"last built: {ts}")
            self.app.call_from_thread(_done)

        threading.Thread(target=_do, daemon=True).start()

    def _save(self):
        self.prefs["im_exe"] = (
            self.query_one("#im-exe-input", Input).value.strip() or "magick")
        self.prefs["ff_exe"] = (
            self.query_one("#ff-exe-input", Input).value.strip() or "ffmpeg")

        palette_value = self.query_one("#theme-palette", Select).value
        palette_name = str(palette_value) if palette_value != Select.BLANK else "default"
        palette = self.palettes[palette_name]

        theme_colors = {}
        for key in THEME_COLOR_KEYS:
            raw = self.query_one(f"#theme-{key}-input", Input).value
            color = self._normalize_hex(raw)
            if not color:
                self.notify(f"Invalid {self._theme_color_label(key)} color", severity="error")
                return
            if color != palette["colors"][key]:
                theme_colors[key] = color

        try:
            brightness = max(0, min(50, int(self.query_one("#theme-brightness-input", Input).value)))
        except (ValueError, TypeError):
            self.notify("Offset must be 0–50", severity="error")
            return

        self.prefs["theme_palette"] = palette_name
        self.prefs["theme_colors"] = theme_colors
        self.prefs["theme_brightness"] = brightness
        save_prefs(self.prefs)
        self.dismiss(self.prefs)

    def action_cancel(self) -> None:
        self.dismiss(None)
