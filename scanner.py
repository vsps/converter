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

# Store next to the app so it travels with the project folder
APP_DIR   = Path(__file__).parent
ARGS_FILE = APP_DIR / "converter_args.json"

# Set to True to write raw ffmpeg output to ff_debug_*.txt files next to the
# app for troubleshooting parse failures.  Turn off for normal use.
DEBUG_DUMP = False

# ── Format tables (duplicated here so scanner is self-contained) ──────────────

IMAGE_FORMATS = [
    "avif", "bmp", "exr", "gif", "heic", "ico", "jpeg", "jpg",
    "png", "psd", "svg", "tga", "tiff", "webp",
]
VIDEO_FORMATS = ["avi", "flv", "mkv", "mov", "mp4", "ts", "webm", "wmv"]
AUDIO_FORMATS = ["aac", "aiff", "flac", "m4a", "mp3", "ogg", "opus", "wav"]
ALL_FORMATS   = sorted(IMAGE_FORMATS + VIDEO_FORMATS + AUDIO_FORMATS)

# FFmpeg format → muxer name (for -help muxer=…)
FF_MUXER_MAP = {
    "mp4": "mp4", "mov": "mov", "mkv": "matroska", "avi": "avi",
    "webm": "webm", "flv": "flv", "wmv": "asf", "ts": "mpegts",
    "mp3": "mp3", "aac": "adts", "flac": "flac", "ogg": "ogg",
    "opus": "ogg", "wav": "wav", "aiff": "aiff", "m4a": "ipod",
    "gif": "gif", "webp": "webp", "avif": "avif",
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
    """
    Run a command and return combined stdout+stderr as a string.
    Uses binary capture + explicit UTF-8 decode with fallback to avoid
    Windows ANSI codepage issues (ffmpeg on Windows writes help to stderr
    and the system codepage can silently corrupt text=True decoding).
    """
    try:
        r = subprocess.run(args, capture_output=True, timeout=timeout)
        def _decode(b):
            if not b:
                return ""
            for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
                try:
                    return b.decode(enc)
                except (UnicodeDecodeError, LookupError):
                    continue
            return b.decode("utf-8", errors="replace")
        return _decode(r.stdout) + _decode(r.stderr)
    except Exception:
        return ""

# ── Debug helper ──────────────────────────────────────────────────────────────

def _debug_dump(label, text):
    """If DEBUG_DUMP is on, write raw text to a file for inspection."""
    if not DEBUG_DUMP:
        return
    try:
        safe = re.sub(r'[^\w\-]', '_', label)[:40]
        path = APP_DIR / f"ff_debug_{safe}.txt"
        path.write_text(text, encoding="utf-8")
    except Exception:
        pass

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
    Parse FFmpeg help output → list of {flag, args, desc}.

    Handles multiple layout styles found across -help long, -help muxer=…,
    and -help encoder=… output:

      -flag <type>                  description   ← general options (<> arg)
      -flag  bareword               description   ← bare-word arg (no <>)
        -flag                <type> ..desc..      ← AVOptions (deeper indent)
      -flag                         description   ← no arg token at all
         -flag <type>       E..V..... desc        ← capability columns in desc
      -flag bare word               description   ← multi-word bare arg
      -flag[:<stream_spec>] <type>  description   ← newer ffmpeg (7.x+)

    Newer FFmpeg versions append [:<stream_spec>] or [:<spec>] to per-stream
    flags (e.g. -r[:<stream_spec>] <rate>).  The bracket suffix is stripped
    so the stored flag name is just '-r'.
    """
    # Bracket suffix that newer ffmpeg appends to per-stream flags
    _BRACKET_RE = re.compile(r"\[:[^\]]*\]$")

    entries = []
    for line in text.splitlines():
        # ── primary: flag[suffix]  [<type>]  description ──────────────
        m = re.match(
            r"^\s{0,20}"
            r"(-[\w\-:]+(?:\[:[^\]]*\])?)"   # flag + optional [:<spec>]
            r"\s+"
            r"(<[^>]+>)?"                      # optional <type> token
            r"\s{2,}"                           # gap before description
            r"(.+)$",                           # description
            line,
        )
        if m:
            desc = _CAP_RE.sub("", m.group(3).strip())
            args = _CAP_RE.sub("", (m.group(2) or "").strip())
            flag = _BRACKET_RE.sub("", m.group(1).strip())
            if desc:
                entries.append({"flag": flag, "args": args, "desc": desc})
                continue

        # ── fallback: flag[suffix]  bare-type-token(s)  description ───
        # Handles single-word args (-r rate  set frame rate)
        # and multi-word args (-hwaccel hwaccel name  use HW …)
        m2 = re.match(
            r"^\s{0,20}"
            r"(-[\w\-:]+(?:\[:[^\]]*\])?)"   # flag + optional [:<spec>]
            r"\s+(\S+(?:\s+\S+)*?)"           # bare type token(s), lazy
            r"\s{2,}"                           # gap (2+ spaces)
            r"(.+)$",                           # description
            line,
        )
        if m2:
            desc = _CAP_RE.sub("", m2.group(3).strip())
            args = _CAP_RE.sub("", m2.group(2).strip())
            flag = _BRACKET_RE.sub("", m2.group(1).strip())
            if desc:
                entries.append({"flag": flag, "args": args, "desc": desc})

    return entries


def _dedup_entries(entries):
    """Deduplicate a list of {flag, …} dicts by flag, keeping first."""
    seen, out = set(), []
    for e in entries:
        if e["flag"] not in seen:
            seen.add(e["flag"])
            out.append(e)
    return out

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


def scan_ffmpeg(ff_exe, progress_cb=None):
    """
    Build the complete FFmpeg args DB:
      general   — flags from -help long
      formats   — per-output-format args (muxer options)
    """
    def _cb(msg):
        if progress_cb:
            progress_cb(msg)

    # ── 1. General flags from -help long ──────────────────────────────
    _cb("  Scanning general flags…")
    raw = _run([ff_exe, "-hide_banner", "-help", "long"])
    _debug_dump("help_long", raw)
    general = _parse_ff(raw)
    _cb(f"    → {len(general)} general flags")

    # ── 2. Per-format muxer options ───────────────────────────────────
    _cb("  Scanning muxers…")
    fmt_specific = {}
    for fmt in ALL_FORMATS:
        muxer = FF_MUXER_MAP.get(fmt)
        if not muxer:
            continue
        mux_raw = _run([ff_exe, "-hide_banner", "-help", f"muxer={muxer}"])
        _debug_dump(f"muxer_{muxer}", mux_raw)
        entries = _parse_ff(mux_raw)
        if entries:
            fmt_specific[fmt] = _dedup_entries(entries)

    _cb(f"    → {len(fmt_specific)} format sections")

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
        db["ff"] = scan_ffmpeg(ff_exe, progress_cb=_cb)
        _cb(f"  FF → {len(db['ff']['general'])} general  "
            f"· {len(db['ff']['formats'])} format sections")

    _cb("Done.")
    return db
