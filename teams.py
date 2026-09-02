"""The Teams tab: every remaining game for the teams worth following.

Michigan football, Michigan basketball and Tottenham, from ESPN's public API,
grouped into Monday-start weeks and running to the end of the season. No Google
Sheet and no live scores -- the daily build is the whole story.

Two endpoints, because neither is enough on its own:

* `teams/<id>/schedule` gives a college team's whole season in one small call,
  with AP rankings and broadcasts -- but its team colours are null.
* `scoreboard?dates=` gives colours, and is the only way to see a club across
  competitions: the team endpoint knows Tottenham's league and nothing else, so
  it would miss the Carabao Cup entirely.

Verified against the live API on 2026-09-01.
"""

import csv
import datetime as dt
import io
import json
import os
import re
import time

import ui

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")

KEY = "teams"
LABEL = "Teams"

SITE = "https://site.api.espn.com/apis/site/v2/sports/%s"
# ESPN 403s a browser-style User-Agent from a non-browser client but serves the
# requests default fine. Do NOT set one. (sports-daily learned this the hard
# way; the same rule applies here.)
UA = {"Accept": "application/json"}

UNRANKED = 99          # ESPN's curatedRank for "not ranked"
CACHE_MINUTES = 360    # the page rebuilds daily; fixtures do not move hourly


# --------------------------------------------------------------- fetching

def _cache_path(key):
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)
    return os.path.join(CACHE, safe + ".json")


def _get(path, params=None, cache_key=None):
    """GET one ESPN endpoint, through a disk cache. None on any failure.

    A failed fetch must not take the tab down -- an empty week is wrong but
    survivable, and `build` says so on the page.
    """
    import requests
    os.makedirs(CACHE, exist_ok=True)
    disk = _cache_path(cache_key) if cache_key else None
    if disk and os.path.exists(disk):
        if (time.time() - os.path.getmtime(disk)) / 60 < CACHE_MINUTES:
            try:
                with open(disk, encoding="utf-8") as fh:
                    return json.load(fh)
            except (OSError, ValueError):
                pass                      # corrupt cache: refetch
    try:
        r = requests.get(SITE % path, params=params, headers=UA, timeout=25)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        print("  ! espn fetch failed: %s (%s)" % (path, exc))
        if disk and os.path.exists(disk):
            print("    using stale cache")
            with open(disk, encoding="utf-8") as fh:
                return json.load(fh)
        return None
    if disk:
        with open(disk, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
    return data


# ----------------------------------------------------------------- season

def season_span(path):
    """(first day, last day) of a league's ACTUAL playing season, or None.

    From `leagues[0].calendar`, not `leagues[0].season`: the season block is an
    administrative window -- the Carabao Cup reports 1 June to 1 June, which
    would claim you are in season all summer. The calendar is the real matchday
    list (the Premier League's runs 2026-08-21 to 2027-05-30).
    """
    data = _get(path + "/scoreboard", cache_key="cal-" + path)
    cal = ((data or {}).get("leagues") or [{}])[0].get("calendar") or []
    days = []
    for entry in cal:
        if isinstance(entry, str):
            days.append(entry[:10])
        elif isinstance(entry, dict):
            for block in [entry] + list(entry.get("entries") or []):
                for field in ("startDate", "endDate"):
                    if block.get(field):
                        days.append(block[field][:10])
    if not days:
        return None
    return min(days), max(days)


def in_season(spans, today):
    """True when today falls inside any anchor league's calendar.

    Only the three league competitions are anchors. A cup's calendar is that
    administrative June-to-June window, so including one would make this always
    true and the summer would fill with empty week headings.
    """
    iso = today.isoformat()
    return any(lo <= iso <= hi for lo, hi in spans if lo and hi)


# ---------------------------------------------------------------- colours
# These three rules are sports-daily's, copied deliberately rather than
# reinvented -- a simple "is it bright enough" test throws away Brighton's
# #0606fa, which is a vivid blue with a luminance darker than a navy.

def _rgb(value):
    value = (value or "").lstrip("#")
    if len(value) != 6:
        return None
    try:
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def invisible_colour(value):
    """True when a colour reads as black on the page's own near-black ground.

    Brightness alone is the wrong question -- Indiana's crimson and Michigan
    State's green sit at the same luminance as a navy that vanishes. So a
    colour is only rejected when it is near-neutral, or a genuine navy: navy
    runs r < g < b, while a purple of the same darkness runs g < r < b and
    reads perfectly well.
    """
    parts = _rgb(value)
    if not parts:
        return False
    red, green, blue = parts
    # A vivid colour shows however dark the luminance figure says it is. Blue
    # contributes almost nothing to luminance, so Brighton's #0606fa scores 24
    # -- darker than a navy -- while being a bright blue anyone can see. What
    # separates them is the strongest channel: a navy peaks around 64, that
    # blue at 250.
    if max(parts) >= 140:
        return False
    if 0.2126 * red + 0.7152 * green + 0.0722 * blue >= 55:
        return False
    if max(parts) - min(parts) < 40:
        return True
    return blue > red and blue > green and green >= red


def washed_out(value):
    """True when a colour reads as white on the page: white itself, or a light
    grey with no colour left in it.

    Saturation is what separates them from a pale but real colour -- Leeds'
    #ffcd00 is brighter than the Yankees' silver and obviously yellow.
    """
    parts = _rgb(value)
    if not parts:
        return False
    if max(parts) - min(parts) >= 45:
        return False
    return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2] >= 170


