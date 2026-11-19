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
