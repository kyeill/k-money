"""The Reminders tab: what is due over the next eight days.

The Google Sheet is the source of truth. Two things read it, and they must
agree: this module, which renders the page, and the Apps Script in
`apps-script/reminders.gs`, which actually fires the notifications. **The page
is only a view. Nothing here sends anything** -- a static site cannot wake a
phone at 7:30am.

The same rules are also implemented in JS (see JS below) so a pull-to-refresh
re-reads the Sheet live instead of showing the morning's build. That is a
deliberate duplication, and `selftest.py` plus the browser check compare the
two against the same input rather than trusting them to stay in step.
"""

import calendar
import csv
import datetime as dt
import io
import os
import sys

import ui

KEY = "reminders"
LABEL = "Reminders"

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_URL = "https://docs.google.com/spreadsheets/d/%s/gviz/tq?tqx=out:csv"
DAYS_SHOWN = 8
# A day reads as day-then-evening, so the first thing at or after this hour
# gets a gap above it. Display only -- it changes nothing about what fires, and
# it feeds the browser copy too, so there is one number to move.
AFTERNOON_HOUR = 16

# Ticks live in a second tab so every device sees the same state and the Apps
# Script can read it too -- that one decision is what makes ticking something
# off both sync across devices AND stop the notification.
REMINDERS_TAB = "Reminders"
DONE_TAB = "Done"
DONE_HEADER = ["date", "key", "done", "updated"]

# Monday-first, matching both the Sheet's column order and date.weekday().
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
QUARTERLY = {1, 4, 7, 10}

# The header the Sheet must have. Checked because asking Google for a tab that
# does not exist silently returns the FIRST tab instead of erroring, so a
# reordered or renamed sheet would otherwise be parsed as if it were this one.
#
# Columns up to and including nth are fixed. After that the sheet may or may not
# carry a Weekday column, and BOTH layouts are accepted -- the schema has to
# survive being edited while the page and the notifications are live.
# Title, Time and the seven day columns are positional -- the tick grid has to
# be in weekday order. EVERYTHING after them is located BY NAME, so columns can
# be added, removed or reordered without breaking anything. Hard-coded indices
# have already taken this system down twice.
EXPECT = ["title", "time"] + [d.lower() for d in WEEKDAYS]
OPTIONAL = ["nth", "weekday", "every", "starting", "months"]


class SheetError(Exception):
    pass


def _first_words(header):
    return [cell.split()[0] if cell.split() else "" for cell in header]


def layout(header):
    """(ok, {name: index}, [unrecognised headings]).

    Headings match on their FIRST WORD: he labels sections in the sheet and put
    one in the header cell itself -- A1 read "Title DAILY", which broke every
    reader at once. Being forgiving about a label costs nothing and still
    refuses the Done tab, whose first heading is "date".

    Anything after the day columns is found by NAME. A heading we do not know
    is reported rather than ignored: a typo in "Starting" would otherwise mean
    the column is silently dropped and every interval reminder stops.
    """
    words = _first_words(header)
    if words[:len(EXPECT)] != EXPECT:
        return (False, {}, [])
    where, unknown = {}, []
    for i in range(len(EXPECT), len(words)):
        name = words[i]
        if not name:
            continue
        if name in OPTIONAL and name not in where:
            where[name] = i
        else:
            unknown.append(header[i])
    return (True, where, unknown)


def header_ok(header):
    return layout(header)[0]


# ------------------------------------------------------------------ input

def fetch_csv(sheet_id, tab=None):
    """KMONEY_REMINDERS_CSV / _DONE point at local files instead, for tests and
    for `site.py --fixtures`."""
    env = ("KMONEY_REMINDERS_DONE" if tab == DONE_TAB
           else "KMONEY_REMINDERS_CSV")
    local = os.environ.get(env)
    if local:
        if not os.path.exists(local):
            return ""
        with open(local, encoding="utf-8") as fh:
            return fh.read()
    import requests
    url = CSV_URL % sheet_id
    if tab:
        url += "&sheet=" + tab
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return r.text


def read_done(text):
    """{(date, key)} for everything ticked off.

    Asking for a tab that does not exist returns the FIRST tab instead of
    erroring, so before the Done tab is created this would parse the reminders
    themselves as ticks. The header check is what stops that, and a mismatch
    means "nothing is ticked yet" rather than a broken page.
    """
    out = set()
    rows = list(csv.reader(io.StringIO(text or "")))
    if not rows:
        return out
    header = [h.strip().lower().split()[0] if h.strip() else ""
              for h in rows[0]]
    if header[:len(DONE_HEADER)] != DONE_HEADER:
        return out
    for line in rows[1:]:
        cells = [c.strip() for c in line] + [""] * 4
        if cells[0] and cells[1] and cells[2]:
            out.add((cells[0], cells[1]))
    return out


