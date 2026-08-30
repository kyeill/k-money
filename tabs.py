"""The tab registry -- the one place to touch when adding a tab.

A tab is any module exposing:

    KEY     str   url fragment and localStorage value, e.g. "watch"
    LABEL   str   what the nav button reads
    CSS     str   its own rules; the shell owns only the frame  (optional)
    build() -> data              whatever that tab needs, JSON-shaped
    render(data) -> str          the HTML inside its <section>
    page_js(data) -> str         browser-side code for this tab   (optional)

Nothing else in the app knows what a tab is. A new tab is a module plus one
line here -- and this list's ORDER is the nav order.
"""

import church
import reminders
import watch

TABS = [reminders, church, watch]


def by_key(key):
    return next((t for t in TABS if t.KEY == key), None)
