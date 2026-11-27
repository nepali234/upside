# Upside Radar

A personal job radar for early-career software roles in the **Greater Seattle Area**.

Every morning a small Python script checks the job boards of a hand-picked watchlist of companies, keeps the roles that fit, and publishes them to a tracker page. The page hands you a fixed number of applications to make each day (3 by default), favors roles posted in the last few days, and spreads your bets across sectors.

No AI, no servers, no accounts. It runs free on GitHub Actions and GitHub Pages.

**Live page:** https://nepali234.github.io/upside/

---

## What it does

**Every morning (automatic)**
1. GitHub Actions runs `discover.py` (the **Seed Finder**, below), then `scraper.py` at 13:36 UTC (6:36am Seattle in summer, 5:36am in winter).
2. The script asks each watched company's job board for its open jobs over plain HTTP.
3. It keeps software roles at early-career level in the Greater Seattle Area. Amazon is always excluded.
   It also casts a **Wider Net**: the community-kept [Simplify New-Grad list](https://github.com/SimplifyJobs/New-Grad-Positions) adds Seattle-area new-grad roles from companies that aren't on the watchlist, and fills in the link-only cards (Microsoft, Google, Blue Origin...). This month's Hacker News **"Ask HN: Who is hiring?"** thread adds Seattle-area roles at small startups that aren't on any list yet, read through the free [HN search API](https://hn.algolia.com/api).
   It also reads each posting's full description and drops roles that ask for 4+ years, an active security clearance, or a PhD (the **Fit Check**).
4. It merges the results into `docs/jobs.json`: new roles are added, each job's real posting date is saved, and jobs that disappeared are marked closed.
5. It commits the file. GitHub Pages republishes the site a minute later.

**On the page (you)**
- **Today's bets:** your daily quota of roles to apply to. The set cycles through three kinds of bet: a **middle** bet (growth-stage company, past the risky years, still has upside), a **wild** bet (startup) and a **safe** bet (big, stable company). 1 a day gets a middle bet, 2 gets middle + wild, 3 gets one of each. Every pick comes from a different company and sector. Freshly seeded startups come first, then the freshest roles. Tap **✓ I applied** or **not for me**.
- **Seed Finder (`discover.py`):** every morning it reads funding news (GeekWire's funding and seed-round feeds, set in `news` in `companies.json`), keeps Seattle-area private companies that just raised any round before going public (pre-seed, seed, Series A, B, C and later), and looks for each one's job board on Greenhouse, Ashby and Lever. Boards it finds are read like any watchlist company, so their roles show up on their own. Results go to `docs/leads.json`. The first run reads about 40 pages of each feed to catch up on older rounds.
- **Recently funded startups:** its own section right under Today's bets, for pre-IPO stock. It lists every new open role at a recently funded private company (it ignores the list filters, so none get missed), each with **copy note**. Below that, **Email them** lists every funded company with no open posting here, newest funding first: no posting doesn't mean no hiring, so email them directly. Each card has the round, the careers page, the funding story (**news ↗**, which usually names the founders), **copy note** (your outreach note, filled in for that company) and **mark reached** to track who you've emailed. Views: not contacted (the default), all, found in news. Funding stories where the company's name couldn't be read are listed at the bottom so you can check them by hand.
- **Streak:** days in a row you hit your quota. Use **−** and **+** to change the quota (1–10).
- **Spread:** where your bets have gone by sector, with a warning if more than half land in one.
- **The list:** every open role, spread out so no company floods it: each company's newest role first, then everyone's second role, and so on, with freshly seeded startups first in each round. Every role shows; nothing is folded away. Roles posted in the last 3 days are tagged **just posted**. Mark each one by circling **applied**, **interview** or **skip**, and tap again to clear it.
- **Filters:** status tabs, sector chips, search, **posted within** (3 days, week, month, any time; any time by default, so every open role shows) and **kind of bet** (safe, middle, wild, new finds, fresh seed). Roles you applied to always stay visible. The tab counts follow the filters.
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

Prefer companies with real Seattle-area offices, and keep sectors balanced. Set `"tier"` to `"middle"` for growth-stage companies (roughly 200–5,000 people, past product-market fit, hiring early-career): they're the sweet spot between big tech and seed startups, so keep plenty of them. A reliable way to find a slug: search the Simplify listings for the company and read the job-board URL. If one sector passes about a third of the list, add elsewhere.

## Running locally

```bash
python3 -m unittest discover tests     # tests use fake board data, no network
python3 scraper.py                     # real run: fetches boards, rewrites docs/jobs.json
python3 scraper.py check ashby baseten # preview one board against the filters
python3 scraper.py check google        # preview Google's Seattle and Kirkland roles
cd docs && python3 -m http.server      # then open http://localhost:8000
```

Opening `docs/index.html` directly from disk won't load the data. Serve the folder.

---

## For future agents and maintainers

Read this before changing anything.

> **Start from an up-to-date local copy. Always.** The owner's working copy lives on their machine (`~/Downloads/upside-radar`), and it often has commits that aren't on GitHub yet, while the daily bot keeps pushing `jobs.json` refreshes to GitHub. Before you change anything:
> 1. Work in that local copy, not a fresh clone or a patch built from GitHub's `main`. Changes built on an old copy collide with the owner's unpushed work.
> 2. Run `git status` (it should be clean) and `git log --oneline origin/main..main` to see any unpushed commits, then `git pull --rebase` to get the bot's latest commits under them. If the rebase conflicts only in `docs/jobs.json`, keep GitHub's version.
> 3. Make your changes on top of that, run `python3 -m unittest discover tests`, and commit. Leave `git push` to the owner unless they ask you to push.

### Design principles

1. **No AI and no paid services at runtime.** The owner chose this deliberately. Don't add LLM calls, hosted APIs, databases, or anything that needs a key or costs money. The whole system is a cron job, a script, a JSON file and a static page.
2. **Simple over clever.** Standard library Python only, and one self-contained HTML file with no build step and no framework. Keep it that way.
3. **Many small bets.** The page exists to make the owner apply to a few roles every day, spread across sectors, with a mix of safe and high-upside companies. Changes should support that habit, not add dashboards.

### Rules that must not break

- **Amazon and AWS are never shown.** They're blocked by `BLOCKED_COMPANIES` in `scraper.py`. Don't remove this, and don't add Amazon-owned companies to the watchlist.
- **Greater Seattle Area only.** `location_include` in `docs/companies.json` decides this. A multi-city job is kept if any of its cities is in the area. Remote-only and unknown locations are dropped.
- **Early-career level only.** `title_exclude` drops senior, staff, principal, lead, manager, director, head, intern, level III/IV and similar titles. The owner has about a year of full-time industry experience plus an internship. Target "Software Engineer I/II", roles asking 0–3 years, and new-grad or early-career programs.
- **Fit Check: judge a job by what it asks for, not what it's called.** Titles hide level ("Software Engineer - GPU Kernels" can mean 5+ years). `description_exclude` in `companies.json` is matched against the full posting text and drops roles asking for 4+ years of experience, an *active* clearance (eligibility to obtain one is fine), or a required PhD. Descriptions come from Greenhouse (`?content=true`), Lever (`descriptionPlain` plus the requirement `lists`) and Ashby (`descriptionHtml`). They're used only for filtering and never saved to `jobs.json`. Workday gives no description in its search results, so Workday roles skip this check. When a rule looks too strict, `python3 scraper.py check <board> <slug>` lists every role the Fit Check dropped and the phrase that dropped it.
- **Wider Net: more sources, same rules.** `feeds` in `companies.json` lists community feeds (today: Simplify New Grad and Hacker News Who's Hiring). Feed roles go through the same title, location and Amazon filters. Companies read directly from their own board are skipped so nothing shows twice; link-only watchlist companies get their roles from the feed (match by name, or add `"aliases"` to the company). Feed roles carry `"source"` and close when they leave the feed; a feed that fails to load closes nothing. Simplify has no descriptions, so the Fit Check can't read it. Hacker News posts are the description, so they do get the Fit Check. An HN post is kept only if its header line (`Company | Role | Location | ...`) names an engineering role and a Seattle-area place; posts that mix senior and junior roles in one title are dropped by the title rule. HN roles link to the post itself and close when next month's thread replaces this one. Companies not on the watchlist show on the page as the sector **Wider net** and the tier **new find**.
- **Fresh seed ranks, it never hides.** A company's `"seed"` (`{"round": "$15M seed", "date": "2026-05"}`, date as `YYYY` or `YYYY-MM`) makes the page put it first in Today's bets and in each round of the list when the round is within 5 years (`SEED_YEARS`); its roles show a **fresh seed** note. Only add a seed you've checked in a funding announcement. Most newly seeded startups have no Greenhouse/Lever/Ashby board yet, so they start as `"board": "link"`; once a board shows up, check it with `scraper.py check` and switch the entry over.
- **No pile-ups.** The list spreads companies out and folds anything past `PER_COMPANY` (2) roles per company behind a button. Nothing is dropped or capped in `jobs.json`.
- **"Backed by" is a badge, never a filter.** `backers` in `companies.json` maps a company name to its top investors, and the page shows "backed by …" next to its roles. Only add backers you've checked in a funding announcement.
- **The scraper never touches the owner's statuses.** Applied, skipped and interviewing marks live only in the browser's `localStorage`. `jobs.json` is board data only.
- **One broken board never stops the run.** Each fetch is wrapped in try/except. Errors go into `jobs.json` under `errors`, and the page shows "N boards unreachable".
- **Never invent jobs or dates.** Every job comes from a board feed or from the owner's manual entry.

- **Seed Finder rules.** A lead is a funding story whose headline and opening announce money raised by a private company: any stage from pre-seed to Series K, or no stage named (`funding`); when several stages appear, the latest is the new round. IPOs, SPACs, acquisitions, mergers and public companies are skipped, because the point is stock that can still grow before an IPO. It must be for a company in the Seattle area (an "X-based" phrase must name an area city), dated within `seedFinder.years`. Watchlist companies are never duplicated as leads; the watchlist entry, checked by hand, wins. A board counts only when it clearly belongs to the company: Greenhouse must report the same company name, and Ashby or Lever only count for the company's whole name as the slug with roles open. Boards not found are looked for again every `recheckDays`, at most `maxChecksPerRun` companies a run. Names the parser gets wrong go in `seedFinder.ignore`. The Seed Finder only ever links to the company's own careers page and the news story: it doesn't collect people's contact details, and the outreach note is sent by hand, one company at a time.

### How the pieces fit

```
.github/workflows/daily.yml   cron 13:36 UTC + manual "Run workflow"
   └─ runs tests, then discover.py, then scraper.py, then commits docs/jobs.json and docs/leads.json
discover.py                   Seed Finder: funding news -> docs/leads.json (leads, their boards, unreadable stories)
   ├─ parse_rss / read_news      RSS 2.0, paged with ?paged=N
   ├─ lead_from / name_of        stage, amount, area and company name from headline + opening
   ├─ find_board                 Greenhouse / Ashby / Lever lookups with proof of ownership
   └─ discover(config, saved)    pure merge logic, easy to test
scraper.py
   ├─ fetch_greenhouse / fetch_lever / fetch_ashby / fetch_workday / fetch_google   (one per board type)
   ├─ fetch_simplify / fetch_hn   (Wider Net feeds)
   ├─ is_match(job, filters)    title include/exclude + location regexes from companies.json
   ├─ refresh(config, existing, fetchers, now)   pure merge logic, easy to test
   ├─ summary_text / notify_phone   optional ntfy push
   └─ check_board(board, slug)   "python3 scraper.py check <board> <slug>"
docs/companies.json   watchlist + filter regexes (edited by hand)
docs/jobs.json        generated each morning; never hand-edit except to repair
docs/index.html       the whole front end: CSS, markup and JS in one file
tests/test_scraper.py unittest; fakes every network call
tests/test_discover.py Seed Finder tests with fake news feeds and fake boards
```

### Data formats

**`docs/companies.json`**
```json
{
  "filters": { "title_include": "regex", "title_exclude": "regex", "description_exclude": "regex", "location_include": "regex" },
  "feeds": [{ "name": "Simplify New Grad", "type": "simplify", "url": "https://raw.githubusercontent.com/..." },
            { "name": "Hacker News Who's Hiring", "type": "hn", "url": "https://hn.algolia.com/api/v1" }],
  "backers": { "K2 Space": "Kleiner Perkins, Lightspeed" },   // badge text per company
  "companies": [{
    "name": "Baseten",                 // display name; also the join key used by jobs.json "company"
    "category": "AI infrastructure",   // sector, used for colors, chips and the diversity rule
    "tier": "middle",                  // "safe" (big, stable), "middle" (growth-stage) or "wild" (startup); defaults by category
    "hq": "San Francisco, CA",
    "why": "One plain sentence on why it's a bet.",
    "careersUrl": "https://...",       // must be https; shown on the watchlist card
    "linkLabel": "optional link text",
    "board": "greenhouse",             // greenhouse | lever | ashby | workday | google | link
    "slug": "baseten",
    "aliases": ["Baseten Labs"],       // optional: other names a feed may use for this company
    "seed": { "round": "$15M seed", "date": "2026-05" },  // optional: recent seed/pre-seed; ranks the company first
    "workday": { "host": "...", "tenant": "...", "site": "...", "search": "software engineer" }  // workday only
  }]
}
```
Regexes are Python `re` with `re.I`. `"board": "google"` reads Google's careers search page (it has no API): it searches each office in `google.locations` at the levels in `google.levels` and picks the job links off the page. No dates or descriptions, so no Fit Check. If the page ever shows no job links, the run reports "Google: … layout may have changed" and closes nothing. Test it with `python3 scraper.py check google`. `"board": "link"` means there's no readable feed (Microsoft, Meta, Zap, Overland, Blue Origin): the company appears as a card for checking by hand and is never fetched.

**`docs/jobs.json`** (written by the scraper)
```json
{
  "updatedAt": "2026-10-22T13:36:00Z",
  "errors": ["NVIDIA: URLError: ..."],
  "jobs": [{
    "id": "gh-stripe-6042172",   // <prefix>-<slug>-<board job id>; prefixes gh, lv, ab, wd, go (Google), sf (Simplify feed), hn (Hacker News)
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

- **Today's picks** (`choosePicks`): the pool is open roles still at `new`, sorted by seed band (`seedRank`: seeded ≤2 years, ≤5 years, other), then by freshness band (posted ≤3 days, ≤7, ≤21, older or unknown) and then by a hash of the date plus the job id, so picks are stable through the day and change daily. Three passes fill the quota: first a strict pass (a new sector per pick, one safe bet, the rest wild), then one that relaxes the safe/wild split, then one that relaxes sectors. A company is never picked twice in a day.
- **Recently funded section** (`renderSeeded`): roles are open, still `new`, at companies where `isSeeded()` is true (funding dated within 5 years, any private stage), ignoring `filtered()`. **Email them** is the same companies minus those with an open role. Its buttons use the same `setStatus` as Today's bets.
- **Visibility:** closed postings are hidden unless the owner marked them applied or interviewing (`isVisible`).
- **Sorting** (`spreadOut`): jobs are ranked within their company by `postedAt` (or `firstSeen`), newest first, then listed round by round: every company's 1st role, then every 2nd, and so on, seeded startups first within a round. With no search typed, roles past `PER_COMPANY` fold behind a **+ N more** button; `ui.open` remembers which companies are unfolded.
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
| Add a funding-news feed | Add `{"name", "url"}` to `news` in `docs/companies.json` (any RSS 2.0 feed) |
| Hide a lead the Seed Finder got wrong | Add its name to `seedFinder.ignore` |
| Add a "backed by" badge | Add the company to `backers` in `docs/companies.json` |
| Mark a startup as freshly seeded | Add `"seed": {"round": "…", "date": "YYYY-MM"}` to its entry |
| Show more or fewer roles per company before folding | `PER_COMPANY` in `index.html` |
| Add another community feed | Write `fetch_<type>()` returning `make_job(...)` dicts with `"company"`, register it in `FEED_FETCHERS`, add it to `feeds` |
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
