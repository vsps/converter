"""
scanner.py — probe tools, parse their help output, build & persist the args DB.

Public API:
    probe_tool(exe)              → (ok: bool, version_line: str)
    build_args_db(im, ff, cb)    → dict
    load_args_db()               → dict
    save_args_db(db)
"""

import re
import subprocess
import json
from pathlib import Path
from datetime import datetime

# ── Paths ────────────────────────────────────────────────────────────────────

ARGS_FILE = Path.home() / ".converter_args.json"

# ── Format tables (duplicated here so scanner is self-contained) ──────────────

IMAGE_FORMATS = [
    "avif", "bmp", "exr", "gif", "heic", "ico", "jpeg", "jpg",
    "png", "psd", "svg", "tga", "tiff", "webp",
]
VIDEO_FORMATS = ["avi", "flv", "mkv", "mov", "mp4", "ts", "webm", "wmv"]
AUDIO_FORMATS = ["aac", "aiff", "flac", "m4a", "mp3", "ogg", "opus", "wav"]
ALL_FORMATS   = sorted(IMAGE_FORMATS + VIDEO_FORMATS + AUDIO_FORMATS)

# FFmpeg format → muxer/encoder mappings
FF_FORMAT_MAP = {
    "mp4":  {"muxer": "mp4",      "encoder": None},
    "mov":  {"muxer": "mov",      "encoder": None},
    "mkv":  {"muxer": "matroska", "encoder": None},
    "avi":  {"muxer": "avi",      "encoder": None},
    "webm": {"muxer": "webm",     "encoder": None},
    "flv":  {"muxer": "flv",      "encoder": None},
    "wmv":  {"muxer": "asf",      "encoder": None},
    "ts":   {"muxer": "mpegts",   "encoder": None},
    "mp3":  {"muxer": "mp3",      "encoder": "libmp3lame"},
    "aac":  {"muxer": "adts",     "encoder": "aac"},
    "flac": {"muxer": "flac",     "encoder": "flac"},
    "ogg":  {"muxer": "ogg",      "encoder": "libvorbis"},
    "opus": {"muxer": "ogg",      "encoder": "libopus"},
    "wav":  {"muxer": "wav",      "encoder": "pcm_s16le"},
    "aiff": {"muxer": "aiff",     "encoder": None},
    "m4a":  {"muxer": "ipod",     "encoder": "aac"},
    "gif":  {"muxer": "gif",      "encoder": "gif"},
    "webp": {"muxer": "webp",     "encoder": "libwebp"},
    "avif": {"muxer": "avif",     "encoder": None},
    "png":  {"muxer": None,       "encoder": "png"},
    "tiff": {"muxer": None,       "encoder": "tiff"},
    "jpeg": {"muxer": None,       "encoder": "mjpeg"},
    "jpg":  {"muxer": None,       "encoder": "mjpeg"},
    "bmp":  {"muxer": None,       "encoder": "bmp"},
}

# ── Persistence ───────────────────────────────────────────────────────────────

def load_args_db():
    if ARGS_FILE.exists():
        try:
            return json.loads(ARGS_FILE.read_text())
        except Exception:
            pass
    return {}

def save_args_db(db):
    try:
        ARGS_FILE.write_text(json.dumps(db, indent=2))
    except Exception:
        pass

# ── Tool probe ────────────────────────────────────────────────────────────────

def probe_tool(exe_path):
    """Returns (ok: bool, first_version_line: str)."""
    if not exe_path:
        return False, "not set"
    try:
        r = subprocess.run([exe_path, "-version"],
                           capture_output=True, text=True, timeout=6)
        lines = (r.stdout or r.stderr or "").strip().splitlines()
        return True, (lines[0] if lines else "ok")
    except FileNotFoundError:
        return False, "not found"
    except subprocess.TimeoutExpired:
        return False, "timed out"
    except Exception as e:
        return False, str(e)

# ── Raw command runner ────────────────────────────────────────────────────────

def _run(args, timeout=15):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")
    except Exception:
        return ""

