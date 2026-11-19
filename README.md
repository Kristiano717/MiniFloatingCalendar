# Mini Floating Calendar

A small calendar for Windows that floats on your desktop and pops up reminders, for example
"apply for X on 1 Dec" or "call the bank at 4:30 pm".

## Features

- **Floating widget**: a compact month view that stays on top. Drag it anywhere and it remembers where you put it.
- **Collapse to a pill**: click `–` to shrink it to one line showing today's date and your next reminder. Click the pill to expand it again.
- **Reminders by date or time**:
  - With a time (e.g. `5:30 pm`), the popup appears at that time.
  - Without a time (all day), it pops up that morning at 9:00 AM. You can change this time in the menu.
- **Early warning**: get a "Coming up" popup 1, 2, 3 or 7 days before.
- **Repeats**: daily, weekly, monthly or yearly (good for birthdays and bills).
- **Popups that wait for you**: a reminder stays on screen with a sound until you click **Done** or **Snooze** (10 min / 1 hr / tomorrow).
- **Nothing gets lost**: if your PC was off when a reminder was due, it shows up as *Missed* the next time the app starts.
- **Start with Windows**: one click in the menu.

## Requirements

- Windows 10 or 11
- [Python 3.9+](https://www.python.org/downloads/) (tkinter comes with it). No other packages are needed.

## Run it

Double-click `mini_floating_calendar.pyw`, or run:

```powershell
pythonw mini_floating_calendar.pyw
```

Then right-click the widget (or click `⋯`) and tick **Start with Windows** so it is always running.

## How to use

| Action | How |
|---|---|
| Add a reminder | Click a date, or click `+` |
| See a day's reminders | Hover over a highlighted date, or click it |
| Edit / delete / mark done | Click the reminder in the **Upcoming** list |
| Change month | `‹` `›`. Click the month name to go back to today |
| Move the widget | Drag the header |
| Settings | Right-click anywhere on the widget, or click `⋯` |

Dates can be typed as `1 Dec 2026`, `01/12/2026`, `2026-12-01` or just `1 dec`.
Times can be typed as `17:30`, `5:30 pm` or `5pm`.

## Where your data lives

`%APPDATA%\MiniFloatingCalendar\reminders.json` (plain JSON, easy to back up).
To open the folder, choose **Open data folder** from the menu.

> Reminders only pop up while the app is running, so turn on **Start with Windows**.
