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

# The one blue that is not a category colour. Church uses it for a date
# inside a fortnight, Teams for an AP ranking and a marquee network, Active for
# the add control -- four uses across three tabs, so it gets a name here rather
# than a fourth literal. sports-daily used it first.
BLUE = "#8fb0d8"

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


# ------------------------------------------------------ shared browser code

# Three tabs re-read their Sheet in the browser, so each one needs to escape
# HTML, read a CSV and parse a date the way Python just did. They each grew
# their own copy, and the copies DRIFTED: `2026/11/5` is one of the four forms
# `sheet_date` accepts, and two of the three browser copies silently dropped
# it -- a row would be on the page at 6am and gone the moment the refresh
# landed, which reads as the app having eaten it.
#
# So there is one copy, here, injected into each tab's JS in place of
# `%%HELPERS%%`. `selftest.py` runs `sheet_date` and `sheetDate` over the same
# inputs and requires the same answers.
JS_HELPERS = r"""
  function esc(s){
    return String(s==null?'':s).replace(/[&<>"']/g,function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }
  function two(n){ return (n<10?'0':'')+n; }
  // The LOCAL date. toISOString() would be UTC, which is yesterday all
  // evening on this side of the Atlantic.
  function iso(d){
    return d.getFullYear()+'-'+two(d.getMonth()+1)+'-'+two(d.getDate());
  }
  function today(){ return iso(new Date()); }

  // A date that does not exist is NOT a date. strptime refuses 2026-02-30 and
  // 2/29/2026; a regex happily hands back "2026-02-30", and the row then sorts
  // into a day that never comes. Checked by round trip, which also catches
  // month 13 and day 99.
  function ymd(y,m,d){
    var t=new Date(y,m-1,d);
    if(t.getFullYear()!==y||t.getMonth()!==m-1||t.getDate()!==d) return null;
    return y+'-'+two(m)+'-'+two(d);
  }

  // sheet_date, to the character -- including which forms it REFUSES. Sheets
  // renders a date in the viewer's locale, so the export says "9/8/26" and
  // not ISO. Returns 'YYYY-MM-DD', or null. strptime does not insist on two
  // digits, so neither does this: "2026-11-5" is a date.
  function sheetDate(text){
    text=(text||'').trim();
    var m=text.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/)
         ||text.match(/^(\d{4})\/(\d{1,2})\/(\d{1,2})$/);
    if(m) return ymd(+m[1],+m[2],+m[3]);
    m=text.match(/^(\d{1,2})\/(\d{1,2})\/(\d{2,4})$/);
    if(!m) return null;
    // strptime's %y pivot, not a guess: 69-99 are the 1900s and 00-68 the
    // 2000s. Nothing in this Sheet is from 1999, but the two sides have to
    // answer the same thing or the checks below are testing a coincidence.
    var y=+m[3]; if(y<100) y+=(y<69?2000:1900);
    return ymd(y,+m[1],+m[2]);
  }

  // The gviz export: quoted fields, with doubled quotes inside them.
  function csvRows(text){
    var out=[], row=[], cell='', quoted=false;
    for(var i=0;i<text.length;i++){
      var c=text[i];
      if(quoted){
        if(c==='"'){ if(text[i+1]==='"'){ cell+='"'; i++; } else quoted=false; }
        else cell+=c;
      } else if(c==='"') quoted=true;
      else if(c===','){ row.push(cell); cell=''; }
      else if(c==='\n'){ row.push(cell); out.push(row); row=[]; cell=''; }
      else if(c!=='\r') cell+=c;
    }
    if(cell!==''||row.length){ row.push(cell); out.push(row); }
    return out;
  }

  // wash(), at the one strength the whole app uses.
  function washOf(hex){
    var r=parseInt(hex.substr(1,2),16), g=parseInt(hex.substr(3,2),16),
        b=parseInt(hex.substr(5,2),16);
    return 'rgba('+r+','+g+','+b+',%%WASH%%)';
  }
"""


def js_helpers():
    """The shared block, with the wash strength filled in from WASH."""
    return JS_HELPERS.replace("%%WASH%%", "%.2f" % WASH)
