# Traps

Each of these is encoded in the code and asserted in `selftest.py`. Do not
rediscover them.

## `nth` is a day number, not a lookup of five ordinals

It parses `1st`..`31st`, a bare number, or `Last`. It used to be a dict of
1st-5th and Last only, which made **"the 25th" inexpressible** -- and that was
the one thing `Weekday = Day` existed for. Values past 5 are meaningless with a
weekday (no month has a sixth Tuesday) and `nth_weekday` returns nothing for
them, so a nonsense pairing is silent rather than wrong.

A day a month does not have is likewise silent: `30th` does not fire in
February. It does NOT fall back to the 28th -- `Last` + `Day` is how you ask
for that.

## An `nth` with no `Weekday` used to fire every week

Setting `4th` and ticking Sun, leaving the Weekday column blank, is the obvious
way to write "every 4th Sunday" -- and it used to drop the `nth` silently and
fire on EVERY Sunday. Four times too often, with nothing anywhere to say so.

`read_rules` now infers the weekday from the tick grid when exactly one day is
ticked. Two or more ticked days with an `nth` is genuinely ambiguous, so that
is left weekly rather than guessing which day the `nth` applies to -- the one
remaining way to write a cadence that does not do what it looks like.

## The tab always opens on the first tab

It used to restore the last tab from localStorage, which meant the app could
open on Watchlist days after you last used it. Reminders is what you want on
opening. Neither the hash nor localStorage is written any more -- nothing reads
them, and a stale `#watch` in the URL beside a Reminders pane is a lie.

## The reminder rules exist three times, and nothing enforces that from outside

`reminders.py` renders the page. The **JS copy** in the same file re-reads the
Sheet in the browser so a pull-down is live. `apps-script/reminders.gs` is the
only one that actually notifies. All three must agree.

Python and JS are compared directly: run both over the same CSV and hash the
rendered HTML. They matched byte for byte across month ends, quarter
boundaries, a 5th-Sunday month and a leap February. **Do this again after any
rule change** — the failure mode otherwise is a page that quietly disagrees
with the notifications.

The Apps Script can be reached too — see the harness section below. Change all
three in the same commit or not at all.

## ntfy.sh cannot be used from Apps Script — the quota is not yours

It was the first choice and it fails, structurally:

```
429  {"code":42908,"error":"limit reached: daily message quota reached"}
```

ntfy.sh's free tier meters **per source IP**, and Apps Script egresses from
shared Google infrastructure. The daily allowance is spent by thousands of
other people's scripts before you send anything. It is not your usage, so
nothing in the script can fix it — not retries, not backoff, not a different
URL. A POST from an ordinary machine to the same topic returns 200 with a
message id, which is what makes this so confusing to diagnose.

Delivery is therefore **Pushover**, whose limits are per account. `PROVIDER` at
the top of the Apps Script switches back to ntfy for anyone running the sender
from a normal machine, or against a self-hosted ntfy.

## "No error" never meant "delivered"

Two independent traps hid this for an hour, and both are now closed:

* `muteHttpExceptions: true` returns a 4xx as a **response**, not an exception.
  The original `push()` never looked at the status, so a refusal and a delivery
  were indistinguishable. Always check the code.
* **ntfy accepts any string as a topic** and answers 200 — so an unset `TOPIC`
  publishes happily to a topic literally named `PUT-YOUR-NTFY-TOPIC-HERE`,
  forever, with no error anywhere.

Pushover has the same shape of trap: it answers **HTTP 200 with
`{"status":0}`** for a bad token. The status code alone is not the answer, so
`push()` checks for `"status":1` as well.

The lesson generalises: when a send reports success and nothing arrives, prove
delivery at the *receiving* end. Polling the ntfy topic with `?poll=1&since=all`
and finding it empty is what turned this from guesswork into a fact.

## The Apps Script CAN be tested — run it in a browser with Google stubbed

It is the copy of the rules nothing else can reach, so it is the one most
likely to rot. It is also ordinary ES5: load the source, hand it stubbed
`Utilities` / `SpreadsheetApp` / `UrlFetchApp` / `PropertiesService` / `Logger`
via `new Function(...)`, override `Date` so `new Date()` returns a chosen
instant, and step `tick()` through 288 five-minute slots to simulate a whole
day. `Utilities.formatDate` maps onto `Intl.DateTimeFormat` with
`timeZone: 'America/New_York'` and `hourCycle: 'h23'`.

