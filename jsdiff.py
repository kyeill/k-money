"""Does a tab's browser copy paint what its Python copy paints?

Three tabs re-read their Sheet in the browser, because the page is baked once a
morning and the Sheet is edited all day. That means the rules exist twice -- in
Python and in JS -- and the second copy is only worth having if it agrees with
the first. Nothing else in this project checks that; a text assertion over the
JS source proves the code is *present*, not that it is *right*.

So this runs the real JS under node against a CSV and diffs the HTML against
what `render` produced from the same CSV.

    python jsdiff.py              every case, as a table
    python jsdiff.py -v           print the HTML of any case that differs

`selftest.py` calls `check()` and skips quietly when node is not installed, so
this is also the thing to extend when the Church rules change.

Two things are covered. **Church** is diffed as HTML, since its browser copy
exists to paint. **Reminders** is diffed as a CALENDAR -- which day each rule
fires on over a year -- because that is what its three copies have to agree
about, and because Reminders has a third implementation: `apps-script/Code.js`
is what actually sends the notification to his phone, so a rule it reads
differently is a buzz at the wrong time, or none at all.

The Active tab is not covered. It would fit the same harness and does not have
one, which is a gap rather than a decision.
"""

import datetime as dt
import difflib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

import church
import reminders

HERE = os.path.dirname(os.path.abspath(__file__))

# Windows installs node outside PATH as often as not, and this is the one path
# it uses; `shutil.which` covers everywhere else.
WINDOWS_NODE = r"C:\Program Files\nodejs\node.exe"


def node():
    """The node binary, or None -- in which case callers skip rather than fail."""
    found = shutil.which("node")
    if found:
        return found
    return WINDOWS_NODE if os.path.exists(WINDOWS_NODE) else None


TODAY = dt.date(2026, 8, 30)


def _iso(n):
    return (TODAY + dt.timedelta(days=n)).isoformat()


def _slash(n):
    """The locale form Sheets exports -- 9/8/26, no leading zeros.

    Written out rather than with strftime, which has no %-m on Windows.
    """
    day = TODAY + dt.timedelta(days=n)
    return "%d/%d/%02d" % (day.month, day.day, day.year % 100)


def _csv(*lines):
    return "\n".join(('"Title","Details","Date","Color"',) + lines)


# Each case is a place the two copies could drift apart without anyone noticing
# until a Sunday morning.
CASES = {
    "the fixture": None,          # filled in below, from fixtures/church.csv

    "quotes, ampersands and angle brackets": _csv(
        # The two escapers genuinely disagree here -- html.escape writes
        # &#x27; and the browser copy &#39; -- which is why `canon` exists.
        '"Men\'s Breakfast & <Prayer>","Bring a friend","%s","Orange"' % _iso(0),
    ),
    "both urgency boundaries, and one day past": _csv(
        '"Seven days out","","%s","Blue"' % _iso(7),
        '"Eight days out","","%s","Blue"' % _iso(8),
        '"Fourteen days out","","%s","Blue"' % _iso(14),
        '"Fifteen days out","","%s","Blue"' % _iso(15),
    ),
    "yesterday is dropped": _csv(
        '"Gone by","","%s","Red"' % _iso(-1),
        '"Still here","","%s","Red"' % _iso(1),
    ),
    "a reordered header with columns we do not know": "\n".join([
        '"Notes","Color ","Date","Title","Rota"',
        '"ignored","#4488FF","%s","Upper case hex",""' % _iso(3),
        '"ignored","chartreuse","%s","A colour that is not in the palette",""'
        % _iso(4),
        '"ignored","","%s","No colour at all",""' % _iso(5),
    ]),
    "a details cell repeating its title": _csv(
        '"Session Meeting","Session Meeting","%s","Gray"' % _slash(2),
    ),
    "an unreadable date is named, a missing one is not": _csv(
        '"Whenever","","soon","Blue"',
        '"No date at all","","",""',
    ),
    "a row with no title": _csv(
        '"","","%s","Blue"' % _iso(2),
        '"Real","","%s","Blue"' % _iso(2),
    ),
    "sorted within the day, and case matters the same way": _csv(
        '"Zebra","","%s",""' % _iso(6),
        '"apple","","%s",""' % _iso(6),
        '"Apple","","%s",""' % _iso(6),
    ),
    "every date form Sheets might export": _csv(
        '"Slashes, two-digit year","","%s","Red"' % _slash(1),
        '"ISO","","%s","Green"' % _iso(2),
        '"Slashes, four-digit year","","%d/%d/%d","Teal"'
        % ((TODAY + dt.timedelta(days=3)).month,
           (TODAY + dt.timedelta(days=3)).day,
           (TODAY + dt.timedelta(days=3)).year),
        '"Year first","","%d/%d/%d","Navy"'
        % ((TODAY + dt.timedelta(days=4)).year,
           (TODAY + dt.timedelta(days=4)).month,
           (TODAY + dt.timedelta(days=4)).day),
    ),
    "nothing coming up": _csv(
        '"Long gone","","%s","Red"' % _iso(-30),
    ),
}

