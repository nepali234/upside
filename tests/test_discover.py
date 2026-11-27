"""Tests for discover.py (the Seed Finder), using fake news feeds and fake job boards (no network).

Run:  python3 -m unittest discover tests
"""
import json
import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import discover  # noqa: E402
import scraper  # noqa: E402

CONFIG = json.loads((Path(__file__).resolve().parent.parent / "docs" / "companies.json").read_text())
AREA = re.compile(CONFIG["filters"]["location_include"], re.I)
NOW = datetime(2026, 11, 26, 14, 0, tzinfo=timezone.utc)


def item(title, text, date="2026-11-20T00:00:00Z"):
    return {"title": title, "text": text, "date": date, "url": "https://news.test/" + re.sub(r"\W+", "-", title)[:40]}


def rss(*items):
    body = "".join(
        f"<item><title>{t}</title><link>https://news.test/{i}</link><pubDate>{d}</pubDate>"
        f"<description><![CDATA[<img src='x.jpg'/><p>{x}</p>]]></description></item>"
        for i, (t, x, d) in enumerate(items))
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>Funding</title>{body}</channel></rss>'


class ReadingNewsTests(unittest.TestCase):
    def test_parse_rss(self):
        items = discover.parse_rss(rss(("Seattle startup Aarden raises $8M", "Seattle startup Aarden raised $8 million.",
                                        "Tue, 17 Nov 2026 17:58:19 +0000")))
        self.assertEqual(items[0]["title"], "Seattle startup Aarden raises $8M")
        self.assertEqual(items[0]["date"], "2026-11-17T17:58:19Z")
        self.assertIn("Aarden raised $8 million", items[0]["text"])

    def test_reads_the_name_stage_and_amount(self):
        cases = [
            ("Seattle startup Aarden raises $8M to help landowners", "Seattle startup Aarden raised $8 million in a seed round.",
             "Aarden", "seed", "$8M"),
            ("StepSecurity, led by two Microsoft vets, raises $20M", "StepSecurity, a Seattle-area startup founded by two former Microsoft engineers, raised a $20 million Series A.",
             "StepSecurity", "Series A", "$20M"),
            ("Ex-Marine and Microsoft vets launch Watchtower Labs with $35M", "Watchtower Labs, a Bellevue, Wash.-based defense tech startup, emerged from stealth with $35 million. Shield Capital led the seed round.",
             "Watchtower Labs", "seed", "$35M"),
            ("Apptio co-founders reunite to launch enterprise AI startup Thira with $21M", "The Bellevue company raised $21 million in seed funding.",
             "Thira", "seed", "$21M"),
            ("The code AI forgot: logcat.ai raises $2.55M", "Seattle startup logcat.ai has raised $2.55 million in pre-seed funding.",
             "logcat.ai", "pre-seed", "$2.55M"),
            ("Electric boat maker Zin Boats raises $5M", "The Seattle startup's new division sells motors. It raised a $5 million seed round.",
             "Zin Boats", "seed", "$5M"),
        ]
        for title, text, name, stage, amount in cases:
            lead = discover.lead_from(item(title, text), AREA)
            self.assertEqual((lead["name"], lead["stage"], lead["amount"]), (name, stage, amount), title)

    def test_skips_later_rounds_and_other_cities(self):
        self.assertIsNone(discover.lead_from(item("Helion raises $425M", "Helion, a Seattle-area fusion company, raised a Series F."), AREA))
        self.assertIsNone(discover.lead_from(item("SenseNet lands $43M", "Vancouver, B.C.-based SenseNet announced a $43 million seed round led by Seattle investors."), AREA))
        self.assertIsNone(discover.lead_from(item("Austin startup Foo raises $3M", "Foo, an Austin startup, raised a $3 million seed round."), AREA))
        self.assertIsNone(discover.lead_from(item("Seattle startup Bar opens an office", "Seattle startup Bar opened an office."), AREA))

    def test_keeps_a_fitting_story_even_when_the_name_cant_be_read(self):
        lead = discover.lead_from(item("Exclusive: Former Apple leaders raise $16M for stealthy Seattle startup",
                                       "As AI demand grows, inference matters. The seed round was led by FUSE."), AREA)
        self.assertTrue(lead["unnamed"])
        self.assertEqual(lead["amount"], "$16M")

    def test_never_amazon(self):
        self.assertIsNone(discover.lead_from(item("Seattle startup Zoox raises $5M", "Seattle startup Zoox raised a $5 million seed round."), AREA))