def done_key(rule):
    """"Laundry@12:30" -- the identity of one occurrence.

    The SAME string is built by the page's JS and by the Apps Script. If it
    changes, all three change, or a tick stops matching the reminder it was
    meant to silence.
    """
    return "%s@%02d:%02d" % (rule["title"], rule["at"][0], rule["at"][1])


def parse_time(text):
    """'12:30 PM' -> (12, 30). The CSV endpoint hands back the DISPLAYED value,
    which is why this sees a time at all -- the JSON endpoint would give
    'Date(1899,11,30,12,30,0)', a spreadsheet serial, instead."""
    text = (text or "").strip().upper().replace(".", "")
    if not text:
        return None
    suffix = None
    for tag in ("AM", "PM"):
        if text.endswith(tag):
            suffix, text = tag, text[: -len(tag)].strip()
            break
    bits = text.split(":")
    try:
        hour = int(bits[0])
        minute = int(bits[1]) if len(bits) > 1 else 0
    except (ValueError, IndexError):
        return None
    if not (0 <= minute < 60):
        return None
    if suffix == "PM" and hour < 12:
        hour += 12
    elif suffix == "AM" and hour == 12:
        hour = 0
    return (hour, minute) if 0 <= hour < 24 else None


WORD_NTH = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
            "last": -1}


def parse_nths(text):
    """A LIST of occurrences: "1st, 3rd" is two of them.

    It used to return a single number by stripping non-digits, which turned
    "1st, 3rd" into **13** -- a thirteenth Tuesday does not exist, so those
    reminders fired NEVER. Word forms were not understood either, so "Second"
    parsed to nothing, the row stopped being monthly, and it fell back to the
    weekly ticks and fired four or five times a month instead of once.

    Both are natural things to type and both failed in silence.
    """
    text = (text or "").strip().lower()
    if not text:
        return []
    out = []
    for piece in text.replace(",", " ").split():
        if piece in WORD_NTH:
            value = WORD_NTH[piece]
        else:
            digits = "".join(ch for ch in piece if ch.isdigit())
            value = int(digits) if digits else None
            if value is not None and not 1 <= value <= 31:
                value = None
        if value is not None and value not in out:
            out.append(value)
    return out


def parse_every(text):
    """"4 weeks" -> 28 days. Also "10 days", "2w", "3d".

    A unit is REQUIRED. A bare "4" could mean days or weeks and guessing would
    be wrong half the time -- it is reported as unreadable instead.
    """
    text = (text or "").strip().lower()
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    count = int(digits)
    if count < 1:
        return None
    letters = "".join(ch for ch in text if ch.isalpha())
    if letters.startswith("w"):
        return count * 7
    if letters.startswith("d"):
        return count
    return None


# Shared with the Church tab, so the two cannot drift apart on date parsing.
parse_date = ui.sheet_date


def parse_months(text):
    """Blank or 'All' -> every month. 'Quarterly' -> Jan/Apr/Jul/Oct. Otherwise
    a list of month names, so semi-annual and annual need no new syntax."""
    text = (text or "").strip()
    if not text or text.lower() == "all":
        return set(range(1, 13))
    if text.lower() == "quarterly":
        return set(QUARTERLY)
    out = set()
    for piece in text.replace(",", " ").split():
        head = piece[:3].title()
        if head in MONTHS:
            out.add(MONTHS.index(head) + 1)
    return out or set(range(1, 13))


def header_issues(text):
    """Headings after the day columns that we do not recognise.

    A typo in "Starting" would otherwise mean the column is quietly dropped and
    every interval reminder stops, with nothing anywhere saying so.
    """
    rows = list(csv.reader(io.StringIO(text or "")))
    if not rows:
        return []
    return layout([h.strip().lower() for h in rows[0]])[2]


