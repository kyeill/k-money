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
python resolve.py --write fill watchlist ids in from titles
python selftest.py       72 assertions -- run before trusting any change
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

## Publishing a change the same day

1. commit
2. `git pull --rebase` — the morning build commits `seen.json`, so your push is
   rejected otherwise
3. delete `output/history/_last_build.txt`, commit, push

A push builds and deploys on its own (the gate only skips *scheduled* runs), so
step 3 matters only if you also want to dispatch manually:
`gh workflow run build.yml -R kyeill/k-money`

`gh` is installed at `C:\Program Files\GitHub CLI\gh.exe` but is **not on PATH**
in Claude's shell — call it by full path, and omit the leading slash on
`gh api` endpoints or Git Bash rewrites them into Windows paths.
