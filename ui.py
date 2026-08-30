"""Shared render helpers. Anything a future tab would otherwise reinvent."""

import datetime as dt
import html


def esc(text):
    return html.escape(str(text if text is not None else ""))


def chip(text, cls="chip"):
    return '<span class="%s">%s</span>' % (cls, esc(text))


def day_parts(iso, today=None):
    """('Sep 3', 'Wed') this year, ('Sep 2027', '') in any other.

    A bare 'Sep 3' three years out reads as this September, so the year has to
    appear -- but 'Sep 3 2027' does not fit the date column, and nobody plans
    around which weekday a film in 2028 opens on. Past the turn of the year the
    day of the month is dropped instead of the year.
    """
    if not iso:
        return ("TBA", "")
    day = dt.date.fromisoformat(iso)
    now = dt.date.fromisoformat(today) if today else dt.date.today()
    if day.year != now.year:
        return ("%s %d" % (day.strftime("%b"), day.year), "")
    return ("%s %d" % (day.strftime("%b"), day.day), day.strftime("%A"))


def sheet_date(text):
    """A date out of a Sheets cell.

    Sheets renders dates in the viewer's locale, so the CSV hands back
    "9/8/26" rather than ISO -- the same trap the time column sets. Every
    plausible form is accepted rather than assuming one.
    """
    text = (text or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def day_heading(day, today):
    """Only today is named; everything else carries its date. Shared so the
    tabs cannot drift into two different date formats."""
    if day == today:
        return "Today"
    return day.strftime("%A, %b ") + str(day.day)


def relative(iso, today):
    """'Today', 'Tomorrow', or ''. Only worth saying inside the near horizon."""
    if not iso:
        return ""
    delta = (dt.date.fromisoformat(iso) - dt.date.fromisoformat(today)).days
    return {0: "Today", 1: "Tomorrow", -1: "Yesterday"}.get(delta, "")
