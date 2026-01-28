# SusAlert Lite v4.6.11 – Minimal Auto-Start Overlay (Borderless + Draggable + Close X + Info + Settings)
# CHANGES:
# - REMOVED: user-set global hotkey + all hotkey UI/options
# - Help window re-added + improved user guide (Info button opens Help window)
# - Default MSBT font size = 30
# - Main window width increased by 15px (280 -> 295)
# - Demo mode OFF by default
# - Banner alerts OFF by default
# - Banner mode COUNTDOWN by default
# - MSBT default position: center of screen, lower third (anchor = "lower_center")
# - MSBT transparent key is BLACK (no green border)
# - Sound: reliable Windows fallback chain:
#     winsound.PlaySound(system alias) -> winsound.MessageBeep -> winsound.Beep -> Tk bell
#
# Includes:
# - Time adjustment [-]/[+] (100ms steps) persisted as time_offset_ms
# - Energy fungi button reliable show/hide + bright yellow surround
# - Demo mode (toggle + Start/Stop Demo buttons)
# - Settings resize open/close fixed
# - Loop errors print to terminal

import json
import sys
import time
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Tuple

import numpy as np
import mss
import tkinter as tk
from tkinter import messagebox
from tkinter import font as tkfont
from PIL import Image, ImageTk
import cv2

APP_NAME = "SusAlert Lite"

if getattr(sys, "frozen", False) and hasattr(sys, "executable"):
    BASE = Path(sys.executable).resolve().parent
else:
    BASE = Path(__file__).resolve().parent

CFG_PATH = BASE / "config.json"

ROTATION_EVENTS = [
    (13,  "Red Spore"),
    (25,  "Fairy Ring"),
    (37,  "Slimes"),
    (49,  "Yellow Spore"),
    (61,  "Stun"),
    (73,  "Sticky Fungi"),
    (85,  "Green Spore"),
    (97,  "Fairy Ring"),
    (109, "Slimes"),
    (121, "Blue Spore"),
    (133, "Stun"),
    (145, "MID!"),
]
ENERGY_TIME = 145


@dataclass
class Region:
    x: int
    y: int
    w: int
    h: int


def default_cfg() -> dict:
    return {
        "always_on_top": True,
        "poll_ms": 120,
        "template_threshold": 0.62,
        "timer_region": None,
        "timer_template_path": "assets/timer_template.png",
        "cooldown_s": 1.0,
        "setup_complete": False,
        "first_run_popup_shown": False,

        "theme_bg": "#212121",
        "theme_fg": "#ffffff",
        "theme_muted": "#bdbdbd",
        "theme_header": "#1a1a1a",

        # sound
        "event_sound": True,

        # window position
        "window_x": None,
        "window_y": None,

        # help window sizing
        "help_window_w": 560,
        "help_window_h": 560,

        # Banner alerts (inside app)
        "banner_enabled": False,           # OFF by default
        "banner_mode": "COUNTDOWN",        # COUNTDOWN by default
        "banner_countdown_s": 3,
        "banner_hold_ms": 1200,

        # MSBT overlay
        "msbt_enabled": True,
        "msbt_anchor": "lower_center",
        "msbt_x": 400,
        "msbt_y": 120,
        "msbt_font_family": "Segoe UI",
        "msbt_font_size": 30,              # default 30px
        "msbt_duration_ms": 2500,
        "msbt_step_ms": 250,

        # UI state
        "settings_open": False,

        # Demo mode
        "demo_mode": False,

        # time adjustment
        "time_offset_ms": 0,
    }


def load_cfg() -> dict:
    if CFG_PATH.exists():
        try:
            cfg = json.loads(CFG_PATH.read_text(encoding="utf-8"))
            d = default_cfg()
            d.update(cfg if isinstance(cfg, dict) else {})
            return d
        except Exception:
            pass
    return default_cfg()


def save_cfg(cfg: dict) -> None:
    try:
        CFG_PATH.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    CFG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def play_alert_sound(root: Optional[tk.Tk] = None) -> None:
    """
    Windows-friendly sound that should work on essentially all PCs.
    Fallback chain:
      PlaySound(system alias) -> MessageBeep -> Beep -> Tk bell
    """
    try:
        import winsound

        try:
            winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
            return
        except Exception:
            pass

        try:
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
            return
        except Exception:
            pass

        try:
            winsound.Beep(880, 120)
            winsound.Beep(660, 120)
            return
        except Exception:
            pass

    except Exception:
        pass

    try:
        if root is not None:
            root.bell()
    except Exception:
        pass