def read_rules(text):
    """CSV -> rules. Raises SheetError if the header is not what we expect."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise SheetError("the sheet is empty")
    header = [h.strip().lower() for h in rows[0]]
    good, col, unknown = layout(header)
    if not good:
        raise SheetError("unexpected header %r; expected %r then any of %r"
                         % (header, EXPECT, OPTIONAL))
    width = len(header)

    def cell(cells, name):
        i = col.get(name)
        return cells[i] if i is not None and i < len(cells) else ""

    rules = []
    for line in rows[1:]:
        cells = [c.strip() for c in line] + [""] * width
        title = cells[0]
        at = parse_time(cells[1])
        # A time is required, by his call: a reminder with no time cannot fire.
        if not title or not at:
            continue
        nths = parse_nths(cell(cells, "nth"))
        # A cell with text in it that yields nothing is a typo, not a blank --
        # and used to fail silently. It is counted and surfaced on the page.
        every = parse_every(cell(cells, "every"))
        start = parse_date(cell(cells, "starting"))
        # A cell with text in it that yields nothing is a typo, not a blank --
        # and used to fail silently. Counted and surfaced on the page.
        unreadable = ((bool(cell(cells, "nth").strip()) and not nths)
                      or (bool(cell(cells, "every").strip()) and not every)
                      or (bool(cell(cells, "starting").strip()) and not start)
                      # Half an interval rule is no rule at all.
                      or (every is not None) != (start is not None))
        weekday = cell(cells, "weekday").strip().title()
        # Any non-empty mark counts, so x / X / TRUE / a tick all work.
        days = {i for i, d in enumerate(WEEKDAYS) if cells[2 + i]}
        # "4th" with Sun ticked and Weekday left blank is the obvious intent,
        # and it is the natural way to write it. Without this the nth is
        # silently dropped and the row fires EVERY Sunday -- four times too
        # often, with nothing anywhere to say so.
        # With an nth set, the weekday can be inferred rather than typed:
        #   one day ticked  -> that weekday        ("4th" + Sun = 4th Sunday)
        #   no day ticked   -> day of the month    ("25th" = the 25th)
        # The second is what lets the Weekday column be deleted entirely, and
        # it also rescues a case that used to fail silently: an nth with no
        # ticks and no Weekday was not monthly, had no days, and so fired never.
        if nths and not weekday:
            if len(days) == 1:
                weekday = WEEKDAYS[next(iter(days))]
            elif not days:
                weekday = "Day"
        monthly = bool(nths) and weekday != ""
        rules.append({
            "title": title,
            "at": at,
            "days": days,
            "nths": nths,
            "unreadable": unreadable,
            "weekday": weekday,
            "months": parse_months(cell(cells, "months")),
            "every": every,
            "start": start,
            "monthly": monthly,
        })
    return rules


# -------------------------------------------------------------- the rules

def nth_weekday(year, month, weekday, nth):
    """The nth Tuesday of a month, or the last one when nth is -1."""
    first = dt.date(year, month, 1)
    days_in = calendar.monthrange(year, month)[1]
    offset = (weekday - first.weekday()) % 7
    if nth == -1:
        day = 1 + offset + ((days_in - 1 - offset) // 7) * 7
    else:
        day = 1 + offset + (nth - 1) * 7
    return dt.date(year, month, day) if 1 <= day <= days_in else None


def nth_day(year, month, nth):
    """'1st Day' is the 1st of the month; 'Last Day' is the last."""
    days_in = calendar.monthrange(year, month)[1]
    day = days_in if nth == -1 else nth
    return dt.date(year, month, day) if 1 <= day <= days_in else None


def fires_on(rule, day):
    # Months gates BOTH kinds of rule, so "Sat ticked, Months = Sep, Oct, Nov,
    # Dec" is a weekly reminder with a season. A blank Months parses to all
    # twelve, so every existing row is unaffected by this being here.
    if day.month not in rule["months"]:
        return False
    # Interval beats everything: "every 4 weeks from the 7th" is its own
    # schedule and the tick grid, if any, is not consulted. One row, one
    # schedule. Counted in whole days from the anchor, so DST cannot drift it.
    if rule.get("every") and rule.get("start"):
        if day < rule["start"]:
            return False
        return (day - rule["start"]).days % rule["every"] == 0
    if rule["monthly"]:
        # A row carrying both a monthly rule and weekly ticks is monthly. One
        # row, one schedule -- a row firing on both would be unreadable later.
        if rule["weekday"] == "Day":
            return any(nth_day(day.year, day.month, n) == day
                       for n in rule["nths"])
        if rule["weekday"] not in WEEKDAYS:
            return False
        target = WEEKDAYS.index(rule["weekday"])
        return any(nth_weekday(day.year, day.month, target, n) == day
                   for n in rule["nths"])
    return day.weekday() in rule["days"]


def upcoming(rules, today, days=DAYS_SHOWN):
    """[(date, [rule, ...])] for the next `days` days, each list time-sorted."""
    out = []
    for step in range(days):
        day = today + dt.timedelta(days=step)
        due = sorted((r for r in rules if fires_on(r, day)),
                     key=lambda r: (r["at"], r["title"].lower()))
        out.append((day, due))
    return out


# ----------------------------------------------------------------- render

CSS = """
.rday{margin:18px 0 0}
.rday h2{font-size:12px;text-transform:uppercase;letter-spacing:.08em;
         color:var(--muted);font-weight:600;margin:0 0 7px}
.rday h2 b{color:var(--ink);font-weight:600}
.rem{display:flex;gap:11px;align-items:baseline;background:var(--card);
     border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:6px 0}
/* Today's, still to do. `.tick` is only ever put on today's rows and `.done`
   is toggled by the checkbox handler, so ticking clears the shading on its own
   -- no JS knows this rule exists. The wash carries it alone: no leading
   stripe here, unlike Church, where the stripe is what separates one colour
   from another. There is only one colour on this tab, so it had nothing to
   distinguish. Two layers, because a translucent colour on the page
   background would make a shaded row DARKER than a plain one. */
