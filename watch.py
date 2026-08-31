"""The Watch tab: what is coming, when, and where it lands.

Two sources feed one list. Franchises are discovered from TMDB by studio, so a
newly announced Marvel or DC project appears without anyone adding it. The
one-offs are hand-added: from the `Watchlist` tab of the Google Sheet, which is
editable from a phone, and from `watchlist` in config.json, which is where an
entry that needs a written reason belongs.
"""

import csv
import datetime as dt
import io
import json
import os

import tmdb
import ui

HERE = os.path.dirname(os.path.abspath(__file__))
SEEN = os.path.join(HERE, "output", "history", "seen.json")
# Beside seen.json because output/history is the one directory the build
# commits: a title is searched once, and what it resolved to is then reviewable
# in git rather than re-guessed every morning.
PINNED = os.path.join(HERE, "output", "history", "watchlist.json")

KEY = "watch"
LABEL = "Watchlist"

# A title in one of these states has no date because it is over, not because it
# is waiting -- 16 finished Marvel and DC shows arrive via the popularity pass.
FINISHED = ("Released", "Ended", "Canceled")

# TMDB release_dates types. 3 is a wide theatrical run, 2 a limited one.
THEATRICAL, DIGITAL, PREMIERE, ON_TV = (2, 3), 4, 1, 6
NEW_FOR_DAYS = 7
SEED = "1970-01-01"       # backdate for the very first run; see collect()

# What to say instead of a date. "Release" and "Series" are what the date
# functions fall back to, and neither tells you anything in a TBA list.
UNDATED = {
    "Planned": "Announced",
    "Rumored": "Rumored",
    "In Production": "Filming",
    "Post Production": "Post-production",
    "Returning Series": "Returning",
}


def load_config(path=None):
    """KMONEY_CONFIG points every tab at a different config -- that is how
    `site.py --fixtures` runs the canned data without touching the real one."""
    path = path or os.environ.get("KMONEY_CONFIG") or os.path.join(HERE, "config.json")
    with open(path, encoding="utf-8-sig") as fh:
        return json.load(fh)


def _day(value):
    """TMDB mixes bare dates and full ISO timestamps in the same field."""
    return (value or "")[:10] or None


# ------------------------------------------------------------- date picking

def movie_date(detail, region="US"):
    """When it is watchable HERE, and how.

    `release_date` at the top level is the earliest release anywhere on earth.
    For anything with a festival or overseas premiere that date has already
    passed while the film is still months away, which silently drops it off an
    upcoming list. The per-country breakdown is the honest answer.
    """
    blocks = ((detail.get("release_dates") or {}).get("results")) or []
    mine = next((b for b in blocks if b.get("iso_3166_1") == region), None)
    if mine:
        by_type = {}
        for entry in mine.get("release_dates") or []:
            day = _day(entry.get("release_date"))
            kind = entry.get("type")
            if day and (kind not in by_type or day < by_type[kind]):
                by_type[kind] = day
        for kind in THEATRICAL:
            if kind in by_type:
                return by_type[kind], "In theaters"
        if DIGITAL in by_type:
            return by_type[DIGITAL], "Streaming"
        if ON_TV in by_type:
            return by_type[ON_TV], "On TV"
        if PREMIERE in by_type:
            return by_type[PREMIERE], "Premiere"
    return _day(detail.get("release_date")), "Release"


def tv_date(detail, today=None):
    """The next thing to watch, not the show's own start date.

    A returning series in its off-season has no next_episode_to_air, so the
    next season's air_date in `seasons` is the only forward-looking date it
    carries -- without that check every mid-run show reads as TBA.
    """
    today = today or dt.date.today().isoformat()
    nxt = detail.get("next_episode_to_air") or {}
    day = _day(nxt.get("air_date"))
    if day:
        label = "S%d E%d" % (nxt.get("season_number") or 0,
                             nxt.get("episode_number") or 0)
        name = (nxt.get("name") or "").strip()
        # TMDB fills unnamed episodes in with "Episode 4", which just repeats
        # what the S/E label already said.
        if name and not name.lower().startswith("episode "):
            label += " · " + name
        return day, label

    # A show that has never aired is a premiere, not "Season 1" -- and its
    # first_air_date and its season 1 air_date are the same day, so this has to
    # be asked BEFORE the seasons list or the wrong label wins.
    first = _day(detail.get("first_air_date"))
    if first and first > today:
        return first, "Premiere"

    future = [
        (_day(s.get("air_date")), s.get("season_number"))
        for s in detail.get("seasons") or []
        if _day(s.get("air_date")) and _day(s.get("air_date")) > today
        and (s.get("season_number") or 0) > 0
    ]
    if future:
        day, num = min(future)
        return day, "Season %d" % num
    return None, "Series"


