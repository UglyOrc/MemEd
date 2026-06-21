"""
MemEd loading splash screen.
Call show_splash() before creating the main App window.
"""
from __future__ import annotations

import tkinter as tk


def _font(family_candidates: list[str], size: int, weight: str = "normal") -> tuple:
    try:
        import tkinter.font as tkfont
        available = set(tkfont.families())
        for name in family_candidates:
            if name in available:
                return (name, size, weight) if weight != "normal" else (name, size)
    except Exception:
        pass
    return (family_candidates[-1], size, weight) if weight != "normal" else (family_candidates[-1], size)


_UI = ["Ubuntu", "DejaVu Sans", "Noto Sans", "Liberation Sans", "Segoe UI", "Helvetica", "Arial"]

# ── Palette (matches main app) ─────────────────────────────────────────────
BG       = "#0f0f17"
SURFACE  = "#16161f"
SURFACE2 = "#1e1e2a"
BORDER   = "#2a2a3a"
BLUE     = "#5b9cf6"
BLUE_DIM = "#3a5fa0"
GREEN    = "#4ec994"
TEXT     = "#d4d4dc"
TEXT_DIM = "#5a5a72"
TEXT_BRIGHT = "#ffffff"


class SplashScreen(tk.Tk):
    """
    Borderless loading window shown while the app initialises.
    Dismiss by calling .finish() from any thread, or it self-destructs
    after `auto_close_ms` milliseconds.
    """

    WIDTH  = 480
    HEIGHT = 320

    def __init__(self, steps: list[str], auto_close_ms: int = 4000):
        super().__init__()
        self._steps        = steps
        self._step_index   = 0
        self._done         = False
        self._auto_ms      = auto_close_ms

        self.overrideredirect(True)        # no window decorations
        self.configure(bg=BG)
        self.resizable(False, False)
        self.attributes("-topmost", True)  # stay on top until dismissed

        # Build first so all widgets exist, then measure and center
        self._build()
        self.update_idletasks()
        self._center()
        self._animate_bar()
        self._run_steps()

    # ── Layout ─────────────────────────────────────────────────────────────

    def _build(self):
        # Outer border frame (1 px accent border)
        outer = tk.Frame(self, bg=BLUE, padx=1, pady=1)
        outer.pack(fill=tk.BOTH, expand=True)

        inner = tk.Frame(outer, bg=BG)
        inner.pack(fill=tk.BOTH, expand=True)

        # ── Top section: logo ──────────────────────────────────────────────
        logo_frame = tk.Frame(inner, bg=BG, pady=20)
        logo_frame.pack(fill=tk.X)

        logo_row = tk.Frame(logo_frame, bg=BG)
        logo_row.pack()
        tk.Label(logo_row, text="MEM", font=_font(_UI, 28, "bold"),
                 fg=BLUE, bg=BG).pack(side=tk.LEFT)
        tk.Label(logo_row, text="ED", font=_font(_UI, 28, "bold"),
                 fg=TEXT_BRIGHT, bg=BG).pack(side=tk.LEFT)

        tk.Label(inner, text="Process Memory Editor",
                 font=_font(_UI, 10), fg=TEXT_DIM, bg=BG).pack()

        # ── Divider ────────────────────────────────────────────────────────
        tk.Frame(inner, bg=BORDER, height=1).pack(fill=tk.X, padx=24, pady=(14, 0))

        # ── Progress bar ───────────────────────────────────────────────────
        bar_frame = tk.Frame(inner, bg=BG, padx=24, pady=10)
        bar_frame.pack(fill=tk.X)

        track = tk.Frame(bar_frame, bg=SURFACE2, height=4)
        track.pack(fill=tk.X)
        track.pack_propagate(False)

        self._bar = tk.Frame(track, bg=BLUE, height=4, width=0)
        self._bar.place(x=0, y=0, relheight=1.0, width=0)
        self._track = track

        # ── Status label ───────────────────────────────────────────────────
        self._status_var = tk.StringVar(value="Starting…")
        tk.Label(inner, textvariable=self._status_var,
                 font=_font(_UI, 9), fg=TEXT_DIM, bg=BG
                 ).pack(pady=(0, 6))

        # ── Dots animation ─────────────────────────────────────────────────
        self._dots_var = tk.StringVar(value="")
        tk.Label(inner, textvariable=self._dots_var,
                 font=_font(_UI, 10), fg=BLUE, bg=BG).pack()

        # ── Footer ─────────────────────────────────────────────────────────
        tk.Frame(inner, bg=BORDER, height=1).pack(fill=tk.X, padx=24, pady=(12, 0))
        tk.Label(inner, text="v2.0.0  ·  github.com/UglyOrc/MemEd",
                 font=_font(_UI, 8), fg=TEXT_DIM, bg=BG
                 ).pack(pady=(6, 10))

    # ── Animation ──────────────────────────────────────────────────────────

    def _center(self):
        w  = self.winfo_reqwidth()  or self.WIDTH
        h  = self.winfo_reqheight() or self.HEIGHT
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x  = (sw - w) // 2
        y  = (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _animate_bar(self):
        if self._done or not self.winfo_exists():
            return
        total  = len(self._steps)
        target = int((self._step_index / max(total, 1)) * self._track.winfo_width())
        self._bar.place_configure(width=target)
        self.after(30, self._animate_bar)

    def _dots_tick(self, count=0):
        if self._done or not self.winfo_exists():
            return
        self._dots_var.set("●  " * (count % 4))
        self.after(350, self._dots_tick, count + 1)

    # ── Step runner ────────────────────────────────────────────────────────

    def _run_steps(self):
        """Advance through init steps with small delays so the UI renders."""
        delay_per_step = max(180, (self._auto_ms - 400) // max(len(self._steps), 1))

        def _next(idx):
            if idx >= len(self._steps):
                self._status_var.set("Ready.")
                self._step_index = len(self._steps)
                self.after(400, self.finish)
                return
            self._status_var.set(self._steps[idx])
            self._step_index = idx + 1
            self.after(delay_per_step, _next, idx + 1)

        self.after(100, self._dots_tick)
        self.after(200, _next, 0)

    # ── Public API ─────────────────────────────────────────────────────────

    def finish(self):
        """Close the splash and hand control back to the caller."""
        if self._done:
            return
        self._done = True
        try:
            self.destroy()
        except Exception:
            pass


def show_splash(steps: list[str] | None = None):  # noqa: UP007
    """
    Display the splash screen and block until it closes.
    Call this before creating the main App() instance.
    """
    if steps is None:
        steps = [
            "Loading platform drivers…",
            "Initialising scan engine…",
            "Applying stealth configuration…",
            "Building interface…",
        ]
    splash = SplashScreen(steps)
    splash.mainloop()
