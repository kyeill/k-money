"""The Reminders tab: what is due in the next seven days.

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

import ui

KEY = "reminders"
LABEL = "Reminders"

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_URL = ("https://docs.google.com/spreadsheets/d/%s/gviz/tq?tqx=out:csv")
DAYS_SHOWN = 7

# Monday-first, matching both the Sheet's column order and date.weekday().
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
NTH = {"1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5, "last": -1}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
QUARTERLY = {1, 4, 7, 10}

# The header the Sheet must have. Checked because asking Google for a tab that
# does not exist silently returns the FIRST tab instead of erroring, so a
# reordered or renamed sheet would otherwise be parsed as if it were this one.
EXPECT = ["title", "time"] + [d.lower() for d in WEEKDAYS] + \
         ["nth", "weekday", "months"]


class SheetError(Exception):
    pass


# ------------------------------------------------------------------ input

def fetch_csv(sheet_id):
    """KMONEY_REMINDERS_CSV points at a local file instead, for tests and for
    `site.py --fixtures`."""
    local = os.environ.get("KMONEY_REMINDERS_CSV")
    if local:
        with open(local, encoding="utf-8") as fh:
            return fh.read()
    import requests
    r = requests.get(CSV_URL % sheet_id, timeout=20)
    r.raise_for_status()
    return r.text


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


def read_rules(text):
    """CSV -> rules. Raises SheetError if the header is not what we expect."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise SheetError("the sheet is empty")
    header = [h.strip().lower() for h in rows[0]]
    if header[:len(EXPECT)] != EXPECT:
        raise SheetError("unexpected header %r; expected %r" % (header, EXPECT))

    rules = []
    for line in rows[1:]:
        cells = [c.strip() for c in line] + [""] * (len(EXPECT) - len(line))
        title = cells[0]
        at = parse_time(cells[1])
        # A time is required, by his call: a reminder with no time cannot fire.
        if not title or not at:
            continue
        nth = NTH.get(cells[9].strip().lower())
        weekday = cells[10].strip().title()
        monthly = nth is not None and weekday != ""
        rules.append({
            "title": title,
            "at": at,
            # Any non-empty mark counts, so x / X / TRUE / a tick all work.
            "days": {i for i, d in enumerate(WEEKDAYS) if cells[2 + i]},
            "nth": nth,
            "weekday": weekday,
            "months": parse_months(cells[11]),
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
    if rule["monthly"]:
        # A row carrying both a monthly rule and weekly ticks is monthly. One
        # row, one schedule -- a row firing on both would be unreadable later.
        if day.month not in rule["months"]:
            return False
        if rule["weekday"] == "Day":
            return nth_day(day.year, day.month, rule["nth"]) == day
        if rule["weekday"] not in WEEKDAYS:
            return False
        target = WEEKDAYS.index(rule["weekday"])
        return nth_weekday(day.year, day.month, target, rule["nth"]) == day
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
.rem .rt{flex:0 0 auto;width:74px;font-variant-numeric:tabular-nums;
         font-weight:600;font-size:13.5px}
.rem .rn{flex:1 1 auto;min-width:0;font-size:15px;
         overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
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
  .rem .rt{width:88px;font-size:15px}
  .rem .rn{font-size:17px}
  .rfoot{font-size:13px}
}
"""

# The same rules again, in the browser, so a pull-down re-reads the Sheet
# instead of showing whatever the 6am build baked. Kept deliberately close to
# the Python above; selftest and the browser check compare their output.
JS = """
(function(){
  var SHEET=%%SHEET%%, DAYS=%%DAYS%%;
  var WD=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
  var NTH={'1st':1,'2nd':2,'3rd':3,'4th':4,'5th':5,'last':-1};
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
    var rules=[],i;
    for(i=1;i<rows.length;i++){
      var c=rows[i].map(function(x){return (x||'').trim();});
      while(c.length<12) c.push('');
      var at=parseTime(c[1]);
      if(!c[0]||!at) continue;
      var nth=NTH[(c[9]||'').trim().toLowerCase()];
      var wd=(c[10]||'').trim();
      wd=wd?wd.charAt(0).toUpperCase()+wd.slice(1).toLowerCase():'';
      var days=[],d;
      for(d=0;d<7;d++) if(c[2+d]) days.push(d);
      rules.push({title:c[0],at:at,days:days,nth:(nth===undefined?null:nth),
                  weekday:wd,months:parseMonths(c[11]),
                  monthly:(nth!==undefined&&wd!=='')});
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
    if(r.monthly){
      if(r.months.indexOf(m)<0) return false;
      if(r.weekday==='Day'){
        var want=(r.nth===-1)?daysIn(y,m):r.nth;
        return want>=1&&want<=daysIn(y,m)&&want===dd;
      }
      var t=WD.indexOf(r.weekday);
      if(t<0) return false;
      return nthWeekday(y,m,t,r.nth)===dd;
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

  function build(rules,today){
    var out=[],i,step;
    for(step=0;step<DAYS;step++){
      var day=new Date(today.getFullYear(),today.getMonth(),today.getDate()+step);
      var due=rules.filter(function(r){return firesOn(r,day);});
      due.sort(function(a,b){
        return (a.at[0]-b.at[0])||(a.at[1]-b.at[1])||
               (a.title.toLowerCase()<b.title.toLowerCase()?-1:1); });
      var label=step===0?'Today':(step===1?'Tomorrow':
        day.toLocaleDateString(undefined,{weekday:'long',month:'short',day:'numeric'}));
      out.push('<div class="rday"><h2>'+esc(label)+' <b>'+due.length+'</b></h2>');
      if(!due.length) out.push('<div class="rnone">Nothing.</div>');
      for(i=0;i<due.length;i++)
        out.push('<div class="rem"><span class="rt">'+esc(clock(due[i].at))+
                 '</span><span class="rn">'+esc(due[i].title)+'</span></div>');
      out.push('</div>');
    }
    return out.join('');
  }
  window.__remBuild=function(text,today){ return build(readRules(text),today); };

  var pane=document.querySelector('section[data-k="reminders"]');
  if(!pane) return;
  var body=pane.querySelector('#rbody'), note=pane.querySelector('#rpull');
  var busy=false;
  function refresh(){
    if(busy||!SHEET) return;
    busy=true;
    // The Sheet allows cross-origin reads, which is the whole reason a
    // pull-down can show an edit made a minute ago rather than this morning's
    // build. cache-busted, or the browser hands back its own copy.
    fetch('https://docs.google.com/spreadsheets/d/'+SHEET+
          '/gviz/tq?tqx=out:csv&_='+Date.now(),{cache:'no-store'})
      .then(function(r){ if(!r.ok) throw new Error(r.status); return r.text(); })
      .then(function(t){ body.innerHTML=build(readRules(t),new Date()); })
      .catch(function(){})            // keep the baked list; it is not wrong
      .then(function(){ busy=false; });
  }
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


def day_label(day, today):
    delta = (day - today).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Tomorrow"
    return day.strftime("%A, %b ") + str(day.day)


def render(data):
    if data.get("error"):
        return ('<div class="rerr">Could not read the reminders sheet: %s</div>'
                % ui.esc(data["error"]))
    out = ['<div id="rpull">Release to refresh</div><div id="rbody">']
    for day, due in data["days"]:
        out.append('<div class="rday"><h2>%s <b>%d</b></h2>'
                   % (ui.esc(day_label(day, data["today"])), len(due)))
        if not due:
            out.append('<div class="rnone">Nothing.</div>')
        for rule in due:
            out.append('<div class="rem"><span class="rt">%s</span>'
                       '<span class="rn">%s</span></div>'
                       % (ui.esc(clock(rule["at"])), ui.esc(rule["title"])))
        out.append("</div>")
    out.append("</div>")
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
        rules = read_rules(fetch_csv(sheet))
    except Exception as exc:          # a bad sheet must not kill the build
        return {"today": today, "days": [], "count": 0,
                "error": "%s" % exc, "sheet": sheet}
    return {"today": today, "days": upcoming(rules, today), "sheet": sheet,
            "count": len(rules), "error": None}


def page_js(data):
    return (JS.replace("%%SHEET%%", '"%s"' % data.get("sheet", ""))
              .replace("%%DAYS%%", str(DAYS_SHOWN)))


if __name__ == "__main__":
    d = build()
    if d["error"]:
        raise SystemExit("error: " + d["error"])
    for day, due in d["days"]:
        print("%s (%d)" % (day_label(day, d["today"]), len(due)))
        for r in due:
            print("    %-9s %s" % (clock(r["at"]), r["title"]))
    print("\n%d reminder(s) in the sheet" % d["count"])
