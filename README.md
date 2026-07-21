# FastAPI Observability Demo

A small FastAPI service instrumented end-to-end with **Prometheus** and **Grafana**, paired with a synthetic load generator so the dashboards always have real traffic to show. No database, no task queue — this project is purely a hands-on observability playground.

## How it works

- **`app`** — a FastAPI service (`app/main.py`) instrumented via `prometheus-fastapi-instrumentator`, which exposes a `/metrics` endpoint.
- **`loadgen`** — a standalone async script (`worker/load_driver.py`) that continuously calls the app's `/load/*` endpoints over HTTP, purely to generate traffic for the metrics/dashboards.
- **`prometheus`** — scrapes `app:8002/metrics` every 5s.
- **`grafana`** — auto-provisioned with a Prometheus datasource and a ready-made "FastAPI Metrics" dashboard (request latency p95, throughput, CPU, memory, status codes, 4xx/5xx error rate).

The `/load/*` endpoints each stress a different resource on purpose, so the dashboard has something to plot:

| Endpoint | What it does | Dashboard panel it feeds |
|---|---|---|
| `GET /load/io-bound` | `asyncio.sleep(2)` | Request latency |
| `GET /load/cpu-bound` | Blocking CPU-heavy loop | CPU usage |
| `GET /load/stress/{seconds}` | Blocking busy-wait for N seconds | CPU usage |
| `GET /load/memory-spike` | Allocates a large in-memory list | Memory usage |

## Stack

- Python 3.11
- FastAPI 0.139 (Uvicorn), Pydantic 2 / pydantic-settings
- prometheus-fastapi-instrumentator
- pytest, pytest-asyncio, pytest-cov (80% coverage gate)
- black, isort, flake8
- pip-audit (dependency vulnerability scanning)
- Docker Compose, Prometheus, Grafana

See [CLAUDE.md](CLAUDE.md) for exact pinned versions and detailed architecture notes.

## Running the stack

```bash
docker compose up --build
```

| Service | URL |
|---|---|
| FastAPI app | http://localhost:8002 |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 (login: `admin` / `admin`) |

The app also runs standalone, without Docker:

```bash
pip install -r requirements/base.txt
uvicorn app.main:app --host 0.0.0.0 --port 8002
```

## Development

Install dev dependencies:

```bash
pip install -r requirements/dev.txt
```

Run tests (with coverage):

```bash
tox -e py311
# or directly:
pytest --cov=app --cov=worker --cov-fail-under=80 --cov-report term-missing tests/
```

Lint and format:

```bash
tox -e lint
# or individually:
black .
isort .
flake8 .
```

Run everything (tests + lint + dependency audit) at once:

```bash
tox
```

### Security / dependency audit

Check pinned dependencies for known vulnerabilities with [pip-audit](https://pypi.org/project/pip-audit/):

```bash
tox -e safety
```

This is part of the default `tox` run (`envlist = py311, lint, safety`). It checks `requirements/base.txt` and `requirements/dev.txt` **separately** rather than in one combined invocation — a combined run can fail with a plain pip dependency-resolution error instead of a vulnerability report if the two lockfiles ever drift on a shared transitive package's version (see "Updating dependencies" below). If `tox -e safety` reports a real CVE, either bump the affected package (`pip-compile --upgrade-package <name> ...`, see below) or explicitly ignore it with `pip-audit --ignore-vuln <ID>` if there's no fix yet — don't just remove `safety` from `envlist` to get a green build.

### Updating dependencies

Runtime deps are declared in `requirements/base.in`, dev/test/lint deps in `requirements/dev.in`. The actual pinned lockfiles (`requirements/base.txt` / `requirements/dev.txt`) are generated from those with `pip-compile` (from `pip-tools`) — don't hand-edit the `.txt` files.

After changing a dependency in one of the `.in` files, regenerate the corresponding lockfile:

```bash
pip install pip-tools   # if not already installed
pip-compile requirements/base.in -o requirements/base.txt
pip-compile requirements/dev.in -o requirements/dev.txt   # dev.in includes base.in, so run both
```

To pull in newer versions of already-pinned packages (e.g. to fix a CVE flagged by `tox -e safety`), add `--upgrade` (everything) or `--upgrade-package <name>` (just one package):

```bash
pip-compile --upgrade requirements/base.in -o requirements/base.txt
pip-compile --upgrade requirements/dev.in -o requirements/dev.txt
```

If `pip-compile` crashes with `AttributeError: 'PackageFinder' object has no attribute 'allow_all_prereleases'`, your `pip-tools` install predates the installed `pip` version — fix it with:

```bash
pip install --upgrade pip-tools
```

Notes:
- Because `base.in` and `dev.in` are compiled independently, a shared transitive dependency can resolve to slightly different versions in each `.txt` file. This isn't harmful by itself, but keep it in mind when comparing dev vs. container behavior, and re-check `tox -e safety` after any upgrade since a drifted package can make the combined `pip-audit` invocation fail outright with a resolution error.
- `requirements/base.in` deliberately requests `fastapi[standard-no-fastapi-cloud-cli]`, not `fastapi[standard]` — the latter pulls in `fastapi-cloud-cli` and its dependencies (`sentry-sdk`, `fastar`, `rignore`), which this project doesn't use. Keep that extra as-is when upgrading FastAPI.
- After regenerating, also update the version ranges in `pyproject.toml` (`[tool.poetry.dependencies]` / `[tool.poetry.dev-dependencies]`) to match — nothing enforces this automatically.
- Re-run `tox` after regenerating to confirm the new pins still pass tests, lint, and the audit.

## Project layout

```
app/
  main.py                 # FastAPI app, instrumentation, router registration
  api/endpoints/          # one module per route group (example, load)
  core/config.py          # pydantic-settings Settings singleton
worker/
  load_driver.py          # standalone async load generator (calls app's /load/* endpoints)
grafana/                  # provisioned datasource + "FastAPI Metrics" dashboard
prometheus.yml            # Prometheus scrape config
tests/                    # pytest suite (one test file per module)
requirements/             # pip-compile sources (base.in/dev.in) and lockfiles (base.txt/dev.txt)
```

For a deeper architecture walkthrough and conventions, see [CLAUDE.md](CLAUDE.md).