def stripe_color(team, overrides=None):
    """The opponent's colour: the first candidate that will actually show.

    An override wins outright -- ESPN's primary is not always the one people
    picture, and Syracuse comes back navy rather than orange. Otherwise the
    primary is used unless it would read as black or as white, in which case
    the alternate stands in: that is how the Steelers become gold rather than
    a stripe you cannot see.

    White is a last resort, not a preference. A white stripe says nothing about
    who is playing, and a page of them says less -- but an invisible stripe is
    just a missing one, so something beats nothing.
    """
    name = (team.get("displayName") or team.get("name") or "").lower()
    for label, value in (overrides or {}).items():
        if label.lower() in name:
            return "#" + value.lstrip("#")

    candidates = [(team.get("color") or "").lstrip("#"),
                  (team.get("alternateColor") or "").lstrip("#")]
    candidates = [c for c in candidates if _rgb(c)]
    for candidate in candidates:
        if not washed_out(candidate) and not invisible_colour(candidate):
            return "#" + candidate
    for candidate in candidates:
        if not washed_out(candidate):
            return "#" + candidate
    return "#" + candidates[0] if candidates else None


# ------------------------------------------------------- the shared list

COLORS_EXPECT = ["team", "color"]


def read_colors(text):
    """{team: hex} from the shared Colors tab.

    The header is CHECKED, not assumed. Asking Google for a tab that does not
    exist hands back the FIRST tab instead of erroring, so without this a Sheet
    with no Colors tab would be parsed as if the reminders were team colours.
    """
    rows = list(csv.reader(io.StringIO(text or "")))
    if not rows:
        return {}
    header = [h.strip().lower().split()[0] if h.strip() else "" for h in rows[0]]
    where = {name: i for i, name in enumerate(header) if name in COLORS_EXPECT}
    if len(where) < len(COLORS_EXPECT):
        return {}
    out = {}
    for line in rows[1:]:
        cells = [c.strip() for c in line]
        if max(where.values()) >= len(cells):
            continue
        team, value = cells[where["team"]], cells[where["color"]].lstrip("#")
    # Google Sheets reads an all-digit cell as a NUMBER and eats the leading
    # zero: "061440" comes back as "61440". It only happens to values with no
    # letters in them, which is why "0a2240" survives and Penn State's navy did
    # not. Pad rather than reject -- the alternative is a row that vanishes
    # with nothing to say why.
        if value.isdigit() and len(value) < 6:
            value = value.zfill(6)
        if team and _rgb(value):
            out[team] = value
    return out


def color_overrides(cfg, conf):
    """The committed list, with the Sheet's laid over it.

    config.json is the FALLBACK, not the source: three sites read this list, and
    a Sheet outage must not be able to break all three at once. The Sheet wins
    where it has an opinion, and says nothing where it does not.
    """
    baked = dict(conf.get("team_colors") or {})
    sheet_id = (cfg.get("reminders_sheet") or "").strip()
    tab = conf.get("colors_tab")
    if not sheet_id or not tab:
        return baked
    local = os.environ.get("KMONEY_COLORS_CSV")
    try:
        if local:
            if not os.path.exists(local):
                return baked
            with open(local, encoding="utf-8") as fh:
                text = fh.read()
        else:
            import reminders
            import requests
            r = requests.get(reminders.CSV_URL % sheet_id + "&sheet=" + tab,
                             timeout=20)
            r.raise_for_status()
            text = r.text
        shared = read_colors(text)
    except Exception as exc:
        print("  ! colours sheet unreadable (%s); using the committed list" % exc)
        return baked
    if shared:
        baked.update(shared)
    return baked


