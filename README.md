# Upside Radar

A personal job radar. Every morning a small Python script checks the job boards of the companies you care about, keeps the software roles that fit your level, and publishes them to a tracker page. The page gives you a fixed number of applications to make each day, spread across different sectors.

No AI and no servers. It runs for free on GitHub.

## How it works

```
GitHub Actions (every morning)
   └─ scraper.py ── asks each job board for open jobs (plain HTTP)
        └─ keeps: software roles, your level, US or remote
        └─ writes docs/jobs.json (remembers first-seen dates, marks closed jobs)
GitHub Pages
   └─ docs/index.html ── reads jobs.json, shows today's bets
        └─ your Applied / Skipped marks are saved in your browser
```

## Files

| File | What it is |
|---|---|
| `scraper.py` | Fetches Greenhouse, Lever, Ashby and Workday boards, filters, merges. |
| `docs/companies.json` | Your watchlist and filters. Edit this to add companies. |
| `docs/jobs.json` | The job list. The script rewrites it every morning. |
| `docs/index.html` | The tracker page. |
| `.github/workflows/daily.yml` | Runs the script every morning and commits the results. |
| `tests/test_scraper.py` | Tests with fake board data. Run: `python3 -m unittest discover tests` |

## Setup (about 10 minutes)

1. **Create a repo** on GitHub, for example `upside-radar`. Make it **private** if you don't want anyone to see your watchlist.
   GitHub Pages on a private repo needs a paid plan; with a free plan, use a public repo.
2. **Upload these files**, keeping the folder structure, including the hidden `.github` folder:
   ```bash
   cd upside-radar
   git init && git add . && git commit -m "Upside Radar"
   git branch -M main
   git remote add origin https://github.com/<you>/upside-radar.git
   git push -u origin main
   ```
3. **Let the workflow save results:** Settings → Actions → General → Workflow permissions → **Read and write permissions** → Save.
4. **Turn on the page:** Settings → Pages → Source: **Deploy from a branch** → Branch `main`, folder **`/docs`** → Save.
   Your page will be at `https://<you>.github.io/upside-radar/`.
5. **Run it once now:** Actions → *Daily job refresh* → **Run workflow**. After that it runs every morning on its own.
6. **Bring over your progress (optional):** on the page, open *Back up or move your progress* → *Import progress*, and pick `upside-radar-progress.json`.

### Phone alerts (optional)

Install the free **ntfy** app and subscribe to a hard-to-guess topic name (for example `sayuj-radar-8f3k2q`). In the repo: Settings → Secrets and variables → Actions → **New repository secret**, name `NTFY_TOPIC`, value your topic name. You'll get a push only on days with new roles.

## Growing the watchlist

This replaces a "scout": when you hear about a company (funding news, a friend, LinkedIn), check it in 30 seconds.

1. Open one of its job postings and look at the URL:
   - `boards.greenhouse.io/acme/...` or `job-boards.greenhouse.io/acme/...` → board `greenhouse`, slug `acme`
   - `jobs.lever.co/acme/...` → board `lever`, slug `acme`
   - `jobs.ashbyhq.com/acme/...` → board `ashby`, slug `acme`
2. See what it would pick up:
   ```bash
   python3 scraper.py check greenhouse acme
   ```
3. If it looks good, add an entry to `docs/companies.json`:
   ```json
   { "name": "Acme", "category": "Robotics", "tier": "wild", "hq": "Seattle, WA",
     "why": "One sentence on why it's a bet.",
     "careersUrl": "https://job-boards.greenhouse.io/acme", "board": "greenhouse", "slug": "acme" }
   ```
   - `tier`: `"safe"` for big, stable companies; `"wild"` for startups. Each day's picks mix one safe with the rest wild.
   - `category`: any name works. Sectors with a color already: AI infrastructure, Defense, Energy, Developer tools, Fintech, Robotics, Space, Big tech.
   - Companies without a supported board: use `"board": "link"`. They show as a card with a link, and you check them by hand.

Keep it spread out. If one sector grows past about a third of the list, add somewhere else.

## Recently posted roles come first

Applying in the first few days matters, so the script saves each job's real posting date from the board (Greenhouse `first_published`, Lever `createdAt`, Ashby `publishedAt`, Workday "Posted N days ago").

- The list is sorted newest first. Roles posted in the last 3 days get a green **just posted** tag.
- Today's bets pick from the freshest roles first (last 3 days, then this week, then older), while still mixing sectors and one safe bet.
- **Posted this week** narrows the list to the last 7 days.

## Changing the filters

The three regexes at the top of `docs/companies.json` decide what counts:

- `title_include`: the title must match (software, backend, SDE, ...).
- `title_exclude`: skip if it matches (senior, staff, manager, intern, ...).
- `location_include`: Greater Seattle Area cities (Seattle, Bellevue, Redmond, Kirkland, Bothell, Everett, Renton, Tacoma, ...). A job listing several cities is kept if any of them is in the area. Remote-only roles are skipped; add `|remote` to include them.

Change them, then run `python3 -m unittest discover tests` to make sure nothing broke.

## Notes

- Amazon and AWS are blocked in the code and can never be added.
- Microsoft, Google, Meta, Helion, Zap Energy and Overland AI don't publish a job feed the script can read. They appear as link cards, so check those by hand once a week.
- NVIDIA uses Workday's public search endpoint. If it ever stops working, the page shows "boards unreachable" at the top and everything else keeps running.
- Closed postings are hidden. Ones you marked applied or interviewing stay in those tabs, so your history and streak are kept.
- Mark a role by circling **applied**, **interview** or **skip**; tap the circled one again to clear it.
- Your statuses live in your browser. Use Export/Import to back them up or move between phone and laptop.
- Run the page locally with `cd docs && python3 -m http.server`, then open http://localhost:8000. Opening the file directly won't load the data.