label.rem.tick:not(.done){
     background:linear-gradient(%(wash)s,%(wash)s),var(--card)}
.rem .rt{flex:0 0 auto;width:74px;font-variant-numeric:tabular-nums;
         font-weight:600;font-size:13.5px}
.rem .rn{flex:1 1 auto;min-width:0;font-size:15px;
         overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
label.rem.tick{cursor:pointer;-webkit-tap-highlight-color:transparent}
/* The row aligns on the text baseline, and a checkbox's baseline is its BOTTOM
   edge -- so baseline alignment sits it visibly high against the text. Centre
   this one item instead, leaving the time and title sharing their baseline. */
label.rem input{flex:0 0 auto;width:19px;height:19px;margin:0 1px 0 0;
                align-self:center;accent-color:var(--accent)}
/* A day with no checkboxes reserves their width anyway, so the time and title
   hold one column down the whole page instead of stepping left after today.
   Same width and margin as the input, so the two stay in step. */
.rem:not(.tick)::before{content:"";flex:0 0 auto;width:19px;margin-right:1px;
                        align-self:center}
/* Ticked rows stay in place rather than reordering -- a list that rearranges
   itself under your thumb is how you tick the wrong thing. */
label.rem.done .rt,label.rem.done .rn{opacity:.45;text-decoration:line-through}
/* The break between morning and the rest of the day. Space only -- a rule or
   a heading would imply two sections, and it is one day. */
.rem.pm1{margin-top:20px}
.rnone{color:var(--muted);font-size:13px;padding:1px 2px 3px}
.rfoot{color:var(--muted);font-size:12px;margin:16px 2px 0}
.rerr{color:var(--bad,#d4676a);font-size:13px;border:1px dashed var(--line);
      border-radius:9px;padding:10px 12px;margin:12px 0}
#rpull{text-align:center;color:var(--muted);font-size:12px;height:0;
       overflow:hidden;transition:height .15s}
#rpull.on{height:22px}
@media (min-width:641px){
  .rday{margin:24px 0 0}
  .rday h2{font-size:13px}
  .rem{padding:12px 14px;margin:8px 0}
  .rem.pm1{margin-top:26px}
  label.rem input{width:21px;height:21px}
  .rem:not(.tick)::before{width:21px}
  .rem .rt{width:88px;font-size:15px}
  .rem .rn{font-size:17px}
  .rfoot{font-size:13px}
}
""" % {"wash": ui.wash(ui.COLORS["orange"])}

# The same rules again, in the browser, so a pull-down re-reads the Sheet
# instead of showing whatever the 6am build baked. Kept deliberately close to
# the Python above; selftest and the browser check compare their output.
JS = """
(function(){
  var SHEET=%%SHEET%%, DAYS=%%DAYS%%, WEBAPP=%%WEBAPP%%, PMHOUR=%%PMHOUR%%;
  var WD=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
  var OPTIONAL=['nth','weekday','every','starting','months'];
  var WORDN={first:1,second:2,third:3,fourth:4,fifth:5,last:-1};
  // "4 weeks" -> 28. A unit is required; a bare number could mean either.
  function parseEvery(t){
    t=(t||'').trim().toLowerCase();
    var d=t.replace(/[^0-9]/g,'');
    if(!d) return null;
    var n=parseInt(d,10); if(n<1) return null;
    var L=t.replace(/[^a-z]/g,'');
    if(L.charAt(0)==='w') return n*7;
    if(L.charAt(0)==='d') return n;
    return null;
  }
  // Sheets renders dates in the viewer's locale, so ISO and US slash both.
  function parseDate(t){
    t=(t||'').trim(); if(!t) return null;
    var m=/^(\\d{4})-(\\d{2})-(\\d{2})$/.exec(t);
    if(m) return new Date(+m[1],+m[2]-1,+m[3]);
    m=/^(\\d{1,2})\\/(\\d{1,2})\\/(\\d{2,4})$/.exec(t);
    if(m){ var y=+m[3]; if(y<100) y+=2000; return new Date(y,+m[1]-1,+m[2]); }
    return null;
  }
  function dayNum(d){ return Math.floor(Date.UTC(d.getFullYear(),d.getMonth(),d.getDate())/864e5); }
  // A LIST: "1st, 3rd" is two occurrences. Stripping non-digits made it 13.
  function parseNths(t){
    t=(t||'').trim().toLowerCase();
    if(!t) return [];
    var out=[];
    t.replace(/,/g,' ').split(/\\s+/).forEach(function(p){
      if(!p) return;
      var v;
      if(WORDN[p]!==undefined) v=WORDN[p];
      else { var d=p.replace(/[^0-9]/g,''); v=d?parseInt(d,10):null;
             if(v!==null&&(v<1||v>31)) v=null; }
      if(v!==null&&v!==undefined&&out.indexOf(v)<0) out.push(v);
    });
    return out;
  }
  var MO=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

  function splitCSV(text){
    var rows=[],row=[],cell='',q=false,i;
    for(i=0;i<text.length;i++){
      var c=text[i];
      if(q){
        if(c==='"'){ if(text[i+1]==='"'){cell+='"';i++;} else q=false; }
        else cell+=c;
      } else if(c==='"') q=true;
      else if(c===','){ row.push(cell); cell=''; }
      else if(c==='\\n'){ row.push(cell); rows.push(row); row=[]; cell=''; }
      else if(c!=='\\r') cell+=c;
    }
    if(cell!==''||row.length){ row.push(cell); rows.push(row); }
    return rows;
  }
  function parseTime(t){
    t=(t||'').trim().toUpperCase().replace(/\\./g,'');
    if(!t) return null;
    var suf=null,m;
    if(/AM$/.test(t)){suf='AM';t=t.slice(0,-2).trim();}
    else if(/PM$/.test(t)){suf='PM';t=t.slice(0,-2).trim();}
    m=t.split(':');
    var h=parseInt(m[0],10), mi=m.length>1?parseInt(m[1],10):0;
    if(isNaN(h)||isNaN(mi)||mi<0||mi>59) return null;
    if(suf==='PM'&&h<12)h+=12; else if(suf==='AM'&&h===12)h=0;
    return (h>=0&&h<24)?[h,mi]:null;
  }
  function parseMonths(t){
    t=(t||'').trim();
    var all=[1,2,3,4,5,6,7,8,9,10,11,12];
    if(!t||t.toLowerCase()==='all') return all;
    if(t.toLowerCase()==='quarterly') return [1,4,7,10];
    var out=[];
    t.replace(/,/g,' ').split(/\\s+/).forEach(function(p){
      if(!p) return;
      var h=p.slice(0,3).toLowerCase();
      h=h.charAt(0).toUpperCase()+h.slice(1);
      var i=MO.indexOf(h); if(i>=0&&out.indexOf(i+1)<0) out.push(i+1);
    });
    return out.length?out:all;
  }
  function readRules(text){
    var rows=splitCSV(text);
    if(!rows.length) throw new Error('empty sheet');
    // Everything after the day columns is located BY NAME, so columns can be
    // added, removed or reordered without breaking anything.
    var head=rows[0].map(function(x){
      return (x||'').trim().toLowerCase().split(/\\s+/)[0]; });
    var COL={}, oi;
    for(oi=9;oi<head.length;oi++)
      if(OPTIONAL.indexOf(head[oi])>=0&&COL[head[oi]]===undefined) COL[head[oi]]=oi;
    function cell(c,name){
      var i=COL[name];
      return (i===undefined||i>=c.length)?'':c[i];
    }
    var rules=[],i;
    for(i=1;i<rows.length;i++){
      var c=rows[i].map(function(x){return (x||'').trim();});
      while(c.length<head.length) c.push('');
      var at=parseTime(c[1]);
      if(!c[0]||!at) continue;
      var nths=parseNths(cell(c,'nth'));
      var every=parseEvery(cell(c,'every')), start=parseDate(cell(c,'starting'));
      var wd=(cell(c,'weekday')||'').trim();
      wd=wd?wd.charAt(0).toUpperCase()+wd.slice(1).toLowerCase():'';
      var days=[],d;
      for(d=0;d<7;d++) if(c[2+d]) days.push(d);
      // One day ticked means that weekday; none ticked means day of the month.
      if(nths.length&&wd===''){
        if(days.length===1) wd=WD[days[0]];
        else if(!days.length) wd='Day';
      }
      rules.push({title:c[0],at:at,days:days,nths:nths,every:every,start:start,
                  weekday:wd,months:parseMonths(cell(c,'months')),
                  monthly:(nths.length>0&&wd!=='')});
    }
    return rules;
  }
  // JS getDay() is Sunday-based; the Sheet and Python are Monday-based.
  function wd(date){ return (date.getDay()+6)%7; }
  function daysIn(y,m){ return new Date(y,m,0).getDate(); }
  function nthWeekday(y,m,target,nth){
    var first=new Date(y,m-1,1), off=(target-wd(first)+7)%7, di=daysIn(y,m), day;
    if(nth===-1) day=1+off+Math.floor((di-1-off)/7)*7;
    else day=1+off+(nth-1)*7;
    return (day>=1&&day<=di)?day:null;
  }
  function firesOn(r,date){
    var y=date.getFullYear(), m=date.getMonth()+1, dd=date.getDate();
    // Months gates weekly rows too, so a weekly rule can have a season.
    if(r.months.indexOf(m)<0) return false;
    // Interval beats everything; whole days from the anchor, so DST cannot
    // drift it.
    if(r.every&&r.start){
      var a=dayNum(r.start), b=dayNum(date);
      return b>=a && ((b-a)%r.every)===0;
    }
    if(r.monthly){
      var i;
      if(r.weekday==='Day'){
        for(i=0;i<r.nths.length;i++){
          var want=(r.nths[i]===-1)?daysIn(y,m):r.nths[i];
          if(want>=1&&want<=daysIn(y,m)&&want===dd) return true;
        }
        return false;
      }
      var t=WD.indexOf(r.weekday);
      if(t<0) return false;
      for(i=0;i<r.nths.length;i++) if(nthWeekday(y,m,t,r.nths[i])===dd) return true;
      return false;
    }
    return r.days.indexOf(wd(date))>=0;
  }
  function two(n){ return (n<10?'0':'')+n; }
  function clock(at){
    var h=at[0]%12; if(h===0)h=12;
    return h+':'+two(at[1])+' '+(at[0]<12?'am':'pm');
  }
  function esc(s){ return String(s).replace(/[&<>"]/g,function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  function doneKey(r){ return r.title+'@'+two(r.at[0])+':'+two(r.at[1]); }
  function iso(d){ return d.getFullYear()+'-'+two(d.getMonth()+1)+'-'+two(d.getDate()); }

  // A tick is fire-and-forget: an Apps Script web app redirects, and a browser
  // will not follow that for a readable cross-origin response, so the reply is
  // unreadable by design. The Sheet is reconciled on the next read instead.
  // Until then PENDING holds what was just tapped, so a refresh three seconds
  // later does not show the box springing back open.
  var PENDING={};
  try{ PENDING=JSON.parse(localStorage.getItem('rdone')||'{}'); }catch(e){}
  function remember(key,on){
    PENDING[key]={on:on,at:Date.now()};
    try{ localStorage.setItem('rdone',JSON.stringify(PENDING)); }catch(e){}
  }
  function pending(key){
    var p=PENDING[key];
    if(!p) return null;
    if(Date.now()-p.at>12e4){ delete PENDING[key]; return null; }
    return p.on;
  }

  function build(rules,today,done){
    done=done||{};
    var out=[],i,step,todayIso=iso(today);
    for(step=0;step<DAYS;step++){
      var day=new Date(today.getFullYear(),today.getMonth(),today.getDate()+step);
      var due=rules.filter(function(r){return firesOn(r,day);});
      due.sort(function(a,b){
        return (a.at[0]-b.at[0])||(a.at[1]-b.at[1])||
               (a.title.toLowerCase()<b.title.toLowerCase()?-1:1); });
      var label=step===0?'Today':
        day.toLocaleDateString(undefined,{weekday:'long',month:'short',day:'numeric'});
      out.push('<div class="rday"><h2>'+esc(label)+'</h2>');
      if(!due.length) out.push('<div class="rnone">Nothing.</div>');
      for(i=0;i<due.length;i++){
        var r=due[i];
        // Gap above the first thing at or after 1pm, but only if something
        // came before it -- an afternoon-only day gets no stray space.
        var pm=(i>0&&r.at[0]>=PMHOUR&&due[i-1].at[0]<PMHOUR)?' pm1':'';
        // Only today is tickable: ticking ahead would silence a notification
        // days early, which nobody means by it.
        if(step!==0){
          out.push('<div class="rem'+pm+'"><span class="rt">'+esc(clock(r.at))+
                   '</span><span class="rn">'+esc(r.title)+'</span></div>');
          continue;
        }
        var k=doneKey(r), p=pending(k);
        var on = (p===null) ? !!done[todayIso+'|'+k] : p;
        out.push('<label class="rem tick'+(on?' done':'')+pm+'">'+
                 '<input type="checkbox" data-key="'+esc(k)+'"'+(on?' checked':'')+'>'+
                 '<span class="rt">'+esc(clock(r.at))+'</span>'+
                 '<span class="rn">'+esc(r.title)+'</span></label>');
      }
      out.push('</div>');
    }
    return out.join('');
  }
  window.__remBuild=function(text,today,done){ return build(readRules(text),today,done||{}); };
  // The pending overlay is a JS-only idea -- Python has no user to have just
  // tapped something. The parity check therefore needs a way to clear it, or
  // an old tap makes the two engines look like they disagree when they do not.
  window.__remReset=function(){
    PENDING={};
    try{ localStorage.removeItem('rdone'); }catch(e){}
  };

  var pane=document.querySelector('section[data-k="reminders"]');
  if(!pane) return;
  var body=pane.querySelector('#rbody'), note=pane.querySelector('#rpull');
  var busy=false;
  function sheetCsv(tab){
    // The Sheet allows cross-origin reads, which is the whole reason a
    // pull-down can show an edit made a minute ago rather than this morning's
    // build. cache-busted, or the browser hands back its own copy.
    return 'https://docs.google.com/spreadsheets/d/'+SHEET+
           '/gviz/tq?tqx=out:csv'+(tab?'&sheet='+encodeURIComponent(tab):'')+
           '&_='+Date.now();
  }
  function readDone(text){
    var rows=splitCSV(text||''), out={}, i;
    if(!rows.length) return out;
    var h=rows[0].map(function(x){return (x||'').trim().toLowerCase().split(/\\s+/)[0];});
    // An unknown tab returns the FIRST one, so without this the reminders
    // themselves would be parsed as ticks.
    if(h[0]!=='date'||h[1]!=='key'||h[2]!=='done') return out;
    for(i=1;i<rows.length;i++){
      var c=rows[i].map(function(x){return (x||'').trim();});
      if(c[0]&&c[1]&&c[2]) out[c[0]+'|'+c[1]]=true;
    }
    return out;
  }
  // Almost every refresh rebuilds exactly what is already on screen -- the
  // page opens on a baked copy, and the sheet has usually not changed since.
  // Assigning innerHTML anyway tears the rows down and rebuilds them, which is
  // the flash. So compare first, and only touch the DOM when something is
  // actually different.
  //
  // Both sides go through innerHTML before comparing: read back from the DOM,
  // the browser normalises quoting and attribute order, so the string it
  // returns never matches a freshly built one character for character even
  // when the two are identical.
  var scratch=document.createElement('div');
  function paint(html){
    scratch.innerHTML=html;
    if(scratch.innerHTML!==body.innerHTML) body.innerHTML=scratch.innerHTML;
  }

  // The baked copy is what a reload paints FIRST, and it was built at 6am --
  // so everything ticked since then comes back unticked and orange for as long
  // as the fetch takes. That is the flash, and the guard above cannot help:
  // the two really are different.
  //
  // So the last list actually seen is kept and painted back at once, before
  // any network. The fetch that follows almost always just confirms it.
  // Keyed by date, because yesterday's list restored this morning would be
  // worse than the baked one.
  var SNAP='rsnap:';
  function snapKey(){ return SNAP+iso(new Date()); }
  function saveSnap(html){
    try{
      Object.keys(localStorage).forEach(function(k){
        if(k.indexOf(SNAP)===0 && k!==snapKey()) localStorage.removeItem(k);
      });
      localStorage.setItem(snapKey(),html);
    }catch(e){}
  }
  function loadSnap(){
    try{ return localStorage.getItem(snapKey()); }catch(e){ return null; }
  }
  function refresh(){
    if(busy||!SHEET) return;
    busy=true;
    var rules=null;
    fetch(sheetCsv('Reminders'),{cache:'no-store'})
      .then(function(r){ if(!r.ok) throw new Error(r.status); return r.text(); })
      .then(function(t){
        rules=readRules(t);
        // Ticks are a convenience; if the Done tab is missing or unreadable
        // the list must still render.
        return fetch(sheetCsv('Done'),{cache:'no-store'})
          .then(function(r){ return r.ok? r.text() : ''; })
          .catch(function(){ return ''; });
      })
      .then(function(d){
        var html=build(rules,new Date(),readDone(d));
        paint(html);
        saveSnap(html);
      })
      .catch(function(){})            // keep the baked list; it is not wrong
      .then(function(){ busy=false; });
  }

  // Delegated, because every refresh replaces the rows underneath.
  pane.addEventListener('change',function(e){
    var box=e.target;
    if(!box||box.type!=='checkbox'||!box.dataset.key) return;
    var on=box.checked, key=box.dataset.key;
    box.closest('label').classList.toggle('done',on);
    remember(key,on);
    if(!WEBAPP) return;
    // no-cors: the reply is unreadable across origins from an Apps Script web
    // app, and is not needed -- the Sheet is the record, reconciled on the
    // next read.
    fetch(WEBAPP+'?action=done&date='+encodeURIComponent(iso(new Date()))+
          '&key='+encodeURIComponent(key)+'&done='+(on?'1':'0'),
          {mode:'no-cors',cache:'no-store'}).catch(function(){});
  });
  // Before the network, not after it.
  var snap=loadSnap();
  if(snap) paint(snap);
  refresh();
  document.addEventListener('visibilitychange',function(){
    if(document.visibilityState==='visible') refresh(); });

  // Pull to refresh, only at the top of the page and only on a clear vertical
  // drag, so it cannot fight the horizontal swipe that changes tabs.
  var y0=null;
  addEventListener('touchstart',function(e){
    y0=(scrollY<=0&&e.touches.length===1)?e.touches[0].clientY:null;
  },{passive:true});
  addEventListener('touchmove',function(e){
    if(y0===null) return;
    var dy=e.touches[0].clientY-y0;
    if(note) note.classList.toggle('on',dy>40);
  },{passive:true});
  addEventListener('touchend',function(e){
    if(y0===null) return;
    var dy=e.changedTouches[0].clientY-y0;
    y0=null;
    if(note) note.classList.remove('on');
    if(dy>70) refresh();
  },{passive:true});
})();
"""


def clock(at):
    hour = at[0] % 12 or 12
    return "%d:%02d %s" % (hour, at[1], "am" if at[0] < 12 else "pm")


# "Tomorrow" read fine alone but sat oddly above a column of real dates.
day_label = ui.day_heading


def starts_afternoon(due, i):
    """True for the first row at or after AFTERNOON_HOUR, when something came
    before it.

    A day with nothing but evening items gets no stray gap at the top.
    """
    return (i > 0 and due[i]["at"][0] >= AFTERNOON_HOUR
            and due[i - 1]["at"][0] < AFTERNOON_HOUR)


def row_html(rule, tickable, gap=False):
    """One reminder. Only today's are tickable -- ticking ahead is not a thing
    anyone means, and it would silence a notification days early."""
    pm = " pm1" if gap else ""
    if not tickable:
        return ('<div class="rem%s"><span class="rt">%s</span>'
                '<span class="rn">%s</span></div>'
                % (pm, ui.esc(clock(rule["at"])), ui.esc(rule["title"])))
    done = rule.get("done")
    return ('<label class="rem tick%s%s"><input type="checkbox" data-key="%s"%s>'
            '<span class="rt">%s</span><span class="rn">%s</span></label>'
            % (" done" if done else "", pm,
               ui.esc(done_key(rule)),
               " checked" if done else "",
               ui.esc(clock(rule["at"])), ui.esc(rule["title"])))


def render(data):
    if data.get("error"):
        return ('<div class="rerr">Could not read the reminders sheet: %s</div>'
                % ui.esc(data["error"]))
    out = ['<div id="rpull">Release to refresh</div><div id="rbody">']
    for day, due in data["days"]:
        first = day == data["today"]
        out.append('<div class="rday"><h2>%s</h2>'
                   % ui.esc(day_label(day, data["today"])))
        if not due:
            out.append('<div class="rnone">Nothing.</div>')
        for i, rule in enumerate(due):
            out.append(row_html(rule, first, starts_afternoon(due, i)))
        out.append("</div>")
    out.append("</div>")
    cols = data.get("unknown_cols") or []
    if cols:
        out.append('<div class="rerr">Column heading not recognised: %s</div>'
                   % ui.esc(", ".join(cols)))
    bad = data.get("unreadable") or []
    if bad:
        # These parse to no cadence at all, so they would simply never fire.
        # Silence is the one thing a reminders app must not do.
        out.append('<div class="rerr">Could not read the cadence for: %s</div>'
                   % ui.esc(", ".join(bad)))
    out.append('<div class="rfoot">%d reminder%s in the sheet · '
               'notifications are sent by the sheet, not this page</div>'
               % (data["count"], "" if data["count"] == 1 else "s"))
    return "".join(out)


def build(today=None, cfg=None, record=True):
    import watch                      # shares load_config and its override
    today = dt.date.fromisoformat(today) if isinstance(today, str) else today
    today = today or dt.date.today()
    cfg = cfg or watch.load_config()
    sheet = (cfg.get("reminders_sheet") or "").strip()
    if not sheet:
        return {"today": today, "days": [], "count": 0,
                "error": "no reminders_sheet in config.json", "sheet": ""}
    try:
        sheet_csv = fetch_csv(sheet, cfg.get("reminders_tab", REMINDERS_TAB))
        rules = read_rules(sheet_csv)
    except Exception as exc:          # a bad sheet must not kill the build
        return {"today": today, "days": [], "count": 0,
                "error": "%s" % exc, "sheet": sheet}
    try:
        done = read_done(fetch_csv(sheet, DONE_TAB))
    except Exception:
        # Ticks are a convenience. Losing them must never cost the schedule.
        done = set()
    unreadable = [r["title"] for r in rules if r.get("unreadable")]
    unknown_cols = header_issues(sheet_csv)
    days = upcoming(rules, today)
    iso = today.isoformat()
    for rule in days[0][1]:
        rule["done"] = (iso, done_key(rule)) in done
    return {"today": today, "days": days, "sheet": sheet,
            "count": len(rules), "error": None, "unreadable": unreadable,
            "unknown_cols": unknown_cols,
            "webapp": (cfg.get("reminders_webapp") or "").strip()}


def page_js(data):
    return (JS.replace("%%SHEET%%", '"%s"' % data.get("sheet", ""))
              .replace("%%WEBAPP%%", '"%s"' % data.get("webapp", ""))
              .replace("%%DAYS%%", str(DAYS_SHOWN))
              .replace("%%PMHOUR%%", str(AFTERNOON_HOUR)))


if __name__ == "__main__":
    # Reminder titles carry emoji and the Windows console is cp1252, which
    # cannot encode them -- printing the list would die on its own output.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    d = build()
    if d["error"]:
        raise SystemExit("error: " + d["error"])
    for day, due in d["days"]:
        print("%s (%d)" % (day_label(day, d["today"]), len(due)))
        for r in due:
            print("    %-9s %s" % (clock(r["at"]), r["title"]))
    print("\n%d reminder(s) in the sheet" % d["count"])
