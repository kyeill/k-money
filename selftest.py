"""Assertions over the parts the page cannot show you.

Runs entirely against fixtures/tmdb.json, so it needs no API key and no
network. `python selftest.py` before trusting any change.
"""

import datetime as dt
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
       watch.movie_date(detail("movie/1000")), ("2026-09-02", "In Theaters"))
    ok("digital-only film uses its digital date",
       watch.movie_date(detail("movie/1001")), ("2026-09-20", "Streaming"))
    ok("no country block falls back to release_date",
       watch.movie_date(detail("movie/1002")), (None, "Release"))
    ok("a country we do not care about is ignored",
       watch.movie_date(detail("movie/1000"), region="ZZ"), ("2026-08-20", "Release"))


def test_tv_dates():
    ok("mid-run show reads its next episode",
       watch.tv_date(detail("tv/2000"), TODAY), ("2026-09-02", "Season 2 Episode 4"))
    ok("unaired show is a premiere, not Season 1",
       watch.tv_date(detail("tv/2001"), TODAY), ("2026-12-01", "Premiere"))
    ok("renewed with no date has no date",
       watch.tv_date(detail("tv/2002"), TODAY), (None, "Series"))
    ok("a real episode name is kept",
       watch.tv_date(detail("tv/2004"), TODAY), ("2026-10-15", "Season 1 Episode 6 · The Green Sea"))

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

def sheet_watchlist_env(tmp):
    """Point the hand-added list at fixtures, and its remembered ids at a temp
    file -- a test must not read, or overwrite, the real ones."""
    os.environ["KMONEY_WATCHLIST_CSV"] = os.path.join(HERE, "fixtures",
                                                      "watchlist.csv")
    os.environ["KMONEY_WATCHLIST_STATE"] = os.path.join(tmp, "watchlist.json")


def clear_watchlist_env():
    os.environ.pop("KMONEY_WATCHLIST_CSV", None)
    os.environ.pop("KMONEY_WATCHLIST_STATE", None)


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
        # 2026-09-15 "Preschool Pals" is filtered out between these two, and
        # 2026-09-12 "Preschool Special" before them.
        "Skeleton Crew Shaped",         # 2026-09-18
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
    # "DC" in the fixture config, "DCU" on the page: LABEL_NAMES renames every
    # label whatever its source, so the Sheet's Label column gets it too --
    # that column is his to type into and is not worth retyping.
    ok("DC company id resolved by name, and renamed", src["Lanterns"], "DCU")
    ok("watchlist entries carry their own label", src["Frankenstein"], "Custom")
    ok("franchise items are labelled", src["Avengers: Doomsday"], "MCU")
    ok("a label with no rename passes through", watch.label_name("Star Wars"),
       "Star Wars")
    # The source column already says LOTR, so the title repeating it just wraps
    # the row to two lines on a phone.
    ok("the LOTR prefix comes off a series",
       watch.short_title("The Lord of the Rings: The Rings of Power"),
       "The Rings of Power")
    ok("and off a film",
       watch.short_title("The Lord of the Rings: The Hunt for Gollum"),
       "The Hunt for Gollum")
    # I argued for keeping this one, on the grounds that "Star Wars: Skeleton
    # Crew" is how the show is known. He wanted it gone; the source column says
    # Star Wars either way.
    ok("the Star Wars prefix comes off too",
       watch.short_title("Star Wars: Skeleton Crew"), "Skeleton Crew")
    ok("an unlisted franchise keeps its prefix",
       watch.short_title("Alien: Earth"), "Alien: Earth")
    ok("a title that only mentions it mid-string is untouched",
       watch.short_title("Making The Lord of the Rings: A Documentary"),
       "Making The Lord of the Rings: A Documentary")
    # Stripping a title to nothing would be worse than leaving it long.
    ok("a bare prefix is left alone",
       watch.short_title("The Lord of the Rings: "),
       "The Lord of the Rings: ")
    ok("renaming ignores case", watch.label_name("lord of THE rings"), "LOTR")
    ok("and tolerates stray spacing", watch.label_name("  DC "), "DCU")


def test_soon_split():
    """The list is cut into "next 30 days" and "upcoming". The rows are
    already in date order, so this is only about where the boundary falls."""
    data = run_build()
    soon, later = watch.split_soon(data["rows"], TODAY)

    ok("the near section, up to and including the 30th day",
       [r["title"] for r in soon],
       ["Thunderbolts",              # 2026-08-25, already out
        "Avengers: Doomsday",        # 2026-09-02
        "Daredevil: Born Again",     # 2026-09-02
        "Frankenstein",              # 2026-09-10
        "Skeleton Crew Shaped",      # 2026-09-18
        "Spider-Man: Brand New Day"])  # 2026-09-20
    ok("and everything else below it", [r["title"] for r in later],
       ["Lanterns", "Wonder Man"])   # 2026-10-15, 2026-12-01

    # Already out belongs in the NEAR section: it is the most actionable thing
    # on the page, and it is only listed at all because keep_released_days
    # exists so a release is not missed by looking a day late.
    true("something already out is near, not 'upcoming'",
         soon[0]["date"] < TODAY)
    ok("nothing is lost or duplicated by the split",
       len(soon) + len(later), len(data["rows"]))
    true("both halves stay in date order",
         [r["date"] for r in soon + later]
         == sorted(r["date"] for r in soon + later))

    # The boundary is inclusive, and a day past it is not.
    edge = watch._shift(TODAY, watch.SOON_DAYS)
    rows = [{"date": edge, "title": "on the day"},
            {"date": watch._shift(TODAY, watch.SOON_DAYS + 1), "title": "one later"}]
    a, b = watch.split_soon(rows, TODAY)
    ok("the 30th day itself is near", [r["title"] for r in a], ["on the day"])
    ok("the 31st is not", [r["title"] for r in b], ["one later"])

    html = watch.render(data)
    true("the near section is headed", "<h2>Next 30 days</h2>" in html)
    true("and the rest is headed too", "<h2>Upcoming</h2>" in html)
    true("near comes first", html.index("Next 30 days") < html.index("Upcoming"))
    true("and both come before the undated list",
         html.index("Upcoming") < html.index("Pending release date"))
    # An empty near section is news; a missing one looks like a broken page.
    empty = watch.render(dict(data, rows=later))
    true("an empty near section says so",
         "Nothing out in the next 30 days." in empty)
    true("and the heading is still there", "<h2>Next 30 days</h2>" in empty)
    # With nothing far out there is no second heading to show.
    near_only = watch.render(dict(data, rows=soon))
    true("no 'Upcoming' heading when there is nothing beyond the window",
         "Upcoming" not in near_only)


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


def test_sheet_watchlist():
    """The hand-added titles come from the Sheet's Watchlist tab. Columns are
    by name, so the sheet can grow a column without breaking, and an id is
    resolved once and then remembered rather than re-guessed every morning."""
    text = open(os.path.join(HERE, "fixtures", "watchlist.csv"),
                encoding="utf-8").read()
    rows = watch.read_sheet_watchlist(text)

    ok("a row per titled line", [r["title"] for r in rows],
       ["Frankenstein", "Skeleton Crew Shaped", "Ended But Pinned"])
    # Label sits in column A in the fixture and Title in column B, which is
    # the whole point: nothing here is positional.
    ok("columns are found by name, not position", rows[0]["label"], "Custom")
    ok("a named label is kept", rows[2]["label"], "Lord of the Rings")
    ok("no label falls back to Custom", rows[1]["label"], "Custom")
    ok("no type falls back to tv", rows[1]["type"], "tv")
    ok("type is case-insensitive", rows[2]["type"], "tv")
    ok("an explicit movie is honoured", rows[0]["type"], "movie")
    true("a row with no title is dropped",
         all(r["title"] for r in rows))
    ok("an unrecognised column is simply ignored", len(rows), 3)

    ok("a one-column sheet is enough",
       [r["title"] for r in watch.read_sheet_watchlist('"Title"\n"Solo"')],
       ["Solo"])
    ok("an empty sheet is not an error", watch.read_sheet_watchlist(""), [])
    try:
        watch.read_sheet_watchlist('"Name","When"\n"x","y"')
        ok("a sheet with no Title column is refused", "no error", "ValueError")
    except ValueError:
        ok("a sheet with no Title column is refused", "ValueError", "ValueError")


