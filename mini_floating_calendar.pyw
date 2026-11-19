#!/usr/bin/env python3
"""Mini Floating Calendar - a small floating calendar for Windows that pops up reminders.

Double-click this file to run it (it opens with pythonw, so no console window).
Your reminders are stored in %APPDATA%\\MiniFloatingCalendar\\reminders.json.
"""

import calendar
import ctypes
import json
import os
import re
import socket
import subprocess
import sys
import traceback
import uuid
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import date, datetime, timedelta

try:
    import winsound
except ImportError:  # not on Windows
    winsound = None

APP = "MiniFloatingCalendar"
DATA_DIR = os.environ.get("FLOATCAL_DATA") or os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")), APP)
REM_FILE = os.path.join(DATA_DIR, "reminders.json")
SET_FILE = os.path.join(DATA_DIR, "settings.json")
LOG_FILE = os.path.join(DATA_DIR, "error.log")
STARTUP_LNK = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                           "Start Menu", "Programs", "Startup", "MiniFloatingCalendar.lnk")
LOCK_PORT = 47613
NO_WINDOW = 0x08000000

C = {
    "bg": "#1c1d24", "panel": "#272935", "fg": "#e8e8ee", "dim": "#8b8e9c",
    "faint": "#5a5d6b", "accent": "#6c8cff", "event": "#353b5e", "ok": "#4cd295",
    "danger": "#ff6b6b", "warn": "#ffb454", "border": "#3a3d4c",
}
F = "Segoe UI"

DEFAULT_SETTINGS = {"x": None, "y": None, "topmost": True, "alpha": 0.96,
                    "collapsed": False, "allday_time": "09:00", "week_start": 0}

REPEATS = [("none", "Does not repeat"), ("daily", "Every day"), ("weekly", "Every week"),
           ("monthly", "Every month"), ("yearly", "Every year")]
ADVANCE = [(0, "No early reminder"), (1, "1 day before"), (2, "2 days before"),
           (3, "3 days before"), (7, "1 week before")]


# ---------------------------------------------------------------- helpers

def log_error(text):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}]\n{text}\n")
    except OSError:
        pass


def parse_time(s):
    """'17:30', '5:30 pm', '5pm', '' -> 'HH:MM' or '' (all day)."""
    s = s.strip().lower().replace(".", "").replace(" ", "")
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
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    today = date.today()
    for f in SHORT_FORMATS:
        try:
            d = datetime.strptime(f"{s} 2000", f + " %Y").date()
        except ValueError:
            continue
        d = d.replace(year=today.year) if not (d.month == 2 and d.day == 29) else d
        if d < today:
            d = d.replace(year=today.year + 1)
        return d
    raise ValueError(s)


def clamp_day(y, m, d):
    return date(y, m, min(d, calendar.monthrange(y, m)[1]))


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
        y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
        return clamp_day(y, m, anchor.day)
    if rep == "yearly":
        return clamp_day(d.year + 1, anchor.month, anchor.day)
    return None


def fmt_time(t):
    if not t:
        return ""
    return datetime.strptime(t, "%H:%M").strftime("%I:%M %p").lstrip("0")


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
    h = hex_.lstrip("#")
    return "#" + "".join(f"{min(255, int(h[i:i + 2], 16) + amt):02x}" for i in (0, 2, 4))


def work_area(root):
    try:
        class RECT(ctypes.Structure):
            _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                        ("r", ctypes.c_long), ("b", ctypes.c_long)]
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


def mkbtn(parent, text, cmd, bg=None, fg=None, font=None, padx=10, pady=4):
    """A flat label that behaves like a button (looks better than tk.Button)."""
    bg = bg or C["panel"]
    fg = fg or C["fg"]
    b = tk.Label(parent, text=text, bg=bg, fg=fg, font=font or (F, 9),
                 padx=padx, pady=pady, cursor="hand2")
    hover = shade(bg)
    b.bind("<Enter>", lambda e: b.config(bg=hover))
    b.bind("<Leave>", lambda e: b.config(bg=bg))
    b.bind("<Button-1>", lambda e: cmd())
    return b