class AnnouncementOverlay:
    """
    MSBT-like announcements (transparent, borderless Toplevel).
    Transparent key is BLACK to avoid green border effect.
    """
    TRANSPARENT_KEY = "#000000"  # black

    def __init__(self, root: tk.Tk, cfg: dict, on_cfg_changed=None):
        self.root = root
        self.cfg = cfg
        self.on_cfg_changed = on_cfg_changed

        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)

        self.win.config(bg=self.TRANSPARENT_KEY)
        try:
            self.win.wm_attributes("-transparentcolor", self.TRANSPARENT_KEY)
        except Exception:
            pass

        self.label = tk.Label(
            self.win, text="",
            bg=self.TRANSPARENT_KEY,
            fg=self.cfg.get("theme_fg", "#ffffff"),
            font=self._font(),
            padx=12, pady=8
        )
        self.label.pack()

        self._job = None
        self._drag_mode = False
        self._dx = 0
        self._dy = 0

        self._apply_position()

    def _font(self):
        fam = str(self.cfg.get("msbt_font_family", "Segoe UI"))
        size = int(self.cfg.get("msbt_font_size", 30))
        return tkfont.Font(family=fam, size=size, weight="bold")

    def _apply_position(self):
        self.win.update_idletasks()
        w = self.win.winfo_reqwidth()
        h = self.win.winfo_reqheight()
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()

        anchor = str(self.cfg.get("msbt_anchor", "custom"))
        if anchor == "top_left":
            x, y = 0, 0
        elif anchor == "top":
            x, y = (sw - w) // 2, 0
        elif anchor == "top_right":
            x, y = sw - w, 0
        elif anchor == "center":
            x, y = (sw - w) // 2, (sh - h) // 2
        elif anchor == "lower_center":
            x = (sw - w) // 2
            y = int(sh * 0.66 - h / 2)
        elif anchor == "bottom_left":
            x, y = 0, sh - h
        elif anchor == "bottom":
            x, y = (sw - w) // 2, sh - h
        elif anchor == "bottom_right":
            x, y = sw - w, sh - h
        else:
            x = int(self.cfg.get("msbt_x", 400))
            y = int(self.cfg.get("msbt_y", 120))

        x = max(0, min(sw - w, x))
        y = max(0, min(sh - h, y))
        self.win.geometry(f"+{x}+{y}")

    def hide(self):
        if self._job:
            try:
                self.root.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        self.win.withdraw()

    def show_text(self, text: str, hold_ms: int):
        self.hide()
        self.label.config(text=text, font=self._font())
        self._apply_position()
        self.win.deiconify()
        self._job = self.root.after(max(250, int(hold_ms)), self.hide)

    def show_countdown(self, label: str, seconds: int):
        self.hide()
        step_ms = int(self.cfg.get("msbt_step_ms", 250))
        dur_ms = int(self.cfg.get("msbt_duration_ms", 2500))

        def step(s: int):
            if not bool(self.cfg.get("msbt_enabled", True)):
                self.hide()
                return
            if s > 0:
                self.label.config(text=f"{label} in {s}…", font=self._font())
                self._apply_position()
                self.win.deiconify()
                self._job = self.root.after(1000, lambda: step(s - 1))
            else:
                self.show_text(f"{label} NOW!", dur_ms)

        self.label.config(text=f"{label} in {seconds}…", font=self._font())
        self._apply_position()
        self.win.deiconify()
        self._job = self.root.after(max(50, step_ms), lambda: step(int(seconds)))

    def set_position_mode(self, on_done=None):
        if self._drag_mode:
            return
        self._drag_mode = True
        self.label.config(text="Drag me (MSBT position)\nClick to save", font=self._font())
        self._apply_position()
        self.win.deiconify()

        def down(e):
            self._dx = e.x
            self._dy = e.y

        def move(e):
            x = self.win.winfo_pointerx() - self._dx
            y = self.win.winfo_pointery() - self._dy
            self.win.geometry(f"+{x}+{y}")

        def up(_e):
            sw = self.win.winfo_screenwidth()
            sh = self.win.winfo_screenheight()
            x = max(0, min(sw, int(self.win.winfo_x())))
            y = max(0, min(sh, int(self.win.winfo_y())))
            self.cfg["msbt_anchor"] = "custom"
            self.cfg["msbt_x"] = x
            self.cfg["msbt_y"] = y
            if self.on_cfg_changed:
                self.on_cfg_changed(self.cfg)
            self._drag_mode = False
            self.win.unbind("<ButtonPress-1>")
            self.win.unbind("<B1-Motion>")
            self.win.unbind("<ButtonRelease-1>")
            self.hide()
            if on_done:
                on_done()

        self.win.bind("<ButtonPress-1>", down)
        self.win.bind("<B1-Motion>", move)
        self.win.bind("<ButtonRelease-1>", up)