def test_sheet_watchlist_merge():
    """config.json and the Sheet both feed the list, and the remembered ids
    survive the Sheet being unreachable."""
    with tempfile.TemporaryDirectory() as tmp:
        state = os.path.join(tmp, "watchlist.json")
        os.environ["KMONEY_WATCHLIST_STATE"] = state
        try:
            items = watch.hand_added(CFG, "en-US")
            titles = [i["title"] for i in items]
            true("config entries are kept", "Ended But Pinned" in titles)
            true("sheet entries are added", "Skeleton Crew Shaped" in titles)
            ok("nothing is lost from either source", len(titles), 5)
            true("what the sheet resolved is written down",
                 os.path.exists(state))

            # Type defaults to tv, so a FILM added with only a title finds
            # nothing at all as a series. Searching the other kind before
            # giving up is what lets a one-column sheet work -- "The Hunt for
            # Gollum" is a film, and nobody should have to know a column exists
            # to say so.
            # A bare sheet: one title, no Id column, so it must be searched.
            bare = os.path.join(tmp, "bare.csv")
            with open(bare, "w", encoding="utf-8") as fh:
                fh.write('"Title"\n"A Film"\n')
            os.environ["KMONEY_WATCHLIST_CSV"] = bare
            os.environ["KMONEY_WATCHLIST_STATE"] = os.path.join(tmp, "s1.json")

            searched, real = [], tmdb.search

            def only_movies(kind, title, lang):
                searched.append(kind)
                return [{"id": 1005, "title": title}] if kind == "movie" else []

            tmdb.search = only_movies
            try:
                found = watch.hand_added(dict(CFG, watchlist=[]), "en-US")
            finally:
                tmdb.search = real
            ok("a title typed tv falls back to movie", searched, ["tv", "movie"])
            ok("and is kept, as a movie",
               [(f["title"], f["type"]) for f in found], [("A Film", "movie")])

            # A title nothing can place must be NAMED, not just absent -- that
            # looks identical to forgetting to add it.
            os.environ["KMONEY_WATCHLIST_STATE"] = os.path.join(tmp, "s2.json")
            missing = []
            tmdb.search = lambda kind, title, lang: []
            try:
                watch.hand_added(dict(CFG, watchlist=[]), "en-US", missing)
            finally:
                tmdb.search = real
            ok("an unplaceable title is reported, not dropped in silence",
               missing, ["A Film"])
            true("the page says so",
                 'class="werr"' in watch.render(
                     {"today": TODAY, "rows": [], "pending": [],
                      "tracked": 0, "unresolved": ["Nope"]}))

            # A network blip must not quietly shrink the list for a day. s1
            # remembers "A Film"; the sheet is now unreachable.
            os.environ["KMONEY_WATCHLIST_STATE"] = os.path.join(tmp, "s1.json")
            os.environ["KMONEY_WATCHLIST_CSV"] = os.path.join(tmp, "gone.csv")
            fallback = watch.hand_added(dict(CFG, watchlist=[]), "en-US")
            ok("an unreadable sheet falls back to the remembered rows",
               [i["title"] for i in fallback], ["A Film"])
        finally:
            os.environ.pop("KMONEY_WATCHLIST_STATE", None)
            sheet_watchlist_env(tmp)


def test_no_refresh_flash():
    """The tab opens on a baked copy and then refetches. Rebuilding identical
    rows and assigning them anyway tears the list down and rebuilds it, which
    is the flash -- so the DOM is only touched when something actually
    differs."""
    import reminders
    js = reminders.page_js({"today": "2026-08-30", "days": [], "sheet": "S",
                            "webapp": "", "error": None})
    true("the refresh goes through the guard", "paint(html)" in js)
    true("nothing else assigns the list wholesale",
         js.count("body.innerHTML=") == 1)
    true("the guard compares before it writes",
         "if(scratch.innerHTML!==body.innerHTML)" in js)

    # The guard alone cannot help the reload case: the baked copy was built at
    # 6am, so everything ticked since comes back unticked -- genuinely
    # different markup, correctly repainted, and visible as a flash. The last
    # list seen is kept and painted BEFORE any network.
    true("the last list seen is kept", "saveSnap(html)" in js)
    true("and painted before the fetch, not after",
         js.index("if(snap) paint(snap)") < js.index("refresh();\n  document"))
    # Yesterday's list restored this morning would be worse than the baked one.
    true("the snapshot is keyed by date", "SNAP+iso(new Date())" in js)
    true("older snapshots are pruned", "localStorage.removeItem(k)" in js)
    # Both sides are normalised by the browser first. A string built in JS
    # never matches one read back out of the DOM, even when they are the same
    # markup -- quoting and attribute order come back differently.
    true("both sides are normalised through innerHTML first",
         "scratch.innerHTML=html" in js)


def test_preschool_filter():
    """The Disney Jr. tier is officially Marvel/DC/Lucasfilm, so only the genre
    separates it. The danger is over-reaching and losing a real show."""
    kids = {"genre_ids": [16, 10762]}
    ok("a Kids series is preschool", tmdb.is_preschool("tv", kids), True)
    ok("Kids is TV-only, so it means nothing on a film",
       tmdb.is_preschool("movie", kids), False)

    for name, ids in [("X-Men '97", [16, 10759, 10765]),
                      ("Marvel Zombies", [10765, 16, 10759]),
                      ("Star Wars: Visions", [16, 10765, 10759]),
                      ("Get Jiro", [16])]:
        ok("real animation survives: " + name,
           tmdb.is_preschool("tv", {"genre_ids": ids}), False)

    # THE regression that matters: Family alone must never disqualify a show.
    ok("Star Wars: Skeleton Crew (Family, live action) is NOT preschool",
       tmdb.is_preschool("tv", {"genre_ids": [10759, 10765, 10751]}), False)
    ok("a film needs BOTH animation and family",
       tmdb.is_preschool("movie", {"genre_ids": [16, 10751]}), True)
    ok("an animated film that is not Family survives",
       tmdb.is_preschool("movie", {"genre_ids": [16, 878]}), False)
    ok("a live-action Family film survives",
       tmdb.is_preschool("movie", {"genre_ids": [12, 10751]}), False)
    ok("no genres at all is not preschool",
       tmdb.is_preschool("tv", {}), False)


def test_preschool_filter_end_to_end():
    data = run_build()
    everything = [r["title"] for r in data["rows"] + data["pending"]]
    true("the preschool series never reaches the page",
         "Preschool Pals" not in everything)
    true("nor the preschool film", "Preschool Special" not in everything)
    true("but the Family live-action show does",
         "Skeleton Crew Shaped" in everything)


# ------------------------------------------------------------- reminders

def _rules():
    import reminders
    with open(os.path.join(HERE, "fixtures", "reminders.csv"), encoding="utf-8") as fh:
        return reminders.read_rules(fh.read())


def test_reminder_parsing():
    import reminders
    rules = _rules()
    titles = [r["title"] for r in rules]
    ok("a row with no time is dropped -- it could never fire",
       "No time row" not in titles, True)
    ok("a row with no title is dropped", "" not in titles, True)
    ok("everything else parses", len(rules), 17)

    ok("12-hour times", reminders.parse_time("12:30 PM"), (12, 30))
    ok("midnight is 00, not 12", reminders.parse_time("12:00 AM"), (0, 0))
    ok("noon stays 12", reminders.parse_time("12:00 PM"), (12, 0))
    ok("lowercase and no space", reminders.parse_time("7:15am"), (7, 15))
    ok("24-hour passes through", reminders.parse_time("19:00"), (19, 0))
    ok("blank is no time", reminders.parse_time(""), None)
    ok("nonsense is no time", reminders.parse_time("soon"), None)

    by = {r["title"]: r for r in rules}
    ok("any non-empty mark ticks the day", sorted(by["Odd marks"]["days"]), [0])
    ok("weekly rows are not monthly", by["Standup"]["monthly"], False)
    ok("a complete nth+weekday makes a row monthly", by["Rent"]["monthly"], True)
    ok("blank Months means every month", sorted(by["Board mtg"]["months"]),
       list(range(1, 13)))
    ok("Quarterly is Jan/Apr/Jul/Oct",
       sorted(by["Quarterly tax"]["months"]), [1, 4, 7, 10])
    ok("All means every month", sorted(by["Rent"]["months"]), list(range(1, 13)))

    bad = "Title,Time,Mon\nx,1:00 PM,x"
    try:
        reminders.read_rules(bad)
        ok("a wrong header is refused", "no error", "SheetError")
    except reminders.SheetError:
        ok("a wrong header is refused", "SheetError", "SheetError")

    # He labels sections in the sheet, and put one in the header cell itself:
    # A1 read "Title DAILY". That broke the page AND every notification at
    # once, so headings are matched on their first word.
    full = ["Title DAILY", "Time ", "Mon ", "Tue ", "Wed ", "Thu ", "Fri ",
            "Sat ", "Sun ", "nth ", "Weekday ", "Months "]
    true("a labelled heading is still that heading",
         reminders.header_ok([h.strip().lower() for h in full]))
    true("trailing spaces are fine",
         reminders.header_ok(["title", "time ", "mon", "tue", "wed", "thu",
                              "fri", "sat", "sun", "nth", "weekday", "months"]))
    ok("but the Done tab is still refused",
       reminders.header_ok(["date", "key", "done", "updated"]), False)
    ok("and a short header is refused", reminders.header_ok(["title"]), False)

    # The Weekday column is optional. Both layouts must work, because the sheet
    # gets edited while the page and the notifications are live.
    eleven = ["title", "time", "mon", "tue", "wed", "thu", "fri", "sat", "sun",
              "nth", "months"]
    ok("a sheet with no Weekday column is fine",
       reminders.layout(eleven)[1], {"nth": 9, "months": 10})
    ok("and one with it puts Months a column later",
       reminders.layout(eleven[:10] + ["weekday", "months"])[1],
       {"nth": 9, "weekday": 10, "months": 11})

    # His proposed layout: nth, Every, Starting, Months.
    ok("interval columns are found by name",
       reminders.layout(eleven[:10] + ["every", "starting", "months"])[1],
       {"nth": 9, "every": 10, "starting": 11, "months": 12})
    ok("order among them does not matter",
       reminders.layout(eleven[:10] + ["months", "starting", "every"])[1],
       {"nth": 9, "months": 10, "starting": 11, "every": 12})
    ok("a missing Months column just means every month",
       reminders.layout(eleven[:10])[0], True)

    # A typo would otherwise drop the column silently and stop every interval
    # reminder, with nothing anywhere saying so.
    ok("an unrecognised heading is reported",
       reminders.layout(eleven[:10] + ["every", "startng", "months"])[2],
       ["startng"])

    # Day-of-month with no Weekday column at all: nth and no ticked day can
    # only mean the day of the month. Without this it was not monthly, had no
    # days, and fired NEVER.
    no_wd = "\n".join([
        '"' + '","'.join(eleven) + '"',
        '"Rent","9:00 AM","","","","","","","","1st",""',
        '"Card","2:00 PM","","","","","","","","Last",""',
        '"Bins","7:00 AM","","","","","","","x","1st, 3rd",""'])
    by = {r["title"]: r for r in reminders.read_rules(no_wd)}
    ok("no ticks means day of the month", by["Rent"]["weekday"], "Day")
    ok("and it is monthly", by["Rent"]["monthly"], True)
    true("the 1st fires on the 1st",
         reminders.fires_on(by["Rent"], dt.date(2026, 9, 1)))
    ok("and not the 2nd",
       reminders.fires_on(by["Rent"], dt.date(2026, 9, 2)), False)
    true("Last means the last day",
         reminders.fires_on(by["Card"], dt.date(2026, 9, 30)))
    ok("a ticked day still wins over day-of-month",
       by["Bins"]["weekday"], "Sun")
    ok("a heading that merely starts the same is refused",
       reminders.header_ok(["titles", "time", "mon", "tue", "wed", "thu",
                            "fri", "sat", "sun", "nth", "weekday", "months"]),
       False)