# ---------------------------------------------------------------- storage

class Store:
    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.reminders = self._load(REM_FILE, [])
        self.settings = {**DEFAULT_SETTINGS, **self._load(SET_FILE, {})}

    @staticmethod
    def _load(path, default):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
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
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
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
        tk.Label(tw, text=self.text, bg=C["panel"], fg=C["fg"], font=(F, 9),
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


# ---------------------------------------------------------------- popup toast

HEADS = {
    "due": ("⏰  REMINDER", C["accent"]),
    "snooze": ("⏰  REMINDER (snoozed)", C["accent"]),
    "missed": ("⚠  MISSED REMINDER", C["danger"]),
    "advance": ("◷  COMING UP", C["ok"]),
}


class Toast(tk.Toplevel):
    def __init__(self, app, r, kind):
        super().__init__(app.root)
        self.app, self.rid, self.kind = app, r["id"], kind
        s = app.s
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        head, color = HEADS[kind]
        self.configure(bg=color)

        body = tk.Frame(self, bg=C["panel"], padx=int(14 * s), pady=int(12 * s))
        body.pack(fill="both", expand=True, padx=(int(5 * s), 0))
        wrap = int(300 * s)

        tk.Label(body, text=head, bg=C["panel"], fg=color, font=(F, 8, "bold"),
                 anchor="w").pack(fill="x")
        tk.Label(body, text=r["title"], bg=C["panel"], fg=C["fg"], font=(F, 13, "bold"),
                 wraplength=wrap, justify="left", anchor="w").pack(fill="x", pady=(3, 0))

        if kind == "advance":
            n = (date.fromisoformat(r["date"]) - date.today()).days
            when = f"{rel_days(n).capitalize()}  ·  {format_when(r)}"
        elif kind == "missed":
            when = f"Was due {format_when(r)}"
        else:
            when = format_when(r)
        tk.Label(body, text=when, bg=C["panel"], fg=C["dim"], font=(F, 9),
                 wraplength=wrap, justify="left", anchor="w").pack(fill="x", pady=(2, 0))
        if r.get("notes"):
            tk.Label(body, text=r["notes"], bg=C["panel"], fg=C["fg"], font=(F, 9),
                     wraplength=wrap, justify="left", anchor="w").pack(fill="x", pady=(8, 0))

        row = tk.Frame(body, bg=C["panel"])
        row.pack(fill="x", pady=(12, 0))
        if kind == "advance":
            mkbtn(row, "Got it", self.close, bg=C["accent"], fg="white").pack(side="right")
            mkbtn(row, "Open", self.open, bg=C["border"]).pack(side="right", padx=(0, 6))
        else:
            mkbtn(row, "✓ Done", self.done, bg=C["ok"], fg="#0d1a14",
                  font=(F, 9, "bold")).pack(side="right")
            tk.Label(row, text="Snooze", bg=C["panel"], fg=C["dim"],
                     font=(F, 8)).pack(side="left", padx=(0, 4))
            for label, delta in (("10 min", timedelta(minutes=10)),
                                 ("1 hr", timedelta(hours=1)), ("Tomorrow", None)):
                mkbtn(row, label, lambda d=delta: self.snooze(d), bg=C["border"],
                      font=(F, 8), padx=7, pady=3).pack(side="left", padx=(0, 4))

        app.toasts[self.rid] = self
        app.restack_toasts()
        play_sound()

    def close(self):
        self.app.toasts.pop(self.rid, None)
        self.destroy()
        self.app.restack_toasts()

    def done(self):
        self.app.store.complete(self.rid)
        self.close()
        self.app.render()

    def snooze(self, delta):
        if delta is None:
            t = datetime.strptime(self.app.store.settings["allday_time"], "%H:%M").time()
            until = datetime.combine(date.today() + timedelta(days=1), t)
        else:
            until = datetime.now() + delta
        self.app.store.snooze(self.rid, until)
        self.close()
        self.app.render()

    def open(self):
        self.close()
        r = self.app.store.get(self.rid)
        if r:
            self.app.edit(r)


# ---------------------------------------------------------------- dialogs

def entry(parent, var, width):
    return tk.Entry(parent, textvariable=var, width=width, bg=C["panel"], fg=C["fg"],
                    insertbackground=C["fg"], relief="flat", font=(F, 10),
                    highlightthickness=1, highlightcolor=C["accent"],
                    highlightbackground=C["border"])


class ReminderDialog(tk.Toplevel):
    def __init__(self, app, r=None, day=None):
        super().__init__(app.root)
        self.app, self.r = app, r
        self.title("Edit reminder" if r else "New reminder")
        self.configure(bg=C["bg"], padx=18, pady=16)
        self.attributes("-topmost", True)
        self.resizable(False, False)

        d = date.fromisoformat(r["date"]) if r else (day or date.today())
        self.v_title = tk.StringVar(value=r["title"] if r else "")
        self.v_date = tk.StringVar(value=f"{d.day} {d:%b %Y}")
        self.v_time = tk.StringVar(value=fmt_time(r.get("time")) if r else "")
        adv = r.get("advance", 0) if r else 0
        self.v_adv = tk.StringVar(value=dict(ADVANCE).get(adv, ADVANCE[0][1]))
        rep = r.get("repeat", "none") if r else "none"
        self.v_rep = tk.StringVar(value=dict(REPEATS)[rep])

        def lab(text, row, col=0, **kw):
            tk.Label(self, text=text, bg=C["bg"], fg=C["dim"], font=(F, 9),
                     anchor="w").grid(row=row, column=col, sticky="w", pady=(10, 2), **kw)

        def hint(text, row, col=0, **kw):
            tk.Label(self, text=text, bg=C["bg"], fg=C["faint"], font=(F, 8),
                     anchor="w").grid(row=row, column=col, sticky="w", **kw)

        lab("What do you need to remember?", 0, columnspan=2)
        self.e_title = entry(self, self.v_title, 40)
        self.e_title.grid(row=1, column=0, columnspan=2, sticky="we", ipady=4)

        lab("Date", 2)
        lab("Time (optional)", 2, 1, padx=(12, 0))
        entry(self, self.v_date, 18).grid(row=3, column=0, sticky="we", ipady=4)
        entry(self, self.v_time, 18).grid(row=3, column=1, sticky="we", ipady=4, padx=(12, 0))
        hint("e.g. 1 Dec 2026 or 01/12/2026", 4)
        hint("e.g. 5:30 pm; empty = all day", 4, 1, padx=(12, 0))

        chips = tk.Frame(self, bg=C["bg"])
        chips.grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))
        for label, days in (("Today", 0), ("Tomorrow", 1), ("In 1 week", 7)):
            mkbtn(chips, label, lambda n=days: self._set_date(n), bg=C["panel"],
                  font=(F, 8), padx=8, pady=2).pack(side="left", padx=(0, 5))

        lab("Remind me early", 6)
        lab("Repeat", 6, 1, padx=(12, 0))
        ttk.Combobox(self, textvariable=self.v_adv, values=[a[1] for a in ADVANCE],
                     state="readonly", width=17).grid(row=7, column=0, sticky="we")
        ttk.Combobox(self, textvariable=self.v_rep, values=[x[1] for x in REPEATS],
                     state="readonly", width=17).grid(row=7, column=1, sticky="we", padx=(12, 0))

        lab("Notes (optional)", 8, columnspan=2)
        self.t_notes = tk.Text(self, height=3, width=40, bg=C["panel"], fg=C["fg"],
                               insertbackground=C["fg"], relief="flat", font=(F, 10),
                               highlightthickness=1, highlightcolor=C["accent"],
                               highlightbackground=C["border"], wrap="word")
        self.t_notes.grid(row=9, column=0, columnspan=2, sticky="we")
        if r and r.get("notes"):
            self.t_notes.insert("1.0", r["notes"])

        self.err = tk.Label(self, text="", bg=C["bg"], fg=C["danger"], font=(F, 9),
                            anchor="w", wraplength=380, justify="left")
        self.err.grid(row=10, column=0, columnspan=2, sticky="w", pady=(8, 0))

        btns = tk.Frame(self, bg=C["bg"])
        btns.grid(row=11, column=0, columnspan=2, sticky="we", pady=(8, 0))
        mkbtn(btns, "Save", self.save, bg=C["accent"], fg="white",
              font=(F, 9, "bold"), padx=16).pack(side="right")
        mkbtn(btns, "Cancel", self.destroy, bg=C["panel"]).pack(side="right", padx=(0, 6))
        if r:
            mkbtn(btns, "Delete", self.delete, bg=C["panel"], fg=C["danger"]).pack(side="left")
            mkbtn(btns, "✓ Mark done", self.mark_done, bg=C["panel"],
                  fg=C["ok"]).pack(side="left", padx=(6, 0))

        self.bind("<Escape>", lambda e: self.destroy())
        self.e_title.bind("<Return>", lambda e: self.save())
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

        data = {
            "title": title, "date": d.isoformat(), "time": t,
            "advance": {lbl: n for n, lbl in ADVANCE}[self.v_adv.get()],
            "repeat": {lbl: k for k, lbl in REPEATS}[self.v_rep.get()],
            "notes": self.t_notes.get("1.0", "end").strip(),
        }
        store = self.app.store
        r = self.r
        if r is None:
            r = {"id": uuid.uuid4().hex[:12], "created": datetime.now().isoformat(timespec="seconds")}
            store.reminders.append(r)
            timing_changed = True
        else:
            timing_changed = any(r.get(k) != data[k] for k in ("date", "time", "advance", "repeat"))
        r.update(data)
        if timing_changed:
            r.update(anchor=data["date"], done=False, snooze_until=None,
                     fired_main=False, fired_advance=False)
            self.app.shown.discard(r["id"])
            # Don't pop up instantly for something you just entered that is already due.
            now, due = datetime.now(), store.due(r)
            if due <= now:
                r["fired_main"] = r["fired_advance"] = True
                self.app.shown.add(r["id"])
            elif data["advance"] and now >= due - timedelta(days=data["advance"]):
                r["fired_advance"] = True
            self.app.close_toast(r["id"])
        store.save()
        self.app.view_month(d.year, d.month)
        self.destroy()

    def delete(self):
        if messagebox.askyesno("Delete reminder", f"Delete \"{self.r['title']}\"?", parent=self):
            self.app.close_toast(self.r["id"])
            self.app.store.delete(self.r["id"])
            self.app.render()
            self.destroy()

    def mark_done(self):
        self.app.close_toast(self.r["id"])
        self.app.store.complete(self.r["id"])
        self.app.render()
        self.destroy()


