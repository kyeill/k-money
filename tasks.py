"""The Tasks tab: dated to-dos that roll over until they are done.

Deliberately NOT more columns on the Reminders sheet, because it is a different
kind of thing. A reminder is a SCHEDULE -- a rule that fires on the days its
cadence names, and an unticked one simply does not come back tomorrow. A task is
an OPEN ITEM -- it has a due date and stays open until it is closed, appearing
every day from its due date onward. Same app, different model, different tab.

    Task | Due | Category | Done

Every column is found by NAME. A due date is required: the point of the tab is
that everything on today's list is something he meant to do today, and an
undated backlog living at the bottom of every day would break that.

Ticking a task and adding one both write to the Sheet through the Apps Script
web app, the same path the reminder checkboxes already use -- so the Sheet is
the storage and he never has to open it.
"""

import csv
import datetime as dt
import io
import os

import reminders          # CSV_URL and SheetError -- the plumbing is shared
import ui

KEY = "tasks"
LABEL = "Tasks"

TAB = "Tasks"
REQUIRED = ["task", "due"]
OPTIONAL = ["category", "done"]

# Categories colour themselves. Assigning them by hand in config would mean a
# commit every time a new one is typed on his phone, which is exactly the
# friction this tab exists to remove -- so a name maps to a colour the same way
# every time, and config only has to name the exceptions.
CATEGORY_COLORS = ("blue", "green", "purple", "teal",
                   "pink", "amber", "brown", "red")


def category_color(name, overrides=None):
    """A stable colour for a category name, or None when it has none.

    Deterministic rather than first-seen: a colour picked in arrival order
    would change the moment a row was added above another, and the tab would
    quietly recolour itself.
    """
    name = (name or "").strip()
    if not name:
        return None
    override = (overrides or {}).get(name.lower())
    if override:
        return ui.COLORS.get(override.lower(), override)
    total = sum(ord(ch) for ch in name.lower())
    return ui.COLORS[CATEGORY_COLORS[total % len(CATEGORY_COLORS)]]


def task_key(task, due):
    """"Call the dentist@2026-09-15" -- the identity of one task.

    Built identically here and in the Apps Script. Row position cannot be the
    key: sorting the sheet would repoint every tick at the wrong row.
    """
    return "%s@%s" % (task, due.isoformat() if hasattr(due, "isoformat") else due)


def layout(header):
    where, unknown = {}, []
    for i, name in enumerate(header):
        if not name:
            continue
        if name in REQUIRED + OPTIONAL:
            where.setdefault(name, i)
        else:
            unknown.append(name)
    return where, [n for n in REQUIRED if n not in where], unknown


def read_tasks(text, today, overrides=None):
    """([(day, [task, ...])], undated, unknown) -- open tasks, rolled forward.

    A task shows on its due date, and on every day after until it is done. That
    is the whole point: nothing falls off the list by being ignored.
    """
    rows = list(csv.reader(io.StringIO(text or "")))
    if not rows:
        raise reminders.SheetError("the Tasks tab is empty")
    header = [h.strip().lower().split()[0] if h.strip() else "" for h in rows[0]]
    where, missing, unknown = layout(header)
    if missing:
        raise reminders.SheetError(
            "no %s column; the headings read %r"
            % (" or ".join(missing), [h for h in header if h]))

    def cell(cells, name):
        i = where.get(name)
        return cells[i] if i is not None and i < len(cells) else ""

    by_day, undated = {}, []
    for line in rows[1:]:
        cells = [c.strip() for c in line]
        title = cell(cells, "task")
        if not title:
            continue
        # Any mark at all closes a task. It is a spreadsheet cell he may tick,
        # type an x into, or let the app stamp with a date.
        if cell(cells, "done"):
            continue
        due = ui.sheet_date(cell(cells, "due"))
        if due is None:
            undated.append(title)
            continue
        # THE ROLLOVER. An overdue task moves to today rather than staying on a
        # day that has gone -- silently, by his choice, so a thing dodged for a
        # fortnight sits in the list looking like anything else.
        show_on = max(due, today)
        by_day.setdefault(show_on, []).append({
            "task": title,
            "due": due,
            "key": task_key(title, due),
            "category": cell(cells, "category"),
            "color": category_color(cell(cells, "category"), overrides),
            "late": (today - due).days if due < today else 0,
        })

    days = [(day, sorted(by_day[day], key=lambda t: (t["due"], t["task"])))
            for day in sorted(by_day)]
    return days, undated, unknown


