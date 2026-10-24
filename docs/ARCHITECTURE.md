# Architecture

GEX PRO is independent feature packages, one app shell that joins them, and one web page.

| Package | Owns | May import |
|---|---|---|
| `gexsys/` | GEX only: options data, the math, levels, the hourly TradingView paste, the indicator script | nothing else in the project |
| `feeds/` | Market news: ForexFactory calendar, Truth Social posts | nothing else in the project |
| `briefings/` | NY AM and Asia session briefings | nothing else in the project |
| `trackrecord/` | The live track record (plans frozen before the open, graded after the close) and the VIX/VXN expected-move backtest | nothing else in the project |
| `gexpro/` | The app shell: the local website server, the hosted-site build, the START.bat command | `gexsys`, `feeds`, `briefings`, `trackrecord` |

`tests/test_architecture.py` fails the build if a feature package imports another one or the shell.

## Components

Each feature package exposes one **component**. The shell runs whatever is listed in
`gexpro/components.py`:

```python
class SomethingComponent:
    name = "something"
    def routes(self) -> dict:              # {"/api/something": handler}; handler(query) -> (status, body)
    def start(self) -> None:               # begin background work (threads); called by serve
    def stop(self) -> None:
    def build_static(self, data, state) -> dict:   # write data/something.json for the hosted site
```

- **Handlers** get the query string as a dict of lists (`parse_qs`), and return `(status, body)`.
  A dict or list body is sent as JSON; a str body is sent as text.
- **Paths** belong to exactly one component; a clash stops the app at start-up.
- **`build_static`** writes the same data as the routes, as files under `_site/data/`. The page reads
  `data/x.json` on the hosted site and `/api/x` locally (the `API` map at the top of the page's script).
- **`state`** is a folder that the GitHub workflow keeps between hosted builds (caches, history).

Today's components:

| Component | Routes | Hosted files |
|---|---|---|
| `gexsys.component.GexComponent` | `/health`, `/api/markets`, `/api/all`, `/api/levels`, `/api/pine`, `/api/pine/all`, `/api/indicator`, `/api/heatmap` | `all.json`, `pine-*.txt`, `indicator.json` |
| `feeds.component.FeedsComponent` | `/api/news`, `/api/posts`, `/api/quotes` | `news.json`, `posts.json`, `quotes.json` |
| `briefings.component.BriefingsComponent` | `/api/briefings` | `briefings.json` |
| `trackrecord.component.TrackRecordComponent` | `/api/trackrecord` | `trackrecord.json` (sessions kept in `$GEXPRO_TRACK_DIR`, which the workflow keeps in the `track-record` branch) |

## Features that need other features' data

Briefings use GEX levels, the calendar and posts, but may not import those packages. Instead the shell
builds a plain snapshot (`gexpro/context.py`) and passes it in as `context()`, together with anything
else it needs (`is_trading_day`, `notify`). The feature defines the snapshot's shape in its own docs
(`briefings/compose.py`), so it can be tested with hand-made data. Do the same for future features.
The track record works the same way: the shell's `pre_open(gex, date)` reads the saved snapshots and hands
over plain dicts in the shape `trackrecord/score.py` documents.

## The website

`dashboard/index.html` (markup), `dashboard/assets/terminal.css` (look) and `dashboard/assets/app.js`
(behaviour). The local server serves `/assets/<file>` (plain file names only); the hosted build copies
the assets and adds `?v=<content hash>` to their links, so browsers never keep a stale copy. Every
module with `data-help="key"` gets an Explain button; its text lives in the `HELP` table in `app.js`.
The Library's lessons, glossary and diagrams are content only, in `dashboard/assets/library.js`
(`forHelp` maps each Explain key to its lesson). Add a lesson by adding an entry there.

## Adding a feature

1. Make a new package next to the others, e.g. `flows/`. It imports only the standard library and
   its own modules.
2. Give it `flows/component.py` with a `FlowsComponent` that has the four parts above.
3. Add it to `default_components()` in `gexpro/components.py`, and add `"flows"` to `ALLOWED["gexpro"]`
   and a `"flows": set()` row in `tests/test_architecture.py`, plus `"flows*"` in `pyproject.toml`.
4. Add its page: a sidebar button and a view `<div>` (with `data-help` on each module) in `dashboard/index.html`,
   an `API` entry, a `PAGES` row, a `HELP` entry and a
   load/render function in `dashboard/assets/app.js`. Copy the Live table or Track record page as a template.
5. Add `tests/test_flows_*.py` with the network replaced by canned responses.

## Commands

| Command | Package |
|---|---|
| `python -m gexpro serve --auto` | the local website and all background work (what START.bat runs) |
| `python -m gexpro build-site --out _site --state .state` | the hosted copy (the GitHub workflow) |
| `python -m gexsys demo / snapshot / audit / replay / sensitivity` | GEX-only tools |
