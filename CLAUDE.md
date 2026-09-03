# Working on K Money

Read `README.md` first for the design, then `NOTES.md` for the trap list — each
entry there already cost a debugging pass.

## Orientation

Kyle's rolling list of upcoming films and shows: Marvel and DC discovered
automatically by studio, plus hand-added one-offs. Built by GitHub Actions each
morning and published to Pages. Nothing runs locally.

```
python site.py           build the app into output/site/
python site.py --tab X   build one tab, while working on it
python watch.py          print the list as text (writes no history)
python reminders.py      print the next eight days of reminders
python church.py         print upcoming church events
python tasks.py          print open tasks, rolled forward
python teams.py          print the season, week by week
python resolve.py --write fill watchlist ids in from titles
python selftest.py       476 assertions -- run before trusting any change
```

Python is not on PATH:
`C:\Users\kyleh\AppData\Local\Programs\Python\Python312-arm64\python.exe`

**No pandas or numpy.** Standard library plus `requests`.

`selftest.py` runs against `fixtures/tmdb.json` — no API key, no network. Any
change to the date logic belongs there before it belongs in the page.

## It is a shell, deliberately

Kyle asked for this so that **unrelated tabs can be added later**. Watchlist is
just the first one. `tabs.py` documents the contract and is the only file that
knows tabs exist — resist putting tab-specific anything into `site.py`.

## If you are Claude and this folder is your working directory

Kyle's project notes live in the memory for the **parent** directory,
`C:\Users\kyleh\My Drive\Documents\Claude`. Opening a session here loads none
of it. A copy sits in `..\memory-backup\`.

Two standing preferences of his, easy to miss:

* End every reply with a clearly marked section of outstanding **questions**,
  plus key notes and action items. Buried asks get lost.
* **Verify by running things.** Most trap lists came from code that looked
  obviously correct.

He has also asked that README and NOTES be kept updated **constantly**, across
all his projects — treat doc updates as part of every change, not a cleanup
pass afterwards.

## Publishing a change

1. commit
2. `git pull --rebase` — the build commits `seen.json` and `_last_build.txt`,
   so your push is rejected otherwise. This happens routinely; expect it.
3. push

**A push builds and deploys on its own** (the gate only skips *scheduled*
runs), so nothing else is needed. Confirm with
`gh run watch <id> -R kyeill/k-money --exit-status`.

To force a run without a code change, delete
`output/history/_last_build.txt`, commit and push, then
`gh workflow run build.yml -R kyeill/k-money`.

`gh` is installed at `C:\Program Files\GitHub CLI\gh.exe` but is **not on PATH**
in Claude's shell — call it by full path, and omit the leading slash on
`gh api` endpoints or Git Bash rewrites them into Windows paths. A
`permissions.allow` rule in `~/.claude/settings.json` covers it; without that
rule every `gh` call is refused by the auto-mode classifier, and Claude cannot
add the rule itself.

## Validation routine — run all of it before trusting a change

`python selftest.py` (476 assertions), plus: compile every module, run every
entry point (`site.py`, `site.py --fixtures`, `site.py --tab watch`,
`watch.py`, `reminders.py`, `church.py`, `teams.py`, `tasks.py`, `resolve.py`), a dead-code sweep (every `def` and module constant
cross-referenced across all files; CSS classes checked against the built page,
remembering that `.on`, `.past`, `.empty` and `.new` are applied at runtime and
always look unused), and a structural check of the page — balanced tags, and
one provider chip at most per row.

**A local build will not match the live one byte for byte.** `cache/` holds
TMDB responses for hours, so a local run can render staler data than the
workflow just fetched. Compare structure, not bytes.
