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

## A date-gated `discover` cannot return an undated title

`primary_release_date.gte` excludes anything with a blank date — which is
precisely the announced-but-unscheduled slate worth knowing about. `discover()`
therefore runs two passes: the date-gated one, then a `popularity.desc` pass
whose blanks are kept.

## An undated title is not automatically "upcoming"

A cancelled or long-ended show also has no future date. Only titles whose
`status` is *not* Released / Ended / Canceled reach the TBA bucket, or the list
fills with dead projects.

## Rent and buy providers are noise

Everything is purchasable. Only `flatrate` answers the actual question — is
this included on something already paid for. `watch/providers` is US-only here
by config.

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
