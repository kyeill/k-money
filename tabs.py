"""The tab registry -- the one place to touch when adding a tab.

A tab is any module exposing:

    KEY     str   url fragment and localStorage value, e.g. "watch"
    LABEL   str   what the nav button reads
    CSS     str   its own rules; the shell owns only the frame  (optional)
    build() -> data          whatever that tab needs, JSON-shaped
    render(data) -> str      the HTML inside its <section>

Nothing else in the app knows what a tab is. A second, unrelated tab is a new
module plus one line here.
"""

import watch

TABS = [watch]


def by_key(key):
    return next((t for t in TABS if t.KEY == key), None)
