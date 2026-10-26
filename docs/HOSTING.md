# Hosting the website for free (GitHub Pages)

This puts the same dashboard (Levels, Bias, News with the Trump feed) on a real web address such as
`https://yourname.github.io/gex-pro/`. You can open it from any device, and your PC doesn't need to be on.

**How it works:** GitHub runs a small job on its own computers. While futures trade (Sunday 6 pm ET to Friday
5 pm ET) each run starts the next one when it finishes: about every 3 minutes in cash hours and every 6 minutes
overnight. When futures are closed it runs hourly. The job:
1. Fetches fresh Cboe options data, the ForexFactory calendar and Truth Social posts.
2. Runs the same calculations as START.bat.
3. Publishes the result as plain web pages.

It costs nothing and does not rely on Claude or on your terminal. The job is in
`.github/workflows/website.yml`; the build command is `python -m gexpro build-site`.

## One-time setup (about 10 minutes, all in the browser)

1. **Create a free GitHub account** at github.com, if you don't have one.
2. **Make a repository.** Click **+** (top right), then **New repository**.
   - Name: `gex-pro` (any name works, and it becomes part of the web address).
   - Visibility: **Public**. Free GitHub Pages needs a public repository.
   - Leave "Add a README" unticked, then click **Create repository**.
3. **Upload the project.** On the new repository page, click **uploading an existing file**.
   - Open your `Options Indicator` folder in File Explorer.
   - Select everything inside it (Ctrl+A), including the `.github` folder, and drag it into the browser.
   - **Do not upload a file called `.env`**, if you have one. (`.env.example` is fine; it has no secrets.)
   - Click **Commit changes**.
4. **Turn on Pages.** Go to **Settings > Pages**, then under "Build and deployment" set **Source** to
   **GitHub Actions**.
5. **First run.** Go to the **Actions** tab. If it asks, click the green button to enable workflows. Then:
   - Click **Website** on the left, then **Run workflow > Run workflow**.
   - After 1–2 minutes the run shows a green tick.
   - Your site is at `https://<your-username>.github.io/gex-pro/`. The link also appears in the run's
     "deploy" box, and under Settings > Pages.

**If the `.github` folder didn't upload** (some browsers skip folders that start with a dot):
1. Click **Add file > Create new file**.
2. Type the name `.github/workflows/website.yml`, including the slashes.
3. Paste in the contents of that file from your folder, then click **Commit changes**.

## Updating the site after changes on your PC

Upload the changed files again the same way (**Add file > Upload files**). Each upload rebuilds the site.

## Differences from the local version (START.bat)

| | Local (START.bat) | Hosted (GitHub Pages) |
|---|---|---|
| Needs your PC on | Yes | No |
| Options data | Cboe, 15-min delayed | Cboe, 15-min delayed |
| How often it updates | Every minute or so in market hours | About every 3 min in cash hours, 6 min overnight |
| Windows notifications | Yes | No: check the "Next paste" time on the site |
| Who can open it | Only you (127.0.0.1) | Anyone who has the link |

- **Public:** the web address isn't listed anywhere, but anyone who has it can open the page. The page holds
  only public market data, with no account details.
- **Truth Social** may block GitHub's servers. If it does, the feed uses the trumpstruth.org archive
  instead, and the footer under the feed names the source.
- **60-day pause:** GitHub pauses scheduled jobs in a repository with no changes for 60 days, and emails
  you first. Click **Enable workflow** on the Actions tab, or upload any file, to restart it.
- **Opening the page always gets the newest build.** It skips the browser and GitHub caches, and pulls
  everything again when you come back to the tab. If the newest build is over 20 minutes old while futures
  trade, the page says so.
- **Why runs start each other.** GitHub's own scheduler is unreliable: it ran an every-10-minutes schedule only a
  few times a day. A run may start another run of the same workflow, so the job keeps itself going while futures
  trade; the schedule only restarts it if it ever stops, and a Sunday run waits for the 6 pm ET open.
- **Extra safety net (optional, free).** If the chain ever stops and you want it restarted on time instead of
  whenever GitHub's scheduler gets to it, cron-job.org can start the job:
  1. On GitHub: Settings > Developer settings > Personal access tokens > Fine-grained tokens > Generate new
     token. Repository access: only `gex-pro`. Permissions: **Actions: Read and write**. Nothing else.
  2. On cron-job.org (free account): Create cronjob. URL
     `https://api.github.com/repos/WSEVwevx/gex-pro/actions/workflows/website.yml/dispatches`, every 10 minutes.
     Advanced: method **POST**; headers `Authorization: Bearer <your token>`, `Accept: application/vnd.github+json`;
     request body `{"ref":"main"}`.
  3. A successful call returns 204 and a new run appears on the Actions tab. Keep the token private; it can
     only start this job.
- **The TradingView paste is the same.** Click "Copy for TradingView" on the hosted site exactly as on the
  local one.