class RegionSelector(tk.Toplevel):
    """Full-screen screenshot overlay: drag to select region, Enter to confirm, Esc to cancel."""
    def __init__(self, master, screenshot: Image.Image, on_done, bg="#000000"):
        super().__init__(master)
        self.attributes("-topmost", True)
        self.overrideredirect(True)
        self.on_done = on_done

        self.tk_img = ImageTk.PhotoImage(screenshot)
        self.canvas = tk.Canvas(
            self,
            width=screenshot.width,
            height=screenshot.height,
            highlightthickness=0,
            bg=bg,
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_image(0, 0, image=self.tk_img, anchor="nw")

        self.start = None
        self.rect = None
        self.region = None

        self.canvas.bind("<ButtonPress-1>", self._down)
        self.canvas.bind("<B1-Motion>", self._move)
        self.canvas.bind("<ButtonRelease-1>", self._up)
        self.bind("<Return>", self._confirm)
        self.bind("<Escape>", self._cancel)

        self.geometry(f"{screenshot.width}x{screenshot.height}+0+0")

    def _down(self, e):
        self.start = (e.x, e.y)
        if self.rect:
            self.canvas.delete(self.rect)
            self.rect = None

    def _move(self, e):
        if not self.start:
            return
        x0, y0 = self.start
        x1, y1 = e.x, e.y
        if self.rect:
            self.canvas.coords(self.rect, x0, y0, x1, y1)
        else:
            self.rect = self.canvas.create_rectangle(
                x0, y0, x1, y1, outline="#ff3b30", width=2
            )

    def _up(self, e):
        if not self.start:
            return
        x0, y0 = self.start
        x1, y1 = e.x, e.y
        x = min(x0, x1)
        y = min(y0, y1)
        w = abs(x1 - x0)
        h = abs(y1 - y0)
        if w > 5 and h > 5:
            self.region = (x, y, w, h)

    def _confirm(self, _=None):
        if not self.region:
            messagebox.showinfo("No selection", "Drag to select the boss timer region first.")
            return
        self.on_done(self.region)
        self.destroy()

    def _cancel(self, _=None):
        self.on_done(None)
        self.destroy()


class TimerMatcher:
    """Template match: determines whether the boss timer widget is present in the selected region."""
    def __init__(self, template_path: Path, threshold: float):
        self.template_path = template_path
        self.threshold = threshold
        self.template = None
        if template_path.exists():
            self.template = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)

    def save_template(self, gray: np.ndarray):
        self.template_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(self.template_path), gray)
        self.template = gray

    def score(self, gray: np.ndarray) -> float:
        if self.template is None:
            return 0.0
        if gray.shape != self.template.shape:
            return 0.0
        res = cv2.matchTemplate(gray, self.template, cv2.TM_CCOEFF_NORMED)
        return float(res.max())

    def is_present(self, gray: np.ndarray) -> bool:
        return self.score(gray) >= self.threshold


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.cfg = load_cfg()

        self.bg = self.cfg.get("theme_bg", "#212121")
        self.fg = self.cfg.get("theme_fg", "#ffffff")
        self.muted = self.cfg.get("theme_muted", "#bdbdbd")
        self.header_bg = self.cfg.get("theme_header", "#1a1a1a")

        self.title(APP_NAME)
        self.configure(bg=self.bg)
        self.resizable(False, False)
        self.overrideredirect(True)
        self.attributes("-topmost", bool(self.cfg.get("always_on_top", True)))

        # window pos: saved, else top-left
        x = self.cfg.get("window_x")
        y = self.cfg.get("window_y")
        if isinstance(x, int) and isinstance(y, int):
            self.geometry(f"295x132+{x}+{y}")  # +15px width
        else:
            self.geometry("295x132+0+0")       # +15px width

        self._base_h = 132

        # hotkeys (in-app)
        self.bind_all("<Escape>", lambda e: self._safe_close())
        self.bind_all("<Control-q>", lambda e: self._safe_close())
        self.bind_all("<Control-r>", lambda e: self.reset_setup())

        # drag
        self._drag_off_x = 0
        self._drag_off_y = 0

        # state
        self.running = False
        self.worker: Optional[threading.Thread] = None

        self.timer_region = self._cfg_region()
        self.matcher = TimerMatcher(
            BASE / self.cfg.get("timer_template_path", "assets/timer_template.png"),
            float(self.cfg.get("template_threshold", 0.62)),
        )

        self.encounter_active = False
        self.rotation_start = 0.0
        self.last_seen_timer = 0.0
        self.last_event_fire: Dict[str, float] = {}
        self.last_banner_fire: Dict[str, float] = {}
        self.energy_button_shown = False

        # demo
        self.demo_running = False

        # time adjustment
        self.time_offset_ms = int(self.cfg.get("time_offset_ms", 0))
        self.time_offset_var = tk.StringVar(value=self._fmt_offset(self.time_offset_ms))

        # UI vars
        self.status = tk.StringVar(value="WAITING — encounter start")
        self.next_name = tk.StringVar(value="Next: Red Spore")
        self.countdown = tk.StringVar(value="00:13")

        # help window handle
        self._help_win: Optional[tk.Toplevel] = None

        # banner job refs
        self._banner_hide_job = None
        self._banner_seq_job = None

        # announcement overlay
        self.msbt = AnnouncementOverlay(self, self.cfg, on_cfg_changed=self._on_cfg_changed)

        # build UI
        self._build_ui()

        # start behavior
        if self._setup_complete() or bool(self.cfg.get("demo_mode", False)):
            self.after(200, self.start_monitoring)
        else:
            self.after(150, self._show_first_run_instructions)

        if bool(self.cfg.get("settings_open", False)):
            self.after(80, self.toggle_settings)

        self.after(60, lambda: self._resize_dynamic(allow_shrink=True))

    # -------------------- help --------------------

    def _help_text(self) -> str:
        return (
            "SusAlert Lite — User Guide\n"
            "==========================\n\n"
            "What this does\n"
            "- Auto-detects Croesus encounter start by matching the boss timer widget.\n"
            "- Shows the next mechanic + countdown.\n"
            "- At 145s it shows a MID clear button.\n"
            "- Optional: Banner alerts (inside the app) and MSBT overlay announcements.\n\n"
            "First-time setup (ONE TIME)\n"
            "1) Open RuneScape and make sure the Croesus boss timer is visible.\n"
            "2) Press Ctrl+R.\n"
            "3) Drag a box around ONLY the timer widget, then press Enter.\n"
            "4) Done. Next runs will auto-start.\n\n"
            "During the fight\n"
            "- The main window shows: status, next mechanic, and timer.\n"
            "- Use the − / + buttons to adjust timing (100ms steps).\n"
            "  (Useful for latency/UI delay. Offset is saved.)\n\n"
            "MID clear\n"
            "- When MID happens (145s), the yellow MID cleared button appears.\n"
            "- Click it AFTER MID is cleared.\n\n"
            "Settings\n"
            "- Gear icon opens Settings.\n"
            "- Banner alerts: shows countdown/now text inside the app.\n"
            "- MSBT overlay: big text overlay (transparent) on your screen.\n"
            "  Use 'Set MSBT position' to drag it where you want.\n\n"
            "Hotkeys\n"
            "- Ctrl+R: re-select timer region\n"
            "- Ctrl+Q or Esc: quit\n\n"
            "Troubleshooting\n"
            "- If it won’t detect the timer: redo Ctrl+R and select a tighter region.\n"
            "- If MSBT looks misplaced: change anchor or use Set MSBT position.\n"
        )

    def open_help(self):
        if self._help_win and self._help_win.winfo_exists():
            self._help_win.lift()
            return

        w = int(self.cfg.get("help_window_w", 560))
        h = int(self.cfg.get("help_window_h", 560))

        win = tk.Toplevel(self)
        win.overrideredirect(True)
        win.configure(bg=self.bg)
        win.attributes("-topmost", True)

        screen_w = win.winfo_screenwidth()
        x = max(0, int(screen_w - w))
        y = 0
        win.geometry(f"{w}x{h}+{x}+{y}")
        win.bind("<Escape>", lambda e: win.destroy())

        hdr = tk.Frame(win, bg=self.header_bg, height=26)
        hdr.pack(fill="x")

        lbl = tk.Label(
            hdr, text="SusAlert Lite — Help",
            bg=self.header_bg, fg=self.fg,
            font=("Segoe UI", 10, "bold"),
        )
        lbl.pack(side="left", padx=10, pady=4)

        btn_close = tk.Label(
            hdr, text="✕",
            bg=self.header_bg, fg="#ff5c5c",
            font=("Segoe UI", 12, "bold"),
            cursor="hand2",
        )
        btn_close.pack(side="right", padx=10)
        btn_close.bind("<Button-1>", lambda e: win.destroy())
        btn_close.bind("<Enter>", lambda e: btn_close.config(fg="#ff1f1f"))
        btn_close.bind("<Leave>", lambda e: btn_close.config(fg="#ff5c5c"))

        def h_start_move(event):
            win._drag_off_x = event.x
            win._drag_off_y = event.y

        def h_do_move(event):
            x2 = win.winfo_pointerx() - getattr(win, "_drag_off_x", 0)
            y2 = win.winfo_pointery() - getattr(win, "_drag_off_y", 0)
            win.geometry(f"+{x2}+{y2}")

        for wdg in (hdr, lbl):
            wdg.bind("<ButtonPress-1>", h_start_move)
            wdg.bind("<B1-Motion>", h_do_move)

        body = tk.Frame(win, bg=self.bg)
        body.pack(fill="both", expand=True)

        scroll = tk.Scrollbar(body)
        scroll.pack(side="right", fill="y")

        txt = tk.Text(
            body, wrap="word",
            bg="#151515", fg=self.fg, insertbackground=self.fg,
            relief="flat", yscrollcommand=scroll.set,
            font=("Consolas", 10),
        )
        txt.pack(side="left", fill="both", expand=True)
        scroll.config(command=txt.yview)

        txt.insert("1.0", self._help_text())
        txt.config(state="disabled")

        def on_close():
            try:
                self.cfg["help_window_w"] = int(win.winfo_width())
                self.cfg["help_window_h"] = int(win.winfo_height())
                save_cfg(self.cfg)
            except Exception:
                pass
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", on_close)
        self._help_win = win

    # -------------------- helpers --------------------

    def _on_cfg_changed(self, cfg: dict):
        save_cfg(cfg)

    @staticmethod
    def _fmt_mmss(seconds: int) -> str:
        seconds = max(0, int(seconds))
        m = seconds // 60
        s = seconds % 60
        return f"{m:02d}:{s:02d}"

    @staticmethod
    def _next_event(rot_t: float) -> Tuple[int, str]:
        for sec, name in ROTATION_EVENTS:
            if rot_t < sec:
                return sec, name
        return ROTATION_EVENTS[-1]

    @staticmethod
    def _fmt_offset(ms: int) -> str:
        s = ms / 1000.0
        sign = "+" if s >= 0 else "−"
        return f"{sign}{abs(s):.1f}s"

    def _set_offset_ms(self, new_ms: int):
        new_ms = int(max(-5000, min(5000, new_ms)))
        self.time_offset_ms = new_ms
        self.cfg["time_offset_ms"] = new_ms
        save_cfg(self.cfg)
        self.time_offset_var.set(self._fmt_offset(new_ms))

    def _offset_minus(self):
        self._set_offset_ms(self.time_offset_ms - 100)

    def _offset_plus(self):
        self._set_offset_ms(self.time_offset_ms + 100)

    def _effective_elapsed(self) -> float:
        return (time.time() - self.rotation_start) + (self.time_offset_ms / 1000.0)

    # -------------------- sizing --------------------

    def _resize_dynamic(self, allow_shrink: bool = True):
        try:
            self.update_idletasks()
            w = self.winfo_width()
            x = self.winfo_x()
            y = self.winfo_y()

            req_h = self.winfo_reqheight()
            target_h = max(self._base_h, req_h)

            if not allow_shrink:
                target_h = max(target_h, self.winfo_height())

            self.geometry(f"{w}x{target_h}+{x}+{y}")
        except Exception:
            pass

    # -------------------- first-run instructions --------------------

    def _show_first_run_instructions(self):
        self.status.set("FIRST RUN — Press Ctrl+R to set timer region")
        self.next_name.set("Open Croesus timer, then Ctrl+R")
        self.countdown.set("--:--")

        if not bool(self.cfg.get("first_run_popup_shown", False)):
            messagebox.showinfo(
                "SusAlert Lite – First time setup",
                "First time setup (one-time):\n\n"
                "1) Open RuneScape and make sure the Croesus boss timer is visible.\n"
                "2) Press Ctrl+R\n"
                "3) Drag a box around the boss timer, then press Enter.\n\n"
                "After this, SusAlert auto-starts on every launch.\n\n"
                "TIP: Settings -> Demo Mode lets you test without RuneScape."
            )
            self.cfg["first_run_popup_shown"] = True
            save_cfg(self.cfg)

    # -------------------- close & persistence --------------------

    def _safe_close(self):
        self.running = False
        self.demo_running = False
        self._save_position()

        try:
            if self._help_win and self._help_win.winfo_exists():
                self._help_win.destroy()
        except Exception:
            pass

        try:
            self.msbt.hide()
        except Exception:
            pass

        self.destroy()

    def _save_position(self):
        try:
            self.cfg["window_x"] = int(self.winfo_x())
            self.cfg["window_y"] = int(self.winfo_y())
            save_cfg(self.cfg)
        except Exception:
            pass

    # -------------------- window dragging --------------------

    def _start_move(self, event):
        self._drag_off_x = event.x
        self._drag_off_y = event.y

    def _do_move(self, event):
        x = self.winfo_pointerx() - self._drag_off_x
        y = self.winfo_pointery() - self._drag_off_y
        self.geometry(f"+{x}+{y}")

    def _end_move(self, _event=None):
        self._save_position()

    # -------------------- setup --------------------

    def _cfg_region(self) -> Optional[Region]:
        r = self.cfg.get("timer_region")
        if not r:
            return None
        return Region(int(r["x"]), int(r["y"]), int(r["w"]), int(r["h"]))

    def _setup_complete(self) -> bool:
        tpl_path = BASE / self.cfg.get("timer_template_path", "assets/timer_template.png")
        tpl_ok = tpl_path.exists() and (self.matcher.template is not None)
        return bool(self.cfg.get("setup_complete")) and (self.timer_region is not None) and tpl_ok

    def first_time_setup(self):
        self.status.set("SETUP — drag timer area, Enter to confirm")
        self.next_name.set("Boss timer must be visible")
        self.countdown.set("--:--")

        with mss.mss() as sct:
            mon = sct.monitors[1]
            grabbed = sct.grab(mon)
            img = Image.frombytes("RGB", grabbed.size, grabbed.rgb)

        def done(sel):
            if not sel:
                self.status.set("SETUP — cancelled (Ctrl+R to retry)")
                self.next_name.set("Press Ctrl+R to retry")
                self.countdown.set("--:--")
                return

            x, y, w, h = sel
            self.timer_region = Region(x, y, w, h)
            self.cfg["timer_region"] = {"x": x, "y": y, "w": w, "h": h}
            save_cfg(self.cfg)

            gray = self._grab_gray()
            if gray is None:
                messagebox.showinfo("Setup error", "Could not capture template. Try again with timer visible.")
                self.status.set("SETUP — failed (Ctrl+R to retry)")
                self.next_name.set("Boss timer must be visible")
                self.countdown.set("--:--")
                return

            self.matcher.save_template(gray)
            self.cfg["setup_complete"] = True
            save_cfg(self.cfg)

            self.status.set("WAITING — encounter start")
            self.next_name.set("Next: Red Spore")
            self.countdown.set("00:13")
            self.start_monitoring()

        RegionSelector(self, img, done, bg=self.bg)

    def reset_setup(self):
        self.running = False
        self.demo_running = False
        self.encounter_active = False
        self.last_event_fire.clear()
        self.last_banner_fire.clear()
        self.energy_button_shown = False
        self._hide_energy_button()

        self.cfg["setup_complete"] = False
        self.cfg["timer_region"] = None
        save_cfg(self.cfg)

        tpl_path = BASE / self.cfg.get("timer_template_path", "assets/timer_template.png")
        try:
            if tpl_path.exists():
                tpl_path.unlink()
        except Exception:
            pass

        self.timer_region = None
        self.matcher.template = None
        self.after(50, self.first_time_setup)

    # -------------------- capture --------------------

    def _grab_gray(self) -> Optional[np.ndarray]:
        r = self.timer_region
        if not r:
            return None
        with mss.mss() as sct:
            img = sct.grab({"left": r.x, "top": r.y, "width": r.w, "height": r.h})
            frame = np.array(img)[:, :, :3]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)

    # -------------------- energy fungi button --------------------

    def _show_energy_button(self):
        if not self.energy_border.winfo_ismapped():
            self.energy_border.pack(fill="x", padx=10, pady=(4, 8))
        self._resize_dynamic(allow_shrink=False)

    def _hide_energy_button(self):
        if self.energy_border.winfo_ismapped():
            self.energy_border.pack_forget()
        self._resize_dynamic(allow_shrink=True)

    def resume_rotation(self):
        self.rotation_start = time.time()
        self.energy_button_shown = False
        self._hide_energy_button()
        if bool(self.cfg.get("event_sound", True)):
            play_alert_sound(self)

    # -------------------- banner alerts (inside main window) --------------------

    def _banner_hide_now(self):
        self._banner_hide_job = None
        self.banner_label.place_forget()

    def _show_banner_text(self, text: str, hold_ms: int):
        if self._banner_seq_job:
            try:
                self.after_cancel(self._banner_seq_job)
            except Exception:
                pass
            self._banner_seq_job = None
        if self._banner_hide_job:
            try:
                self.after_cancel(self._banner_hide_job)
            except Exception:
                pass
            self._banner_hide_job = None

        self.banner_label.config(text=text)
        self.banner_label.place(relx=0.5, rely=0.55, anchor="center")
        self.banner_label.lift()
        self._banner_hide_job = self.after(max(250, int(hold_ms)), self._banner_hide_now)

    def _banner_countdown(self, label: str, seconds: int):
        if seconds <= 0:
            self._show_banner_text(f"{label} NOW!", int(self.cfg.get("banner_hold_ms", 1200)))
            return

        if self._banner_seq_job:
            try:
                self.after_cancel(self._banner_seq_job)
            except Exception:
                pass
            self._banner_seq_job = None
        if self._banner_hide_job:
            try:
                self.after_cancel(self._banner_hide_job)
            except Exception:
                pass
            self._banner_hide_job = None

        def step(s: int):
            if not bool(self.cfg.get("banner_enabled", False)):
                self._banner_hide_now()
                return
            if s > 0:
                self.banner_label.config(text=f"{label} in {s}…")
                self.banner_label.place(relx=0.5, rely=0.55, anchor="center")
                self.banner_label.lift()
                self._banner_seq_job = self.after(1000, lambda: step(s - 1))
            else:
                self._show_banner_text(f"{label} NOW!", int(self.cfg.get("banner_hold_ms", 1200)))

        step(int(seconds))

    # -------------------- settings panel --------------------

    def toggle_settings(self, *_):
        if self.settings_frame.winfo_ismapped():
            self.settings_frame.pack_forget()
            self._resize_dynamic(allow_shrink=True)
            self.cfg["settings_open"] = False
            save_cfg(self.cfg)
        else:
            self.settings_frame.pack(fill="x", padx=10, pady=(4, 6), after=self.header)
            self._resize_dynamic(allow_shrink=True)
            self.cfg["settings_open"] = True
            save_cfg(self.cfg)

    def _apply_settings(self):
        self.cfg["always_on_top"] = bool(self.var_topmost.get())
        self.cfg["event_sound"] = bool(self.var_sound.get())

        self.cfg["demo_mode"] = bool(self.var_demo.get())

        self.cfg["banner_enabled"] = bool(self.var_banner.get())
        self.cfg["banner_mode"] = str(self.var_banner_mode.get())
        try:
            self.cfg["banner_countdown_s"] = int(self.var_banner_countdown.get())
        except Exception:
            self.cfg["banner_countdown_s"] = 3
        try:
            self.cfg["banner_hold_ms"] = int(self.var_banner_hold.get())
        except Exception:
            self.cfg["banner_hold_ms"] = 1200

        self.cfg["msbt_enabled"] = bool(self.var_msbt.get())
        self.cfg["msbt_anchor"] = str(self.var_msbt_anchor.get())
        try:
            self.cfg["msbt_font_size"] = int(self.var_msbt_font_size.get())
        except Exception:
            self.cfg["msbt_font_size"] = 30
        try:
            self.cfg["msbt_duration_ms"] = int(self.var_msbt_duration.get())
        except Exception:
            self.cfg["msbt_duration_ms"] = 2500
        try:
            self.cfg["msbt_step_ms"] = int(self.var_msbt_step.get())
        except Exception:
            self.cfg["msbt_step_ms"] = 250

        save_cfg(self.cfg)

        try:
            self.attributes("-topmost", bool(self.cfg.get("always_on_top", True)))
        except Exception:
            pass

        try:
            self.msbt._apply_position()
        except Exception:
            pass

        self._resize_dynamic(allow_shrink=True)

    def _msbt_set_pos(self):
        self.msbt.set_position_mode(on_done=self._apply_settings)

    # -------------------- demo --------------------

    def demo_start(self):
        if self.demo_running:
            return
        self.demo_running = True
        self.encounter_active = True
        self.rotation_start = time.time()
        self.energy_button_shown = False
        self.last_event_fire.clear()
        self.last_banner_fire.clear()
        self._hide_energy_button()
        self.status.set("RUNNING (DEMO)")

    def demo_stop(self):
        if not self.demo_running:
            return
        self.demo_running = False
        self.encounter_active = False
        self.energy_button_shown = False
        self.last_event_fire.clear()
        self.last_banner_fire.clear()
        self._hide_energy_button()
        self.status.set("WAITING — encounter start")
        self.next_name.set("Next: Red Spore")
        self.countdown.set("00:13")
        self._banner_hide_now()
        self.msbt.hide()

    # -------------------- UI --------------------

    def _build_ui(self):
        self.header = tk.Frame(self, bg=self.header_bg, height=20)
        self.header.pack(fill="x")

        info_btn = tk.Label(
            self.header, text="ⓘ", bg=self.header_bg, fg=self.muted,
            font=("Segoe UI", 11, "bold"), cursor="hand2"
        )
        info_btn.pack(side="left", padx=(8, 0))
        info_btn.bind("<Button-1>", lambda e: self.open_help())
        info_btn.bind("<Enter>", lambda e: info_btn.config(fg=self.fg))
        info_btn.bind("<Leave>", lambda e: info_btn.config(fg=self.muted))

        gear_btn = tk.Label(
            self.header, text="⚙", bg=self.header_bg, fg=self.muted,
            font=("Segoe UI", 11, "bold"), cursor="hand2"
        )
        gear_btn.pack(side="left", padx=(6, 0))
        gear_btn.bind("<Button-1>", self.toggle_settings)
        gear_btn.bind("<Enter>", lambda e: gear_btn.config(fg=self.fg))
        gear_btn.bind("<Leave>", lambda e: gear_btn.config(fg=self.muted))

        title = tk.Label(
            self.header, text="SusAlert Lite", bg=self.header_bg, fg=self.muted,
            font=("Segoe UI", 9)
        )
        title.pack(side="left", padx=8)

        close_btn = tk.Label(
            self.header, text="✕", bg=self.header_bg, fg="#ff5c5c",
            font=("Segoe UI", 11, "bold"), cursor="hand2"
        )
        close_btn.pack(side="right", padx=8)
        close_btn.bind("<Button-1>", lambda e: self._safe_close())
        close_btn.bind("<Enter>", lambda e: close_btn.config(fg="#ff1f1f"))
        close_btn.bind("<Leave>", lambda e: close_btn.config(fg="#ff5c5c"))

        for wdg in (self.header, title):
            wdg.bind("<ButtonPress-1>", self._start_move)
            wdg.bind("<B1-Motion>", self._do_move)
            wdg.bind("<ButtonRelease-1>", self._end_move)

        # Settings panel (hidden by default)
        self.settings_frame = tk.Frame(self, bg=self.bg)

        self.var_topmost = tk.BooleanVar(value=bool(self.cfg.get("always_on_top", True)))
        self.var_sound = tk.BooleanVar(value=bool(self.cfg.get("event_sound", True)))
        self.var_demo = tk.BooleanVar(value=bool(self.cfg.get("demo_mode", False)))

        self.var_banner = tk.BooleanVar(value=bool(self.cfg.get("banner_enabled", False)))
        self.var_banner_mode = tk.StringVar(value=str(self.cfg.get("banner_mode", "COUNTDOWN")))
        self.var_banner_countdown = tk.StringVar(value=str(int(self.cfg.get("banner_countdown_s", 3))))
        self.var_banner_hold = tk.StringVar(value=str(int(self.cfg.get("banner_hold_ms", 1200))))

        self.var_msbt = tk.BooleanVar(value=bool(self.cfg.get("msbt_enabled", True)))
        self.var_msbt_anchor = tk.StringVar(value=str(self.cfg.get("msbt_anchor", "lower_center")))
        self.var_msbt_font_size = tk.StringVar(value=str(int(self.cfg.get("msbt_font_size", 30))))
        self.var_msbt_duration = tk.StringVar(value=str(int(self.cfg.get("msbt_duration_ms", 2500))))
        self.var_msbt_step = tk.StringVar(value=str(int(self.cfg.get("msbt_step_ms", 250))))

        def mk_cb(text, var):
            cb = tk.Checkbutton(
                self.settings_frame, text=text, variable=var,
                bg=self.bg, fg=self.fg, activebackground=self.bg, activeforeground=self.fg,
                selectcolor=self.bg, highlightthickness=0,
                command=self._apply_settings
            )
            cb.pack(anchor="w")
            return cb

        mk_cb("Always on top", self.var_topmost)
        mk_cb("Sound (beep) on mechanic", self.var_sound)
        mk_cb("Demo mode (no screen capture)", self.var_demo)

        demo_row = tk.Frame(self.settings_frame, bg=self.bg)
        demo_row.pack(fill="x", pady=(6, 0))
        tk.Button(
            demo_row, text="Start Demo",
            command=self.demo_start, bg="#303030", fg=self.fg,
            relief="flat", padx=10, pady=6
        ).pack(side="left")
        tk.Button(
            demo_row, text="Stop Demo",
            command=self.demo_stop, bg="#303030", fg=self.fg,
            relief="flat", padx=10, pady=6
        ).pack(side="left", padx=8)

        sep1 = tk.Label(self.settings_frame, text="— Alerts —", bg=self.bg, fg=self.muted, font=("Segoe UI", 9, "bold"))
        sep1.pack(anchor="w", pady=(8, 0))

        mk_cb("Banner alerts (inside app)", self.var_banner)

        row = tk.Frame(self.settings_frame, bg=self.bg)
        row.pack(fill="x", pady=(4, 0))
        tk.Label(row, text="Banner mode:", bg=self.bg, fg=self.muted, font=("Segoe UI", 9)).pack(side="left")
        opt = tk.OptionMenu(row, self.var_banner_mode, "NOW", "COUNTDOWN", command=lambda *_: self._apply_settings())
        opt.config(bg="#303030", fg=self.fg, activebackground="#404040", activeforeground=self.fg,
                   relief="flat", highlightthickness=0)
        opt["menu"].config(bg="#303030", fg=self.fg)
        opt.pack(side="left", padx=6)

        tk.Label(row, text="Countdown:", bg=self.bg, fg=self.muted, font=("Segoe UI", 9)).pack(side="left", padx=(10, 0))
        sp = tk.Spinbox(
            row, from_=1, to=10, width=3,
            textvariable=self.var_banner_countdown,
            bg="#303030", fg=self.fg, relief="flat",
            highlightthickness=0, command=self._apply_settings
        )
        sp.pack(side="left", padx=6)
        sp.bind("<KeyRelease>", lambda e: self._apply_settings())

        rowh = tk.Frame(self.settings_frame, bg=self.bg)
        rowh.pack(fill="x", pady=(4, 0))
        tk.Label(rowh, text="Hold (ms):", bg=self.bg, fg=self.muted, font=("Segoe UI", 9)).pack(side="left")
        sph = tk.Spinbox(
            rowh, from_=250, to=5000, increment=50, width=5,
            textvariable=self.var_banner_hold,
            bg="#303030", fg=self.fg, relief="flat",
            highlightthickness=0, command=self._apply_settings
        )
        sph.pack(side="left", padx=6)
        sph.bind("<KeyRelease>", lambda e: self._apply_settings())

        sep2 = tk.Label(self.settings_frame, text="— MSBT Announcements —", bg=self.bg, fg=self.muted, font=("Segoe UI", 9, "bold"))
        sep2.pack(anchor="w", pady=(8, 0))

        mk_cb("Enable MSBT overlay", self.var_msbt)

        row2 = tk.Frame(self.settings_frame, bg=self.bg)
        row2.pack(fill="x", pady=(4, 0))
        tk.Label(row2, text="Anchor:", bg=self.bg, fg=self.muted, font=("Segoe UI", 9)).pack(side="left")
        opt2 = tk.OptionMenu(
            row2, self.var_msbt_anchor,
            "lower_center", "center", "custom", "top_left", "top", "top_right", "bottom_left", "bottom", "bottom_right",
            command=lambda *_: self._apply_settings()
        )
        opt2.config(bg="#303030", fg=self.fg, activebackground="#404040", activeforeground=self.fg,
                    relief="flat", highlightthickness=0)
        opt2["menu"].config(bg="#303030", fg=self.fg)
        opt2.pack(side="left", padx=6)

        tk.Label(row2, text="Font:", bg=self.bg, fg=self.muted, font=("Segoe UI", 9)).pack(side="left", padx=(10, 0))
        sp2 = tk.Spinbox(
            row2, from_=20, to=80, width=4,
            textvariable=self.var_msbt_font_size,
            bg="#303030", fg=self.fg, relief="flat",
            highlightthickness=0, command=self._apply_settings
        )
        sp2.pack(side="left", padx=6)
        sp2.bind("<KeyRelease>", lambda e: self._apply_settings())

        row3 = tk.Frame(self.settings_frame, bg=self.bg)
        row3.pack(fill="x", pady=(4, 0))
        tk.Label(row3, text="Duration (ms):", bg=self.bg, fg=self.muted, font=("Segoe UI", 9)).pack(side="left")
        sp3 = tk.Spinbox(
            row3, from_=500, to=8000, increment=100, width=6,
            textvariable=self.var_msbt_duration,
            bg="#303030", fg=self.fg, relief="flat",
            highlightthickness=0, command=self._apply_settings
        )
        sp3.pack(side="left", padx=6)
        sp3.bind("<KeyRelease>", lambda e: self._apply_settings())

        tk.Label(row3, text="Step (ms):", bg=self.bg, fg=self.muted, font=("Segoe UI", 9)).pack(side="left", padx=(10, 0))
        sp4 = tk.Spinbox(
            row3, from_=50, to=1000, increment=50, width=5,
            textvariable=self.var_msbt_step,
            bg="#303030", fg=self.fg, relief="flat",
            highlightthickness=0, command=self._apply_settings
        )
        sp4.pack(side="left", padx=6)
        sp4.bind("<KeyRelease>", lambda e: self._apply_settings())

        tk.Button(
            self.settings_frame, text="Set MSBT position (drag preview)",
            command=self._msbt_set_pos, bg="#303030", fg=self.fg, relief="flat", padx=10, pady=6
        ).pack(anchor="w", pady=(6, 0))

        # Main content
        tk.Label(
            self, textvariable=self.status, bg=self.bg, fg=self.fg,
            font=("Segoe UI", 10, "bold"), anchor="w"
        ).pack(fill="x", padx=10, pady=(8, 2))

        tk.Label(
            self, textvariable=self.next_name, bg=self.bg, fg=self.muted,
            font=("Segoe UI", 9), anchor="w"
        ).pack(fill="x", padx=10)

        # Timer row with +/- and offset label
        timer_row = tk.Frame(self, bg=self.bg)
        timer_row.pack(fill="x", padx=10, pady=(0, 2))

        tk.Button(
            timer_row, text="−", command=self._offset_minus,
            bg="#303030", fg=self.fg, relief="flat",
            width=2, padx=6, pady=6
        ).pack(side="left")

        tk.Label(
            timer_row, textvariable=self.countdown, bg=self.bg, fg=self.fg,
            font=("Consolas", 26, "bold"), anchor="w"
        ).pack(side="left", padx=8)

        tk.Button(
            timer_row, text="+", command=self._offset_plus,
            bg="#303030", fg=self.fg, relief="flat",
            width=2, padx=6, pady=6
        ).pack(side="left")

        tk.Label(
            timer_row, textvariable=self.time_offset_var,
            bg=self.bg, fg=self.muted, font=("Segoe UI", 9, "bold")
        ).pack(side="right")

        # Energy button with bright yellow surround (hidden by default)
        self.energy_border = tk.Frame(self, bg="#ffeb3b")
        self.resume_btn = tk.Button(
            self.energy_border,
            text="MID cleared",
            command=self.resume_rotation,
            bg="#303030",
            fg=self.fg,
            activebackground="#3a3a3a",
            activeforeground=self.fg,
            relief="flat",
            borderwidth=0,
            padx=10,
            pady=8,
        )
        self.resume_btn.pack(fill="x", padx=3, pady=3)
        self.energy_border.pack(fill="x", padx=10, pady=(4, 8))
        self.energy_border.pack_forget()

        # Integrated banner (hidden until used)
        self.banner_label = tk.Label(
            self, text="",
            bg="#151515", fg=self.fg,
            font=("Segoe UI", 12, "bold"),
            padx=12, pady=8, relief="flat",
        )
        self.banner_label.place_forget()

    # -------------------- monitoring --------------------

    def start_monitoring(self):
        if self.running:
            return
        if not bool(self.cfg.get("demo_mode", False)) and not self._setup_complete():
            self._show_first_run_instructions()
            return
        self.running = True
        self.worker = threading.Thread(target=self._loop, daemon=True)
        self.worker.start()

    def _loop(self):
        poll_s = float(self.cfg.get("poll_ms", 120)) / 1000.0
        miss_reset_s = 4.0
        cooldown_s = float(self.cfg.get("cooldown_s", 1.0))
        tolerance = max(0.06, poll_s * 1.2)

        self.after(0, lambda: self.status.set(
            "WAITING (DEMO) — press Start Demo" if self.cfg.get("demo_mode", False) else "WAITING — encounter start"
        ))
        self.after(0, lambda: self.next_name.set("Next: Red Spore"))
        self.after(0, lambda: self.countdown.set("00:13"))

        last_demo_hint = 0.0

        while self.running:
            t0 = time.time()
            now = t0

            try:
                if bool(self.cfg.get("demo_mode", False)):
                    if not self.demo_running:
                        if now - last_demo_hint > 2.5:
                            last_demo_hint = now
                            self.after(0, lambda: self.status.set("WAITING (DEMO) — press Start Demo"))
                        time.sleep(0.10)
                        continue
                    present = True
                else:
                    gray = self._grab_gray()
                    if gray is None:
                        time.sleep(0.2)
                        continue
                    score = self.matcher.score(gray)
                    present = score >= float(self.cfg.get("template_threshold", 0.62))

                if present:
                    self.last_seen_timer = now
                    if not self.encounter_active:
                        self.encounter_active = True
                        self.rotation_start = now
                        self.energy_button_shown = False
                        self.last_event_fire.clear()
                        self.last_banner_fire.clear()
                        self.after(0, self._hide_energy_button)
                        self.after(0, lambda: self.status.set("RUNNING" + (" (DEMO)" if self.cfg.get("demo_mode", False) else "")))
                else:
                    if self.encounter_active and (now - self.last_seen_timer) >= miss_reset_s:
                        self.encounter_active = False
                        self.energy_button_shown = False
                        self.last_event_fire.clear()
                        self.last_banner_fire.clear()
                        self.after(0, self._hide_energy_button)
                        self.after(0, lambda: self.status.set("WAITING — encounter start"))
                        self.after(0, lambda: self.next_name.set("Next: Red Spore"))
                        self.after(0, lambda: self.countdown.set("00:13"))
                        self.after(0, self._banner_hide_now)
                        self.after(0, self.msbt.hide)

                if self.encounter_active:
                    rot_t = max(0.0, self._effective_elapsed())
                    nxt_sec, nxt_name = self._next_event(rot_t)
                    remaining = int(round(nxt_sec - rot_t))

                    self.after(0, lambda n=nxt_name: self.next_name.set(f"Next: {n}"))
                    self.after(0, lambda r=remaining: self.countdown.set(self._fmt_mmss(r)))
                    self.after(0, lambda: self.status.set("RUNNING" + (" (DEMO)" if self.cfg.get("demo_mode", False) else "")))

                    # Banner countdown triggers
                    if bool(self.cfg.get("banner_enabled", False)) and str(self.cfg.get("banner_mode", "COUNTDOWN")) == "COUNTDOWN":
                        cd_s = int(self.cfg.get("banner_countdown_s", 3))
                        for sec, name in ROTATION_EVENTS:
                            trigger_t = sec - cd_s
                            if trigger_t >= 0 and abs(rot_t - trigger_t) < tolerance:
                                key = f"bcd:{sec}:{name}"
                                if now - self.last_banner_fire.get(key, 0.0) >= max(0.8, cooldown_s):
                                    self.last_banner_fire[key] = now
                                    self.after(0, lambda nm=name, s=cd_s: self._banner_countdown(nm, s))

                    # MSBT countdown triggers
                    if bool(self.cfg.get("msbt_enabled", True)) and str(self.cfg.get("banner_mode", "COUNTDOWN")) == "COUNTDOWN":
                        cd_s = int(self.cfg.get("banner_countdown_s", 3))
                        for sec, name in ROTATION_EVENTS:
                            trigger_t = sec - cd_s
                            if trigger_t >= 0 and abs(rot_t - trigger_t) < tolerance:
                                key = f"mcd:{sec}:{name}"
                                if now - self.last_banner_fire.get(key, 0.0) >= max(0.8, cooldown_s):
                                    self.last_banner_fire[key] = now
                                    self.after(0, lambda nm=name, s=cd_s: self.msbt.show_countdown(nm, s))

                    # Exact-time triggers
                    for sec, name in ROTATION_EVENTS:
                        if abs(rot_t - sec) < tolerance:
                            key = f"{sec}:{name}"
                            if now - self.last_event_fire.get(key, 0.0) >= cooldown_s:
                                self.last_event_fire[key] = now

                                if bool(self.cfg.get("event_sound", True)):
                                    self.after(0, lambda: play_alert_sound(self))

                                # Banner NOW (if mode NOW)
                                if bool(self.cfg.get("banner_enabled", False)) and str(self.cfg.get("banner_mode", "COUNTDOWN")) == "NOW":
                                    hold = int(self.cfg.get("banner_hold_ms", 1200))
                                    self.after(0, lambda nm=name, h=hold: self._show_banner_text(f"{nm} NOW!", h))

                                # MSBT NOW (if mode NOW)
                                if bool(self.cfg.get("msbt_enabled", True)) and str(self.cfg.get("banner_mode", "COUNTDOWN")) == "NOW":
                                    dur = int(self.cfg.get("msbt_duration_ms", 2500))
                                    self.after(0, lambda nm=name, d=dur: self.msbt.show_text(f"{nm} NOW!", d))

                                if sec == ENERGY_TIME and not self.energy_button_shown:
                                    self.energy_button_shown = True
                                    self.after(0, self._show_energy_button)

            except Exception:
                print("SusAlert loop error:\n" + traceback.format_exc())

            dt = time.time() - t0
            time.sleep(max(0.02, poll_s - dt))


def main():
    try:
        (BASE / "assets").mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    App().mainloop()


if __name__ == "__main__":
    main()
