"""
MemEd — Memory Editor
Main GUI application using tkinter. Linux-compatible version.
"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import threading
import os
import sys

from memory_engine import (
    MemoryEngine, list_processes, VALUE_TYPES,
    SCAN_LABELS, FIRST_SCAN_MODES, NEXT_SCAN_MODES,
    NEEDS_VALUE1, NEEDS_VALUE2,
    SCAN_EXACT, SCAN_UNKNOWN,
)
from freeze_manager import FreezeManager
from stealth import get_stealth_status, hide_window
from address_file import save as af_save, load as af_load, SavedEntry, FILE_FILTER, FILE_EXT

# ── Palette ────────────────────────────────────────────────────────────────
BG          = "#0f0f17"
SURFACE     = "#16161f"
SURFACE2    = "#1e1e2a"
BORDER      = "#2a2a3a"
INPUT_BG    = "#1a1a26"

BLUE        = "#5b9cf6"
BLUE_DIM    = "#3a5fa0"
GREEN       = "#4ec994"
ORANGE      = "#e8934a"
RED         = "#e05c6a"
YELLOW      = "#d4c06a"

TEXT        = "#d4d4dc"
TEXT_DIM    = "#5a5a72"
TEXT_BRIGHT = "#ffffff"

SEL_BG      = "#252535"

# ── Typography — prefer cross-platform fonts, fall back to Segoe UI ────────
def _pick_font(candidates: list[str], size: int, weight: str = "normal") -> tuple:
    """Return the first available font family from candidates."""
    try:
        import tkinter.font as tkfont
        available = set(tkfont.families())
        for name in candidates:
            if name in available:
                return (name, size, weight) if weight != "normal" else (name, size)
    except Exception:
        pass
    return (candidates[-1], size, weight) if weight != "normal" else (candidates[-1], size)


_UI_FAMILY   = ["Ubuntu", "DejaVu Sans", "Noto Sans", "Liberation Sans",
                "Segoe UI", "Helvetica", "Arial"]
_MONO_FAMILY = ["DejaVu Sans Mono", "Ubuntu Mono", "Liberation Mono",
                "Noto Mono", "Courier New", "Consolas", "Courier"]

UI_FONT    = _pick_font(_UI_FAMILY,   10)
UI_BOLD    = _pick_font(_UI_FAMILY,   10, "bold")
UI_SMALL   = _pick_font(_UI_FAMILY,    9)
UI_TITLE   = _pick_font(_UI_FAMILY,   11, "bold")
MONO       = _pick_font(_MONO_FAMILY, 10)
MONO_SMALL = _pick_font(_MONO_FAMILY,  9)

ALIGNMENTS = {"1 byte": 1, "2 bytes": 2, "4 bytes": 4, "8 bytes": 8}


# ── Helpers ────────────────────────────────────────────────────────────────

def _btn(parent, text, cmd, kind="default", **kw):
    styles = {
        "primary":   dict(bg=BLUE,    fg=TEXT_BRIGHT, activebackground=BLUE_DIM,   activeforeground=TEXT_BRIGHT),
        "success":   dict(bg=GREEN,   fg=BG,          activebackground="#3aaa7a",   activeforeground=BG),
        "danger":    dict(bg=RED,     fg=TEXT_BRIGHT, activebackground="#c04050",   activeforeground=TEXT_BRIGHT),
        "default":   dict(bg=SURFACE2, fg=TEXT,       activebackground=BORDER,      activeforeground=TEXT),
        "ghost":     dict(bg=SURFACE,  fg=TEXT_DIM,   activebackground=SURFACE2,    activeforeground=TEXT),
        "orange":    dict(bg=ORANGE,   fg=BG,         activebackground="#c07030",   activeforeground=BG),
    }
    s = styles.get(kind, styles["default"])
    font = kw.pop("font", UI_BOLD if kind == "primary" else UI_FONT)
    return tk.Button(parent, text=text, command=cmd,
                     font=font, bd=0, relief=tk.FLAT, cursor="hand2",
                     padx=kw.pop("padx", 12), pady=kw.pop("pady", 5),
                     **s, **kw)


def _label(parent, text, dim=False, bold=False, mono=False, **kw):
    font = MONO if mono else (UI_BOLD if bold else (UI_SMALL if dim else UI_FONT))
    fg   = kw.pop("fg", TEXT_DIM if dim else TEXT)
    return tk.Label(parent, text=text, font=font, fg=fg,
                    bg=kw.pop("bg", parent.cget("bg")), **kw)


def _sep(parent, color=BORDER, pad=6):
    tk.Frame(parent, bg=color, height=1).pack(fill=tk.X, pady=pad)


def _section(parent, title):
    f = tk.Frame(parent, bg=SURFACE)
    f.pack(fill=tk.X, pady=(10, 4))
    tk.Frame(f, bg=BLUE, width=3).pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))
    tk.Label(f, text=title.upper(), font=UI_SMALL, fg=BLUE,
             bg=SURFACE).pack(side=tk.LEFT, anchor=tk.W)
    return f


def _apply_styles():
    s = ttk.Style()
    s.theme_use("clam")

    s.configure("Treeview",
                background=SURFACE2, foreground=TEXT,
                fieldbackground=SURFACE2, rowheight=24,
                font=MONO_SMALL, borderwidth=0)
    s.configure("Treeview.Heading",
                background=SURFACE, foreground=TEXT_DIM,
                font=UI_SMALL, relief=tk.FLAT, borderwidth=0)
    s.map("Treeview",
          background=[("selected", SEL_BG)],
          foreground=[("selected", TEXT_BRIGHT)])
    s.map("Treeview.Heading",
          background=[("active", BORDER)])

    s.configure("TCombobox",
                fieldbackground=INPUT_BG, background=INPUT_BG,
                foreground=TEXT, selectbackground=SEL_BG,
                selectforeground=TEXT, arrowcolor=TEXT_DIM,
                bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
    s.map("TCombobox",
          fieldbackground=[("readonly", INPUT_BG)],
          foreground=[("readonly", TEXT)],
          selectbackground=[("readonly", SEL_BG)],
          arrowcolor=[("disabled", TEXT_DIM)])

    s.configure("Vertical.TScrollbar",
                background=SURFACE, troughcolor=SURFACE2,
                arrowcolor=TEXT_DIM, bordercolor=SURFACE, darkcolor=SURFACE,
                lightcolor=SURFACE, relief=tk.FLAT)
    s.map("Vertical.TScrollbar",
          background=[("active", BORDER)])

    s.configure("TProgressbar",
                troughcolor=SURFACE2, background=BLUE,
                bordercolor=SURFACE2, lightcolor=BLUE, darkcolor=BLUE)

    s.configure("TScale",
                background=SURFACE, troughcolor=INPUT_BG,
                sliderlength=14, sliderrelief=tk.FLAT)


def _entry(parent, var, **kw):
    return tk.Entry(parent, textvariable=var,
                    bg=INPUT_BG, fg=TEXT, insertbackground=TEXT,
                    relief=tk.FLAT, bd=0, font=MONO,
                    highlightthickness=1, highlightbackground=BORDER,
                    highlightcolor=BLUE, **kw)


def _combobox(parent, var, values, **kw):
    return ttk.Combobox(parent, textvariable=var, values=values,
                        state="readonly", font=UI_FONT, **kw)


# ── Process dialog ─────────────────────────────────────────────────────────

class ProcessDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Attach to Process")
        self.configure(bg=BG)
        self.geometry("560x540")
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()
        self.selected_pid: int | None = None
        self.selected_name: str | None = None
        self._build()
        self._load()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _build(self):
        hdr = tk.Frame(self, bg=SURFACE, pady=12, padx=16)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="Select Process", font=UI_TITLE,
                 fg=TEXT_BRIGHT, bg=SURFACE).pack(side=tk.LEFT)
        _btn(hdr, "Refresh", self._load, kind="ghost",
             font=UI_SMALL, padx=8, pady=3).pack(side=tk.RIGHT)

        sf = tk.Frame(self, bg=BG, padx=12, pady=8)
        sf.pack(fill=tk.X)
        _label(sf, "Search", dim=True).pack(anchor=tk.W)
        self._filter_var = tk.StringVar()
        self._filter_var.trace_add("write", lambda *_: self._apply_filter())
        _entry(sf, self._filter_var).pack(fill=tk.X, pady=(2, 0))

        tf = tk.Frame(self, bg=BG, padx=12)
        tf.pack(fill=tk.BOTH, expand=True)
        cols = ("PID", "Name")
        self._tree = ttk.Treeview(tf, columns=cols, show="headings",
                                   selectmode="browse")
        self._tree.heading("PID",  text="PID")
        self._tree.heading("Name", text="Process Name")
        self._tree.column("PID",  width=72,  anchor=tk.CENTER)
        self._tree.column("Name", width=420, anchor=tk.W)
        sb = ttk.Scrollbar(tf, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.bind("<Double-1>", lambda _: self._confirm())

        ft = tk.Frame(self, bg=SURFACE, pady=10, padx=12)
        ft.pack(fill=tk.X)
        _btn(ft, "Attach", self._confirm, kind="primary").pack(side=tk.RIGHT, padx=(4, 0))
        _btn(ft, "Cancel", self.destroy,  kind="ghost").pack(side=tk.RIGHT)

    def _load(self):
        self._processes = list_processes()
        self._apply_filter()

    def _apply_filter(self):
        q = self._filter_var.get().lower()
        self._tree.delete(*self._tree.get_children())
        for p in self._processes:
            if q in p.name.lower() or q in str(p.pid):
                self._tree.insert("", tk.END, iid=str(p.pid),
                                  values=(p.pid, p.name))

    def _confirm(self):
        sel = self._tree.selection()
        if not sel:
            return
        pid = int(sel[0])
        for p in self._processes:
            if p.pid == pid:
                self.selected_pid  = pid
                self.selected_name = p.name
                break
        self.destroy()


# ── Address row ────────────────────────────────────────────────────────────

class AddressRow:
    def __init__(self, address: int, value, vtype: str):
        self.address     = address
        self.value       = value
        self.prev_value  = value
        self.vtype       = vtype
        self.frozen      = False
        self.description = ""


# ── Main window ────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MemEd")
        self.geometry("1100x720")
        self.minsize(820, 560)
        self.configure(bg=BG)

        self._engine  = MemoryEngine()
        self._freezer = FreezeManager(
            self._engine, interval=0.25,
            on_auto_disable=self._on_freeze_auto_disabled)
        self._address_rows: list[AddressRow] = []
        self._scan_thread: threading.Thread | None = None

        self._current_vtype   = tk.StringVar(value="Int32")
        self._scan_mode_var   = tk.StringVar(value=SCAN_LABELS[SCAN_EXACT])
        self._alignment_var   = tk.StringVar(value="4 bytes")
        self._safe_mode_var   = tk.BooleanVar(value=True)
        self._verify_var      = tk.BooleanVar(value=True)
        self._current_proc_name: str | None = None
        self._last_save_path:   str | None = None
        self._paused = False

        _apply_styles()
        self._build_menu()
        self._build_ui()
        self._start_refresh_loop()
        self._scan_mode_var.trace_add("write", lambda *_: self._on_mode_change())

        self.bind_all("<F12>",       lambda _: self._emergency_unfreeze())
        self.bind_all("<F11>",       lambda _: self._emergency_pause_toggle())
        self.bind_all("<Control-s>", lambda _: self._save_address_list())
        self.bind_all("<Control-o>", lambda _: self._load_address_list())

    # ── Menu ───────────────────────────────────────────────────────────────

    def _build_menu(self):
        style = dict(bg=SURFACE, fg=TEXT,
                     activebackground=BLUE, activeforeground=TEXT_BRIGHT, bd=0)
        mb = tk.Menu(self, **style)
        self.config(menu=mb)

        def _menu(**kw):
            return tk.Menu(mb, tearoff=0, **style, **kw)

        fm = _menu()
        fm.add_command(label="Save Address List  Ctrl+S", command=self._save_address_list)
        fm.add_command(label="Load Address List  Ctrl+O", command=self._load_address_list)
        fm.add_separator()
        fm.add_command(label="Clear Address Table", command=self._clear_address_table)
        mb.add_cascade(label="File", menu=fm)

        pm = _menu()
        pm.add_command(label="Open Process...", command=self._open_process)
        pm.add_command(label="Detach",          command=self._detach)
        mb.add_cascade(label="Process", menu=pm)

        sm = _menu()
        sm.add_command(label="New Scan",   command=self._new_scan)
        sm.add_command(label="Next Scan",  command=self._next_scan)
        sm.add_separator()
        sm.add_command(label="Reset Scan", command=self._reset_scan)
        mb.add_cascade(label="Scan", menu=sm)

        frm = _menu()
        frm.add_command(label="Freeze Settings...",            command=self._open_freeze_settings)
        frm.add_separator()
        frm.add_command(label="Emergency Unfreeze All  F12",   command=self._emergency_unfreeze)
        frm.add_command(label="Pause / Resume Freeze   F11",   command=self._emergency_pause_toggle)
        mb.add_cascade(label="Freeze", menu=frm)

        hm = _menu()
        hm.add_command(label="About", command=self._show_about)
        mb.add_cascade(label="Help", menu=hm)

    # ── Layout ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_titlebar()

        body = tk.PanedWindow(self, orient=tk.HORIZONTAL, bg=BG,
                               sashwidth=1, sashrelief=tk.FLAT,
                               sashpad=0, bd=0)
        body.pack(fill=tk.BOTH, expand=True)

        sidebar = tk.Frame(body, bg=SURFACE, width=260)
        body.add(sidebar, minsize=220, width=260)
        self._build_sidebar(sidebar)

        right = tk.Frame(body, bg=BG)
        body.add(right, minsize=500)
        self._build_right(right)

        self._build_statusbar()

    def _build_titlebar(self):
        bar = tk.Frame(self, bg=SURFACE, height=46)
        bar.pack(fill=tk.X)
        bar.pack_propagate(False)

        left = tk.Frame(bar, bg=SURFACE)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=14)
        tk.Label(left, text="MEM", font=_pick_font(_UI_FAMILY, 12, "bold"),
                 fg=BLUE, bg=SURFACE).pack(side=tk.LEFT, pady=12)
        tk.Label(left, text="ED", font=_pick_font(_UI_FAMILY, 12, "bold"),
                 fg=TEXT, bg=SURFACE).pack(side=tk.LEFT)

        tk.Frame(bar, bg=BORDER, width=1).pack(side=tk.LEFT, fill=tk.Y, padx=12, pady=8)

        self._proc_label = tk.Label(bar, text="No process attached",
                                     font=UI_FONT, fg=TEXT_DIM, bg=SURFACE)
        self._proc_label.pack(side=tk.LEFT, pady=14)

        right = tk.Frame(bar, bg=SURFACE)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=10)

        tk.Frame(right, bg=BORDER, width=1).pack(side=tk.RIGHT, fill=tk.Y, pady=8, padx=4)
        _btn(right, "Detach", self._detach, kind="ghost",
             font=UI_SMALL, padx=10, pady=4).pack(side=tk.RIGHT, padx=2, pady=10)
        _btn(right, "+ Open Process", self._open_process, kind="primary",
             font=UI_SMALL, padx=10, pady=4).pack(side=tk.RIGHT, padx=2, pady=10)

    def _build_statusbar(self):
        bar = tk.Frame(self, bg=SURFACE, height=26)
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        bar.pack_propagate(False)

        self._freeze_status_var = tk.StringVar(value="")
        tk.Label(bar, textvariable=self._freeze_status_var,
                 font=UI_SMALL, fg=ORANGE, bg=SURFACE).pack(side=tk.RIGHT, padx=12)

        self._status_var = tk.StringVar(value="Ready")
        tk.Label(bar, textvariable=self._status_var,
                 font=UI_SMALL, fg=TEXT_DIM, bg=SURFACE).pack(side=tk.LEFT, padx=12)

        self._progress = ttk.Progressbar(bar, mode="determinate",
                                          maximum=100, length=140)
        self._progress.pack(side=tk.RIGHT, padx=(0, 16), pady=5)

        self._scan_info_var = tk.StringVar(value="")
        tk.Label(bar, textvariable=self._scan_info_var,
                 font=UI_SMALL, fg=TEXT_DIM, bg=SURFACE).pack(side=tk.RIGHT, padx=12)

    # ── Sidebar ────────────────────────────────────────────────────────────

    def _build_sidebar(self, parent):
        canvas = tk.Canvas(parent, bg=SURFACE, bd=0, highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = tk.Frame(canvas, bg=SURFACE)
        win = canvas.create_window((0, 0), window=inner, anchor=tk.NW)

        def _resize(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(win, width=canvas.winfo_width())
        inner.bind("<Configure>", _resize)
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))

        p = inner
        p.configure(padx=14)

        _section(p, "Scan")

        _label(p, "Value Type", dim=True).pack(anchor=tk.W, pady=(0, 2))
        _combobox(p, self._current_vtype, list(VALUE_TYPES.keys())
                  ).pack(fill=tk.X, pady=(0, 8))

        _label(p, "Comparison", dim=True).pack(anchor=tk.W, pady=(0, 2))
        self._label_to_mode = {v: k for k, v in SCAN_LABELS.items()}
        self._mode_cb = _combobox(
            p, self._scan_mode_var,
            [SCAN_LABELS[m] for m in FIRST_SCAN_MODES])
        self._mode_cb.pack(fill=tk.X, pady=(0, 8))
        self._scan_mode_var.set(SCAN_LABELS[SCAN_EXACT])

        self._val1_frame = tk.Frame(p, bg=SURFACE)
        _label(self._val1_frame, "Value", dim=True).pack(anchor=tk.W, pady=(0, 2))
        self._scan_val1_var = tk.StringVar()
        self._val1_entry = _entry(self._val1_frame, self._scan_val1_var)
        self._val1_entry.pack(fill=tk.X)
        self._val1_entry.bind("<Return>", lambda _: self._smart_scan())
        self._val1_frame.pack(fill=tk.X, pady=(0, 6))

        self._val2_frame = tk.Frame(p, bg=SURFACE)
        _label(self._val2_frame, "Value 2", dim=True).pack(anchor=tk.W, pady=(0, 2))
        self._scan_val2_var = tk.StringVar()
        _entry(self._val2_frame, self._scan_val2_var).pack(fill=tk.X)

        _label(p, "Alignment", dim=True).pack(anchor=tk.W, pady=(0, 2))
        _combobox(p, self._alignment_var, list(ALIGNMENTS.keys())
                  ).pack(fill=tk.X, pady=(0, 10))

        scan_btns = tk.Frame(p, bg=SURFACE)
        scan_btns.pack(fill=tk.X, pady=(0, 4))
        self._btn_new = _btn(scan_btns, "New Scan", self._new_scan, kind="primary",
                              padx=0, pady=7)
        self._btn_new.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))
        self._btn_next = _btn(scan_btns, "Next Scan", self._next_scan, kind="success",
                               padx=0, pady=7, state=tk.DISABLED)
        self._btn_next.config(disabledforeground=TEXT_DIM)
        self._btn_next.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(3, 0))

        cancel_reset = tk.Frame(p, bg=SURFACE)
        cancel_reset.pack(fill=tk.X, pady=(0, 4))
        self._btn_cancel = _btn(cancel_reset, "Cancel", self._cancel_scan,
                                 kind="ghost", font=UI_SMALL, padx=0, pady=4,
                                 state=tk.DISABLED)
        self._btn_cancel.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))
        _btn(cancel_reset, "Reset", self._reset_scan,
             kind="ghost", font=UI_SMALL, padx=0, pady=4
             ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(3, 0))

        _sep(p)
        _section(p, "Freeze")

        freeze_btns = tk.Frame(p, bg=SURFACE)
        freeze_btns.pack(fill=tk.X, pady=(0, 4))
        _btn(freeze_btns, "Freeze All", self._toggle_freeze_all,
             kind="orange", font=UI_SMALL, padx=0, pady=5
             ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))
        _btn(freeze_btns, "Unfreeze All", self._emergency_unfreeze,
             kind="ghost", font=UI_SMALL, padx=0, pady=5
             ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(3, 0))

        ks_btns = tk.Frame(p, bg=SURFACE)
        ks_btns.pack(fill=tk.X, pady=(0, 4))
        self._pause_btn = _btn(ks_btns, "Pause  [F11]",
                                self._emergency_pause_toggle,
                                kind="ghost", font=UI_SMALL, padx=0, pady=4)
        self._pause_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))
        _btn(ks_btns, "Settings", self._open_freeze_settings,
             kind="ghost", font=UI_SMALL, padx=0, pady=4
             ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(3, 0))

        _sep(p)
        _section(p, "Tools")

        _btn(p, "Save Address List  Ctrl+S", self._save_address_list,
             kind="ghost", font=UI_SMALL, padx=0, pady=5
             ).pack(fill=tk.X, pady=(0, 3))
        _btn(p, "Load Address List  Ctrl+O", self._load_address_list,
             kind="ghost", font=UI_SMALL, padx=0, pady=5
             ).pack(fill=tk.X)

        tk.Frame(p, bg=SURFACE, height=20).pack()

    # ── Right panel ────────────────────────────────────────────────────────

    def _build_right(self, parent):
        pane = tk.PanedWindow(parent, orient=tk.VERTICAL, bg=BG,
                               sashwidth=1, sashrelief=tk.FLAT, sashpad=0, bd=0)
        pane.pack(fill=tk.BOTH, expand=True, padx=(1, 0))

        top = tk.Frame(pane, bg=BG)
        pane.add(top, minsize=180)
        self._build_results(top)

        bot = tk.Frame(pane, bg=BG)
        pane.add(bot, minsize=160)
        self._build_addr_table(bot)

    def _build_results(self, parent):
        hdr = tk.Frame(parent, bg=BG, pady=8, padx=12)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="Scan Results", font=UI_BOLD,
                 fg=TEXT, bg=BG).pack(side=tk.LEFT)
        self._result_count_var = tk.StringVar(value="")
        tk.Label(hdr, textvariable=self._result_count_var,
                 font=UI_SMALL, fg=TEXT_DIM, bg=BG).pack(side=tk.LEFT, padx=10)
        tk.Label(hdr, text="Double-click to add  ·  Right-click for options",
                 font=UI_SMALL, fg=TEXT_DIM, bg=BG).pack(side=tk.RIGHT)

        tf = tk.Frame(parent, bg=BG, padx=12)
        tf.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

        cols = ("Address", "Value", "Previous", "Type")
        self._result_tree = ttk.Treeview(tf, columns=cols,
                                          show="headings", selectmode="extended")
        for col, w, anc in [("Address", 160, tk.W), ("Value", 110, tk.E),
                             ("Previous", 110, tk.E), ("Type", 80, tk.CENTER)]:
            self._result_tree.heading(col, text=col)
            self._result_tree.column(col, width=w, anchor=anc)

        sb = ttk.Scrollbar(tf, orient=tk.VERTICAL, command=self._result_tree.yview)
        self._result_tree.configure(yscrollcommand=sb.set)
        self._result_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self._result_tree.tag_configure("changed", foreground=YELLOW)
        self._result_tree.bind("<Double-1>", self._add_selected_to_table)
        self._result_tree.bind("<Return>",   self._add_selected_to_table)
        self._result_tree.bind("<Button-3>", self._result_ctx_menu)

    def _build_addr_table(self, parent):
        hdr = tk.Frame(parent, bg=BG, pady=8, padx=12)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="Address Table", font=UI_BOLD,
                 fg=TEXT, bg=BG).pack(side=tk.LEFT)
        self._file_label = tk.Label(hdr, text="", font=UI_SMALL,
                                     fg=TEXT_DIM, bg=BG)
        self._file_label.pack(side=tk.LEFT, padx=10)

        _btn(hdr, "Save", self._save_address_list,
             kind="ghost", font=UI_SMALL, padx=8, pady=2
             ).pack(side=tk.RIGHT, padx=1)
        _btn(hdr, "Load", self._load_address_list,
             kind="ghost", font=UI_SMALL, padx=8, pady=2
             ).pack(side=tk.RIGHT, padx=1)
        tk.Frame(hdr, bg=BORDER, width=1).pack(side=tk.RIGHT, fill=tk.Y, pady=2, padx=6)

        tf = tk.Frame(parent, bg=BG, padx=12)
        tf.pack(fill=tk.BOTH, expand=True)

        cols = ("S", "Address", "Description", "Type", "Value")
        self._addr_tree = ttk.Treeview(tf, columns=cols, show="headings",
                                        selectmode="browse")
        self._addr_tree.heading("S",           text="")
        self._addr_tree.heading("Address",     text="Address")
        self._addr_tree.heading("Description", text="Description")
        self._addr_tree.heading("Type",        text="Type")
        self._addr_tree.heading("Value",       text="Value")
        self._addr_tree.column("S",           width=22,  anchor=tk.CENTER)
        self._addr_tree.column("Address",     width=150, anchor=tk.W)
        self._addr_tree.column("Description", width=180, anchor=tk.W)
        self._addr_tree.column("Type",        width=72,  anchor=tk.CENTER)
        self._addr_tree.column("Value",       width=120, anchor=tk.E)

        sb2 = ttk.Scrollbar(tf, orient=tk.VERTICAL, command=self._addr_tree.yview)
        self._addr_tree.configure(yscrollcommand=sb2.set)
        self._addr_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb2.pack(side=tk.RIGHT, fill=tk.Y)

        self._addr_tree.tag_configure("frozen",   foreground=ORANGE)
        self._addr_tree.tag_configure("disabled", foreground=TEXT_DIM)
        self._addr_tree.bind("<Double-1>", self._edit_addr_value)
        self._addr_tree.bind("<Delete>",   self._delete_addr_row)
        self._addr_tree.bind("<Button-3>", self._addr_ctx_menu)

        ab = tk.Frame(parent, bg=BG, padx=12, pady=6)
        ab.pack(fill=tk.X)
        for text, cmd, kind in [
            ("Add Address", self._add_address_manual, "default"),
            ("Freeze",      self._toggle_freeze,      "orange"),
            ("Edit Value",  self._edit_addr_value,    "default"),
            ("Remove",      self._delete_addr_row,    "danger"),
        ]:
            _btn(ab, text, cmd, kind=kind,
                 font=UI_SMALL, padx=10, pady=3).pack(side=tk.LEFT, padx=(0, 4))

    # ── Process ────────────────────────────────────────────────────────────

    def _open_process(self):
        dlg = ProcessDialog(self)
        self.wait_window(dlg)
        if dlg.selected_pid is None:
            return
        if self._engine.attach(dlg.selected_pid):
            self._current_proc_name = dlg.selected_name
            self._proc_label.config(
                text=f"{dlg.selected_name}  ·  PID {dlg.selected_pid}",
                fg=GREEN)
            self._clear_results()
            self._status("Attached — ready to scan.")
            self._btn_next.config(state=tk.DISABLED)
            self._scan_info_var.set("")
            self._update_mode_list(first=True)
        else:
            messagebox.showerror(
                "Attach Failed",
                f"Could not open PID {dlg.selected_pid}.\n\n"
                "On Linux, MemEd needs permission to read /proc/<pid>/mem.\n"
                "Try running as root, or:\n"
                "  sudo sysctl kernel.yama.ptrace_scope=0", parent=self)

    def _detach(self):
        self._engine.detach()
        self._freezer.unfreeze_all()
        self._current_proc_name = None
        self._proc_label.config(text="No process attached", fg=TEXT_DIM)
        self._clear_results()
        self._address_rows.clear()
        self._refresh_addr_table()
        self._status("Detached.")
        self._btn_next.config(state=tk.DISABLED)
        self._scan_info_var.set("")

    # ── Scan mode helpers ──────────────────────────────────────────────────

    def _on_mode_change(self, *_):
        label = self._scan_mode_var.get()
        mode  = self._label_to_mode.get(label, SCAN_EXACT)
        if mode in NEEDS_VALUE1:
            self._val1_frame.pack(fill=tk.X, pady=(0, 6))
        else:
            self._val1_frame.pack_forget()
        if mode in NEEDS_VALUE2:
            self._val2_frame.pack(fill=tk.X, pady=(0, 6))
        else:
            self._val2_frame.pack_forget()

    def _update_mode_list(self, first: bool):
        modes = FIRST_SCAN_MODES if first else NEXT_SCAN_MODES
        self._mode_cb["values"] = [SCAN_LABELS[m] for m in modes]
        current = self._label_to_mode.get(self._scan_mode_var.get(), SCAN_EXACT)
        if current not in modes:
            self._scan_mode_var.set(SCAN_LABELS[SCAN_EXACT])

    # ── Scanning ───────────────────────────────────────────────────────────

    def _require_attached(self) -> bool:
        if not self._engine.handle:
            messagebox.showwarning("No Process",
                                    "Attach to a process first.", parent=self)
            return False
        return True

    def _smart_scan(self):
        if not self._engine.has_scanned:
            self._new_scan()
        else:
            self._next_scan()

    def _get_mode(self) -> str:
        return self._label_to_mode.get(self._scan_mode_var.get(), SCAN_EXACT)

    def _parse_value(self, var: tk.StringVar, label: str):
        vtype = self._current_vtype.get()
        raw = var.get().strip()
        if not raw:
            messagebox.showwarning("Missing Value",
                                    f"Enter a {label}.", parent=self)
            return None
        try:
            return float(raw) if vtype in ("Float", "Double") else int(raw, 0)
        except ValueError:
            messagebox.showerror("Invalid Value",
                                  f"Cannot parse '{raw}' as {vtype}.", parent=self)
            return None

    def _new_scan(self):
        if not self._require_attached():
            return
        mode = self._get_mode()
        v1 = self._parse_value(self._scan_val1_var, "value") \
             if mode in NEEDS_VALUE1 else None
        if mode in NEEDS_VALUE1 and v1 is None:
            return
        v2 = self._parse_value(self._scan_val2_var, "second value") \
             if mode in NEEDS_VALUE2 else None
        if mode in NEEDS_VALUE2 and v2 is None:
            return
        self._run_scan("first", mode, v1, v2)

    def _next_scan(self):
        if not self._require_attached():
            return
        mode = self._get_mode()
        v1 = self._parse_value(self._scan_val1_var, "value") \
             if mode in NEEDS_VALUE1 else None
        if mode in NEEDS_VALUE1 and v1 is None:
            return
        v2 = self._parse_value(self._scan_val2_var, "second value") \
             if mode in NEEDS_VALUE2 else None
        if mode in NEEDS_VALUE2 and v2 is None:
            return
        self._run_scan("next", mode, v1, v2)

    def _cancel_scan(self):
        self._engine.cancel()
        self._status("Cancelling...")

    def _reset_scan(self):
        self._engine.reset_scan()
        self._clear_results()
        self._btn_next.config(state=tk.DISABLED)
        self._scan_info_var.set("")
        self._status("Scan reset.")
        self._update_mode_list(first=True)

    def _run_scan(self, phase: str, mode: str, v1, v2):
        if self._scan_thread and self._scan_thread.is_alive():
            return
        vtype     = self._current_vtype.get()
        alignment = ALIGNMENTS.get(self._alignment_var.get(), 4)

        self._btn_new.config(state=tk.DISABLED)
        self._btn_next.config(state=tk.DISABLED)
        self._btn_cancel.config(state=tk.NORMAL)
        self._status("Scanning...")
        self._progress["value"] = 0

        def progress_cb(done, total):
            if total:
                pct = int(done / total * 100)
                self.after(0, lambda p=pct: self._progress.configure(value=p))

        def worker():
            if phase == "first":
                self._engine.reset_scan()
                results = self._engine.first_scan(mode, vtype, v1, v2,
                                                   alignment, progress_cb)
            else:
                results = self._engine.next_scan(mode, vtype, v1, v2, progress_cb)
            self.after(0, lambda r=results, vt=vtype: self._scan_done(r, vt, phase))

        self._scan_thread = threading.Thread(target=worker, daemon=True)
        self._scan_thread.start()

    def _scan_done(self, results, vtype: str, phase: str):
        self._btn_new.config(state=tk.NORMAL)
        self._btn_next.config(state=tk.NORMAL)
        self._btn_cancel.config(state=tk.DISABLED)
        self._progress["value"] = 100
        count = len(results)
        self._result_count_var.set(f"{count:,} results")

        stats = self._engine.last_stats
        n     = self._engine.scan_count
        if phase == "first" and stats.bytes_scanned > 0:
            self._scan_info_var.set(
                f"Scan #{n}  ·  {stats.bytes_scanned/1e6:.0f} MB  "
                f"·  {stats.mb_per_sec:.0f} MB/s  ·  {stats.duration*1000:.0f} ms")
        else:
            self._scan_info_var.set(f"Scan #{n}  ·  {stats.duration*1000:.0f} ms")

        self._status(f"Found {count:,} address(es).")
        self._update_mode_list(first=False)
        if n >= 1:
            self._btn_next.config(state=tk.NORMAL)

        self._result_tree.delete(*self._result_tree.get_children())
        for r in results[:2000]:
            vs  = self._fmt(r.value, vtype)
            ps  = self._fmt(r.prev_value, vtype)
            tag = ("changed",) if r.value != r.prev_value else ()
            self._result_tree.insert("", tk.END, iid=str(r.address),
                                      values=(f"0x{r.address:016X}", vs, ps, vtype),
                                      tags=tag)
        if count > 2000:
            self._result_tree.insert("", tk.END,
                                      values=(f"... {count-2000:,} more — refine scan",
                                              "", "", ""))

    def _clear_results(self):
        self._result_tree.delete(*self._result_tree.get_children())
        self._result_count_var.set("")
        self._engine.reset_scan()

    # ── Context menus ──────────────────────────────────────────────────────

    def _ctx(self):
        return tk.Menu(self, tearoff=0, bg=SURFACE, fg=TEXT,
                       activebackground=BLUE, activeforeground=TEXT_BRIGHT, bd=0,
                       font=UI_FONT)

    def _result_ctx_menu(self, event):
        iid = self._result_tree.identify_row(event.y)
        if not iid:
            return
        self._result_tree.selection_set(iid)
        m = self._ctx()
        m.add_command(label="Add to Address Table", command=self._add_selected_to_table)
        m.add_command(label="Copy Address",         command=lambda: self._copy(iid))
        m.add_separator()
        m.add_command(label="Add All to Table",     command=self._add_all_to_table)
        m.tk_popup(event.x_root, event.y_root)

    def _addr_ctx_menu(self, event):
        iid = self._addr_tree.identify_row(event.y)
        if not iid:
            return
        self._addr_tree.selection_set(iid)
        m = self._ctx()
        m.add_command(label="Edit Value",       command=self._edit_addr_value)
        m.add_command(label="Edit Description", command=self._edit_description)
        m.add_command(label="Toggle Freeze",    command=self._toggle_freeze)
        m.add_separator()
        m.add_command(label="Copy Address",
                      command=lambda: self._copy(
                          f"0x{self._address_rows[int(iid)].address:016X}"))
        m.add_separator()
        m.add_command(label="Remove", command=self._delete_addr_row)
        m.tk_popup(event.x_root, event.y_root)

    def _copy(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)

    # ── Address table ──────────────────────────────────────────────────────

    def _add_selected_to_table(self, _=None):
        vtype = self._current_vtype.get()
        for iid in self._result_tree.selection():
            try:
                addr = int(iid, 0)
            except ValueError:
                continue
            val = self._engine.read_value(addr, vtype)
            self._address_rows.append(AddressRow(addr, val, vtype))
        self._refresh_addr_table()

    def _add_all_to_table(self):
        vtype = self._current_vtype.get()
        for r in self._engine.results[:200]:
            val = self._engine.read_value(r.address, vtype)
            self._address_rows.append(AddressRow(r.address, val, vtype))
        self._refresh_addr_table()

    def _add_address_manual(self):
        raw = simpledialog.askstring("Add Address",
                                      "Enter address (hex or decimal):", parent=self)
        if not raw:
            return
        try:
            addr = int(raw.strip(), 0)
        except ValueError:
            messagebox.showerror("Invalid", f"Cannot parse '{raw}'.", parent=self)
            return
        vtype = self._current_vtype.get()
        val   = self._engine.read_value(addr, vtype) if self._engine.handle else None
        self._address_rows.append(AddressRow(addr, val, vtype))
        self._refresh_addr_table()

    def _edit_addr_value(self, _=None):
        sel = self._addr_tree.selection()
        if not sel:
            return
        row = self._address_rows[int(sel[0])]
        raw = simpledialog.askstring(
            "Edit Value",
            f"Address: 0x{row.address:016X}\n"
            f"Current: {row.value}\nNew value:", parent=self)
        if raw is None:
            return
        try:
            nv = float(raw) if row.vtype in ("Float", "Double") else int(raw, 0)
        except ValueError:
            messagebox.showerror("Invalid", f"Cannot parse '{raw}'.", parent=self)
            return
        if not self._engine.handle:
            return
        if self._engine.write_value(row.address, nv, row.vtype):
            row.value = nv
            if row.frozen:
                self._freezer.update_freeze_value(row.address, nv, row.vtype)
        else:
            messagebox.showerror("Write Failed",
                                  f"Could not write 0x{row.address:016X}.\n"
                                  "Check process is writable (/proc/<pid>/mem).",
                                  parent=self)
        self._refresh_addr_table()

    def _edit_description(self, _=None):
        sel = self._addr_tree.selection()
        if not sel:
            return
        row  = self._address_rows[int(sel[0])]
        desc = simpledialog.askstring("Description", "Enter description:",
                                       initialvalue=row.description, parent=self)
        if desc is not None:
            row.description = desc
            self._refresh_addr_table()

    def _delete_addr_row(self, _=None):
        sel = self._addr_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        self._freezer.unfreeze(self._address_rows[idx].address)
        del self._address_rows[idx]
        self._refresh_addr_table()

    def _toggle_freeze(self):
        sel = self._addr_tree.selection()
        if not sel:
            return
        row = self._address_rows[int(sel[0])]
        if row.frozen:
            row.frozen = False
            self._freezer.unfreeze(row.address)
        else:
            if row.value is None:
                messagebox.showwarning("No Value",
                                        "Read a value before freezing.", parent=self)
                return
            row.frozen = True
            self._freezer.freeze(row.address, row.value, row.vtype,
                                  safe_mode=self._safe_mode_var.get(),
                                  verify=self._verify_var.get())
        self._refresh_addr_table()

    def _toggle_freeze_all(self):
        if not self._address_rows:
            return
        any_unfrozen = any(not r.frozen for r in self._address_rows)
        for row in self._address_rows:
            if any_unfrozen:
                if not row.frozen and row.value is not None:
                    row.frozen = True
                    self._freezer.freeze(row.address, row.value, row.vtype,
                                          safe_mode=self._safe_mode_var.get(),
                                          verify=self._verify_var.get())
            else:
                row.frozen = False
                self._freezer.unfreeze(row.address)
        self._refresh_addr_table()

    def _refresh_addr_table(self):
        sel = self._addr_tree.selection()
        self._addr_tree.delete(*self._addr_tree.get_children())
        for i, row in enumerate(self._address_rows):
            entry       = self._freezer.get_entry(row.address)
            is_disabled = entry is not None and entry.disabled
            if is_disabled:
                mark, tag = "X", ("disabled",)
            elif row.frozen:
                mark, tag = "*", ("frozen",)
            else:
                mark, tag = "", ()
            self._addr_tree.insert("", tk.END, iid=str(i),
                                    values=(mark,
                                            f"0x{row.address:016X}",
                                            row.description or "—",
                                            row.vtype,
                                            self._fmt(row.value, row.vtype)),
                                    tags=tag)
        if sel and sel[0] in [str(i) for i in range(len(self._address_rows))]:
            self._addr_tree.selection_set(sel[0])

    # ── Live refresh ───────────────────────────────────────────────────────

    def _start_refresh_loop(self):
        self._refresh_addr_values()
        self.after(400, self._start_refresh_loop)

    def _refresh_addr_values(self):
        if not self._engine.handle:
            return
        changed = False
        for row in self._address_rows:
            if row.frozen:
                continue
            val = self._engine.read_value(row.address, row.vtype)
            if val != row.value:
                row.value = val
                changed   = True
        if changed:
            self._refresh_addr_table()

    # ── Helpers ────────────────────────────────────────────────────────────

    def _fmt(self, value, vtype: str) -> str:
        if value is None:
            return "—"
        return f"{value:.6g}" if vtype in ("Float", "Double") else str(value)

    def _status(self, msg: str):
        self._status_var.set(msg)

    def _show_about(self):
        messagebox.showinfo("About MemEd",
            "MemEd — Memory Editor (Linux)\n\n"
            "Scan: Exact · Not Equal · Greater · Less · Between\n"
            "      Changed · Unchanged · Increased · Decreased\n"
            "      Increased By · Decreased By · Unknown Initial\n\n"
            "Types: Int8/16/32/64  UInt8/16/32/64  Float  Double\n"
            "Freeze: Safe Mode · Verify · Auto-disable\n\n"
            "F11 = Pause freeze    F12 = Unfreeze all\n"
            "Ctrl+S = Save    Ctrl+O = Load\n\n"
            "Requires permission to read /proc/<pid>/mem.\n"
            "Run as root or set:\n"
            "  sudo sysctl kernel.yama.ptrace_scope=0", parent=self)

    # ── Save / Load ────────────────────────────────────────────────────────

    def _save_address_list(self):
        if not self._address_rows:
            messagebox.showwarning("Empty", "No entries to save.", parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self, title="Save Address List",
            defaultextension=FILE_EXT, filetypes=FILE_FILTER,
            initialfile=self._suggested_filename())
        if not path:
            return
        entries = []
        for row in self._address_rows:
            fv = None
            if row.frozen:
                fe = self._freezer.get_entry(row.address)
                fv = fe.value if fe else row.value
            entries.append(SavedEntry(row.address, row.description,
                                       row.vtype, row.frozen, fv))
        try:
            af_save(path, entries, self._current_proc_name or "")
        except Exception as e:
            messagebox.showerror("Save Failed", str(e), parent=self)
            return
        self._last_save_path = path
        self._file_label.config(text=os.path.basename(path))
        self._status(f"Saved {len(entries)} entries → {os.path.basename(path)}")

    def _load_address_list(self):
        path = filedialog.askopenfilename(
            parent=self, title="Load Address List", filetypes=FILE_FILTER)
        if not path:
            return
        try:
            saved, proc_name = af_load(path)
        except Exception as e:
            messagebox.showerror("Load Failed", str(e), parent=self)
            return
        if not saved:
            messagebox.showwarning("Empty File", "No valid entries found.", parent=self)
            return
        if self._address_rows:
            ans = messagebox.askyesnocancel(
                "Load Address List",
                f"Load {len(saved)} entries from '{os.path.basename(path)}'.\n\n"
                "Yes → Replace    No → Append    Cancel → Abort",
                parent=self)
            if ans is None:
                return
            if ans:
                self._freezer.unfreeze_all()
                self._address_rows.clear()
        vtype = self._current_vtype.get()
        for se in saved:
            evtype = se.vtype if se.vtype in VALUE_TYPES else vtype
            val    = self._engine.read_value(se.address, evtype) \
                     if self._engine.handle else None
            row    = AddressRow(se.address, val, evtype)
            row.description = se.description
            if se.frozen and se.freeze_value is not None:
                try:
                    fv = (float(se.freeze_value) if evtype in ("Float", "Double")
                          else int(se.freeze_value))
                    row.frozen = True
                    self._freezer.freeze(se.address, fv, evtype,
                                          safe_mode=self._safe_mode_var.get(),
                                          verify=self._verify_var.get())
                except (TypeError, ValueError):
                    row.frozen = False
            self._address_rows.append(row)
        self._last_save_path = path
        self._file_label.config(text=os.path.basename(path))
        self._refresh_addr_table()
        self._status(f"Loaded {len(saved)} entries from {os.path.basename(path)}"
                     + (f"  (process: {proc_name})" if proc_name else ""))

    def _clear_address_table(self):
        if not self._address_rows:
            return
        if not messagebox.askyesno("Clear", "Remove all entries?", parent=self):
            return
        self._freezer.unfreeze_all()
        self._address_rows.clear()
        self._file_label.config(text="")
        self._last_save_path = None
        self._refresh_addr_table()
        self._status("Address table cleared.")

    def _suggested_filename(self) -> str:
        if self._last_save_path:
            return os.path.basename(self._last_save_path)
        proc = (self._current_proc_name or "addresses")
        return f"{proc}{FILE_EXT}"

    # ── Freeze safety ──────────────────────────────────────────────────────

    def _emergency_unfreeze(self):
        for row in self._address_rows:
            row.frozen = False
        self._freezer.unfreeze_all()
        self._freeze_status_var.set("")
        self._pause_btn.config(text="Pause  [F11]")
        self._paused = False
        self._refresh_addr_table()
        self.title("MemEd — All Unfrozen")
        self.after(2000, lambda: self.title("MemEd"))

    def _emergency_pause_toggle(self):
        if self._paused:
            self._freezer.emergency_resume()
            self._paused = False
            self._pause_btn.config(text="Pause  [F11]")
            self._freeze_status_var.set("")
        else:
            self._freezer.emergency_pause()
            self._paused = True
            self._pause_btn.config(text="Resume  [F11]")
            self._freeze_status_var.set("Freeze paused")

    def _on_freeze_auto_disabled(self, address: int, reason: str):
        def _upd():
            for row in self._address_rows:
                if row.address == address:
                    row.frozen = False
                    break
            self._refresh_addr_table()
            self._freeze_status_var.set(f"[!] 0x{address:X} auto-disabled")
        self.after(0, _upd)

    def _open_freeze_settings(self):
        FreezeSafetyPanel(self, self._freezer,
                           self._safe_mode_var, self._verify_var)


# ── Freeze Safety Panel ────────────────────────────────────────────────────

class FreezeSafetyPanel(tk.Toplevel):
    def __init__(self, parent, freezer, safe_mode_var, verify_var):
        super().__init__(parent)
        self.title("Freeze Settings")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self._freezer       = freezer
        self._safe_mode_var = safe_mode_var
        self._verify_var    = verify_var
        self._build()
        self._refresh_loop()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _build(self):
        hdr = tk.Frame(self, bg=SURFACE, pady=12, padx=16)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="Freeze Settings", font=UI_TITLE,
                 fg=TEXT_BRIGHT, bg=SURFACE).pack(side=tk.LEFT)

        body = tk.Frame(self, bg=BG, padx=16, pady=12)
        body.pack(fill=tk.BOTH, expand=True)

        tk.Label(body, text="DEFAULT OPTIONS FOR NEW ENTRIES",
                 font=UI_SMALL, fg=TEXT_DIM, bg=BG).pack(anchor=tk.W, pady=(0, 6))

        for var, label, desc in [
            (self._safe_mode_var,
             "Safe Mode  —  only write when value drifts",
             "Reads current value first; skips write if already matches target.\n"
             "Greatly reduces crash risk on physics / logic values."),
            (self._verify_var,
             "Write Verify  —  read-back after each write",
             "Confirms write succeeded; auto-disables after 3 consecutive failures."),
        ]:
            f = tk.Frame(body, bg=SURFACE2, padx=12, pady=8)
            f.pack(fill=tk.X, pady=(0, 6))
            tk.Checkbutton(f, text=label, variable=var,
                           bg=SURFACE2, fg=TEXT, selectcolor=INPUT_BG,
                           activebackground=SURFACE2, activeforeground=BLUE,
                           font=UI_FONT).pack(anchor=tk.W)
            tk.Label(f, text=desc, font=UI_SMALL, fg=TEXT_DIM,
                     bg=SURFACE2, justify=tk.LEFT).pack(anchor=tk.W, padx=20)

        tk.Frame(body, bg=BORDER, height=1).pack(fill=tk.X, pady=10)
        tk.Label(body, text="WRITE INTERVAL", font=UI_SMALL,
                 fg=TEXT_DIM, bg=BG).pack(anchor=tk.W, pady=(0, 6))

        self._interval_var = tk.DoubleVar(value=self._freezer.interval * 1000)
        sl_row = tk.Frame(body, bg=BG)
        sl_row.pack(fill=tk.X)
        tk.Label(sl_row, text="50ms", font=UI_SMALL, fg=TEXT_DIM, bg=BG).pack(side=tk.LEFT)
        ttk.Scale(sl_row, from_=50, to=2000, variable=self._interval_var,
                  orient=tk.HORIZONTAL,
                  command=lambda _: self._on_interval()).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        tk.Label(sl_row, text="2s", font=UI_SMALL, fg=TEXT_DIM, bg=BG).pack(side=tk.LEFT)

        self._iv_label = tk.Label(body, text="", font=UI_BOLD, fg=BLUE, bg=BG)
        self._iv_label.pack(anchor=tk.W, pady=(4, 0))
        self._on_interval()

        presets = tk.Frame(body, bg=BG)
        presets.pack(anchor=tk.W, pady=(6, 0))
        for lbl, ms in [("50ms", 50), ("250ms", 250), ("500ms", 500), ("1s", 1000)]:
            _btn(presets, lbl, lambda v=ms: self._set_preset(v),
                 kind="ghost", font=UI_SMALL, padx=10, pady=3
                 ).pack(side=tk.LEFT, padx=(0, 4))

        tk.Frame(body, bg=BORDER, height=1).pack(fill=tk.X, pady=10)
        tk.Label(body, text="ACTIVE FREEZE ENTRIES", font=UI_SMALL,
                 fg=TEXT_DIM, bg=BG).pack(anchor=tk.W, pady=(0, 6))

        tf = tk.Frame(body, bg=BG)
        tf.pack(fill=tk.BOTH, expand=True)
        cols = ("Address", "Value", "Writes", "Errors", "Status")
        self._etree = ttk.Treeview(tf, columns=cols, show="headings", height=5)
        for col, w, anc in [("Address", 80, tk.W), ("Value", 80, tk.E),
                              ("Writes", 55, tk.CENTER), ("Errors", 50, tk.CENTER),
                              ("Status", 120, tk.CENTER)]:
            self._etree.heading(col, text=col)
            self._etree.column(col, width=w, anchor=anc)
        self._etree.tag_configure("ok",       foreground=GREEN)
        self._etree.tag_configure("disabled", foreground=RED)
        sb = ttk.Scrollbar(tf, orient=tk.VERTICAL, command=self._etree.yview)
        self._etree.configure(yscrollcommand=sb.set)
        self._etree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        ft = tk.Frame(self, bg=SURFACE, pady=10, padx=16)
        ft.pack(fill=tk.X)
        _btn(ft, "Re-enable Selected", self._reenable, kind="success",
             font=UI_SMALL).pack(side=tk.LEFT)
        _btn(ft, "Close", self.destroy, kind="ghost").pack(side=tk.RIGHT)

    def _on_interval(self):
        ms = int(self._interval_var.get())
        self._freezer.set_interval(ms / 1000.0)
        risk = "Higher crash risk" if ms < 100 else \
               "Balanced" if ms < 600 else "Low crash risk"
        self._iv_label.config(text=f"{ms} ms  —  {risk}")

    def _set_preset(self, ms):
        self._interval_var.set(ms)
        self._on_interval()

    def _reenable(self):
        for iid in self._etree.selection():
            try:
                self._freezer.reenable(int(iid, 16))
            except ValueError:
                pass

    def _refresh_loop(self):
        if not self.winfo_exists():
            return
        entries = self._freezer.get_all_entries()
        self._etree.delete(*self._etree.get_children())
        for addr, e in entries.items():
            if e.disabled:
                status, tag = f"X {e.last_error[:18]}", ("disabled",)
            elif e.error_count:
                status, tag = f"! {e.error_count} err", ("disabled",)
            else:
                status, tag = "OK", ("ok",)
            self._etree.insert("", tk.END, iid=hex(addr),
                                values=(f"0x{addr:X}", e.value,
                                        e.write_count, e.error_count, status),
                                tags=tag)
        self.after(500, self._refresh_loop)


# ── Entry point ────────────────────────────────────────────────────────────

def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
