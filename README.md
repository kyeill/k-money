# K Money

A rolling list of what is coming out — Marvel and DC by default, plus whatever
one-offs are worth following — built once a morning by GitHub Actions and
published as an installable page.

It is a **tab shell**, not a watchlist app. Watch is the first tab; unrelated
tabs are meant to be added beside it later.

## What it shows

One list, five horizons:

| Section | What lands there |
| --- | --- |
| This week | today through the next 7 days — always shown, even when empty |
| Next 30 days | the rest of the month |
| Later | anything dated beyond that |
| No date yet | announced and alive, but unscheduled — labelled Announced / Filming / Post-production / Returning |
| Just out | released in the last 14 days, so nothing gets missed |

Every row carries a poster, the title, where it came from (Marvel / DC / your
own), what the date actually *is* — `In theaters`, `Streaming`, `S2 E4 · The
Green Sea`, `Premiere` — and which services stream it. Rows link to TMDB.

A title first seen within the last 7 days is flagged **NEW**, which is how a
freshly announced project makes itself known. First-seen dates live in
`output/history/seen.json`, committed by the workflow, and cannot be
backfilled. The first run backdates its whole batch, so nothing is badged until
something genuinely arrives.

## Where the titles come from

Two sources, one list.

**Franchises** are discovered by studio, so nothing has to be added by hand.
`config.json` lists them; `company_id` is resolved from the studio name on
first run if it is left `null`. Marvel Studios is pinned at 420, which is
folklore-stable; DC Studios resolves to 184898.

Discovery deliberately excludes **animation** (`exclude_animation`, on) and,
for series, the studios' own **making-of podcasts**. Series are found by
`air_date` rather than first air date, so a show already running or between
seasons is caught — that is what puts Daredevil and Lanterns on the list at
all.

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
python site.py --fixtures  build from canned data -- no key, for styling work
python site.py --tab watch build one tab only
python watch.py            print the list as text, no HTML, no history written
python resolve.py --write  fill in watchlist ids from titles
python selftest.py         72 assertions, no key and no network needed
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

## Adding a tab

`tabs.py` is the only file that knows tabs exist. A tab is a module with:

```python
KEY = "budget"          # url fragment, localStorage value
LABEL = "Budget"        # nav button text
CSS = "..."             # its own rules; optional
def build(today=None, record=True): ...   # -> JSON-shaped data
def render(data): ...                     # -> the HTML inside its <section>
```

…and one line in `tabs.TABS`. The shell owns the frame, the nav, the service
worker and the light/dark palette; nothing else. Tab CSS is concatenated after
the shell's, so keep selectors scoped — two tabs both styling `.row` would
collide. The nav bar hides itself while there is only one tab.

## The shape of it

```
tmdb.py     the only thing that talks to the network; disk-cached
watch.py    the Watch tab -- date logic, buckets, and its own render
ui.py       shared render helpers
tabs.py     the registry
site.py     the shell: frame, nav, service worker, manifest
resolve.py  title -> tmdb id, run by hand
selftest.py fixture-driven; no key, no network
```

Read `NOTES.md` before changing the date logic. Every entry there is a trap
that has already cost a debugging pass.
