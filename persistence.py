"""
persistence.py — user prefs, format tables, and small pure helpers.
"""

import colorsys
import json
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

# All data files live next to the app so the project folder is self-contained
APP_DIR          = Path(__file__).parent
PREFS_FILE       = APP_DIR / "converter_prefs.json"
ARG_HISTORY_FILE = APP_DIR / "converter_arg_history.json"
PRESETS_FILE     = APP_DIR / "converter_presets.json"
PALETTES_FILE    = APP_DIR / "palettes.json"

THEME_COLOR_KEYS = ("bg", "text", "accent", "success", "danger")
THEME_SHIFT_KEYS = ("panel", "panel_hv", "border", "muted")

DERIVED_TOKEN_RULES = {
    "panel": {"hue": 0.00, "sat": -0.04, "lum": 0.08},
    "panel_hv": {"hue": 0.00, "sat": -0.02, "lum": 0.13},
    "border": {"hue": 0.00, "sat": -0.08, "lum": 0.20},
    "muted": {"hue": 0.00, "sat": -0.22, "lum": 0.30},
}
FG_DIM_RULE = {"hue": 0.00, "sat": -0.10, "lum": 0.20}
FG_DIM_AMOUNT = 45

DEFAULT_PALETTES = {
    "default": {
        "label": "Default Lime",
        "colors": {
            "bg": "#0f0f0f",
            "text": "#e0e0e0",
            "accent": "#e8ff47",
            "success": "#47ffb0",
            "danger": "#ff4d4d",
        },
        "shifts": {"panel": 26, "panel_hv": 44, "border": 58, "muted": 72},
    },
    "ocean": {
        "label": "Ocean",
        "colors": {
            "bg": "#101821",
            "text": "#dbe7f3",
            "accent": "#52d6ff",
            "success": "#4ef0b6",
            "danger": "#ff6b6b",
        },
        "shifts": {"panel": 24, "panel_hv": 42, "border": 56, "muted": 70},
    },
    "ember": {
        "label": "Ember",
        "colors": {
            "bg": "#18110f",
            "text": "#f3e2d6",
            "accent": "#ffb347",
            "success": "#79f0b2",
            "danger": "#ff6a5e",
        },
        "shifts": {"panel": 22, "panel_hv": 38, "border": 52, "muted": 66},
    },
    "paper": {
        "label": "Paper",
        "colors": {
            "bg": "#f1eadf",
            "text": "#1d1b17",
            "accent": "#106d5d",
            "success": "#237a57",
            "danger": "#a93434",
        },
        "shifts": {"panel": 18, "panel_hv": 30, "border": 40, "muted": 58},
    },
}

# ── Format tables ─────────────────────────────────────────────────────────────

IMAGE_FORMATS = [
    "avif", "bmp", "exr", "gif", "heic", "ico", "jpeg", "jpg",
    "png", "psd", "svg", "tga", "tiff", "webp",
]
VIDEO_FORMATS = ["avi", "flv", "mkv", "mov", "mp4", "ts", "webm", "wmv"]
AUDIO_FORMATS = ["aac", "aiff", "flac", "m4a", "mp3", "ogg", "opus", "wav"]
ALL_FORMATS   = sorted(IMAGE_FORMATS + VIDEO_FORMATS + AUDIO_FORMATS)

IMAGE_EXTENSIONS = {f".{f}" for f in IMAGE_FORMATS}
VIDEO_EXTENSIONS = {f".{f}" for f in VIDEO_FORMATS}
AUDIO_EXTENSIONS = {f".{f}" for f in AUDIO_FORMATS}
ALL_EXTENSIONS   = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS | AUDIO_EXTENSIONS

# ── Prefs ─────────────────────────────────────────────────────────────────────

def load_prefs():
    if PREFS_FILE.exists():
        try:
            return json.loads(PREFS_FILE.read_text())
        except Exception:
            pass
    return {}

def save_prefs(prefs):
    try:
        PREFS_FILE.write_text(json.dumps(prefs, indent=2))
    except Exception:
        pass

# ── Arg value history ─────────────────────────────────────────────────────────
# Stored separately so a DB rebuild never wipes it.
# Schema: { "flag_values": {"-quality": "85", "-r": "30", ...} }

def load_arg_history():
    if ARG_HISTORY_FILE.exists():
        try:
            return json.loads(ARG_HISTORY_FILE.read_text())
        except Exception:
            pass
    return {"flag_values": {}}

def save_arg_history(history):
    try:
        ARG_HISTORY_FILE.write_text(json.dumps(history, indent=2))
    except Exception:
        pass

def get_last_value(flag):
    """Return the last used value string for a flag, or ''."""
    return load_arg_history().get("flag_values", {}).get(flag, "")

def set_last_value(flag, value):
    """Persist the last used value for a flag."""
    h = load_arg_history()
    h.setdefault("flag_values", {})[flag] = value
    save_arg_history(h)