That harness earned itself immediately by finding a real bug: **`fired` was
keyed by TITLE alone**, so two rows sharing a name at different times ("Take
pills" 8am and 8pm) silently lost the second one for the rest of the day. Now
keyed by title **and** time.

Confirmed by the same run, and worth keeping true:

* a 12:32 reminder fires at 12:35 — at most one tick late, never early;
* on the DST fall-back day the 1am hour repeats, and a 1:30 AM reminder still
  fires exactly **once**;
* "last Sunday" fires on 30 Aug and 27 Sep but not on 6 Sep.

## A Google Sheet time cell is not a time

Read raw, a cell formatted `h:mm am/pm` comes back as a **Date on the
1899-12-30 epoch** — the gviz JSON endpoint literally returns
`Date(1899,11,30,12,30,0)`. Both the CSV endpoint and Apps Script's
`getDisplayValues()` hand back the *displayed* `"12:30 PM"` instead, which is
why all three parsers take a string. Never switch to raw values or
`getValues()`.

## Asking a Google Sheet for a tab that does not exist returns the FIRST tab

Silently, with no error — a trap that already cost time on `dynasty`. So the
header row is validated on every read, in `reminders.py` and again in the Apps
Script, and a mismatch is refused loudly rather than parsed as if it were the
right sheet.

## The Sheet allows cross-origin reads

`Access-Control-Allow-Origin` comes back echoing the caller, so the page can
fetch the CSV directly from `kyeill.github.io`. That is the only reason
pull-to-refresh shows an edit made a minute ago rather than this morning's
build. Do not assume it of other Google endpoints.

## TMDB's top-level `release_date` is the earliest release **anywhere on earth**

For anything with a festival or overseas premiere it is already in the past
while the film is still months from a US screen — so a film sorted on it
silently falls off an upcoming list. `movie_date()` reads the per-country
breakdown from `append_to_response=release_dates` instead, preferring US
theatrical (type 3, then the limited type 2), then digital (4), then TV (6),
then premiere (1). The types are the whole point of that endpoint.

## A returning series between seasons has **no** `next_episode_to_air`

It is `null` for the entire off-season, so reading only that field puts every
mid-run show in "No date yet". `tv_date()` falls through to the `seasons`
array and takes the earliest future `air_date`.

**Order matters:** a show that has never aired has the same date in
`first_air_date` and in season 1's `air_date`. `first_air_date` must be checked
first or a premiere is labelled "Season 1".

**Season 0 is the specials bucket** and must be excluded, or a behind-the-scenes
special becomes the thing you are waiting for.

## TMDB fills unnamed episodes in with "Episode 4"

Which is exactly what the `S2 E4` label already said. Episode names starting
`Episode ` are dropped.

## `first_air_date.gte` asks the wrong question about a series

It means "did this show *premiere* in the future", which is false for every
show currently running or returning — the first live run had no Daredevil, no
Peacemaker and no mid-run Lanterns because of it. `air_date.gte` matches on ANY
episode, which is the actual question. Films are fine on
`primary_release_date.gte`: a film has one date and it is either ahead or
behind.

## "Lucasfilm" resolves to the WRONG company

`search/company` returns **11928** for a bare "Lucasfilm". The one that matters
is **Lucasfilm Ltd. = 1**, which covers the animated shows too — *The Bad
Batch* is credited to both it and Lucasfilm Animation (108270), so one entry
catches everything. Star Wars is therefore the one franchise with a **pinned**
`company_id`; the exact-name resolver would otherwise be one typo from silence.

## DC Studios makes the DCU *and* Elseworlds, and TMDB cannot tell them apart

*The Batman: Part II* is company **184898**, exactly like *Superman* and
*Lanterns*, because DC Studios produces the Elseworlds line (The Batman, Joker)
alongside the DCU proper. There is no genre, keyword or company that separates
them reliably — the distinction is editorial, announced in press releases.

So Elseworlds titles are listed by hand in `config.json`'s `ignore`, with a
parallel `_comment_ignore_list` naming each one and why. **Expect to add to it**
as DC announces more; this is the one part of discovery that cannot be
automated, and pretending otherwise would silently put the wrong films on the
list.

## The Disney Jr. tier is officially Marvel/DC/Lucasfilm

*Spidey and His Amazing Friends*, *Iron Man and His Awesome Friends*, *Krypto
Saves the Day*, *Young Jedi Adventures* are all genuinely credited to the
studios, so discovery by company cannot tell them apart from the real slate.

The **Kids** genre (10762) separates them cleanly and catches nothing real:
X-Men '97, Marvel Zombies, Creature Commandos, My Adventures with Superman and
Star Wars: Visions all carry Animation *without* Kids. Kids is TV-only, so the
film side needs **Animation AND Family together**.

**Family alone is far too broad** — it would drop *Star Wars: Skeleton Crew*,
which is live action and exactly what must not vanish. That is asserted in
`selftest.py`; do not "simplify" the film rule to Family.

The filter runs locally against `genre_ids` on the discover results rather than
through `without_genres`, because the film rule ANDs two genres and the
`without_genres` separators do not express that reliably.

## A studio files its own podcasts under its own company

And TMDB types them **Miniseries**, so `with_type=2|4` does not catch them.
The **Talk** genre (10767, TV only) does. Animation is genre 16 and applies to
both kinds. `without_genres` takes a pipe for OR.

## TMDB called Peacemaker "Ended" while season 3 was announced

Which the status filter below then dropped. A studio-discovered title
disappearing on that basis is fine; a **hand-added watchlist entry vanishing is
indistinguishable from a bug**, so pinned rows are exempt from the status drop.

## Everything is "first seen today" on the first run

Badging the whole list says nothing, and stamping today would keep it badged
for a week. The seed batch is written with a backdated `1970-01-01` instead, so
only what actually arrives later is ever NEW.

## DC Studios is 184898

Not 128064, which is what guessing produced. It is resolved from the name at
build time for exactly this reason — Marvel Studios' 420 is folklore-stable,
DC Studios is new. The resolver prefers an **exact** name match, because
`search/company` returns DC Entertainment first.

## A date-gated `discover` cannot return an undated title

`primary_release_date.gte` excludes anything with a blank date — which is
precisely the announced-but-unscheduled slate worth knowing about. `discover()`
therefore runs two passes: the date-gated one, then a `popularity.desc` pass
whose blanks are kept.

## An undated title is not automatically "upcoming"

A cancelled or long-ended show also has no future date. Only titles whose
`status` is *not* Released / Ended / Canceled reach the TBA bucket, or the list
fills with dead projects — unless the row is pinned, see above.

## "Undated" and "waiting" are not the same number

An early tally read "48 waiting on a date" and was wrong twice over. It was
computed as `tracked - shown`, which also counted titles that *had* a date and
had simply aged out of the window. And of the 27 genuinely undated, **16 were
finished shows** — Loki, WandaVision, Hawkeye, Echo, The Penguin and the rest,
pulled in by the popularity pass, undated because they are over.

Eleven could actually get a date. That is what "Pending release date" shows:
`status not in FINISHED`, or pinned. Count the thing you mean.

## Undated titles are tracked, not listed — and the difference matters

Kyle asked to exclude anything without a date. Dropping them from *discovery*
would have been the obvious reading and the wrong one: nothing would then
notice the day a slate project finally gets scheduled. They stay in `collect`
and are filtered out in `listing`.

The same distinction drives the NEW badge. First-seen is stamped in
`stamp_new`, on the rows actually shown — **not** in `collect`. Stamping at
discovery would mean a project banked two years ago quietly appears one morning
with no badge, on the very day it became news.

## "Release" and "Series" are not labels

They are what the date functions fall back to when there is no date, and in a
TBA list neither says anything. Undated rows show the production status
instead: Announced / Filming / Post-production / Returning.

## The date column is 64px because it was measured

The widest string it ever holds is "Tomorrow" at 60px. At 58px it was two
pixels over and sat against the title. Dates in another year drop the day
rather than the year — "Dec 2027", not "Dec 17 2027", which did not fit.

## Rent and buy providers are noise

Everything is purchasable. Only `flatrate` answers the actual question — is
this included on something already paid for. `watch/providers` is US-only here
by config.

## `display_priority` ranks the RESELLER above the real service

TMDB lists each service twice: the service, and the variant you bolt onto
someone else's bill ("HBO Max Amazon Channel"). That is not a different place
to watch it, only a different way to pay — and the priority field is actively
misleading here: **HBO Max Amazon Channel is 11, actual HBO Max is 152.**
Sorting on it alone picks the reseller every time.

Drop names ending in "Channel" first, and only then let `display_priority`
choose between genuinely different services (Disney+ 5 beats Hulu 6). If a
title is carried *only* by resellers, name the odd one rather than saying
nothing.

## `site.py` shadows a stdlib module name

`site` is imported by Python at startup, so `import site` anywhere in this
project returns the **standard library's** `site`, not the shell. Running
`python site.py` is fine (it is `__main__`). `selftest.py` loads the shell by
file path for this reason.

## GitHub delivers scheduled runs late

Sometimes by hours, and it delivers the queued slots all at once. The gate asks
whether **today** has been built, not what hour it is — gating a queued trigger
on wall-clock hour means it may never fire at all. (Learned the expensive way
on `dynasty`.)

The gate must also **not** block a manual dispatch or a push, or a code change
shipped after the morning build redeploys the old page and looks like it
worked.

## The deploy job must be gated on the build having run

`if: needs.build.outputs.built == 'yes'`. Without it a catch-up slot skips the
build, uploads no artifact, and `deploy-pages` fails on "No artifacts named
github-pages" every morning.

## A workflow registers only when a push *modifies* its file

If `build.yml` arrives in the repo-creation push, GitHub never scans it: Actions
looks healthy, the sidebar lists no workflow, and `gh workflow run` says the
workflow is not found. Fix: edit the file and push again. (From `standings`.)

## Action versions: take the bump deliberately

An action declares which Node runtime it wants. GitHub is retiring Node 20 from
its runners and, for now, force-runs those actions on Node 24 with a
deprecation annotation instead of failing them. Nothing is broken — until the
fallback is withdrawn, at which point the morning deploy fails unattended.

`upload-pages-artifact@v5` and `deploy-pages@v5` (2026-08-30) clear both
annotations; v3 pulled in `upload-artifact@v4`, which was the transitive
offender. Interfaces checked before bumping, not assumed: v5 deploy-pages runs
on node24 and still outputs `page_url`, v5 upload-pages-artifact still takes
`path`.

Current: `checkout@v5`, `setup-python@v6`, `upload-pages-artifact@v5`,
`deploy-pages@v5`.

## `TZ=America/New_York date` does NOT work in the local Git Bash

It silently returns UTC — the tz database is not there. The workflow's gate
depends on that conversion, so **never reason about whether the gate will fire
from local `date` output**. On ubuntu-latest it works correctly: the run at
2026-08-30T01:02Z stamped `2026-08-29`, which is the right Eastern date, and is
how the conversion was confirmed to work where it matters.

## "any maskable" is a promise about the artwork, not just a manifest string

Declaring `"purpose": "any maskable"` tells Android to treat the icon as
adaptive and mask it to the launcher's shape — circle, squircle, teardrop —
cropping roughly **20% off each edge**. Two things follow, and the string alone
without them makes the icon *worse*, not better:

1. **Full bleed.** The background must reach every corner. The old SVG drew a
   rounded rectangle; masked, that rounds an already-rounded corner and leaves
   a notch of launcher wallpaper.
2. **Glyph inside the safe zone**, the centred circle of 80% diameter. The K
   spans 0.29–0.71 vertically and its furthest pixel sits 0.31 of the icon
   width from centre, against a 0.40 limit.

Both are asserted in `selftest.py` by decoding the generated PNG — corners
must be background, and no foreground pixel may fall outside the safe radius.
Do not change the geometry without re-running it.

Icons are drawn by pixel maths with `zlib` + `struct` because there is no image
library on this machine — the same approach, palette and sizes as
`sports-daily`, whose structure this deliberately follows.

## GitHub Pages serves index.html with `max-age=600`

So after a rebuild the browser hands the service worker a stale copy for ten
minutes. Navigations are fetched with `cache:'no-store'`, and the cache name
carries the build **time**, not just the date — two builds in one day would
otherwise share a cache name and the old entries would survive.

## Expected noise, not bugs

Studio discovery picks up **making-of specials** (Marvel's *Assembled*) and the
occasional short. There is no clean field to filter them on — `config.json`'s
`ignore` list is the intended answer.
