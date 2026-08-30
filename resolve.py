"""Fill in tmdb ids for watchlist entries that only have a title.

    python resolve.py            show what each untitled entry resolves to
    python resolve.py --write    write the ids back into config.json

A title search can absolutely pick the wrong show -- there are four things
called "The Pitt" -- so the id is written back once and then never guessed
again, and this prints the year and overview so you can check it.
"""

import json
import os
import sys

import tmdb
import watch

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "config.json")


def main():
    write = "--write" in sys.argv
    with open(CONFIG, encoding="utf-8-sig") as fh:
        cfg = json.load(fh)

    changed = 0
    for item in cfg.get("watchlist") or []:
        if item.get("id"):
            continue
        kind = item.get("type") or "tv"
        hits = tmdb.search(kind, item.get("title", ""), cfg.get("language", "en-US"))
        if not hits:
            print("  ?  %-40s no match" % item.get("title"))
            continue
        top = hits[0]
        name = top.get("title") or top.get("name")
        year = (top.get("release_date") or top.get("first_air_date") or "")[:4]
        print("  %s  %-40s -> %s (%s) id %s" % (
            kind[:2], item.get("title"), name, year or "?", top["id"]))
        for other in hits[1:4]:
            print("      also: %s (%s) id %s" % (
                other.get("title") or other.get("name"),
                (other.get("release_date") or other.get("first_air_date") or "?")[:4],
                other["id"]))
        item["id"] = top["id"]
        changed += 1

    if not changed:
        print("nothing to resolve")
        return
    if write:
        with open(CONFIG, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
            fh.write("\n")
        print("\nwrote %d id(s) into config.json -- check them" % changed)
    else:
        print("\n%d id(s) found. Re-run with --write to save them." % changed)


if __name__ == "__main__":
    main()
