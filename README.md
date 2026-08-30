# K Money

A rolling list of what is coming out — Marvel and DC by default, plus whatever
one-offs are worth following — built once a morning by GitHub Actions and
published as an installable page.

It is a **tab shell**, not a watchlist app. Watchlist is the first tab; unrelated
tabs are meant to be added beside it later.

## What it shows

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
python selftest.py         75 assertions, no key and no network needed
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
watch.py    the Watchlist tab -- date logic, ordering, and its own render
ui.py       shared render helpers
tabs.py     the registry
site.py     the shell: frame, nav, service worker, manifest
resolve.py  title -> tmdb id, run by hand
selftest.py fixture-driven; no key, no network
```

Read `NOTES.md` before changing the date logic. Every entry there is a trap
that has already cost a debugging pass.
