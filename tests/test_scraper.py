"""Tests for the scraper, using fake board responses (no network needed).

Run:  python3 -m unittest discover tests
"""
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scraper  # noqa: E402

CONFIG = json.loads((Path(__file__).resolve().parent.parent / "docs" / "companies.json").read_text())
FILTERS = CONFIG["filters"]


def j(title, location="Seattle, WA", jid="1"):
    return {"id": f"gh-x-{jid}", "title": title, "location": location, "url": f"https://x.test/{jid}"}


class FilterTests(unittest.TestCase):
    def keep(self, title, location="Seattle, WA"):
        return scraper.is_match(j(title, location), FILTERS)

    def test_keeps_right_level_software_roles(self):
        for t in ["Software Engineer", "Software Engineer II", "Backend Engineer, Core Technology",
                  "Member of Technical Staff - Systems", "2027 Early Career Software Engineer",
                  "Software Development Engineer - New Graduate", "Forward Deployed Engineer",
                  "Site Reliability Engineer", "Embedded Software Engineer, Validation", "Autonomy Zip Perception SWE"]:
            self.assertTrue(self.keep(t), t)

    def test_drops_senior_and_non_software(self):
        for t in ["Senior Software Engineer", "Staff Software Engineer", "Sr. Backend Engineer",
                  "Engineering Manager", "Tech Lead, Platform", "Software Engineer Intern",
                  "Principal Engineer", "Software Engineer III", "Accounting Manager", "Fabricator",
                  "Propulsion Technician I", "Solutions Architect"]:
            self.assertFalse(self.keep(t), t)

    def test_locations(self):
        for loc in ["Seattle, WA", "Remote (US)", "US-Remote, Chicago", "Costa Mesa, California, United States",
                    "San Francisco · Toronto", "Austin, TX", "3 Locations", "", "SEA, SF, NY, Toronto"]:
            self.assertTrue(self.keep("Software Engineer", loc), loc)
        for loc in ["London, UK", "Amsterdam", "Stockholm", "Singapore", "Kigali, Rwanda", "Toronto, Canada"]:
            self.assertFalse(self.keep("Software Engineer", loc), loc)


class FetcherTests(unittest.TestCase):
    def test_greenhouse(self):
        fake = {"jobs": [{"id": 5, "title": "Software Engineer", "location": {"name": "Seattle, WA"},
                          "absolute_url": "https://boards.greenhouse.io/x/jobs/5"}]}
        with mock.patch.object(scraper, "http_json", return_value=fake):
            out = scraper.fetch_greenhouse({"slug": "x"})
        self.assertEqual(out, [{"id": "gh-x-5", "title": "Software Engineer", "location": "Seattle, WA",
                                "url": "https://boards.greenhouse.io/x/jobs/5"}])

    def test_lever(self):
        fake = [{"id": "abc", "text": "Software Engineer", "hostedUrl": "https://jobs.lever.co/x/abc",
                 "categories": {"location": "San Diego", "allLocations": ["San Diego", "Boston"]}}]
        with mock.patch.object(scraper, "http_json", return_value=fake):
            out = scraper.fetch_lever({"slug": "x"})
        self.assertEqual(out[0]["location"], "San Diego · Boston")
        self.assertEqual(out[0]["id"], "lv-x-abc")

    def test_ashby_skips_unlisted_and_merges_locations(self):
        fake = {"jobs": [
            {"id": "a1", "title": "MTS", "location": "New York", "isRemote": True,
             "secondaryLocations": [{"location": "San Francisco"}], "jobUrl": "https://jobs.ashbyhq.com/x/a1"},
            {"id": "a2", "title": "Hidden", "isListed": False, "jobUrl": "https://jobs.ashbyhq.com/x/a2"}]}
        with mock.patch.object(scraper, "http_json", return_value=fake):
            out = scraper.fetch_ashby({"slug": "x"})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["location"], "New York · San Francisco · Remote")

    def test_workday_pages_and_builds_urls(self):
        page = {"jobPostings": [{"title": "Software Engineer", "locationsText": "US, CA, Santa Clara",
                                 "externalPath": "/job/US-CA-Santa-Clara/Software-Engineer_JR123"}]}
        with mock.patch.object(scraper, "http_json", return_value=page) as m:
            out = scraper.fetch_workday({"slug": "nvidia", "workday": {
                "host": "nvidia.wd5.myworkdayjobs.com", "tenant": "nvidia", "site": "Ext"}})
        self.assertEqual(m.call_count, 1)  # fewer than 20 results -> no second page
        self.assertEqual(out[0]["id"], "wd-nvidia-JR123")
        self.assertEqual(out[0]["url"], "https://nvidia.wd5.myworkdayjobs.com/en-US/Ext/job/US-CA-Santa-Clara/Software-Engineer_JR123")


class RefreshTests(unittest.TestCase):
    CONF = {"filters": FILTERS, "companies": [
        {"name": "Acme", "board": "fake", "slug": "acme"},
        {"name": "Broken", "board": "boom", "slug": "b"},
        {"name": "Amazon", "board": "fake", "slug": "amzn"},
        {"name": "LinkOnly", "board": "link", "slug": "l"}]}

    def run_refresh(self, board_jobs, existing, now):
        def boom(c):
            raise TimeoutError("timed out")
        return scraper.refresh(self.CONF, existing, {"fake": lambda c: board_jobs, "boom": boom}, now=now)

    def test_new_seen_closed_and_errors(self):
        t1 = datetime(2026, 10, 22, 13, 0, tzinfo=timezone.utc)
        day1 = [j("Software Engineer", jid="1"), j("Senior Software Engineer", jid="2")]
        merged, new, errors = self.run_refresh(day1, [], t1)
        self.assertEqual([r["id"] for r in new], ["gh-x-1"])          # senior filtered out
        self.assertEqual(merged[0]["company"], "Acme")                 # Amazon never added
        self.assertEqual(len(errors), 1)                               # broken board reported, others continue
        self.assertIn("Broken", errors[0])

        t2 = t1 + timedelta(days=1)
        day2 = [j("Backend Engineer", jid="3")]                        # job 1 disappeared
        merged, new, _ = self.run_refresh(day2, merged, t2)
        self.assertEqual([r["id"] for r in new], ["gh-x-3"])
        old = next(r for r in merged if r["id"] == "gh-x-1")
        self.assertFalse(old["open"])
        self.assertEqual(old["firstSeen"], "2026-10-22T13:00:00Z")    # history kept

        t3 = t2 + timedelta(days=1)
        merged, new, _ = self.run_refresh([j("Software Engineer", jid="1"), j("Backend Engineer", jid="3")], merged, t3)
        self.assertEqual(new, [])                                      # reopened job isn't "new" again
        self.assertTrue(next(r for r in merged if r["id"] == "gh-x-1")["open"])

        t4 = t3 + timedelta(days=61)
        merged, _, _ = self.run_refresh([], merged, t4)                # both close now...
        merged, _, _ = self.run_refresh([], merged, t4 + timedelta(days=61))
        self.assertEqual(merged, [])                                   # ...and are pruned after 60 days


if __name__ == "__main__":
    unittest.main()
