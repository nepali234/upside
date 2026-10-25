#!/usr/bin/env python3
"""
Upside Radar scraper.

The whole idea in four steps:
  1. Read the watchlist (docs/companies.json).
  2. Ask each company's job board for its open jobs (plain HTTP, no AI).
  3. Keep the ones that fit: software roles, your level, US or remote.
  4. Merge into docs/jobs.json, remembering when each job was first seen
     and marking jobs that disappeared as closed.

The tracker page (docs/index.html) reads jobs.json. GitHub Actions runs this
every morning and commits the result.

Standard library only. Run locally with:  python3 scraper.py
"""

import html
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
COMPANIES_FILE = DOCS / "companies.json"
JOBS_FILE = DOCS / "jobs.json"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; upside-radar/1.0)", "Accept": "application/json"}
# Amazon and anything it owns: never, ever.
BLOCKED_COMPANIES = re.compile(r"\bamazon\b|\baws\b|\bzoox\b|\btwitch\b|\baudible\b|whole foods|\bimdb\b|\bzappos\b"
                               r"|one medical|\bwondery\b|goodreads|^ring$", re.I)
KEEP_CLOSED_DAYS = 60


# ---------------------------------------------------------------------------
# 1. Fetching. Every fetcher returns a list of
#    {"id", "title", "location", "url", "postedAt", "description"} dicts.
#    The description is only used for filtering; it is never saved.
# ---------------------------------------------------------------------------

def http_json(url, body=None, timeout=30):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = dict(HEADERS)
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def make_job(prefix, slug, job_id, title, location, url, posted=None, description=""):
    return {
        "id": f"{prefix}-{slug}-{job_id}",
        "title": (title or "").strip(),
        "location": (location or "").strip(),
        "url": url or "",
        "postedAt": to_iso(posted),
        "description": plain_text(description),
    }


def plain_text(markup):
    """Job descriptions come as HTML (Greenhouse escapes it twice). Turn it into one line of plain text."""
    text = html.unescape(markup or "")
    text = re.sub(r"<(br|/p|/li|/div|/h\d)\b[^>]*>", ". ", text, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"\s+", " ", text).strip()


ISO = "%Y-%m-%dT%H:%M:%SZ"


def to_iso(value):
    """Board dates come as ISO strings with offsets or as epoch milliseconds. Return UTC 'Z' or None."""
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        elif isinstance(value, datetime):
            dt = value
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime(ISO)
    except (ValueError, OverflowError, OSError):
        return None


def workday_posted(text, now=None):
    """Workday says 'Posted Today', 'Posted Yesterday', 'Posted 3 Days Ago', 'Posted 30+ Days Ago'."""
    now = now or datetime.now(timezone.utc)
    t = (text or "").lower()
    if "today" in t:
        days = 0
    elif "yesterday" in t:
        days = 1
    else:
        m = re.search(r"(\d+)\+?\s*day", t)
        if not m:
            return None
        days = int(m.group(1))
    return now - timedelta(days=days)


def fetch_greenhouse(company):
    slug = company["slug"]
    data = http_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    return [
        make_job("gh", slug, j["id"], j.get("title"), (j.get("location") or {}).get("name"), j.get("absolute_url"),
                 j.get("first_published"), j.get("content"))
        for j in data.get("jobs", [])
    ]


def fetch_lever(company):
    slug = company["slug"]
    data = http_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    jobs = []
    for j in data:
        cats = j.get("categories") or {}
        locations = cats.get("allLocations") or [cats.get("location") or ""]
        # Lever keeps requirements in "lists" (e.g. "What you'll need"), separate from the main description.
        parts = [j.get("descriptionPlain") or j.get("description") or ""]
        for item in j.get("lists") or []:
            parts += [item.get("text") or "", item.get("content") or ""]
        parts.append(j.get("additionalPlain") or j.get("additional") or "")
        jobs.append(make_job("lv", slug, j["id"], j.get("text"),
                             " · ".join(l for l in locations if l), j.get("hostedUrl"), j.get("createdAt"),
                             " . ".join(p for p in parts if p)))
    return jobs