class DayDialog(tk.Toplevel):
    def __init__(self, app, d, items):
        super().__init__(app.root)
        self.title(fmt_date(d))
        self.configure(bg=C["bg"], padx=16, pady=14)
        self.attributes("-topmost", True)
        self.resizable(False, False)
        tk.Label(self, text=fmt_date(d), bg=C["bg"], fg=C["fg"],
                 font=(F, 12, "bold")).pack(anchor="w", pady=(0, 8))
        for r in sorted(items, key=lambda x: x.get("time") or "99"):
            row = tk.Frame(self, bg=C["panel"], cursor="hand2", padx=10, pady=6)
            row.pack(fill="x", pady=2)
            when = fmt_time(r.get("time")) or "All day"
            a = tk.Label(row, text=when, width=9, anchor="w", bg=C["panel"], fg=C["dim"], font=(F, 9))
            b = tk.Label(row, text=r["title"], anchor="w", bg=C["panel"], fg=C["fg"], font=(F, 10))
            a.pack(side="left")
            b.pack(side="left", fill="x", expand=True)
            for w in (row, a, b):
                w.bind("<Button-1>", lambda e, rr=r: (self.destroy(), app.edit(rr)))
        mkbtn(self, "+ Add reminder on this day", lambda: (self.destroy(), app.edit(None, d)),
              bg=C["accent"], fg="white").pack(anchor="w", pady=(10, 0))
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        self.geometry(f"+{app.root.winfo_rootx()}+{app.root.winfo_rooty() + 40}")
        self.focus_force()


