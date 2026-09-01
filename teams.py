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

import datetime as dt
import json
import os
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

def _luma(hex_color):
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return 0.299 * r + 0.587 * g + 0.114 * b


def stripe_color(team):
    """The opponent's colour, as a stripe that will actually be visible.

    Sports Daily's rule: a near-black stripe disappears into the card and a
    white one says nothing about who is playing, so the alternate stands in --
    which is how the Steelers become gold. Tottenham's own primary is #ffffff,
    so this is not a rare case.
    """
    candidates = [(team.get("color") or "").lstrip("#"),
                  (team.get("alternateColor") or "").lstrip("#")]
    candidates = [c for c in candidates if len(c) == 6]
    for c in candidates:
        if 45 < _luma(c) < 215:
            return "#" + c
    return "#" + candidates[0] if candidates else None


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
    team = competitor.get("team") or {}
    name = team.get("displayName") or team.get("name") or "?"
    rank = rank_of(competitor)
    return ("#%d %s" % (rank, name)) if rank else name


def matchup(home, away, soccer, neutral):
    """Soccer prints the home side first; every other sport is away at home.

    Getting this backwards is the single easiest way to make every row read
    wrong, and it is invisible unless you know the convention.
    """
    if neutral:
        first, second = (home, away) if soccer else (away, home)
        return "%s vs. %s" % (side_name(first), side_name(second))
    if soccer:
        return "%s vs. %s" % (side_name(home), side_name(away))
    return "%s at %s" % (side_name(away), side_name(home))


def _logo(team):
    logos = team.get("logos") or []
    if logos:
        return logos[0].get("href")
    return team.get("logo")


def normalize(event, sport, follow, today, colors=None):
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

    when = local(event.get("date") or comp.get("date") or "")
    day = when.date()
    timed = event.get("timeValid")
    timed = True if timed is None else bool(timed)
    soccer = sport["path"].startswith("soccer/")
    return {
        "id": str(event.get("id")),
        "day": day,
        "at": when,
        "title": matchup(home, away, soccer, comp.get("neutralSite")),
        "competition": competition_label(event, comp, sport["label"]),
        "network": pick_network(comp),
        "time": clock(when, timed),
        "timed": timed,
        "stripe": stripe_color(other),
        "wash": follow["wash"],
        "logos": [_logo(away.get("team") or {}), _logo(home.get("team") or {})],
        "past": day < today,
    }


# ------------------------------------------------------------------ weeks

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
                                     key=lambda r: (r["at"], r["title"]))))
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
                                colors.get(sport["path"]))
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
                         time=clock(when, timed), past=when.date() < today))
    spans = [tuple(s) for s in raw.get("spans") or []]
    return {"today": today, "weeks": into_weeks(rows, today, spans),
            "error": None}


# ----------------------------------------------------------------- render

CSS = """
.wk{margin:18px 0 0}
.wk h2{font-size:12px;text-transform:uppercase;letter-spacing:.08em;
       color:var(--muted);font-weight:600;margin:0 0 7px}
.gm{display:flex;gap:11px;align-items:flex-start;background:var(--card);
    border:1px solid var(--line);border-left:4px solid transparent;
    border-radius:10px;padding:10px 12px;margin:6px 0}
/* Two layers, as on the Church tab: the wash is translucent, so without the
   card colour under it the page background shows through and a shaded row
   comes out DARKER than a plain one. */
.gm.tint{border-left-color:var(--tint);
         background:linear-gradient(var(--wash),var(--wash)),var(--card)}
/* Already played. It stays on the page -- a week that quietly empties itself
   as it goes is worse than one that shows what happened. */
.gm.done{opacity:.55}
.badges{flex:0 0 auto;display:flex;flex-direction:column;gap:3px;width:26px}
.badges img{width:26px;height:26px;object-fit:contain;display:block}
.gm .b{flex:1 1 auto;min-width:0}
.gm .t{display:block;font-weight:600;font-size:15px;line-height:1.3}
.gm .c{display:block;color:var(--muted);font-size:13px;margin-top:2px}
/* Wide enough for "Sat Nov 28" and "NBC · 12:00 PM" without wrapping. */
.gm .w{flex:0 0 auto;width:104px;text-align:right;
       font-variant-numeric:tabular-nums}
.gm .w .d{display:block;font-size:13.5px;font-weight:600;line-height:1.25}
.gm .w .n{display:block;font-size:11.5px;color:var(--muted);margin-top:2px}
.wnone{color:var(--muted);font-size:13px;padding:1px 2px 8px}
@media (min-width:641px){
  .wk{margin:24px 0 0}
  .wk h2{font-size:13px}
  .gm{padding:12px 14px;margin:8px 0;gap:13px}
  .badges,.badges img{width:30px}
  .badges img{height:30px}
  .gm .t{font-size:17px}
  .gm .c{font-size:14px}
  .gm .w{width:118px}
  .gm .w .d{font-size:15px}
  .gm .w .n{font-size:12.5px}
}
"""


def week_heading(monday):
    return "Week of %s %d" % (monday.strftime("%B"), monday.day)


def _game(row):
    tint = row.get("stripe")
    logos = "".join(
        '<img loading="lazy" alt="" src="%s">' % ui.esc(src)
        for src in row.get("logos") or [] if src)
    right = ui.esc(row["at"].strftime("%a %b ")) + str(row["at"].day)
    beneath = ("%s · %s" % (row["network"], row["time"])
               if row.get("network") else row["time"])
    return (
        '<div class="gm%s%s"%s><span class="badges">%s</span>'
        '<span class="b"><span class="t">%s</span>'
        '<span class="c">%s</span></span>'
        '<span class="w"><span class="d">%s</span>'
        '<span class="n">%s</span></span></div>'
    ) % (
        " tint" if tint else "",
        " done" if row.get("past") else "",
        ' style="--tint:%s;--wash:%s"' % (ui.esc(tint), ui.wash(row["wash"]))
        if tint else ' style="--wash:%s"' % ui.wash(row["wash"]),
        logos,
        ui.esc(row["title"]),
        ui.esc(row["competition"]),
        right,
        ui.esc(beneath),
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
            print("   %-9s %-52s %-26s %s" % (
                g["at"].strftime("%a %b %d"), g["title"][:52],
                g["competition"][:26],
                ("%s · %s" % (g["network"], g["time"])) if g["network"]
                else g["time"]))
    total = sum(len(g) for _, g in data["weeks"])
    print("\n%d games across %d weeks (%d already played)"
          % (total, len(data["weeks"]), played))