def test_reminder_rules():
    """Google silently returns the FIRST tab for an unknown one, so the header
    check above is what stops us parsing the wrong sheet. These are the dates."""
    import reminders
    by = {r["title"]: r for r in _rules()}

    def fires(title, iso):
        return reminders.fires_on(by[title], dt.date.fromisoformat(iso))

    true("weekly: Laundry on a Sunday", fires("Laundry", "2026-08-30"))
    ok("weekly: not on a Monday", fires("Laundry", "2026-08-31"), False)
    true("weekdays only: Standup on Friday", fires("Standup", "2026-09-04"))
    ok("weekdays only: not Saturday", fires("Standup", "2026-09-05"), False)

    true("last Sunday of August is the 30th", fires("Credit Cards", "2026-08-30"))
    ok("the 23rd is a Sunday but not the last one",
       fires("Credit Cards", "2026-08-23"), False)
    true("first Tuesday of September is the 1st", fires("Board mtg", "2026-09-01"))
    ok("the second Tuesday is not the first",
       fires("Board mtg", "2026-09-08"), False)

    true("1st Day is the 1st", fires("Rent", "2026-09-01"))
    ok("and only the 1st", fires("Rent", "2026-09-02"), False)
    true("Last Day of a 31-day month", fires("Quarterly tax", "2026-10-31"))
    ok("but only in a quarter month", fires("Quarterly tax", "2026-11-30"), False)
    true("Last Day of a 30-day quarter month", fires("Quarterly tax", "2026-04-30"))
    true("Last Day handles February", fires("Quarterly tax", "2027-01-31"))

    # A row carrying both kinds is monthly; the weekly ticks are ignored.
    true("mixed row fires on its monthly rule (2nd Wed of Sep)",
         fires("Mixed both", "2026-09-09"))
    ok("mixed row ignores its weekly tick (a Monday)",
       fires("Mixed both", "2026-09-07"), False)

    # Leap year, because "last day of February" is where date maths goes wrong.
    leap = {"title": "x", "at": (9, 0), "days": set(), "nths": [-1],
            "weekday": "Day", "months": set(range(1, 13)), "monthly": True}
    true("last day of Feb 2028 is the 29th",
         reminders.fires_on(leap, dt.date(2028, 2, 29)))
    ok("not the 28th in a leap year",
       reminders.fires_on(leap, dt.date(2028, 2, 28)), False)
    true("last day of Feb 2027 is the 28th",
         reminders.fires_on(leap, dt.date(2027, 2, 28)))

    # "4th" + Sun ticked + Weekday blank. Without the inference the nth is
    # dropped and this fires EVERY Sunday -- four times too often, silently.
    true("4th Sunday of August is the 23rd", fires("Fourth Sun", "2026-08-23"))
    ok("the 30th is a 5th Sunday, not a 4th",
       fires("Fourth Sun", "2026-08-30"), False)
    true("4th Sunday of September is the 27th", fires("Fourth Sun", "2026-09-27"))
    ok("the 20th is the 3rd Sunday", fires("Fourth Sun", "2026-09-20"), False)
    ok("it is treated as monthly, not weekly", by["Fourth Sun"]["monthly"], True)
    ok("and the weekday was inferred from the tick", by["Fourth Sun"]["weekday"], "Sun")

    # Day-of-month past the 5th. Without this "the 25th" is inexpressible --
    # nth used to be a lookup of 1st..5th and Last only.
    true("the 25th fires on the 25th", fires("Rent 25th", "2026-09-25"))
    ok("and not the 24th", fires("Rent 25th", "2026-09-24"), False)
    true("and again next month", fires("Rent 25th", "2026-10-25"))
    ok("a bare number", reminders.parse_nths("25"), [25])
    ok("an ordinal", reminders.parse_nths("25th"), [25])
    ok("Last is -1", reminders.parse_nths("Last"), [-1])
    ok("blank is nothing", reminders.parse_nths(""), [])
    ok("nonsense is nothing", reminders.parse_nths("soon"), [])
    ok("out of range is nothing", reminders.parse_nths("32nd"), [])
    # Both of these were in his real sheet and both failed silently: "1st, 3rd"
    # had its digits glued into 13 (a month has no 13th Tuesday, so it fired
    # NEVER) and word forms parsed to nothing, dropping the row back to its
    # weekly ticks and firing it four or five times a month.
    ok("two occurrences, not thirteen", reminders.parse_nths("1st, 3rd"), [1, 3])
    ok("spaces instead of a comma", reminders.parse_nths("1st 3rd"), [1, 3])
    ok("word ordinals", reminders.parse_nths("Second"), [2])
    ok("mixed forms", reminders.parse_nths("First, 3rd, Last"), [1, 3, -1])
    ok("duplicates collapse", reminders.parse_nths("1st, 1st"), [1])

    # A short month simply has no 30th, so the rule is silent rather than
    # firing on some other day.
    ok("the 30th does not fire in February", fires("Feb 30th", "2027-02-28"), False)
    true("but does in January", fires("Feb 30th", "2027-01-30"))

    # Section headers: a row with a title and nothing else must be inert, so
    # the sheet can be organised without inventing reminders.
    true("a section header row is not a rule",
         "HOUSEHOLD" not in [r["title"] for r in _rules()])

    # Two days ticked with an nth is genuinely ambiguous, so no inference: it
    # stays weekly rather than guessing which day the nth applies to.
    ok("an ambiguous nth does not become monthly",
       by["Ambiguous nth"]["monthly"], False)

    # Months gates WEEKLY rows too, which is how a weekly rule gets a season.
    true("weekly-with-season fires inside its months (Sat 3 Oct)",
         fires("Ski season", "2026-10-03"))
    ok("and not outside them (Sat 1 Aug)", fires("Ski season", "2026-08-01"), False)
    ok("nor on the wrong weekday inside them (Sun 4 Oct)",
       fires("Ski season", "2026-10-04"), False)
    true("a summer-only weekly fires in July", fires("Summer swim", "2026-07-06"))
    ok("and is silent in October", fires("Summer swim", "2026-10-05"), False)
    true("a season does not disturb a plain weekly row",
         fires("Laundry", "2026-08-30") and fires("Laundry", "2027-01-03"))

    # A 5th weekday exists in some months and not others.
    fifth = {"title": "x", "at": (9, 0), "days": set(), "nths": [5],
             "weekday": "Sun", "months": set(range(1, 13)), "monthly": True}
    true("August 2026 has a 5th Sunday", reminders.fires_on(fifth, dt.date(2026, 8, 30)))
    ok("September 2026 has no 5th Sunday",
       any(reminders.fires_on(fifth, dt.date(2026, 9, d)) for d in range(1, 31)),
       False)


