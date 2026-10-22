# Upside Radar

A personal job radar for early-career software roles in the **Greater Seattle Area**.

Every morning a small Python script checks the job boards of a hand-picked watchlist of companies, keeps the roles that fit, and publishes them to a tracker page. The page hands you a fixed number of applications to make each day (3 by default), favors roles posted in the last few days, and spreads your bets across sectors.

No AI, no servers, no accounts. It runs free on GitHub Actions and GitHub Pages.

**Live page:** https://nepali234.github.io/upside/

---

## What it does

**Every morning (automatic)**
1. GitHub Actions runs `scraper.py` at 13:36 UTC (6:36am Seattle in summer, 5:36am in winter).
2. The script asks each watched company's job board for its open jobs over plain HTTP.
3. It keeps software roles at early-career level in the Greater Seattle Area. Amazon is always excluded.
   It also reads each posting's full description and drops roles that ask for 4+ years, an active security clearance, or a PhD (the **Fit Check**).
4. It merges the results into `docs/jobs.json`: new roles are added, each job's real posting date is saved, and jobs that disappeared are marked closed.
5. It commits the file. GitHub Pages republishes the site a minute later.

**On the page (you)**
- **Today's bets:** your daily quota of roles to apply to. Each set mixes one safe bet (big, stable company) with wild bets (startups), every pick from a different company and sector, freshest roles first. Tap **✓ I applied** or **not for me**.
- **Streak:** days in a row you hit your quota. Use **−** and **+** to change the quota (1–10).
- **Spread:** where your bets have gone by sector, with a warning if more than half land in one.
- **The list:** every open role, newest first. Roles posted in the last 3 days are tagged **just posted**. Mark each one by circling **applied**, **interview** or **skip**, and tap again to clear it.
- **Filters:** status tabs, sector chips, search, and **Posted this week**.
- **Add a role you found yourself**, for anything spotted elsewhere.
- **Back up or move your progress:** export and import your marks as a JSON file.
- **The watchlist:** one card per company, with why it's a bet and a link to its careers page.

---

## Setup

1. Push this folder to a GitHub repo. Pages on a private repo needs a paid plan, so use a public repo on the free plan.
2. **Settings → Actions → General → Workflow permissions → Read and write permissions.** The workflow commits `jobs.json`.
3. **Settings → Pages →** Deploy from a branch → `main`, folder `/docs`.
4. **Actions → Daily job refresh → Run workflow** once. After that it runs every morning.
5. Optional phone alerts: install the free **ntfy** app, subscribe to a hard-to-guess topic, and add it as the repository secret `NTFY_TOPIC`. You get a push only on days with new roles.

GitHub's guides: [Pages publishing source](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site) · [Actions settings](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository) · [Running a workflow by hand](https://docs.github.com/actions/managing-workflow-runs/manually-running-a-workflow)

## Adding a company

1. Open one of its job postings and read the URL:
   - `boards.greenhouse.io/acme/...` or `job-boards.greenhouse.io/acme/...` → board `greenhouse`, slug `acme`
   - `jobs.lever.co/acme/...` → board `lever`, slug `acme`
   - `jobs.ashbyhq.com/acme/...` → board `ashby`, slug `acme`
2. Preview what it would pick up: `python3 scraper.py check greenhouse acme`
3. Add an entry to `docs/companies.json` (the full format is under *Data formats* below).

Prefer companies with real Seattle-area offices, and keep sectors balanced. If one sector passes about a third of the list, add elsewhere.

## Running locally

```bash
python3 -m unittest discover tests     # tests use fake board data, no network
python3 scraper.py                     # real run: fetches boards, rewrites docs/jobs.json
python3 scraper.py check ashby baseten # preview one board against the filters
cd docs && python3 -m http.server      # then open http://localhost:8000
```

Opening `docs/index.html` directly from disk won't load the data. Serve the folder.

---

## For future agents and maintainers

Read this before changing anything.

### Design principles

1. **No AI and no paid services at runtime.** The owner chose this deliberately. Don't add LLM calls, hosted APIs, databases, or anything that needs a key or costs money. The whole system is a cron job, a script, a JSON file and a static page.
2. **Simple over clever.** Standard library Python only, and one self-contained HTML file with no build step and no framework. Keep it that way.
3. **Many small bets.** The page exists to make the owner apply to a few roles every day, spread across sectors, with a mix of safe and high-upside companies. Changes should support that habit, not add dashboards.

### Rules that must not break

