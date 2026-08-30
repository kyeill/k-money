"""Assertions over the parts the page cannot show you.

Runs entirely against fixtures/tmdb.json, so it needs no API key and no
network. `python selftest.py` before trusting any change.
"""

import importlib.util
import json
import os
import re
import sys
import tempfile

import tmdb
import ui
import watch

HERE = os.path.dirname(os.path.abspath(__file__))
TODAY = "2026-08-29"

PASS = FAIL = 0


def ok(label, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
    else:
        FAIL += 1
        print("FAIL  %s\n      got  %r\n      want %r" % (label, got, want))


def true(label, cond):
    ok(label, bool(cond), True)


def fixtures():
    with open(os.path.join(HERE, "fixtures", "tmdb.json"), encoding="utf-8") as fh:
        return json.load(fh)


CFG = {
    "region": "US", "language": "en-US",
    "franchises": [
        {"key": "mcu", "label": "Marvel", "company": "Marvel Studios", "company_id": 420},
        {"key": "dcu", "label": "DC", "company": "DC Studios", "company_id": None},
    ],
    "watchlist": [{"type": "movie", "id": 1005, "title": "Frankenstein", "label": "Mine"}],
    "ignore": [],
    "soon_days": 7, "near_days": 30, "keep_released_days": 14,
}


def detail(path):
    for entry in fixtures():
        if entry["path"] == path:
            return entry["data"]
    raise KeyError(path)


# --------------------------------------------------------------- dates

def test_movie_dates():
    ok("US theatrical beats the global release_date",
       watch.movie_date(detail("movie/1000")), ("2026-09-02", "In theaters"))
    ok("digital-only film uses its digital date",
       watch.movie_date(detail("movie/1001")), ("2026-09-20", "Streaming"))
    ok("no country block falls back to release_date",
       watch.movie_date(detail("movie/1002")), (None, "Release"))
    ok("a country we do not care about is ignored",
       watch.movie_date(detail("movie/1000"), region="ZZ"), ("2026-08-20", "Release"))


def test_tv_dates():
    ok("mid-run show reads its next episode",
       watch.tv_date(detail("tv/2000"), TODAY), ("2026-09-02", "S2 E4"))
    ok("unaired show is a premiere, not Season 1",
       watch.tv_date(detail("tv/2001"), TODAY), ("2026-12-01", "Premiere"))
    ok("renewed with no date has no date",
       watch.tv_date(detail("tv/2002"), TODAY), (None, "Series"))
    ok("a real episode name is kept",
       watch.tv_date(detail("tv/2004"), TODAY), ("2026-10-15", "S1 E6 · The Green Sea"))

    # The seasons branch only reachable once first_air_date is in the past.
    between = dict(detail("tv/2002"))
    between["seasons"] = [{"season_number": 3, "air_date": "2027-02-01"}]
    ok("between seasons uses the next dated season",
       watch.tv_date(between, TODAY), ("2027-02-01", "Season 3"))

    # Season 0 is the specials bucket and is not what anyone is waiting for.
    specials = dict(detail("tv/2002"))
    specials["seasons"] = [{"season_number": 0, "air_date": "2027-02-01"}]
    ok("season 0 specials do not count",
       watch.tv_date(specials, TODAY), (None, "Series"))


def test_providers():
    ok("rent and buy are ignored",
       watch.providers(detail("movie/1003")), ["Disney Plus"])
    ok("no US block is no providers",
       watch.providers(detail("movie/1000")), [])


# -------------------------------------------------------------- buckets

def run_build():
    tmdb.use_fixtures(fixtures())
    with tempfile.TemporaryDirectory() as tmp:
        saved, watch.SEEN = watch.SEEN, os.path.join(tmp, "seen.json")
        try:
            return watch.build(today=TODAY, cfg=CFG, record=True)
        finally:
            watch.SEEN = saved


def test_buckets():
    data = run_build()
    b = data["buckets"]
    titles = {k: [r["title"] for r in v] for k, v in b.items()}

    ok("this week", titles["now"], ["Avengers: Doomsday", "Daredevil: Born Again"])
    ok("next 30 days", titles["soon"], ["Frankenstein", "Spider-Man: Brand New Day"])
    ok("later", titles["later"], ["Lanterns", "Wonder Man"])
    ok("no date yet", titles["tba"], ["Peacemaker", "Untitled Marvel Event Film"])
    ok("just out", titles["out"], ["Thunderbolts"])

    every = [t for v in titles.values() for t in v]
    true("an ended show with no date is dropped", "Loki" not in every)
    true("a film released last year is dropped", "Last Year's Marvel Film" not in every)
    ok("nothing is listed twice", len(every), len(set(every)))

    src = {r["title"]: r["source"] for v in b.values() for r in v}
    ok("DC company id resolved by name", src["Lanterns"], "DC")
    ok("watchlist entries carry their own label", src["Frankenstein"], "Mine")
    ok("franchise items are labelled", src["Avengers: Doomsday"], "Marvel")

    ordered = [r["date"] for r in b["later"]]
    ok("sections sort by date", ordered, sorted(ordered))
    ok("just out sorts newest first", [r["date"] for r in b["out"]],
       sorted([r["date"] for r in b["out"]], reverse=True))


def test_ignore():
    cfg = dict(CFG, ignore=["movie/1000", 2000])
    tmdb.use_fixtures(fixtures())
    with tempfile.TemporaryDirectory() as tmp:
        saved, watch.SEEN = watch.SEEN, os.path.join(tmp, "seen.json")
        try:
            data = watch.build(today=TODAY, cfg=cfg, record=False)
        finally:
            watch.SEEN = saved
    ok("ignore drops by key and by bare id", data["buckets"]["now"], [])


def test_new_badge():
    tmdb.use_fixtures(fixtures())
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "seen.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"movie/1000": "2026-01-01"}, fh)
        saved, watch.SEEN = watch.SEEN, path
        try:
            rows = {r["key"]: r for r in watch.collect(CFG, TODAY, record=True)}
        finally:
            watch.SEEN = saved
        with open(path, encoding="utf-8") as fh:
            stored = json.load(fh)
    ok("a title first seen in January is not new", rows["movie/1000"]["is_new"], False)
    ok("a title first seen today is new", rows["movie/1001"]["is_new"], True)
    ok("first-seen dates are kept, not overwritten",
       stored["movie/1000"], "2026-01-01")
    ok("every title gets recorded", len(stored), len(rows))


# ------------------------------------------------------------ formatting

def test_ui():
    ok("this year needs no year", ui.day_parts("2026-09-02", TODAY), ("Sep 2", "Wed"))
    ok("another year says so", ui.day_parts("2027-09-02", TODAY), ("Sep 2 2027", ""))
    ok("no date", ui.day_parts(None, TODAY), ("TBA", ""))
    ok("today", ui.relative("2026-08-29", TODAY), "Today")
    ok("tomorrow", ui.relative("2026-08-30", TODAY), "Tomorrow")
    ok("anything else is left to the date", ui.relative("2026-09-05", TODAY), "")
    ok("escaping", ui.esc('a & b <c>'), "a &amp; b &lt;c&gt;")


# ---------------------------------------------------------------- page

def shell():
    """`site` is a stdlib module name and is already in sys.modules by the time
    anything here runs, so a plain `import site` returns the stdlib one. Load
    the shell by path instead."""
    spec = importlib.util.spec_from_file_location("kmsite", os.path.join(HERE, "site.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_page():
    data = run_build()
    body = watch.render(data)
    page = shell().render(TODAY, [(watch.KEY, watch.LABEL, body)])

    true("has a doctype", page.startswith("<!doctype html>"))
    true("names itself", "<title>K Money</title>" in page)
    true("the build date reaches the JS", "const BUILT='%s'" % TODAY in page)
    true("the tab's own CSS is included", ".pos{" in page)
    ok("one section per tab", page.count("<section "), 1)
    ok("one nav button per tab", page.count("<button data-k="), 1)
    true("a single tab hides the tab bar", '<nav class="solo">' in page)

    ok("tags balance", page.count("<div"), page.count("</div>"))
    ok("links balance", page.count("<a "), page.count("</a>"))
    ok("spans balance", page.count("<span"), page.count("</span>"))

    rows = sum(len(v) for v in data["buckets"].values())
    ok("every row is rendered", body.count('class="item"'), rows)

    heads = re.findall(r"<h2>([^<]+) <b>(\d+)</b>", body)
    counted = {name.strip(): int(n) for name, n in heads}
    for key, label in watch.SECTIONS:
        if data["buckets"][key]:
            ok("heading count matches rows: " + label,
               counted.get(label), len(data["buckets"][key]))

    true("posters are lazy", 'loading="lazy"' in body)
    true("links open outward", 'rel="noopener"' in body)
    true("a provider chip made it", "Disney Plus" in body)
    true("the episode name made it", "The Green Sea" in body)
    true("filler episode names did not", "Episode 4" not in body)

    # An empty week must still print its heading -- an app whose first section
    # vanishes on a quiet week looks broken.
    quiet = {"today": TODAY, "buckets": dict(data["buckets"], now=[])}
    true("an empty week still shows", "Nothing this week." in watch.render(quiet))


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("\n%d passed, %d failed" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
