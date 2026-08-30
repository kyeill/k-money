# Traps

Each of these is encoded in the code and asserted in `selftest.py`. Do not
rediscover them.

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

## GitHub Pages serves index.html with `max-age=600`

So after a rebuild the browser hands the service worker a stale copy for ten
minutes. Navigations are fetched with `cache:'no-store'`, and the cache name
carries the build **time**, not just the date — two builds in one day would
otherwise share a cache name and the old entries would survive.

## Expected noise, not bugs

Studio discovery picks up **making-of specials** (Marvel's *Assembled*) and the
occasional short. There is no clean field to filter them on — `config.json`'s
`ignore` list is the intended answer.
