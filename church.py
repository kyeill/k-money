"""The Church tab: dated events from the Church tab of the same Sheet.

Deliberately much simpler than Reminders. There are no cadences here -- every
row carries its own date -- so there is nothing to recompute, nothing to notify
and nothing to keep in step with the Apps Script.

Only dates from today onward are shown, and only days that actually have
something on them: most days do not, and a column of empty headings would bury
the handful that matter.

The page is baked each morning, but the Sheet is edited whenever Kyle thinks of
something -- so `JS` below re-reads the tab in the browser on open, the way
Reminders and Active already do. The rules there are a second implementation of
`read_events` and `render`, and the two have to agree; `selftest.py` holds them
to it.
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

# How close a day has to be for its heading to change colour. Orange first,
# then blue, then the ordinary muted grey -- so the top of the list says what
# is imminent without a single date being read.
SOON_DAYS, NEAR_DAYS = 7, 14

# The same blue the Teams tab uses for a ranking, and sports-daily before it.
RANK_BLUE = ui.BLUE


def urgency(day, today):
    """"soon" within a week, "near" within two, otherwise "".

    No class at all past two weeks, rather than a third colour: a page where
    every heading is coloured highlights nothing.
    """
    ahead = (day - today).days
    if ahead <= SOON_DAYS:
        return "soon"
    if ahead <= NEAR_DAYS:
        return "near"
    return ""


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
/* The nav's own underline colour rather than the row wash's orange, which was
   too bright for a heading, and the same blue the Teams tab gives a ranking. */
.cday.soon h2{color:var(--accent)}
.cday.near h2{color:%(blue)s}
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
""" % {"blue": RANK_BLUE}


def render(data):
    # The wrapper is OUTSIDE the error branch on purpose. A failed read at
    # build time is the case that most wants the browser to try again, so the
    # refresh has to have something to paint into even then -- a page that
    # cannot self-heal is stuck with a 6am outage until 6am tomorrow.
    body = _body(data)
    return '<div id="cbody">%s</div>' % body


def _body(data):
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
        near = urgency(day, data["today"])
        out.append('<div class="cday%s"><h2>%s</h2>'
                   % ((" " + near) if near else "",
                      ui.esc(ui.day_heading(day, data["today"]))))
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