# ---------------------------------------------------------------- main widget

class App:
    def __init__(self, root):
        self.root = root
        self.store = Store()
        self.s = root.winfo_fpixels("1i") / 96.0
        self.toasts = {}
        self.shown = set()          # reminders already popped up this session
        self.dialog = None
        self._drag = None
        today = date.today()
        self.vy, self.vm = today.year, today.month
        self.last_day = today
        self.last_render_min = -1

        root.title(APP)
        root.report_callback_exception = lambda *a: log_error("".join(traceback.format_exception(*a)))
        self._style()
        root.overrideredirect(True)
        root.configure(bg=C["border"])
        root.attributes("-topmost", self.store.settings["topmost"])
        root.attributes("-alpha", self.store.settings["alpha"])
        self.frame = tk.Frame(root, bg=C["bg"])
        self.frame.pack(fill="both", expand=True, padx=1, pady=1)
        self.menu = self._build_menu()
        self.render()
        self._place()
        root.after(1500, self.tick)

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
        self.root.option_add("*TCombobox*Listbox.background", C["panel"])
        self.root.option_add("*TCombobox*Listbox.foreground", C["fg"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", C["accent"])
        self.root.option_add("*TCombobox*Listbox.font", (F, 10))

    def _build_menu(self):
        st = self.store.settings
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="Add reminder…", command=lambda: self.edit(None, date.today()))
        m.add_command(label="Go to today", command=self.goto_today)
        m.add_separator()
        self.v_top = tk.BooleanVar(value=st["topmost"])
        m.add_checkbutton(label="Always on top", variable=self.v_top, command=self.toggle_top)
        self.v_start = tk.BooleanVar(value=os.path.exists(STARTUP_LNK))
        m.add_checkbutton(label="Start with Windows", variable=self.v_start,
                          command=self.toggle_startup)
        self.v_alpha = tk.DoubleVar(value=st["alpha"])
        op = tk.Menu(m, tearoff=0)
        for a in (1.0, 0.96, 0.85, 0.7):
            op.add_radiobutton(label=f"{int(a * 100)}%", variable=self.v_alpha, value=a,
                               command=self.set_alpha)
        m.add_cascade(label="Opacity", menu=op)
        self.v_allday = tk.StringVar(value=st["allday_time"])
        ad = tk.Menu(m, tearoff=0)
        for t in ("07:00", "08:00", "09:00", "10:00", "12:00"):
            ad.add_radiobutton(label=fmt_time(t), variable=self.v_allday, value=t,
                               command=self.set_allday)
        m.add_cascade(label="All-day reminders pop up at", menu=ad)
        self.v_week = tk.IntVar(value=st["week_start"])
        wk = tk.Menu(m, tearoff=0)
        wk.add_radiobutton(label="Monday", variable=self.v_week, value=0, command=self.set_week)
        wk.add_radiobutton(label="Sunday", variable=self.v_week, value=6, command=self.set_week)
        m.add_cascade(label="Week starts on", menu=wk)
        m.add_separator()
        m.add_command(label="Open data folder", command=lambda: os.startfile(DATA_DIR))
        m.add_command(label="Quit", command=self.quit)
        return m

    def _place(self):
        self.root.update_idletasks()
        st = self.store.settings
        w, h = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        if st["x"] is None:
            l, t, r, b = work_area(self.root)
            x, y = r - w - int(24 * self.s), t + int(24 * self.s)
        else:
            vl, vt, vr, vb = virtual_screen(self.root)
            x = max(vl, min(st["x"], vr - 80))
            y = max(vt, min(st["y"], vb - 40))
        self.root.geometry(f"+{x}+{y}")

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

    def _bind_menu(self, w):
        w.bind("<Button-3>", lambda e: self.menu.tk_popup(e.x_root, e.y_root))
        for c in w.winfo_children():
            self._bind_menu(c)

    # ---- rendering
    def render(self):
        Tip.close()
        for w in self.frame.winfo_children():
            w.destroy()
        if self.store.settings["collapsed"]:
            self._render_collapsed()
        else:
            self._render_full()
        self._bind_menu(self.frame)
        self.last_render_min = datetime.now().minute

    def _upcoming(self):
        return sorted(self.store.pending(), key=self.store.effective)

    def _render_collapsed(self):
        today = date.today()
        row = tk.Frame(self.frame, bg=C["bg"], padx=10, pady=6, cursor="fleur")
        row.pack()
        up = self._upcoming()
        icon = tk.Label(row, text="◷", bg=C["bg"], fg=C["accent"], font=(F, 11))
        txt = tk.Label(row, text=f"{today:%a} {today.day} {today:%b}", bg=C["bg"],
                       fg=C["fg"], font=(F, 10, "bold"))
        if up:
            r = up[0]
            n = (self.store.effective(r).date() - today).days
            more = f"  ·  {r['title'][:22]} {('overdue' if n < 0 else rel_days(n))}"
        else:
            more = "  ·  nothing due"
        sub = tk.Label(row, text=more, bg=C["bg"], fg=C["dim"], font=(F, 9))
        for w in (icon, txt, sub):
            w.pack(side="left")
        for w in (row, icon, txt, sub):
            self.make_drag(w, on_click=self.toggle_collapse)

    def _render_full(self):
        today = date.today()
        now = datetime.now()
        hdr = tk.Frame(self.frame, bg=C["bg"], padx=8, pady=6)
        hdr.pack(fill="x")
        hb = dict(bg=C["bg"], font=(F, 11), padx=6, pady=0)
        mkbtn(hdr, "‹", lambda: self.shift(-1), **hb).pack(side="left")
        title = tk.Label(hdr, text=f"{calendar.month_name[self.vm]} {self.vy}", bg=C["bg"],
                         fg=C["fg"], font=(F, 11, "bold"), cursor="fleur")
        title.pack(side="left")
        mkbtn(hdr, "›", lambda: self.shift(1), **hb).pack(side="left")
        mkbtn(hdr, "–", self.toggle_collapse, **hb).pack(side="right")
        mkbtn(hdr, "⋯", lambda: self.menu.tk_popup(self.root.winfo_pointerx(),
                                                        self.root.winfo_pointery()), **hb).pack(side="right")
        mkbtn(hdr, "+", lambda: self.edit(None, today if (self.vy, self.vm) == (today.year, today.month)
                                          else date(self.vy, self.vm, 1)), **hb).pack(side="right")
        self.make_drag(hdr)
        self.make_drag(title, on_click=self.goto_today)

        grid = tk.Frame(self.frame, bg=C["bg"], padx=8)
        grid.pack()
        ws = self.store.settings["week_start"]
        names = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
        for i in range(7):
            tk.Label(grid, text=names[(ws + i) % 7], bg=C["bg"], fg=C["faint"],
                     font=(F, 8), width=4).grid(row=0, column=i, pady=(0, 2))

        pending = self.store.pending()
        cal = calendar.Calendar(ws)
        for wi, week in enumerate(cal.monthdayscalendar(self.vy, self.vm), start=1):
            for di, day in enumerate(week):
                if not day:
                    tk.Label(grid, text="", bg=C["bg"], width=4).grid(row=wi, column=di)
                    continue
                d = date(self.vy, self.vm, day)
                evs = [r for r in pending if occurs_on(r, d)]
                bg, fg, font = C["bg"], C["fg"], (F, 9)
                if d < today:
                    fg = C["faint"]
                if evs:
                    bg, fg, font = C["event"], "#ffffff", (F, 9, "bold")
                if d == today:
                    bg, fg, font = C["accent"], "#ffffff", (F, 9, "bold")
                cell = tk.Label(grid, text=str(day), bg=bg, fg=fg, font=font, width=4,
                                pady=3, cursor="hand2")
                cell.grid(row=wi, column=di, padx=1, pady=1)
                cell.bind("<Button-1>", lambda e, dd=d: self.open_day(dd))
                if bg == C["bg"]:
                    cell.bind("<Enter>", lambda e, c=cell: c.config(bg=C["panel"]))
                    cell.bind("<Leave>", lambda e, c=cell: c.config(bg=C["bg"]))
                if evs:
                    Tip(cell, "\n".join(f"{fmt_time(r.get('time')) or 'All day'}  ·  {r['title']}"
                                        for r in evs))

        tk.Frame(self.frame, bg=C["border"], height=1).pack(fill="x", padx=10, pady=(8, 6))
        box = tk.Frame(self.frame, bg=C["bg"], padx=12)
        box.pack(fill="x", pady=(0, 10))
        tk.Label(box, text="UPCOMING", bg=C["bg"], fg=C["faint"],
                 font=(F, 8, "bold")).pack(anchor="w", pady=(0, 3))
        up = self._upcoming()[:6]
        if not up:
            tk.Label(box, text="Nothing yet. Click a date to add a reminder.",
                     bg=C["bg"], fg=C["dim"], font=(F, 9)).pack(anchor="w")
        for r in up:
            eff = self.store.effective(r)
            n = (eff.date() - today).days
            overdue = n < 0 or (r.get("time") and eff < now) or r.get("snooze_until") is None and r.get("fired_main")
            if overdue:
                color, right = C["danger"], "overdue"
            elif r.get("snooze_until"):
                color, right = C["warn"], f"snoozed · {eff:%H:%M}" if n == 0 else f"snoozed · {rel_days(n)}"
            elif n == 0:
                color, right = C["ok"], fmt_time(r.get("time")) or "today"
            else:
                color = C["accent"]
                right = rel_days(n) if n < 7 else f"{eff.day} {eff:%b}"
            row = tk.Frame(box, bg=C["bg"], cursor="hand2")
            row.pack(fill="x", pady=1)
            title = r["title"] if len(r["title"]) <= 24 else r["title"][:23] + "…"
            if r.get("repeat", "none") != "none":
                title += "  ↻"
            ws_ = [tk.Label(row, text="●", bg=C["bg"], fg=color, font=(F, 8)),
                   tk.Label(row, text=title, bg=C["bg"], fg=C["fg"], font=(F, 9), anchor="w"),
                   tk.Label(row, text=right, bg=C["bg"], fg=color, font=(F, 8))]
            ws_[0].pack(side="left", padx=(0, 6))
            ws_[2].pack(side="right")
            ws_[1].pack(side="left", fill="x", expand=True)
            for w in [row] + ws_:
                w.bind("<Button-1>", lambda e, rr=r: self.edit(rr))

    # ---- actions
    def shift(self, n):
        m = self.vm + n
        self.vy, self.vm = self.vy + (m - 1) // 12, (m - 1) % 12 + 1
        self.render()

    def view_month(self, y, m):
        self.vy, self.vm = y, m
        self.render()

    def goto_today(self):
        t = date.today()
        self.view_month(t.year, t.month)

    def toggle_collapse(self):
        self.store.settings["collapsed"] = not self.store.settings["collapsed"]
        self.store.save_settings()
        self.render()

    def show(self):
        if self.store.settings["collapsed"]:
            self.toggle_collapse()
        self.root.deiconify()
        self.root.lift()

    def open_day(self, d):
        items = [r for r in self.store.pending() if occurs_on(r, d)]
        if not items:
            return self.edit(None, d)
        self._open_dialog(lambda: DayDialog(self, d, items))

    def edit(self, r, day=None):
        self._open_dialog(lambda: ReminderDialog(self, r, day))

    def _open_dialog(self, make):
        Tip.close()
        if self.dialog is not None:
            try:
                self.dialog.destroy()
            except tk.TclError:
                pass
        self.dialog = make()

    def toggle_top(self):
        self.store.settings["topmost"] = self.v_top.get()
        self.root.attributes("-topmost", self.v_top.get())
        self.store.save_settings()

    def set_alpha(self):
        self.store.settings["alpha"] = self.v_alpha.get()
        self.root.attributes("-alpha", self.v_alpha.get())
        self.store.save_settings()

    def set_allday(self):
        self.store.settings["allday_time"] = self.v_allday.get()
        self.store.save_settings()
        self.render()

    def set_week(self):
        self.store.settings["week_start"] = self.v_week.get()
        self.store.save_settings()
        self.render()

    def toggle_startup(self):
        try:
            if self.v_start.get():
                exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
                if not os.path.exists(exe):
                    exe = sys.executable
                script = os.path.abspath(__file__)
                q = lambda p: p.replace("'", "''")
                ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{}');"
                      "$s.TargetPath='{}';$s.Arguments='\"{}\"';$s.WorkingDirectory='{}';"
                      "$s.Save()").format(q(STARTUP_LNK), q(exe), q(script), q(os.path.dirname(script)))
                subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                               creationflags=NO_WINDOW, check=True, timeout=30)
            elif os.path.exists(STARTUP_LNK):
                os.remove(STARTUP_LNK)
        except Exception as e:
            log_error(traceback.format_exc())
            messagebox.showerror(APP, f"Couldn't change the startup setting:\n{e}", parent=self.root)
        self.v_start.set(os.path.exists(STARTUP_LNK))

    def quit(self):
        if messagebox.askyesno(APP, "Reminders won't pop up while the calendar is closed.\n\nQuit anyway?",
                               parent=self.root):
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
        w = int(340 * self.s)
        for toast in list(self.toasts.values()):
            toast.update_idletasks()
            h = toast.winfo_reqheight()
            y -= h
            toast.geometry(f"{w}x{h}+{r - w - gap}+{max(t, y)}")
            y -= int(8 * self.s)

    def check_reminders(self):
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
                    self.shown.add(rid)
                    Toast(self, r, "snooze")
                continue
            due = self.store.due(r)
            if now >= due and (not r.get("fired_main") or rid not in self.shown):
                # Fires on time, or on the next launch if the PC was off / it was never acknowledged.
                r["fired_main"] = r["fired_advance"] = True
                changed = True
                self.shown.add(rid)
                Toast(self, r, "missed" if now - due > timedelta(minutes=30) else "due")
            elif (now < due and not r.get("fired_advance") and r.get("advance")
                  and now >= due - timedelta(days=r["advance"])):
                r["fired_advance"] = True
                changed = True
                Toast(self, r, "advance")
        if changed:
            self.store.save()
            self.render()

    def tick(self):
        try:
            self.check_reminders()
            today = date.today()
            if today != self.last_day:
                self.last_day = today
                self.goto_today()
            elif (datetime.now().minute != self.last_render_min and Tip.current is None
                  and self._drag is None):
                self.render()
            if self.store.settings["topmost"]:
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
    app = App(root)

    def poll():
        try:
            conn, _ = lock.accept()
            conn.close()
            app.show()
        except (BlockingIOError, OSError):
            pass
        root.after(700, poll)

    poll()
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log_error(traceback.format_exc())
        raise
