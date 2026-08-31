"""The K Money shell: frame, tabs, service worker. Tabs supply their own body.

    python site.py            build output/site/
    python site.py --tab X    build only tab X (faster while working on it)
"""

import datetime as dt
import json
import os
import struct
import sys
import zlib

import tabs
import ui

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, "output", "site")

APP = "K Money"

# Same two colours as the page, and as sports-daily's icon.
BG = (0x16, 0x16, 0x1A)
FG = (0xE0, 0x83, 0x4F)

FONT = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
        'family=Source+Sans+3:wght@400;600;700&display=swap">')

# The frame only. Everything inside a section belongs to that tab's own CSS,
# so tabs cannot quietly restyle each other.
SHELL_CSS = """
:root{
  --bg:#16161a; --card:#1e1e23; --ink:#ececea; --muted:#9a9a95;
  --line:#2e2e35; --accent:#e0834f; --chip:#2a2a31;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
     font-family:"Source Sans 3",system-ui,-apple-system,"Segoe UI",sans-serif;
     font-size:15px;line-height:1.45;-webkit-text-size-adjust:100%}
.wrap{max-width:720px;margin:0 auto;padding:0 14px 70px}
header{padding:18px 0 10px}
h1{font-size:20px;margin:0}
h1 span{color:var(--muted);font-weight:400;font-size:14px;margin-left:8px}
nav{position:sticky;top:0;z-index:5;background:var(--bg);
    border-bottom:1px solid var(--line);margin:0 -14px;padding:0 8px;
    display:flex;gap:2px;overflow-x:auto;scrollbar-width:none}
nav::-webkit-scrollbar{display:none}
nav button{flex:0 0 auto;background:none;border:0;color:var(--muted);
    font:inherit;font-size:14px;padding:11px 12px;cursor:pointer;
    border-bottom:2px solid transparent;white-space:nowrap}
nav button[aria-selected="true"]{color:var(--ink);border-bottom-color:var(--accent)}
section{display:none;padding-top:6px}
section.on{display:block}
footer{margin-top:34px;color:var(--muted);font-size:12px;
       border-top:1px solid var(--line);padding-top:11px}
@media (min-width:641px){
  body{font-size:16px;line-height:1.5}
  .wrap{max-width:860px;padding:0 16px 80px}
  header{padding:24px 0 12px}
  h1{font-size:26px;letter-spacing:-0.01em}
  nav{margin:0 -16px;padding:0 10px}
  nav button{font-size:15px;padding:12px 15px}
  footer{font-size:13px}
}
"""

SW = """
const CACHE='kmoney-v%(v)s';
self.addEventListener('install',e=>{self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(c=>c.addAll(['./','./index.html'])))});
self.addEventListener('activate',e=>{e.waitUntil(
  caches.keys().then(k=>Promise.all(k.filter(n=>n!==CACHE).map(n=>caches.delete(n))))
  .then(()=>self.clients.claim()))});
self.addEventListener('fetch',e=>{
  if(e.request.method!=='GET')return;
  // GitHub Pages serves index.html with max-age=600, so after a rebuild the
  // browser would hand the worker a stale copy for ten minutes and the app
  // would quietly show yesterday's build.
  const opts = e.request.mode === 'navigate' ? {cache:'no-store'} : undefined;
  e.respondWith(fetch(e.request, opts).then(r=>{
    const copy=r.clone();
    // Cross-origin poster and font responses are opaque and reject on put, so
    // the write must never be allowed to fail the fetch.
    caches.open(CACHE).then(c=>{try{c.put(e.request,copy)}catch(_){}}).catch(()=>{});
    return r;
  }).catch(()=>caches.match(e.request)));
});
"""