- **Amazon and AWS are never shown.** They're blocked by `BLOCKED_COMPANIES` in `scraper.py`. Don't remove this, and don't add Amazon-owned companies to the watchlist.
- **Greater Seattle Area only.** `location_include` in `docs/companies.json` decides this. A multi-city job is kept if any of its cities is in the area. Remote-only and unknown locations are dropped.
- **Early-career level only.** `title_exclude` drops senior, staff, principal, lead, manager, director, head, intern, level III/IV and similar titles. The owner has about a year of full-time industry experience plus an internship. Target "Software Engineer I/II", roles asking 0–3 years, and new-grad or early-career programs.
- **Fit Check: judge a job by what it asks for, not what it's called.** Titles hide level ("Software Engineer - GPU Kernels" can mean 5+ years). `description_exclude` in `companies.json` is matched against the full posting text and drops roles asking for 4+ years of experience, an *active* clearance (eligibility to obtain one is fine), or a required PhD. Descriptions come from Greenhouse (`?content=true`), Lever (`descriptionPlain` plus the requirement `lists`) and Ashby (`descriptionHtml`). They're used only for filtering and never saved to `jobs.json`. Workday gives no description in its search results, so Workday roles skip this check. When a rule looks too strict, `python3 scraper.py check <board> <slug>` lists every role the Fit Check dropped and the phrase that dropped it.
- **The scraper never touches the owner's statuses.** Applied, skipped and interviewing marks live only in the browser's `localStorage`. `jobs.json` is board data only.
- **One broken board never stops the run.** Each fetch is wrapped in try/except. Errors go into `jobs.json` under `errors`, and the page shows "N boards unreachable".
- **Never invent jobs or dates.** Every job comes from a board feed or from the owner's manual entry.

### How the pieces fit

```
.github/workflows/daily.yml   cron 13:36 UTC + manual "Run workflow"
   └─ runs tests, then scraper.py, then commits docs/jobs.json if it changed
scraper.py
   ├─ fetch_greenhouse / fetch_lever / fetch_ashby / fetch_workday   (one per board type)
   ├─ is_match(job, filters)    title include/exclude + location regexes from companies.json
   ├─ refresh(config, existing, fetchers, now)   pure merge logic, easy to test
   ├─ summary_text / notify_phone   optional ntfy push
   └─ check_board(board, slug)   "python3 scraper.py check <board> <slug>"
docs/companies.json   watchlist + filter regexes (edited by hand)
docs/jobs.json        generated each morning; never hand-edit except to repair
docs/index.html       the whole front end: CSS, markup and JS in one file
tests/test_scraper.py unittest; fakes every network call
```

### Data formats

**`docs/companies.json`**
```json
{
  "filters": { "title_include": "regex", "title_exclude": "regex", "description_exclude": "regex", "location_include": "regex" },
  "companies": [{
    "name": "Baseten",                 // display name; also the join key used by jobs.json "company"
    "category": "AI infrastructure",   // sector, used for colors, chips and the diversity rule
    "tier": "wild",                    // "safe" (big, stable) or "wild" (startup); defaults by category
    "hq": "San Francisco, CA",
    "why": "One plain sentence on why it's a bet.",
    "careersUrl": "https://...",       // must be https; shown on the watchlist card
    "linkLabel": "optional link text",
    "board": "greenhouse",             // greenhouse | lever | ashby | workday | link
    "slug": "baseten",
    "workday": { "host": "...", "tenant": "...", "site": "...", "search": "software engineer" }  // workday only
  }]
}
```
Regexes are Python `re` with `re.I`. `"board": "link"` means there's no readable feed (Microsoft, Google, Meta, Helion, Zap, Overland): the company appears as a card for checking by hand and is never fetched.

**`docs/jobs.json`** (written by the scraper)
```json
{
  "updatedAt": "2026-10-22T13:36:00Z",
  "errors": ["NVIDIA: URLError: ..."],
  "jobs": [{
    "id": "gh-stripe-6042172",   // <prefix>-<slug>-<board job id>; prefixes gh, lv, ab, wd
    "company": "Stripe",
    "title": "Backend Engineer, Core Technology",
    "location": "Seattle · US-Remote · Chicago",
    "url": "https://...",
    "postedAt": "2026-10-20T13:00:00Z",   // real posting date from the board; may be missing
    "firstSeen": "...", "lastSeen": "...",
    "open": true,                          // false once it vanishes from the board
    "closedAt": "..."                      // set when closed
  }]
}
```
Merge rules, all in `refresh()`:
- A job is new the first time its `id` is seen. If it disappears and comes back, it reopens without counting as new again.
- `postedAt` keeps the **earliest** date ever seen, because Workday's "Posted 30+ Days Ago" drifts.
- Jobs missing from their company's board are marked `open: false`. Closed jobs are deleted 60 days after `closedAt` (`KEEP_CLOSED_DAYS`).
- Saved jobs that no longer pass the current filters are dropped. Narrowing a filter cleans up on the next run.

