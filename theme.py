"""
theme.py — colours, fonts, ttk style setup, shared widget factories.

Usage:
    from theme import Theme
    th = Theme(root)          # call once on the Tk root
    th.apply_ttk_styles()
    btn = th.button(parent, "click me", callback)
"""

import tkinter as tk
from tkinter import ttk


# ── Palette & fonts ──────────────────────────────────────────────────────────

BG      = "#0f0f0f"
PANEL   = "#1a1a1a"
PANEL_HV= "#252525"   # hover state for panel rows
BORDER  = "#2a2a2a"
ACCENT  = "#e8ff47"
MUTED   = "#555555"
FG      = "#e0e0e0"
FG_DIM  = "#888888"
DANGER  = "#ff4d4d"
SUCCESS = "#47ffb0"

FONT_MONO  = ("Courier New", 10)
FONT_UI    = ("Courier New", 11)
FONT_LABEL = ("Courier New", 9)
FONT_SMALL = ("Courier New", 8)
FONT_BIG   = ("Courier New", 14, "bold")
FONT_BOLD  = ("Courier New", 9, "bold")


# ── TTK style setup ──────────────────────────────────────────────────────────

def apply_ttk_styles(widget):
    """Apply dark theme to all ttk widgets. Call once on any widget."""
    s = ttk.Style(widget)
    s.theme_use("clam")

    s.configure("TCombobox",
        fieldbackground=PANEL, background=PANEL,
        foreground=FG, selectbackground=BORDER,
        selectforeground=ACCENT, bordercolor=BORDER,
        arrowcolor=ACCENT, font=FONT_UI)
    s.map("TCombobox",
        fieldbackground=[("readonly", PANEL)],
        foreground=[("readonly", FG)])

    s.configure("Vertical.TScrollbar",
        troughcolor=PANEL, background=MUTED,
        bordercolor=BORDER, arrowcolor=FG_DIM)
    s.configure("Horizontal.TScrollbar",
        troughcolor=PANEL, background=MUTED,
        bordercolor=BORDER, arrowcolor=FG_DIM)

    s.configure("TProgressbar",
        troughcolor=PANEL, background=ACCENT, bordercolor=BORDER)

    s.configure("Dark.TNotebook",
        background=BG, bordercolor=BORDER, tabmargins=0)
    s.configure("Dark.TNotebook.Tab",
        background=PANEL, foreground=FG_DIM,
        font=FONT_LABEL, padding=[12, 6])
    s.map("Dark.TNotebook.Tab",
        background=[("selected", BG)],
        foreground=[("selected", ACCENT)])


# ── Widget factories ─────────────────────────────────────────────────────────

def panel(parent, **kw):
    """Bordered panel frame."""
    defaults = dict(bg=PANEL, highlightthickness=1,
                    highlightbackground=BORDER, pady=12, padx=14)
    defaults.update(kw)
    return tk.Frame(parent, **defaults)


def sep(parent, **kw):
    """1px horizontal separator."""
    defaults = dict(height=1, bg=BORDER)
    defaults.update(kw)
    return tk.Frame(parent, **defaults)


def label(parent, text, style="normal", **kw):
    """Themed label. style: 'normal'|'muted'|'accent'|'dim'|'small'|'big'."""
    fonts  = {"normal": FONT_LABEL, "muted": FONT_LABEL, "small": FONT_SMALL,
              "big": FONT_BIG, "accent": FONT_LABEL, "dim": FONT_LABEL}
    colors = {"normal": FG, "muted": MUTED, "accent": ACCENT,
              "dim": FG_DIM, "small": MUTED, "big": ACCENT}
    defaults = dict(bg=BG, fg=colors.get(style, FG),
                    font=fonts.get(style, FONT_LABEL), text=text)
    defaults.update(kw)
    return tk.Label(parent, **defaults)


