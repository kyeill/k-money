"""The Watch tab: what is coming, when, and where it lands.

Two sources feed one list. Franchises are discovered from TMDB by studio, so a
newly announced Marvel or DC project appears without anyone adding it. The
watchlist is hand-edited in config.json and is only for the one-offs.
"""

import datetime as dt
import json
import os

import tmdb
import ui

HERE = os.path.dirname(os.path.abspath(__file__))
SEEN = os.path.join(HERE, "output", "history", "seen.json")

KEY = "watch"
LABEL = "Watch"

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
    with open(path or os.path.join(HERE, "config.json"), encoding="utf-8-sig") as fh:
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


def providers(detail, region="US"):
    """Where it streams. Rent and buy are deliberately ignored: the question is
    whether it is included somewhere already paid for, not whether it is
    purchasable, and every title is purchasable."""
    block = ((detail.get("watch/providers") or {}).get("results") or {}).get(region) or {}
    seen, out = set(), []
    for entry in block.get("flatrate") or []:
        name = entry.get("provider_name")
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


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
        "providers": providers(detail, region),
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


def collect(cfg, today, record=True):
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
                                     cfg.get("exclude_animation", True)):
                wanted.setdefault("%s/%s" % (kind, row["id"]),
                                  (fr.get("label") or fr["key"], False))

    for item in cfg.get("watchlist") or []:
        if item.get("id"):
            wanted["%s/%s" % (item["type"], item["id"])] = (item.get("label") or "Mine", True)

    rows = []
    for key, (source, pinned) in sorted(wanted.items()):
        kind, tid = key.split("/")
        if key in ignore or tid in ignore:
            continue
        row = make_row(kind, tmdb.detail(kind, tid, lang), source, region, today)
        row["pinned"] = pinned
        rows.append(row)

    seen, ran_before = _load_seen()
    cutoff = _shift(today, -NEW_FOR_DAYS)
    # On the very first run every title is "first seen today", which would badge
    # the whole list -- and stamping today would keep badging it for a week.
    # The seed batch is backdated instead, so only what arrives later is new.
    stamp = today if ran_before else SEED
    for row in rows:
        row["first_seen"] = seen.setdefault(row["key"], stamp)
        row["is_new"] = row["first_seen"] > cutoff
    if record:
        _save_seen(seen)
    return rows


def bucket(rows, cfg, today):
    """Sort into the five horizons the page shows."""
    soon = _shift(today, cfg.get("soon_days", 7))
    near = _shift(today, cfg.get("near_days", 30))
    back = _shift(today, -abs(cfg.get("keep_released_days", 14)))

    out = {"out": [], "now": [], "soon": [], "later": [], "tba": []}
    for row in rows:
        day = row["date"]
        if not day:
            # A released, ended or cancelled title with no date is not
            # upcoming, it is just gone. Only live projects belong in TBA --
            # EXCEPT one added by hand, which must never vanish silently.
            # TMDB calls Peacemaker "Ended" while season 3 is announced, and a
            # watchlist entry disappearing on that basis looks like a bug.
            if row["status"] in ("Released", "Ended", "Canceled") and not row.get("pinned"):
                continue
            out["tba"].append(row)
        elif day < today:
            if day >= back:
                out["out"].append(row)
        elif day <= soon:
            out["now"].append(row)
        elif day <= near:
            out["soon"].append(row)
        else:
            out["later"].append(row)

    for name, group in out.items():
        group.sort(key=lambda r: (r["date"] or "9999-99-99", r["title"]),
                   reverse=(name == "out"))
    return out


SECTIONS = [
    ("now", "This week"),
    ("soon", "Next 30 days"),
    ("later", "Later"),
    ("tba", "No date yet"),
    ("out", "Just out"),
]


def build(today=None, cfg=None, record=True):
    today = today or dt.date.today().isoformat()
    cfg = cfg or load_config()
    rows = collect(cfg, today, record)
    return {"today": today, "buckets": bucket(rows, cfg, today), "count": len(rows)}


# ----------------------------------------------------------------- render
# Each tab owns its own CSS so that adding an unrelated one later cannot mean
# editing a shared stylesheet and hoping nothing else moved.

CSS = """
.sec{margin:22px 0 0}
.sec h2{font-size:12px;text-transform:uppercase;letter-spacing:.08em;
        color:var(--muted);font-weight:600;margin:0 0 8px}
.sec h2 b{color:var(--ink);font-weight:600}
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
@media (min-width:641px){
  .sec{margin:28px 0 0}
  .sec h2{font-size:13px}
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
    day, weekday = ui.day_parts(row["date"], today)
    near = ui.relative(row["date"], today)
    if near:
        day, weekday = near, ""

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
    provs = "".join(ui.chip(p) for p in row["providers"])
    return (
        '<a class="item" href="%s" target="_blank" rel="noopener">%s'
        '<span class="body"><span class="t">%s%s</span>'
        '<span class="s">%s</span>%s</span>'
        '<span class="when"><span class="d">%s</span><span class="w">%s</span></span></a>'
    ) % (
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
    for key, title in SECTIONS:
        rows = data["buckets"][key]
        if not rows and key != "now":
            continue
        out.append('<div class="sec"><h2>%s <b>%d</b></h2>' % (ui.esc(title), len(rows)))
        if rows:
            out.extend(_item(r, today) for r in rows)
        else:
            out.append('<div class="empty">Nothing this week.</div>')
        out.append("</div>")
    return "".join(out)


if __name__ == "__main__":
    data = build(record=False)
    for key, title in SECTIONS:
        rows = data["buckets"][key]
        print("\n== %s (%d)" % (title, len(rows)))
        for r in rows:
            print("  %-11s %-42s %-18s %s" % (
                r["date"] or "TBA", r["title"][:42], r["when"][:18],
                ", ".join(r["providers"]) or "-"))