CASES["the fixture"] = io.open(
    os.path.join(HERE, "fixtures", "church.csv"), encoding="utf-8").read()


# The IIFE wants a document and a pane; everything after `build` is wiring, so
# the DOM is stubbed and `build` -- which is module-private -- is reached by
# putting a probe in front of the one `refresh()` call that starts it all.
HARNESS = """
globalThis.__csv = %(csv)s;
globalThis.__today = %(today)s;
globalThis.document = {
  querySelector: function(){
    return { querySelector: function(){ return {innerHTML: ''}; } };
  },
  createElement: function(){ return {innerHTML: ''}; },
  addEventListener: function(){},
  visibilityState: 'hidden'
};
globalThis.fetch = function(){
  return Promise.resolve({ok: true, text: function(){
    return Promise.resolve(globalThis.__csv);
  }});
};
%(js)s
console.log(JSON.stringify({html: globalThis.__html}));
"""

PROBE = "  globalThis.__html = build(globalThis.__csv);\n  refresh();\n"


def browser(csv, binary, workdir):
    """What church.JS paints, run for real."""
    js = church.page_js({"sheet": "S", "tab": "Church"})
    assert "  refresh();\n" in js, "the JS no longer ends in a refresh() call"
    js = js.replace("  refresh();\n", PROBE, 1)
    # Pinned, or the comparison depends on the day it is run.
    old = "function today(){ return iso(new Date()); }"
    assert old in js, "the JS no longer takes today from iso(new Date())"
    js = js.replace(old, "function today(){ return globalThis.__today; }", 1)

    path = os.path.join(workdir, "church.probe.js")
    io.open(path, "w", encoding="utf-8", newline="\n").write(
        HARNESS % {"csv": json.dumps(csv),
                   "today": json.dumps(TODAY.isoformat()), "js": js})
    done = subprocess.run([binary, path], capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError("node refused the JS:\n" + done.stderr.strip())
    return json.loads(done.stdout.strip().splitlines()[-1])["html"]


def python(csv):
    """What church.render paints, from the same CSV."""
    days, bad, unknown = church.read_events(csv, TODAY)
    return church._body({"today": TODAY, "days": days, "unreadable": bad,
                         "unknown": unknown, "error": None})


def canon(html):
    """The one difference that is not a difference.

    `html.escape` writes an apostrophe as `&#x27;` and the browser copy writes
    `&#39;`. Both decode to the same character, and `paint()` compares
    innerHTML *after* the browser has normalised them -- so this can cause
    neither a visible difference nor a repaint loop.
    """
    return html.replace("&#x27;", "&#39;")


def check():
    """[(case, agreed, python_html, browser_html)], or None without node."""
    binary = node()
    if not binary:
        return None
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, csv in CASES.items():
            want, got = python(csv), browser(csv, binary, tmp)
            out.append((name, canon(want) == canon(got), want, got))
    return out


# =========================================================== the Reminders tab
#
# Three implementations, not two. The page has Python and its browser copy;
# `apps-script/Code.js` is the one that sends the notification, and it reads
# the same Sheet by itself. A rule the three disagree about is a reminder that
# shows up on the page and never reaches his phone, or the reverse.
#
# They are compared as a CALENDAR: for every rule, every day it fires on over a
# year. A schedule is the whole meaning of a rule, so nothing less would do.

REMINDERS_CSV = os.path.join(HERE, "fixtures", "reminders.csv")

# A year from a fixed Monday, long enough that every monthly, quarterly and
# every-n-weeks rule comes round several times and a leap-year February is in
# range.
CAL_START, CAL_DAYS = dt.date(2026, 10, 19), 420

# The browser copy exports readRules and firesOn on `window` ABOVE its pane
# check, so it loads with no DOM: querySelector returns null, the IIFE returns
# there, and the hooks are already set. None of the page has to be faked.
BROWSER_HARNESS = """
globalThis.window = globalThis;
globalThis.document = { querySelector: function(){ return null; } };
%(js)s
var two = function(n){ return (n < 10 ? '0' : '') + n; };
var rules = window.__remRules(%(csv)s), out = {};
for (var i = 0; i < rules.length; i++) {
  var when = [];
  for (var step = 0; step < %(days)d; step++) {
    var day = new Date(%(y)d, %(m)d - 1, %(d)d + step, 12);
    if (window.__remFires(rules[i], day)) {
      when.push(day.getFullYear() + '-' + two(day.getMonth() + 1) + '-' +
                two(day.getDate()));
    }
  }
  out[rules[i].title] = when;
}
console.log(JSON.stringify(out));
"""

# Code.js reads the Sheet itself, so the stubs are Apps Script's own globals.
# Only what readRules and firesOn actually touch.
SCRIPT_HARNESS = """
globalThis.__grid = %(grid)s;
var SpreadsheetApp = {
  getActiveSpreadsheet: function(){
    var sheet = {
      getDataRange: function(){
        return { getDisplayValues: function(){ return globalThis.__grid; } };
      }
    };
    return { getSheetByName: function(){ return sheet; },
             getSheets: function(){ return [sheet]; } };
  }
};
var Utilities = {
  formatDate: function(date, tz, fmt){
    // The real one works in TZ. Every date this harness passes was built in
    // local time at midday, so reading the local parts back is the same
    // answer without pulling in a timezone database.
    var two = function(n){ return (n<10?'0':'')+n; };
    if(fmt === 'yyyy') return String(date.getFullYear());
    if(fmt === 'MM') return two(date.getMonth()+1);
    if(fmt === 'dd') return two(date.getDate());
    throw new Error('unexpected format ' + fmt);
  }
};
var PropertiesService = {
  getScriptProperties: function(){
    return { getProperty: function(){ return null; },
             setProperty: function(){}, deleteProperty: function(){} };
  }
};
var Session = { getScriptTimeZone: function(){ return 'America/New_York'; } };
var UrlFetchApp = { fetch: function(){ throw new Error('no network here'); } };
var Logger = { log: function(){} };
%(js)s
var __rules = readRules(), __out = {};
for (var i = 0; i < __rules.length; i++) {
  var when = [];
  for (var step = 0; step < %(days)d; step++) {
    var day = new Date(%(y)d, %(m)d - 1, %(d)d + step, 12);
    if (firesOn(__rules[i], day)) {
      var two = function(n){ return (n<10?'0':'')+n; };
      when.push(day.getFullYear()+'-'+two(day.getMonth()+1)+'-'+
                two(day.getDate()));
    }
  }
  __out[__rules[i].title] = when;
}
console.log(JSON.stringify(__out));
"""


def _calendar_python(csv):
    out = {}
    for rule in reminders.read_rules(csv):
        out[rule["title"]] = [
            (CAL_START + dt.timedelta(days=n)).isoformat()
            for n in range(CAL_DAYS)
            if reminders.fires_on(rule, CAL_START + dt.timedelta(days=n))]
    return out


def _run(binary, workdir, name, source):
    path = os.path.join(workdir, name)
    io.open(path, "w", encoding="utf-8", newline="\n").write(source)
    done = subprocess.run([binary, path], capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError("node refused %s:\n%s" % (name, done.stderr.strip()))
    return json.loads(done.stdout.strip().splitlines()[-1])


def _calendar_browser(csv, binary, workdir):
    js = reminders.page_js({"sheet": "S", "webapp": ""})
    for hook in ("window.__remRules", "window.__remFires"):
        assert hook in js, "the browser copy no longer exports " + hook
    return _run(binary, workdir, "reminders.browser.js",
                BROWSER_HARNESS % {"csv": json.dumps(csv), "js": js,
                                   "days": CAL_DAYS, "y": CAL_START.year,
                                   "m": CAL_START.month, "d": CAL_START.day})


def _calendar_script(csv, binary, workdir):
    import csv as csvmod
    grid = list(csvmod.reader(io.StringIO(csv)))
    width = max(len(r) for r in grid)
    grid = [r + [""] * (width - len(r)) for r in grid]
    js = io.open(os.path.join(HERE, "apps-script", "Code.js"),
                 encoding="utf-8").read()
    return _run(binary, workdir, "reminders.script.js",
                SCRIPT_HARNESS % {"grid": json.dumps(grid), "js": js,
                                  "days": CAL_DAYS, "y": CAL_START.year,
                                  "m": CAL_START.month, "d": CAL_START.day})


def check_reminders(csv=None):
    """[(rule, agreed, note)], or None without node.

    Every rule in the fixture, its firing calendar compared across Python, the
    browser copy and the Apps Script.
    """
    binary = node()
    if not binary:
        return None
    if csv is None:
        csv = io.open(REMINDERS_CSV, encoding="utf-8").read()
    want = _calendar_python(csv)
    with tempfile.TemporaryDirectory() as tmp:
        got_browser = _calendar_browser(csv, binary, tmp)
        got_script = _calendar_script(csv, binary, tmp)

    out = []
    for title in sorted(want):
        notes = []
        for label, got in (("browser", got_browser), ("the script", got_script)):
            if title not in got:
                notes.append("%s never read the rule" % label)
            elif got[title] != want[title]:
                notes.append("%s fires %d time(s), python %d"
                             % (label, len(got[title]), len(want[title])))
        out.append((title, not notes, "; ".join(notes)))
    for label, got in (("browser", got_browser), ("the script", got_script)):
        for title in sorted(set(got) - set(want)):
            out.append((title, False, "%s read a rule python did not" % label))
    return out


def main(verbose=False):
    results = check()
    if results is None:
        print("node is not installed -- nothing checked")
        return 0
    bad = 0
    print("Church -- the HTML the browser paints")
    for name, agreed, want, got in results:
        print("  %-7s %s" % ("agree" if agreed else "DIFFER", name))
        if agreed:
            continue
        bad += 1
        for line in difflib.unified_diff(
                canon(want).replace("><", ">\n<").splitlines(),
                canon(got).replace("><", ">\n<").splitlines(),
                "python", "browser", lineterm="", n=2):
            print("    " + line)
        if verbose:
            print("  python  %s\n  browser %s" % (want, got))

    rules = check_reminders()
    print("\nReminders -- %d day calendars, python vs browser vs Apps Script"
          % CAL_DAYS)
    for title, agreed, note in rules:
        if agreed and not verbose:
            continue
        print("  %-7s %s%s" % ("agree" if agreed else "DIFFER", title,
                               "" if agreed else "  (%s)" % note))
        if not agreed:
            bad += 1
    if all(a for _, a, _ in rules):
        print("  all %d rule(s) agree" % len(rules))

    print("\n%d case(s), %d differing" % (len(results) + len(rules), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main("-v" in sys.argv))
