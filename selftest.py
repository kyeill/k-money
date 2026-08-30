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


CFG = watch.load_config(os.path.join(HERE, "fixtures", "config.json"))


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


def test_provider():
    ok("rent and buy are ignored, and the reseller loses to the real service "
       "despite its better display_priority",
       watch.provider(detail("movie/1003")), "Disney+")
    ok("between two real services, display_priority decides",
       watch.provider(detail("tv/2000")), "Disney+")
    ok("a reseller-only title names the reseller rather than nothing",
       watch.provider(detail("tv/2004")), "HBO Max Amazon Channel")
    ok("no US block is no provider", watch.provider(detail("movie/1000")), None)
    ok("TMDB's spelling is corrected to the brand",
       watch.PROVIDER_NAMES["Disney Plus"], "Disney+")


# -------------------------------------------------------------- buckets

def run_build():
    tmdb.use_fixtures(fixtures())
    with tempfile.TemporaryDirectory() as tmp:
        saved, watch.SEEN = watch.SEEN, os.path.join(tmp, "seen.json")
        try:
            return watch.build(today=TODAY, cfg=CFG, record=True)
        finally:
            watch.SEEN = saved


def test_listing():
    data = run_build()
    titles = [r["title"] for r in data["rows"]]

    ok("one list, ordered by when each thing is next out", titles, [
        "Thunderbolts",                 # 2026-08-25, out four days ago
        "Avengers: Doomsday",           # 2026-09-02
        "Daredevil: Born Again",        # 2026-09-02, ties break on title
        "Frankenstein",                 # 2026-09-10
        "Spider-Man: Brand New Day",    # 2026-09-20
        "Lanterns",                     # 2026-10-15
        "Wonder Man",                   # 2026-12-01
    ])
    dates = [r["date"] for r in data["rows"]]
    ok("dates ascend", dates, sorted(dates))

    true("nothing undated is in the main list", all(r["date"] for r in data["rows"]))

    true("a film released last year is gone", "Last Year's Marvel Film" not in titles)
    true("the popularity pass does not add dated films",
         "Should Not Appear" not in titles)
    ok("nothing is listed twice", len(titles), len(set(titles)))

    src = {r["title"]: r["source"] for r in data["rows"]}
    ok("DC company id resolved by name", src["Lanterns"], "DC")
    ok("watchlist entries carry their own label", src["Frankenstein"], "Custom")
    ok("franchise items are labelled", src["Avengers: Doomsday"], "Marvel")


def test_pending():
    """The waiting list: undated but still alive, closest-to-happening first."""
    data = run_build()
    ok("pending, ordered by how close it is to happening",
       [r["title"] for r in data["pending"]],
       ["Peacemaker",                    # Returning
        "Ended But Pinned",              # Announced, and only there by pinning
        "Untitled Marvel Event Film"])   # Announced
    true("a finished show is not 'pending' -- it is over",
         "Loki" not in [r["title"] for r in data["pending"]])
    true("nothing pending has a date", all(not r["date"] for r in data["pending"]))
    true("the main list and the pending list do not overlap",
         not {r["key"] for r in data["rows"]} & {r["key"] for r in data["pending"]})


def test_tracking_survives_undated():
    """The point of tracking undated titles: they appear the day they are dated."""
    tmdb.use_fixtures(fixtures())
    with tempfile.TemporaryDirectory() as tmp:
        saved, watch.SEEN = watch.SEEN, os.path.join(tmp, "seen.json")
        try:
            rows = watch.collect(CFG, TODAY, record=False)
        finally:
            watch.SEEN = saved
    tracked = {r["title"] for r in rows}
    # The popularity pass keeps every SERIES, because a renewed-but-unscheduled
    # show has no date to gate on -- but for FILMS it keeps only the blanks.
    true("a returning series with no date is tracked", "Peacemaker" in tracked)
    true("an announced film with no date is tracked",
         "Untitled Marvel Event Film" in tracked)
    true("an Ended show is tracked but will never list (no date, ever)",
         "Loki" in tracked)


def test_discover_queries():
    """The gate field is the whole reason mid-run shows were invisible."""
    seen = []
    real = tmdb.get

    def spy(path, ttl=None, **params):
        seen.append((path, params))
        return real(path, ttl, **params)

    tmdb.use_fixtures(fixtures())
    tmdb.get = spy
    try:
        tmdb.discover("tv", 420, TODAY)
        tmdb.discover("movie", 420, TODAY)
    finally:
        tmdb.get = real

    tv = [p for path, p in seen if path == "discover/tv"]
    mv = [p for path, p in seen if path == "discover/movie"]
    true("series gate on any episode air date, not the first",
         any("air_date.gte" in p and "first_air_date.gte" not in p for p in tv))
    true("series exclude podcasts by type", all(p.get("with_type") for p in tv))
    true("series exclude animation and talk",
         all("16" in str(p.get("without_genres")) and "10767" in str(p.get("without_genres"))
             for p in tv))
    true("films gate on their release date",
         any("primary_release_date.gte" in p for p in mv))
    true("films exclude animation but have no type filter",
         all(str(p.get("without_genres")) == "16" and "with_type" not in p for p in mv))