CSS = """
.tday{margin:18px 0 0}
.tday h2{font-size:12px;text-transform:uppercase;letter-spacing:.08em;
         color:var(--muted);font-weight:600;margin:0 0 7px}
label.tk{display:flex;gap:11px;align-items:center;background:var(--card);
     border:1px solid var(--line);border-left:4px solid transparent;
     border-radius:10px;padding:11px 12px;margin:6px 0;cursor:pointer;
     -webkit-tap-highlight-color:transparent}
label.tk.tint{border-left-color:var(--tint);
     background:linear-gradient(var(--wash),var(--wash)),var(--card)}
label.tk input{flex:0 0 auto;width:19px;height:19px;margin:0 1px 0 0;
               align-self:center;accent-color:var(--accent)}
.tk .tt{flex:1 1 auto;min-width:0;font-size:15px}
/* Ticked rows stay put and fade rather than vanishing under your thumb -- the
   Sheet is the record, and the row goes on the next read. */
label.tk.done .tt{opacity:.45;text-decoration:line-through}
.tk .cat{flex:0 0 auto;font-size:11px;color:var(--muted);
         background:var(--chip);border-radius:5px;padding:1px 6px;
         white-space:nowrap}
.tnone{color:var(--muted);font-size:13px;padding:1px 2px 8px}
/* The add form. Collapsed to one line until it is wanted, because the tab is
   for reading first and typing second. */
#tadd{margin:2px 0 0}
#tadd summary{list-style:none;cursor:pointer;color:var(--accent);
              font-size:14px;font-weight:600;padding:7px 2px}
#tadd summary::-webkit-details-marker{display:none}
#tadd form{display:flex;flex-direction:column;gap:8px;background:var(--card);
           border:1px solid var(--line);border-radius:10px;padding:12px;
           margin:4px 0 2px}
#tadd input,#tadd button{font:inherit;border-radius:8px;
           border:1px solid var(--line);padding:9px 10px}
#tadd input{background:var(--bg);color:var(--ink);width:100%}
#tadd input::placeholder{color:var(--muted)}
#tadd .pair{display:flex;gap:8px}
#tadd .pair input{flex:1 1 0;min-width:0}
#tadd button{background:var(--accent);color:#16161a;font-weight:700;
             border-color:var(--accent);cursor:pointer}
#tadd button:disabled{opacity:.5;cursor:default}
@media (min-width:641px){
  .tday{margin:24px 0 0}
  .tday h2{font-size:13px}
  label.tk{padding:12px 14px;margin:8px 0}
  label.tk input{width:21px;height:21px}
  .tk .tt{font-size:17px}
}
"""


def _task(row):
    tint = row.get("color")
    return (
        '<label class="tk%s"%s><input type="checkbox" data-key="%s">'
        '<span class="tt">%s</span>%s</label>'
    ) % (
        " tint" if tint else "",
        ' style="--tint:%s;--wash:%s"' % (ui.esc(tint), ui.wash(tint))
        if tint else "",
        ui.esc(row["key"]),
        ui.esc(row["task"]),
        '<span class="cat">%s</span>' % ui.esc(row["category"])
        if row.get("category") else "",
    )


def render(data):
    if data.get("error"):
        return ('<div class="rerr">Could not read the Tasks tab: %s</div>'
                % ui.esc(data["error"]))
    out = ['<details id="tadd"><summary>+ Add a task</summary>'
           '<form id="tform" autocomplete="off">'
           '<input id="ttask" type="text" placeholder="What needs doing?" '
           'required maxlength="120">'
           '<div class="pair"><input id="tdue" type="date" required>'
           '<input id="tcat" type="text" placeholder="Category" maxlength="30">'
           '</div><button type="submit">Add</button></form></details>'
           '<div id="tbody">']
    out.append(body(data))
    out.append("</div>")
    return "".join(out)