def fetch_ashby(company):
    slug = company["slug"]
    data = http_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    jobs = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        locations = [j.get("location") or ""]
        locations += [s.get("location", "") for s in (j.get("secondaryLocations") or [])]
        if j.get("isRemote"):
            locations.append("Remote")
        unique = list(dict.fromkeys(l for l in locations if l))
        jobs.append(make_job("ab", slug, j["id"], j.get("title"), " · ".join(unique), j.get("jobUrl"),
                             j.get("publishedAt"), j.get("descriptionHtml") or j.get("descriptionPlain")))
    return jobs


def fetch_workday(company):
    """Workday career sites (NVIDIA and many big companies) have a public JSON search endpoint."""
    w = company["workday"]
    base = f"https://{w['host']}"
    endpoint = f"{base}/wday/cxs/{w['tenant']}/{w['site']}/jobs"
    jobs = []
    for offset in range(0, 200, 20):
        data = http_json(endpoint, {"appliedFacets": {}, "limit": 20, "offset": offset,
                                    "searchText": w.get("search", "software engineer")})
        postings = data.get("jobPostings", [])
        for p in postings:
            path = p.get("externalPath", "")
            job_id = path.rstrip("/").split("_")[-1] or path
            location = p.get("locationsText") or ""
            if re.match(r"^\d+ Locations?$", location, re.I):
                location = workday_locations(endpoint.rsplit("/jobs", 1)[0] + path) or location
            jobs.append(make_job("wd", company["slug"], job_id, p.get("title"),
                                 location, f"{base}/en-US/{w['site']}{path}", workday_posted(p.get("postedOn"))))
        if len(postings) < 20:
            break
    return jobs


def workday_locations(detail_url):
    """Workday's search shows '3 Locations' for multi-city jobs; the job's detail page names them."""
    try:
        info = http_json(detail_url).get("jobPostingInfo", {})
    except Exception:
        return ""
    names = [info.get("location", "")] + list(info.get("additionalLocations") or [])
    return " · ".join(dict.fromkeys(n for n in names if n))


def fetch_simplify(feed):
    """Wider Net: the community-kept list of new-grad roles at every company (github.com/SimplifyJobs).
    Returns the same job dicts as the board fetchers, plus "company"."""
    jobs = []
    for x in http_json(feed["url"], timeout=90):
        if not x.get("active") or x.get("is_visible") is False:
            continue
        posted = x.get("date_posted")
        job = make_job("sf", "simplify", x.get("id"), x.get("title"), " · ".join(x.get("locations") or []), x.get("url"),
                       posted * 1000 if isinstance(posted, (int, float)) else None)
        job["company"] = (x.get("company_name") or "").strip()
        jobs.append(job)
    return jobs


FEED_FETCHERS = {"simplify": fetch_simplify}


FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "workday": fetch_workday,
    # "link": no feed; the page just shows a link to the careers site.
}


# ---------------------------------------------------------------------------
# 2. Filtering: is this a job worth showing?
# ---------------------------------------------------------------------------

def why_not(job, filters):
    """Return the reason a job doesn't fit, or None if it does."""
    title, location = job["title"], job["location"]
    if not re.search(filters["title_include"], title, re.I):
        return "title is not a software role"
    m = re.search(filters["title_exclude"], title, re.I)
    if m:
        return f"title says '{m.group(0)}'"
    # Location: Greater Seattle Area only. A job listing several cities counts
    # if any of them is in the area. No location listed = can't tell = skip.
    if not re.search(filters["location_include"], location or "", re.I):
        return "not in the Seattle area"
    # Fit Check: the title is a label; the description says what the job really asks for.
    # No description (Workday, saved jobs) = can't tell = keep.
    rule = filters.get("description_exclude")
    if rule and job.get("description"):
        m = re.search(rule, job["description"], re.I)
        if m:
            return f"posting asks for '{m.group(0).strip()}'"
    return None


