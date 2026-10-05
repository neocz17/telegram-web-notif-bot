# webwatch

Get a Telegram message when a website adds something new: a library session, a market, a sale listing.

It runs free on **GitHub Actions** every 15 minutes, so your laptop can be off.

```
watchers.yaml ─► fetch page/API ─► filter ─► compare with state/state.json ─► Telegram
```

## What it does for the Jurong Library sewing watcher

| When | Message |
|---|---|
| First run | One "Now watching" summary of what's currently listed |
| A new sewing session appears | **New in Jurong Library sewing** + date, venue, status |
| 60 min before registration opens | **Heads up: Registration opens at 12:00 PM ...** |
| Registration opens / a seat frees up | **Registration is OPEN - book now** |
| The site breaks 3 runs in a row | **Watcher failing** (and a "recovered" message later) |

NLB opens registration for a batch of sessions at a set time, and the event page says when ("Registrations open at 12:00 PM Saturday, October 10, 2026"). The heads-up reminder uses that.

---

## Setup (about 10 minutes)

### 1. Create your Telegram bot
1. In Telegram, open **@BotFather** and send `/newbot`.
2. Pick a display name and a username ending in `bot`.
3. BotFather replies with a **token** like `123456789:AAH...`. Keep it secret.

### 2. Find your chat ID
1. Open your new bot in Telegram and press **Start** (or send it any message).
2. In a browser, open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`.
3. Find `"chat":{"id":123456789,...}`. That number is your **chat ID**.

### 3. Put the code on GitHub
First, if there's a `MOVE_TO_.github_workflows` folder: create the folder `.github\workflows` and move `watch.yml` and `tests.yml` into it, then delete the empty `MOVE_TO_.github_workflows` folder. GitHub only runs workflows from `.github/workflows/`.

Create a new **empty public** repository on github.com (no README or .gitignore), then in a terminal:

```bash
cd "C:\Main Folder\Personal Projects\Web Update Notif App"
git init -b main
git add .
git commit -m "Initial webwatch"
git remote add origin https://github.com/<your-username>/<repo-name>.git
git push -u origin main
```

### 4. Add your secrets
Repo → **Settings → Secrets and variables → Actions → New repository secret**. Add both:
- `TELEGRAM_BOT_TOKEN`: the token from BotFather
- `TELEGRAM_CHAT_ID`: your chat ID

### 5. Start it
Repo → **Actions** tab → enable workflows if asked → **watch** → **Run workflow**.
Within a minute you should get the "Now watching" message. After that it runs every 15 minutes by itself.

**If the "Commit state" step fails with a 403:** go to Settings → Actions → General → Workflow permissions → **Read and write permissions** → Save.

---

## Is a public repo safe?

Yes, as long as secrets stay in **GitHub Secrets** and never in a file.

- **Secrets are protected.** They're encrypted, hidden (`***`) in logs, and not given to workflows started by other people's forks or pull requests.
- **Never commit `.env`** (it's already in `.gitignore`). If a token ever ends up in a commit, deleting the file isn't enough because git history keeps it. Revoke it in BotFather (`/revoke`) and make a new one.
- **Everything else is public:** your watch list, `state.json` and the run logs. Anyone can see you're watching sewing sessions at Jurong Library. Don't add watchers that reveal things you'd rather keep private.
- **Strangers can't run code here.** The bot only runs on its schedule or when you click the button; nobody else's pull request triggers it.
- **The 60-day rule:** GitHub pauses scheduled workflows in public repos after 60 days without repo activity. The bot commits `state.json` at least once a day, which should count as activity. If it ever pauses, GitHub emails you; re-enable it in the Actions tab.

Public repos get unlimited free Actions minutes. A private repo's free 2,000 minutes a month would only cover a run about every 30 minutes.

---

## Adding more websites

Edit `watchers.yaml`, then commit and push. There are three source types.

### `libcal`: library calendars (NLB and many universities)
Use the branch ID from the calendar page's location dropdown as `campus_id`.

### `rss`: sites with a feed
Look for an RSS icon, or try `/feed`, `/rss` or `/feed.xml` on the site.

### `html`: ordinary pages, described with CSS selectors
Right-click a listing → **Inspect** to see its HTML, then describe it:

```yaml
- name: Example shop - new arrivals
  type: html
  options:
    url: https://example.com/new-arrivals
    item_selector: ".product-card"   # matches each listing
    title: ".product-name"           # text inside each listing
    link: "a@href"                   # "selector@attribute"
    fields: { price: ".price" }
```

**Tip:** if the listings aren't in the page source (View Source shows nothing), the page loads them with JavaScript. Open DevTools (F12) → **Network** → filter **Fetch/XHR** → reload. You'll often find a JSON request with all the data. That's how the LibCal endpoint was found. A JSON endpoint is much more reliable than HTML scraping and is worth a small custom source in `webwatch/sources/`.

**Filters** (on any watcher):
```yaml
filters:
  include: "(?i)sew|quilt"        # regex the title must match ((?i) = ignore case)
  exclude: "(?i)kids"             # regex the title must NOT match
  fields: { location: "Jurong" }  # regex on a named field
```

Big marketplaces (Carousell, Shopee, etc.) actively block bots and their terms usually forbid scraping, so stick to sites that allow it.

---

## Running locally (optional)

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements-dev.txt

python -m webwatch --dry-run      # print what would be sent; doesn't save state
python -m pytest -q               # run the tests
```

To send real messages locally, copy `.env.example` to `.env`, fill it in, and run `python -m webwatch --test-telegram`.
Running locally without `--dry-run` updates your local `state/state.json`, which will clash with the bot's copy on GitHub. Run `git pull` first, or just use `--dry-run`.

## Project layout

```
watchers.yaml              what to watch
state/state.json           what's been seen (updated by the bot)
webwatch/
  __main__.py              command line (python -m webwatch)
  runner.py                fetch -> filter -> diff -> notify -> save
  config.py                watchers.yaml schema (pydantic)
  state.py                 load/save state.json
  notifiers.py             Telegram + console output
  sources/                 one file per website type (libcal, rss, html)
tests/                     pytest suite, no network needed
.github/workflows/         watch.yml (every 15 min), tests.yml (on push)
```