JS = """
const tabs=[...document.querySelectorAll('nav button')];
const panes=[...document.querySelectorAll('section')];
function show(key,push){
  tabs.forEach(b=>b.setAttribute('aria-selected',b.dataset.k===key));
  panes.forEach(p=>p.classList.toggle('on',p.dataset.k===key));
  const btn=tabs.find(b=>b.dataset.k===key);
  if(btn&&btn.scrollIntoView)btn.scrollIntoView({inline:'nearest',block:'nearest'});
  // Neither the hash nor localStorage is written any more: nothing reads them
  // back, and a stale #watch in the URL while Reminders is showing is a lie.
}
tabs.forEach(b=>b.onclick=()=>show(b.dataset.k,true));
// ALWAYS the first tab on open. Restoring the last-used tab from localStorage
// meant the app could open on whichever one you happened to leave it on, days
// later -- Reminders is the thing you want on opening it.
if(tabs[0])show(tabs[0].dataset.k,false);
// Swipe between tabs. The gesture must be HORIZONTAL -- comparing dx to dy and
// requiring a clear winner -- or an ordinary vertical scroll down a long list
// keeps flicking you into the next tab.
let sx=0, sy=0, tracking=false;
const MIN=50;
addEventListener('touchstart',e=>{
  if(e.touches.length!==1){tracking=false;return}
  sx=e.touches[0].clientX; sy=e.touches[0].clientY; tracking=true;
},{passive:true});
addEventListener('touchend',e=>{
  if(!tracking)return;
  tracking=false;
  const t=e.changedTouches[0];
  const dx=t.clientX-sx, dy=t.clientY-sy;
  if(Math.abs(dx)<MIN||Math.abs(dx)<=Math.abs(dy))return;
  const cur=tabs.findIndex(b=>b.getAttribute('aria-selected')==='true');
  const next=cur+(dx<0?1:-1);
  if(next>=0&&next<tabs.length)show(tabs[next].dataset.k,true);
},{passive:true});

if('serviceWorker' in navigator)
  navigator.serviceWorker.register('./sw.js').catch(()=>{});

// A page left open does not refetch. An installed app resumed from the home
// screen shows its last render for as long as the phone keeps it alive, and a
// desktop tab restored from the back/forward cache does the same -- either way
// the build behind it moves on without the reader ever seeing it.
const BUILT='%%BUILT%%';
let hidden=Date.now();
function stale(){
  const n=new Date();
  const today=new Date(n.getTime()-n.getTimezoneOffset()*6e4).toISOString().slice(0,10);
  return today!==BUILT||(Date.now()-hidden)>18e5;
}
document.addEventListener('visibilitychange',()=>{
  if(document.visibilityState==='hidden'){hidden=Date.now();return;}
  if(stale())location.reload();
});
window.addEventListener('pageshow',e=>{if(e.persisted&&stale())location.reload();});
"""

MANIFEST = {
    "name": APP, "short_name": APP,
    "start_url": ".", "scope": ".",
    "display": "standalone", "background_color": "#16161a",
    "theme_color": "#16161a",
    # "any maskable" tells Android to treat these as adaptive icons and mask
    # them to the launcher's shape, as sports-daily does. That is a promise
    # about the artwork -- see _png.
    "icons": [{"src": "icon-%d.png" % s, "sizes": "%dx%d" % (s, s),
               "type": "image/png",
               "purpose": "any maskable"} for s in (192, 512)],
}


def _seg_dist(px, py, ax, ay, bx, by):
    """Distance from a point to a line segment, for drawing the K's arms."""
    dx, dy = bx - ax, by - ay
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return ((px - (ax + t * dx)) ** 2 + (py - (ay + t * dy)) ** 2) ** 0.5


def _png(size):
    """A flat 'K' on a dark ground, drawn by pixel maths.

    No image library on this machine, so this is the same zlib+struct approach
    sports-daily uses for its ring.

    Two rules follow from the manifest declaring **maskable**: Android masks
    the icon to the launcher's shape (circle, squircle, teardrop) and may crop
    roughly 20% off each edge.

    1. FULL BLEED. The background must reach every corner -- no rounded
       rectangle of its own, or the mask rounds an already-rounded corner and
       leaves a notch.
    2. The glyph must sit inside the SAFE ZONE, the centred circle of 80%
       diameter. This K spans 0.29-0.71 vertically and reaches x=0.71, putting
       its furthest corner 0.30 from centre against a safe radius of 0.40.
    """
    stem_x0, stem_x1 = 0.31, 0.39
    top, bottom = 0.29, 0.71
    junction = (0.39, 0.50)
    arm_end_y = (top, bottom)
    arm_x = 0.67
    half = 0.042

    rows = []
    for y in range(size):
        row = bytearray([0])            # filter byte: none
        fy = (y + 0.5) / size
        for x in range(size):
            fx = (x + 0.5) / size
            on = stem_x0 <= fx <= stem_x1 and top <= fy <= bottom
            if not on:
                for end_y in arm_end_y:
                    if _seg_dist(fx, fy, junction[0], junction[1],
                                 arm_x, end_y) <= half:
                        on = True
                        break
            row += bytes(FG if on else BG)
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def render(built, panes):
    """panes: [(key, label, html, js)] in nav order; js may be ""."""
    panes = [p if len(p) == 4 else (p[0], p[1], p[2], "") for p in panes]
    css = SHELL_CSS + "".join(getattr(tabs.by_key(k), "CSS", "")
                              for k, _, _, _ in panes)
    nav = "".join(
        '<button data-k="%s" aria-selected="false">%s</button>' % (ui.esc(k), ui.esc(lbl))
        for k, lbl, _, _ in panes)
    body = "".join(
        '<section data-k="%s">%s</section>' % (ui.esc(k), html)
        for k, _, html, _ in panes)
    # Tab code runs after the shell's, so the panes it looks for already exist.
    tab_js = "".join(js for _, _, _, js in panes if js)
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1,"
        "viewport-fit=cover\">"
        "<title>%(app)s</title>"
        "<meta name=\"theme-color\" content=\"#16161a\">"
        "<link rel=\"manifest\" href=\"manifest.webmanifest\">"
        "<meta name=\"apple-mobile-web-app-capable\" content=\"yes\">"
        "<meta name=\"apple-mobile-web-app-status-bar-style\" content=\"black-translucent\">"
        "<link rel=\"apple-touch-icon\" href=\"icon-180.png\">"
        # Without this a desktop browser asks for /favicon.ico, which the site
        # does not ship, and shows a blank tab icon after the 404.
        "<link rel=\"icon\" href=\"icon-192.png\">"
        "%(font)s<style>%(css)s</style></head><body><div class=\"wrap\">"
        "<header><h1>%(app)s<span>%(pretty)s</span></h1></header>"
        "<nav>%(nav)s</nav>%(body)s"
        "<footer>Built %(pretty)s · film data from TMDB</footer>"
        "</div><script>%(js)s</script></body></html>"
    ) % {
        "app": ui.esc(APP), "font": FONT, "css": css, "nav": nav, "body": body,
        "pretty": pretty(built),
        "js": JS.replace("%%BUILT%%", built) + tab_js,
    }


