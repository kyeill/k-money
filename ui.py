"""Shared render helpers. Anything a future tab would otherwise reinvent."""

import datetime as dt
import html


def esc(text):
    return html.escape(str(text if text is not None else ""))


def chip(text, cls="chip"):
    return '<span class="%s">%s</span>' % (cls, esc(text))


# ------------------------------------------------------------------ colour

# Named rather than hex, because the Sheet gets edited from a phone and
# "Orange" is a thing you can type. Every value is picked to show against the
# dark card: black and white say nothing as a stripe, so those two are bent
# towards a slate and a bone rather than rejected.
#
# Lives here, not in church.py, because Reminders shades today's unticked rows
# in the same orange -- and church.py imports reminders.py, so the dependency
# cannot run the other way.
COLORS = {
    "red": "#e03a3e", "orange": "#e8730c", "amber": "#e0a72b",
    "yellow": "#e0c341", "green": "#3aab5c", "teal": "#25a1a1",
    "blue": "#3d8ee0", "navy": "#5a7fd6", "purple": "#9a6ee0",
    "pink": "#e05c96", "brown": "#b07a52", "gray": "#8b93a0",
    "grey": "#8b93a0", "black": "#6d7480", "white": "#d6d3cd",
}

# The strength of the wash under a shaded row. Faint on purpose: at full
# strength the colour fights the text it sits behind, and a page of saturated
# cards stops distinguishing anything. Mixed here rather than with CSS
# color-mix(), which the phone browsers this is read on do not all have.
WASH = 0.13


def wash(hex_color, strength=WASH):
    """`#e8730c` -> the same colour laid over the card at WASH strength."""
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return "rgba(%d,%d,%d,%.2f)" % (r, g, b, strength)


def shade(hex_color):
    """The two custom properties a shaded row needs: the edge and the wash.

    The card colour has to be painted UNDERNEATH the wash -- a translucent
    colour laid straight on the page background makes a shaded row come out
    DARKER than a plain one, which is backwards. See the `background` rule that
    consumes these.
    """
    return "--tint:%s;--wash:%s" % (hex_color, wash(hex_color))


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
