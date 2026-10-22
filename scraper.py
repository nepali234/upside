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
BLOCKED_COMPANIES = re.compile(r"\bamazon\b|\baws\b", re.I)  # never, ever
KEEP_CLOSED_DAYS = 60


# ---------------------------------------------------------------------------
# 1. Fetching. Every fetcher returns a list of
#    {"id", "title", "location", "url"} dicts.
# ---------------------------------------------------------------------------

def http_json(url, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = dict(HEADERS)
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def make_job(prefix, slug, job_id, title, location, url):
    return {
        "id": f"{prefix}-{slug}-{job_id}",
        "title": (title or "").strip(),
        "location": (location or "").strip(),
        "url": url or "",
    }


def fetch_greenhouse(company):
    slug = company["slug"]
    data = http_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
    return [
        make_job("gh", slug, j["id"], j.get("title"), (j.get("location") or {}).get("name"), j.get("absolute_url"))
        for j in data.get("jobs", [])
    ]


def fetch_lever(company):
    slug = company["slug"]
    data = http_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    jobs = []
    for j in data:
        cats = j.get("categories") or {}
        locations = cats.get("allLocations") or [cats.get("location") or ""]
        jobs.append(make_job("lv", slug, j["id"], j.get("text"),
                             " · ".join(l for l in locations if l), j.get("hostedUrl")))
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
        jobs.append(make_job("ab", slug, j["id"], j.get("title"), " · ".join(unique), j.get("jobUrl")))
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
            jobs.append(make_job("wd", company["slug"], job_id, p.get("title"),
                                 p.get("locationsText"), f"{base}/en-US/{w['site']}{path}"))
        if len(postings) < 20:
            break
    return jobs


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

def is_match(job, filters):
    title, location = job["title"], job["location"]
    if not re.search(filters["title_include"], title, re.I):
        return False
    if re.search(filters["title_exclude"], title, re.I):
        return False
    # Location: keep US / remote. Keep "3 Locations"-style text (Workday) and blanks too.
    if location and not re.search(filters["location_include"], location, re.I) \
            and not re.match(r"^\d+ Locations?$", location, re.I):
        return False
    return True


# ---------------------------------------------------------------------------
# 3. Merging with what we already know
# ---------------------------------------------------------------------------

def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def refresh(config, existing_jobs, fetchers=FETCHERS, now=None):
    """Pure-ish core: returns (merged_jobs, new_jobs, errors). Easy to test."""
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    filters = config["filters"]
    by_id = {j["id"]: dict(j) for j in existing_jobs}
    new_jobs, errors = [], []

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

        seen_here = set()
        for job in fetched:
            if not job["url"].startswith("https://") or not is_match(job, filters):
                continue
            seen_here.add(job["id"])
            if job["id"] in by_id:
                old = by_id[job["id"]]
                old.update(title=job["title"], location=job["location"], url=job["url"],
                           lastSeen=stamp, open=True)
                old.pop("closedAt", None)
            else:
                record = {**job, "company": name, "firstSeen": stamp, "lastSeen": stamp, "open": True}
                by_id[job["id"]] = record
                new_jobs.append(record)

        # Jobs from this company that vanished from its board are closed.
        for record in by_id.values():
            if record.get("company") == name and record.get("open") and record["id"] not in seen_here:
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