# ── User presets ─────────────────────────────────────────────────────────
# Schema: [{"name": "hq mp4", "format": "mp4", "args": "-c:v libx264 ..."}, ...]

def load_presets():
    if PRESETS_FILE.exists():
        try:
            return json.loads(PRESETS_FILE.read_text())
        except Exception:
            pass
    return []

def save_presets(presets):
    try:
        PRESETS_FILE.write_text(json.dumps(presets, indent=2))
    except Exception:
        pass


def _clamp(value, low, high):
    return max(low, min(high, value))


def _normalize_hex(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
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
    return text.lower()


def _hex_to_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[index:index + 2], 16) / 255 for index in (0, 2, 4))


def _rgb_to_hex(rgb):
    return "#" + "".join(f"{round(_clamp(channel, 0.0, 1.0) * 255):02x}" for channel in rgb)


def _apply_shift(source_hex, amount, rule):
    scale = _clamp(float(amount), 0.0, 100.0) / 100.0
    red, green, blue = _hex_to_rgb(source_hex)
    hue, light, sat = colorsys.rgb_to_hls(red, green, blue)
    hue = (hue + rule["hue"] * scale) % 1.0
    sat = _clamp(sat + rule["sat"] * scale, 0.0, 1.0)
    light_dir = -1.0 if light > 0.5 else 1.0
    light = _clamp(light + light_dir * abs(rule["lum"]) * scale, 0.0, 1.0)
    return _rgb_to_hex(colorsys.hls_to_rgb(hue, light, sat))


def _sanitize_palette(name, data):
    if not isinstance(data, dict):
        return None
    colors = {}
    raw_colors = data.get("colors", {})
    for key in THEME_COLOR_KEYS:
        color = _normalize_hex(raw_colors.get(key))
        if not color:
            return None
        colors[key] = color
    shifts = {}
    raw_shifts = data.get("shifts", {})
    for key in THEME_SHIFT_KEYS:
        try:
            shifts[key] = int(_clamp(int(raw_shifts.get(key, 0)), 0, 100))
        except Exception:
            return None
    return {
        "label": str(data.get("label", name.replace("_", " ").title())),
        "colors": colors,
        "shifts": shifts,
    }


def load_palettes():
    palettes = {}
    if PALETTES_FILE.exists():
        try:
            payload = json.loads(PALETTES_FILE.read_text())
            if isinstance(payload, dict):
                for name, data in payload.items():
                    palette = _sanitize_palette(name, data)
                    if palette:
                        palettes[name] = palette
        except Exception:
            palettes = {}
    if palettes:
        return palettes
    return {name: _sanitize_palette(name, data) for name, data in DEFAULT_PALETTES.items()}


def resolve_theme_state(prefs):
    palettes = load_palettes()
    palette_name = prefs.get("theme_palette", "default")
    if palette_name not in palettes:
        palette_name = "default" if "default" in palettes else next(iter(palettes))
    palette = palettes[palette_name]

    colors = dict(palette["colors"])
    for key, value in prefs.get("theme_colors", {}).items():
        if key in THEME_COLOR_KEYS:
            normalized = _normalize_hex(value)
            if normalized:
                colors[key] = normalized

    shifts = dict(palette["shifts"])
    for key, value in prefs.get("theme_shifts", {}).items():
        if key in THEME_SHIFT_KEYS:
            try:
                shifts[key] = int(_clamp(int(value), 0, 100))
            except Exception:
                continue

    return {
        "palette_name": palette_name,
        "palette": palette,
        "palettes": palettes,
        "colors": colors,
        "shifts": shifts,
    }


def resolve_theme_tokens(prefs):
    state = resolve_theme_state(prefs)
    colors = state["colors"]
    shifts = state["shifts"]
    return {
        "c-bg": colors["bg"],
        "c-panel": _apply_shift(colors["bg"], shifts["panel"], DERIVED_TOKEN_RULES["panel"]),
        "c-panel-hv": _apply_shift(colors["bg"], shifts["panel_hv"], DERIVED_TOKEN_RULES["panel_hv"]),
        "c-border": _apply_shift(colors["bg"], shifts["border"], DERIVED_TOKEN_RULES["border"]),
        "c-accent": colors["accent"],
        "c-muted": _apply_shift(colors["bg"], shifts["muted"], DERIVED_TOKEN_RULES["muted"]),
        "c-fg": colors["text"],
        "c-fg-dim": _apply_shift(colors["text"], FG_DIM_AMOUNT, FG_DIM_RULE),
        "c-danger": colors["danger"],
        "c-success": colors["success"],
    }


# ── Format helpers ────────────────────────────────────────────────────────────

def format_badge(fmt):
    if fmt in IMAGE_FORMATS: return "🖼 image"
    if fmt in VIDEO_FORMATS: return "🎬 video"
    if fmt in AUDIO_FORMATS: return "🎵 audio"
    return ""
