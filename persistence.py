"""
persistence.py — user prefs, format tables, and small pure helpers.
"""

import json
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

# All data files live next to the app so the project folder is self-contained
APP_DIR          = Path(__file__).parent
PREFS_FILE       = APP_DIR / "converter_prefs.json"
ARG_HISTORY_FILE = APP_DIR / "converter_arg_history.json"

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

# ── Format helpers ────────────────────────────────────────────────────────────

def format_badge(fmt):
    if fmt in IMAGE_FORMATS: return "🖼 image"
    if fmt in VIDEO_FORMATS: return "🎬 video"
    if fmt in AUDIO_FORMATS: return "🎵 audio"
    return ""
