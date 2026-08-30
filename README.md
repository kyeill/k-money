# K Money

A rolling list of what is coming out — Marvel, DC and Star Wars by default,
plus whatever one-offs are worth following — built once a morning by GitHub
Actions and published as an installable page.

It is a **tab shell**. Two tabs today — **Reminders** and **Watchlist** — and
`tabs.py` is the only file that knows that.

## Reminders

A Google Sheet is the source of truth, and the tab shows the next seven days.

| Title | Time | Mon…Sun | nth | Weekday | Months |
| --- | --- | --- | --- | --- | --- |
| Laundry | 12:30 PM | `x` under Sun | | | |
| Credit Cards | 2:00 PM | | `Last` | `Sun` | `All` |
| Rent | 9:00 AM | | `1st` | `Day` | `All` |
| Quarterly tax | 8:00 AM | | `Last` | `Day` | `Quarterly` |

Any non-empty mark ticks a weekday. `nth` takes `1st`–`5th` or `Last`;
`Weekday` takes `Mon`–`Sun` or **`Day`** for day-of-month; `Months` takes
blank/`All`, `Quarterly` (Jan/Apr/Jul/Oct), or a list like `Jan, Jul`. **A time
is required** — a reminder without one can never fire. If a row has both a
monthly rule and weekly ticks, it is monthly: one row, one schedule.

**`Months` gates weekly rows too**, which is how a reminder gets a season —
tick `Sat` and put `Sep, Oct, Nov, Dec` in Months for "every Saturday, but only
in the back half of the year". A blank Months means all twelve, so it costs
existing rows nothing.

Notifications arrive titled **`Laundry (Sun 8/30)`**. Android's own snooze
re-shows a notification hours later with no hint of which occurrence it was,
and a bare "Laundry" then tells you nothing.

**The page does not send anything.** A static site cannot wake a phone. The
notifications come from `apps-script/reminders.gs`, an Apps Script bound to the
Sheet running on a 5-minute trigger, which POSTs to **Pushover**. That script
holds the credentials and they never enter this repo.

ntfy.sh was the first choice and does not work from Apps Script: its free tier
meters per source IP, and Apps Script shares Google egress, so the daily quota
is spent by strangers before you send anything. `PROVIDER` at the top of the
script switches back for anyone sending from a normal machine. See NOTES.

The Sheet allows cross-origin reads, so the tab **re-fetches it in the browser**
on open and on pull-to-refresh — an edit made a minute ago shows up without
waiting for tomorrow's build. The daily build bakes a snapshot so the tab paints
instantly and still works offline.

Which means the rules exist **twice**: in `reminders.py` and again in JS. That
duplication is deliberate and it is *checked* — `selftest.py` asserts the Python
side, and a browser cross-check runs both over the same CSV across month ends,
quarter boundaries and a leap year, comparing the rendered HTML exactly. See
NOTES before touching either.

## Watchlist

**One list, ordered by when each thing is next out.** No horizon buckets.
Something released in the last 14 days stays on, dimmed, at the top — so a
release is not missed by looking a day late.

Every row carries a poster, the title, where it came from (Marvel / DC /
Custom), what the date actually *is* — `In theaters`, `Streaming`, `S2 E4 ·
The Green Sea`, `Premiere` — and **one** place to stream it. Rows link to TMDB.

Below it, **Pending release date**: announced and alive, but unscheduled,
ordered by how close each is to happening — Returning, then Post-production,
Filming, Announced.

Two kinds of title are kept out. **Finished** shows are undated because they
are *over*, not because they are waiting — studio discovery drags in sixteen of
them (Loki, WandaVision, Hawkeye, The Penguin…) and they would otherwise triple
the count. **Rumored** ones are not a plan. Both stay tracked, silently, and
appear the moment TMDB gives them a date.

A title flagged **NEW** reached the *list* within the last 7 days — which,
since undated things are not listed, usually means it just got a date. That is
the moment it is actually news. First-seen is therefore recorded when a title
becomes showable, not when discovery first saw it. The dates live in
`output/history/seen.json`, committed by the workflow, and cannot be
backfilled; the first run backdates its whole batch so nothing is badged until
something genuinely arrives.

## Where the titles come from

Two sources, one list.

**Franchises** are discovered by studio, so nothing has to be added by hand.
`config.json` lists three: **Marvel Studios** (420), **DC Studios** (184898,
resolved from the name) and **Lucasfilm Ltd.** (1, pinned — a bare "Lucasfilm"
resolves to a different company, and Lucasfilm Ltd. covers the animated shows
too).

**Animation is included.** What a studio officially made is the test, and
X-Men '97, Marvel Zombies, Creature Commandos, My Adventures with Superman and
Star Wars: Visions are all officially theirs. `exclude_animation` turns it back
off.