# The browser copy of `read_events` and `render`. It exists because the page is
# built once a morning and the Sheet is edited all day: twice in one week Kyle
# added something to the Church tab, opened the app and did not see it. The
# rules are duplicated rather than shared because the only thing that could
# share them is a round trip to a server this app does not have.
#
# Everything it paints must match what Python produced, or the list would
# visibly rearrange itself a second after opening.
# A RAW string, deliberately: the JS below contains backslash escapes of
# its own (newline and carriage return in the CSV reader, digit classes in
# the date regexes). In an ordinary triple-quoted string Python would eat
# the first two into real control characters inside a JS string literal --
# a syntax error in the browser that is invisible in the source, which is
# the exact failure NOTES.md records under corrupted escapes.
JS = r"""
(function(){
  var SHEET=%%SHEET%%, TAB=%%TAB%%, COLORS=%%COLORS%%,
      SOON=%%SOON%%, NEAR=%%NEAR%%;
  var pane=document.querySelector('section[data-k="church"]');
  if(!pane||!SHEET) return;
  var body=pane.querySelector('#cbody');
  if(!body) return;

  function esc(s){
    return String(s==null?'':s).replace(/[&<>"']/g, function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }
  function iso(d){
    return new Date(d.getTime()-d.getTimezoneOffset()*6e4)
             .toISOString().slice(0,10);
  }
  function today(){ return iso(new Date()); }

  // A minimal CSV reader: quoted fields with doubled quotes inside, which is
  // everything the gviz endpoint emits. The Active tab carries the same one.
  function rows(text){
    var out=[], row=[], field='', quoted=false;
    for(var i=0;i<text.length;i++){
      var c=text[i];
      if(quoted){
        if(c==='"'){ if(text[i+1]==='"'){ field+='"'; i++; } else quoted=false; }
        else field+=c;
      } else if(c==='"') quoted=true;
      else if(c===','){ row.push(field); field=''; }
      else if(c==='\n'){ row.push(field); out.push(row); row=[]; field=''; }
      else if(c!=='\r') field+=c;
    }
    if(field||row.length){ row.push(field); out.push(row); }
    return out;
  }

  // The four forms ui.sheet_date accepts. Sheets renders a date in the
  // VIEWER'S locale, so the export says "9/8/26" and not ISO.
  function parseDate(text){
    text=(text||'').trim();
    var m=text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if(m) return m[1]+'-'+m[2]+'-'+m[3];
    m=text.match(/^(\d{4})\/(\d{1,2})\/(\d{1,2})$/);
    if(m) return m[1]+'-'+('0'+m[2]).slice(-2)+'-'+('0'+m[3]).slice(-2);
    m=text.match(/^(\d{1,2})\/(\d{1,2})\/(\d{2,4})$/);
    if(!m) return null;
    var y=Number(m[3]); if(y<100) y+=2000;
    return y+'-'+('0'+m[1]).slice(-2)+'-'+('0'+m[2]).slice(-2);
  }

  // color_of: a named colour from the shared palette, or a literal #rrggbb.
  function colourFor(text){
    text=(text||'').trim().toLowerCase();
    if(!text) return null;
    if(/^#?[0-9a-f]{6}$/.test(text)) return '#'+text.replace(/^#/,'');
    return COLORS[text]||null;
  }
  // ui.wash, at the one strength the whole app uses.
  function washOf(hex){
    var r=parseInt(hex.substr(1,2),16), g=parseInt(hex.substr(3,2),16),
        b=parseInt(hex.substr(5,2),16);
    return 'rgba('+r+','+g+','+b+',0.13)';
  }

  // ui.day_heading: only today is named.
  function heading(day, now){
    if(day===now) return 'Today';
    var d=new Date(day+'T12:00:00');
    var days=['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
    var mon=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    return days[d.getDay()]+', '+mon[d.getMonth()]+' '+d.getDate();
  }

  // Noon on both sides, so a clock change cannot turn seven days into 6.96 and
  // drop a heading out of the orange band.
  function urgency(day, now){
    var ahead=Math.round((new Date(day+'T12:00:00')-new Date(now+'T12:00:00'))/864e5);
    if(ahead<=SOON) return 'soon';
    if(ahead<=NEAR) return 'near';
    return '';
  }

  function build(text){
    var lines=rows(text);
    if(!lines.length) return null;
    var head=lines[0].map(function(h){
      h=(h||'').trim().toLowerCase(); return h.split(' ')[0];
    });
    var at={}, unknown=[], known=['title','date','details','color'];
    head.forEach(function(name,i){
      if(!name) return;
      if(known.indexOf(name)>=0){ if(at[name]===undefined) at[name]=i; }
      else unknown.push(name);
    });
    // No Title or no Date means the tab has been restructured, not that it is
    // empty. Keep whatever the build produced rather than painting a blank
    // list over a correct one.
    if(at.title===undefined||at.date===undefined) return null;
    var now=today(), byDay={}, bad=[];
    for(var i=1;i<lines.length;i++){
      var c=lines[i].map(function(v){ return (v||'').trim(); });
      var title=c[at.title]||'';
      if(!title) continue;
      var when=c[at.date]||'';
      var day=parseDate(when);
      // A date we cannot read is NAMED rather than guessed at, so a bad cell
      // shows up as a bad cell instead of the event never appearing.
      if(!day){ if(when) bad.push(title); continue; }
      if(day<now) continue;
      var details=at.details!==undefined?(c[at.details]||''):'';
      (byDay[day]=byDay[day]||[]).push({
        title:title,
        // A Details cell repeating the Title renders the same line twice.
        details:details===title?'':details,
        color:colourFor(at.color!==undefined?c[at.color]:'')
      });
    }
    var out=[], days=Object.keys(byDay).sort();
    if(bad.length)
      out.push('<div class="rerr">Could not read the date for: '+
               esc(bad.join(', '))+'</div>');
    if(unknown.length)
      out.push('<div class="rerr">Column not recognised: '+
               esc(unknown.join(', '))+'</div>');
    if(!days.length)
      return out.join('')+'<div class="cnone">Nothing coming up.</div>';
    days.forEach(function(day){
      var near=urgency(day,now);
      out.push('<div class="cday'+(near?' '+near:'')+'">'+
               '<h2>'+esc(heading(day,now))+'</h2>');
      byDay[day].sort(function(a,b){
        return a.title<b.title?-1:a.title>b.title?1:0;
      }).forEach(function(ev){
        var col=ev.color;
        out.push('<div class="cev'+(col?' tint':'')+'"'+
          (col?' style="--tint:'+col+';--wash:'+washOf(col)+'"':'')+
          '><span class="t">'+esc(ev.title)+'</span>'+
          (ev.details?'<span class="s">'+esc(ev.details)+'</span>':'')+
          '</div>');
      });
      out.push('</div>');
    });
    return out.join('');
  }

  var scratch=document.createElement('div'), busy=false;
  // Compared before assigning, so an unchanged list -- which is almost every
  // refresh -- does not blow away the scroll position or restart a transition.
  function paint(html){
    scratch.innerHTML=html;
    if(scratch.innerHTML!==body.innerHTML) body.innerHTML=scratch.innerHTML;
  }
  function url(){
    // headers=1 for the same reason CSV_URL carries it: without it gviz
    // GUESSES how many leading rows are the header and space-joins them into
    // one, at which point every column lookup here misses.
    return 'https://docs.google.com/spreadsheets/d/'+SHEET+
           '/gviz/tq?tqx=out:csv&headers=1&sheet='+encodeURIComponent(TAB)+
           '&_='+Date.now();
  }
  function refresh(){
    if(busy) return;
    busy=true;
    fetch(url(),{cache:'no-store'})
      .then(function(r){ if(!r.ok) throw new Error(r.status); return r.text(); })
      .then(function(t){
        var html=build(t);
        if(html!==null) paint(html);
      })
      .catch(function(){})        // keep the baked list; it is not wrong
      .then(function(){ busy=false; });
  }

  refresh();
  document.addEventListener('visibilitychange',function(){
    if(document.visibilityState==='visible') refresh();
  });
})();
"""


