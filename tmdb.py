"""The only module that talks to TMDB.

Auth is a v3 API key in TMDB_API_KEY, or a gitignored secrets.json holding
{"tmdb_api_key": "..."} for local runs. Every response is cached on disk so a
day of iterating costs one round of requests.
"""

import json
import os
import time
import urllib.parse

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
BASE = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p"

# Detail payloads carry air dates that move; discover results move less. Both
# are short enough that a same-day rebuild after an edit still refetches.
TTL_DETAIL = 6 * 3600
TTL_DISCOVER = 12 * 3600

_session = None
_offline = None          # canned payloads; set by selftest


def use_fixtures(entries):
    """Run without a key or a network, against canned payloads (selftest).

    `entries` is a list of {"path", "when", "data"}. A fixture matches when the
    path is equal and every key in `when` matches that request parameter --
    a subset, not the whole query, so a fixture does not have to restate the
    six boilerplate params every discover call carries.
    """
    global _offline
    _offline = entries


def _fixture(path, params):
    for entry in _offline:
        if entry["path"] != path:
            continue
        if all(str(params.get(k)) == str(v) for k, v in (entry.get("when") or {}).items()):
            return entry["data"]
    raise KeyError("no fixture for %s %s" % (path, params))


def api_key():
    key = os.environ.get("TMDB_API_KEY", "").strip()
    if key:
        return key
    path = os.path.join(HERE, "secrets.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as fh:
            key = (json.load(fh).get("tmdb_api_key") or "").strip()
        if key:
            return key
    raise SystemExit(
        "No TMDB key. Set TMDB_API_KEY, or write secrets.json with\n"
        '  {"tmdb_api_key": "..."}\n'
        "Get one free at themoviedb.org -> Settings -> API."
    )


def _cache_path(path, params):
    stem = path.strip("/").replace("/", "-")
    if params:
        bits = "-".join(f"{k}={params[k]}" for k in sorted(params))
        stem += "-" + urllib.parse.quote(bits, safe="")
    return os.path.join(CACHE, stem[:150] + ".json")


def get(path, ttl=TTL_DETAIL, **params):
    """One GET, cached. `path` is the bit after /3, e.g. "movie/1234"."""
    if _offline is not None:
        return _fixture(path, params)

    cached = _cache_path(path, params)
    if ttl and os.path.exists(cached) and time.time() - os.path.getmtime(cached) < ttl:
        with open(cached, encoding="utf-8") as fh:
            return json.load(fh)

    global _session
    if _session is None:
        _session = requests.Session()

    query = dict(params)
    query["api_key"] = api_key()
    for attempt in range(3):
        r = _session.get(f"{BASE}/{path.lstrip('/')}", params=query, timeout=20)
        # TMDB answers 429 with Retry-After when it is unhappy. Everything else
        # in the 5xx range is worth one more try.
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", 2)) + 0.5)
            continue
        if r.status_code >= 500 and attempt < 2:
            time.sleep(1.5 * (attempt + 1))
            continue
        break
    r.raise_for_status()
    data = r.json()

    os.makedirs(CACHE, exist_ok=True)
    tmp = cached + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, cached)
    return data


# ---------------------------------------------------------------- lookups

def company_id(name):
    """Resolve a studio name to its TMDB id.

    Pinning ids in config would be faster but wrong the day a studio is
    reorganised -- DC Studios is new enough that its id is not folklore the way
    Marvel Studios' 420 is. Exact name match first, then the top hit.
    """
    data = get("search/company", ttl=30 * 86400, query=name)
    hits = data.get("results") or []
    if not hits:
        return None
    for h in hits:
        if (h.get("name") or "").strip().lower() == name.strip().lower():
            return h["id"]
    return hits[0]["id"]


def discover(kind, cid, today, language="en-US", region="US"):
    """Everything a company has dated in the future, plus its undated slate.

    Two passes on purpose. A date-gated discover cannot return a title with no
    date at all, and the undated ones are exactly the announced-but-unscheduled
    projects worth knowing about -- so the second pass sorts by popularity and
    keeps the blanks.
    """
    date_field = "primary_release_date" if kind == "movie" else "first_air_date"
    common = {
        "with_companies": cid,
        "include_adult": "false",
        "language": language,
        "region": region,
    }
    out, seen = [], set()

    for page in (1, 2):
        data = get(f"discover/{kind}", ttl=TTL_DISCOVER, page=page,
                   sort_by=f"{date_field}.asc",
                   **{f"{date_field}.gte": today}, **common)
        for row in data.get("results") or []:
            if row["id"] not in seen:
                seen.add(row["id"])
                out.append(row)
        if page >= (data.get("total_pages") or 1):
            break

    undated = get(f"discover/{kind}", ttl=TTL_DISCOVER,
                  sort_by="popularity.desc", **common)
    for row in undated.get("results") or []:
        if not (row.get(date_field) or "").strip() and row["id"] not in seen:
            seen.add(row["id"])
            out.append(row)
    return out


def detail(kind, tid, language="en-US"):
    """One call per title. append_to_response saves two round trips each."""
    extra = "watch/providers"
    if kind == "movie":
        # The top-level release_date is the earliest release ANYWHERE, which
        # for a film with a foreign or festival premiere is not the day it is
        # watchable here. release_dates carries the per-country breakdown.
        extra += ",release_dates"
    return get(f"{kind}/{tid}", language=language, append_to_response=extra)


def search(kind, title, language="en-US"):
    data = get(f"search/{kind}", ttl=7 * 86400, query=title, language=language,
               include_adult="false")
    return data.get("results") or []


def poster(path, size="w154"):
    return f"{IMG}/{size}{path}" if path else None