def pretty(iso):
    return dt.date.fromisoformat(iso).strftime("%d %b %Y")


def main():
    only = None
    if "--tab" in sys.argv:
        only = sys.argv[sys.argv.index("--tab") + 1]
    record = "--no-record" not in sys.argv
    built = dt.date.today().isoformat()

    if "--fixtures" in sys.argv:
        # Styling work should not need a key, a network, or a real morning's
        # data. Renders the same canned payloads selftest.py asserts against --
        # including its config, so that adding a title to the real watchlist
        # does not break this mode until a fixture is written for it.
        import json as _json
        import tmdb
        with open(os.path.join(HERE, "fixtures", "tmdb.json"), encoding="utf-8") as fh:
            tmdb.use_fixtures(_json.load(fh))
        built, record = "2026-08-29", False
        os.environ["KMONEY_CONFIG"] = os.path.join(HERE, "fixtures", "config.json")
        os.environ["KMONEY_REMINDERS_CSV"] = os.path.join(
            HERE, "fixtures", "reminders.csv")
        os.environ["KMONEY_REMINDERS_DONE"] = os.path.join(
            HERE, "fixtures", "reminders-done.csv")
        os.environ["KMONEY_CHURCH_CSV"] = os.path.join(
            HERE, "fixtures", "church.csv")
        os.environ["KMONEY_WATCHLIST_CSV"] = os.path.join(
            HERE, "fixtures", "watchlist.csv")
        # Somewhere disposable: a fixture run must not overwrite the ids the
        # real build resolved and committed.
        os.environ["KMONEY_WATCHLIST_STATE"] = os.path.join(
            HERE, "output", "fixtures-watchlist.json")

    panes = []
    for tab in tabs.TABS:
        if only and tab.KEY != only:
            continue
        data = tab.build(today=built, record=record)
        js = getattr(tab, "page_js", lambda _d: "")(data)
        panes.append((tab.KEY, tab.LABEL, tab.render(data), js))
    if not panes:
        raise SystemExit("no tabs built (--tab %s matched nothing)" % only)

    os.makedirs(SITE, exist_ok=True)
    page = render(built, panes)
    write(os.path.join(SITE, "index.html"), page)
    write(os.path.join(SITE, "manifest.webmanifest"), json.dumps(MANIFEST, indent=2))
    # 180 is Apple's touch icon; 192 and 512 are what the manifest declares.
    for icon_size in (180, 192, 512):
        with open(os.path.join(SITE, "icon-%d.png" % icon_size), "wb") as fh:
            fh.write(_png(icon_size))
    # The build TIME, not just the date: two builds in one day would otherwise
    # share a cache name and the old entries would survive.
    stamp = built.replace("-", "") + dt.datetime.now().strftime("%H%M%S")
    write(os.path.join(SITE, "sw.js"), SW % {"v": stamp})
    print("wrote %s (%.1f KB) -- tabs: %s"
          % (os.path.join(SITE, "index.html"), len(page) / 1024,
             ", ".join(k for k, _, _, _ in panes)))


def write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


if __name__ == "__main__":
    main()