def page_js(data):
    import json
    return (JS.replace("%%SHEET%%", json.dumps(data.get("sheet") or ""))
              .replace("%%TAB%%", json.dumps(data.get("tab") or TAB))
              .replace("%%COLORS%%", json.dumps(COLORS))
              .replace("%%SOON%%", json.dumps(SOON_DAYS))
              .replace("%%NEAR%%", json.dumps(NEAR_DAYS)))


def build(today=None, cfg=None, record=True):
    today = dt.date.fromisoformat(today) if isinstance(today, str) else today
    today = today or dt.date.today()
    if cfg is None:
        import watch          # load_config lives there; reminders does the same
        cfg = watch.load_config()
    sheet = (cfg.get("reminders_sheet") or "").strip()
    tab = cfg.get("church_tab", TAB)
    # sheet and tab are carried even on the error paths: page_js needs them to
    # wire up the refresh, and the refresh is most useful precisely when the
    # build-time read failed.
    blank = {"today": today, "days": [], "unreadable": [], "unknown": [],
             "sheet": sheet, "tab": tab}
    if not sheet:
        return dict(blank, error="no reminders_sheet in config.json")
    try:
        text = fetch(sheet, tab)
        days, bad, unknown = read_events(text, today)
    except Exception as exc:      # a bad tab must not take the whole page down
        return dict(blank, error="%s" % exc)
    return dict(blank, days=days, unreadable=bad, unknown=unknown, error=None)


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
