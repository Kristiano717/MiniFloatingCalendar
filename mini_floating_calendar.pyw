#!/usr/bin/env python3
"""Mini Floating Calendar - a floating calendar for Windows that pops up reminders.

Double-click this file to run it (it opens with pythonw, so no console window).
Reminders are stored in %APPDATA%\\MiniFloatingCalendar\\reminders.json.
For the system-tray icon:  pip install pystray pillow
"""

import calendar
import ctypes
import json
import os
import queue
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import traceback
import urllib.request
import uuid
from ctypes import wintypes
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import date, datetime, timedelta, timezone

try:
    import winsound
except ImportError:  # not on Windows
    winsound = None

APP = "MiniFloatingCalendar"
TITLE = "Mini Floating Calendar"
FROZEN = getattr(sys, "frozen", False)
SCRIPT = sys.executable if FROZEN else os.path.abspath(__file__)
APP_DIR = os.path.dirname(SCRIPT)
DATA_DIR = os.environ.get("FLOATCAL_DATA") or os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")), APP)
REM_FILE = os.path.join(DATA_DIR, "reminders.json")
SET_FILE = os.path.join(DATA_DIR, "settings.json")
LOG_FILE = os.path.join(DATA_DIR, "error.log")
STARTUP_LNK = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                           "Start Menu", "Programs", "Startup", "MiniFloatingCalendar.lnk")
LOCK_PORT = 47613
NO_WINDOW = 0x08000000
HOTKEY_LABEL = "Ctrl+Alt+R"
NTFY_SERVER = "https://ntfy.sh"

# ---------------------------------------------------------------- themes

THEMES = {
    "Vintage Almanac": dict(
        dark=False, F="Georgia", FH="Georgia", FM="Courier New",
        upper=True, spaced=True, orn=("\u2726 ", " \u2726"),
        bg="#f4ead5", panel="#eadcbc", fg="#3b2a1a", dim="#7a6248", faint="#a58d6a",
        accent="#b5432a", accent_fg="#fbf3e2", event="#e3c890", ok="#5f7a3a",
        danger="#a8231a", warn="#b7791f", orange="#c2611f", border="#8a6a45",
        chip_fg="#fbf3e2"),
    "Daylight": dict(
        dark=False, F="Segoe UI", FH="Segoe UI Semibold", FM="Consolas",
        upper=False, spaced=False, orn=("", ""),
        bg="#f7f7fa", panel="#ebecf2", fg="#1f2230", dim="#6b6f80", faint="#a3a7b5",
        accent="#4f6bed", accent_fg="#ffffff", event="#dde4ff", ok="#2f9e6a",
        danger="#d64545", warn="#c98a00", orange="#e07a1f", border="#c9ccd6",
        chip_fg="#ffffff"),
    "Midnight Noir": dict(
        dark=True, F="Segoe UI", FH="Segoe UI Semibold", FM="Consolas",
        upper=False, spaced=False, orn=("", ""),
        bg="#1c1d24", panel="#272935", fg="#e8e8ee", dim="#8b8e9c", faint="#5a5d6b",
        accent="#6c8cff", accent_fg="#ffffff", event="#353b5e", ok="#4cd295",
        danger="#ff6b6b", warn="#ffb454", orange="#ff9f43", border="#3a3d4c",
        chip_fg="#ffffff"),
    "Retro Terminal": dict(
        dark=True, F="Consolas", FH="Consolas", FM="Consolas",
        upper=True, spaced=False, orn=("> ", "_"),
        bg="#0a0f09", panel="#111a0f", fg="#a6ff8f", dim="#5fae55", faint="#3a6b33",
        accent="#39ff14", accent_fg="#0a0f09", event="#1e3d19", ok="#39ff14",
        danger="#ff5050", warn="#ffd23f", orange="#ff9f1c", border="#2e5a28",
        chip_fg="#0a0f09"),
    "Synthwave '84": dict(
        dark=True, F="Trebuchet MS", FH="Trebuchet MS", FM="Consolas",
        upper=True, spaced=True, orn=("\u2605 ", " \u2605"),
        bg="#1a1033", panel="#28164d", fg="#ffeaff", dim="#c79bdc", faint="#7d5a9c",
        accent="#ff2fb9", accent_fg="#ffffff", event="#46207a", ok="#2de2e6",
        danger="#ff3864", warn="#f9c80e", orange="#ff6c11", border="#7a35c9",
        chip_fg="#ffffff"),
}
DEFAULT_THEME = "Vintage Almanac"
C = dict(THEMES[DEFAULT_THEME])   # current theme; replaced in place when the theme changes


def f(size, *style):
    return (C["F"], size, *style)


def fh(size, *style):
    return (C["FH"], size, "bold", *style)


def fm(size, *style):
    return (C["FM"], size, *style)


def heading(text, spaced=True):
    t = text.upper() if C["upper"] else text
    if spaced and C["spaced"]:
        t = " ".join(t)
    return f"{C['orn'][0]}{t}{C['orn'][1]}"


CATEGORIES = [("Personal", "#4f7cac"), ("Work", "#d08c2c"), ("College", "#8e6bbf"),
              ("Bills", "#c0453a"), ("Health", "#4f9a62"), ("Other", "#8a8a7a")]
CAT_COLOR = dict(CATEGORIES)


def cat_color(r):
    return CAT_COLOR.get(r.get("category") or "Personal", CAT_COLOR["Personal"])


DEFAULT_SETTINGS = {"x": None, "y": None, "topmost": True, "alpha": 1.0,
                    "collapsed": False, "hidden": False, "allday_time": "09:00",
                    "week_start": 0, "theme": DEFAULT_THEME, "hold_fullscreen": True,
                    "auto_update": True, "phone_topic": "", "big_geom": None,
                    "tray_hint_shown": False,
                    # automatic light/dark: "off", "schedule" (by time) or "windows" (follow Windows)
                    "auto_theme": "schedule", "light_theme": DEFAULT_THEME,
                    "dark_theme": "Midnight Noir", "light_start": "07:00", "dark_start": "19:00"}
AUTO_MODES = [("off", "Fixed theme (no switching)"), ("schedule", "Switch light/dark by time"),
              ("windows", "Follow Windows light/dark setting")]


