# K Money

A rolling list of what is coming out — Marvel, DC and Star Wars by default,
plus whatever one-offs are worth following — built once a morning by GitHub
Actions and published as an installable page.

It is a **tab shell**. Three tabs — **Reminders**, **Church** and
**Watchlist** — and `tabs.py` is the only file that knows that; its order is
the nav order.

Reminders and Church both read the same Google Sheet, **by tab name**. Asking a
Sheet for a tab that does not exist returns the FIRST one, so position would
mean a reorder silently redirects everything.

## Reminders

A Google Sheet is the source of truth, and the tab shows the next **eight**
days (`DAYS_SHOWN` in `reminders.py`, which feeds the browser copy too).

```
A Title   B Time   C–I Mon…Sun   J nth   K Every   L Starting   M Months
```

**Title, Time and the day columns are positional. Everything after them is
found by NAME**, so those columns can be added, removed or reordered freely —
`Weekday` used to sit in there and no longer does. A heading that is not
recognised is named on the page, because a typo in `Starting` would otherwise
drop the column silently and stop every interval reminder.

**A time is required.** A reminder without one can never fire, so those rows
are skipped — which means a row with only a title works as a section header.
Blank rows are ignored too.

### The three cadences

**Weekly** — tick the days. Any non-empty mark counts.

**Monthly** — `nth` plus a day. It takes `1st`–`31st`, a bare number, the words
`First`–`Fifth`, or `Last`, **and a list**: `1st, 3rd` fires on both.

| ticked days | `nth` means |
| --- | --- |
| exactly one | that weekday — `4th` + Sun is the 4th Sunday |
| none | **day of the month** — `25th` is the 25th, `Last` the last day |
| two or more | ambiguous, so it stays weekly rather than guessing |

A day a month does not have simply does not fire: `30th` skips February rather
than landing somewhere else. (`Weekday`, if you re-add the column, takes
`Mon`–`Sun` or `Day` and overrides the inference.)

**Interval** — `Every` plus `Starting`. `4 weeks` + `2026-09-07` fires on the
7th and every 28 days after, never varying. That is *not* "every 4th Monday",
which stretches to five weeks across some month boundaries. `Every` takes
`N weeks` or `N days` (`2w`, `3d` too) and **a unit is required** — a bare
number could mean either. `Starting` accepts ISO or `9/7/2026`, since Sheets
renders dates in the viewer's locale. A future anchor just delays the start.

**Interval beats monthly beats weekly. One row, one schedule.**

**`Months` gates all three**, which is how anything gets a season — tick `Sat`
and put `Sep, Oct, Nov, Dec` in Months for "every Saturday, but only in the back
half of the year". It takes blank/`All`, `Quarterly` (Jan/Apr/Jul/Oct), or a
list. Blank means all twelve, so it costs existing rows nothing.

A cadence cell that parses to nothing is **called out on the page** rather than
silently reverting to the weekly ticks. That fallback once hid eight broken
rows: a typo did not look like a typo, it looked like a different schedule.

### Ticking things off

**Today's reminders have a checkbox.** Ticks are written to a second tab in
the Sheet called `Done`, not to the browser — which is what makes them show up
on every device *and* stop the notification. The Apps Script checks the same
tab before it sends. Only today is tickable; ticking ahead would silence a
notification days early.

The page can read the Sheet but not write to it, so a tick calls the Apps
Script deployed as a **web app** (`reminders_webapp` in config.json). That URL
is public, and the endpoint answers accordingly: it validates the date, checks
the key against a reminder that actually exists, and only ever flips one
checkbox — so the worst a stranger who finds it can do is tick your laundry
off. Leave `reminders_webapp` blank and ticking is simply disabled.

### On the page

Only today is named; every other day carries its date. Within a day, the first
reminder at or after **4pm** gets space above it, so a day reads as day and
then evening — space only, not a heading, because it is one day rather than two
sections. A day with nothing before 4pm gets no stray gap at the top.
`AFTERNOON_HOUR` in `reminders.py` is the one place to move it; it feeds the
browser copy too.

A day with no checkboxes **reserves their width anyway**, so the times and
titles hold one column all the way down instead of stepping left after today.

**Today's reminders are shaded orange until they are ticked**, the same shade
the Church tab uses, so what is still outstanding reads at a glance. The wash
carries it alone — no leading stripe, unlike Church, where the stripe is what
separates one colour from another; there is only one colour here, so it had
nothing to distinguish.