def test_interval_rules():
    """"Every 4 weeks from the 7th" -- a cadence neither weekly nor monthly can
    express. "Every 4th Sunday" is NOT the same thing: that one gaps to five
    weeks across some month boundaries, an interval never varies."""
    import reminders
    head = ('"Title","Time","Mon","Tue","Wed","Thu","Fri","Sat","Sun",'
            '"nth","Every","Starting","Months"')
    csv = "\n".join([
        head,
        '"Bins","7:00 AM","","","","","","","","","4 weeks","2026-09-07",""',
        '"Haircut","10:00 AM","","","","","","","","","6 weeks","9/12/2026",""',
        '"Water","8:00 AM","","","","","","","","","3 days","2026-09-01",""',
        '"Later","9:00 AM","","","","","","","","","2 weeks","2026-12-01",""',
        '"Half","9:00 AM","","","","","","","","","4 weeks","",""',
        '"Seasonal","9:00 AM","","","","","","","","","1 week","2026-01-05","Jun"'])
    by = {r["title"]: r for r in reminders.read_rules(csv)}

    ok("weeks become days", by["Bins"]["every"], 28)
    ok("and the anchor parses", by["Bins"]["start"], dt.date(2026, 9, 7))
    ok("a US-formatted date parses too -- Sheets renders dates by locale",
       by["Haircut"]["start"], dt.date(2026, 9, 12))

    def fires(title, iso):
        return reminders.fires_on(by[title], dt.date.fromisoformat(iso))

    true("fires on the anchor itself", fires("Bins", "2026-09-07"))
    ok("not a week later", fires("Bins", "2026-09-14"), False)
    true("four weeks later", fires("Bins", "2026-10-05"))
    true("and again, across a month end", fires("Bins", "2026-11-02"))
    true("a day interval works", fires("Water", "2026-09-04"))
    ok("and not between", fires("Water", "2026-09-05"), False)

    ok("nothing fires before its anchor", fires("Later", "2026-09-01"), False)
    true("but does once it arrives", fires("Later", "2026-12-01"))

    # Half a rule is no rule -- and must say so rather than doing nothing.
    ok("Every with no Starting does not fire",
       fires("Half", "2026-09-07"), False)
    ok("and is reported", by["Half"]["unreadable"], True)

    # Months still gates, so an interval can have a season.
    ok("an interval outside its months is silent",
       fires("Seasonal", "2026-09-07"), False)

    ok("a bare number is not a unit", reminders.parse_every("4"), None)
    ok("weeks", reminders.parse_every("4 weeks"), 28)
    ok("shorthand", reminders.parse_every("2w"), 14)
    ok("days", reminders.parse_every("10 days"), 10)


def test_reminder_render():
    import reminders
    rules = _rules()
    today = dt.date(2026, 8, 30)
    data = {"today": today, "days": reminders.upcoming(rules, today),
            "count": len(rules), "error": None, "sheet": "abc"}
    html = reminders.render(data)

    # Tied to the constant, not to the number 8: the horizon is a setting and
    # a test that hard-codes it just has to be edited every time it moves.
    ok("the horizon is however many days DAYS_SHOWN says",
       html.count('class="rday"'), reminders.DAYS_SHOWN)
    ok("and that is currently eight", reminders.DAYS_SHOWN, 8)
    true("the page and its JS agree on the horizon",
         "DAYS=%d," % reminders.DAYS_SHOWN in reminders.page_js(data))
    true("today is named, not dated", "<h2>Today</h2>" in html)
    # Only today is named. "Tomorrow" sat oddly above a column of real dates.
    true("every other day carries its date",
         "<h2>Monday, Aug 31</h2>" in html)
    true("including the one after that", "<h2>Tuesday, Sep 1</h2>" in html)
    ok("nothing says Tomorrow any more", "Tomorrow" in html, False)
    true("no counts in the headings -- he does not want them",
         "<b>" not in html)

    # Every day in the window happens to be busy now, so make a quiet one.
    quiet = {"today": today, "days": [(today, [])], "count": 0,
             "error": None, "sheet": "abc"}
    true("a quiet day says so", "Nothing." in reminders.render(quiet))
    true("times read as clock times", ">12:30 pm<" in html)
    true("the page says it does not send anything",
         "notifications are sent by the sheet, not this page" in html)

    ok("a broken sheet renders an error, not a traceback",
       'class="rerr"' in reminders.render(
           {"today": today, "days": [], "count": 0, "error": "boom"}), True)

    js = reminders.page_js(data)
    true("the sheet id reaches the browser code", '"abc"' in js)
    true("no unreplaced placeholders", "%%" not in js)


def test_done_ticks():
    """Ticks live in the Sheet, not localStorage -- that one decision is what
    makes them sync across devices AND stop the notification."""
    import reminders
    done = reminders.read_done(
        open(os.path.join(HERE, "fixtures", "reminders-done.csv"),
             encoding="utf-8").read())
    ok("only rows with the Done column set count",
       sorted(done), [("2026-08-31", "Odd marks@07:15"), ("2026-09-01", "Rent@09:00")])

    # Asking for a tab that does not exist returns the FIRST tab, so without a
    # header check the reminders themselves would parse as ticks.
    reminders_csv = open(os.path.join(HERE, "fixtures", "reminders.csv"),
                         encoding="utf-8").read()
    ok("the reminders tab is not mistaken for the Done tab",
       reminders.read_done(reminders_csv), set())
    ok("an empty response is no ticks", reminders.read_done(""), set())

    ok("the key is title@HH:MM, zero padded",
       reminders.done_key({"title": "Laundry", "at": (9, 5)}), "Laundry@09:05")


def test_done_render():
    import reminders
    os.environ["KMONEY_REMINDERS_CSV"] = os.path.join(HERE, "fixtures", "reminders.csv")
    os.environ["KMONEY_REMINDERS_DONE"] = os.path.join(HERE, "fixtures",
                                                       "reminders-done.csv")
    try:
        data = reminders.build(today="2026-08-31", cfg=CFG)
    finally:
        os.environ.pop("KMONEY_REMINDERS_CSV", None)
        os.environ.pop("KMONEY_REMINDERS_DONE", None)

    today_rows = data["days"][0][1]
    marks = {r["title"]: r.get("done") for r in today_rows}
    ok("the ticked one is marked", marks["Odd marks"], True)
    ok("an untouched one is not", marks["Standup"], False)

    html = reminders.render(data)
    ok("a checkbox per row due today",
       html.count('type="checkbox"'), len(today_rows))
    ok("one of them is checked", html.count(" checked>"), 1)
    true("the ticked row is struck through", 'class="rem tick done"' in html)
    # Rent is ticked for TOMORROW in the fixture, and must not render a box:
    # ticking ahead would silence a notification a day early.
    true("only today is tickable",
         html.count('type="checkbox"') == len(today_rows))
    true("the web app url reaches the browser code",
         "example.invalid" in reminders.page_js(data))
    true("no unreplaced placeholders", "%%" not in reminders.page_js(data))

    # Today's unticked rows are shaded the Church orange. This is CSS alone --
    # `.tick` is only ever on today's rows and `.done` is already toggled by
    # the checkbox handler, so ticking clears the shading with no JS involved,
    # and a future day (no `.tick`) is never shaded at all.
    true("the shading targets today's unticked rows only",
         "label.rem.tick:not(.done){" in reminders.CSS)
    true("it is the Church orange, not a second one",
         ui.wash(ui.COLORS["orange"]) in reminders.CSS)
    true("laid over the card, like the Church rows",
         "linear-gradient(%s,%s),var(--card)"
         % (ui.wash(ui.COLORS["orange"]), ui.wash(ui.COLORS["orange"]))
         in reminders.CSS)
    # The wash carries it alone here. Church stripes because it has several
    # colours to tell apart; this tab has one, so a stripe distinguished
    # nothing and he asked for it gone.
    true("no leading stripe on a reminder", "border-left" not in reminders.CSS)
    true("no placeholder survived the CSS substitution",
         "%(wash)s" not in reminders.CSS)


def test_afternoon_gap():
    """A day reads as day then evening, so the first thing at or after
    AFTERNOON_HOUR gets space above it -- but only when something came before
    it. Written against the constant, not the number, so moving the hour does
    not mean rewriting the test."""
    import reminders
    at = lambda h, m=0: {"at": (h, m)}
    cut = reminders.AFTERNOON_HOUR
    ok("the cut is currently 4pm", cut, 16)

    due = [at(7), at(9, 5), at(cut), at(cut + 4)]
    ok("the first row at the cut opens the evening",
       [reminders.starts_afternoon(due, i) for i in range(4)],
       [False, False, True, False])
    ok("the minute before the cut is still the day",
       reminders.starts_afternoon([at(cut - 1, 30), at(cut)], 1), True)
    # 1pm used to be the cut. It must now be on the earlier side of it,
    # otherwise the hour did not really move.
    ok("1pm no longer opens anything",
       reminders.starts_afternoon([at(9), at(13)], 1), False)
    ok("an evening-only day gets no stray gap at the top",
       [reminders.starts_afternoon([at(cut + 1), at(cut + 4)], i)
        for i in range(2)], [False, False])
    ok("a day that ends before the cut gets none either",
       [reminders.starts_afternoon([at(7), at(9)], i) for i in range(2)],
       [False, False])
    ok("only the FIRST row past the cut gets it",
       [reminders.starts_afternoon([at(9), at(cut), at(cut + 1), at(cut + 2)], i)
        for i in range(4)], [False, True, False, False])
    true("the browser copy is given the same hour",
         "PMHOUR=%d;" % cut in reminders.page_js(
             {"today": "2026-08-30", "days": [], "sheet": "s",
              "webapp": "", "error": None}))