# TMDB's own spelling for a couple of services is not the brand. Keep this
# list SHORT -- a rule needing many exceptions is the wrong rule.
PROVIDER_NAMES = {"Disney Plus": "Disney+", "Amazon Prime Video": "Prime Video"}


def provider(detail, region="US"):
    """The ONE service to watch it on.

    Rent and buy are ignored: the question is whether it is included somewhere
    already paid for, not whether it is purchasable, and everything is
    purchasable.

    TMDB lists each service twice -- the service itself and the reseller
    variant you can bolt onto Amazon or Apple ("HBO Max Amazon Channel"). The
    reseller is not a different place to watch it, just a different way to pay,
    and `display_priority` is NO help in choosing: it ranks HBO Max Amazon
    Channel at 11 and actual HBO Max at 152. Drop the resellers first, and only
    then let display_priority pick between genuinely different services
    (Disney+ 5 beats Hulu 6).
    """
    block = ((detail.get("watch/providers") or {}).get("results") or {}).get(region) or {}
    entries = [e for e in block.get("flatrate") or [] if e.get("provider_name")]
    direct = [e for e in entries if not e["provider_name"].endswith("Channel")]
    # If a title is ONLY carried by resellers, saying nothing would be worse
    # than naming the odd one.
    best = min(direct or entries,
               key=lambda e: e.get("display_priority", 9999), default=None)
    if not best:
        return None
    name = best["provider_name"]
    return PROVIDER_NAMES.get(name, name)


# ------------------------------------------------------------------ rows

def make_row(kind, detail, source, region="US", today=None):
    if kind == "movie":
        day, when = movie_date(detail, region)
        title = detail.get("title") or detail.get("original_title") or "?"
    else:
        day, when = tv_date(detail, today)
        title = detail.get("name") or detail.get("original_name") or "?"
    if not day:
        when = UNDATED.get(detail.get("status") or "", "Announced")
    return {
        "key": "%s/%s" % (kind, detail["id"]),
        "kind": kind,
        "id": detail["id"],
        "title": title,
        "date": day,
        "when": when,
        "status": detail.get("status") or "",
        "provider": provider(detail, region),
        "poster": tmdb.poster(detail.get("poster_path")),
        "source": source,
        "overview": (detail.get("overview") or "").strip(),
    }


def _load_seen():
    """Returns (first-seen dates, had we ever run before)."""
    if os.path.exists(SEEN):
        with open(SEEN, encoding="utf-8") as fh:
            return json.load(fh), True
    return {}, False


def _save_seen(seen):
    os.makedirs(os.path.dirname(SEEN), exist_ok=True)
    with open(SEEN, "w", encoding="utf-8") as fh:
        json.dump(seen, fh, indent=1, sort_keys=True)


def _shift(day, days):
    return (dt.date.fromisoformat(day) + dt.timedelta(days=days)).isoformat()


SHEET_REQUIRED = ["title"]
SHEET_OPTIONAL = ["label", "type", "id"]


def read_sheet_watchlist(text):
    """[{title, label, type, id}] from the Watchlist tab.

    Columns are found BY NAME and only Title is required, so the sheet can be
    a single column until it needs to be more. `Type` defaults to tv: almost
    everything anyone follows week to week is a series, and a wrong guess is
    visible on the page rather than silent.
    """
    rows = list(csv.reader(io.StringIO(text or "")))
    if not rows:
        return []
    header = [h.strip().lower().split()[0] if h.strip() else "" for h in rows[0]]
    where = {}
    for i, name in enumerate(header):
        if name in SHEET_REQUIRED + SHEET_OPTIONAL:
            where.setdefault(name, i)
    if "title" not in where:
        raise ValueError("no Title column; the headings read %r"
                         % [h for h in header if h])

    def cell(cells, name):
        i = where.get(name)
        return cells[i] if i is not None and i < len(cells) else ""

    out = []
    for line in rows[1:]:
        cells = [c.strip() for c in line]
        title = cell(cells, "title")
        if not title:
            continue
        kind = (cell(cells, "type") or "tv").lower()
        out.append({
            "title": title,
            "label": cell(cells, "label") or "Custom",
            "type": "movie" if kind.startswith("m") else "tv",
            "id": cell(cells, "id") or None,
        })
    return out