def windows_light():
    """True if Windows apps are set to light mode, False for dark, None if unknown."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return bool(winreg.QueryValueEx(k, "AppsUseLightTheme")[0])
    except (OSError, ImportError):
        return None

REPEATS = [("none", "Does not repeat"), ("daily", "Every day"), ("weekly", "Every week"),
           ("monthly", "Every month"), ("yearly", "Every year")]
ADVANCE_CHOICES = [0, 1, 2, 3, 7]


def adv_label(n):
    if not n:
        return "No early reminder"
    if n == 7:
        return "1 week before"
    return f"{n} day{'s' if n != 1 else ''} before"


def adv_from_label(s):
    if s.startswith("No"):
        return 0
    if "week" in s:
        return 7
    return int(s.split()[0])


# ---------------------------------------------------------------- helpers

def log_error(text):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as fh_:
            fh_.write(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}]\n{text}\n")
    except OSError:
        pass


def parse_time(s):
    """'17:30', '5:30 pm', '5pm', '' -> 'HH:MM' or '' (all day)."""
    s = (s or "").strip().lower().replace(".", "").replace(" ", "")
    if not s:
        return ""
    m = re.fullmatch(r"(\d{1,2})(?::?(\d{2}))?(am|pm)?", s)
    if not m:
        raise ValueError(s)
    h, mi, ap = int(m[1]), int(m[2] or 0), m[3]
    if ap:
        if not 1 <= h <= 12:
            raise ValueError(s)
        h = h % 12 + (12 if ap == "pm" else 0)
    if not (0 <= h < 24 and 0 <= mi < 60):
        raise ValueError(s)
    return f"{h:02d}:{mi:02d}"


DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y",
                "%d %B %Y", "%b %d %Y", "%B %d %Y")
SHORT_FORMATS = ("%d %b", "%d %B", "%b %d", "%B %d", "%d/%m")


def parse_date(s):
    """'1 Dec 2026', '2026-12-01', '01/12/2026', '1 dec' -> date."""
    s = " ".join(s.replace(",", " ").split())
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    today = date.today()
    for fmt in SHORT_FORMATS:
        try:
            d = datetime.strptime(f"{s} 2000", fmt + " %Y").date()
        except ValueError:
            continue
        try:
            d = d.replace(year=today.year)
            if d < today:
                d = d.replace(year=today.year + 1)
        except ValueError:
            pass
        return d
    raise ValueError(s)


def clamp_day(y, m, d):
    return date(y, m, min(d, calendar.monthrange(y, m)[1]))


def add_months(d, n, day=None):
    m = d.month - 1 + n
    return clamp_day(d.year + m // 12, m % 12 + 1, day or d.day)


def occurs_on(r, d):
    start = date.fromisoformat(r["date"])
    rep = r.get("repeat", "none")
    if rep == "none":
        return d == start
    if d < start:
        return False
    anchor = date.fromisoformat(r.get("anchor") or r["date"])
    if rep == "daily":
        return True
    if rep == "weekly":
        return (d - start).days % 7 == 0
    if rep == "monthly":
        return d == clamp_day(d.year, d.month, anchor.day)
    if rep == "yearly":
        return d.month == anchor.month and d == clamp_day(d.year, d.month, anchor.day)
    return False


def next_occurrence(r, d):
    rep = r.get("repeat", "none")
    anchor = date.fromisoformat(r.get("anchor") or r["date"])
    if rep == "daily":
        return d + timedelta(days=1)
    if rep == "weekly":
        return d + timedelta(days=7)
    if rep == "monthly":
        return add_months(d.replace(day=1), 1, anchor.day)
    if rep == "yearly":
        return clamp_day(d.year + 1, anchor.month, anchor.day)
    return None


def fmt_time(t):
    if not t:
        return ""
    return datetime.strptime(t, "%H:%M").strftime("%I:%M %p").lstrip("0")


def short_time(t):
    if not t:
        return ""
    s = datetime.strptime(t, "%H:%M").strftime("%I:%M%p").lstrip("0").lower()
    return s.replace(":00", "")[:-1]   # 5:30pm -> 5:30p, 5:00pm -> 5p


def fmt_date(d):
    return f"{d:%a}, {d.day} {d:%b %Y}"


def format_when(r):
    d = date.fromisoformat(r["date"])
    return fmt_date(d) + (f" at {fmt_time(r['time'])}" if r.get("time") else " (all day)")


def rel_days(n):
    if n == 0:
        return "today"
    if n == 1:
        return "tomorrow"
    return f"in {n} days"


def shade(hex_, amt=22):
    """Lighten (dark themes) or darken (light themes) a colour for hover states."""
    if not C["dark"]:
        amt = -amt
    h = hex_.lstrip("#")
    return "#" + "".join(f"{max(0, min(255, int(h[i:i + 2], 16) + amt)):02x}" for i in (0, 2, 4))


class RECT(ctypes.Structure):
    _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                ("r", ctypes.c_long), ("b", ctypes.c_long)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT),
                ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]


def work_area(root):
    try:
        rc = RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rc), 0):
            return rc.l, rc.t, rc.r, rc.b
    except Exception:
        pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def virtual_screen(root):
    try:
        gm = ctypes.windll.user32.GetSystemMetrics
        x, y = gm(76), gm(77)
        return x, y, x + gm(78), y + gm(79)
    except Exception:
        return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def foreground_fullscreen():
    """True when the active window covers its whole monitor (game, video, slideshow)."""
    try:
        u = ctypes.windll.user32
        u.GetForegroundWindow.restype = wintypes.HWND
        hwnd = u.GetForegroundWindow()
        if not hwnd:
            return False
        buf = ctypes.create_unicode_buffer(256)
        u.GetClassNameW(wintypes.HWND(hwnd), buf, 256)
        if buf.value in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
            return False
        rc = RECT()
        u.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rc))
        u.MonitorFromWindow.restype = wintypes.HANDLE
        mon = u.MonitorFromWindow(wintypes.HWND(hwnd), 2)
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if not u.GetMonitorInfoW(wintypes.HANDLE(mon), ctypes.byref(mi)):
            return False
        m = mi.rcMonitor
        return rc.l <= m.l and rc.t <= m.t and rc.r >= m.r and rc.b >= m.b
    except Exception:
        return False


def dark_titlebar(win):
    if not C["dark"]:
        return
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        val = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(val), 4)
    except Exception:
        pass


def play_sound():
    if not winsound:
        return
    try:
        winsound.PlaySound("SystemNotification", winsound.SND_ALIAS | winsound.SND_ASYNC)
    except Exception:
        try:
            winsound.MessageBeep()
        except Exception:
            pass


def pythonw_path():
    p = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return p if os.path.exists(p) else sys.executable


def find_git():
    g = shutil.which("git")
    if g:
        return g
    for p in (r"C:\Program Files\Git\cmd\git.exe",
              os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\cmd\git.exe")):
        if os.path.exists(p):
            return p
    return None


def make_icon_image(size=64, alert=False):
    img = _icon_base(size)
    if alert:  # red "!" badge used while a reminder is waiting
        from PIL import ImageDraw
        s = size / 64
        d = ImageDraw.Draw(img)
        d.ellipse([34 * s, 30 * s, 63 * s, 59 * s], fill="#e0241b", outline="#ffffff", width=max(1, int(3 * s)))
        d.rectangle([46.5 * s, 36 * s, 50.5 * s, 48 * s], fill="#ffffff")
        d.rectangle([46.5 * s, 51 * s, 50.5 * s, 54.5 * s], fill="#ffffff")
    return img


def _icon_base(size):
    from PIL import Image, ImageDraw
    s = size / 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([3 * s, 8 * s, 61 * s, 61 * s], radius=9 * s, fill="#f4ead5",
                        outline="#3b2a1a", width=max(1, int(3 * s)))
    d.rounded_rectangle([3 * s, 8 * s, 61 * s, 26 * s], radius=9 * s, fill="#b5432a",
                        outline="#3b2a1a", width=max(1, int(3 * s)))
    d.rectangle([4.5 * s, 18 * s, 59.5 * s, 25 * s], fill="#b5432a")
    for x in (18, 42):
        d.rounded_rectangle([(x - 3) * s, 2 * s, (x + 3) * s, 16 * s], radius=2 * s,
                            fill="#3b2a1a")
    for row in range(3):
        for col in range(4):
            x0, y0 = (11 + col * 11) * s, (31 + row * 9.5) * s
            fill = "#b5432a" if (row, col) == (1, 2) else "#7a6248"
            d.rectangle([x0, y0, x0 + 6 * s, y0 + 5.5 * s], fill=fill)
    return img


def mkbtn(parent, text, cmd, bg=None, fg=None, font=None, padx=10, pady=4):
    """A flat label that behaves like a button (looks better than tk.Button)."""
    bg = bg or C["panel"]
    fg = fg or C["fg"]
    b = tk.Label(parent, text=text, bg=bg, fg=fg, font=font or f(9),
                 padx=padx, pady=pady, cursor="hand2")
    hover = shade(bg)
    b.bind("<Enter>", lambda e: b.config(bg=hover))
    b.bind("<Leave>", lambda e: b.config(bg=bg))
    b.bind("<Button-1>", lambda e: cmd())
    return b


def entry(parent, var, width, size=10):
    return tk.Entry(parent, textvariable=var, width=width, bg=C["panel"], fg=C["fg"],
                    insertbackground=C["fg"], relief="flat", font=f(size),
                    highlightthickness=1, highlightcolor=C["accent"],
                    highlightbackground=C["border"])


# ---------------------------------------------------------------- quick-add parser

NUMS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
NUM_RE = r"(\d+|an?|one|two|three|four|five|six|seven|eight|nine|ten)"
MONTH_RE = (r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
            r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
WD_RE = (r"(mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:r(?:s(?:day)?)?)?"
         r"|fri(?:day)?|sat(?:urday)?|sun(?:day)?)")


def _num(x):
    return int(x) if x.isdigit() else NUMS[x.lower()]


def _month(s):
    return ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
            "nov", "dec"].index(s[:3].lower()) + 1


def _wd(s):
    return ["mon", "tue", "wed", "thu", "fri", "sat", "sun"].index(s[:3].lower())


def parse_quick(text, now=None):
    """'apply for scholarship dec 1 5pm #college' -> reminder fields."""
    now = now or datetime.now()
    today = now.date()
    st = {"s": f" {text.strip()} "}
    res = {"date": None, "time": "", "repeat": "none", "advance": 0, "category": "Personal"}

    def take(pattern, fn):
        m = re.search(pattern, st["s"], re.I)
        if not m or fn(m) is False:
            return False
        st["s"] = st["s"][:m.start()] + " " + st["s"][m.end():]
        return True

    def upcoming_day(day):
        d = clamp_day(today.year, today.month, day)
        return d if d >= today else add_months(today.replace(day=1), 1, day)

    def next_wd(w, skip_today=False):
        ahead = (w - today.weekday()) % 7
        if skip_today and ahead == 0:
            ahead = 7
        return today + timedelta(days=ahead)

    def set_date(y, mo, d):
        try:
            res["date"] = date(y, mo, d)
        except ValueError:
            return False

    # category: #work, #bills ...
    def f_cat(m):
        name = m[1].lower()
        res["category"] = next((c for c, _ in CATEGORIES if c.lower().startswith(name)), "Other")
    take(r"#(\w+)", f_cat)

    # early reminder: "remind me 2 days before", "a week early"
    def f_adv(m):
        res["advance"] = _num(m[1]) * (7 if m[2].lower().startswith("week") else 1)
    (take(r"\b(?:remind(?:\s+me)?\s+)?" + NUM_RE + r"\s+(days?|weeks?)\s+(?:before|early|earlier|ahead|prior)\b", f_adv)
     or take(r"\bremind(?:\s+me)?\s+early\b", lambda m: res.update(advance=1)))

    # repeats
    def f_every_nth(m):
        day = int(m[1])
        if not 1 <= day <= 31:
            return False
        res.update(repeat="monthly", date=upcoming_day(day))
    if not (take(r"\b(?:every|each)\s+" + WD_RE + r"\b",
                 lambda m: res.update(repeat="weekly", date=next_wd(_wd(m[1]))))
            or take(r"\b(?:on\s+)?(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(?:every|each)\s+month\b", f_every_nth)
            or take(r"\bevery\s+(\d{1,2})(?:st|nd|rd|th)(?:\s+of\s+(?:the|every|each)\s+month)?\b", f_every_nth)):
        for pat, rep in ((r"\b(?:every\s*day|each\s+day|daily)\b", "daily"),
                         (r"\b(?:every|each)\s+week\b|\bweekly\b", "weekly"),
                         (r"\b(?:every|each)\s+month\b|\bmonthly\b", "monthly"),
                         (r"\b(?:every|each)\s+year\b|\byearly\b|\bannually\b", "yearly")):
            if take(pat, lambda m, rep=rep: res.update(repeat=rep)):
                break

    # relative: "in 3 days", "in 2 hours", "in 30 minutes"
    def f_in(m):
        n, unit = _num(m[1]), m[2].lower()
        if unit.startswith(("min", "hour", "hr")):
            dt = now + (timedelta(minutes=n) if unit.startswith("min") else timedelta(hours=n))
            if dt.second or dt.microsecond:
                dt = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
            res.update(date=dt.date(), time=f"{dt:%H:%M}")
        elif unit.startswith("day"):
            res["date"] = today + timedelta(days=n)
        elif unit.startswith("week"):
            res["date"] = today + timedelta(weeks=n)
        else:
            res["date"] = add_months(today, n)
    take(r"\bin\s+" + NUM_RE + r"\s+(minutes?|mins?|hours?|hrs?|days?|weeks?|months?)\b", f_in)

    # explicit time: 5pm, 5:30 pm, 17:30, at 5
    def f_ampm(m):
        h, mi = int(m[1]), int(m[2] or 0)
        if not (1 <= h <= 12 and mi < 60):
            return False
        res["time"] = f"{h % 12 + (12 if m[3].lower() == 'p' else 0):02d}:{mi:02d}"

    def f_at(m):
        h = int(m[1])
        if not 0 <= h <= 23:
            return False
        if 1 <= h <= 7:  # "at 5" almost always means 5 PM
            h += 12
        res["time"] = f"{h:02d}:00"
    if not res["time"]:
        (take(r"(?:\bat\s+|@\s*)?\b(\d{1,2})(?:[:.](\d{2}))?\s*([ap])\.?m\.?(?![a-z])", f_ampm)
         or take(r"(?:\bat\s+|@\s*)?\b([01]?\d|2[0-3])[:.]([0-5]\d)\b",
                 lambda m: res.update(time=f"{int(m[1]):02d}:{m[2]}"))
         or take(r"(?:\bat\s+|@\s*)(\d{1,2})\b(?![:./\d]|\s*(?:st|nd|rd|th)\b)", f_at))

    # explicit dates
    def f_dm(m, di, mi, yi):
        d, mo = int(m[di]), _month(m[mi])
        y = int(m[yi]) if m[yi] else today.year
        if set_date(y, mo, d) is False:
            return False
        if not m[yi] and res["date"] < today:
            set_date(y + 1, mo, d)

    def f_num(m):
        d, mo, y = int(m[1]), int(m[2]), m[3]
        yy = (int(y) + 2000 if len(y) == 2 else int(y)) if y else today.year
        if set_date(yy, mo, d) is False:
            return False
        if not y and res["date"] < today:
            set_date(yy + 1, mo, d)
    if res["date"] is None:
        (take(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b",
              lambda m: set_date(int(m[1]), int(m[2]), int(m[3])))
         or take(r"\b(?:on\s+)?(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + MONTH_RE
                 + r"\.?(?:,?\s+(\d{4}))?\b", lambda m: f_dm(m, 1, 2, 3))
         or take(r"\b(?:on\s+)?" + MONTH_RE + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b",
                 lambda m: f_dm(m, 2, 1, 3))
         or take(r"\b(?:on\s+)?(\d{1,2})/(\d{1,2})(?:/(\d{4}|\d{2}))?\b", f_num))

    # day words
    if res["date"] is None:
        (take(r"\bday\s+after\s+tomorrow\b", lambda m: res.update(date=today + timedelta(days=2)))
         or take(r"\b(?:tomorrow|tomorow|tmrw|tmrow|tmr)\b",
                 lambda m: res.update(date=today + timedelta(days=1)))
         or take(r"\btoday\b", lambda m: res.update(date=today))
         or take(r"\btonight\b", lambda m: res.update(date=today, time=res["time"] or "20:00")))

    # weekday: "on friday", "next monday"
    if res["date"] is None:
        take(r"\b(?:on\s+)?(next\s+|this\s+)?" + WD_RE + r"\b",
             lambda m: res.update(date=next_wd(_wd(m[2]), bool(m[1]) and m[1].lower().startswith("next"))))

    # day of month: "on the 5th", "1st"
    if res["date"] is None:
        def f_ord(m):
            day = int(m[1])
            if not 1 <= day <= 31:
                return False
            res["date"] = upcoming_day(day)
        take(r"\b(?:on\s+)?(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)\b", f_ord)

    # part of day
    if not res["time"]:
        for pat, t in ((r"\bnoon\b|\bmidday\b", "12:00"), (r"\bmidnight\b", "23:59"),
                       (r"\b(?:in\s+the\s+|this\s+)?morning\b", "09:00"),
                       (r"\b(?:in\s+the\s+|this\s+)?afternoon\b", "15:00"),
                       (r"\b(?:in\s+the\s+|this\s+)?evening\b", "18:00"),
                       (r"\b(?:at\s+)?night\b", "20:00")):
            if take(pat, lambda m, t=t: res.update(time=t)):
                break

    # what's left is the title
    t = " ".join(st["s"].split())
    t = re.sub(r"^(?:please\s+)?(?:remind\s+me\s+(?:to\s+|about\s+|of\s+)?|reminder\s*:?\s*|todo\s*:?\s*|to\s+)",
               "", t, flags=re.I)
    lead = r"(?:on|at|by|due|-|\u2013|,|:|@)"
    trail = r"(?:on|at|by|for|due|the|of|in|before|from|and|every|-|\u2013|,|:|@)"
    prev = None
    while prev != t:
        prev = t
        t = re.sub(r"^" + lead + r"(?:\s+|$)", "", t, flags=re.I).strip()
        t = re.sub(r"(?:^|\s+)" + trail + r"$", "", t, flags=re.I).strip()
        t = t.strip(" ,;:-\u2013")
    if not t:
        raise ValueError("What should I remind you about?")
    res["title"] = t[0].upper() + t[1:]

    if res["date"] is None:
        res["date"] = today
        if res["time"] and res["time"] <= f"{now:%H:%M}":
            res["date"] = today + timedelta(days=1)
    res["date"] = res["date"].isoformat()
    return res


# ---------------------------------------------------------------- .ics import / export

RRULE = {"daily": "DAILY", "weekly": "WEEKLY", "monthly": "MONTHLY", "yearly": "YEARLY"}


def ics_escape(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def ics_unescape(s):
    return (s.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",")
            .replace("\\;", ";").replace("\\\\", "\\"))


def ics_fold(line):
    out, cur, n = [], "", 0
    for ch in line:
        b = len(ch.encode("utf-8"))
        if n + b > 74:
            out.append(cur)
            cur, n = " ", 1
        cur += ch
        n += b
    out.append(cur)
    return "\r\n".join(out)


def export_ics(reminders, path):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    L = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//MiniFloatingCalendar//EN", "CALSCALE:GREGORIAN"]
    for r in reminders:
        d = date.fromisoformat(r["date"])
        L += ["BEGIN:VEVENT", f"UID:{r.get('ics_uid') or r['id'] + '@minifloatingcalendar'}",
              f"DTSTAMP:{stamp}"]
        if r.get("time"):
            s = datetime.strptime(f"{r['date']} {r['time']}", "%Y-%m-%d %H:%M")
            L += [f"DTSTART:{s:%Y%m%dT%H%M%S}", f"DTEND:{s + timedelta(minutes=30):%Y%m%dT%H%M%S}"]
        else:
            L += [f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{d + timedelta(days=1):%Y%m%d}"]
        L.append("SUMMARY:" + ics_escape(r["title"]))
        if r.get("notes"):
            L.append("DESCRIPTION:" + ics_escape(r["notes"]))
        if r.get("category"):
            L.append("CATEGORIES:" + ics_escape(r["category"]))
        if r.get("repeat", "none") in RRULE:
            L.append("RRULE:FREQ=" + RRULE[r["repeat"]])
        L += ["BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:" + ics_escape(r["title"]),
              "TRIGGER:-PT0M" if r.get("time") else "TRIGGER:PT9H", "END:VALARM"]
        if r.get("advance"):
            L += ["BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:" + ics_escape(r["title"]),
                  f"TRIGGER:-P{int(r['advance'])}D", "END:VALARM"]
        L.append("END:VEVENT")
    L.append("END:VCALENDAR")
    with open(path, "w", encoding="utf-8", newline="") as fh_:
        fh_.write("\r\n".join(ics_fold(x) for x in L) + "\r\n")


def read_ics(path):
    """Parse VEVENTs from an .ics file into reminder field dicts (past one-offs skipped)."""
    with open(path, encoding="utf-8-sig", errors="replace") as fh_:
        raw = fh_.read().splitlines()
    lines = []
    for ln in raw:
        if ln[:1] in (" ", "\t") and lines:
            lines[-1] += ln[1:]
        else:
            lines.append(ln)
    events, cur, in_alarm = [], None, False
    for ln in lines:
        u = ln.strip().upper()
        if u == "BEGIN:VEVENT":
            cur, in_alarm = {}, False
        elif u == "END:VEVENT" and cur is not None:
            events.append(cur)
            cur = None
        elif cur is None or ":" not in ln:
            continue
        elif u == "BEGIN:VALARM":
            in_alarm = True
        elif u == "END:VALARM":
            in_alarm = False
        else:
            key, val = ln.split(":", 1)
            name, *params = key.split(";")
            name = name.upper()
            if in_alarm:
                m = re.match(r"-P(\d+)([DW])", val.strip())
                if name == "TRIGGER" and m:
                    cur["_adv"] = max(cur.get("_adv", 0), int(m[1]) * (7 if m[2] == "W" else 1))
            else:
                cur.setdefault(name, ([p.upper() for p in params], val.strip()))

    today = date.today()
    out = []
    for ev in events:
        if "DTSTART" not in ev:
            continue
        params, val = ev["DTSTART"]
        try:
            if "VALUE=DATE" in params or len(val) == 8:
                d, t = datetime.strptime(val[:8], "%Y%m%d").date(), ""
            else:
                dt = datetime.strptime(val[:15], "%Y%m%dT%H%M%S")
                if val.endswith("Z"):
                    dt = dt.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
                d, t = dt.date(), f"{dt:%H:%M}"
        except ValueError:
            continue
        repeat = "none"
        if "RRULE" in ev:
            rule = ev["RRULE"][1].upper()
            m = re.search(r"FREQ=(\w+)", rule)
            repeat = {v: k for k, v in RRULE.items()}.get(m[1] if m else "", "none")
            m = re.search(r"UNTIL=(\d{8})", rule)
            if m and datetime.strptime(m[1], "%Y%m%d").date() < today:
                continue
        rec = {"title": ics_unescape(ev.get("SUMMARY", ([], "(no title)"))[1]) or "(no title)",
               "date": d.isoformat(), "time": t, "repeat": repeat,
               "advance": min(ev.get("_adv", 0), 30),
               "notes": ics_unescape(ev.get("DESCRIPTION", ([], ""))[1])[:2000],
               "category": "Personal",
               "ics_uid": ev.get("UID", ([], ""))[1]}
        cats = ics_unescape(ev.get("CATEGORIES", ([], ""))[1]).split(",")[0].strip().lower()
        rec["category"] = next((c for c, _ in CATEGORIES if c.lower() == cats), "Personal")
        if repeat == "none":
            if d < today:
                continue
        else:
            rec["anchor"] = rec["date"]
            while d < today:
                d = next_occurrence(rec, d)
            rec["date"] = d.isoformat()
        out.append(rec)
    return out


# ---------------------------------------------------------------- phone alerts (ntfy)

def ntfy_send(topic, title, message, timeout=15):
    body = json.dumps({"topic": topic, "title": title, "message": message,
                       "tags": ["alarm_clock"], "priority": 4}).encode("utf-8")
    req = urllib.request.Request(NTFY_SERVER, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp.read()


def ntfy_send_async(topic, title, message):
    def work():
        try:
            ntfy_send(topic, title, message)
        except Exception:
            log_error("Phone alert failed:\n" + traceback.format_exc())
    threading.Thread(target=work, daemon=True).start()


# ---------------------------------------------------------------- global hotkey

def hotkey_loop(q):
    """Registers Ctrl+Alt+R system-wide and posts 'quickadd' whenever it is pressed."""
    try:
        user32 = ctypes.windll.user32
        if not user32.RegisterHotKey(None, 1, 0x0002 | 0x0001 | 0x4000, 0x52):
            q.put("hotkey-failed")
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == 0x0312:  # WM_HOTKEY
                q.put("quickadd")
    except Exception:
        log_error(traceback.format_exc())


# ---------------------------------------------------------------- storage

class Store:
    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.reminders = self._load(REM_FILE, [])
        self.settings = {**DEFAULT_SETTINGS, **self._load(SET_FILE, {})}
        if self.settings.get("theme") not in THEMES:
            self.settings["theme"] = DEFAULT_THEME

    @staticmethod
    def _load(path, default):
        try:
            with open(path, encoding="utf-8") as fh_:
                return json.load(fh_)
        except FileNotFoundError:
            return default
        except (OSError, ValueError):
            try:
                os.replace(path, path + ".broken")  # keep the damaged file for recovery
            except OSError:
                pass
            return default

    @staticmethod
    def _write(path, data):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh_:
            json.dump(data, fh_, indent=2)
        os.replace(tmp, path)

    def save(self):
        self._write(REM_FILE, self.reminders)

    def save_settings(self):
        self._write(SET_FILE, self.settings)

    def get(self, rid):
        return next((r for r in self.reminders if r["id"] == rid), None)

    def due(self, r):
        t = r.get("time") or self.settings["allday_time"]
        return datetime.strptime(f"{r['date']} {t}", "%Y-%m-%d %H:%M")

    def effective(self, r):
        s = r.get("snooze_until")
        return datetime.fromisoformat(s) if s else self.due(r)

    def pending(self):
        return [r for r in self.reminders if not r.get("done")]

    def delete(self, rid):
        self.reminders = [r for r in self.reminders if r["id"] != rid]
        self.save()

    def complete(self, rid):
        r = self.get(rid)
        if not r:
            return
        if r.get("repeat", "none") == "none":
            r["done"] = True
            r["done_at"] = datetime.now().isoformat(timespec="minutes")
        else:  # move a repeating reminder to its next future occurrence
            now = datetime.now()
            d = date.fromisoformat(r["date"])
            while True:
                d = next_occurrence(r, d)
                r["date"] = d.isoformat()
                if self.due(r) > now:
                    break
            r["fired_main"] = r["fired_advance"] = False
        r["snooze_until"] = None
        self.save()

    def snooze(self, rid, until):
        r = self.get(rid)
        if r:
            r["snooze_until"] = until.isoformat(timespec="minutes")
            self.save()


# ---------------------------------------------------------------- tooltip

class Tip:
    current = None

    def __init__(self, widget, text):
        self.w, self.text = widget, text
        widget.bind("<Enter>", self.show, add="+")
        widget.bind("<Leave>", self.hide, add="+")

    def show(self, _e=None):
        Tip.close()
        tw = tk.Toplevel(self.w)
        tw.overrideredirect(True)
        tw.attributes("-topmost", True)
        tk.Label(tw, text=self.text, bg=C["panel"], fg=C["fg"], font=f(9),
                 justify="left", padx=8, pady=5, highlightthickness=1,
                 highlightbackground=C["border"]).pack()
        tw.geometry(f"+{self.w.winfo_rootx()}+{self.w.winfo_rooty() + self.w.winfo_height() + 4}")
        Tip.current = tw

    def hide(self, _e=None):
        Tip.close()

    @staticmethod
    def close():
        if Tip.current is not None:
            try:
                Tip.current.destroy()
            except tk.TclError:
                pass
            Tip.current = None


# ---------------------------------------------------------------- popup cards

class Card(tk.Toplevel):
    """Base for the stacked pop-ups in the bottom-right corner."""

    def __init__(self, app, key, stripe):
        super().__init__(app.root)
        self.app, self.key = app, key
        s = app.s
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=C["border"])
        self.stripe = stripe
        self.outer = outer = tk.Frame(self, bg=stripe)
        outer.pack(fill="both", expand=True, padx=1, pady=1)
        self.body = tk.Frame(outer, bg=C["panel"], padx=int(14 * s), pady=int(12 * s))
        self.body.pack(fill="both", expand=True, padx=(int(6 * s), 0))
        self.wrap = int(300 * s)

    def label(self, text, font, fg=None, pady=0):
        tk.Label(self.body, text=text, bg=C["panel"], fg=fg or C["fg"], font=font,
                 wraplength=self.wrap, justify="left", anchor="w").pack(fill="x", pady=pady)

    def show(self):
        self.app.toasts[self.key] = self
        self.app.restack_toasts()

    def close(self):
        self.app.toasts.pop(self.key, None)
        try:
            self.destroy()
        except tk.TclError:
            pass
        self.app.restack_toasts()


class Toast(Card):
    def __init__(self, app, r, kind):
        heads = {"due": ("REMINDER", C["accent"]), "snooze": ("REMINDER \u00b7 SNOOZED", C["accent"]),
                 "missed": ("MISSED REMINDER", C["danger"]), "advance": ("COMING UP", C["ok"])}
        head, color = heads[kind]
        super().__init__(app, r["id"], cat_color(r))
        self.rid, self.kind = r["id"], kind
        self.label(f"\u23f0  {heading(head, spaced=False)}", fh(8), color)
        self.label(r["title"], fh(13), pady=(3, 0))
        if kind == "advance":
            n = (date.fromisoformat(r["date"]) - date.today()).days
            when = f"{rel_days(n).capitalize()}  \u00b7  {format_when(r)}"
        elif kind == "missed":
            when = f"Was due {format_when(r)}"
        else:
            when = format_when(r)
        self.label(when, f(9), C["dim"], pady=(2, 0))
        if r.get("notes"):
            self.label(r["notes"], f(9), pady=(8, 0))

        row = tk.Frame(self.body, bg=C["panel"])
        row.pack(fill="x", pady=(12, 0))
        if kind == "advance":
            mkbtn(row, "Got it", self.close, bg=C["accent"], fg=C["accent_fg"]).pack(side="right")
            mkbtn(row, "Open", self.open, bg=C["bg"]).pack(side="right", padx=(0, 6))
        else:
            mkbtn(row, "\u2713 Done", self.done, bg=C["ok"], fg=C["accent_fg"] if not C["dark"] else "#0d1a14",
                  font=f(9, "bold")).pack(side="right")
            tk.Label(row, text="Snooze", bg=C["panel"], fg=C["dim"], font=f(8)).pack(side="left", padx=(0, 4))
            for label, delta in (("10 min", timedelta(minutes=10)),
                                 ("1 hr", timedelta(hours=1)), ("Tomorrow", None)):
                mkbtn(row, label, lambda d=delta: self.snooze(d), bg=C["bg"],
                      font=f(8), padx=7, pady=3).pack(side="left", padx=(0, 4))
        self.show()
        play_sound()

    def done(self):
        self.app.store.complete(self.rid)
        self.close()
        self.app.changed()

    def snooze(self, delta):
        if delta is None:
            t = datetime.strptime(self.app.store.settings["allday_time"], "%H:%M").time()
            until = datetime.combine(date.today() + timedelta(days=1), t)
        else:
            until = datetime.now() + delta
        self.app.store.snooze(self.rid, until)
        self.close()
        self.app.changed()

    def open(self):
        self.close()
        r = self.app.store.get(self.rid)
        if r:
            self.app.edit(r)


class Notice(Card):
    def __init__(self, app, key, head, text, actions):
        super().__init__(app, key, C["accent"])
        self.label(heading(head, spaced=False), fh(8), C["accent"])
        self.label(text, f(10), pady=(4, 0))
        row = tk.Frame(self.body, bg=C["panel"])
        row.pack(fill="x", pady=(10, 0))
        for i, (label, cmd) in enumerate(actions):
            primary = i == 0
            mkbtn(row, label, lambda c=cmd: (self.close(), c() if c else None),
                  bg=C["accent"] if primary else C["bg"],
                  fg=C["accent_fg"] if primary else C["fg"]).pack(side="right", padx=(6, 0))
        self.show()


# ---------------------------------------------------------------- dialogs

class ReminderDialog(tk.Toplevel):
    def __init__(self, app, r=None, day=None, prefill=None):
        super().__init__(app.root)
        self.app, self.r = app, r
        src = r or prefill or {}
        self.title("Edit reminder" if r else "New reminder")
        self.configure(bg=C["bg"], padx=18, pady=16)
        self.attributes("-topmost", True)
        self.resizable(False, False)

        d = date.fromisoformat(src["date"]) if src.get("date") else (day or date.today())
        self.v_title = tk.StringVar(value=src.get("title", ""))
        self.v_date = tk.StringVar(value=f"{d.day} {d:%b %Y}")
        self.v_time = tk.StringVar(value=fmt_time(src.get("time")))
        adv = int(src.get("advance", 0) or 0)
        adv_opts = [adv_label(n) for n in sorted(set(ADVANCE_CHOICES + [adv]))]
        self.v_adv = tk.StringVar(value=adv_label(adv))
        self.v_rep = tk.StringVar(value=dict(REPEATS)[src.get("repeat", "none")])
        self.v_cat = tk.StringVar(value=src.get("category") or "Personal")

        def lab(text, row, col=0, **kw):
            tk.Label(self, text=text, bg=C["bg"], fg=C["dim"], font=f(9),
                     anchor="w").grid(row=row, column=col, sticky="w", pady=(10, 2), **kw)

        def hint(text, row, col=0, **kw):
            tk.Label(self, text=text, bg=C["bg"], fg=C["faint"], font=f(8),
                     anchor="w").grid(row=row, column=col, sticky="w", **kw)

        tk.Label(self, text=heading("Edit reminder" if r else "New reminder", spaced=False),
                 bg=C["bg"], fg=C["accent"], font=fh(11)).grid(row=0, column=0, columnspan=2, sticky="w")
        lab("What do you need to remember?", 1, columnspan=2)
        self.e_title = entry(self, self.v_title, 42)
        self.e_title.grid(row=2, column=0, columnspan=2, sticky="we", ipady=4)

        lab("Date", 3)
        lab("Time (optional)", 3, 1, padx=(12, 0))
        entry(self, self.v_date, 18).grid(row=4, column=0, sticky="we", ipady=4)
        entry(self, self.v_time, 18).grid(row=4, column=1, sticky="we", ipady=4, padx=(12, 0))
        hint("e.g. 1 Dec 2026 or 01/12/2026", 5)
        hint("e.g. 5:30 pm; empty = all day", 5, 1, padx=(12, 0))

        chips = tk.Frame(self, bg=C["bg"])
        chips.grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))
        for label, days in (("Today", 0), ("Tomorrow", 1), ("In 1 week", 7)):
            mkbtn(chips, label, lambda n=days: self._set_date(n), bg=C["panel"],
                  font=f(8), padx=8, pady=2).pack(side="left", padx=(0, 5))

        lab("Category", 7)
        lab("Repeat", 7, 1, padx=(12, 0))
        ttk.Combobox(self, textvariable=self.v_cat, values=[c for c, _ in CATEGORIES],
                     state="readonly", width=17).grid(row=8, column=0, sticky="we")
        ttk.Combobox(self, textvariable=self.v_rep, values=[x[1] for x in REPEATS],
                     state="readonly", width=17).grid(row=8, column=1, sticky="we", padx=(12, 0))
        lab("Remind me early", 9)
        ttk.Combobox(self, textvariable=self.v_adv, values=adv_opts,
                     state="readonly", width=17).grid(row=10, column=0, sticky="we")

        lab("Notes (optional)", 11, columnspan=2)
        self.t_notes = tk.Text(self, height=3, width=42, bg=C["panel"], fg=C["fg"],
                               insertbackground=C["fg"], relief="flat", font=f(10),
                               highlightthickness=1, highlightcolor=C["accent"],
                               highlightbackground=C["border"], wrap="word")
        self.t_notes.grid(row=12, column=0, columnspan=2, sticky="we")
        if src.get("notes"):
            self.t_notes.insert("1.0", src["notes"])

        self.err = tk.Label(self, text="", bg=C["bg"], fg=C["danger"], font=f(9),
                            anchor="w", wraplength=380, justify="left")
        self.err.grid(row=13, column=0, columnspan=2, sticky="w", pady=(8, 0))

        btns = tk.Frame(self, bg=C["bg"])
        btns.grid(row=14, column=0, columnspan=2, sticky="we", pady=(8, 0))
        mkbtn(btns, "Save", self.save, bg=C["accent"], fg=C["accent_fg"],
              font=f(9, "bold"), padx=16).pack(side="right")
        mkbtn(btns, "Cancel", self.destroy, bg=C["panel"]).pack(side="right", padx=(0, 6))
        if r:
            mkbtn(btns, "Delete", self.delete, bg=C["panel"], fg=C["danger"]).pack(side="left")
            mkbtn(btns, "\u2713 Mark done", self.mark_done, bg=C["panel"],
                  fg=C["ok"]).pack(side="left", padx=(6, 0))

        self.bind("<Escape>", lambda e: self.destroy())
        self.e_title.bind("<Return>", lambda e: self.save())
        dark_titlebar(self)
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        self.geometry(f"+{(self.winfo_screenwidth() - w) // 2}+{(self.winfo_screenheight() - h) // 3}")
        self.e_title.focus_force()
        self.grab_set()

    def _set_date(self, n):
        d = date.today() + timedelta(days=n)
        self.v_date.set(f"{d.day} {d:%b %Y}")

    def save(self):
        title = self.v_title.get().strip()
        if not title:
            return self.err.config(text="Give the reminder a name.")
        try:
            d = parse_date(self.v_date.get())
        except ValueError:
            return self.err.config(text="Couldn't read the date. Try 1 Dec 2026 or 01/12/2026.")
        try:
            t = parse_time(self.v_time.get())
        except ValueError:
            return self.err.config(text="Couldn't read the time. Try 17:30 or 5:30 pm, or leave it empty.")
        self.app.save_reminder(self.r, {
            "title": title, "date": d.isoformat(), "time": t,
            "advance": adv_from_label(self.v_adv.get()),
            "repeat": {lbl: k for k, lbl in REPEATS}[self.v_rep.get()],
            "category": self.v_cat.get(),
            "notes": self.t_notes.get("1.0", "end").strip(),
        })
        self.destroy()

    def delete(self):
        if messagebox.askyesno("Delete reminder", f"Delete \"{self.r['title']}\"?", parent=self):
            self.app.close_toast(self.r["id"])
            self.app.store.delete(self.r["id"])
            self.app.changed()
            self.destroy()

    def mark_done(self):
        self.app.close_toast(self.r["id"])
        self.app.store.complete(self.r["id"])
        self.app.changed()
        self.destroy()


class QuickAdd(tk.Toplevel):
    EXAMPLES = ("apply for scholarship dec 1 5pm #college   \u00b7   pay rent 1st every month #bills\n"
                "call mom tomorrow 7pm   \u00b7   exam in 3 days remind 1 day before   \u00b7   gym every monday 6am")

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Quick add")
        self.configure(bg=C["bg"], padx=20, pady=16)
        self.attributes("-topmost", True)
        self.resizable(False, False)
        tk.Label(self, text=heading("Quick add", spaced=False), bg=C["bg"], fg=C["accent"],
                 font=fh(11)).pack(anchor="w")
        self.v = tk.StringVar()
        self.e = entry(self, self.v, 48, size=13)
        self.e.pack(fill="x", ipady=7, pady=(8, 6))
        self.preview = tk.Label(self, text="", bg=C["bg"], fg=C["dim"], font=f(10),
                                anchor="w", justify="left", wraplength=int(520 * app.s))
        self.preview.pack(fill="x")
        tk.Label(self, text="Try:  " + self.EXAMPLES, bg=C["bg"], fg=C["faint"], font=f(8),
                 justify="left", anchor="w").pack(fill="x", pady=(10, 0))
        row = tk.Frame(self, bg=C["bg"])
        row.pack(fill="x", pady=(12, 0))
        mkbtn(row, "Add  \u23ce", self.add, bg=C["accent"], fg=C["accent_fg"],
              font=f(9, "bold"), padx=16).pack(side="right")
        mkbtn(row, "Cancel", self.destroy, bg=C["panel"]).pack(side="right", padx=(0, 6))
        mkbtn(row, "More options\u2026", self.more, bg=C["panel"]).pack(side="left")
        self.v.trace_add("write", lambda *a: self.update_preview())
        self.update_preview()
        self.bind("<Return>", lambda e: self.add())
        self.bind("<Escape>", lambda e: self.destroy())
        dark_titlebar(self)
        self.update_idletasks()
        w = self.winfo_reqwidth()
        self.geometry(f"+{(self.winfo_screenwidth() - w) // 2}+{self.winfo_screenheight() // 4}")
        self.after(40, self.grab_focus)

    def grab_focus(self):
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
            self.e.focus_set()
        except tk.TclError:
            pass

    def update_preview(self):
        txt = self.v.get().strip()
        if not txt:
            return self.preview.config(text="Type what, when, and how often. Press Enter to add.",
                                       fg=C["dim"])
        try:
            p = parse_quick(txt)
        except ValueError as e:
            return self.preview.config(text=str(e), fg=C["warn"])
        parts = [p["title"], format_when(p)]
        if p["repeat"] != "none":
            parts.append(dict(REPEATS)[p["repeat"]].lower())
        if p["advance"]:
            parts.append("early alert " + adv_label(p["advance"]))
        parts.append(p["category"])
        self.preview.config(text="\u2192 " + "   \u00b7   ".join(parts), fg=C["fg"])

    def add(self):
        try:
            p = parse_quick(self.v.get())
        except ValueError as e:
            return self.preview.config(text=str(e), fg=C["warn"])
        data = {k: p[k] for k in ("title", "date", "time", "advance", "repeat", "category")}
        data["notes"] = ""
        self.app.save_reminder(None, data)
        self.destroy()

    def more(self):
        try:
            p = parse_quick(self.v.get())
        except ValueError:
            p = {"title": self.v.get().strip()}
        self.destroy()
        self.app.edit(None, prefill=p)


class DayDialog(tk.Toplevel):
    def __init__(self, app, d, items):
        super().__init__(app.root)
        self.title(fmt_date(d))
        self.configure(bg=C["bg"], padx=16, pady=14)
        self.attributes("-topmost", True)
        self.resizable(False, False)
        tk.Label(self, text=fmt_date(d), bg=C["bg"], fg=C["fg"],
                 font=fh(12)).pack(anchor="w", pady=(0, 8))
        for r in sorted(items, key=lambda x: x.get("time") or "99"):
            row = tk.Frame(self, bg=C["panel"], cursor="hand2", padx=10, pady=6)
            row.pack(fill="x", pady=2)
            dot = tk.Label(row, text="\u25cf", bg=C["panel"], fg=cat_color(r), font=f(9))
            a = tk.Label(row, text=fmt_time(r.get("time")) or "All day", width=9, anchor="w",
                         bg=C["panel"], fg=C["dim"], font=f(9))
            b = tk.Label(row, text=r["title"], anchor="w", bg=C["panel"], fg=C["fg"], font=f(10))
            dot.pack(side="left", padx=(0, 6))
            a.pack(side="left")
            b.pack(side="left", fill="x", expand=True)
            for w in (row, dot, a, b):
                w.bind("<Button-1>", lambda e, rr=r: (self.destroy(), app.edit(rr)))
        mkbtn(self, "+ Add reminder on this day", lambda: (self.destroy(), app.edit(None, d)),
              bg=C["accent"], fg=C["accent_fg"]).pack(anchor="w", pady=(10, 0))
        self.bind("<Escape>", lambda e: self.destroy())
        dark_titlebar(self)
        self.update_idletasks()
        x, y = app.root.winfo_rootx(), app.root.winfo_rooty() + 40
        if app.root.state() == "withdrawn":
            x, y = (self.winfo_screenwidth() - self.winfo_reqwidth()) // 2, self.winfo_screenheight() // 3
        self.geometry(f"+{x}+{y}")
        self.focus_force()


class PhoneDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Phone alerts")
        self.configure(bg=C["bg"], padx=18, pady=16)
        self.attributes("-topmost", True)
        self.resizable(False, False)
        cur = app.store.settings.get("phone_topic") or ""
        self.v = tk.StringVar(value=cur or f"mfc-{secrets.token_hex(6)}")
        tk.Label(self, text=heading("Phone alerts", spaced=False), bg=C["bg"], fg=C["accent"],
                 font=fh(11)).pack(anchor="w")
        steps = ("Get every reminder on your phone too, using the free ntfy app.\n\n"
                 "1.  Install \u201cntfy\u201d from the Play Store or App Store.\n"
                 "2.  In the app, tap  +  and subscribe to the topic below.\n"
                 "3.  Click \u201cSend test\u201d, then \u201cSave\u201d.")
        tk.Label(self, text=steps, bg=C["bg"], fg=C["fg"], font=f(10), justify="left",
                 anchor="w").pack(fill="x", pady=(8, 10))
        e = entry(self, self.v, 34, size=12)
        e.pack(fill="x", ipady=5)
        tk.Label(self, text="Anyone who knows this topic name can read the alerts, so keep it random.",
                 bg=C["bg"], fg=C["faint"], font=f(8), anchor="w").pack(fill="x", pady=(4, 0))
        self.status = tk.Label(self, text="On" if cur else "Off", bg=C["bg"],
                               fg=C["ok"] if cur else C["dim"], font=f(9), anchor="w")
        self.status.pack(fill="x", pady=(8, 0))
        row = tk.Frame(self, bg=C["bg"])
        row.pack(fill="x", pady=(10, 0))
        mkbtn(row, "Save", self.save, bg=C["accent"], fg=C["accent_fg"], font=f(9, "bold"),
              padx=16).pack(side="right")
        mkbtn(row, "Send test", self.test, bg=C["panel"]).pack(side="right", padx=(0, 6))
        mkbtn(row, "Turn off", self.off, bg=C["panel"], fg=C["danger"]).pack(side="left")
        self.bind("<Escape>", lambda ev: self.destroy())
        dark_titlebar(self)
        self.update_idletasks()
        self.geometry(f"+{(self.winfo_screenwidth() - self.winfo_reqwidth()) // 2}+{self.winfo_screenheight() // 4}")
        self.focus_force()

    def topic(self):
        t = self.v.get().strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{4,64}", t):
            self.status.config(text="Use 4-64 letters, numbers, - or _ for the topic.", fg=C["danger"])
            return None
        return t

    def test(self):
        t = self.topic()
        if not t:
            return
        self.status.config(text="Sending\u2026", fg=C["dim"])
        self.update_idletasks()
        try:
            ntfy_send(t, "\u23f0 Test from Mini Floating Calendar", "If you can read this, phone alerts work.", 10)
            self.status.config(text="Sent! Check your phone.", fg=C["ok"])
        except Exception as e:
            self.status.config(text=f"Couldn't send: {e}", fg=C["danger"])

    def save(self):
        t = self.topic()
        if t:
            self.app.store.settings["phone_topic"] = t
            self.app.store.save_settings()
            self.destroy()

    def off(self):
        self.app.store.settings["phone_topic"] = ""
        self.app.store.save_settings()
        self.destroy()


class ThemeDialog(tk.Toplevel):
    """Pick the light theme, the dark theme, and when to switch between them."""

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        st = app.store.settings
        self.title("Light & dark timings")
        self.configure(bg=C["bg"], padx=18, pady=16)
        self.attributes("-topmost", True)
        self.resizable(False, False)
        tk.Label(self, text=heading("Light & dark timings", spaced=False), bg=C["bg"],
                 fg=C["accent"], font=fh(11)).pack(anchor="w", pady=(0, 8))

        self.v_mode = tk.StringVar(value=st.get("auto_theme", "off"))
        for val, lbl in AUTO_MODES:
            tk.Radiobutton(self, text=lbl, variable=self.v_mode, value=val, command=self._sync,
                           bg=C["bg"], fg=C["fg"], selectcolor=C["panel"], activebackground=C["bg"],
                           activeforeground=C["fg"], font=f(10), anchor="w").pack(fill="x")

        g = tk.Frame(self, bg=C["bg"])
        g.pack(fill="x", pady=(12, 0))
        names = list(THEMES)

        def lab(text, r, c):
            tk.Label(g, text=text, bg=C["bg"], fg=C["dim"], font=f(9)).grid(
                row=r, column=c, sticky="w", pady=(6, 2), padx=(0 if c == 0 else 14, 0))
        self.v_light = tk.StringVar(value=st.get("light_theme", DEFAULT_THEME))
        self.v_dark = tk.StringVar(value=st.get("dark_theme", "Midnight Noir"))
        self.v_ls = tk.StringVar(value=fmt_time(st.get("light_start", "07:00")))
        self.v_ds = tk.StringVar(value=fmt_time(st.get("dark_start", "19:00")))
        lab("☀  Light theme", 0, 0)
        lab("☾  Dark theme", 0, 1)
        ttk.Combobox(g, textvariable=self.v_light, values=names, state="readonly",
                     width=18).grid(row=1, column=0, sticky="we")
        ttk.Combobox(g, textvariable=self.v_dark, values=names, state="readonly",
                     width=18).grid(row=1, column=1, sticky="we", padx=(14, 0))
        lab("Light from", 2, 0)
        lab("Dark from", 2, 1)
        self.e_ls = entry(g, self.v_ls, 18)
        self.e_ds = entry(g, self.v_ds, 18)
        for e in (self.e_ls, self.e_ds):
            e.config(disabledbackground=C["panel"], disabledforeground=C["faint"])
        self.e_ls.grid(row=3, column=0, sticky="we", ipady=4)
        self.e_ds.grid(row=3, column=1, sticky="we", ipady=4, padx=(14, 0))

        chips = tk.Frame(self, bg=C["bg"])
        chips.pack(fill="x", pady=(8, 0))
        tk.Label(chips, text="Presets:", bg=C["bg"], fg=C["faint"], font=f(8)).pack(side="left")
        for lbl, a, b in (("7 am / 7 pm", "07:00", "19:00"), ("6 am / 6 pm", "06:00", "18:00"),
                          ("8 am / 9 pm", "08:00", "21:00")):
            mkbtn(chips, lbl, lambda a=a, b=b: self._preset(a, b), bg=C["panel"], font=f(8),
                  padx=7, pady=2).pack(side="left", padx=(5, 0))

        tk.Label(self, text="“Follow Windows” uses Settings → Personalization → Colors.",
                 bg=C["bg"], fg=C["faint"], font=f(8), anchor="w").pack(fill="x", pady=(10, 0))
        self.err = tk.Label(self, text="", bg=C["bg"], fg=C["danger"], font=f(9), anchor="w")
        self.err.pack(fill="x", pady=(4, 0))
        row = tk.Frame(self, bg=C["bg"])
        row.pack(fill="x", pady=(8, 0))
        mkbtn(row, "Save", self.save, bg=C["accent"], fg=C["accent_fg"], font=f(9, "bold"),
              padx=16).pack(side="right")
        mkbtn(row, "Cancel", self.destroy, bg=C["panel"]).pack(side="right", padx=(0, 6))
        self.bind("<Escape>", lambda ev: self.destroy())
        self._sync()
        dark_titlebar(self)
        self.update_idletasks()
        self.geometry(f"+{(self.winfo_screenwidth() - self.winfo_reqwidth()) // 2}+{self.winfo_screenheight() // 4}")
        self.focus_force()

    def _preset(self, a, b):
        self.v_mode.set("schedule")
        self._sync()
        self.v_ls.set(fmt_time(a))
        self.v_ds.set(fmt_time(b))

    def _sync(self):
        state = "normal" if self.v_mode.get() == "schedule" else "disabled"
        self.e_ls.config(state=state)
        self.e_ds.config(state=state)

    def save(self):
        mode = self.v_mode.get()
        try:
            a, b = parse_time(self.v_ls.get()), parse_time(self.v_ds.get())
        except ValueError:
            return self.err.config(text="Couldn't read a time. Try 7:00 am or 19:00.")
        if mode == "schedule" and (not a or not b or a == b):
            return self.err.config(text="Light and dark need two different times.")
        st = self.app.store.settings
        st.update(auto_theme=mode, light_theme=self.v_light.get(), dark_theme=self.v_dark.get(),
                  light_start=a or st["light_start"], dark_start=b or st["dark_start"])
        self.app.store.save_settings()
        self.app.v_auto.set(mode)
        self.destroy()
        w = self.app.wanted_theme()
        if w and w != st["theme"]:
            self.app.apply_theme(w, manual=False)


# ---------------------------------------------------------------- big calendar window

class BigCalendar(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        s = app.s
        self.title(TITLE)
        self.configure(bg=C["bg"])
        self.minsize(int(760 * s), int(540 * s))
        self.geometry(app.store.settings.get("big_geom") or f"{int(1040 * s)}x{int(720 * s)}")
        t = date.today()
        self.vy, self.vm = t.year, t.month
        self.mode = "month"
        self.filter = "upcoming"
        self.q = tk.StringVar()
        self.q.trace_add("write", lambda *a: self.fill_tree())
        self.tree = None
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bar = tk.Frame(self, bg=C["bg"], padx=16, pady=12)
        self.bar.pack(fill="x")
        self.body = tk.Frame(self, bg=C["bg"])
        self.body.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.bind("<Left>", lambda e: self.mode == "month" and self.shift(-1))
        self.bind("<Right>", lambda e: self.mode == "month" and self.shift(1))
        dark_titlebar(self)
        self.refresh()

    def close(self):
        try:
            self.app.store.settings["big_geom"] = self.geometry()
            self.app.store.save_settings()
        except Exception:
            pass
        self.app.big = None
        self.destroy()

    def shift(self, n):
        d = add_months(date(self.vy, self.vm, 1), n)
        self.vy, self.vm = d.year, d.month
        self.refresh()

    def goto_today(self):
        t = date.today()
        self.vy, self.vm = t.year, t.month
        self.refresh()

    def set_mode(self, mode):
        self.mode = mode
        self.refresh()

    def refresh(self):
        Tip.close()
        for w in self.bar.winfo_children() + self.body.winfo_children():
            w.destroy()
        self.tree = None
        self._bar()
        if self.mode == "month":
            self._month()
        else:
            self._list()
        self.app.bind_menu(self.bar)

    def _bar(self):
        b = self.bar
        if self.mode == "month":
            mkbtn(b, "\u2039", lambda: self.shift(-1), bg=C["bg"], font=f(16), padx=6, pady=0).pack(side="left")
            tk.Label(b, text=heading(f"{calendar.month_name[self.vm]} {self.vy}"), bg=C["bg"],
                     fg=C["fg"], font=fh(17)).pack(side="left", padx=4)
            mkbtn(b, "\u203a", lambda: self.shift(1), bg=C["bg"], font=f(16), padx=6, pady=0).pack(side="left")
            mkbtn(b, "Today", self.goto_today, bg=C["panel"], font=f(9)).pack(side="left", padx=(10, 0))
        else:
            tk.Label(b, text=heading("All reminders"), bg=C["bg"], fg=C["fg"],
                     font=fh(17)).pack(side="left")
            e = entry(b, self.q, 26, size=10)
            e.pack(side="left", padx=(16, 0), ipady=4)
            tk.Label(b, text="\u2315 search", bg=C["bg"], fg=C["faint"], font=f(8)).pack(side="left", padx=6)
        mkbtn(b, "Export .ics", self.app.export_ics, bg=C["panel"], font=f(9)).pack(side="right", padx=(6, 0))
        mkbtn(b, "Import .ics", self.app.import_ics, bg=C["panel"], font=f(9)).pack(side="right", padx=(6, 0))
        mkbtn(b, "+ Quick add", self.app.quick_add, bg=C["accent"], fg=C["accent_fg"],
              font=f(9, "bold")).pack(side="right", padx=(6, 0))
        seg = tk.Frame(b, bg=C["border"], padx=1, pady=1)
        seg.pack(side="right", padx=(0, 10))
        for mode, label in (("month", "Month"), ("list", "List")):
            on = self.mode == mode
            mkbtn(seg, label, lambda m=mode: self.set_mode(m), bg=C["accent"] if on else C["panel"],
                  fg=C["accent_fg"] if on else C["fg"], font=f(9)).pack(side="left")

    def _month(self):
        app, s = self.app, self.app.s
        today = date.today()
        ws = app.store.settings["week_start"]
        grid = tk.Frame(self.body, bg=C["border"], padx=1, pady=1)
        grid.pack(fill="both", expand=True)
        names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        for i in range(7):
            grid.columnconfigure(i, weight=1, uniform="col")
            tk.Label(grid, text=heading(names[(ws + i) % 7][:3], spaced=False) if C["upper"] else names[(ws + i) % 7][:3],
                     bg=C["bg"], fg=C["dim"], font=fh(9), pady=4).grid(row=0, column=i, sticky="nsew", padx=(0, 1), pady=(0, 1))
        weeks = calendar.Calendar(ws).monthdatescalendar(self.vy, self.vm)
        everything = app.store.reminders
        for wi, week in enumerate(weeks, start=1):
            grid.rowconfigure(wi, weight=1, uniform="row")
            for di, d in enumerate(week):
                in_month = d.month == self.vm
                light, darker = (C["panel"], C["bg"]) if C["dark"] else (C["bg"], C["panel"])
                bg = light if in_month else darker
                cell = tk.Frame(grid, bg=bg, width=1, height=1, cursor="hand2")
                cell.grid(row=wi, column=di, sticky="nsew", padx=(0, 1), pady=(0, 1))
                cell.pack_propagate(False)
                top = tk.Frame(cell, bg=bg)
                top.pack(fill="x", padx=4, pady=(3, 1))
                if d == today:
                    num = tk.Label(top, text=f" {d.day} ", bg=C["accent"], fg=C["accent_fg"], font=fh(10))
                else:
                    num = tk.Label(top, text=str(d.day), bg=bg,
                                   fg=(C["fg"] if in_month else C["faint"]),
                                   font=fh(10) if in_month else f(9))
                num.pack(side="left")
                for w in (cell, top, num):
                    w.bind("<Button-1>", lambda e, dd=d: app.edit(None, dd))
                evs = [r for r in everything if occurs_on(r, d)]
                evs.sort(key=lambda r: (bool(r.get("done")), r.get("time") or "99"))
                limit = 3
                for r in evs[:limit]:
                    done = r.get("done")
                    label = (short_time(r.get("time")) + " " if r.get("time") else "") + r["title"]
                    chip = tk.Label(cell, text=label, anchor="w", padx=4, cursor="hand2",
                                    bg=bg if done else cat_color(r),
                                    fg=C["faint"] if done else C["chip_fg"],
                                    font=f(8, "overstrike") if done else f(8))
                    chip.pack(fill="x", padx=4, pady=1)
                    chip.bind("<Button-1>", lambda e, rr=r: app.edit(rr))
                    Tip(chip, f"{r['title']}\n{format_when(r)}" + ("\n(done)" if done else ""))
                if len(evs) > limit:
                    more = tk.Label(cell, text=f"+{len(evs) - limit} more", bg=bg, fg=C["dim"],
                                    font=f(8), anchor="w", cursor="hand2")
                    more.pack(fill="x", padx=6)
                    more.bind("<Button-1>", lambda e, dd=d: app.open_day(dd))

    def _list(self):
        top = tk.Frame(self.body, bg=C["bg"])
        top.pack(fill="x", pady=(0, 8))
        seg = tk.Frame(top, bg=C["border"], padx=1, pady=1)
        seg.pack(side="left")
        for key, label in (("upcoming", "Upcoming"), ("done", "Done"), ("all", "All")):
            on = self.filter == key
            mkbtn(seg, label, lambda k=key: self._set_filter(k), bg=C["accent"] if on else C["panel"],
                  fg=C["accent_fg"] if on else C["fg"], font=f(9)).pack(side="left")
        mkbtn(top, "Delete", self._delete, bg=C["panel"], fg=C["danger"]).pack(side="right", padx=(6, 0))
        mkbtn(top, "Restore", self._restore, bg=C["panel"]).pack(side="right", padx=(6, 0))
        mkbtn(top, "\u2713 Mark done", self._done, bg=C["panel"], fg=C["ok"]).pack(side="right", padx=(6, 0))
        tk.Label(top, text="Double-click to edit  \u00b7  Ctrl/Shift-click to select several",
                 bg=C["bg"], fg=C["faint"], font=f(8)).pack(side="right", padx=10)

        frame = tk.Frame(self.body, bg=C["border"], padx=1, pady=1)
        frame.pack(fill="both", expand=True)
        cols = ("when", "title", "category", "repeat", "status")
        tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="extended")
        for c, label, w, stretch in (("when", "When", 210, False), ("title", "Reminder", 340, True),
                                     ("category", "Category", 100, False), ("repeat", "Repeats", 110, False),
                                     ("status", "Status", 130, False)):
            tree.heading(c, text=label, anchor="w")
            tree.column(c, width=int(w * self.app.s), stretch=stretch, anchor="w")
        tree.tag_configure("overdue", foreground=C["danger"])
        tree.tag_configure("soon", foreground=C["orange"])
        tree.tag_configure("done", foreground=C["faint"])
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        tree.bind("<Double-1>", lambda e: self._edit_selected())
        tree.bind("<Return>", lambda e: self._edit_selected())
        tree.bind("<Delete>", lambda e: self._delete())
        self.tree = tree
        self.fill_tree()

    def _set_filter(self, k):
        self.filter = k
        self.refresh()

    def fill_tree(self):
        tree = self.tree
        if tree is None or not tree.winfo_exists():
            return
        tree.delete(*tree.get_children())
        store, q = self.app.store, self.q.get().strip().lower()
        items = store.reminders
        if self.filter == "upcoming":
            items = [r for r in items if not r.get("done")]
        elif self.filter == "done":
            items = [r for r in items if r.get("done")]
        if q:
            items = [r for r in items if q in (r["title"] + " " + r.get("notes", "") + " "
                                               + (r.get("category") or "")).lower()]
        pend = sorted([r for r in items if not r.get("done")], key=store.effective)
        done = sorted([r for r in items if r.get("done")], key=lambda r: r["date"], reverse=True)
        for r in pend + done:
            status, color = self.app.countdown(r)
            tag = ("done" if r.get("done") else "overdue" if color == C["danger"]
                   else "soon" if color in (C["orange"], C["warn"]) else "")
            tree.insert("", "end", iid=r["id"], tags=(tag,), values=(
                format_when(r), r["title"], r.get("category") or "Personal",
                dict(REPEATS)[r.get("repeat", "none")] if r.get("repeat", "none") != "none" else "\u2014",
                status))

    def _selected(self):
        if not self.tree:
            return []
        return [r for r in (self.app.store.get(i) for i in self.tree.selection()) if r]

    def _edit_selected(self):
        sel = self._selected()
        if sel:
            self.app.edit(sel[0])

    def _done(self):
        for r in self._selected():
            if not r.get("done"):
                self.app.close_toast(r["id"])
                self.app.store.complete(r["id"])
        self.app.changed()

    def _restore(self):
        for r in self._selected():
            if r.get("done"):
                r["done"] = False
                r["fired_main"] = r["fired_advance"] = True   # don't pop up instantly
                self.app.shown.add(r["id"])
        self.app.store.save()
        self.app.changed()

    def _delete(self):
        sel = self._selected()
        if not sel:
            return
        what = f"\"{sel[0]['title']}\"" if len(sel) == 1 else f"{len(sel)} reminders"
        if messagebox.askyesno("Delete", f"Delete {what}? This can't be undone.", parent=self):
            for r in sel:
                self.app.close_toast(r["id"])
                self.app.store.reminders = [x for x in self.app.store.reminders if x["id"] != r["id"]]
            self.app.store.save()
            self.app.changed()


# ---------------------------------------------------------------- main widget

class App:
    def __init__(self, root, lock=None, background=True):
        self.root = root
        self.lock = lock
        self.events = queue.Queue()
        self.store = Store()
        self.store.settings["theme"] = self.wanted_theme() or self.store.settings["theme"]
        C.clear()
        C.update(THEMES[self.store.settings["theme"]])
        self.s = root.winfo_fpixels("1i") / 96.0
        self.toasts = {}
        self.shown = set()          # reminders already popped up this session
        self.dialog = None
        self.qa = None
        self.big = None
        self.tray = None
        self.hotkey_ok = True
        self._drag = None
        today = date.today()
        self.vy, self.vm = today.year, today.month
        self.last_day = today
        self.last_render_min = -1

        root.title(TITLE)
        root.report_callback_exception = lambda *a: log_error("".join(traceback.format_exception(*a)))
        try:
            from PIL import ImageTk
            self._icon = ImageTk.PhotoImage(make_icon_image(64))
            root.iconphoto(True, self._icon)
        except Exception:
            pass
        self._style()
        root.overrideredirect(True)
        root.configure(bg=C["border"])
        root.attributes("-topmost", self.store.settings["topmost"])
        root.attributes("-alpha", self.store.settings["alpha"])
        self.frame = tk.Frame(root, bg=C["bg"])
        self.frame.pack(fill="both", expand=True, padx=2, pady=2)
        self._blink_on = False
        self._alerting = False
        if background:
            self.tray = self.start_tray()
            threading.Thread(target=hotkey_loop, args=(self.events,), daemon=True).start()
        self.menu = self._build_menu()
        self.render()
        self._place()
        if self.tray and self.store.settings.get("hidden"):
            root.withdraw()
        root.after(1500, self.tick)
        root.after(250, self.poll_events)
        root.after(600, self.blink)
        if background:
            root.after(20_000, self.update_loop)

    # ---- setup
    def _style(self):
        st = ttk.Style(self.root)
        st.theme_use("clam")
        st.configure("TCombobox", fieldbackground=C["panel"], background=C["panel"],
                     foreground=C["fg"], arrowcolor=C["fg"], bordercolor=C["border"],
                     lightcolor=C["panel"], darkcolor=C["panel"], padding=4)
        st.map("TCombobox", fieldbackground=[("readonly", C["panel"])],
               foreground=[("readonly", C["fg"])],
               selectbackground=[("readonly", C["panel"])],
               selectforeground=[("readonly", C["fg"])])
        st.configure("Treeview", background=C["panel"], fieldbackground=C["panel"],
                     foreground=C["fg"], bordercolor=C["border"], rowheight=int(28 * self.s),
                     font=f(10), borderwidth=0)
        st.map("Treeview", background=[("selected", C["accent"])],
               foreground=[("selected", C["accent_fg"])])
        st.configure("Treeview.Heading", background=C["bg"], foreground=C["dim"], font=fh(9),
                     relief="flat", bordercolor=C["border"], lightcolor=C["bg"], darkcolor=C["bg"])
        st.map("Treeview.Heading", background=[("active", C["panel"])])
        st.configure("Vertical.TScrollbar", background=C["panel"], troughcolor=C["bg"],
                     bordercolor=C["bg"], arrowcolor=C["dim"], lightcolor=C["panel"], darkcolor=C["panel"])
        self.root.option_add("*TCombobox*Listbox.background", C["panel"])
        self.root.option_add("*TCombobox*Listbox.foreground", C["fg"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", C["accent"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", C["accent_fg"])
        self.root.option_add("*TCombobox*Listbox.font", f(10))

    def _build_menu(self):
        st = self.store.settings
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="Quick add\u2026", accelerator=HOTKEY_LABEL, command=self.quick_add)
        m.add_command(label="New reminder (full form)\u2026", command=lambda: self.edit(None, date.today()))
        m.add_command(label="Open big calendar", command=self.open_big)
        m.add_command(label="Go to today", command=self.goto_today)
        m.add_separator()
        self.v_theme = tk.StringVar(value=st["theme"])
        th = tk.Menu(m, tearoff=0)
        for name in THEMES:
            th.add_radiobutton(label=f"{name}   ({'dark' if THEMES[name]['dark'] else 'light'})",
                               variable=self.v_theme, value=name,
                               command=lambda n=name: self.apply_theme(n))
        th.add_separator()
        self.v_auto = tk.StringVar(value=st["auto_theme"])
        for val, lbl in AUTO_MODES:
            th.add_radiobutton(label=lbl, variable=self.v_auto, value=val,
                               command=lambda: self.set_auto_theme(self.v_auto.get()))
        th.add_command(label="Light / dark timings…",
                       command=lambda: self._open_dialog(lambda: ThemeDialog(self)))
        m.add_cascade(label="Theme", menu=th)
        self.v_top = tk.BooleanVar(value=st["topmost"])
        m.add_checkbutton(label="Always on top", variable=self.v_top, command=self.toggle_top)
        self.v_start = tk.BooleanVar(value=os.path.exists(STARTUP_LNK))
        m.add_checkbutton(label="Start with Windows", variable=self.v_start, command=self.toggle_startup)
        self.v_hold = tk.BooleanVar(value=st["hold_fullscreen"])
        m.add_checkbutton(label="Hold pop-ups during fullscreen", variable=self.v_hold,
                          command=lambda: self._set("hold_fullscreen", self.v_hold.get()))
        if not FROZEN and os.path.isdir(os.path.join(APP_DIR, ".git")):
            self.v_upd = tk.BooleanVar(value=st["auto_update"])
            m.add_checkbutton(label="Auto-update from GitHub", variable=self.v_upd,
                              command=lambda: self._set("auto_update", self.v_upd.get()))
        self.v_alpha = tk.DoubleVar(value=st["alpha"])
        op = tk.Menu(m, tearoff=0)
        for a in (1.0, 0.97, 0.85, 0.7):
            op.add_radiobutton(label=f"{int(a * 100)}%", variable=self.v_alpha, value=a,
                               command=self.set_alpha)
        m.add_cascade(label="Opacity", menu=op)
        self.v_allday = tk.StringVar(value=st["allday_time"])
        ad = tk.Menu(m, tearoff=0)
        for t in ("07:00", "08:00", "09:00", "10:00", "12:00"):
            ad.add_radiobutton(label=fmt_time(t), variable=self.v_allday, value=t,
                               command=lambda: self._set("allday_time", self.v_allday.get(), True))
        m.add_cascade(label="All-day reminders pop up at", menu=ad)
        self.v_week = tk.IntVar(value=st["week_start"])
        wk = tk.Menu(m, tearoff=0)
        wk.add_radiobutton(label="Monday", variable=self.v_week, value=0,
                           command=lambda: self._set("week_start", 0, True))
        wk.add_radiobutton(label="Sunday", variable=self.v_week, value=6,
                           command=lambda: self._set("week_start", 6, True))
        m.add_cascade(label="Week starts on", menu=wk)
        m.add_separator()
        m.add_command(label="Phone alerts\u2026", command=lambda: self._open_dialog(lambda: PhoneDialog(self)))
        m.add_command(label="Import .ics\u2026", command=self.import_ics)
        m.add_command(label="Export .ics\u2026", command=self.export_ics)
        m.add_command(label="Open data folder", command=lambda: os.startfile(DATA_DIR))
        m.add_separator()
        if self.tray:
            m.add_command(label="Hide to tray", command=self.hide_widget)
        m.add_command(label="Quit", command=self.quit)
        return m

    def _set(self, key, value, rerender=False):
        self.store.settings[key] = value
        self.store.save_settings()
        if rerender:
            self.changed()

    def _place(self):
        self.root.update_idletasks()
        st = self.store.settings
        w = self.root.winfo_reqwidth()
        if st["x"] is None:
            l, t, r, b = work_area(self.root)
            x, y = r - w - int(24 * self.s), t + int(24 * self.s)
        else:
            vl, vt, vr, vb = virtual_screen(self.root)
            x = max(vl, min(st["x"], vr - 80))
            y = max(vt, min(st["y"], vb - 40))
        self.root.geometry(f"+{x}+{y}")

    # ---- tray
    def start_tray(self):
        try:
            import pystray
        except Exception:
            return None
        q = self.events
        item = pystray.MenuItem
        menu = pystray.Menu(
            item("Show / hide calendar", lambda i, it: q.put("toggle"), default=True),
            item(f"Quick add   ({HOTKEY_LABEL})", lambda i, it: q.put("quickadd")),
            item("Open big calendar", lambda i, it: q.put("big")),
            pystray.Menu.SEPARATOR,
            item("Quit", lambda i, it: q.put("quit")))
        try:
            icon = pystray.Icon(APP, make_icon_image(64), TITLE, menu)
            icon.run_detached()
            return icon
        except Exception:
            log_error(traceback.format_exc())
            return None

    def update_tray_title(self):
        if not self.tray:
            return
        up = self._upcoming()
        text = TITLE
        if up:
            label, _ = self.countdown(up[0])
            text = f"{TITLE}\nNext: {up[0]['title'][:40]} ({label})"
        try:
            self.tray.title = text[:120]
        except Exception:
            pass

    def hide_widget(self):
        if not self.tray:  # no tray icon available: collapse instead of vanishing
            if not self.store.settings["collapsed"]:
                self.toggle_collapse()
            return
        Tip.close()
        self.root.withdraw()
        self._set("hidden", True)
        if not self.store.settings.get("tray_hint_shown"):
            self._set("tray_hint_shown", True)
            Notice(self, "__trayhint__", "Still running",
                   "The calendar is hiding in the system tray (the ^ hidden-icons area by the clock). "
                   f"Click its icon to bring it back, or press {HOTKEY_LABEL} to quick-add. "
                   "Tip: drag the icon onto the taskbar to keep it always visible.",
                   [("Got it", None)])

    def show(self):
        if self.store.settings["collapsed"]:
            self.toggle_collapse()
        self.root.deiconify()
        self.root.lift()
        self._set("hidden", False)

    def toggle_widget(self):
        if self.root.state() == "withdrawn":
            self.show()
        else:
            self.hide_widget()

    # ---- events from tray / hotkey / second launch
    def poll_events(self):
        try:
            while True:
                ev = self.events.get_nowait()
                if ev == "quickadd":
                    self.quick_add()
                elif ev == "toggle":
                    self.toggle_widget()
                elif ev == "big":
                    self.open_big()
                elif ev == "quit":
                    self.quit()
                elif ev == "show":
                    self.show()
                elif ev == "hotkey-failed":
                    self.hotkey_ok = False
                    log_error(f"Global hotkey {HOTKEY_LABEL} is used by another app.")
                elif ev == "updated":
                    Notice(self, "__update__", "Update installed",
                           "A newer version was downloaded from GitHub. Restart to use it.",
                           [("Restart now", self.restart), ("Later", None)])
        except queue.Empty:
            pass
        if self.lock is not None:
            try:
                conn, _ = self.lock.accept()
                conn.close()
                self.show()
            except (BlockingIOError, OSError):
                pass
        self.root.after(250, self.poll_events)

    # ---- drag / click
    def make_drag(self, w, on_click=None):
        def press(e):
            self._drag = (e.x_root, e.y_root, self.root.winfo_x(), self.root.winfo_y(), False)

        def motion(e):
            if not self._drag:
                return
            sx, sy, wx, wy, moved = self._drag
            dx, dy = e.x_root - sx, e.y_root - sy
            if moved or abs(dx) + abs(dy) > 4:
                self._drag = (sx, sy, wx, wy, True)
                self.root.geometry(f"+{wx + dx}+{wy + dy}")

        def release(_e):
            d, self._drag = self._drag, None
            if not d:
                return
            if d[4]:
                self.store.settings["x"] = self.root.winfo_x()
                self.store.settings["y"] = self.root.winfo_y()
                self.store.save_settings()
            elif on_click:
                on_click()

        w.bind("<ButtonPress-1>", press)
        w.bind("<B1-Motion>", motion)
        w.bind("<ButtonRelease-1>", release)

    def bind_menu(self, w):
        w.bind("<Button-3>", lambda e: self.menu.tk_popup(e.x_root, e.y_root))
        for c in w.winfo_children():
            self.bind_menu(c)

    # ---- rendering
    def changed(self):
        """Call after any reminder data changes: refresh every view."""
        self.render()
        if self.big is not None:
            try:
                self.big.refresh()
            except tk.TclError:
                self.big = None

    def render(self):
        Tip.close()
        for w in self.frame.winfo_children():
            w.destroy()
        if self.store.settings["collapsed"]:
            self._render_collapsed()
        else:
            self._render_full()
        self.bind_menu(self.frame)
        self.last_render_min = datetime.now().minute
        self.update_tray_title()

    def _upcoming(self):
        return sorted(self.store.pending(), key=self.store.effective)

    def countdown(self, r, now=None, compact=False):
        """Status text + colour, e.g. ('3 days left', warn)."""
        now = now or datetime.now()
        today = now.date()
        if r.get("done"):
            return "done \u2713", C["faint"]
        eff = self.store.effective(r)
        n = (eff.date() - today).days
        if r.get("snooze_until"):
            return ("snoozed \u00b7 " + (fmt_time(f"{eff:%H:%M}") if n == 0 else rel_days(n))), C["warn"]
        if n < 0 or (r.get("time") and eff <= now):
            return "overdue", C["danger"]
        if n == 0:
            return (fmt_time(r.get("time")) or "today"), C["orange"]
        if n == 1:
            return "tomorrow", C["warn"]
        left = f"{n}d left" if compact else f"{n} days left"
        if n <= 3:
            return left, C["warn"]
        if n <= 14:
            return left, C["ok"]
        return f"{eff.day} {eff:%b}", C["dim"]

    def _render_collapsed(self):
        today = date.today()
        row = tk.Frame(self.frame, bg=C["bg"], padx=10, pady=6, cursor="fleur")
        row.pack()
        up = self._upcoming()
        icon = tk.Label(row, text="\u25f7", bg=C["bg"], fg=C["accent"], font=f(11))
        txt = tk.Label(row, text=f"{today:%a} {today.day} {today:%b}", bg=C["bg"],
                       fg=C["fg"], font=fh(10))
        if up:
            label, color = self.countdown(up[0], compact=True)
            more = f"  \u00b7  {up[0]['title'][:22]} "
            sub2 = tk.Label(row, text=label, bg=C["bg"], fg=color, font=f(9, "bold"))
        else:
            more, sub2 = "  \u00b7  nothing due", None
        sub = tk.Label(row, text=more, bg=C["bg"], fg=C["dim"], font=f(9))
        widgets = [icon, txt, sub] + ([sub2] if sub2 else [])
        for w in widgets:
            w.pack(side="left")
        for w in [row] + widgets:
            self.make_drag(w, on_click=self.toggle_collapse)

    def _render_full(self):
        today = date.today()
        now = datetime.now()
        hdr = tk.Frame(self.frame, bg=C["bg"], padx=6, pady=6)
        hdr.pack(fill="x")
        hb = dict(bg=C["bg"], font=f(11), padx=5, pady=0)
        mkbtn(hdr, "\u2039", lambda: self.shift(-1), **hb).pack(side="left")
        title = tk.Label(hdr, text=heading(f"{calendar.month_abbr[self.vm]} {self.vy}", spaced=False),
                         bg=C["bg"], fg=C["fg"], font=fh(11), cursor="fleur")
        title.pack(side="left")
        mkbtn(hdr, "\u203a", lambda: self.shift(1), **hb).pack(side="left")
        close = mkbtn(hdr, "\u00d7", self.hide_widget, **hb)
        close.pack(side="right")
        Tip(close, "Hide to tray" if self.tray else "Collapse")
        mkbtn(hdr, "\u2013", self.toggle_collapse, **hb).pack(side="right")
        mkbtn(hdr, "\u22ef", lambda: self.menu.tk_popup(self.root.winfo_pointerx(),
                                                        self.root.winfo_pointery()), **hb).pack(side="right")
        big = mkbtn(hdr, "\u25a6", self.open_big, **hb)
        big.pack(side="right")
        Tip(big, "Big calendar")
        add = mkbtn(hdr, "+", self.quick_add, **hb)
        add.pack(side="right")
        Tip(add, f"Quick add ({HOTKEY_LABEL})")
        self.make_drag(hdr)
        self.make_drag(title, on_click=self.goto_today)

        tk.Frame(self.frame, bg=C["border"], height=1).pack(fill="x", padx=10)
        if not C["dark"]:  # double rule: a little printed-almanac flourish
            tk.Frame(self.frame, bg=C["border"], height=1).pack(fill="x", padx=10, pady=(2, 0))

        grid = tk.Frame(self.frame, bg=C["bg"], padx=8, pady=4)
        grid.pack()
        ws = self.store.settings["week_start"]
        names = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
        for i in range(7):
            n = names[(ws + i) % 7]
            tk.Label(grid, text=n.upper() if C["upper"] else n, bg=C["bg"], fg=C["faint"],
                     font=f(8), width=4).grid(row=0, column=i, pady=(0, 2))

        pending = self.store.pending()
        cal = calendar.Calendar(ws)
        for wi, week in enumerate(cal.monthdayscalendar(self.vy, self.vm), start=1):
            for di, day in enumerate(week):
                if not day:
                    tk.Label(grid, text="", bg=C["bg"], width=4).grid(row=wi, column=di)
                    continue
                d = date(self.vy, self.vm, day)
                evs = [r for r in pending if occurs_on(r, d)]
                bg, fg, font = C["bg"], C["fg"], f(9)
                if d < today:
                    fg = C["faint"]
                if evs:
                    bg, fg, font = C["event"], C["fg"], f(9, "bold")
                if d == today:
                    bg, fg, font = C["accent"], C["accent_fg"], f(9, "bold")
                cell = tk.Label(grid, text=str(day), bg=bg, fg=fg, font=font, width=4,
                                pady=3, cursor="hand2")
                cell.grid(row=wi, column=di, padx=1, pady=1)
                cell.bind("<Button-1>", lambda e, dd=d: self.open_day(dd))
                if bg == C["bg"]:
                    cell.bind("<Enter>", lambda e, c=cell: c.config(bg=C["panel"]))
                    cell.bind("<Leave>", lambda e, c=cell: c.config(bg=C["bg"]))
                if evs:
                    Tip(cell, "\n".join(f"{fmt_time(r.get('time')) or 'All day'}  \u00b7  {r['title']}"
                                        for r in evs))

        tk.Frame(self.frame, bg=C["border"], height=1).pack(fill="x", padx=10, pady=(6, 6))
        box = tk.Frame(self.frame, bg=C["bg"], padx=12)
        box.pack(fill="x", pady=(0, 10))
        tk.Label(box, text=heading("Upcoming"), bg=C["bg"], fg=C["faint"],
                 font=fh(8)).pack(anchor="w", pady=(0, 3))
        up = self._upcoming()[:6]
        if not up:
            tk.Label(box, text=f"Nothing yet. Click + or press {HOTKEY_LABEL}.",
                     bg=C["bg"], fg=C["dim"], font=f(9)).pack(anchor="w")
        for r in up:
            label, color = self.countdown(r, now, compact=True)
            row = tk.Frame(box, bg=C["bg"], cursor="hand2")
            row.pack(fill="x", pady=1)
            title_txt = r["title"] if len(r["title"]) <= 22 else r["title"][:21] + "\u2026"
            if r.get("repeat", "none") != "none":
                title_txt += "  \u21bb"
            ws_ = [tk.Label(row, text="\u25cf", bg=C["bg"], fg=cat_color(r), font=f(8)),
                   tk.Label(row, text=title_txt, bg=C["bg"], fg=C["fg"], font=f(9), anchor="w"),
                   tk.Label(row, text=label, bg=C["bg"], fg=color, font=f(8, "bold"))]
            ws_[0].pack(side="left", padx=(0, 6))
            ws_[2].pack(side="right")
            ws_[1].pack(side="left", fill="x", expand=True)
            for w in [row] + ws_:
                w.bind("<Button-1>", lambda e, rr=r: self.edit(rr))

    # ---- actions
    def shift(self, n):
        d = add_months(date(self.vy, self.vm, 1), n)
        self.vy, self.vm = d.year, d.month
        self.render()

    def goto_today(self):
        t = date.today()
        self.vy, self.vm = t.year, t.month
        self.render()

    def toggle_collapse(self):
        self._set("collapsed", not self.store.settings["collapsed"])
        self.render()

    def open_day(self, d):
        items = [r for r in self.store.pending() if occurs_on(r, d)]
        if not items:
            return self.edit(None, d)
        self._open_dialog(lambda: DayDialog(self, d, items))

    def edit(self, r, day=None, prefill=None):
        self._open_dialog(lambda: ReminderDialog(self, r, day, prefill))

    def quick_add(self):
        Tip.close()
        if self.qa is not None:
            try:
                if self.qa.winfo_exists():
                    self.qa.grab_focus()
                    return
            except tk.TclError:
                pass
        self.qa = QuickAdd(self)

    def open_big(self):
        if self.big is not None:
            try:
                self.big.deiconify()
                self.big.lift()
                self.big.focus_force()
                return
            except tk.TclError:
                self.big = None
        self.big = BigCalendar(self)

    def _open_dialog(self, make):
        Tip.close()
        if self.dialog is not None:
            try:
                self.dialog.destroy()
            except tk.TclError:
                pass
        self.dialog = make()

    def wanted_theme(self, now=None):
        """The theme the light/dark schedule wants right now, or None when switching is off."""
        st = self.store.settings
        mode = st.get("auto_theme", "off")
        if mode == "windows":
            light = windows_light()
            if light is None:
                return None
        elif mode == "schedule":
            t = f"{(now or datetime.now()):%H:%M}"
            a, b = st.get("light_start", "07:00"), st.get("dark_start", "19:00")
            light = (a <= t < b) if a <= b else not (b <= t < a)
        else:
            return None
        name = st.get("light_theme") if light else st.get("dark_theme")
        return name if name in THEMES else None

    def set_auto_theme(self, mode):
        self._set("auto_theme", mode)
        self.v_auto.set(mode)
        w = self.wanted_theme()
        if w and w != self.store.settings["theme"]:
            self.apply_theme(w, manual=False)

    def apply_theme(self, name, manual=True):
        if manual and self.store.settings.get("auto_theme", "off") != "off":
            # picking a theme by hand means "keep this one": stop automatic switching
            self.store.settings["auto_theme"] = "off"
            self.v_auto.set("off")
        C.clear()
        C.update(THEMES[name])
        self.v_theme.set(name)
        self._set("theme", name)
        self._style()
        self.root.configure(bg=C["border"])
        self.frame.configure(bg=C["bg"])
        for w in (self.dialog, self.qa):
            try:
                if w is not None:
                    w.destroy()
            except tk.TclError:
                pass
        reopen = self.big is not None
        if reopen:
            try:
                self.big.close()
            except tk.TclError:
                self.big = None
        self.render()
        if reopen:
            self.open_big()

    def save_reminder(self, r, data, refresh=True):
        store = self.store
        if r is None:
            r = {"id": uuid.uuid4().hex[:12], "created": datetime.now().isoformat(timespec="seconds")}
            store.reminders.append(r)
            timing_changed = True
        else:
            timing_changed = any(r.get(k) != data.get(k) for k in ("date", "time", "advance", "repeat"))
        r.update(data)
        if timing_changed:
            r.update(anchor=r["date"], done=False, snooze_until=None,
                     fired_main=False, fired_advance=False)
            self.shown.discard(r["id"])
            # Don't pop up instantly for something you just entered that is already due.
            now, due = datetime.now(), store.due(r)
            if due <= now:
                r["fired_main"] = r["fired_advance"] = True
                self.shown.add(r["id"])
            elif r.get("advance") and now >= due - timedelta(days=r["advance"]):
                r["fired_advance"] = True
            self.close_toast(r["id"])
        if refresh:
            store.save()
            d = date.fromisoformat(r["date"])
            self.vy, self.vm = d.year, d.month
            self.changed()
        return r

    def toggle_top(self):
        self._set("topmost", self.v_top.get())
        self.root.attributes("-topmost", self.v_top.get())

    def set_alpha(self):
        self._set("alpha", self.v_alpha.get())
        self.root.attributes("-alpha", self.v_alpha.get())

    def toggle_startup(self):
        try:
            if self.v_start.get():
                target, args = (SCRIPT, "") if FROZEN else (pythonw_path(), f'"{SCRIPT}"')
                q = lambda p: p.replace("'", "''")
                ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{}');"
                      "$s.TargetPath='{}';$s.Arguments='{}';$s.WorkingDirectory='{}';"
                      "$s.Save()").format(q(STARTUP_LNK), q(target), q(args), q(APP_DIR))
                subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                               creationflags=NO_WINDOW, check=True, timeout=30)
            elif os.path.exists(STARTUP_LNK):
                os.remove(STARTUP_LNK)
        except Exception as e:
            log_error(traceback.format_exc())
            messagebox.showerror(TITLE, f"Couldn't change the startup setting:\n{e}", parent=self.root)
        self.v_start.set(os.path.exists(STARTUP_LNK))

    def export_ics(self):
        pend = self.store.pending()
        if not pend:
            return messagebox.showinfo(TITLE, "There are no upcoming reminders to export.", parent=self.root)
        path = filedialog.asksaveasfilename(parent=self.big or self.root, title="Export reminders",
                                            defaultextension=".ics", initialfile="reminders.ics",
                                            filetypes=[("Calendar file", "*.ics")])
        if not path:
            return
        try:
            export_ics(pend, path)
            messagebox.showinfo(TITLE, f"Exported {len(pend)} reminders.\n\nYou can import this file "
                                "into Google Calendar or Outlook.", parent=self.root)
        except Exception as e:
            messagebox.showerror(TITLE, f"Export failed:\n{e}", parent=self.root)

    def import_ics(self):
        path = filedialog.askopenfilename(parent=self.big or self.root, title="Import reminders",
                                          filetypes=[("Calendar file", "*.ics"), ("All files", "*.*")])
        if not path:
            return
        try:
            recs = read_ics(path)
        except Exception as e:
            return messagebox.showerror(TITLE, f"Couldn't read that file:\n{e}", parent=self.root)
        known = {r.get("ics_uid") for r in self.store.reminders if r.get("ics_uid")}
        added = 0
        for rec in recs:
            if rec["ics_uid"] and rec["ics_uid"] in known:
                continue
            anchor = rec.pop("anchor", None)
            r = self.save_reminder(None, rec, refresh=False)
            if anchor:
                r["anchor"] = anchor
            added += 1
        self.store.save()
        self.changed()
        messagebox.showinfo(TITLE, f"Imported {added} upcoming reminder(s)."
                            + (f"\nSkipped {len(recs) - added} already imported." if len(recs) - added else ""),
                            parent=self.root)

    def restart(self):
        try:
            if self.lock is not None:
                self.lock.close()
                self.lock = None
            cmd = [SCRIPT] if FROZEN else [pythonw_path(), SCRIPT]
            subprocess.Popen(cmd, cwd=APP_DIR, creationflags=0x00000008 | 0x00000200)
        except Exception:
            log_error(traceback.format_exc())
            return
        self.shutdown()

    def quit(self):
        if messagebox.askyesno(TITLE, "Reminders won't pop up while the calendar is closed.\n\n"
                               "Quit anyway?" + ("\n\n(Tip: the \u00d7 button hides it to the tray instead.)"
                                                 if self.tray else ""), parent=self.root):
            self.shutdown()

    def shutdown(self):
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
        self.root.destroy()

    # ---- reminders
    def close_toast(self, rid):
        t = self.toasts.get(rid)
        if t:
            t.close()

    def restack_toasts(self):
        l, t, r, b = work_area(self.root)
        gap = int(12 * self.s)
        y = b - gap
        w = int(350 * self.s)
        for toast in list(self.toasts.values()):
            try:
                toast.update_idletasks()
                h = toast.winfo_reqheight()
            except tk.TclError:
                continue
            y -= h
            toast.geometry(f"{w}x{h}+{r - w - gap}+{max(t, y)}")
            y -= int(8 * self.s)

    def blink(self):
        """While a reminder pop-up is waiting, flash the widget border, the card edge and the tray icon."""
        try:
            waiting = [t for t in self.toasts.values() if isinstance(t, Toast)]
            if waiting:
                self._blink_on = not self._blink_on
                on = self._blink_on
                self.root.configure(bg=C["danger"] if on else C["accent"])
                for t in waiting:
                    t.outer.configure(bg=C["danger"] if on else t.stripe)
                    t.configure(bg=C["danger"] if on else C["border"])
                if self.tray:
                    self.tray.icon = self._tray_img(alert=on)
            elif self._alerting:
                self._blink_on = False
                self.root.configure(bg=C["border"])
                if self.tray:
                    self.tray.icon = self._tray_img(alert=False)
            self._alerting = bool(waiting)
        except Exception:
            log_error(traceback.format_exc())
        self.root.after(600, self.blink)

    def _tray_img(self, alert):
        key = "_img_alert" if alert else "_img_normal"
        if not hasattr(self, key):
            setattr(self, key, make_icon_image(64, alert=alert))
        return getattr(self, key)

    def fire(self, r, kind):
        self.shown.add(r["id"])
        Toast(self, r, kind)
        topic = self.store.settings.get("phone_topic")
        if topic:
            head = {"advance": "Coming up", "missed": "Missed"}.get(kind, "Reminder")
            ntfy_send_async(topic, f"\u23f0 {head}: {r['title']}",
                            format_when(r) + (f"\n{r['notes']}" if r.get("notes") else ""))

    def check_reminders(self):
        if self.store.settings.get("hold_fullscreen") and foreground_fullscreen():
            return  # wait until the game / video / slideshow is closed
        now = datetime.now()
        changed = False
        for r in list(self.store.reminders):
            rid = r["id"]
            if r.get("done") or rid in self.toasts:
                continue
            snooze = r.get("snooze_until")
            if snooze:
                if now >= datetime.fromisoformat(snooze):
                    r["snooze_until"] = None
                    changed = True
                    self.fire(r, "snooze")
                continue
            due = self.store.due(r)
            if now >= due and (not r.get("fired_main") or rid not in self.shown):
                # Fires on time, or on the next launch if the PC was off / it was never acknowledged.
                r["fired_main"] = r["fired_advance"] = True
                changed = True
                self.fire(r, "missed" if now - due > timedelta(minutes=30) else "due")
            elif (now < due and not r.get("fired_advance") and r.get("advance")
                  and now >= due - timedelta(days=r["advance"])):
                r["fired_advance"] = True
                changed = True
                self.fire(r, "advance")
        if changed:
            self.store.save()
            self.changed()

    def update_loop(self):
        self.check_update()
        self.root.after(12 * 3600 * 1000, self.update_loop)

    def check_update(self):
        if FROZEN or not self.store.settings.get("auto_update"):
            return
        if not os.path.isdir(os.path.join(APP_DIR, ".git")):
            return
        git = find_git()
        if not git:
            return

        def work():
            try:
                def run(*a):
                    return subprocess.run([git, "-C", APP_DIR, *a], capture_output=True, text=True,
                                          timeout=90, creationflags=NO_WINDOW)
                before = run("rev-parse", "HEAD").stdout.strip()
                p = run("pull", "--ff-only", "-q")
                after = run("rev-parse", "HEAD").stdout.strip()
                if p.returncode != 0:
                    log_error("Auto-update failed:\n" + p.stderr)
                elif before and after and before != after:
                    self.events.put("updated")
            except Exception:
                log_error(traceback.format_exc())
        threading.Thread(target=work, daemon=True).start()

    def tick(self):
        try:
            w = self.wanted_theme()
            if w and w != self.store.settings["theme"]:
                self.apply_theme(w, manual=False)
            self.check_reminders()
            today = date.today()
            if today != self.last_day:
                self.last_day = today
                self.goto_today()
                if self.big is not None:
                    self.big.refresh()
            elif (datetime.now().minute != self.last_render_min and Tip.current is None
                  and self._drag is None):
                self.render()
            if self.store.settings["topmost"] and self.root.state() != "withdrawn":
                self.root.attributes("-topmost", True)
        except Exception:
            log_error(traceback.format_exc())
        self.root.after(10_000, self.tick)


# ---------------------------------------------------------------- entry point

def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    # Only one copy at a time; launching again just brings the widget forward.
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock.bind(("127.0.0.1", LOCK_PORT))
    except OSError:
        try:
            with socket.create_connection(("127.0.0.1", LOCK_PORT), timeout=2) as c:
                c.sendall(b"show")
        except OSError:
            pass
        return
    lock.listen(5)
    lock.setblocking(False)

    root = tk.Tk()
    App(root, lock)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log_error(traceback.format_exc())
        raise