# ── Parsers ───────────────────────────────────────────────────────────────────

_CAP_RE = re.compile(r"^[EDA.]{8,}\s+")

def _parse_im(text):
    """
    Parse ImageMagick -help → list of {flag, args, desc}.
    Continuation lines (deep indent, no leading -) are merged into the
    previous entry.
    """
    entries = []
    merged  = []
    for line in text.splitlines():
        if (merged and line
                and not line.lstrip().startswith("-")
                and len(line) - len(line.lstrip()) > 10):
            merged[-1] += " " + line.strip()
        else:
            merged.append(line)

    for line in merged:
        m = re.match(r"^\s{1,4}(-[\w\-]+(?:\s+\S+)?)\s{2,}(.+)$", line)
        if m:
            parts = m.group(1).strip().split(None, 1)
            entries.append({
                "flag": parts[0],
                "args": parts[1] if len(parts) > 1 else "",
                "desc": m.group(2).strip(),
            })
    return entries


def _parse_ff(text):
    """
    Parse FFmpeg -help[-style] output → list of {flag, args, desc}.
    Strips capability-flag columns (E.......... etc).
    """
    entries = []
    for line in text.splitlines():
        m = re.match(r"^\s{0,4}(-[\w\-:]+)\s+(<[^>]+>|\S+)?\s{2,}(.+)$", line)
        if m:
            entries.append({
                "flag": m.group(1).strip(),
                "args": _CAP_RE.sub("", (m.group(2) or "").strip()),
                "desc": _CAP_RE.sub("", m.group(3).strip()),
            })
    return entries

# ── Scanners ──────────────────────────────────────────────────────────────────

def scan_imagemagick(im_exe):
    general = _parse_im(_run([im_exe, "-help"]))
    fmt_specific = {}
    for fmt in IMAGE_FORMATS:
        matches = [e for e in general
                   if fmt.lower() in e["desc"].lower()
                   or fmt.upper() in e["desc"]
                   or e["flag"] == "-define"]
        if matches:
            fmt_specific[fmt] = matches
    return {"general": general, "formats": fmt_specific}


def scan_ffmpeg(ff_exe):
    general      = _parse_ff(_run([ff_exe, "-hide_banner", "-help"]))
    fmt_specific = {}

    for fmt in ALL_FORMATS:
        mapping = FF_FORMAT_MAP.get(fmt, {})
        muxer   = mapping.get("muxer")
        encoder = mapping.get("encoder")
        entries = []

        if muxer:
            entries += _parse_ff(_run([ff_exe, "-hide_banner", "-help", f"muxer={muxer}"]))
        if encoder:
            entries += _parse_ff(_run([ff_exe, "-hide_banner", "-help", f"encoder={encoder}"]))

        # Deduplicate by flag (preserve first occurrence)
        seen, deduped = set(), []
        for e in entries:
            if e["flag"] not in seen:
                seen.add(e["flag"])
                deduped.append(e)

        if deduped:
            fmt_specific[fmt] = deduped

    return {"general": general, "formats": fmt_specific}


def build_args_db(im_exe, ff_exe, progress_cb=None):
    """
    Scan both tools, return the complete args DB dict.
    progress_cb(msg: str) is called with human-readable status lines.
    """
    def _cb(msg):
        if progress_cb:
            progress_cb(msg)

    db = {"scanned_at": datetime.now().isoformat()}

    if im_exe and probe_tool(im_exe)[0]:
        _cb("Scanning ImageMagick…")
        db["im"] = scan_imagemagick(im_exe)
        _cb(f"  IM → {len(db['im']['general'])} general  "
            f"· {len(db['im']['formats'])} format sections")

    if ff_exe and probe_tool(ff_exe)[0]:
        _cb("Scanning FFmpeg…")
        db["ff"] = scan_ffmpeg(ff_exe)
        _cb(f"  FF → {len(db['ff']['general'])} general  "
            f"· {len(db['ff']['formats'])} format sections")

    _cb("Done.")
    return db