class BoardTests(unittest.TestCase):
    def fake_get(self, boards):
        def get(url):
            if url in boards:
                return boards[url]
            raise OSError("404")
        return get

    def test_slugs(self):
        self.assertEqual(discover.slugs_for("Watchtower Labs")[:3], ["watchtowerlabs", "watchtower-labs", "watchtower"])
        self.assertIn("logcatai", discover.slugs_for("logcat.ai"))

    def test_greenhouse_needs_a_matching_name(self):
        get = self.fake_get({"https://boards-api.greenhouse.io/v1/boards/watchtower": {"name": "watchTowr"}})
        self.assertIsNone(discover.find_board("Watchtower Labs", get))
        get = self.fake_get({"https://boards-api.greenhouse.io/v1/boards/watchtowerlabs": {"name": "Watchtower Labs"}})
        self.assertEqual(discover.find_board("Watchtower Labs", get)["board"], "greenhouse")

    def test_ashby_and_lever_need_the_whole_name_and_open_roles(self):
        get = self.fake_get({"https://api.ashbyhq.com/posting-api/job-board/watchtower": {"jobs": [{"id": 1}]}})
        self.assertIsNone(discover.find_board("Watchtower Labs", get))  # 'watchtower' alone could be anyone
        get = self.fake_get({"https://api.ashbyhq.com/posting-api/job-board/sageox": {"jobs": []}})
        self.assertIsNone(discover.find_board("SageOx", get))  # an empty board proves nothing
        get = self.fake_get({"https://api.ashbyhq.com/posting-api/job-board/sageox": {"jobs": [{"id": 1}]}})
        self.assertEqual(discover.find_board("SageOx", get),
                         {"board": "ashby", "slug": "sageox", "careersUrl": "https://jobs.ashbyhq.com/sageox"})
        get = self.fake_get({"https://api.lever.co/v0/postings/meadow-ai?mode=json&limit=1": [{"id": "x"}]})
        self.assertEqual(discover.find_board("Meadow AI", get)["slug"], "meadow-ai")


class DiscoverTests(unittest.TestCase):
    def config(self, **extra):
        return {**CONFIG, "news": [{"name": "Fake news", "url": "https://news.test/feed/"}],
                "seedFinder": {**CONFIG.get("seedFinder", {}), "backfillPages": 2, **extra}}

    def test_end_to_end(self):
        feed = rss(
            ("Seattle startup Glimmer raises $4M", "Seattle startup Glimmer raised a $4 million seed round.", "Mon, 23 Nov 2026 10:00:00 +0000"),
            ("Seattle startup Aarden raises $8M", "Seattle startup Aarden raised $8 million in seed funding.", "Tue, 17 Nov 2026 10:00:00 +0000"),
            ("Old news: Seattle startup Dusty raises $1M", "Seattle startup Dusty raised a $1 million seed round.", "Mon, 01 Jan 2018 10:00:00 +0000"),
            ("Exclusive: Former Apple leaders raise $16M for stealthy Seattle startup", "Inference is hot. The seed round was led by FUSE.", "Mon, 23 Nov 2026 09:00:00 +0000"),
        )
        pages = {"https://news.test/feed/": feed}
        boards = {"https://api.ashbyhq.com/posting-api/job-board/glimmer": {"jobs": [{"id": 1}]}}
        get = lambda url: boards[url] if url in boards else (_ for _ in ()).throw(OSError("404"))
        out = discover.discover(self.config(), {}, NOW, fetch_text=lambda u: pages[u], get=get, pause=0)
        names = [l["name"] for l in out["leads"]]
        self.assertEqual(names, ["Glimmer"])  # Aarden is on the watchlist; Dusty is too old
        self.assertEqual(out["leads"][0]["board"], "ashby")
        self.assertEqual(len(out["unnamed"]), 1)
        self.assertTrue(out["backfilled"])
        # Watchlist companies still checked by hand get looked up too.
        self.assertTrue(all("checkedAt" in b for b in out["boards"].values()))

        # Next day: one page only, nothing found again is re-checked before recheckDays.
        calls = []
        out2 = discover.discover(self.config(), out, NOW, fetch_text=lambda u: calls.append(u) or pages[u], get=get, pause=0)
        self.assertEqual(calls, ["https://news.test/feed/"])
        self.assertEqual(out2["leads"][0]["firstSeen"], out["leads"][0]["firstSeen"])

    def test_a_broken_feed_is_reported_and_backfill_retried(self):
        def boom(url):
            raise OSError("down")
        out = discover.discover(self.config(maxChecksPerRun=0), {}, NOW, fetch_text=boom, get=lambda u: {}, pause=0)
        self.assertTrue(out["errors"])
        self.assertFalse(out["backfilled"])


class ScraperUsesLeadsTests(unittest.TestCase):
    def test_with_leads(self):
        config = {"filters": {}, "companies": [{"name": "Watchtower Labs", "board": "link", "slug": "x", "careersUrl": "https://w"}]}
        leads = {"boards": {"Watchtower Labs": {"board": "greenhouse", "slug": "watchtowerlabs"}},
                 "leads": [{"name": "Glimmer", "board": "ashby", "slug": "glimmer"},
                           {"name": "NoBoard"},
                           {"name": "watchtower labs", "board": "lever", "slug": "dup"}]}
        out = scraper.with_leads(config, leads)
        self.assertEqual([(c["name"], c["board"], c["slug"]) for c in out["companies"]],
                         [("Watchtower Labs", "greenhouse", "watchtowerlabs"), ("Glimmer", "ashby", "glimmer")])
        self.assertEqual(config["companies"][0]["board"], "link")  # the watchlist itself is untouched

    def test_config_has_news_feeds(self):
        self.assertTrue(CONFIG["news"] and all(f["url"].startswith("https://") for f in CONFIG["news"]))


if __name__ == "__main__":
    unittest.main()