It is CSS alone: `.tick` is only ever on today's rows and `.done` is already
toggled by the checkbox handler, so ticking clears the shading with no JS aware
the rule exists, and a future day is never shaded. The palette lives in `ui.py`
rather than in either tab, since `church.py` imports `reminders.py` and the
dependency cannot run the other way.

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

**That refresh does not flash**, which took two separate fixes.

The new markup is **compared before it is written**, so a refresh that rebuilds
what is already there does not tear the rows down and build them again. Both
sides go through `innerHTML` before comparing: read back out of the DOM the
browser normalises quoting and attribute order, so a freshly built string never
matches character for character even when the markup is identical.

That alone does not help a reload, because there the two really are different:
**the baked copy was built at 6am**, so everything ticked since comes back
unticked — and, since today's unticked rows are shaded, orange. The comparison
correctly repaints, and the repaint is the flash. So the **last list actually
seen is kept in `localStorage` and painted back before any network**; the fetch
that follows almost always just confirms it. It is keyed by date — yesterday's
list restored this morning would be worse than the baked one — and older keys
are pruned. Every access is wrapped, because a page opened from a `data:` URL
throws on `localStorage` rather than returning nothing.

Which means the rules exist **twice**: in `reminders.py` and again in JS. That
duplication is deliberate and it is *checked* — `selftest.py` asserts the Python
side, and a browser cross-check runs both over the same CSV across month ends,
quarter boundaries and a leap year, comparing the rendered HTML exactly. See
NOTES before touching either.

### Setting the reminders up

In the Sheet: **Extensions → Apps Script**, paste `apps-script/reminders.gs`,
fill in the Pushover keys at the top, run `setup()`. That installs the
5-minute trigger, creates the `Done` tab, and sends one message to prove the
credentials work.

Then, for the checkboxes, deploy the same script as a web app:

1. **Deploy → New deployment**
2. "Select type" has a **gear icon** beside it — choose **Web app**
3. **Execute as: Me**, **Who has access: Anyone** (not "Anyone with Google
   account", or the page cannot call it without a login)
4. **Deploy**, authorise (the "Google hasn't verified this app" warning is
   expected for your own script), and copy the `/exec` URL into
   `reminders_webapp` in `config.json`

Open that URL in a browser to check it: `{"ok":false,"error":"unknown action"}`
means it is live and reachable anonymously, which is exactly right.

**Editing the script does not update the deployment.** The `/exec` URL keeps
serving whatever was deployed. After any edit: **Deploy → Manage deployments →
pencil → Version: New version → Deploy**. Paste and run `setup()` BEFORE
deploying, or the web app goes live without `doGet` and ticks fail silently.

## Church

Dated events from the `Church` tab. Grouped by day, soonest first, and only
days that actually have something on them — most days do not, and a column of
empty headings would bury the handful that matter. Dates in the past are
dropped.

```
Title   Details   Date   Color
```

**Every column here is found by NAME, and only `Title` and `Date` are
required.** Details and Color arrived *between* the two original columns, which
under position would have read the details as the date and dropped every row.
Order them however you like; a heading nobody recognises is named on the page,
because an ignored column should not be invisible.

A row is the Watchlist's shape — title above, quieter detail below — so the app
reads as one app rather than three. A `Details` cell that just repeats the
`Title` is dropped: the same line twice reads as a bug, not as detail.

`Color` shades the row the way Sports Daily shades its games: a stripe down the
leading edge **and** the whole bubble washed in the same colour, so a glance
sorts meetings from worship. It takes a name — red, orange, amber, yellow,
green, teal, blue, navy, purple, pink, brown, gray, black, white — or a literal
`#rrggbb`. The named values are picked to show against the dark card; black and
white are bent towards a slate and a bone, since neither says anything as a
stripe here. A blank or unrecognised colour is simply no shading.

The wash is 13% and the card colour is painted **underneath** it. Both matter:
at full strength the colour fights the text sitting on it, and a translucent
colour laid straight on the page background would make a tinted row *darker*
than a plain one. It is mixed in Python rather than by CSS `color-mix()`, which
not every phone browser this gets read on has.

Much simpler than Reminders on purpose. Every row carries its own date, so
there is no cadence to recompute, nothing to notify, and nothing that has to
stay in step with the Apps Script. Dates parse as US or ISO; one that cannot be
read is named on the page rather than the event just never appearing.

Baked at build time only — no live re-fetch, unlike Reminders. It changes
rarely enough that next morning is soon enough.

## Watchlist

**Ordered by when each thing is next out**, in two sections: **Next 30 days**,
then **Upcoming**. It was one unbroken list until 2026-08-30 — one heading is
what separates this month from someday, and someday runs to 2028.

Something released in the last 14 days stays on, dimmed, and stays in the
**near** section: it is the most actionable thing on the page, and the only
reason it is listed at all is `keep_released_days`, which exists so a release
is not missed by looking a day late. Filing it below films two years out would
be exactly backwards.

The near heading shows even when nothing falls under it — "nothing out in the
next 30 days" is news, while a missing section reads as a page that failed to
render. `SOON_DAYS` in `watch.py` moves the boundary, which is inclusive: the
30th day is near, the 31st is not.

Every row carries a poster, the title, where it came from (Marvel / DC /
Custom), what the date actually *is* — `In theaters`, `Streaming`, `Season 2 Episode 4 ·
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

**Three is not an arbitrary number: those are the franchises that ARE one
production company.** Lord of the Rings is not, and cannot be added as a
fourth. Checked against TMDB — Rings of Power credits Amazon Studios and New
Line Cinema, and discovering by New Line returns The Conjuring, Evil Dead,
Final Destination and Hello Kitty. Keywords do not rescue it either: the show
carries none of `middle earth`, `lord of the rings` or `tolkien`, and
discovering by all three finds a single unrelated short film. So LOTR titles
are added one at a time, by hand, and that is what the `Label` column is for.

**Animation is excluded** (`exclude_animation`), along with the studios' own
**making-of podcasts** and the **Disney Jr. tier** (`exclude_preschool`).

**Elseworlds films are excluded by hand.** DC Studios produces *The Batman* and
*Joker* alongside the DCU proper, all under company 184898, and TMDB has no
field that separates them — the distinction is editorial. They live in
`config.json`'s `ignore`, each one named in `_comment_ignore_list`. Expect to
add to it as DC announces more; see NOTES.

Series are found by `air_date` rather than first air date, so a show already
running or between seasons is caught — that is what puts Daredevil and Lanterns
on the list at all.

**The one-offs are hand-added**, from two places that are merged into one list.

The **`Watchlist` tab of the same Google Sheet** is the everyday one, because
it can be edited from a phone and `config.json` cannot:

```
Title   Label   Type   Id
```

Only `Title` is required and **all four are found by name**. `Label` is what
shows in the source column (default `Custom`), `Type` is `movie` or `tv`
(default `tv`), and `Id` overrules the search when it picks wrong.

Because the sheet gives only a title, the id is **resolved by search once and
then remembered** in `output/history/watchlist.json`, which the build commits.
After that it is read, never guessed — so a wrong match is a line in a diff
rather than a show that quietly turns into a different show. The build prints
what each title resolved to the first time.

That same file is the **fallback if the sheet cannot be read**. An empty
response is not an empty list: a Watchlist tab with nothing on it still returns
its header row, so nothing at all means the fetch failed, and honouring that
would drop every hand-added title for the day.

**`Type` is worth understanding.** It defaults to `tv`, and a film searched as
a series finds *nothing* — so when the declared kind comes back empty the other
kind is tried before giving up. That is what lets a one-column sheet hold *The
Hunt for Gollum*: it is a film, and nobody should have to know a column exists
to say so. The kind that actually matched is what gets remembered.

**A title TMDB cannot place is named on the page**, not just missing. A show
you added that never appears looks exactly like forgetting to add it.

`config.json`'s `watchlist` still works and is merged in — it is **empty by
choice**, not unused. Keep an entry there when it needs a *written reason* a
spreadsheet cell cannot hold. Peacemaker used to be the example: TMDB marks it
Ended while season 3 is announced, so discovery drops it and only a pin kept it
visible. That pin is gone by his call — it comes back when TMDB updates the
status. Entries here need `type` and `id`; leave the id `null` and
`python resolve.py --write` fills it in.

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
python selftest.py         317 assertions, no key and no network needed
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
church.py    the Church tab -- dated events, no cadences, no notifications
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