def test_teams_text():
    """The matchup line, and the two conventions that make it read wrong if
    you get them backwards."""
    import teams
    home = {"homeAway": "home", "team": {"displayName": "Michigan Wolverines"},
            "curatedRank": {"current": 16}}
    away = {"homeAway": "away", "team": {"displayName": "Iowa Hawkeyes"},
            "curatedRank": {"current": 99}}

    # Every sport but soccer is away AT home; soccer prints the home side
    # first. Swap them and every row reads backwards, silently.
    ok("college is away at home", teams.matchup(home, away, False, False),
       "Iowa Hawkeyes at #16 Michigan Wolverines")
    ok("soccer is home first", teams.matchup(home, away, True, False),
       "#16 Michigan Wolverines vs. Iowa Hawkeyes")
    # "at" means the second team is hosting. On a neutral field nobody is.
    ok("a neutral site is vs, not at",
       teams.matchup(home, away, False, True),
       "Iowa Hawkeyes vs. #16 Michigan Wolverines")
    # The rows are built from the parts, not by splitting the sentence back up.
    ok("the parts drive the two lines",
       [teams.side_name(p) if not isinstance(p, str) else p
        for p in teams.matchup_parts(home, away, False, False)],
       ["Iowa Hawkeyes", "at", "#16 Michigan Wolverines"])
    ok("soccer swaps which team leads",
       [teams.side_name(p) if not isinstance(p, str) else p
        for p in teams.matchup_parts(home, away, True, False)],
       ["#16 Michigan Wolverines", "vs.", "Iowa Hawkeyes"])
    # 99 is ESPN's "unranked", not a 99th-ranked team.
    ok("rank 99 is not a rank", teams.rank_of(away), None)
    ok("a real rank is kept", teams.rank_of(home), 16)


def test_teams_network():
    """One network, national only, streaming named last."""
    import teams
    sb = lambda *n: {"broadcasts": [{"market": "national", "names": list(n)}]}
    ok("the scoreboard shape is read", teams.pick_network(sb("FOX")), "FOX")
    # Both endpoints are used, and they encode this differently.
    ok("the schedule shape is read too", teams.pick_network(
        {"broadcasts": [{"market": {"type": "National"},
                         "media": {"shortName": "NBC"}}]}), "NBC")
    # A match on USA and Peacock is a USA game.
    ok("real television beats streaming",
       teams.pick_network(sb("Peacock", "USA Net")), "USA")
    ok("streaming stands when it is the only way to watch",
       teams.pick_network(sb("Peacock")), "Peacock")
    ok("ESPN's spelling is corrected", teams.pick_network(sb("USA Net")), "USA")
    ok("a simulcast is named once", teams.pick_network(sb("TBS", "truTV")), "TBS")
    ok("hidden feeds do not count", teams.pick_network(sb("TUDN")), None)
    # A regional-only game shows nothing, which is honest: that feed is only
    # useful if you happen to get it.
    ok("a regional broadcast is not a network",
       teams.pick_network({"broadcasts": [{"market": "home", "names": ["BTN"]}]}),
       None)
    ok("no broadcast at all is None", teams.pick_network({}), None)


def test_teams_colour():
    """The stripe is the OPPONENT's colour, and the rules are sports-daily's --
    copied deliberately, not reinvented."""
    import teams
    ok("a usable primary is used",
       teams.stripe_color({"color": "c41230", "alternateColor": "ffffff"}),
       "#c41230")
    # That is how the Steelers become gold rather than a stripe you cannot see.
    ok("black falls through to the alternate",
       teams.stripe_color({"color": "000000", "alternateColor": "ffb612"}),
       "#ffb612")
    ok("white falls through too",
       teams.stripe_color({"color": "ffffff", "alternateColor": "1c4587"}),
       "#1c4587")
    ok("no colour is no stripe", teams.stripe_color({}), None)

    # An override wins outright: ESPN's primary is not always the one people
    # picture, and Syracuse comes back navy rather than orange.
    ok("an override beats everything",
       teams.stripe_color({"displayName": "Syracuse Orange", "color": "0c2340"},
                          {"Syracuse": "f76900"}), "#f76900")
    ok("and it matches on part of the name",
       teams.stripe_color({"displayName": "Michigan Wolverines", "color": "00274c"},
                          {"Michigan Wolverines": "ffcb05"}), "#ffcb05")

    # Brightness alone is the wrong question. Brighton's #0606fa scores a
    # luminance of 24 -- darker than a navy -- and is a vivid blue anyone can
    # see; what separates them is the strongest channel.
    true("a vivid blue is not invisible", not teams.invisible_colour("0606fa"))
    true("a navy is", teams.invisible_colour("0c2340"))
    true("black is", teams.invisible_colour("000000"))
    true("a purple of the same darkness is not",
         not teams.invisible_colour("4b2e83"))
    # Saturation is what separates white from a pale but real colour.
    true("silver reads as white", teams.washed_out("c4ced4"))
    true("Leeds' yellow does not", not teams.washed_out("ffcd00"))
    true("white does", teams.washed_out("ffffff"))

    # The fallback order is sports-daily's: a colour that SHOWS, then any
    # colour that is not washed out, then whatever is left. Tottenham's real
    # pair is white and a navy darker than the card -- so the navy wins the
    # second pass, which is the same answer sports-daily gives.
    ok("a non-washed-out colour beats a washed-out one, even when dark",
       teams.stripe_color({"color": "ffffff", "alternateColor": "0b1426"}),
       "#0b1426")
    ok("something beats nothing when neither shows",
       teams.stripe_color({"color": "ffffff", "alternateColor": "000000"}),
       "#000000")


def test_teams_shared_colours():
    """The master list, shared with sports-daily and standings."""
    import teams
    ok("a Colors tab parses", teams.read_colors(
        '"Team","Color"\n"Michigan Wolverines","f5b400"'),
       {"Michigan Wolverines": "f5b400"})
    ok("a leading hash is fine", teams.read_colors(
        '"Team","Color"\n"X","#ff0000"'), {"X": "ff0000"})
    ok("columns are found by name, in any order", teams.read_colors(
        '"Color","Team"\n"f5b400","X"'), {"X": "f5b400"})
    ok("a value that is not a colour is skipped", teams.read_colors(
        '"Team","Color"\n"X","nope"\n"Y","00ff00"'), {"Y": "00ff00"})

    # THE trap this project keeps hitting: asking Google for a tab that does
    # not exist hands back the FIRST tab. Without the header check, a Sheet
    # with no Colors tab would be read as if the reminders were team colours.
    # This is the real header off his sheet.
    ok("the reminders tab is not mistaken for colours", teams.read_colors(
        '"Title DAILY","Time ","Mon "\n"Laundry","12:30 PM","x"'), {})
    ok("an empty response is no colours", teams.read_colors(""), {})
    # Google Sheets reads an all-digit cell as a NUMBER and eats the leading
    # zero, so Penn State's 061440 came back as 61440 and the row vanished.
    # Only values with no letters in them are affected, which is why 0a2240
    # survived and this did not.
    ok("a leading zero eaten by Sheets is put back", teams.read_colors(
        '"Team","Color"\n"Penn State","61440"'), {"Penn State": "061440"})
    ok("a value with letters is untouched", teams.read_colors(
        '"Team","Color"\n"X","0a2240"'), {"X": "0a2240"})

    # config.json is the FALLBACK, not the source: three sites read this list,
    # and a Sheet outage must not be able to break all three at once.
    conf = {"team_colors": {"Michigan Wolverines": "ffcb05", "Keep": "111111"},
            "colors_tab": "Colors"}
    cfg = {"reminders_sheet": "SHEET"}
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "colors.csv")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('"Team","Color"\n"Michigan Wolverines","f5b400"\n')
        os.environ["KMONEY_COLORS_CSV"] = path
        try:
            merged = teams.color_overrides(cfg, conf)
        finally:
            os.environ.pop("KMONEY_COLORS_CSV", None)

        ok("the Sheet wins where it has an opinion",
           merged["Michigan Wolverines"], "f5b400")
        ok("and the committed list survives where it does not",
           merged["Keep"], "111111")

        os.environ["KMONEY_COLORS_CSV"] = os.path.join(tmp, "gone.csv")
        try:
            fallback = teams.color_overrides(cfg, conf)
        finally:
            os.environ.pop("KMONEY_COLORS_CSV", None)
    ok("an unreachable Sheet falls back to the committed list",
       fallback["Michigan Wolverines"], "ffcb05")
    ok("no sheet configured is just the committed list",
       teams.color_overrides({}, conf)["Keep"], "111111")


def test_teams_marquee():
    """The showcase windows, matched on network AND kickoff together."""
    import teams
    cfb = [{"networks": ["FOX"], "days": ["Sat"], "from": "11:30", "to": "12:30"},
           {"networks": ["NBC", "ABC"], "days": ["Sat"], "from": "19:00",
            "to": "20:00"}]
    at = lambda d, h, m=0: dt.datetime(2026, 9, d, h, m)

    true("FOX at noon on a Saturday", teams.is_marquee(at(5, 12), "FOX", cfb))
    true("NBC on a Saturday night", teams.is_marquee(at(5, 19, 30), "NBC", cfb))
    # The same channel carries ordinary games at other hours -- matching on the
    # network alone would light up half the season and say nothing.
    true("FOX at 3:30 is not the window",
         not teams.is_marquee(at(5, 15, 30), "FOX", cfb))
    true("noon on a Thursday is not either",
         not teams.is_marquee(at(3, 12), "FOX", cfb))
    true("nor is another channel in the same hour",
         not teams.is_marquee(at(5, 12), "BTN", cfb))
    true("the edges of the range count", teams.is_marquee(at(5, 11, 30), "FOX", cfb))
    true("a minute past the range does not",
         not teams.is_marquee(at(5, 12, 31), "FOX", cfb))
    true("no network, no marquee", not teams.is_marquee(at(5, 12), None, cfb))
    true("no windows, no marquee", not teams.is_marquee(at(5, 12), "FOX", []))


