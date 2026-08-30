"""Shared render helpers. Anything a future tab would otherwise reinvent."""

import datetime as dt
import html


def esc(text):
    return html.escape(str(text if text is not None else ""))


def chip(text, cls="chip"):
    return '<span class="%s">%s</span>' % (cls, esc(text))


def day_parts(iso, today=None):
    """('Sep 3', 'Wed') -- or ('Sep 3 2027', '') once the year stops being
    obvious, because a bare 'Sep 3' three years out reads as this September."""
    if not iso:
        return ("TBA", "")
    day = dt.date.fromisoformat(iso)
    now = dt.date.fromisoformat(today) if today else dt.date.today()
    label = "%s %d" % (day.strftime("%b"), day.day)
    if day.year != now.year:
        return ("%s %d" % (label, day.year), "")
    return (label, day.strftime("%a"))


def relative(iso, today):
    """'Today', 'Tomorrow', or ''. Only worth saying inside the near horizon."""
    if not iso:
        return ""
    delta = (dt.date.fromisoformat(iso) - dt.date.fromisoformat(today)).days
    return {0: "Today", 1: "Tomorrow", -1: "Yesterday"}.get(delta, "")