Posting-date sources: Greenhouse `first_published`, Lever `createdAt` (epoch ms), Ashby `publishedAt`, Workday `postedOn` text parsed by `workday_posted()`. Workday's search only says "N Locations" for multi-city jobs, so `workday_locations()` fetches the job's detail endpoint to get the real cities.

**Browser storage** (`localStorage["upside-radar-v1"]`, also the export/import file format)
```json
{
  "statuses": { "<job id>": { "status": "applied", "statusAt": "ISO", "appliedAt": "ISO" } },
  "manual":   [{ "id": "manual-...", "company": "...", "title": "...", "location": "...", "url": "https://...", "firstSeen": "ISO" }],
  "target": 3,
  "ui": { "tab": "new" }
}
```
`status` is `new`, `applied`, `interviewing` or `skipped`. A bet counts toward a day's quota and the streak on its `appliedAt` date, and only while the status is still applied or interviewing. Clearing a mark removes `appliedAt`. Import merges by keeping the newer `statusAt` per job. If you rename the storage key, migrate the old one, or the owner loses their history.

### Page logic (`docs/index.html`)

- **Today's picks** (`choosePicks`): the pool is open roles still at `new`, sorted by freshness band (posted ≤3 days, ≤7, ≤21, older or unknown) and then by a hash of the date plus the job id, so picks are stable through the day and change daily. Three passes fill the quota: first a strict pass (a new sector per pick, one safe bet, the rest wild), then one that relaxes the safe/wild split, then one that relaxes sectors. A company is never picked twice in a day.
- **Visibility:** closed postings are hidden unless the owner marked them applied or interviewing (`isVisible`).
- **Sorting:** by `postedAt` newest first. Jobs with no posting date sort after dated ones.
- **`shortLoc`** shortens long city lists to the Seattle-area city plus a count. Its `AREA` regex mirrors `location_include`, so keep the two in sync.
- Sector chips only show sectors that currently have roles.

### Visual design

Minimal, Apple-like layout drawn as if in pencil on paper. Keep this direction unless the owner asks otherwise.
- **Color:** monochrome graphite on near-white paper with faint grain, plus a dark mode (charcoal on dark paper). Colored pencil appears only for sector dots, the green "placed" and "just posted" states, and amber for interviewing. All colors are CSS variables on `:root`, redefined under `prefers-color-scheme: dark`.
- **Type:** the system font (SF Pro on Apple devices) for UI text and headings. **Kalam**, a neat handwritten print, for job titles and buttons. **Caveat**, a looser hand, for small notes and annotations. Both come from Google Fonts with handwriting fallbacks.
- **Pencil effect:** two inline SVG filters, `#rough` and `#rough2` (turbulence plus displacement), wobble the outlines. Frames are pseudo-elements (`.sk::before/::after`) so text is never distorted. Buttons (`.pb`) are hand-drawn outlines that fill with pencil hatching on hover. Status marks (`.mark`) get a pencil circle when chosen.
- The page must work at phone width with no sideways scrolling.

### Common changes

| Want to… | Change |
|---|---|
| Add or remove a company | `docs/companies.json` (check with `scraper.py check` first) |
| Include remote roles again | Add `\|remote` to `location_include`, and to `AREA` in `index.html` |
| Change seniority | `title_exclude` / `title_include`, and the years part of `description_exclude`, then run the tests |
| Support a new board type | Add `fetch_<board>()` returning `make_job(...)` dicts, register it in `FETCHERS`, add a fake-data test |
| Change the run time | The cron in `.github/workflows/daily.yml` (UTC) |
| Change the default daily quota | `target: 3` in `loadStore()` in `index.html` |

Always run `python3 -m unittest discover tests` before committing. Workflow runs execute the tests first and won't publish if they fail.

### Gotchas

- GitHub Pages can take a minute or two to show a new commit. Hard-refresh if the page looks stale.
- The workflow can only push if workflow permissions are set to read and write.
- The daily workflow commits `jobs.json`. Pull before pushing local changes, or the push will be rejected.
- Job boards occasionally change their APIs. A failing board shows up in `errors` and in the run summary under **Actions**, and the other boards keep working.
- If `location_include` changes, `refresh()` drops non-matching saved jobs on the next run. Roles the owner marked applied keep their status in the browser but vanish from the list if their job was dropped.