# --------------------------------------------------------------- networks

# Kept SHORT on purpose. A rule needing many exceptions is the wrong rule.
HIDE_NETWORKS = ("MLB.TV", "ESPN Deportes", "Universo", "Telemundo Deportes",
                 "TUDN", "TUDN USA")
# Named only when it is the ONLY way to watch: a Premier League match on USA
# and Peacock is a USA game.
STREAMING = ("Peacock", "Paramount+", "ESPN+", "Prime Video", "Apple TV",
             "Apple TV+", "Netflix", "Max", "HBO Max", "Fubo", "B1G+",
             "ESPN3", "ESPN Unlimited", "ESPN Select", "Peacock Premium")
# ESPN alternates spellings between games; these are the ones that fit.
NETWORK_NAMES = {"USA Net": "USA", "CBS Sports Network": "CBSSN",
                 "SEC Network+": "SECN+", "NBC Sports": "NBC",
                 "Big Ten Network": "BTN", "FOX Sports 1": "FS1"}


def _broadcast_names(comp):
    """[(market, name)] from either endpoint's shape.

    The scoreboard returns {market:'national', names:[...]}; the team schedule
    returns {market:{type:'National'}, media:{shortName:...}}. Same idea, two
    encodings, and only one of them is ever present.
    """
    out = []
    for entry in comp.get("broadcasts") or []:
        market = entry.get("market")
        if isinstance(market, dict):
            market = market.get("type")
        market = (market or "").lower()
        names = entry.get("names")
        if not names:
            media = entry.get("media") or {}
            names = [media.get("shortName") or media.get("callLetters") or ""]
        for name in names:
            if name:
                out.append((market, name))
    return out


def pick_network(comp):
    """ONE network, or None. A simulcast does not need naming twice.

    National only: a game carried solely on a regional feed shows nothing,
    which is the honest answer -- that feed is only useful if you happen to
    get it.
    """
    entries = [(m, NETWORK_NAMES.get(n, n)) for m, n in _broadcast_names(comp)]
    national = [n for m, n in entries if m == "national"]
    if not national:
        return None
    real = [n for n in national if n not in HIDE_NETWORKS]
    on_tv = [n for n in real if n not in STREAMING]
    return (on_tv or real or [None])[0]


# ---------------------------------------------------------------- marquee

def _minutes(text):
    hour, _, minute = (text or "0:0").partition(":")
    return int(hour) * 60 + int(minute)


def is_marquee(when, network, windows):
    """True for a showcase window a competition names for itself.

    Matched on the network AND the kickoff TOGETHER, never either alone: FOX
    has a 3:30 window of its own and NBC carries ordinary games midweek, so
    matching on the channel would light up half the season and say nothing.

    The bounds are a range rather than an exact time because a window shifts
    occasionally, and because Britain and the States change their clocks on
    different dates -- which moves the Saturday match by an hour for a fortnight
    each year.
    """
    if not network:
        return False
    clock_now = when.hour * 60 + when.minute
    for window in windows or []:
        days = window.get("days") or []
        if days and when.strftime("%a") not in days:
            continue
        if network not in (window.get("networks") or []):
            continue
        if window.get("from") and clock_now < _minutes(window["from"]):
            continue
        if window.get("to") and clock_now > _minutes(window["to"]):
            continue
        return True
    return False


# ------------------------------------------------------------------ rounds

KNOCKOUT_WORDS = ("final", "semi", "quarter", "round", "playoff", "16", "32")
SMALL_WORDS = ("of", "the", "and")


def round_tag(slug):
    """"third-round" -> "Third Round". Soccer keeps the round in season.slug
    rather than in a note, so a cup tie has nothing to label itself with
    otherwise."""
    slug = (slug or "").lower()
    if not slug or not any(w in slug for w in KNOCKOUT_WORDS):
        return ""
    slug = slug.split("---")[-1]
    words = [w for w in slug.replace("-", " ").split() if w and w != "proper"]
    if " ".join(words) in ("round of 16", "round of 32"):
        return "R" + words[-1]
    return " ".join(w if (w in SMALL_WORDS and i) else w.capitalize()
                    for i, w in enumerate(words))


