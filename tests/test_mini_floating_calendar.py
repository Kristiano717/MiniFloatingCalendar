"""Tests for Mini Floating Calendar.  Run:  python -m unittest discover -s tests -v"""

import importlib.machinery
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta

os.environ["FLOATCAL_DATA"] = tempfile.mkdtemp(prefix="mfc-test-")
_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mini_floating_calendar.pyw")
_loader = importlib.machinery.SourceFileLoader("mfc", _PATH)
mfc = importlib.util.module_from_spec(importlib.util.spec_from_loader("mfc", _loader))
sys.modules["mfc"] = mfc
_loader.exec_module(mfc)

NOW = datetime(2026, 11, 19, 12, 0)   # a Thursday


class QuickAddParserTests(unittest.TestCase):
    CASES = [
        ("apply for scholarship dec 1 5pm #college", dict(title="Apply for scholarship", date="2026-12-01", time="17:00", category="College")),
        ("pay rent 1st every month #bills", dict(title="Pay rent", date="2026-12-01", repeat="monthly", category="Bills")),
        ("call mom tomorrow 7pm", dict(title="Call mom", date="2026-11-20", time="19:00")),
        ("exam in 3 days remind 1 day before", dict(title="Exam", date="2026-11-22", advance=1)),
        ("gym every monday 6am", dict(title="Gym", date="2026-11-23", time="06:00", repeat="weekly")),
        ("submit form on 5/12", dict(title="Submit form", date="2026-12-05")),
        ("meeting at 14:30", dict(title="Meeting", date="2026-11-19", time="14:30")),
        ("standup at 9am", dict(title="Standup", date="2026-11-20", time="09:00")),
        ("dentist friday at 4", dict(title="Dentist", date="2026-11-20", time="16:00")),
        ("dentist next friday", dict(title="Dentist", date="2026-11-27")),
        ("call next monday", dict(title="Call", date="2026-11-23")),
        ("pick up parcel on sat", dict(title="Pick up parcel", date="2026-11-21")),
        ("SAT exam registration dec 3", dict(title="SAT exam registration", date="2026-12-03")),
        ("birthday party 25 dec yearly", dict(title="Birthday party", date="2026-12-25", repeat="yearly")),
        ("drink water in 30 minutes", dict(title="Drink water", date="2026-11-19", time="12:30")),
        ("remind me to renew passport on 3 jan 2027 a week before", dict(title="Renew passport", date="2027-01-03", advance=7)),
        ("pay electricity bill by nov 10", dict(title="Pay electricity bill", date="2027-11-10")),
        ("water plants every sunday", dict(title="Water plants", date="2026-11-22", repeat="weekly")),
        ("call bank tomorrow morning", dict(title="Call bank", date="2026-11-20", time="09:00")),
        ("fill visa form dec 2 ! https://example.com/visa", dict(title="Fill visa form", important=True, link="https://example.com/visa")),
        ("renew licence urgent www.example.org/licence", dict(title="Renew licence", important=True, link="https://www.example.org/licence")),
    ]

    def test_cases(self):
        for text, expected in self.CASES:
            with self.subTest(text=text):
                got = mfc.parse_quick(text, NOW)
                for k, v in expected.items():
                    self.assertEqual(got[k], v, f"{k} for {text!r}: {got}")

    def test_needs_a_title(self):
        with self.assertRaises(ValueError):
            mfc.parse_quick("tomorrow 5pm", NOW)


class DateHelperTests(unittest.TestCase):
    def test_parse_time(self):
        self.assertEqual(mfc.parse_time("5:30 pm"), "17:30")
        self.assertEqual(mfc.parse_time("12am"), "00:00")
        self.assertEqual(mfc.parse_time(""), "")
        for bad in ("25:00", "13pm", "abc"):
            with self.assertRaises(ValueError):
                mfc.parse_time(bad)

    def test_parse_date(self):
        for s in ("1 Dec 2026", "01/12/2026", "2026-12-01"):
            self.assertEqual(mfc.parse_date(s), date(2026, 12, 1))

    def test_monthly_repeat_keeps_end_of_month(self):
        r = {"date": "2026-01-31", "anchor": "2026-01-31", "repeat": "monthly"}
        self.assertEqual(mfc.next_occurrence(r, date(2026, 1, 31)), date(2026, 2, 28))
        self.assertEqual(mfc.next_occurrence(r, date(2026, 2, 28)), date(2026, 3, 31))

    def test_occurs_on(self):
        self.assertTrue(mfc.occurs_on({"date": "2026-11-19", "repeat": "weekly"}, date(2026, 12, 3)))
        self.assertFalse(mfc.occurs_on({"date": "2026-11-19", "repeat": "weekly"}, date(2026, 12, 4)))

    def test_progress(self):
        self.assertEqual(mfc.progress({"checklist": [{"text": "a", "done": True}, {"text": "b"}]}), "1/2")
        self.assertEqual(mfc.progress({}), "")


