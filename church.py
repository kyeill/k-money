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
import re

import reminders          # for fetch_csv only -- the Sheet plumbing is shared
import ui

KEY = "church"
LABEL = "Church"

TAB = "Church"
REQUIRED = ["title", "date"]
OPTIONAL = ["details", "color"]

# The palette lives in ui.py: Reminders shades today's unticked rows in the
# same orange, and church.py imports reminders.py, so it cannot live here.
COLORS = ui.COLORS


def color_of(text):
    """A stripe colour, or None. A literal #rrggbb passes through."""
    text = (text or "").strip().lower()
    if not text:
        return None
    if re.fullmatch(r"#?[0-9a-f]{6}", text):
        return "#" + text.lstrip("#")
    return COLORS.get(text)


wash = ui.wash


def layout(header):
    """(where, missing, unknown) -- every column here is found BY NAME.

    Nothing on this tab is positional. Details and Color arrived *between* the
    two original columns, which under position would have read the details as
    the date; reordering them again should stay a non-event.
    """
    where, unknown = {}, []
    for i, name in enumerate(header):
        if not name:
            continue
        if name in REQUIRED + OPTIONAL:
            where.setdefault(name, i)
        else:
            unknown.append(name)
    missing = [n for n in REQUIRED if n not in where]
    return where, missing, unknown


def read_events(text, today):
    """([(date, [event, ...])], unreadable, unknown) from today onward.

    Rows with no date, or a date we cannot read, are dropped rather than
    guessed at -- and named by `unreadable`, so a bad cell is visible instead
    of the event simply never appearing.
    """
    rows = list(csv.reader(io.StringIO(text or "")))
    if not rows:
        raise reminders.SheetError("the Church tab is empty")
    header = [h.strip().lower().split()[0] if h.strip() else "" for h in rows[0]]
    where, missing, unknown = layout(header)
    if missing:
        raise reminders.SheetError(
            "no %s column; the headings read %r"
            % (" or ".join(missing), [h for h in header if h]))

    def cell(cells, name):
        i = where.get(name)
        return cells[i] if i is not None and i < len(cells) else ""

    by_day, bad = {}, []
    for line in rows[1:]:
        cells = [c.strip() for c in line]
        title = cell(cells, "title")
        if not title:
            continue
        when = cell(cells, "date")
        day = ui.sheet_date(when)
        if day is None:
            if when:
                bad.append(title)
            continue
        if day < today:
            continue
        # A Details cell that just repeats the Title renders as the same line
        # twice, which reads as a bug rather than as detail.
        details = cell(cells, "details")
        by_day.setdefault(day, []).append({
            "title": title,
            "details": "" if details == title else details,
            "color": color_of(cell(cells, "color")),
        })

    days = [(day, sorted(by_day[day], key=lambda e: e["title"]))
            for day in sorted(by_day)]
    return days, bad, unknown


# The two-line row is the Watchlist's, on purpose -- title above, quieter
# detail below -- so the app reads as one app rather than three. The colour is
# Sports Daily's: a stripe down the leading edge, and the whole bubble washed
# in the same colour so the row reads as orange or blue from across the room
# rather than only at the margin.
CSS = """
.cday{margin:18px 0 0}
.cday h2{font-size:12px;text-transform:uppercase;letter-spacing:.08em;
         color:var(--muted);font-weight:600;margin:0 0 7px}
.cev{background:var(--card);border:1px solid var(--line);border-radius:10px;
     border-left:4px solid transparent;padding:10px 12px;margin:6px 0}
/* Two layers, not one: the wash is translucent, so without the card colour
   underneath it the page background would show through and a tinted row would
   sit DARKER than an untinted one. */
.cev.tint{border-left-color:var(--tint);
          background:linear-gradient(var(--wash),var(--wash)),var(--card)}
.cev .t{display:block;font-weight:600;font-size:15px;line-height:1.25}
/* Wraps, unlike the Watchlist's one-line subtitle: no date column is squeezing
   this row, and a note is worth reading in full. */
.cev .s{display:block;color:var(--muted);font-size:13px;margin-top:2px}
.cnone{color:var(--muted);font-size:13px;padding:2px 2px 4px}
@media (min-width:641px){
  .cday{margin:24px 0 0}
  .cday h2{font-size:13px}
  .cev{padding:12px 15px;margin:8px 0}
  .cev .t{font-size:17px}
  .cev .s{font-size:14px}
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
    if data.get("unknown"):
        out.append('<div class="rerr">Column not recognised: %s</div>'
                   % ui.esc(", ".join(data["unknown"])))
    if not data["days"]:
        return "".join(out) + '<div class="cnone">Nothing coming up.</div>'
    for day, events in data["days"]:
        out.append('<div class="cday"><h2>%s</h2>'
                   % ui.esc(ui.day_heading(day, data["today"])))
        for ev in events:
            tint = ev.get("color")
            out.append('<div class="cev%s"%s><span class="t">%s</span>%s</div>' % (
                " tint" if tint else "",
                ' style="%s"' % ui.esc(ui.shade(tint)) if tint else "",
                ui.esc(ev["title"]),
                '<span class="s">%s</span>' % ui.esc(ev["details"])
                if ev["details"] else "",
            ))
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
    blank = {"today": today, "days": [], "unreadable": [], "unknown": []}
    if not sheet:
        return dict(blank, error="no reminders_sheet in config.json")
    try:
        text = fetch(sheet, tab)
        days, bad, unknown = read_events(text, today)
    except Exception as exc:      # a bad tab must not take the whole page down
        return dict(blank, error="%s" % exc)
    return {"today": today, "days": days, "unreadable": bad,
            "unknown": unknown, "error": None}


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
    for day, events in data["days"]:
        print("%s" % ui.day_heading(day, data["today"]))
        for ev in events:
            print("    %-26s %-32s %s"
                  % (ev["title"], ev["details"], ev["color"] or ""))
    print("\n%d day(s) with something on" % len(data["days"]))
