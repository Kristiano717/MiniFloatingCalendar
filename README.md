# Mini Floating Calendar

A small calendar for Windows that floats on your desktop and nags you about deadlines,
with a vintage-almanac look and three other themes.

## Features

**Reminders that you won't miss**
- A pop-up card appears in the bottom-right corner with a sound. **It blinks** (the card edge, the widget border and the tray icon) until you click **Done** or **Snooze** (10 min / 1 hr / tomorrow).
- Reminders with a time fire at that time. All-day reminders fire that morning (9:00 AM by default).
- Early warnings: a "Coming up" card 1, 2, 3 or 7 days before.
- If your PC was off when a reminder was due, it shows up as **Missed** the next time the app starts.
- Pop-ups wait while you're in a fullscreen game, video or slideshow.
- **Phone alerts** (optional): every reminder can also be sent to your phone through the free [ntfy](https://ntfy.sh) app.

**Quick add: just type it**

Press **Ctrl+Alt+R** from any app, or click `+`, and type something like:

| You type | You get |
|---|---|
| `apply for scholarship dec 1 5pm #college` | 1 Dec, 5:00 PM, College |
| `pay rent 1st every month #bills` | the 1st of every month, Bills |
| `call mom tomorrow 7pm` | tomorrow, 7:00 PM |
| `exam in 3 days remind 1 day before` | in 3 days, with an early warning the day before |
| `gym every monday 6am` | weekly, Mondays at 6:00 AM |
| `drink water in 30 minutes` | 30 minutes from now |

A live preview shows what it understood before you press Enter.
Categories: `#personal #work #college #bills #health #other`.

**Calendar views**
- **Floating widget**: a month view plus your next reminders with countdowns ("3d left", "tomorrow", "overdue"). Drag it anywhere, or click `–` to shrink it to one line.
- **Big calendar** (`▦` button): a full-size month table with each reminder shown in its day, colour-coded by category.
- **List view**: every reminder in one table. Search it, filter by Upcoming / Done / All, mark as done, restore, or delete.

**Lives in the tray**
- The `×` button hides the widget to the system tray, including the `^` hidden-icons area. Click the tray icon to bring it back, or right-click it for a menu.
- Starts with Windows. It only quits if you choose **Quit**.

**Themes** (right-click → Theme): **Vintage Almanac** (default), **Midnight Noir**, **Retro Terminal**, **Synthwave '84**.

**Other features**
- Repeating reminders: daily, weekly, monthly, yearly.
- Import and export `.ics` files to move reminders to or from Google Calendar and Outlook.
- Auto-updates from this GitHub repo when it runs from a git clone.

## Install

**Option A: run the Python script** (gets auto-updates)
1. Install [Python 3.9+](https://www.python.org/downloads/).
2. Clone this repo, then install the tray-icon packages:
   ```powershell
   git clone https://github.com/Kristiano717/MiniFloatingCalendar.git
   cd MiniFloatingCalendar
   pip install -r requirements.txt
   ```
3. Double-click `mini_floating_calendar.pyw`, then right-click the widget and tick **Start with Windows**.

**Option B: build a single `.exe`** (no Python needed on the PC that runs it)
```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```
This creates `dist\MiniFloatingCalendar.exe`, which you can copy to any Windows PC.

## Phone alerts setup
1. Install **ntfy** on your phone (Play Store or App Store).
2. On the PC, right-click the widget, choose **Phone alerts…**, and copy the topic name shown.
3. In the ntfy app, tap **+** and subscribe to that topic. Click **Send test**, then **Save**.

## Where your data lives
`%APPDATA%\MiniFloatingCalendar\reminders.json` (plain JSON). To open the folder, right-click the widget and choose **Open data folder**.