def body(data):
    """The list alone. Split out because the browser repaints just this part."""
    out = []
    if data.get("undated"):
        out.append('<div class="rerr">No due date, so not shown: %s</div>'
                   % ui.esc(", ".join(data["undated"])))
    if data.get("unknown"):
        out.append('<div class="rerr">Column not recognised: %s</div>'
                   % ui.esc(", ".join(data["unknown"])))
    if data.get("missing"):
        return ("".join(out) + '<div class="tnone">No Tasks tab on the sheet '
                'yet &mdash; add one above and it will be created for you.'
                '</div>')
    if not data["days"]:
        return "".join(out) + '<div class="tnone">Nothing to do.</div>'
    for day, items in data["days"]:
        out.append('<div class="tday"><h2>%s</h2>'
                   % ui.esc(ui.day_heading(day, data["today"])))
        out.extend(_task(t) for t in items)
        out.append("</div>")
    return "".join(out)


def build(today=None, cfg=None, record=True):
    today = dt.date.fromisoformat(today) if isinstance(today, str) else today
    today = today or dt.date.today()
    if cfg is None:
        import watch
        cfg = watch.load_config()
    sheet = (cfg.get("reminders_sheet") or "").strip()
    tab = cfg.get("tasks_tab", TAB)
    overrides = {k.lower(): v for k, v in (cfg.get("task_colors") or {}).items()}
    blank = {"today": today, "days": [], "undated": [], "unknown": [],
             "sheet": sheet, "tab": tab, "overrides": overrides,
             "webapp": cfg.get("reminders_webapp", "")}
    if not sheet:
        return dict(blank, error="no reminders_sheet in config.json")
    try:
        days, undated, unknown = read_tasks(fetch(sheet, tab), today, overrides)
    except reminders.SheetError as exc:
        # Before the tab exists, Google hands back the FIRST tab and the header
        # check refuses it -- correct, but "no task column" is a poor first
        # impression. The add form creates the tab, so say that instead.
        if "no task" in str(exc) or "empty" in str(exc):
            return dict(blank, error=None, missing=True)
        return dict(blank, error="%s" % exc)
    except Exception as exc:
        return dict(blank, error="%s" % exc)
    return dict(blank, days=days, undated=undated, unknown=unknown, error=None)


def fetch(sheet, tab):
    """KMONEY_TASKS_CSV points at a local file, for tests and --fixtures."""
    local = os.environ.get("KMONEY_TASKS_CSV")
    if local:
        if not os.path.exists(local):
            return ""
        with open(local, encoding="utf-8") as fh:
            return fh.read()
    import requests
    r = requests.get(reminders.CSV_URL % sheet + "&sheet=" + tab, timeout=20)
    r.raise_for_status()
    return r.text