class IcsTests(unittest.TestCase):
    def test_round_trip(self):
        future = (date.today() + timedelta(days=5)).isoformat()
        rems = [{"id": "a1", "title": "Visa, form; part 2", "date": future, "time": "17:30", "repeat": "none",
                 "advance": 2, "notes": "bring passport", "category": "Work", "link": "https://example.com",
                 "checklist": [{"text": "photo", "done": False}]},
                {"id": "b2", "title": "Rent", "date": future, "time": "", "repeat": "monthly", "advance": 0,
                 "notes": "", "category": "Bills"}]
        path = os.path.join(tempfile.mkdtemp(), "x.ics")
        mfc.export_ics(rems, path)
        back = {r["title"]: r for r in mfc.read_ics(path)}
        self.assertEqual(set(back), {"Visa, form; part 2", "Rent"})
        v = back["Visa, form; part 2"]
        self.assertEqual((v["time"], v["advance"], v["category"], v["link"]), ("17:30", 2, "Work", "https://example.com"))
        self.assertIn("photo", v["notes"])
        self.assertEqual(back["Rent"]["repeat"], "monthly")


try:
    import tkinter as tk
    _r = tk.Tk()
    _r.destroy()
    HAVE_TK = True
except Exception:
    HAVE_TK = False


@unittest.skipUnless(HAVE_TK, "needs a display for Tk")
class AppTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="mfc-app-")
        mfc.DATA_DIR = self.dir
        mfc.SET_FILE = os.path.join(self.dir, "settings.json")
        mfc.LOG_FILE = os.path.join(self.dir, "error.log")
        mfc.ANIM["on"] = False          # instant open/close so tests are deterministic
        self.root = tk.Tk()
        self.app = mfc.App(self.root, None, background=False)
        st = self.app.store.settings
        st.update(hold_fullscreen=False, auto_theme="off", sound=False)

    def tearDown(self):
        # (Tk may print "invalid command name ..." for timers of closed windows; that's harmless.)
        self.root.destroy()
        shutil.rmtree(self.dir, ignore_errors=True)

    def pump(self, ms=0):
        if ms:
            self.root.after(ms, self.root.quit)
            self.root.mainloop()
        self.root.update()

    def wait_until(self, cond, timeout=5.0):
        """Let animations run until cond() is true (slow CI machines need longer)."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.pump(50)
            try:
                if cond():
                    return True
            except tk.TclError:
                pass
        return False

    def add(self, rid, **kw):
        now = datetime.now()
        r = {"id": rid, "title": rid, "date": now.date().isoformat(), "time": "", "advance": 0,
             "repeat": "none", "notes": "", "category": "Work", "done": False, "fired_main": False,
             "fired_advance": False, "snooze_until": None}
        r.update(kw)
        r.setdefault("anchor", r["date"])
        self.app.store.reminders.append(r)
        return r

    def test_reminders_fire_blink_and_complete(self):
        now = datetime.now()
        self.add("due", time=(now - timedelta(minutes=1)).strftime("%H:%M"), important=True,
                 checklist=[{"text": "scan ID", "done": False}], link="https://example.com")
        self.add("missed", date=(now - timedelta(days=2)).date().isoformat(), time="10:00")
        self.add("soon", date=(now + timedelta(days=1)).date().isoformat(), time="23:59", advance=2)
        self.add("daily", time=(now - timedelta(minutes=2)).strftime("%H:%M"), repeat="daily")
        self.app.check_reminders()
        self.assertEqual({k: t.kind for k, t in self.app.toasts.items()},
                         {"due": "due", "missed": "missed", "soon": "advance", "daily": "due"})
        self.pump(700)
        self.assertTrue(self.app._alerting)
        self.assertEqual(self.app._cur_alpha, 1.0, "widget turns solid while a reminder waits")
        # checklist inside the pop-up
        self.app.toasts["due"]._toggle(0)
        self.assertTrue(self.app.store.get("due")["checklist"][0]["done"])
        # ignored pop-ups shake again
        for t in self.app.toasts.values():
            t.last_nag -= mfc.NAG_SECONDS + 1
        self.app.blink()
        self.assertTrue(all(time.monotonic() - t.last_nag < 5 for t in self.app.toasts.values()))
        # done (with undo), repeat moves forward, snooze
        self.app.toasts["due"].done()
        self.assertTrue(self.app.store.get("due")["done"])
        self.app.undo()
        self.assertFalse(self.app.store.get("due")["done"])
        self.app.toasts["daily"].done()
        self.assertEqual(self.app.store.get("daily")["date"], (now.date() + timedelta(days=1)).isoformat())
        self.app.toasts["missed"].snooze(timedelta(minutes=10))
        self.assertTrue(self.app.store.get("missed")["snooze_until"])
        self.app.toasts["soon"].close()
        self.app.check_reminders()
        self.assertNotIn("missed", self.app.toasts)

    def test_quick_add_and_views(self):
        self.app.quick_add()
        self.app.qa.v.set("fill visa form next friday ! www.example.com/visa #work")
        self.app.qa.add()
        r = next(r for r in self.app.store.reminders if r["title"] == "Fill visa form")
        self.assertTrue(r["important"])
        self.assertEqual(r["link"], "https://www.example.com/visa")
        self.app.open_big()
        for mode in ("month", "agenda", "list"):
            self.app.big.set_mode(mode)
            self.pump()
        self.assertIn(r["id"], self.app.big.tree.get_children())
        self.app.big.tree.selection_set(r["id"])
        self.app.big._delete()
        self.assertIsNone(self.app.store.get(r["id"]))
        self.app.undo()
        self.assertIsNotNone(self.app.store.get(r["id"]))

    def test_themes_sizes_and_schedule(self):
        self.app.open_big()
        for name in mfc.THEMES:
            self.app.apply_theme(name)
            self.pump()
        for size in (0.85, 1.4, 1.0):
            self.app.set_size(size)
            self.pump()
        st = self.app.store.settings
        st.update(auto_theme="schedule", light_start="07:00", dark_start="19:00",
                  light_theme="Vintage Almanac", dark_theme="Midnight Noir")
        self.assertEqual(self.app.wanted_theme(datetime(2026, 1, 1, 8)), "Vintage Almanac")
        self.assertEqual(self.app.wanted_theme(datetime(2026, 1, 1, 22)), "Midnight Noir")

    def _at(self, key):
        """Canvas coordinates of the middle of an area on the widget, e.g. ("day", 15) or "grip"."""
        z = self.app.zone(key)
        self.assertIsNotNone(z, key)
        x0, y0, x1, y1 = z["bbox"]
        return (x0 + x1) / 2, (y0 + y1) / 2

    def test_drag_resize_grip(self):
        from types import SimpleNamespace as E
        app, cv = self.app, self.app.cv
        self.pump()
        day = app.zone(("day", 15))
        self.assertIn(cv.gettags(day["item"])[0], app.live_fonts.tags.values())   # styled by font tag
        items = cv.find_all()
        w0, s0, cw0 = self.root.winfo_width(), mfc.UI["scale"], day["bbox"][2] - day["bbox"][0]
        tw0 = cv.bbox(day["item"])[2] - cv.bbox(day["item"])[0]     # drawn width of the "15"
        gx, gy = self._at("grip")
        app._cv_press(E(x=gx, y=gy, x_root=500, y_root=500))      # grab the corner grip
        self.assertIsNotNone(app._resize)
        for step in range(1, 6):             # drag it out diagonally
            app._cv_drag(E(x=gx, y=gy, x_root=500 + 20 * step, y_root=500 + 20 * step))
            self.pump()
        self.assertGreater(mfc.UI["scale"], s0)
        self.assertEqual(cv.find_all(), items)              # resized in place, nothing redrawn
        day = app.zone(("day", 15))
        self.assertGreater(day["bbox"][2] - day["bbox"][0], cw0)
        self.assertGreater(cv.bbox(day["item"])[2] - cv.bbox(day["item"])[0], tw0)   # text drawn bigger
        self.assertEqual(app.store.settings["size"], s0)    # not saved until the grip is let go
        app.changed()                                       # a redraw asked for mid-drag waits
        self.assertTrue(app._render_pending)
        self.assertEqual(cv.find_all(), items)
        app._cv_release(E(x=gx, y=gy, x_root=600, y_root=600))
        self.pump()
        self.assertIsNone(app._resize)
        self.assertFalse(app._render_pending)
        self.assertGreater(self.root.winfo_width(), w0)
        self.assertEqual(app.store.settings["size"], round(mfc.UI["scale"], 3))
        # shrink below the minimum clamps
        app._grip_press(E(x_root=500, y_root=500))
        app._grip_motion(E(x_root=-3000, y_root=-3000))
        app._grip_release()
        self.assertEqual(mfc.UI["scale"], app.SIZE_MIN)
        # Ctrl+scroll: one notch grows 5 %, a touchpad's small delta grows a little
        app._wheel_resize(E(delta=120))
        self.assertAlmostEqual(mfc.UI["scale"], app.SIZE_MIN + 0.05, places=3)
        app._wheel_resize(E(delta=24))
        self.assertAlmostEqual(mfc.UI["scale"], app.SIZE_MIN + 0.06, places=3)
        # collapsed mode has no grip
        app.toggle_collapse()
        self.pump()
        self.assertIsNone(app.zone("grip"))
        app.set_size(1.0)

    def test_resize_glides_smoothly(self):
        mfc.ANIM["on"] = True
        self.addCleanup(mfc.ANIM.__setitem__, "on", False)
        app = self.app
        self.pump()
        items = app.cv.find_all()
        frames = []
        real = app.apply_scale
        app.apply_scale = lambda v: (frames.append(v), real(v))
        app.set_size(1.5)                    # Size menu preset
        self.wait_until(lambda: app.store.settings["size"] == 1.5)
        self.assertGreater(len(frames), 4)            # several in-between frames, not one jump
        self.assertEqual(frames, sorted(frames))      # grows steadily, no overshoot or wobble
        self.assertAlmostEqual(mfc.UI["scale"], 1.5)
        self.assertEqual(app.cv.find_all(), items)    # same canvas items, just moved and resized
        light = app.zone(("light", 0))
        self.assertGreaterEqual(light["bbox"][2] - light["bbox"][0], app.light_px())

    def test_canvas_clicks_hover_and_drag(self):
        from types import SimpleNamespace as E
        app = self.app
        self.pump()
        opened = []
        app.open_day = lambda d: opened.append(d)

        def click(key):
            x, y = self._at(key)
            app._cv_press(E(x=x, y=y, x_root=400, y_root=400))
            app._cv_release(E(x=x, y=y, x_root=400, y_root=400))
        click(("day", 15))
        self.assertEqual([d.day for d in opened], [15])
        month = (app.vy, app.vm)
        click("next")
        self.assertNotEqual((app.vy, app.vm), month)
        click("title")                       # back to this month
        self.assertEqual((app.vy, app.vm), (date.today().year, date.today().month))
        # hover: a plain day lights up and goes back; the traffic lights show symbols together
        plain = 16 if date.today().day == 15 else 15
        x, y = self._at(("day", plain))
        hover = app._v["hover_cell"]
        app._cv_motion(E(x=x, y=y))
        self.assertEqual(app.cv.itemcget(hover, "state"), "normal")
        hx0, hy0, hx1, hy1 = app.cv.coords(hover)
        self.assertTrue(hx0 < x < hx1 and hy0 < y < hy1)       # the highlight sits on that day
        app._cv_motion(E(x=1, y=1))          # empty corner
        self.assertEqual(app.cv.itemcget(hover, "state"), "hidden")
        app._cv_motion(E(x=self._at(("light", 2))[0], y=self._at(("light", 2))[1]))
        self.assertTrue(app._lights_hover)
        app._set_hover(None)
        self.assertFalse(app._lights_hover)
        # dragging from anywhere moves the widget instead of clicking
        self.pump()
        x0, y0 = self.root.winfo_x(), self.root.winfo_y()
        app._cv_press(E(x=x, y=y, x_root=400, y_root=400))
        app._cv_drag(E(x=x, y=y, x_root=430, y_root=420))
        app._cv_release(E(x=x, y=y, x_root=430, y_root=420))
        self.pump()
        self.assertEqual((self.root.winfo_x(), self.root.winfo_y()), (x0 + 30, y0 + 20))
        self.assertEqual(app.store.settings["x"], x0 + 30)
        self.assertEqual(len(opened), 1)     # still just the first click
        # yellow light collapses; clicking the collapsed bar expands it again
        click(("light", 1))
        self.assertTrue(app.store.settings["collapsed"])
        click("collapsed")
        self.assertFalse(app.store.settings["collapsed"])

    def test_reminder_dialog_checklist_link(self):
        self.app.edit(None, date.today() + timedelta(days=3))
        d = self.app.dialog
        d.v_title.set("Scholarship")
        d.v_link.set("example.com/apply")
        d.v_imp.set(True)
        d.v_item.set("Transcript")
        d._add_item()
        d.v_item.set("SOP")   # typed but not added: still saved
        d.save()
        r = next(r for r in self.app.store.reminders if r["title"] == "Scholarship")
        self.assertEqual([i["text"] for i in r["checklist"]], ["Transcript", "SOP"])
        self.assertEqual(r["link"], "https://example.com/apply")
        self.assertTrue(r["important"])

    def test_animations_open_and_close(self):
        mfc.ANIM["on"] = True
        try:
            self.app.quick_add()
            qa = self.app.qa
            self.assertTrue(self.wait_until(lambda: float(qa.attributes("-alpha")) > 0.99), "quick add fades in")
            qa.destroy()                       # fades out, then really closes
            self.assertTrue(qa.winfo_exists())
            self.assertTrue(self.wait_until(lambda: not qa.winfo_exists()), "quick add closes")
            # pop-up glides in from the right and ends in its slot
            self.add("now", time=(datetime.now() - timedelta(minutes=1)).strftime("%H:%M"))
            self.app.check_reminders()
            card = self.app.toasts["now"]
            l, t, r, b = mfc.work_area(self.root)
            right = r - int(12 * self.app.s)
            self.assertTrue(self.wait_until(
                lambda: abs(card.winfo_x() + card.winfo_width() - right) < 4
                and getattr(card, "_anim_token", None) is not None and float(card.attributes("-alpha")) > 0.99),
                "card slides into place")
            card.close()
            self.assertTrue(self.wait_until(lambda: not card.winfo_exists()), "card slides away")
            # hide to tray / show again (tray isn't running in tests, so pretend)
            self.app.tray = object()
            self.app.store.settings["tray_hint_shown"] = True
            self.app.hide_widget()
            self.assertTrue(self.wait_until(lambda: self.root.state() == "withdrawn"), "widget hides")
            self.app.show()
            self.assertTrue(self.wait_until(lambda: self.root.state() == "normal" and not self.app._animating),
                            "widget shows")
            self.app.tray = None
        finally:
            mfc.ANIM["on"] = False

    def test_glass_theme_and_click_forwarding(self):
        self.app.apply_theme("iOS Light")
        self.pump(200)
        if not self.app.glass:
            self.skipTest("acrylic glass not available on this Windows")
        self.assertEqual(str(self.root.attributes("-transparentcolor")).lower(), mfc.C["bg"])
        self.assertEqual(self.app.catcher.state(), "normal")
        # a click that lands on the glass between letters reaches the day underneath
        opened = []
        self.app.open_day = lambda d: opened.append(d)
        self.app.render()
        self.pump()
        cv, z = self.app.cv, self.app.zone(("day", 15))
        x, y = round(cv.winfo_rootx() + z["bbox"][0] + 2), round(cv.winfo_rooty() + z["bbox"][1] + 2)

        class Ev:   # what the catcher would receive
            def __init__(s, t):
                s.type, s.num, s.x_root, s.y_root = t, 1, x, y
        self.app._forward(Ev("ButtonPress"))
        self.app._forward(Ev("ButtonRelease"))
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0].day, 15)
        self.app.apply_theme("Daylight")
        self.assertFalse(self.app.glass)
        self.assertEqual(self.app.catcher.state(), "withdrawn")

    def test_data_folder_sync_and_backup(self):
        self.add("a")
        self.app.store.save()
        cloud = tempfile.mkdtemp(prefix="mfc-cloud-")
        with open(os.path.join(cloud, "reminders.json"), "w", encoding="utf-8") as fh:
            json.dump([{"id": "from_other_pc", "title": "Other PC", "date": "2030-01-01", "time": ""}], fh)
        self.assertTrue(self.app.move_data(cloud))
        ids = {r["id"] for r in self.app.store.reminders}
        self.assertEqual(ids, {"a", "from_other_pc"})
        self.assertTrue(os.listdir(os.path.join(cloud, "backups")))
        # another PC edits the file -> this one picks it up
        data = self.app.store.reminders + [{"id": "new", "title": "Added elsewhere", "date": "2030-02-02", "time": ""}]
        time.sleep(1.1)
        with open(os.path.join(cloud, "reminders.json"), "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        self.app.tick()
        self.assertIsNotNone(self.app.store.get("new"))
        shutil.rmtree(cloud, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
