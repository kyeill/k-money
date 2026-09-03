# K Money

A rolling list of what is coming out — Marvel, DC and Star Wars by default,
plus whatever one-offs are worth following — built once a morning by GitHub
Actions and published as an installable page.

It is a **tab shell**. Five tabs — **Active**, **Reminders**, **Teams**,
**Church** and **Watchlist** — and `tabs.py` is the only file that knows
that; its order is the nav order.

Under the title sits **`Updated 2:07 pm`**. The build stamps an epoch rather
than a formatted string, because the workflow runs in UTC and the reader does
not — only the browser knows which clock to render it on. A bare time is only
honest on the day it was made, so a build from an earlier day shows its **date**
instead: an installed app can sit on a stale render for days, and
`Updated 6:04 am` would then be a lie about which morning.

Reminders, Church and the Watchlist all read the same Google Sheet, **by tab name**. Asking a
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

## Active

Dated to-dos that **roll over until they are done**. First in the nav, so the
app opens on it -- what is still to do is the thing worth seeing first. The tab
is called Active; the module, the Sheet tab and the config key stay `tasks`.

```
Task   Due   Category   Done
```

Deliberately not more columns on the Reminders sheet, because it is a different
kind of thing. A reminder is a **schedule**: a rule fires on the days its
cadence names, and an unticked one simply does not come back tomorrow. A task is
an **open item**: it has a due date and stays open until it is closed, appearing
every day from its due date onward. Same app, different model, different tab.

**A due date is required.** The point of the tab is that everything on today's
list is something you meant to do today; an undated backlog living at the foot
of every day would break that. A row with no readable date is *named on the
page* rather than dropped, so it cannot go missing silently.

**Rollover is silent.** An overdue task moves to today and looks like anything
else — his call. How late it is, is computed and available, just not shown.

### Adding and completing, without opening the Sheet

That was the whole objection to a spreadsheet: typing into Sheets on a phone is
worse than not capturing the thought at all. So the page writes.

**+ Add a task** takes a title, a date and a category, and appends a row through
the Apps Script web app — the same endpoint the reminder checkboxes already use.
**Ticking a task** writes the date into its `Done` cell, which is what removes it
from every device. **Tapping a task's title** opens it in the same form to edit,
with the button reading Save.

That is why a row is no longer a single `<label>`. It used to be, so a tap
anywhere ticked it; editing needs its own target, so the title is a `<button>`
and the checkbox keeps its own padded label. Both stay reachable by thumb and by
keyboard.

The category is a **dropdown**, not free text — there are five categories and a
typo can no longer invent a sixth. The date field sets `color-scheme: dark`,
without which the browser draws its own calendar icon in light mode: a black
glyph on a near-black field, which is why the date looked like a plain text box.
Focusing it calls `showPicker()`, so tapping opens the calendar rather than
merely focusing something that accepts a date.

The tab **re-fetches the Sheet in the browser**, so an added task appears
immediately rather than at tomorrow's build. Which means the rules exist twice,
in `tasks.py` and again in JS — much smaller than the Reminders duplication
(parse, drop done, roll over, group) but the same discipline applies.

A tick, an add and an edit are all fire-and-forget `no-cors` calls, so for a few
seconds the Sheet does not agree yet — and Google's CSV export lags a write by
several seconds on top of that. Three `localStorage` lists cover the gap: ticks,
adds, and edits.

An **edit cannot reuse the add list**: the row is already in the CSV, so it has
to be *replaced as it is read* rather than appended. Edits are therefore keyed by
the key the task had **before** the edit, applied while parsing each row, and
dropped the moment the row comes back already carrying the new values. All three
lists expire after five minutes, so a write that genuinely failed cannot leave a
ghost on the page for ever.

Editing only ever touches an **open** row. Editing a completed task would
resurrect it, and the page never offers that — a closed task is not on screen to
tap.

**The key is `Task@YYYY-MM-DD`**, built identically in `tasks.py`, in the
browser copy and in the Apps Script. Row position cannot be the key: sorting the
sheet would repoint every tick at the wrong row.

### Categories

**Five fixed categories**, in `tasks.py`:

| | |
| --- | --- |
| Personal | orange `#e8730c` |
| Work | red `#d84343` |
| Blog | blue `#3d8ee0` |
| Church | yellow `#e0c341` |
| Other | grey `#8b93a0` |

Colours were derived from the category name at first, so a new one typed on a
phone needed no commit. That was dropped because derived colours **collide** —
Blog and Personal both came out pink — and because five names he actually uses
is a list, not an algorithm.

The shades are picked for a 13% wash on a near-black card, so each is a mid
tone: a pure red or yellow at full strength would either shout or vanish. Work
is softened from a true red, which on this page would read as an error.

**Anything not one of the five renders as Other**, which is the point of Other
being on the list. A typo should look like a task filed under Other, not like a
sixth category nobody meant to create.

### Before the tab exists

Asking Google for a tab that is not there hands back the **first** tab, so the
header check refuses it — correctly, but "no task column" is a poor first
impression. That case renders as *"No Tasks tab on the sheet yet"* with the add
form still there, and adding the first task creates the tab.

