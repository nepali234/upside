#!/usr/bin/env python3
"""
Seed Finder: finds Seattle-area private companies that just raised money, and their job boards.

The whole idea in four steps:
  1. Read funding news feeds (RSS, free, no key). Today: GeekWire's funding and seed-round tags.
  2. Keep stories about a Seattle-area company raising a private round (pre-seed, seed, Series A,
     B, C and later: anything before an IPO), and pull out the company's name, the round, the
     amount and the date. IPOs, acquisitions and public companies are skipped: the point is
     stock that can still grow before it goes public.
  3. Look for each company's job board on Greenhouse, Ashby and Lever by trying slugs made from
     its name, and accept a board only when it clearly belongs to that company.
  4. Save everything to docs/leads.json. scraper.py then reads those boards every morning like
     any watchlist company, and the page lists every lead in its Seeded startups section.

It also looks for boards for watchlist companies that are still "link" (checked by hand), so a
seeded startup's roles start flowing in as soon as it opens a board.

Standard library only. Run locally with:  python3 discover.py
"""

import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from scraper import BLOCKED_COMPANIES, DOCS, COMPANIES_FILE, http_json, http_text, load_json, norm_name, plain_text

LEADS_FILE = DOCS / "leads.json"
ISO = "%Y-%m-%dT%H:%M:%SZ"
DEFAULTS = {"years": 5, "backfillPages": 40, "recheckDays": 7, "maxChecksPerRun": 80}


# ---------------------------------------------------------------------------
# 1. Reading the news
# ---------------------------------------------------------------------------

CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"


def parse_rss(xml_text):
    """RSS 2.0 -> [{"title", "url", "date", "text"}]. "text" is the story's opening, as plain text."""
    items = []
    for item in ET.fromstring(xml_text).iter("item"):
        title = plain_text(item.findtext("title") or "")
        body = (item.findtext("description") or "") + " " + (item.findtext(CONTENT) or "")
        try:
            date = parsedate_to_datetime(item.findtext("pubDate") or "").astimezone(timezone.utc).strftime(ISO)
        except (TypeError, ValueError):
            date = None
        items.append({"title": title, "url": (item.findtext("link") or "").strip(),
                      "date": date, "text": plain_text(body)[:2500]})
    return items


def read_news(feed, pages, fetch=http_text, pause=1.0):
    """One news feed, newest page first. WordPress feeds page with ?paged=2, 3, ..."""
    items = []
    for page in range(1, pages + 1):
        url = feed["url"] if page == 1 else f"{feed['url']}{'&' if '?' in feed['url'] else '?'}paged={page}"
        try:
            got = parse_rss(fetch(url))
        except Exception:
            if page == 1:
                raise
            break  # past the last page
        if not got:
            break
        items += got
        if page < pages:
            time.sleep(pause)
    return items


# ---------------------------------------------------------------------------
# 2. Is it a Seattle-area early round, and who raised it?
# ---------------------------------------------------------------------------

# Not a private round: going public, being bought, or already public.
NOT_PRIVATE = re.compile(r"\bipo\b|initial public offering|\bspac\b|goes public|going public|\bacquir|\bbuys\b|"
                         r"\bmerg(?:e|er|es|ing)\b|\bnasdaq\b|\bnyse\b|publicly traded|\blayoffs?\b", re.I)
SERIES = re.compile(r"\bseries\s+([a-k])\b", re.I)
RAISED = re.compile(r"\b(?:rais\w*|lands?|landed|secur\w*|clos\w*|nabs?|reels? in|funding|financing|round|backed|invest\w*)\b", re.I)
PRE_SEED = re.compile(r"\bpre-?\s?seed\b", re.I)
SEED = re.compile(r"\bseed\b", re.I)
AMOUNT = re.compile(r"\$\s?(\d+(?:\.\d+)?)\s?(million|billion|thousand|[MBK])\b", re.I)
BASED = re.compile(r"([A-Z][\w.' ]{1,40}?(?:,\s*[A-Z][\w.]+)?)-based\b")


def stage_of(text):
    """The round being announced: 'pre-seed', 'seed', 'Series A' ... 'Series K', 'funding' when the
    story names no stage, or None when it isn't a private round. Reads only the headline and opening,
    where the round being announced is named; with several stages there, the latest is the new one."""
    if NOT_PRIVATE.search(text) or not AMOUNT.search(text) or not RAISED.search(text):
        return None
    series = sorted({m.upper() for m in SERIES.findall(text)})
    if series:
        return f"Series {series[-1]}"
    if PRE_SEED.search(text):
        return "pre-seed"
    if SEED.search(text):
        return "seed"
    return "funding"


def amount_of(text):
    m = AMOUNT.search(text)
    if not m:
        return None
    unit = m.group(2).lower()
    unit = {"million": "M", "m": "M", "billion": "B", "b": "B", "thousand": "K", "k": "K"}[unit]
    return f"${m.group(1)}{unit}"