def test_teams_rounds():
    """Cup rounds live in season.slug, not in a note."""
    import teams
    ok("a cup round is spelled out", teams.round_tag("third-round"), "Third Round")
    ok("Europe's long rounds are shortened", teams.round_tag("round-of-16"), "R16")
    ok("MLS keeps only the tail",
       teams.round_tag("eastern-conference-playoffs---round-one"), "Round One")
    ok("'proper' is dropped", teams.round_tag("third-round-proper"), "Third Round")
    ok("a league slug is not a round", teams.round_tag("2026-2027"), "")
    ok("no slug, no round", teams.round_tag(None), "")

    # A note headline wins: that is where college keeps "Big Ten Tournament".
    ok("a note headline names the competition",
       teams.competition_label({}, {"notes": [{"headline": "Big Ten Tournament"}]},
                               "College Basketball"), "Big Ten Tournament")
    ok("otherwise the league plus its round",
       teams.competition_label({"season": {"slug": "semifinals"}}, {}, "Carabao Cup"),
       "Carabao Cup - Semifinals")
    ok("a league match is just the league",
       teams.competition_label({"season": {"slug": "2026-2027"}}, {},
                               "Premier League"), "Premier League")


def test_teams_weeks():
    """Weeks start on Monday, blanks are kept, and the summer does not open on
    a dozen empty headings."""
    import teams
    ok("Monday is its own week start",
       teams.week_start(dt.date(2026, 8, 31)), dt.date(2026, 8, 31))
    ok("Sunday belongs to the week that began six days earlier",
       teams.week_start(dt.date(2026, 9, 6)), dt.date(2026, 8, 31))
    ok("the heading names the Monday",
       teams.week_heading(dt.date(2026, 9, 7)), "Week of September 7")

    def game(day):
        when = teams.local(day + "T18:00")
        return {"id": day, "day": when.date(), "at": when, "title": "x",
                "competition": "c", "network": None, "time": "1:00 PM",
                "stripe": None, "wash": "#ffcb05", "logos": [], "past": False}

    rows = [game("2026-09-05"), game("2026-09-26")]
    spans = [("2026-08-22", "2027-02-01")]
    weeks = teams.into_weeks(rows, dt.date(2026, 9, 1), spans)
    ok("every week from this one to the last game",
       [str(m) for m, _ in weeks],
       ["2026-08-31", "2026-09-07", "2026-09-14", "2026-09-21"])
    # A bye week is information. Skipping it would make the list lie about how
    # far apart two games are.
    ok("blank weeks are kept", [len(g) for _, g in weeks], [1, 0, 0, 1])

    # A game with no announced kickoff is stamped MIDNIGHT by ESPN, so sorting
    # on the timestamp alone floats it above games that actually start earlier
    # in the day. It is not the first game, it is the unscheduled one.
    day = teams.local("2026-09-05T16:00")
    midnight = teams.local("2026-09-05T04:00")
    same_day = [
        dict(game("2026-09-05"), id="tbd", title="TBD one", at=midnight,
             day=midnight.date(), timed=False),
        dict(game("2026-09-05"), id="noon", title="Noon one", at=day,
             day=day.date(), timed=True)]
    ordered = teams.into_weeks(same_day, dt.date(2026, 9, 1), spans)[0][1]
    ok("a TBD sits below the games with a time",
       [r["title"] for r in ordered], ["Noon one", "TBD one"])

    # Out of season -- June -- the run starts at the next fixture instead of a
    # dozen empty headings waiting for August.
    summer = teams.into_weeks(rows, dt.date(2026, 6, 10), spans)
    ok("outside the season it opens on the next game",
       str(summer[0][0]), "2026-08-31")
    ok("in season it opens on this week", str(weeks[0][0]), "2026-08-31")
    ok("no games, no weeks", teams.into_weeks([], dt.date(2026, 9, 1), spans), [])

    ok("in_season reads the anchor calendars",
       [teams.in_season(spans, dt.date(2026, 9, 1)),
        teams.in_season(spans, dt.date(2026, 6, 10))], [True, False])


def test_teams_normalize():
    """One ESPN event to one row, including what must NOT become a row."""
    import teams
    sport = {"path": "football/college-football", "label": "College Football"}
    follow = {"id": "130", "wash": "#ffcb05"}
    event = {
        "id": "401", "date": "2026-09-26T04:00Z", "timeValid": False,
        "seasonType": {"id": "2"},
        "competitions": [{
            "broadcasts": [], "notes": [],
            "competitors": [
                {"homeAway": "home", "curatedRank": {"current": 16},
                 "team": {"id": "130", "displayName": "Michigan Wolverines",
                          "logos": [{"href": "m.png"}]}},
                {"homeAway": "away", "curatedRank": {"current": 22},
                 "team": {"id": "2294", "displayName": "Iowa Hawkeyes",
                          "logos": [{"href": "i.png"}]}}]}]}
    row = teams.normalize(event, sport, follow, dt.date(2026, 9, 1),
                          {"2294": {"color": "ffcd00", "alternateColor": "000000"}})
    ok("both ranks show", row["title"],
       "#22 Iowa Hawkeyes at #16 Michigan Wolverines")
    # The schedule endpoint returns colours as null, so the opponent's stripe
    # has to be looked up from the league's team list.
    ok("the opponent's colour is filled in from the team list",
       row["stripe"], "#ffcd00")
    ok("the wash is the followed team's", row["wash"], "#ffcb05")
    # ESPN stamps an unscheduled kickoff at midnight and flags it. Without the
    # flag this reads "12:00 AM", which looks like a real midnight fixture.
    ok("an unset kickoff is TBD, not midnight", row["time"], "TBD")
    ok("but the day is still right", str(row["day"]), "2026-09-26")
    # sports-daily's rule: the -dark variant reads on a dark page, and each
    # crest carries the plain URL to fall back to because not every team has
    # one on the CDN.
    ok("the dark crest is preferred, with the plain one to fall back to",
       [tuple(x) for x in row["logos"]],
       [("i.png", "i.png"), ("m.png", "m.png")])
    true("a future game is not past", not row["past"])

    played = dict(event, date="2026-08-30T16:00Z", timeValid=True)
    ok("a game already played is marked",
       teams.normalize(played, sport, follow, dt.date(2026, 9, 1), {})["past"],
       True)

    # He asked for exhibitions and friendlies out.
    exhibition = dict(event, seasonType={"id": "1"})
    ok("a preseason exhibition is dropped",
       teams.normalize(exhibition, sport, follow, dt.date(2026, 9, 1), {}), None)
    friendly = json.loads(json.dumps(event))
    friendly["competitions"][0]["type"] = {"abbreviation": "FRIENDLY"}
    ok("a friendly is dropped",
       teams.normalize(friendly, sport, follow, dt.date(2026, 9, 1), {}), None)

    # A competition neither followed team is in should never reach the page.
    other = json.loads(json.dumps(event))
    for c in other["competitions"][0]["competitors"]:
        c["team"]["id"] = "999"
    ok("someone else's game is dropped",
       teams.normalize(other, sport, follow, dt.date(2026, 9, 1), {}), None)


def test_teams_render():
    """The tab renders from canned rows -- no network, no API key."""
    import teams
    os.environ["KMONEY_TEAMS_JSON"] = os.path.join(HERE, "fixtures", "teams.json")
    try:
        data = teams.build(today="2026-08-29")
    finally:
        os.environ.pop("KMONEY_TEAMS_JSON", None)
    html = teams.render(data)

    ok("a heading per week", html.count('class="wk"'), len(data["weeks"]))
    ok("a row per game", html.count('class="gm'), 4)
    true("weeks are named for their Monday", "<h2>Week of August 24</h2>" in html)
    true("an empty week says so", "No games." in html)
    # Three rows now: the date belongs to the first team's line, the time to
    # the second's, and the competition and network share the third.
    true("the date sits on the first team's line",
         '<span class="r d">Sat Aug 29</span>' in html)
    true("the time sits on the second team's line",
         '<span class="r t">7:30 PM</span>' in html)
    ok("a connector per row", html.count('class="j"'), 4)
    true("college reads away at home", '>Fresno State Bulldogs <span class="j">at<' in html)
    true("soccer reads home first", '>Nottingham Forest <span class="j">vs.<' in html)
    ok("a competition and a network cell per row",
       [html.count('class="c"'), html.count('class="net')], [4, 4])
    true("a game with no network leaves that cell empty",
         '<span class="net"></span>' in html)
    # Matched on network AND kickoff: NBC at 7:30 on a Saturday is the window,
    # Peacock inside the same hour is not.
    ok("only the marquee game is blue", html.count('class="net marquee"'), 1)
    true("and it is the NBC one",
         '<span class="net marquee">NBC</span>' in html)
    true("the wash is laid over the card, as on the other tabs",
         "linear-gradient(var(--wash),var(--wash)),var(--card)" in teams.CSS)
    ok("every row carries a wash", html.count("--wash:"), 4)
    # Yellow needs more of itself than blue does: at the 13% the other tabs
    # use, every yellow reads brown against this card. So the strength is per
    # team, not global -- ui.WASH still drives Church and Reminders.
    # Strength is per team and still supported, even though both teams sit on
    # the shared 13% today -- yellow needed 28% until he tuned it on his phone.
    true("a team can set its own wash strength",
         "rgba(255,203,5,0.28)" in html)
    true("and one that does not keeps the shared strength",
         "rgba(61,142,224,0.13)" in html)
    # A washed row is a lighter ground, so the ordinary muted grey loses
    # contrast on it -- 4.33 against maize at 13%, just under readable.
    true("the quiet line is lifted on a washed row",
         ".gm.tint .c,.gm.tint .net{color:#a3a39d}" in teams.CSS)
    ok("and a stripe where the opponent has a usable colour",
       html.count("--tint:"), 4)
    true("both logos are drawn", html.count("<img") >= 8)
    true("logos are lazy", 'loading="lazy"' in html)

    empty = teams.render({"today": dt.date(2026, 9, 1), "weeks": [], "error": None})
    true("nothing scheduled says so", "Nothing scheduled." in empty)
    true("a broken fetch renders an error, not a traceback",
         'class="rerr"' in teams.render(
             {"today": dt.date(2026, 9, 1), "weeks": [], "error": "boom"}))


