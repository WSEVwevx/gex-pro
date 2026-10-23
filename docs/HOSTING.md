# Hosting the website for free (GitHub Pages)

This puts the same dashboard (Levels, Bias, News with the Trump feed) on a real web address such as
`https://yourname.github.io/gex-levels/`. You can open it from any device, and your PC doesn't need to be on.

**How it works:** GitHub runs a small job on its own computers about every 15 minutes during US market hours,
and every 2 hours otherwise. The job:
1. Fetches fresh Cboe options data, the ForexFactory calendar and Truth Social posts.
2. Runs the same calculations as START.bat.
3. Publishes the result as plain web pages.

It costs nothing and does not rely on Claude or on your terminal. The job is in
`.github/workflows/website.yml`; the build command is `python -m gexsys build-site`.

## One-time setup (about 10 minutes, all in the browser)

1. **Create a free GitHub account** at github.com, if you don't have one.
2. **Make a repository.** Click **+** (top right), then **New repository**.
   - Name: `gex-levels` (any name works, and it becomes part of the web address).
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
   - Your site is at `https://<your-username>.github.io/gex-levels/`. The link also appears in the run's
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
| How often it updates | Every minute or so in market hours | About every 15 min in market hours (GitHub can start runs 5–20 min late) |
| Windows notifications | Yes | No: check the "Next paste" time on the site |
| Who can open it | Only you (127.0.0.1) | Anyone who has the link |

- **Public:** the web address isn't listed anywhere, but anyone who has it can open the page. The page holds
  only public market data, with no account details.
- **Truth Social** may block GitHub's servers. If it does, the feed uses the trumpstruth.org archive
  instead, and the footer under the feed names the source.
- **60-day pause:** GitHub pauses scheduled jobs in a repository with no changes for 60 days, and emails
  you first. Click **Enable workflow** on the Actions tab, or upload any file, to restart it.
- **The TradingView paste is the same.** Click "Copy for TradingView" on the hosted site exactly as on the
  local one.