## Teams

Every remaining game for **Michigan football**, **Michigan basketball** and
**Tottenham**, from ESPN's public API. No Google Sheet, no live scores, no
records — one build a day is the whole story.

Weeks start on **Monday** and are headed `Week of September 7`. Within a week games run
chronologically, with any **TBD after the games that have a time** — ESPN stamps
an unscheduled game at midnight, so sorting on the timestamp alone floats it
above a noon kickoff that is genuinely earlier in the day. It is not the first
game, it is the one nobody has scheduled. A row is **three lines**, laid out as a grid so the
right-hand figure stays level with the name it belongs to:

```
[crest]  Western Michigan Broncos at      Sat Sep 5
[crest]  #16 Michigan Wolverines            7:30 PM
         College Football                       NBC
```

The date belongs to the first team's line and the time to the second's; the
competition and network share the quieter third. Separate blocks would drift
apart the moment a team name wrapped, which is why it is a grid.

### The marquee windows

A network renders **blue** when the game falls in a showcase window the
competition names for itself — FOX at noon, CBS at 3:30, NBC or ABC on Saturday
night, the Saturday Premier League match on NBC. So the week's marquee games
are findable without reading every row.

Matched on the **network and the kickoff together**, never either alone: FOX has
a 3:30 window of its own and NBC carries ordinary games midweek, so matching on
the channel would light up half the season and say nothing. The bounds are a
range rather than an exact time, partly because a window shifts occasionally and
partly because Britain and the States change their clocks on different dates,
which moves the Saturday match by an hour for a fortnight each year.

`marquee_windows` sits per sport in `config.json`. Today three of the 49 games
qualify.

### Two endpoints, because neither is enough

| Team | Endpoint | Why |
| --- | --- | --- |
| Michigan FB / BB | `teams/130/schedule` | A whole season in one small call, with AP rankings |
| Tottenham | `scoreboard?dates=` per competition | The team endpoint knows only its league, and would miss the Carabao Cup entirely |

The schedule endpoint returns **team colours as `null`**, so the opponent's
stripe is looked up from the league's `/teams` list. The scoreboard carries
colours already.

**No `season` parameter, and no falling back a year.** ESPN returns the current
season on its own, and a fallback is actively wrong: ask basketball for last
season and it happily returns thirty-four games from last winter. Michigan
basketball is simply **absent** until ESPN publishes the schedule — silence, by
his choice, not a placeholder.

### Colour

Sports Daily's scheme, and **its actual rules** — `invisible_colour` and
`washed_out` are copied across rather than reinvented. A naive "is it bright
enough" test throws away Brighton's `#0606fa`, a vivid blue whose luminance is
*darker than a navy*; what separates them is the strongest channel, which peaks
at 64 for a navy and 250 for that blue. Likewise saturation, not brightness,
separates the Yankees' silver from Leeds' yellow.

The **stripe is the opponent's** colour: an override first, then the primary
unless it reads as black or white, then the alternate — that is how the
Steelers become gold. When nothing shows, something still beats nothing.
Checked against sports-daily's own `_colour()` over a Premier League season:
**zero mismatches**, Brighton's vivid `#0606fa` included.

**Crests use ESPN's `-dark` variant**, which is the default URL with the size
folder swapped, because that is the one that reads on a dark page. For some
clubs it is a flat white silhouette, so `logo-overrides.json` names the ones
where the default reads better. Tottenham is deliberately NOT among them: its
dark crest is a white cockerel, which is what it should be.

That list is **pulled from sports-daily's repo at build time**, since its
`logos.py --write` is the generator — it measures the actual pixels of both
variants. `logo-overrides.json` here is the committed **fallback**: a GitHub
blip must not silently change every crest on the page, and a list a few days
old beats one that cannot be read at all.
Each `<img>` carries the plain URL as an `onerror` fallback, since not every
team has a dark variant on the CDN.

The **wash is yours** — maize for Michigan, blue for Tottenham, fixed in
`config.json` rather than taken from ESPN, which has Michigan's primary as navy
with maize only as the alternate, and Tottenham's as **white**.

Michigan is `#fad105`, a slightly greener maize than ESPN's `#ffcb05`, at the
shared 13%. **He picked it on his own phone**, and that matters: a low-alpha
wash over a near-black card is exactly where displays diverge, so the same hex
is genuinely a different colour on a phone OLED and a desktop LCD. It could not
be settled from screenshots on my side, and 28% looked right to me and too
yellow to him.

**Strength is still per team** (`wash_strength`), because it was needed while
that was being worked out and the next colour may need it again. Nothing sets
it today.

A washed row is a lighter ground than the plain card, so the ordinary muted grey
loses contrast on it — **4.33** against this maize, just under readable. The
competition and network line lifts to `#a3a39d` on any tinted row, which holds
4.82. Deliberately the *gentlest* lift that clears the bar rather than the
brightest, so the third line stays visibly quieter than the names above it.

**Ranks are blue** (`#8fb0d8`), the same light blue as a marquee network and
for the same reason — a dark navy would vanish against this ground. The Church
tab borrows the same blue for its second week, so there is one blue across the
app rather than two that nearly match.