def button(parent, text, cmd, style="normal", padx=16, pady=8, **kw):
    """
    Themed button.
    style: 'primary' (accent bg), 'normal' (border bg), 'ghost' (bg bg).
    """
    bgs = {"primary": ACCENT, "normal": BORDER, "ghost": BG}
    fgs = {"primary": BG,     "normal": FG,     "ghost": FG_DIM}
    bg  = bgs.get(style, BORDER)
    fg  = fgs.get(style, FG)
    defaults = dict(text=text, command=cmd, font=FONT_LABEL,
                    bg=bg, fg=fg,
                    activebackground=ACCENT, activeforeground=BG,
                    relief="flat", bd=0, padx=padx, pady=pady, cursor="hand2")
    defaults.update(kw)
    return tk.Button(parent, **defaults)


def entry(parent, textvariable, **kw):
    """Themed single-line entry."""
    defaults = dict(textvariable=textvariable, font=FONT_MONO,
                    bg=BG, fg=FG, insertbackground=ACCENT,
                    relief="flat", highlightthickness=1,
                    highlightbackground=BORDER)
    defaults.update(kw)
    return tk.Entry(parent, **defaults)


def scrolled_text(parent, **kw):
    """
    Text widget + vertical scrollbar packed into parent.
    Returns (text_widget, vert_scrollbar, horiz_scrollbar).
    """
    defaults = dict(font=FONT_MONO, bg=PANEL, fg=FG,
                    insertbackground=ACCENT, relief="flat",
                    padx=10, pady=6, wrap="none", state="disabled")
    defaults.update(kw)
    txt  = tk.Text(parent, **defaults)
    sb_v = ttk.Scrollbar(parent, orient="vertical",   command=txt.yview)
    sb_h = ttk.Scrollbar(parent, orient="horizontal",  command=txt.xview)
    txt.configure(yscrollcommand=sb_v.set, xscrollcommand=sb_h.set)
    sb_v.pack(side="right",  fill="y")
    sb_h.pack(side="bottom", fill="x")
    txt.pack(fill="both", expand=True)
    return txt, sb_v, sb_h


def scrolled_canvas(parent):
    """
    Canvas + vertical scrollbar for scrollable list panels.
    Returns (canvas, inner_frame).
    """
    canvas = tk.Canvas(parent, bg=BG, highlightthickness=0)
    sb     = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    inner  = tk.Frame(canvas, bg=BG)
    win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

    def _on_canvas_resize(e):
        canvas.itemconfig(win_id, width=e.width)
    def _on_inner_resize(e):
        canvas.configure(scrollregion=canvas.bbox("all"))
    def _on_scroll(e):
        canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

    canvas.bind("<Configure>", _on_canvas_resize)
    inner.bind("<Configure>", _on_inner_resize)
    canvas.bind_all("<MouseWheel>", _on_scroll)

    return canvas, inner


def checkbox(parent, text, variable, **kw):
    """Themed checkbutton."""
    defaults = dict(variable=variable, text=text, font=FONT_LABEL,
                    bg=PANEL, fg=FG, activebackground=PANEL,
                    activeforeground=ACCENT, selectcolor=BG,
                    relief="flat", bd=0, highlightthickness=0)
    defaults.update(kw)
    return tk.Checkbutton(parent, **defaults)


def section_header(parent, text):
    """Accent label + horizontal rule for section titles in list panels."""
    f = tk.Frame(parent, bg=BG)
    f.pack(fill="x", padx=16, pady=(14, 4))
    tk.Label(f, text=text, font=FONT_LABEL, bg=BG, fg=ACCENT).pack(side="left")
    sep(f, bg=BORDER).pack(side="left", fill="x", expand=True, padx=(8, 0))


def center_window(win, relative_to):
    """Centre a Toplevel relative to another window."""
    win.update_idletasks()
    px, py = relative_to.winfo_x(), relative_to.winfo_y()
    pw, ph = relative_to.winfo_width(), relative_to.winfo_height()
    w,  h  = win.winfo_width(), win.winfo_height()
    win.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 2}")