def is_match(job, filters):
    return why_not(job, filters) is None


# ---------------------------------------------------------------------------
# 3. Merging with what we already know
# ---------------------------------------------------------------------------

def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def norm_name(name):
    """'The Boeing Company' -> 'boeing', 'WhatNot' -> 'whatnot'. Used to match feed names to the watchlist."""
    n = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower())
    n = re.sub(r"^the |\b(inc|llc|corp|corporation|company|co)\b", " ", n)
    return " ".join(n.split())


def refresh(config, existing_jobs, fetchers=FETCHERS, now=None, feed_fetchers=FEED_FETCHERS):
    """Pure-ish core: returns (merged_jobs, new_jobs, errors). Easy to test."""
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    filters = config["filters"]
    # If the filters changed, forget saved jobs that no longer fit them.
    by_id = {j["id"]: dict(j) for j in existing_jobs if is_match(j, filters) and not BLOCKED_COMPANIES.search(j.get("company", ""))}
    new_jobs, errors = [], []

    def upsert(job, name, source=None):
        """Add a fetched job, or refresh the one we already have. Returns False if it doesn't fit."""
        if not job["url"].startswith("https://") or not is_match(job, filters):
            by_id.pop(job["id"], None)  # a saved job that fails the Fit Check is dropped, not "closed"
            return False
        job = {k: v for k, v in job.items() if k not in ("description", "company")}
        if job["id"] in by_id:
            old = by_id[job["id"]]
            old.update(title=job["title"], location=job["location"], url=job["url"],
                       lastSeen=stamp, open=True)
            old.pop("closedAt", None)
            # Keep the earliest known posting date (Workday's "30+ days ago" drifts).
            if job.get("postedAt") and (not old.get("postedAt") or job["postedAt"] < old["postedAt"]):
                old["postedAt"] = job["postedAt"]
        else:
            record = {**job, "company": name, "firstSeen": stamp, "lastSeen": stamp, "open": True}
            if source:
                record["source"] = source
            if not record.get("postedAt"):
                record.pop("postedAt", None)
            by_id[job["id"]] = record
            new_jobs.append(record)
        return True

    for company in config["companies"]:
        name = company["name"]
        if BLOCKED_COMPANIES.search(name):
            continue
        fetcher = fetchers.get(company.get("board"))
        if not fetcher:
            continue
        try:
            fetched = fetcher(company)
        except Exception as e:  # one broken board never stops the rest
            errors.append(f"{name}: {type(e).__name__}: {e}")
            continue

        seen_here = {job["id"] for job in fetched if upsert(job, name)}

        # Jobs from this company that vanished from its board are closed.
        for record in by_id.values():
            if (record.get("company") == name and not record.get("source") and record.get("open")
                    and record["id"] not in seen_here):
                record["open"] = False
                record["closedAt"] = stamp

    # Wider Net: community feeds list roles at companies beyond the watchlist.
    # Companies we already read directly are skipped (no duplicates); link-only
    # watchlist companies (Microsoft, Google, ...) get their roles filled in from the feed.
    direct = {norm_name(n) for c in config["companies"] if c.get("board") in fetchers
              for n in [c["name"]] + c.get("aliases", [])}
    watch = {}
    for c in config["companies"]:
        for n in [c["name"]] + c.get("aliases", []):
            watch[norm_name(n)] = c["name"]
    for feed in config.get("feeds", []):
        fetcher = feed_fetchers.get(feed.get("type"))
        if not fetcher:
            continue
        try:
            fetched = fetcher(feed)
        except Exception as e:  # a broken feed never stops the run, and closes nothing
            errors.append(f"{feed['name']}: {type(e).__name__}: {e}")
            continue
        seen_here = set()
        for job in fetched:
            key = norm_name(job.get("company"))
            if not key or BLOCKED_COMPANIES.search(job["company"]) or key in direct:
                continue
            if upsert(job, watch.get(key, job["company"]), source=feed["name"]):
                seen_here.add(job["id"])
        for record in by_id.values():
            if record.get("source") == feed["name"] and record.get("open") and record["id"] not in seen_here:
                record["open"] = False
                record["closedAt"] = stamp

    # Forget jobs closed long ago so the file stays small.
    cutoff = now - timedelta(days=KEEP_CLOSED_DAYS)
    def keep(r):
        if r.get("open", True) or not r.get("closedAt"):
            return True
        return datetime.strptime(r["closedAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) > cutoff
    merged = sorted((r for r in by_id.values() if keep(r)),
                    key=lambda r: (r.get("firstSeen", ""), r.get("company", "")), reverse=True)
    return merged, new_jobs, errors


# ---------------------------------------------------------------------------
# 4. Notify (optional) and save
# ---------------------------------------------------------------------------

NEAR = re.compile(r"seattle|bellevue|redmond|kirkland|everett|bothell|remote", re.I)


def summary_text(new_jobs, errors):
    if not new_jobs:
        lines = ["No new roles today."]
    else:
        ordered = sorted(new_jobs, key=lambda j: not NEAR.search(j["location"]))
        lines = [f"{len(new_jobs)} new role(s):"] + [f"- {j['company']}: {j['title']} ({j['location'] or 'n/a'})" for j in ordered]
    if errors:
        lines += ["", "Boards that could not be checked:"] + [f"- {e}" for e in errors]
    return "\n".join(lines)


def notify_phone(topic, new_jobs):
    """Push to the free ntfy app, only when there's something new."""
    if not topic or not new_jobs:
        return
    body = summary_text(new_jobs, [])[:3500].encode("utf-8")
    req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=body, method="POST",
                                 headers={"Title": f"Upside Radar: {len(new_jobs)} new role(s)", "Tags": "briefcase"})
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print(f"(phone alert failed: {e})")


def check_board(board, slug):
    """Try a company before adding it:  python3 scraper.py check greenhouse stripe"""
    config = load_json(COMPANIES_FILE, None)
    fetcher = FETCHERS.get(board)
    if not fetcher or board == "workday":
        sys.exit("Board must be one of: greenhouse, lever, ashby")
    try:
        jobs = fetcher({"slug": slug, "name": slug})
    except Exception as e:
        sys.exit(f"Could not read {board}/{slug}: {e}\nCheck the slug in the company's job-board URL.")
    matches = [j for j in jobs if is_match(j, config["filters"])]
    print(f"{board}/{slug}: {len(jobs)} jobs on the board, {len(matches)} match your filters.")
    for j in matches:
        print(f"  - {j['title']} | {j['location']}")
    # Show what the Fit Check dropped, so a too-strict rule is easy to spot.
    no_desc = dict(config["filters"], description_exclude="")
    dropped = [(j, why_not(j, config["filters"])) for j in jobs if is_match(j, no_desc) and not is_match(j, config["filters"])]
    if dropped:
        print(f"\nDropped by the Fit Check ({len(dropped)}):")
        for j, reason in dropped:
            print(f"  - {j['title']} | {reason}")


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "check":
        return check_board(sys.argv[2], sys.argv[3])
    config = load_json(COMPANIES_FILE, None)
    if not config:
        sys.exit(f"Missing or invalid {COMPANIES_FILE}")
    existing = load_json(JOBS_FILE, {}).get("jobs", [])

    merged, new_jobs, errors = refresh(config, existing)
    JOBS_FILE.write_text(json.dumps({
        "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "errors": errors,
        "jobs": merged,
    }, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    text = summary_text(new_jobs, errors)
    print(text)
    print(f"\nTotal open roles: {sum(1 for j in merged if j.get('open'))}")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("## Upside Radar\n\n" + text + "\n")
    notify_phone(os.environ.get("NTFY_TOPIC", "").strip(), new_jobs)


if __name__ == "__main__":
    main()
