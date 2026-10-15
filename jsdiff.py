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

Only the Church tab is covered so far. Reminders and Active would both fit the
same harness -- their JS also ends in a `refresh()` call that can be preceded
by a `build()` probe -- and neither is covered, which is a real gap rather than
a decision.
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


def main(verbose=False):
    results = check()
    if results is None:
        print("node is not installed -- nothing checked")
        return 0
    bad = 0
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
    print("\n%d case(s), %d differing" % (len(results), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main("-v" in sys.argv))