def test_ignore():
    cfg = dict(CFG, ignore=["movie/1000", 2000])
    tmdb.use_fixtures(fixtures())
    with tempfile.TemporaryDirectory() as tmp:
        saved, watch.SEEN = watch.SEEN, os.path.join(tmp, "seen.json")
        try:
            data = watch.build(today=TODAY, cfg=cfg, record=False)
        finally:
            watch.SEEN = saved
    gone = {"Avengers: Doomsday", "Daredevil: Born Again"}
    true("ignore drops by key and by bare id",
         not gone & {r["title"] for r in data["rows"]})


def test_new_badge():
    tmdb.use_fixtures(fixtures())
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "seen.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"movie/1000": "2026-01-01"}, fh)
        saved, watch.SEEN = watch.SEEN, path
        try:
            data = watch.build(today=TODAY, cfg=CFG, record=True)
        finally:
            watch.SEEN = saved
        with open(path, encoding="utf-8") as fh:
            stored = json.load(fh)
    rows = {r["key"]: r for r in data["rows"]}
    ok("a title first seen in January is not new", rows["movie/1000"]["is_new"], False)
    ok("a title first seen today is new", rows["movie/1001"]["is_new"], True)
    ok("first-seen dates are kept, not overwritten",
       stored["movie/1000"], "2026-01-01")
    # Only LISTED titles are recorded. An undated project banked years ago must
    # still read NEW on the day it is finally scheduled, which it cannot do if
    # discovery stamped it the first time it was merely announced.
    ok("only what is shown gets recorded", len(stored), len(rows))
    true("an undated title is not stamped", "movie/1002" not in stored)


# ------------------------------------------------------------ formatting

def test_first_run_badges_nothing():
    """Everything is first-seen-today on run one; badging it all says nothing."""
    rows = run_build()["rows"]
    ok("nothing is new before there is a before",
       sorted({r["is_new"] for r in rows}), [False])
    ok("and the seed batch is backdated, so it is not new tomorrow either",
       sorted({r["first_seen"] for r in rows}), [watch.SEED])


def test_undated_labels():
    """Undated rows are not listed today, but the label still has to be right:
    one of them becomes a listed row the day it is scheduled."""
    tmdb.use_fixtures(fixtures())
    with tempfile.TemporaryDirectory() as tmp:
        saved, watch.SEEN = watch.SEEN, os.path.join(tmp, "seen.json")
        try:
            rows = watch.collect(CFG, TODAY, record=False)
        finally:
            watch.SEEN = saved
    by = {r["title"]: r["when"] for r in rows if not r["date"]}
    ok("an undated film says what stage it is at",
       by["Untitled Marvel Event Film"], "Announced")
    ok("an undated series says it is returning", by["Peacemaker"], "Returning")
    true("nothing undated says 'Release' or 'Series'",
         not set(by.values()) & {"Release", "Series"})


def test_ui():
    ok("this year needs no year", ui.day_parts("2026-09-02", TODAY), ("Sep 2", "Wed"))
    ok("another year drops the day, not the year",
       ui.day_parts("2027-09-02", TODAY), ("Sep 2027", ""))
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

    ok("every row is rendered", body.count('class="item'),
       len(data["rows"]) + len(data["pending"]))
    ok("the already-released row is dimmed", body.count('class="item past"'), 1)
    ok("the pending section is headed and counted",
       re.findall(r"<h2>Pending release date <b>(\d+)</b>", body),
       [str(len(data["pending"]))])
    ok("the main list has no heading above it", body.count("<h2>"), 1)

    true("posters are lazy", 'loading="lazy"' in body)
    true("links open outward", 'rel="noopener"' in body)
    true("exactly one provider chip per row that has one",
         body.count("class=\"chip\"") <= body.count("class=\"item"))
    true("the episode name made it", "The Green Sea" in body)
    true("filler episode names did not", "Episode 4" not in body)
    true("an undated row leaves its date column blank rather than reading TBA",
         "TBA" not in body)

    # An empty list must say so rather than render nothing at all.
    empty = watch.render({"today": TODAY, "rows": [], "pending": [], "tracked": 0})
    true("an empty list still says something", "Nothing scheduled." in empty)


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("\n%d passed, %d failed" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