def competition_label(event, comp, default):
    """What to print under the matchup.

    A note headline wins when there is one -- that is where college keeps
    "Big Ten Tournament" and the bowl names. Otherwise the league's own name,
    plus a cup round when the season slug names one.
    """
    note = ((comp.get("notes") or [{}])[0].get("headline") or "").strip()
    if note:
        return note
    tag = round_tag(((event.get("season") or {}).get("slug")))
    return "%s - %s" % (default, tag) if tag else default


# ------------------------------------------------------------------- rows

EASTERN = "America/New_York"


def local(when_iso):
    """ESPN stamps UTC; the reader is in Michigan."""
    stamp = dt.datetime.strptime(when_iso[:16], "%Y-%m-%dT%H:%M")
    stamp = stamp.replace(tzinfo=dt.timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return stamp.astimezone(ZoneInfo(EASTERN))
    except Exception:
        return stamp          # UTC is wrong by hours, but never a crash


def clock(when, valid=True):
    """"7:30 PM", or TBD when the kickoff is not set.

    ESPN stamps an unscheduled game at midnight local and flags `timeValid`
    false. Without that check a Big Ten game five weeks out reads "12:00 AM",
    which looks like a real fixture at midnight rather than a time nobody has
    announced. The DAY is right either way, so the row still belongs where it
    is -- only the clock is unknown.
    """
    if not valid:
        return "TBD"
    return when.strftime("%I:%M %p").lstrip("0")


def rank_of(competitor):
    rank = (competitor.get("curatedRank") or {}).get("current")
    return rank if rank and rank != UNRANKED else None


def side_name(competitor):
    """The plain-text name, rank included -- for the terminal and for tests."""
    team = competitor.get("team") or {}
    name = team.get("displayName") or team.get("name") or "?"
    rank = rank_of(competitor)
    return ("#%d %s" % (rank, name)) if rank else name


def side_html(competitor):
    """The same name with the rank marked up.

    Kept separate from `side_name` because the rank has to survive as MARKUP:
    build one string and escape it whole and the span comes out as text.
    """
    team = competitor.get("team") or {}
    name = ui.esc(team.get("displayName") or team.get("name") or "?")
    rank = rank_of(competitor)
    return ('<span class="rk">#%d</span> %s' % (rank, name)) if rank else name


def matchup_parts(home, away, soccer, neutral):
    """(first, connector, second) -- who is printed on top, and the word.

    Soccer prints the home side first; every other sport is away at home.
    Getting this backwards is the single easiest way to make every row read
    wrong, and it is invisible unless you know the convention.

    "at" says something -- it means the second team is hosting. On a neutral
    field nobody is, so it becomes "vs.".
    """
    first, second = (home, away) if soccer else (away, home)
    return first, ("vs." if (soccer or neutral) else "at"), second


def matchup(home, away, soccer, neutral):
    """The one-line form, for the terminal and for anything comparing text."""
    first, joiner, second = matchup_parts(home, away, soccer, neutral)
    return "%s %s %s" % (side_name(first), joiner, side_name(second))


LOGO_OVERRIDES_FILE = os.path.join(HERE, "logo-overrides.json")
_logo_overrides = None


# sports-daily is the generator: its `logos.py --write` measures the actual
# pixels of both crest variants and records the exceptions. Read straight from
# its repo so the two pages cannot drift, the way the colours come from the
# Sheet -- his call, "always pull from there".
LOGO_SOURCE = ("https://raw.githubusercontent.com/kyeill/sports-daily/"
               "main/config.json")
LOGO_CACHE_MINUTES = 720


def logo_overrides():
    """Teams whose DEFAULT crest reads better than the dark variant.

    Pulled from sports-daily, cached, and falling back to the copy committed
    here. That copy is the FALLBACK, not the source: a GitHub blip must not
    silently change every crest on the page, and a list nobody can read is
    worse than one that is a few days old.
    """
    global _logo_overrides
    if _logo_overrides is not None:
        return _logo_overrides
    disk = _cache_path("logo-overrides")
    fresh = None
    if os.path.exists(disk) and (
            time.time() - os.path.getmtime(disk)) / 60 < LOGO_CACHE_MINUTES:
        try:
            with open(disk, encoding="utf-8") as fh:
                fresh = json.load(fh)
        except Exception:
            fresh = None
    if fresh is None:
        try:
            import requests
            r = requests.get(LOGO_SOURCE, timeout=20)
            r.raise_for_status()
            fresh = (r.json() or {}).get("logo_overrides") or {}
            if fresh:
                os.makedirs(CACHE, exist_ok=True)
                with open(disk, "w", encoding="utf-8") as fh:
                    json.dump(fresh, fh)
                print("  %d logo override(s) from sports-daily" % len(fresh))
        except Exception as exc:
            print("  ! sports-daily logo list unreadable (%s); using the "
                  "committed copy" % exc)
            fresh = None
    if not fresh:
        try:
            with open(LOGO_OVERRIDES_FILE, encoding="utf-8") as fh:
                fresh = json.load(fh)
        except Exception:
            fresh = {}
    _logo_overrides = fresh
    return _logo_overrides


def _logo(team):
    """The crest that reads on a dark page -- sports-daily's rule exactly.

    ESPN's `-dark` variant is the right one for most teams, and is simply the
    default URL with the size folder swapped. For some clubs it is a flat white
    silhouette, so `logo-overrides.json` names the ones where the default reads
    better. Tottenham is NOT one of them: its dark crest is a white cockerel,
    which is what it should be.
    """
    plain = team.get("logo")
    if not plain:
        logos = team.get("logos") or []
        plain = logos[0].get("href") if logos else None
    if not plain:
        return None, None
    name = team.get("displayName") or team.get("name") or ""
    override = logo_overrides().get(name)
    return (override or plain.replace("/500/", "/500-dark/")), plain


def normalize(event, sport, follow, today, colors=None, overrides=None):
    """One ESPN event -> one row, or None if it is not a real fixture."""
    comps = event.get("competitions") or []
    if not comps:
        return None
    comp = comps[0]
    # Exhibitions and friendlies are not games he wants on the page.
    kind = (comp.get("type") or {}).get("abbreviation") or ""
    season_type = (event.get("seasonType") or {}).get("id")
    if kind.upper() in ("EXH", "FRIENDLY") or season_type == "1":
        return None

    sides = comp.get("competitors") or []
    home = next((c for c in sides if c.get("homeAway") == "home"), None)
    away = next((c for c in sides if c.get("homeAway") == "away"), None)
    if not home or not away:
        return None

    mine = next((c for c in sides
                 if (c.get("team") or {}).get("id") == follow["id"]), None)
    if not mine:
        return None
    theirs = home if mine is away else away

    # The schedule endpoint returns colours as null, so they are looked up from
    # the league's team list instead.
    other = dict(theirs.get("team") or {})
    if colors and not other.get("color"):
        other.update(colors.get(other.get("id")) or {})

    soccer = sport["path"].startswith("soccer/")
    when = local(event.get("date") or comp.get("date") or "")
    day = when.date()
    timed = event.get("timeValid")
    timed = True if timed is None else bool(timed)
    network = pick_network(comp)
    first, joiner, second = matchup_parts(home, away, soccer,
                                          comp.get("neutralSite"))
    return {
        "id": str(event.get("id")),
        "day": day,
        "at": when,
        "title": matchup(home, away, soccer, comp.get("neutralSite")),
        "first": side_html(first),
        "joiner": joiner,
        "second": side_html(second),
        "competition": competition_label(event, comp, sport["label"]),
        "network": network,
        "marquee": timed and is_marquee(when, network,
                                        sport.get("marquee_windows")),
        "time": clock(when, timed),
        "timed": timed,
        "stripe": stripe_color(other, overrides),
        "wash": follow["wash"],
        # Per team, because yellow needs more of itself than blue does: at the
        # 13% the other tabs use, every yellow goes brown against this card.
        "wash_strength": follow.get("wash_strength"),
        "logos": [_logo(first.get("team") or {}), _logo(second.get("team") or {})],
        # The dark variant does not exist for every team on the CDN, so each
        # crest carries the plain URL to fall back to rather than showing the
        # browser's broken-image glyph.
        "past": day < today,
    }


# ------------------------------------------------------------------ weeks

def within_day(row):
    """Games in kickoff order, with the TBDs after them.

    A game whose time is not set is stamped MIDNIGHT by ESPN, so sorting on the
    timestamp alone puts it first -- above a noon kickoff that is actually
    happening earlier in the reader's day. It is not the earliest game, it is
    the one nobody has scheduled, so it belongs at the foot of its day.
    """
    return (row["day"], 0 if row.get("timed", True) else 1,
            row["at"], row["title"])


def week_start(day):
    """The Monday on or before a date."""
    return day - dt.timedelta(days=day.weekday())


def into_weeks(rows, today, spans):
    """[(monday, [row, ...])] -- every week from the start to the last game.

    Empty weeks are kept: a bye week is information, and skipping it would make
    the list lie about how far apart two games are.

    Where the run STARTS is the only judgement here. Inside a season it is this
    week, blank or not. Outside every season -- June and July -- it is the week
    of the next fixture, so the summer does not open on a dozen empty headings
    waiting for August.
    """
    if not rows:
        return []
    first = min(r["day"] for r in rows)
    last = max(r["day"] for r in rows)
    start = week_start(today if in_season(spans, today) else first)
    # A season that has already begun still starts at this week, not at the
    # first fixture -- which may be months in the past.
    start = max(start, week_start(first)) if start > week_start(last) else start
    weeks, cursor = [], start
    while cursor <= week_start(last):
        end = cursor + dt.timedelta(days=6)
        weeks.append((cursor, sorted((r for r in rows if cursor <= r["day"] <= end),
                                     key=within_day)))
        cursor += dt.timedelta(days=7)
    return weeks


# ------------------------------------------------------------------ build

def _teams_colors(path):
    """{id: {color, alternateColor}} for a league -- the schedule endpoint
    hands back nulls, so the opponent's stripe has to come from somewhere."""
    data = _get(path + "/teams", params={"limit": 1000},
                cache_key="teams-" + path)
    out = {}
    for group in ((data or {}).get("sports") or [{}])[0].get("leagues") or []:
        for entry in group.get("teams") or []:
            team = entry.get("team") or {}
            if team.get("id"):
                out[team["id"]] = {"color": team.get("color"),
                                   "alternateColor": team.get("alternateColor")}
    return out


def _schedule_events(sport, follow, today):
    """A college team's season, as ESPN currently defines it.

    NO season parameter, and no falling back to the previous year. ESPN returns
    the current season on its own, and a fallback would be actively wrong: ask
    basketball for last season and it happily returns thirty-four games from
    last winter. Michigan basketball is simply absent until ESPN publishes the
    schedule, which is what he asked for -- silence, not a placeholder.
    """
    data = _get("%s/teams/%s/schedule" % (sport["path"], follow["id"]),
                cache_key="sched-%s-%s" % (sport["path"], follow["id"]))
    return (data or {}).get("events") or []


def _scoreboard_events(sport, follow, spans):
    """A club across one competition. Filtered to the followed team here,
    because a season of Premier League is 380 matches and 38 are his."""
    lo = min([s[0] for s in spans if s], default=None)
    hi = max([s[1] for s in spans if s], default=None)
    if not lo or not hi:
        return []
    window = "%s-%s" % (lo.replace("-", ""), hi.replace("-", ""))
    data = _get(sport["path"] + "/scoreboard",
                params={"dates": window, "limit": 1000},
                cache_key="sb-%s-%s" % (sport["path"], window))
    out = []
    for event in (data or {}).get("events") or []:
        sides = (event.get("competitions") or [{}])[0].get("competitors") or []
        if any((c.get("team") or {}).get("id") == follow["id"] for c in sides):
            out.append(event)
    return out


def build(today=None, cfg=None, record=True):
    today = dt.date.fromisoformat(today) if isinstance(today, str) else today
    today = today or dt.date.today()

    local_file = os.environ.get("KMONEY_TEAMS_JSON")
    if local_file:
        return _from_file(local_file, today)

    if cfg is None:
        import watch
        cfg = watch.load_config()
    conf = cfg.get("teams") or {}
    if not conf.get("follow"):
        return {"today": today, "weeks": [], "error": "no teams in config.json"}

    spans = [s for s in (season_span(p) for p in conf.get("anchors") or []) if s]
    overrides = color_overrides(cfg, conf)
    rows, colors, failed = [], {}, []
    for follow in conf["follow"]:
        for sport in follow.get("sports") or []:
            if sport.get("mode") == "schedule":
                events = _schedule_events(sport, follow, today)
                if sport["path"] not in colors:
                    colors[sport["path"]] = _teams_colors(sport["path"])
            else:
                events = _scoreboard_events(sport, follow, spans)
            for event in events:
                row = normalize(event, sport, follow, today,
                                colors.get(sport["path"]),
                                overrides)
                if row:
                    rows.append(row)

    # Two competitions can carry the same fixture; keep one.
    seen, unique = set(), []
    for row in sorted(rows, key=lambda r: r["at"]):
        if row["id"] not in seen:
            seen.add(row["id"])
            unique.append(row)
    return {"today": today, "weeks": into_weeks(unique, today, spans),
            "error": None, "failed": failed}


def _fixture_name(text):
    """Canned rows carry PLAIN text, so they are escaped here and the rank is
    marked up afterwards -- the live path builds the markup itself, and a row
    that is escaped twice shows its own tags."""
    safe = ui.esc(text)
    found = re.match(r"#(\d+)\s+(.*)", safe)
    if found:
        return '<span class="rk">#%s</span> %s' % (found.group(1), found.group(2))
    return safe


def _from_file(path, today):
    """Canned rows for tests and `site.py --fixtures`, so the tab renders with
    no network and no API."""
    if not os.path.exists(path):
        return {"today": today, "weeks": [], "error": None}
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    rows = []
    for row in raw.get("rows") or []:
        when = local(row["at"])
        timed = row.get("timed", True)
        rows.append(dict(row, day=when.date(), at=when, timed=timed,
                         wash_strength=row.get("wash_strength"),
                         first=_fixture_name(row.get("first", "")),
                         second=_fixture_name(row.get("second", "")),
                         time=clock(when, timed), past=when.date() < today,
                         marquee=timed and is_marquee(
                             when, row.get("network"),
                             row.get("marquee_windows"))))
    spans = [tuple(s) for s in raw.get("spans") or []]
    return {"today": today, "weeks": into_weeks(rows, today, spans),
            "error": None}


# ----------------------------------------------------------------- render

CSS = """
.wk{margin:18px 0 0}
.wk h2{font-size:12px;text-transform:uppercase;letter-spacing:.08em;
       color:var(--muted);font-weight:600;margin:0 0 7px}
/* Three rows, three columns: crest, name, and the right-hand figure that
   belongs to that name's line. The grid is what keeps the date level with the
   first team and the time with the second -- laid out as separate blocks they
   drift apart the moment a name wraps. */
.gm{display:grid;grid-template-columns:20px 1fr auto;
    column-gap:9px;row-gap:3px;align-items:center;
    background:var(--card);border:1px solid var(--line);
    border-left:4px solid transparent;border-radius:10px;
    padding:10px 12px;margin:6px 0}
/* Two layers, as on the Church tab: the wash is translucent, so without the
   card colour under it the page background shows through and a shaded row
   comes out DARKER than a plain one. */
.gm.tint{border-left-color:var(--tint);
         background:linear-gradient(var(--wash),var(--wash)),var(--card)}
/* Already played. It stays on the page -- a week that quietly empties itself
   as it goes is worse than one that shows what happened. */
.gm.done{opacity:.55}
/* 20px and 14.5px are sports-daily's, mirrored deliberately: the two
   pages sit side by side on the same phone and were a size apart. */
.gm img{width:20px;height:20px;object-fit:contain;display:block}
.gm .n1,.gm .n2{font-weight:600;font-size:14.5px;line-height:1.3;min-width:0}
/* The connector is part of the first line, not a column of its own: giving it
   one would leave a ragged gap after every short team name. */
.gm .j{color:var(--muted);font-weight:400}
/* A rank reads better in light blue -- the same one the marquee network uses,
   and for the same reason: a dark navy would vanish against this ground. */
.gm .rk{color:#8fb0d8}
/* The date and the time are one column, not a label and a footnote: same
   size, same weight, same colour. They were already the same size -- it was
   the muted grey that made the time read as the smaller of the two. */
.gm .r{text-align:right;font-size:13px;font-weight:600;
       font-variant-numeric:tabular-nums;white-space:nowrap}
/* The third row is the quiet one: competition on the left, network on the
   right, both muted so the teams stay the loudest thing in the bubble. */
.gm .c{grid-column:2;color:var(--muted);font-size:13px}
.gm .net{color:var(--muted);font-size:13px;text-align:right;white-space:nowrap}
/* A washed row is a lighter ground than the plain card, so the ordinary muted
   grey loses contrast on it -- 4.33 against maize at 13%, just under readable.
   The gentlest lift that clears 4.5 rather than the brightest: this holds 4.82,
   so the third line stays visibly quieter than the team names above it. */
.gm.tint .c,.gm.tint .net{color:#a3a39d}
/* The showcase windows a competition names for itself -- FOX at noon, CBS at
   3:30, NBC on Saturday night, the Saturday Premier League match. Blue, so the
   week's marquee games are findable without reading every row. */
.gm .net.marquee{color:#8fb0d8}
.wnone{color:var(--muted);font-size:13px;padding:1px 2px 8px}
@media (min-width:641px){
  .wk{margin:24px 0 0}
  .wk h2{font-size:13px}
  .gm{padding:12px 14px;margin:8px 0;column-gap:11px;
      grid-template-columns:22px 1fr auto}
  .gm img{width:22px;height:22px}
  .gm .n1,.gm .n2{font-size:15px}
  .gm .r,.gm .c,.gm .net{font-size:14px}
}
"""


def week_heading(monday):
    return "Week of %s %d" % (monday.strftime("%B"), monday.day)


def _wash(row):
    return ui.wash(row["wash"], row.get("wash_strength") or ui.WASH)


def _game(row):
    """One bubble: two team lines with their own right-hand figure, then a
    quieter line for the competition and the network."""
    tint = row.get("stripe")
    logos = row.get("logos") or [None, None]

    def crest(pair):
        src, plain = (pair if isinstance(pair, (list, tuple)) else (pair, None))
        if not src:
            return "<span></span>"
        # Not every team has a -dark crest on the CDN; swap to the plain one
        # rather than leaving the browser's broken-image glyph in the row.
        swap = (' onerror="this.onerror=null;this.src=&quot;%s&quot;"'
                % ui.esc(plain)) if plain and plain != src else ""
        return '<img loading="lazy" alt="" src="%s"%s>' % (ui.esc(src), swap)

    date = ui.esc(row["at"].strftime("%a %b ")) + str(row["at"].day)
    return (
        '<div class="gm%s%s"%s>'
        '%s<span class="n1">%s <span class="j">%s</span></span>'
        '<span class="r d">%s</span>'
        '%s<span class="n2">%s</span><span class="r t">%s</span>'
        '<span class="c">%s</span><span class="net%s">%s</span>'
        "</div>"
    ) % (
        " tint" if tint else "",
        " done" if row.get("past") else "",
        ' style="--tint:%s;--wash:%s"' % (ui.esc(tint), _wash(row))
        if tint else ' style="--wash:%s"' % _wash(row),
        crest(logos[0]),
        row["first"],            # already escaped; carries the rank's markup
        ui.esc(row["joiner"]),
        date,
        crest(logos[1] if len(logos) > 1 else None),
        row["second"],
        ui.esc(row["time"]),
        ui.esc(row["competition"]),
        " marquee" if row.get("marquee") else "",
        ui.esc(row.get("network") or ""),
    )


def render(data):
    if data.get("error"):
        return ('<div class="rerr">Could not read the schedule: %s</div>'
                % ui.esc(data["error"]))
    if not data["weeks"]:
        return '<div class="wnone">Nothing scheduled.</div>'
    out = []
    for monday, games in data["weeks"]:
        out.append('<div class="wk"><h2>%s</h2>' % ui.esc(week_heading(monday)))
        if games:
            out.extend(_game(g) for g in games)
        else:
            # A bye week says something. Dropping it would make the list lie
            # about how far apart two games are.
            out.append('<div class="wnone">No games.</div>')
        out.append("</div>")
    return "".join(out)


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    data = build()
    if data["error"]:
        raise SystemExit("error: " + data["error"])
    played = 0
    for monday, games in data["weeks"]:
        print("== %s (%d)" % (week_heading(monday), len(games)))
        for g in games:
            played += bool(g["past"])
            print("   %-9s %-52s %-26s %-9s %s" % (
                g["at"].strftime("%a %b %d"), g["title"][:52],
                g["competition"][:26], g["time"],
                (g["network"] or "") + (" *" if g.get("marquee") else "")))
    total = sum(len(g) for _, g in data["weeks"])
    marquee = sum(1 for _, gs in data["weeks"] for g in gs if g.get("marquee"))
    print("\n%d games across %d weeks (%d played, %d marquee *)"
          % (total, len(data["weeks"]), played, marquee))
