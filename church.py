"""The Church tab: dated events from the Church tab of the same Sheet.

Deliberately much simpler than Reminders. There are no cadences here -- every
row carries its own date -- so there is nothing to recompute, nothing to notify
and nothing to keep in step with the Apps Script.

Only dates from today onward are shown, and only days that actually have
something on them: most days do not, and a column of empty headings would bury
the handful that matter.
"""

import csv
import datetime as dt
import io
import os

import reminders          # for fetch_csv only -- the Sheet plumbing is shared
import ui

KEY = "church"
LABEL = "Church"

TAB = "Church"
EXPECT = ["title", "date"]


def read_events(text, today):
    """[(date, [title, ...])] from today onward, soonest first.

    Rows with no date, or a date we cannot read, are dropped rather than
    guessed at -- and reported by `unreadable` so a bad cell is visible instead
    of the event simply never appearing.
    """
    rows = list(csv.reader(io.StringIO(text or "")))
    if not rows:
        raise reminders.SheetError("the Church tab is empty")
    header = [h.strip().lower().split()[0] if h.strip() else "" for h in rows[0]]
    if header[:len(EXPECT)] != EXPECT:
        raise reminders.SheetError(
            "unexpected header %r; expected %r" % (header, EXPECT))

    by_day, bad = {}, []
    for line in rows[1:]:
        cells = [c.strip() for c in line] + ["", ""]
        title, when = cells[0], cells[1]
        if not title:
            continue
        day = ui.sheet_date(when)
        if day is None:
            if when:
                bad.append(title)
            continue
        if day < today:
            continue
        by_day.setdefault(day, []).append(title)

    days = [(day, sorted(by_day[day])) for day in sorted(by_day)]
    return days, bad


CSS = """
.cday{margin:18px 0 0}
.cday h2{font-size:12px;text-transform:uppercase;letter-spacing:.08em;
         color:var(--muted);font-weight:600;margin:0 0 7px}
.cev{background:var(--card);border:1px solid var(--line);border-radius:10px;
     padding:11px 13px;margin:6px 0;font-size:15px}
.cnone{color:var(--muted);font-size:13px;padding:2px 2px 4px}
@media (min-width:641px){
  .cday{margin:24px 0 0}
  .cday h2{font-size:13px}
  .cev{padding:13px 15px;margin:8px 0;font-size:17px}
}
"""


def render(data):
    if data.get("error"):
        return ('<div class="rerr">Could not read the Church tab: %s</div>'
                % ui.esc(data["error"]))
    out = []
    if data.get("unreadable"):
        out.append('<div class="rerr">Could not read the date for: %s</div>'
                   % ui.esc(", ".join(data["unreadable"])))
    if not data["days"]:
        return "".join(out) + '<div class="cnone">Nothing coming up.</div>'
    for day, titles in data["days"]:
        out.append('<div class="cday"><h2>%s</h2>'
                   % ui.esc(ui.day_heading(day, data["today"])))
        for title in titles:
            out.append('<div class="cev">%s</div>' % ui.esc(title))
        out.append("</div>")
    return "".join(out)


def build(today=None, cfg=None, record=True):
    today = dt.date.fromisoformat(today) if isinstance(today, str) else today
    today = today or dt.date.today()
    if cfg is None:
        import watch          # load_config lives there; reminders does the same
        cfg = watch.load_config()
    sheet = (cfg.get("reminders_sheet") or "").strip()
    tab = cfg.get("church_tab", TAB)
    if not sheet:
        return {"today": today, "days": [], "unreadable": [],
                "error": "no reminders_sheet in config.json"}
    try:
        text = fetch(sheet, tab)
        days, bad = read_events(text, today)
    except Exception as exc:      # a bad tab must not take the whole page down
        return {"today": today, "days": [], "unreadable": [], "error": "%s" % exc}
    return {"today": today, "days": days, "unreadable": bad, "error": None}


def fetch(sheet, tab):
    """KMONEY_CHURCH_CSV points at a local file, for tests and --fixtures."""
    local = os.environ.get("KMONEY_CHURCH_CSV")
    if local:
        if not os.path.exists(local):
            return ""
        with open(local, encoding="utf-8") as fh:
            return fh.read()
    import requests
    r = requests.get(reminders.CSV_URL % sheet + "&sheet=" + tab, timeout=20)
    r.raise_for_status()
    return r.text


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    data = build()
    if data["error"]:
        raise SystemExit("error: " + data["error"])
    for day, titles in data["days"]:
        print("%s" % ui.day_heading(day, data["today"]))
        for title in titles:
            print("    %s" % title)
    print("\n%d day(s) with something on" % len(data["days"]))