def test_tasks():
    """Dated to-dos that roll over until they are done. A different model from
    Reminders: a reminder is a schedule and does not come back if ignored, a
    task is an open item and does."""
    import tasks
    text = open(os.path.join(HERE, "fixtures", "tasks.csv"),
                encoding="utf-8").read()
    today = dt.date(2026, 8, 29)
    days, undated, unknown = tasks.read_tasks(text, today)

    ok("open tasks group by the day they show on",
       [str(d) for d, _ in days], ["2026-08-29", "2026-09-04"])

    # THE ROLLOVER. Two overdue tasks and two due today all land on today --
    # nothing falls off the list by being ignored.
    ok("overdue tasks roll forward onto today",
       [t["task"] for t in days[0][1]],
       ["Renew car tabs", "Send the Q3 deck", "Book the flights",
        "Call the dentist"])
    # Oldest first, then alphabetical -- so the two due today read in a stable
    # order rather than in whatever order the sheet happens to list them.
    ok("and they sort oldest first inside the day",
       [str(t["due"]) for t in days[0][1]],
       ["2026-08-20", "2026-08-28", "2026-08-29", "2026-08-29"])
    ok("how late each one is, is known even though it is not shown",
       [t["late"] for t in days[0][1]], [9, 1, 0, 0])
    ok("a future task stays on its own day",
       [t["task"] for t in days[1][1]], ["Water the plants"])

    flat = [t["task"] for _, ts in days for t in ts]
    # Any mark at all closes it: a tick, an x, or the date the app stamps.
    true("a done task is gone", "Expense report" not in flat)
    true("a row with no task is skipped", "" not in flat)
    # A date is required, so one without a date must be NAMED rather than
    # silently dropped -- otherwise it looks like the row was never added.
    ok("an undated task is reported", undated, ["No due date"])
    ok("an unrecognised column is reported", unknown, ["notes"])

    # The key is Task@Due, built identically in the Apps Script. Row position
    # cannot be the key: sorting the sheet would repoint every tick.
    ok("the key is the task and its due date",
       days[0][1][0]["key"], "Renew car tabs@2026-08-20")
    ok("and it does not move when the task rolls over",
       tasks.task_key("Renew car tabs", dt.date(2026, 8, 20)),
       "Renew car tabs@2026-08-20")

    # Categories colour themselves, so a new one typed on his phone needs no
    # commit here. Deterministic, not first-seen: arrival order would make the
    # tab recolour itself the moment a row was inserted above another.
    work = tasks.category_color("Work")
    ok("the same category always gets the same colour",
       tasks.category_color("Work"), work)
    ok("case does not change it", tasks.category_color("work"), work)
    true("a different category gets a different one",
         tasks.category_color("Personal") != work)
    true("every assigned colour is from the shared palette",
         work in ui.COLORS.values())
    ok("no category is no colour", tasks.category_color(""), None)
    ok("config can override one",
       tasks.category_color("Work", {"work": "red"}), ui.COLORS["red"])
    # Deriving from the name means two names CAN land on the same colour, and
    # two of his four did: Blog and Personal both came out pink. His live four
    # must stay distinct, so the config pin is asserted rather than assumed.
    import watch as _w
    live = _w.load_config()
    over = {k.lower(): v for k, v in (live.get("task_colors") or {}).items()}
    mine = [tasks.category_color(n, over)
            for n in ("Work", "Personal", "Blog", "Church")]
    ok("his four categories are four different colours",
       len(set(mine)), 4)
    ok("and Blog is the pinned one", mine[2], ui.COLORS["blue"])
    true("which it would not be without the pin",
         tasks.category_color("Blog") == tasks.category_color("Personal"))

    data = {"today": today, "days": days, "undated": undated,
            "unknown": unknown, "error": None, "sheet": "S", "tab": "Tasks",
            "webapp": "https://example.invalid/exec", "overrides": {}}
    html = tasks.render(data)
    ok("a heading per day", html.count('class="tday"'), 2)
    ok("a checkbox per open task", html.count('type="checkbox"'), 5)
    true("today is named, not dated", "<h2>Today</h2>" in html)
    true("the undated one is named on the page", "No due date" in html)
    true("there is a way to add one without opening the Sheet",
         'id="tform"' in html and 'type="date"' in html)
    # Silently, by his choice -- a thing dodged for a fortnight looks like
    # anything else on the list.
    true("nothing says how late a task is", "late" not in html)
    ok("a category renders as a colour", html.count("--tint:"), 4)
    true("and as a label", '<span class="cat">Work</span>' in html)

    empty = tasks.render({"today": today, "days": [], "undated": [],
                          "unknown": [], "error": None})
    true("an empty list says so", "Nothing to do." in empty)
    # Before the tab exists Google hands back the FIRST tab, the header check
    # refuses it, and "no task column" would be a poor first impression.
    first_run = tasks.render({"today": today, "days": [], "undated": [],
                              "unknown": [], "error": None, "missing": True})
    true("a missing tab explains itself rather than erroring",
         "No Tasks tab" in first_run and 'class="rerr"' not in first_run)
    true("and still offers the form that creates it", 'id="tform"' in first_run)
    true("a broken tab renders an error, not a traceback",
         'class="rerr"' in tasks.render(
             {"today": today, "days": [], "error": "boom"}))

    try:
        tasks.read_tasks('"Nope","Nah"\n"x","y"', today)
        ok("a wrong header is refused", "no error", "SheetError")
    except Exception:
        ok("a wrong header is refused", "SheetError", "SheetError")

    # The browser copy has to agree with this one, or an added task shows up
    # differently until tomorrow's build.
    js = tasks.page_js(data)
    true("the browser gets the sheet and the tab", '"Tasks"' in js)
    true("and the endpoint that writes", "example.invalid" in js)
    true("no unreplaced placeholders", "%%" not in js)
    true("the browser rolls over too", "due<now?now:due" in js)
    true("it skips done rows as well", "at.done" in js)
    true("ticking writes through the web app", "action=task" in js)
    true("adding writes through the web app", "action=addtask" in js)
    true("the same palette reaches the browser",
         ui.COLORS["blue"] in js)
    # Google's CSV export lags a write by a few seconds, so re-reading straight
    # after an add returns the list WITHOUT it -- which reads as "it did not
    # save", the one thing this tab must never do. A new task is drawn from
    # what he typed, and dropped once the Sheet catches up.
    true("a new task is drawn before the Sheet agrees", "noteAdded(" in js)
    true("and dropped once the export catches up", "!seen[a.task" in js)
    true("the confirm window is wider than one try",
         "[1500, 4000, 9000]" in js)
    true("a pending add expires even if the Sheet never shows it", "3e5" in js)


