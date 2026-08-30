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

    ok("seven days are shown", html.count('class="rday"'), 7)
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
         ui.COLORS["orange"] + ";" in reminders.CSS)
    true("laid over the card, like the Church rows",
         "linear-gradient(%s,%s),var(--card)"
         % (ui.wash(ui.COLORS["orange"]), ui.wash(ui.COLORS["orange"]))
         in reminders.CSS)
    # Every row carries the transparent edge, so shading one does not shunt its
    # contents 3px sideways.
    true("the coloured edge is reserved on every row",
         "border-left:4px solid transparent" in reminders.CSS)
    true("no placeholder survived the CSS substitution",
         "%(tint)s" not in reminders.CSS and "%(wash)s" not in reminders.CSS)


def test_afternoon_gap():
    """A day reads as morning then the rest, so the first thing at or after 1pm
    gets space above it -- but only when something came before it."""
    import reminders
    at = lambda h, m=0: {"at": (h, m)}
    due = [at(7), at(9, 5), at(13), at(20)]
    ok("the 1pm row opens the afternoon",
       [reminders.starts_afternoon(due, i) for i in range(4)],
       [False, False, True, False])
    ok("12:30 is still morning, 1:00 is not",
       reminders.starts_afternoon([at(12, 30), at(13)], 1), True)
    ok("an afternoon-only day gets no stray gap at the top",
       [reminders.starts_afternoon([at(14), at(20)], i) for i in range(2)],
       [False, False])
    ok("a morning-only day gets none either",
       [reminders.starts_afternoon([at(7), at(9)], i) for i in range(2)],
       [False, False])
    ok("only the FIRST afternoon row gets it",
       [reminders.starts_afternoon([at(9), at(13), at(14), at(15)], i)
        for i in range(4)], [False, True, False, False])


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
    ok("a heading per day", html.count('class="cday"'), 5)
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