def in_area(opening, area):
    """The company is in the area: an 'X-based' phrase names an area city, or, with no such phrase,
    the opening mentions one. 'Vancouver, B.C.-based SenseNet ... with Seattle investors' is out."""
    based = BASED.search(opening)
    if based:
        return bool(area.search(based.group(1)))
    return bool(area.search(opening))


# A company name: one to four words, each capitalized, camelCase or like "logcat.ai".
WORD = r"(?:[A-Z0-9][A-Za-z0-9.&'’+-]*|[a-z][a-z0-9]*\.(?:ai|io|dev|co)|[a-z]+[A-Z][A-Za-z0-9]*)"
NAME = rf"{WORD}(?:\s+{WORD}){{0,3}}"
VERB = (r"(?:has\s+|have\s+)?(?:raised|raises|raise|lands|landed|announced|announces|secured|secures|closed|closes|"
        r"nabs|reels in|emerged|emerges|is emerging|launched|launches|debuts|unveiled|unveils)\b")
NAME_RULES = [
    re.compile(rf"^(?:exclusive:\s*)?(?P<n>{NAME}),\s+an?\s+.{{0,90}}?\b(?:startup|company|spinout|spin-out)\b"),
    re.compile(rf"-based\s+(?:[a-z][\w-]*\s+){{0,3}}?(?P<n>{NAME})\s+{VERB}"),
    re.compile(rf"\b(?:startup|company|maker|developer|spinout|spin-out|provider|platform)\s+(?P<n>{NAME})\s+(?:{VERB}|with\s+\$)"),
    re.compile(rf"^(?:exclusive:\s*)?(?P<n>{NAME})\s+{VERB}"),
    re.compile(rf"\b(?:launch|launches|unveil|unveils|debut|debuts)\s+(?:[a-z][\w-]*\s+){{0,4}}(?P<n>{NAME})\s+with\s+\$"),
]
NOT_NAMES = {"seattle", "bellevue", "redmond", "kirkland", "washington", "wash", "the", "a", "an", "former", "exclusive",
             "new", "microsoft", "amazon", "google", "apple", "meta", "startup", "this", "that", "its", "ex", "two",
             "three", "former microsoft", "former amazon", "former apple", "seattle startup", "pacific northwest",
             "venture", "investors", "geekwire", "madrona", "pioneer square labs", "psl", "ai2", "ai2 incubator"}


def name_of(item):
    """The company's name, from the story's opening sentence first and then the headline. None if unsure."""
    first = re.split(r"(?<=[a-z0-9)])\.\s", item["text"], maxsplit=1)[0]
    for text in (first, item["title"]):
        for rule in NAME_RULES:
            m = rule.search(text)
            if not m:
                continue
            name = re.sub(r"[’']s$|,?\s+(?:Inc|LLC|Corp)\.?$", "", m.group("n")).strip(" .,'’")
            key = norm_name(name)
            if key and key not in NOT_NAMES and key.split()[0] not in {"seattle", "former", "exclusive", "ex"} and len(name) <= 40:
                return name
    return None


def lead_from(item, area):
    """A news item -> a lead dict, {"unnamed": ...} when it fits but the name can't be read, or None."""
    opening = f"{item['title']}. {item['text'][:700]}"
    stage = stage_of(opening)
    if not stage or not in_area(opening, area):
        return None
    name = name_of(item)
    base = {"stage": stage, "amount": amount_of(opening), "date": item["date"],
            "sourceTitle": item["title"], "sourceUrl": item["url"]}
    if not name:
        return {"unnamed": True, **base}
    if BLOCKED_COMPANIES.search(name):
        return None
    return {"name": name, **base}


# ---------------------------------------------------------------------------
# 3. Finding a company's job board
# ---------------------------------------------------------------------------

def slugs_for(name):
    """'Watchtower Labs' -> ['watchtowerlabs', 'watchtower-labs', 'watchtower']."""
    words = re.findall(r"[a-z0-9]+", name.lower())
    core = [w for w in words if w not in {"inc", "labs", "lab", "ai", "hq", "io", "technologies", "technology", "co"}]
    out = ["".join(words), "-".join(words), "".join(core), "-".join(core), "".join(core) + "ai"]
    return [s for s in dict.fromkeys(out) if len(s) >= 3]


def find_board(name, get=http_json):
    """Look for a public job board. Greenhouse names the board's company, so a matching name is proof.
    Ashby and Lever don't, so they count only for the company's whole name as the slug, with roles open."""
    whole = {"".join(re.findall(r"[a-z0-9]+", name.lower())), "-".join(re.findall(r"[a-z0-9]+", name.lower()))}
    key = norm_name(name).replace(" ", "")
    for slug in slugs_for(name):
        try:
            info = get(f"https://boards-api.greenhouse.io/v1/boards/{slug}")
            if norm_name(info.get("name")).replace(" ", "") == key:
                return {"board": "greenhouse", "slug": slug, "careersUrl": f"https://boards.greenhouse.io/{slug}"}
        except Exception:
            pass
        if slug not in whole:
            continue
        try:
            if get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}").get("jobs"):
                return {"board": "ashby", "slug": slug, "careersUrl": f"https://jobs.ashbyhq.com/{slug}"}
        except Exception:
            pass
        try:
            if get(f"https://api.lever.co/v0/postings/{slug}?mode=json&limit=1"):
                return {"board": "lever", "slug": slug, "careersUrl": f"https://jobs.lever.co/{slug}"}
        except Exception:
            pass
    return None