def fetch_watchlist_csv(sheet, tab):
    """KMONEY_WATCHLIST_CSV points at a local file, for tests and --fixtures."""
    local = os.environ.get("KMONEY_WATCHLIST_CSV")
    if local:
        if not os.path.exists(local):
            return ""
        with open(local, encoding="utf-8") as fh:
            return fh.read()
    import reminders          # the Sheet plumbing is shared, not re-written
    import requests
    r = requests.get(reminders.CSV_URL % sheet + "&sheet=" + tab, timeout=20)
    r.raise_for_status()
    return r.text


def _pinned_path():
    """KMONEY_WATCHLIST_STATE redirects it, so a test cannot read -- or
    overwrite -- the real remembered ids."""
    return os.environ.get("KMONEY_WATCHLIST_STATE") or PINNED


def _load_pinned():
    try:
        with open(_pinned_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return []


def _save_pinned(rows):
    try:
        os.makedirs(os.path.dirname(_pinned_path()), exist_ok=True)
        with open(_pinned_path(), "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    except Exception:
        pass


def hand_added(cfg, lang, unresolved=None):
    """Everything pinned by hand: the Sheet's Watchlist tab, plus config.json.

    The Sheet gives only a title, so an id has to be resolved by search -- and
    a search can pick the wrong thing, there being four productions called "The
    Pitt". So it is resolved ONCE and remembered in output/history/watchlist.json,
    which the build commits; after that the id is read, never guessed, and a bad
    one is a visible line in a diff. Put the id in an `Id` column to overrule it.

    That same file is the fallback if the Sheet cannot be read. A network blip
    should not quietly drop titles off the list for a day.
    """
    # Titles the search could not place. They are named on the page: a title
    # he added that simply never appears is the failure mode this whole file
    # keeps trying to avoid.
    unresolved = [] if unresolved is None else unresolved
    items = list(cfg.get("watchlist") or [])
    sheet = (cfg.get("reminders_sheet") or "").strip()
    if not sheet:
        return items

    remembered = {}
    for row in _load_pinned():
        remembered[(row.get("type"), (row.get("title") or "").lower())] = row.get("id")

    try:
        text = fetch_watchlist_csv(sheet, cfg.get("watchlist_tab", "Watchlist"))
        # Not the same as an empty list. A Watchlist tab with nothing on it
        # still returns its header row, so nothing AT ALL means the fetch
        # failed -- and honouring that as "he removed everything" would drop
        # the titles for the day.
        if not (text or "").strip():
            raise ValueError("empty response")
        rows = read_sheet_watchlist(text)
    except Exception as exc:
        # Keep what was there last time rather than shrinking the list.
        print("watchlist sheet unreadable (%s); using the last known rows" % exc)
        return items + _load_pinned()

    kept = []
    for row in rows:
        kind = row["type"]
        tid = row["id"] or remembered.get((kind, row["title"].lower()))
        if not tid:
            # Type defaults to tv, and a film typed as a series finds nothing
            # at all -- so try the other kind before giving up. "The Hunt for
            # Gollum" is a film, and nobody should have to know that a column
            # exists to say so.
            for kind in (row["type"], "movie" if row["type"] == "tv" else "tv"):
                hits = tmdb.search(kind, row["title"], lang)
                if hits:
                    break
            if not hits:
                unresolved.append(row["title"])
                print("watchlist: NO MATCH for %r" % row["title"])
                continue
            top = hits[0]
            tid = top["id"]
            print("watchlist: %r -> %s %s (%s) id %s" % (
                row["title"], kind, top.get("title") or top.get("name"),
                (top.get("release_date") or top.get("first_air_date") or "?")[:4],
                tid))
        kept.append(dict(row, id=str(tid), type=kind))

    _save_pinned(kept)
    return items + kept


def collect(cfg, today, record=True, unresolved=None):
    """Every candidate title, deduped, as rows. Network-heavy; call once."""
    lang = cfg.get("language", "en-US")
    region = cfg.get("region", "US")
    ignore = {str(x) for x in cfg.get("ignore") or []}
    wanted = {}          # "kind/id" -> (source label, pinned by hand?)

    for fr in cfg.get("franchises") or []:
        cid = fr.get("company_id") or tmdb.company_id(fr["company"])
        if not cid:
            continue
        for kind in ("movie", "tv"):
            for row in tmdb.discover(kind, cid, today, lang, region,
                                     cfg.get("exclude_animation", True),
                                     cfg.get("exclude_preschool", True)):
                wanted.setdefault("%s/%s" % (kind, row["id"]),
                                  (fr.get("label") or fr["key"], False))

    for item in hand_added(cfg, lang, unresolved):
        if item.get("id"):
            wanted["%s/%s" % (item["type"], item["id"])] = (item.get("label") or "Custom", True)

    rows = []
    for key, (source, pinned) in sorted(wanted.items()):
        kind, tid = key.split("/")
        if key in ignore or tid in ignore:
            continue
        row = make_row(kind, tmdb.detail(kind, tid, lang), source, region, today)
        row["pinned"] = pinned
        rows.append(row)

    return rows


def listing(rows, cfg, today):
    """One list, ordered by when each thing is next out.

    Undated titles are tracked but not shown. They stay in `collect` so that a
    project sitting on the slate for two years appears the moment it is
    scheduled -- dropping them from discovery instead would mean never noticing
    it got a date.
    """
    back = _shift(today, -abs(cfg.get("keep_released_days", 14)))
    out = [r for r in rows if r["date"] and r["date"] >= back]
    out.sort(key=lambda r: (r["date"], r["title"]))
    return out


# Roughly "how close is this to actually happening", which is a more useful
# order for a waiting list than the alphabet.
PENDING_ORDER = ["Returning", "Post-production", "Filming", "Announced"]

# Finished titles are undated because they are over. Rumored ones are excluded
# at Kyle's request (2026-08-29): an unconfirmed rumour is not a plan, and the
# three of them were most of what made the section look padded.
SKIP_IN_PENDING = FINISHED + ("Rumored",)


def pending(rows):
    """Undated, but still alive — the slate that is waiting on a date.

    A pinned title survives the filter anyway, since TMDB calls Peacemaker
    "Ended" while season 3 is announced and that is the case pinning exists for.
    """
    out = [r for r in rows
           if not r["date"] and (r["status"] not in SKIP_IN_PENDING or r.get("pinned"))]
    rank = {label: i for i, label in enumerate(PENDING_ORDER)}
    out.sort(key=lambda r: (rank.get(r["when"], len(rank)), r["title"]))
    return out


def stamp_new(shown, today, record=True):
    """Badge what has only just appeared ON THE LIST.

    First-seen is recorded when a title becomes showable, not when discovery
    first saw it: an undated project banked two years ago should still read NEW
    on the day it finally gets a date, which is the day it becomes news.
    """
    seen, ran_before = _load_seen()
    cutoff = _shift(today, -NEW_FOR_DAYS)
    # On the very first run every title is "first seen today", which would badge
    # the whole list -- and stamping today would keep badging it for a week.
    # The seed batch is backdated instead, so only what arrives later is new.
    stamp = today if ran_before else SEED
    for row in shown:
        row["first_seen"] = seen.setdefault(row["key"], stamp)
        row["is_new"] = row["first_seen"] > cutoff
    if record:
        _save_seen(seen)
    return shown


def build(today=None, cfg=None, record=True):
    today = today or dt.date.today().isoformat()
    cfg = cfg or load_config()
    unresolved = []
    rows = collect(cfg, today, record, unresolved)
    shown = stamp_new(listing(rows, cfg, today), today, record)
    return {
        "today": today,
        "rows": shown,
        "pending": pending(rows),
        "tracked": len(rows),
        "unresolved": unresolved,
    }


# ----------------------------------------------------------------- render
# Each tab owns its own CSS so that adding an unrelated one later cannot mean
# editing a shared stylesheet and hoping nothing else moved.

CSS = """
.sec{margin:14px 0 0}
.sec h2{font-size:12px;text-transform:uppercase;letter-spacing:.08em;
        color:var(--muted);font-weight:600;margin:26px 0 8px}
.sec h2 b{color:var(--ink);font-weight:600}
/* Already out, but recent enough to still be worth catching up on. It reads
   quieter than everything ahead of it without leaving the running order. */
a.item.past{opacity:.62}
a.item{display:flex;gap:11px;align-items:flex-start;text-decoration:none;
       color:inherit;background:var(--card);border:1px solid var(--line);
       border-radius:10px;padding:10px 11px;margin:7px 0}
.pos{flex:0 0 auto;width:42px;height:63px;border-radius:5px;object-fit:cover;
     background:var(--chip);display:block}
.body{flex:1 1 auto;min-width:0}
/* These are spans inside a span, not flex items, so nothing blockifies them
   for us -- without this the title, the NEW badge, the subtitle and the date
   all run together on one wrapped line. */
.t,.s,.when .d,.when .w{display:block}
.t{font-weight:600;font-size:15px;line-height:1.25}
.s{color:var(--muted);font-size:13px;margin-top:2px;
   overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.src{color:var(--ink)}
.provs{margin-top:5px;display:flex;flex-wrap:wrap;gap:4px}
.chip{background:var(--chip);color:var(--muted);font-size:11px;
      border-radius:5px;padding:1px 6px;white-space:nowrap}
.new{background:var(--accent);color:#16161a;font-weight:700;font-size:10px;
     letter-spacing:.04em;border-radius:4px;padding:1px 5px;margin-left:6px;
     vertical-align:2px}
/* 64px, not 58: measured, the widest string this column ever holds is
   "Tomorrow" at 60px. At 58 it was 2px over and sat against the title. */
.when{flex:0 0 auto;width:64px;text-align:right;font-variant-numeric:tabular-nums}
.when .d{font-size:13.5px;font-weight:600;line-height:1.2}
.when .w{font-size:11.5px;color:var(--muted)}
.empty{color:var(--muted);font-size:13px;padding:2px 0 4px}
.werr{color:var(--bad,#d4676a);font-size:13px;border:1px dashed var(--line);
      border-radius:9px;padding:10px 12px;margin:12px 0}
.werr b{color:var(--ink);font-weight:600}
@media (min-width:641px){
  .sec{margin:18px 0 0}
  .sec h2{font-size:13px;margin-top:32px}
  a.item{padding:12px 14px;margin:9px 0;gap:13px}
  .pos{width:54px;height:81px}
  .t{font-size:17px}
  .s{font-size:14px}
  .chip{font-size:12px;padding:1px 7px}
  .when{width:72px}
  .when .d{font-size:15px}
  .when .w{font-size:12.5px}
}
"""

TMDB_PAGE = "https://www.themoviedb.org/%s/%s"


def _item(row, today):
    if row["date"]:
        day, weekday = ui.day_parts(row["date"], today)
        near = ui.relative(row["date"], today)
        if near:
            day, weekday = near, ""
    else:
        # The status already reads on the subtitle line; repeating "TBA" down
        # the whole column just adds noise to a section that is entirely TBA.
        day, weekday = "", ""

    bits = []
    if row["source"]:
        bits.append('<span class="src">%s</span>' % ui.esc(row["source"]))
    if row["when"]:
        bits.append(ui.esc(row["when"]))
    sub = " · ".join(bits)

    # A dead poster path leaves a broken-image glyph in the middle of the row.
    # Clearing src is not enough -- the browser still draws the placeholder --
    # so the element is swapped for the same empty block an absent poster gets.
    poster = ('<img class="pos" loading="lazy" alt="" src="%s" onerror="'
              "this.replaceWith(Object.assign(document.createElement('span'),"
              "{className:'pos'}))\">" % ui.esc(row["poster"])
              if row["poster"] else '<span class="pos"></span>')
    provs = ui.chip(row["provider"]) if row["provider"] else ""
    return (
        '<a class="item%s" href="%s" target="_blank" rel="noopener">%s'
        '<span class="body"><span class="t">%s%s</span>'
        '<span class="s">%s</span>%s</span>'
        '<span class="when"><span class="d">%s</span><span class="w">%s</span></span></a>'
    ) % (
        " past" if row["date"] and row["date"] < today else "",
        ui.esc(TMDB_PAGE % (row["kind"], row["id"])),
        poster,
        ui.esc(row["title"]),
        '<span class="new">NEW</span>' if row.get("is_new") else "",
        sub,
        '<span class="provs">%s</span>' % provs if provs else "",
        ui.esc(day), ui.esc(weekday),
    )


def render(data):
    today = data["today"]
    out = []
    # A title on the sheet that TMDB could not place would otherwise just never
    # appear, which looks exactly like forgetting to add it.
    if data.get("unresolved"):
        out.append('<div class="werr">Not found on TMDB: %s. '
                   'Add an <b>Id</b> column to the sheet to pin it.</div>'
                   % ui.esc(", ".join(data["unresolved"])))
    if data["rows"]:
        out.append('<div class="sec">')
        out.extend(_item(r, today) for r in data["rows"])
        out.append("</div>")
    else:
        out.append('<div class="empty">Nothing scheduled.</div>')

    if data.get("pending"):
        out.append('<div class="sec"><h2>Pending release date <b>%d</b></h2>'
                   % len(data["pending"]))
        out.extend(_item(r, today) for r in data["pending"])
        out.append("</div>")
    return "".join(out)


if __name__ == "__main__":
    data = build(record=False)
    for r in data["rows"]:
        print("  %-11s %-42s %-18s %s" % (
            r["date"], r["title"][:42], r["when"][:18],
            r["provider"] or "-"))
    print("\n== Pending release date (%d)" % len(data["pending"]))
    for r in data["pending"]:
        print("  %-11s %-42s %-18s %s" % (
            "-", r["title"][:42], r["when"][:18], r["source"]))
    print("\n%d listed, %d pending, %d tracked"
          % (len(data["rows"]), len(data["pending"]), data["tracked"]))