Discovery does exclude the studios' own **making-of podcasts** and the
**Disney Jr. tier** (`exclude_preschool`) — Spidey and His Amazing Friends,
Krypto Saves the Day, Young Jedi Adventures. Those are officially Marvel/DC/
Lucasfilm too, so only the Kids genre separates them; see NOTES for why the
film-side rule needs two genres rather than one.

Series are found by `air_date` rather than first air date, so a show already
running or between seasons is caught — that is what puts Daredevil and Lanterns
on the list at all.

**The watchlist** is hand-edited in `config.json` and is only for the one-offs.
Entries need `type` (`movie` or `tv`) and `id`. Write the title, leave the id
`null`, and `python resolve.py --write` fills it in — then check it, because a
title search will happily pick the wrong show.

`ignore` takes `"movie/1234"` or a bare id, for anything discovery keeps
surfacing that you do not care about.

A watchlist entry is **pinned**: it is never dropped for its status. TMDB calls
Peacemaker "Ended" while season 3 is announced, and a title you added by hand
silently disappearing is indistinguishable from a bug.

## Running it

```
python site.py             build output/site/
python reminders.py        print the next seven days as text
python site.py --fixtures  build from canned data -- no key, for styling work
python site.py --tab watch build one tab only
python watch.py            print the list as text, no HTML, no history written
python resolve.py --write  fill in watchlist ids from titles
python selftest.py         150 assertions, no key and no network needed
```

Python is not on PATH:
`C:\Users\kyleh\AppData\Local\Programs\Python\Python312-arm64\python.exe`

**No pandas or numpy.** Standard library plus `requests`.

### The key

TMDB needs a free v3 API key (themoviedb.org → Settings → API). Locally it
comes from `TMDB_API_KEY` or a gitignored `secrets.json`:

```json
{ "tmdb_api_key": "..." }
```

In Actions it is the repository secret `TMDB_API_KEY`. `selftest.py` needs
neither — it runs against `fixtures/tmdb.json`.

### Fixtures

`selftest.py` and `site.py --fixtures` both run against `fixtures/tmdb.json`
**and `fixtures/config.json`** — a config of their own, deliberately not the
real one. Sharing `config.json` meant that adding a title to the watchlist
broke every test until someone wrote a TMDB payload for it.

The override is the `KMONEY_CONFIG` environment variable, which `load_config`
honours ahead of the default path. It is generic on purpose: any future tab
reading config gets pointed at the fixture set the same way.

## Installing it

Open the site on a phone and use "Add to Home Screen" / "Install app". It then
runs standalone, and the self-refresh matters most there: a page left open on a
home screen otherwise shows its last render for as long as the phone keeps it
alive.

The icons follow `sports-daily`'s structure — PNGs at 180/192/512 drawn by
pixel maths (there is no image library on this machine), with the manifest
declaring `"purpose": "any maskable"` so Android treats them as adaptive and
masks them to the launcher's shape. That declaration constrains the artwork:
full bleed to every corner, glyph inside the centred 80% safe zone. Both are
asserted in `selftest.py` by decoding the generated PNG — see NOTES before
changing the geometry.

## Adding a tab

`tabs.py` is the only file that knows tabs exist. A tab is a module with:

```python
KEY = "budget"          # url fragment, localStorage value
LABEL = "Budget"        # nav button text
CSS = "..."             # its own rules; optional
def build(today=None, record=True): ...   # -> JSON-shaped data
def render(data): ...                     # -> the HTML inside its <section>
def page_js(data): ...                    # -> browser code for it (optional)
```

…and one line in `tabs.TABS`. The shell owns the frame, the nav, the service
worker and the light/dark palette; nothing else. Tab CSS is concatenated after
the shell's, so keep selectors scoped — two tabs both styling `.row` would
collide. The nav bar shows even with a single tab; a lone tab that hid its own
bar made the app look like it had none.

## The shape of it

```
tmdb.py      the only thing that talks to TMDB; disk-cached
watch.py     the Watchlist tab -- date logic, ordering, and its own render
reminders.py the Reminders tab -- sheet rules, and the same rules again in JS
ui.py        shared render helpers
tabs.py      the registry; this list's ORDER is the nav order
site.py      the shell: frame, nav, service worker, manifest, icons
resolve.py   title -> tmdb id, run by hand
selftest.py  fixture-driven; no key, no network

apps-script/reminders.gs   NOT part of the build -- paste into the Sheet's
                           Apps Script editor. The only thing that notifies.
```

Read `NOTES.md` before changing the date logic. Every entry there is a trap
that has already cost a debugging pass.