def due(record, now, recheck_days):
    """Look again for a board when we never looked, or when the last look found none and is old."""
    if record.get("board"):
        return False
    checked = record.get("checkedAt")
    if not checked:
        return True
    return datetime.strptime(checked, ISO).replace(tzinfo=timezone.utc) < now - timedelta(days=recheck_days)


# ---------------------------------------------------------------------------
# 4. Putting it together
# ---------------------------------------------------------------------------

def discover(config, saved, now=None, fetch_text=http_text, get=None, pause=1.0):
    """Pure-ish core: returns the new leads.json content. Easy to test with fakes."""
    get = get or (lambda url: http_json(url, timeout=10))  # board lookups: short timeouts
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime(ISO)
    opts = {**DEFAULTS, **config.get("seedFinder", {})}
    area = re.compile(config["filters"]["location_include"], re.I)
    cutoff = (now - timedelta(days=365 * opts["years"])).strftime(ISO)
    ignore = {norm_name(n) for n in config.get("seedFinder", {}).get("ignore", [])}
    watch = {norm_name(c["name"]): c for c in config["companies"]}
    for c in config["companies"]:
        for a in c.get("aliases", []):
            watch[norm_name(a)] = c

    leads = {norm_name(l["name"]): l for l in saved.get("leads", [])}
    unnamed = {u["sourceUrl"]: u for u in saved.get("unnamed", [])}
    errors = []
    pages = 1 if saved.get("backfilled") else opts["backfillPages"]
    for feed in config.get("news", []):
        try:
            items = read_news(feed, pages, fetch_text, pause)
        except Exception as e:  # a broken feed never stops the run
            errors.append(f"{feed['name']}: {type(e).__name__}: {e}")
            continue
        for item in items:
            if not item["date"] or item["date"] < cutoff:
                continue
            lead = lead_from(item, area)
            if not lead:
                continue
            if lead.get("unnamed"):
                lead.pop("unnamed")
                unnamed.setdefault(lead["sourceUrl"], lead)
                continue
            key = norm_name(lead["name"])
            if key in ignore or key in watch:
                continue  # the watchlist entry, checked by hand, wins
            old = leads.get(key)
            if not old:
                leads[key] = {**lead, "firstSeen": stamp}
            elif (lead["date"] or "") > (old.get("date") or ""):
                old.update({k: v for k, v in lead.items() if v})  # a newer round: keep its details

    # Boards: leads, plus watchlist companies still checked by hand.
    boards = dict(saved.get("boards", {}))
    to_check = [l for l in leads.values() if due(l, now, opts["recheckDays"])]
    to_check += [{"name": c["name"], **boards.get(c["name"], {})} for c in config["companies"]
                 if c.get("board") == "link" and c.get("seed") and due(boards.get(c["name"], {}), now, opts["recheckDays"])]
    to_check.sort(key=lambda r: r.get("checkedAt") or "")  # never-checked first
    to_check = to_check[:opts["maxChecksPerRun"]]
    with ThreadPoolExecutor(max_workers=8) as pool:
        found = list(pool.map(lambda r: find_board(r["name"], get), to_check))
    for record, hit in zip(to_check, found):
        update = {**(hit or {}), "checkedAt": stamp}
        key = norm_name(record["name"])
        if key in leads:
            leads[key].update(update)
        else:
            boards[record["name"]] = {**boards.get(record["name"], {}), **update}

    keep = lambda r: (r.get("date") or "") >= cutoff
    return {
        "updatedAt": stamp,
        "backfilled": saved.get("backfilled", False) or not errors,
        "errors": errors,
        "leads": sorted((l for l in leads.values() if keep(l)), key=lambda l: l.get("date") or "", reverse=True),
        "unnamed": sorted((u for u in unnamed.values() if keep(u)), key=lambda u: u.get("date") or "", reverse=True)[:60],
        "boards": boards,
    }


def main():
    config = load_json(COMPANIES_FILE, None)
    if not config:
        sys.exit(f"Missing or invalid {COMPANIES_FILE}")
    result = discover(config, load_json(LEADS_FILE, {}))
    LEADS_FILE.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    with_board = [l for l in result["leads"] if l.get("board")]
    print(f"{len(result['leads'])} seeded startups found, {len(with_board)} with a job board the radar now reads.")
    for l in with_board:
        print(f"  - {l['name']}: {l['board']}/{l['slug']}")
    upgraded = [n for n, b in result["boards"].items() if b.get("board")]
    if upgraded:
        print("Watchlist companies with a board found: " + ", ".join(upgraded))
    if result["unnamed"]:
        print(f"{len(result['unnamed'])} funding stories fit but the name couldn't be read (listed on the page).")
    for e in result["errors"]:
        print(f"! {e}")


if __name__ == "__main__":
    main()