JS = """
(function(){
  var SHEET=%%SHEET%%, TAB=%%TAB%%, WEBAPP=%%WEBAPP%%;
  var pane=document.querySelector('section[data-k="tasks"]');
  if(!pane||!SHEET) return;
  var body=pane.querySelector('#tbody');
  var form=pane.querySelector('#tform');
  var box=pane.querySelector('#tadd');

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

  // Ticks and adds are fire-and-forget, so for a few seconds the Sheet does not
  // agree yet. PENDING covers that window, exactly as the reminders do.
  var PENDING={};
  try{ PENDING=JSON.parse(localStorage.getItem('tdone')||'{}'); }catch(e){}
  function remember(key){
    PENDING[key]=Date.now();
    try{ localStorage.setItem('tdone',JSON.stringify(PENDING)); }catch(e){}
  }
  function closed(key){
    var at=PENDING[key];
    if(!at) return false;
    if(Date.now()-at>12e4){ delete PENDING[key]; return false; }
    return true;
  }

  // A task he just added is not in the Sheet's CSV yet: Google's export lags a
  // write by a few seconds, so re-reading straight after an add returns the
  // list WITHOUT it. Showing nothing then reads as "it did not save", which is
  // the one thing this tab must never do. So a new task is held here and drawn
  // immediately, and dropped as soon as the Sheet catches up.
  var ADDED=[];
  try{ ADDED=JSON.parse(localStorage.getItem('tadded')||'[]'); }catch(e){}
  function keepAdded(){
    var cut=Date.now()-3e5;      // five minutes is long past any export lag
    ADDED=ADDED.filter(function(a){ return a.at>cut; });
    try{ localStorage.setItem('tadded',JSON.stringify(ADDED)); }catch(e){}
  }
  function noteAdded(task,due,cat){
    ADDED.push({task:task,due:due,cat:cat,at:Date.now()});
    keepAdded();
  }

  function rows(text){
    // A minimal CSV reader: quoted fields with doubled quotes inside, which is
    // everything the gviz endpoint emits.
    var out=[], row=[], field='', quoted=false;
    for(var i=0;i<text.length;i++){
      var c=text[i];
      if(quoted){
        if(c==='"'){ if(text[i+1]==='"'){ field+='"'; i++; } else quoted=false; }
        else field+=c;
      } else if(c==='"') quoted=true;
      else if(c===','){ row.push(field); field=''; }
      else if(c==='\\n'){ row.push(field); out.push(row); row=[]; field=''; }
      else if(c!=='\\r') field+=c;
    }
    if(field||row.length){ row.push(field); out.push(row); }
    return out;
  }

  function parseDate(text){
    text=(text||'').trim();
    var m=text.match(/^(\\d{4})-(\\d{2})-(\\d{2})$/);
    if(m) return m[1]+'-'+m[2]+'-'+m[3];
    m=text.match(/^(\\d{1,2})\\/(\\d{1,2})\\/(\\d{2,4})$/);
    if(!m) return null;
    var y=Number(m[3]); if(y<100) y+=2000;
    return y+'-'+('0'+m[1]).slice(-2)+'-'+('0'+m[2]).slice(-2);
  }

  var PALETTE=%%PALETTE%%, OVERRIDES=%%OVERRIDES%%;
  function colourFor(name){
    name=(name||'').trim();
    if(!name) return null;
    var over=OVERRIDES[name.toLowerCase()];
    if(over) return over;
    var total=0, low=name.toLowerCase();
    for(var i=0;i<low.length;i++) total+=low.charCodeAt(i);
    return PALETTE[total%PALETTE.length];
  }
  function washOf(hex){
    var r=parseInt(hex.substr(1,2),16), g=parseInt(hex.substr(3,2),16),
        b=parseInt(hex.substr(5,2),16);
    return 'rgba('+r+','+g+','+b+',0.13)';
  }

  function heading(day, now){
    if(day===now) return 'Today';
    var d=new Date(day+'T12:00:00');
    var days=['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
    var mon=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    return days[d.getDay()]+', '+mon[d.getMonth()]+' '+d.getDate();
  }

  function build(text){
    var lines=rows(text);
    if(!lines.length) return '';
    var head=lines[0].map(function(h){
      h=(h||'').trim().toLowerCase(); return h.split(' ')[0];
    });
    var at={};
    ['task','due','category','done'].forEach(function(n){
      var i=head.indexOf(n); if(i>=0) at[n]=i;
    });
    if(at.task===undefined||at.due===undefined) return null;
    var now=today(), byDay={}, seen={};
    for(var i=1;i<lines.length;i++){
      var c=lines[i].map(function(v){ return (v||'').trim(); });
      var title=c[at.task]||'';
      if(!title) continue;
      if(at.done!==undefined && c[at.done]) continue;
      var due=parseDate(c[at.due]);
      if(!due) continue;
      var key=title+'@'+due;
      seen[key]=true;
      if(closed(key)) continue;
      var show=due<now?now:due;
      (byDay[show]=byDay[show]||[]).push({
        task:title, due:due, key:key,
        cat:(at.category!==undefined?c[at.category]:'')||''
      });
    }
    // Anything added in the last few minutes that the export has not caught up
    // with. Once it appears in the CSV it is dropped from here, so it can never
    // be drawn twice.
    keepAdded();
    ADDED = ADDED.filter(function(a){ return !seen[a.task+'@'+a.due]; });
    try{ localStorage.setItem('tadded',JSON.stringify(ADDED)); }catch(e){}
    ADDED.forEach(function(a){
      var key=a.task+'@'+a.due;
      if(closed(key)) return;
      var show=a.due<now?now:a.due;
      (byDay[show]=byDay[show]||[]).push({
        task:a.task, due:a.due, key:key, cat:a.cat||''
      });
    });
    var out=[], days=Object.keys(byDay).sort();
    if(!days.length) return '<div class="tnone">Nothing to do.</div>';
    days.forEach(function(day){
      out.push('<div class="tday"><h2>'+esc(heading(day,now))+'</h2>');
      byDay[day].sort(function(a,b){
        return a.due<b.due?-1:a.due>b.due?1:(a.task<b.task?-1:1);
      }).forEach(function(t){
        var col=colourFor(t.cat);
        out.push('<label class="tk'+(col?' tint':'')+'"'+
          (col?' style="--tint:'+col+';--wash:'+washOf(col)+'"':'')+
          '><input type="checkbox" data-key="'+esc(t.key)+'">'+
          '<span class="tt">'+esc(t.task)+'</span>'+
          (t.cat?'<span class="cat">'+esc(t.cat)+'</span>':'')+'</label>');
      });
      out.push('</div>');
    });
    return out.join('');
  }

  var scratch=document.createElement('div'), busy=false, lastCsv=null;
  function redraw(){
    if(lastCsv===null) return;
    var html=build(lastCsv);
    if(html!==null) paint(html);
  }
  function paint(html){
    scratch.innerHTML=html;
    if(scratch.innerHTML!==body.innerHTML) body.innerHTML=scratch.innerHTML;
  }
  function url(){
    return 'https://docs.google.com/spreadsheets/d/'+SHEET+
           '/gviz/tq?tqx=out:csv&sheet='+encodeURIComponent(TAB)+
           '&_='+Date.now();
  }
  function refresh(){
    if(busy) return;
    busy=true;
    fetch(url(),{cache:'no-store'})
      .then(function(r){ if(!r.ok) throw new Error(r.status); return r.text(); })
      .then(function(t){
        var html=build(t);
        if(html!==null){ lastCsv=t; paint(html); }
      })
      .catch(function(){})          // keep the baked list; it is not wrong
      .then(function(){ busy=false; });
  }

  pane.addEventListener('change',function(e){
    var cb=e.target;
    if(!cb||cb.type!=='checkbox'||!cb.dataset.key) return;
    var key=cb.dataset.key;
    cb.closest('label').classList.add('done');
    remember(key);
    if(!WEBAPP) return;
    fetch(WEBAPP+'?action=task&key='+encodeURIComponent(key)+'&done=1',
          {mode:'no-cors',cache:'no-store'}).catch(function(){});
    // Long enough to see it strike through, short enough not to feel stuck.
    setTimeout(refresh, 1200);
  });

  if(form){
    var due=pane.querySelector('#tdue');
    if(due&&!due.value) due.value=today();
    form.addEventListener('submit',function(e){
      e.preventDefault();
      var task=pane.querySelector('#ttask').value.trim();
      var when=pane.querySelector('#tdue').value;
      var cat=pane.querySelector('#tcat').value.trim();
      if(!task||!when||!WEBAPP) return;
      var btn=form.querySelector('button');
      btn.disabled=true; btn.textContent='Adding\\u2026';
      fetch(WEBAPP+'?action=addtask&task='+encodeURIComponent(task)+
            '&due='+encodeURIComponent(when)+'&cat='+encodeURIComponent(cat),
            {mode:'no-cors',cache:'no-store'}).catch(function(){});
      // Drawn from what he typed, straight away -- waiting on the Sheet is
      // exactly what made an add look like it had failed.
      noteAdded(task, when, cat);
      pane.querySelector('#ttask').value='';
      pane.querySelector('#tcat').value='';
      btn.disabled=false; btn.textContent='Add';
      if(box) box.open=false;
      redraw();
      // Then confirm, over a window wide enough for the export to catch up.
      [1500, 4000, 9000].forEach(function(ms){ setTimeout(refresh, ms); });
    });
  }

  refresh();
  document.addEventListener('visibilitychange',function(){
    if(document.visibilityState==='visible') refresh();
  });
})();
"""


def page_js(data):
    import json
    palette = [ui.COLORS[name] for name in CATEGORY_COLORS]
    overrides = {}
    for name, value in (data.get("overrides") or {}).items():
        overrides[name] = ui.COLORS.get(str(value).lower(), value)
    return (JS.replace("%%SHEET%%", json.dumps(data.get("sheet") or ""))
              .replace("%%TAB%%", json.dumps(data.get("tab") or TAB))
              .replace("%%WEBAPP%%", json.dumps(data.get("webapp") or ""))
              .replace("%%PALETTE%%", json.dumps(palette))
              .replace("%%OVERRIDES%%", json.dumps(overrides)))


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    data = build()
    if data["error"]:
        raise SystemExit("error: " + data["error"])
    total = 0
    for day, items in data["days"]:
        print("%s" % ui.day_heading(day, data["today"]))
        for t in items:
            total += 1
            late = "  (%d day%s late)" % (t["late"], "" if t["late"] == 1 else "s") \
                if t["late"] else ""
            print("    %-44s %-12s %s" % (t["task"][:44], t["category"], late))
    print("\n%d open task(s) across %d day(s)" % (total, len(data["days"])))