def test_church():
    """Dated events, grouped, from today onward. Much simpler than Reminders:
    every row carries its own date, so there is no cadence to recompute and
    nothing for the Apps Script to stay in step with."""
    import church
    text = open(os.path.join(HERE, "fixtures", "church.csv"),
                encoding="utf-8").read()
    days, bad, unknown = church.read_events(text, dt.date(2026, 8, 30))

    ok("grouped by date, soonest first", [str(d) for d, _ in days],
       ["2026-09-08", "2026-09-20", "2026-10-13", "2026-10-14", "2026-10-15"])
    ok("two on the same day come through together",
       [e["title"] for e in days[1][1]],
       ["C Group: Lesson 1", "Sunday School: Lesson 2"])
    ok("US and ISO dates both parse",
       [e["title"] for e in days[2][1]], ["ISO form"])

    flat = [e["title"] for _, evs in days for e in evs]
    true("a past date is dropped", "Lead Worship" not in flat)
    true("a row with no date is dropped", "No date row" not in flat)
    true("a row with no title is dropped", "" not in flat)
    # A date we cannot read must be visible, not just absent -- otherwise the
    # event silently never appears.
    ok("an unreadable date is reported", bad, ["Bad date"])
    # Same reasoning one level up: a column heading nobody recognises means a
    # whole column is being ignored, which should not be invisible either.
    ok("an unrecognised column is reported", unknown, ["notes"])

    # Details and Color arrived BETWEEN Title and Date. Reading by position
    # would have taken the details for the date and dropped every row.
    ok("columns are found by name, not position",
       days[1][1][0]["details"], "Lesson 1")
    ok("a colour name becomes a hex", days[1][1][0]["color"], "#8b93a0")
    ok("colour names are case-insensitive",
       days[1][1][1]["color"], days[1][1][0]["color"])
    ok("a literal hex passes through", days[2][1][0]["color"], "#4488ff")
    ok("no colour is no stripe, not an error",
       days[3][1][0]["color"], None)
    ok("an unknown colour name is no stripe", days[4][1][0]["color"], None)
    # Repeating the title in Details renders the same line twice, which reads
    # as a bug rather than as detail.
    ok("details that repeat the title are dropped",
       days[0][1][0]["details"], "")

    html = church.render({"today": dt.date(2026, 8, 30), "days": days,
                          "unreadable": bad, "unknown": unknown, "error": None})
    # Prefix, not exact: most headings now carry an urgency class beside it.
    ok("a heading per day", html.count('class="cday'), 5)
    ok("an entry per event", html.count('class="cev'), 6)
    ok("only the coloured rows carry a stripe", html.count("--tint:"), 4)
    true("the stripe is the colour from the Sheet", '--tint:#8b93a0' in html)
    # The bubble is washed in the same colour, not just edged with it.
    ok("a wash goes with every stripe", html.count("--wash:"), 4)
    ok("the wash is the stripe colour, made faint",
       ui.wash("#8b93a0"), "rgba(139,147,160,0.13)")
    true("the wash is laid OVER the card, not instead of it -- a translucent "
         "colour on the page background would sit darker than a plain row",
         "linear-gradient(var(--wash),var(--wash)),var(--card)" in church.CSS)
    true("headings carry the date", "<h2>Tuesday, Sep 8</h2>" in html)
    true("the title is the big line", '<span class="t">ISO form</span>' in html)
    true("the details are the small line", '<span class="s">Lesson 1</span>' in html)
    true("a row with no details renders no second line",
         '<span class="t">Session Meeting</span></div>' in html)
    true("the bad row is named", "Bad date" in html)
    true("the unknown column is named", "Notes" in html or "notes" in html)
    true("no checkboxes here", "checkbox" not in html)

    # The heading colour says how close a day is without a date being read.
    # Orange inside a week, blue inside two, plain after that -- a page where
    # every heading is coloured would highlight nothing.
    day = dt.date(2026, 8, 30)
    ok("today and the week ahead are orange",
       [church.urgency(day + dt.timedelta(days=n), day) for n in (0, 1, 7)],
       ["soon", "soon", "soon"])
    ok("the second week is blue",
       [church.urgency(day + dt.timedelta(days=n), day) for n in (8, 14)],
       ["near", "near"])
    ok("past a fortnight there is no class at all",
       church.urgency(day + dt.timedelta(days=15), day), "")
    # The nav underline's own colour, not the row wash's orange -- that read
    # too bright for a heading -- and the same blue the Teams tab gives a rank.
    true("the near heading uses the nav accent",
         ".cday.soon h2{color:var(--accent)}" in church.CSS)
    true("and the second week the Teams rank blue",
         "color:%s" % church.RANK_BLUE in church.CSS)
    import teams
    ok("one blue across both tabs, not two",
       church.RANK_BLUE in teams.CSS, True)
    soon_html = church.render(
        {"today": day, "days": [(day, [{"title": "Now", "details": "",
                                        "color": None}]),
                                (day + dt.timedelta(days=10),
                                 [{"title": "Later", "details": "",
                                   "color": None}]),
                                (day + dt.timedelta(days=40),
                                 [{"title": "Far", "details": "",
                                   "color": None}])],
         "unreadable": [], "unknown": [], "error": None})
    ok("one heading of each kind reaches the page",
       [soon_html.count('class="cday soon"'), soon_html.count('class="cday near"'),
        soon_html.count('class="cday"')], [1, 1, 1])

    empty = church.render({"today": dt.date(2026, 8, 30), "days": [],
                           "unreadable": [], "unknown": [], "error": None})
    true("an empty list says so", "Nothing coming up." in empty)
    true("a broken tab renders an error, not a traceback",
         'class="rerr"' in church.render(
             {"today": dt.date(2026, 8, 30), "days": [], "error": "boom"}))

    try:
        church.read_events('"Nope","Nah"\n"x","y"', dt.date(2026, 8, 30))
        ok("a wrong header is refused", "no error", "SheetError")
    except Exception:
        ok("a wrong header is refused", "SheetError", "SheetError")

    # Only the two required columns are required. Dropping Details or Color
    # from the Sheet should cost those rows their extras, not the whole tab.
    bare, _, _ = church.read_events(
        '"Date","Title"\n"9/8/26","Bare"', dt.date(2026, 8, 30))
    ok("Title and Date can be in either order", bare[0][1][0]["title"], "Bare")
    ok("a missing Details column is not an error",
       bare[0][1][0]["details"], "")
    ok("a missing Color column is not an error", bare[0][1][0]["color"], None)


def test_maskable_icon():
    """The manifest promises "any maskable". Android then masks the icon to the
    launcher's shape and crops toward a circle of 80% diameter, so the artwork
    has to hold up its end: background to every corner, glyph inside that."""
    mod = shell()
    icons = mod.MANIFEST["icons"]
    ok("both declared icons are maskable",
       sorted(i["purpose"] for i in icons), ["any maskable"] * 2)
    ok("declared at the two sizes Android wants",
       sorted(i["sizes"] for i in icons), ["192x192", "512x512"])
    ok("declared as PNG", {i["type"] for i in icons}, {"image/png"})

    size = 128
    data = mod._png(size)
    true("it is a PNG", data.startswith(b"\x89PNG\r\n\x1a\n"))

    pixels = _decode(data, size)
    corners = [pixels(0, 0), pixels(size - 1, 0),
               pixels(0, size - 1), pixels(size - 1, size - 1)]
    ok("full bleed -- every corner is background", corners, [mod.BG] * 4)

    fg = [(x, y) for y in range(size) for x in range(size)
          if pixels(x, y) == mod.FG]
    true("there is a glyph at all", len(fg) > size * size * 0.04)
    centre = (size - 1) / 2.0
    worst = max(((x - centre) ** 2 + (y - centre) ** 2) ** 0.5 for x, y in fg)
    true("the glyph stays inside the 80%% safe zone (%.3f <= 0.400)"
         % (worst / size), worst / size <= 0.40)


def _decode(data, size):
    """Enough PNG reader to check our own output: no filtering, RGB, one IDAT."""
    import struct
    import zlib
    pos, idat = 8, b""
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        if data[pos + 4:pos + 8] == b"IDAT":
            idat += data[pos + 8:pos + 8 + length]
        pos += 12 + length
    raw = zlib.decompress(idat)
    stride = size * 3 + 1

    def at(x, y):
        off = y * stride + 1 + x * 3
        return tuple(raw[off:off + 3])
    return at


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
    ok("this year needs no year", ui.day_parts("2026-09-02", TODAY), ("Sep 2", "Wednesday"))
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
    true("the tab bar shows even with one tab", "<nav><button data-k=" in page)

    ok("tags balance", page.count("<div"), page.count("</div>"))
    ok("links balance", page.count("<a "), page.count("</a>"))
    ok("spans balance", page.count("<span"), page.count("</span>"))

    ok("every row is rendered", body.count('class="item'),
       len(data["rows"]) + len(data["pending"]))
    ok("the already-released row is dimmed", body.count('class="item past"'), 1)
    ok("the pending section is headed and counted",
       re.findall(r"<h2>Pending release date <b>(\d+)</b>", body),
       [str(len(data["pending"]))])
    # Was "the main list has no heading above it" -- the list used to be one
    # unbroken run on purpose. He asked for a Next 30 days section on
    # 2026-08-30, so three headings is now the shape, and a fourth appearing
    # means something grew a section nobody asked for.
    ok("three headings: near, far, undated",
       re.findall(r"<h2>([^<]*)", body),
       ["Next 30 days", "Upcoming", "Pending release date "])

    true("posters are lazy", 'loading="lazy"' in body)
    true("links open outward", 'rel="noopener"' in body)
    true("exactly one provider chip per row that has one",
         body.count("class=\"chip\"") <= body.count("class=\"item"))
    true("the episode name made it", "The Green Sea" in body)
    # "Season 3 Episode 1" behind "Lord of the Rings" runs past 375px. Measured
    # in the browser: with nowrap it truncated mid-word and ate the episode
    # number, which is the part of that line worth reading.
    true("the subtitle wraps rather than truncating",
         "white-space:nowrap" not in watch.CSS.split(".s{")[1].split("}")[0])
    # Was `"Episode 4" not in body`, which now matches the label itself since
    # S2 E4 spells out as "Season 2 Episode 4". What it was really testing is
    # that TMDB's filler NAME is not appended after the separator, so that is
    # what it tests now -- "Season 2 Episode 4 · Episode 4".
    true("filler episode names are still not appended", "· Episode" not in body)
    true("an undated row leaves its date column blank rather than reading TBA",
         "TBA" not in body)

    # An empty list must say so rather than render nothing at all.
    empty = watch.render({"today": TODAY, "rows": [], "pending": [], "tracked": 0})
    true("an empty list still says something", "Nothing scheduled." in empty)


def main():
    # Set for the WHOLE run, not per call site. The hand-added watchlist reads
    # a Google Sheet and remembers the ids it resolved in output/history --
    # both real, both live. Wiring this in at each build() call is one call
    # site away from a test that quietly reads the real list, or overwrites the
    # remembered ids with fixture ones.
    with tempfile.TemporaryDirectory() as tmp:
        sheet_watchlist_env(tmp)
        try:
            for name, fn in sorted(globals().items()):
                if name.startswith("test_"):
                    fn()
        finally:
            clear_watchlist_env()
    print("\n%d passed, %d failed" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