Crests are **20px** and team names **14.5px**, mirroring sports-daily: the two
pages sit side by side on the same phone and were a size apart.

The date and the time are one column — same size, same weight, same colour.
They were always the same size; it was the muted grey that made the time read
as the smaller of the two.

### The shared colour list

`team_colors` is a **master list shared with sports-daily**. They are separate
repos with separate builds, so it cannot be one file on disk; it is read from
the **`Colors` tab of the same Google Sheet**, laid over the copy committed in
`config.json`.

**standings deliberately does not share it.** It draws a wash across a whole
table row where these two draw a 3px stripe, and the two want different answers
-- a navy that reads as a crisp edge disappears once it is lightened and spread
out. This tab is the master for STRIPE colours.

That copy is the **fallback, not the source**: three sites read this list, and
a Sheet outage must not be able to break all three at once. The Sheet wins where
it has an opinion and says nothing where it does not.

**Format the Color column as plain text in Sheets.** An all-digit value is read
as a NUMBER and loses its leading zero — Penn State's `061440` came back as
`61440` and the row vanished. All three projects pad it back, but the cell is
the better place to fix it. Values with letters in them, like `0a2240`, are
never affected.

The tab is `Team | Color`, found by name. **The header is checked**, because
asking Google for a tab that does not exist hands back the *first* tab — without
that check a Sheet with no `Colors` tab is read as if the reminders were team
colours. Verified: it currently returns the Reminders header and is correctly
refused.

The drift this is meant to stop had already happened. Tottenham was `ffffff` in
sports-daily and `132257` in standings; the Tigers were `#0a2240` and `fa4616`.

### The conventions that make a row read wrong

**Soccer prints the home side first** (`Nottingham Forest vs. Tottenham
Hotspur`); every other sport is away at home (`Western Michigan Broncos at #16
Michigan Wolverines`). Get it backwards and every row is wrong, silently. A
neutral site is `vs.` either way.

**An unset kickoff is `TBD`, not `12:00 AM`.** ESPN stamps an unscheduled game
at midnight and flags `timeValid: false`; without that check a Big Ten game
five weeks out reads like a real midnight fixture. The *day* is right either
way, so the row still belongs where it is.

**A cup round lives in `season.slug`**, not in a note — that is where
`Carabao Cup - Third Round` comes from. A note headline wins when there is one,
which is where college keeps `Big Ten Tournament` and the bowl names.

**One network, national only.** A game carried solely on a regional feed shows
nothing, which is honest: that feed is only useful if you happen to get it.
Streaming is named only when it is the only way to watch, so a match on USA and
Peacock is a USA game.

### Which weeks

Every week from the current one to the last known fixture, **including blank
ones** — a bye week is information, and skipping it would make the list lie
about how far apart two games are. Today that is 49 games across 39 weeks, of
which 2 are empty.

Where the run *starts* is the only judgement. Inside a season it is this week,
blank or not. Outside every season — June and July — it is the week of the next
fixture, so the summer does not open on a dozen empty headings waiting for
August.

"In season" is answered by ESPN, not by a hardcoded month: `leagues[0].calendar`
gives the real matchday span (the Premier League's runs 2026-08-21 to
2027-05-30). Only the three **league** competitions are `anchors` for that test.
A cup's calendar is an administrative window — the Carabao Cup reports 1 June to
1 June — and including one would claim you are in season all summer.

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

**The date heading is coloured by how close it is**: the nav's own accent within
a week, the Teams tab's rank blue within two, and the ordinary muted grey after that. Nothing past a fortnight is
coloured — a page where every heading is coloured highlights nothing. The two
colours are the shared `ui.py` palette, the same orange the Reminders tab uses.

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

Every row carries a poster, the title, where it came from (MCU / DCU / Star
Wars / LOTR / Custom), what the date actually *is* — `In Theaters`,
`Streaming`, `Season 2 Episode 4 ·
The Green Sea`, `Premiere` — and **one** place to stream it. Rows link to TMDB.

Below it, **Pending release date**: announced and alive, but unscheduled,
ordered by how close each is to happening — Returning, then Post-Production,
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

**`TITLE_PREFIXES` in `watch.py` drops a franchise prefix from a title** when
the source column beside it already says the same thing: `LOTR · The Rings of
Power` beats `The Lord of the Rings: The Rings of Power`, which wraps to two
lines on a phone in order to say LOTR twice. Only listed prefixes go —
`Star Wars: Skeleton Crew` keeps its own, because that is how the show is
known — and a title is never stripped to nothing.

**`LABEL_NAMES` in `watch.py` decides what a source is CALLED** — `DC` renders
as **DCU**, `Marvel` as **MCU**, `Lord of the Rings` as **LOTR**. It is matched case-insensitively
and applied to every label whatever its source, because the franchise list in
`config.json` is editable here but the Sheet's `Label` column is not, and a
label typed there should read the same way without being retyped. Keep the map
short; a rule needing many exceptions is the wrong rule.

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
python selftest.py         496 assertions, no key and no network needed
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
teams.py     the Teams tab -- ESPN schedules, weeks, colours
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
