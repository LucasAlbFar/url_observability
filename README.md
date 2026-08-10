# FastAPI Observability Demo

A small FastAPI service instrumented end-to-end with **Prometheus** and **Grafana**, paired with a synthetic load generator so the dashboards always have real traffic to show. No database, no task queue — this project is purely a hands-on observability playground.

## How it works

- **`app`** — a FastAPI service (`app/main.py`) instrumented via `prometheus-fastapi-instrumentator`, which exposes a `/metrics` endpoint.
- **`loadgen`** — a standalone async script (`worker/load_driver.py`) that continuously calls the app's `/load/*` endpoints over HTTP, purely to generate traffic for the metrics/dashboards.
- **`prometheus`** — scrapes `app:8002/metrics` every 5s.
- **`grafana`** — auto-provisioned with a Prometheus datasource and a ready-made "FastAPI Metrics" dashboard (request latency p95, throughput, CPU, memory, status codes, 4xx/5xx error rate).

The `/load/*` endpoints each stress a different resource on purpose, so the dashboard has something to plot:

| Endpoint | What it does | Dashboard panel it feeds |
| --- | --- | --- |
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
- markdownlint (Markdown style, via the VS Code extension bundling markdownlint 0.39+; rules in `.markdownlint.jsonc`)
- Docker Compose, with every service behind a `core` or `load` profile
- Prometheus `prom/prometheus:v3.13.2` and Grafana `grafana/grafana:12.4.7`, both pinned — no image tracks `latest`

Exact Python pins live in `requirements/base.txt` / `requirements/dev.txt`. [CLAUDE.md](CLAUDE.md) covers the conventions for working on the code.

## Running the stack

```bash
docker compose --profile core --profile load up --build
```

| Service | URL |
| --- | --- |
| FastAPI app | <http://localhost:8002> |
| Prometheus | <http://localhost:9090> |
| Grafana | <http://localhost:3000> (login: `admin` / `admin`) |

**Every service sits behind a profile, so `--profile` is required on every `docker compose` command** — teardown included. Without it most subcommands do nothing at all: `up` starts nothing, and `down`, `stop`, `start` and `logs` print nothing and exit `0` while leaving the containers untouched. Only `build` warns (`No services to build`), and only `ps` ignores profiles and lists the containers anyway — which is what makes a bare `down` look like it hung rather than like it did nothing. Use `--profile '*'` for anything acting on the whole stack, or export `COMPOSE_PROFILES=core,load` once per shell.

Pick the group you need:

| Command | Brings up | Use it for |
| --- | --- | --- |
| `docker compose --profile core up -d` | `app`, `prometheus`, `grafana` | dashboards, without synthetic traffic |
| `docker compose --profile load up -d` | `app`, `loadgen` | exercising the API, without the observability side |
| `docker compose --profile core --profile load up -d` | all four | the full demo |

`app` belongs to both profiles on purpose, so `--profile load` boots something worth hitting instead of a generator retrying against nothing.

The first `up` takes a while to go green: Grafana runs its schema migrations against an empty database before opening its HTTP port, so `docker compose ps` can show it as `starting` for the better part of a minute. `app`, `prometheus` and `grafana` all report `healthy` once ready, and `loadgen` waits for a healthy `app` before it starts generating traffic.

The app also runs standalone, without Docker. Use a virtualenv — these requirements are pinned and installing them into your system Python is a bad trade:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements/base.txt
uvicorn app.main:app --host 0.0.0.0 --port 8002
```

### Stopping and cleaning up

`Ctrl+C` in the terminal running the foreground `up` (or the standalone `uvicorn` process) asks for a graceful shutdown; pressing it a second time force-kills instead of waiting for the grace period.

Everything below needs `--profile` for the reason given above — a bare `docker compose down` silently does nothing:

| Goal | Command |
| --- | --- |
| Stop the foreground run | `Ctrl+C` |
| Stop containers, keep them | `docker compose --profile '*' stop` (resume with `--profile '*' start`) |
| Stop + remove containers and the default network | `docker compose --profile '*' down` |
| Run detached, stop later from any terminal | `docker compose --profile core --profile load up -d --build` → `docker compose --profile '*' down` |
| Full teardown, **including both databases** | `docker compose --profile '*' down --volumes --rmi all` |

**What a `--volumes` teardown destroys.** The stack declares two named volumes, and `--volumes` erases both:

| Volume | Holds |
| --- | --- |
| `prometheus_data` | the scraped metrics history (`/prometheus`) |
| `grafana_data` | dashboards, users and preferences you created by hand (`/var/lib/grafana`) |

Everything else survives: a `down` without `--volumes` keeps both databases, so the metrics history and any dashboard you built in the UI are still there after the next `up`. The provisioned datasource and the "FastAPI Metrics" dashboard are bind-mounted from the repo, and bind-mounted repo files are **never** deleted.

Don't take that on faith — it takes two minutes to prove. With the stack up, create a dashboard by hand in Grafana and let Prometheus scrape for a few minutes, then:

```bash
docker compose --profile '*' down
docker compose --profile core --profile load up -d
```

Your dashboard is still in Grafana, and a `http_requests_total` query in Prometheus still returns points from before the teardown. Adding `--volumes` to that `down` is what erases them.

`docker compose --profile '*' down` on its own keeps images and the build cache, so the next `up --build` is fast — that's the option to reach for by default. Add `--rmi all` only to reclaim disk: it also deletes the pulled `prom/prometheus:v3.13.2` and `grafana/grafana:12.4.7` images, which are shared with any other project on the machine using them, so Docker skips any still referenced elsewhere and the command can partially succeed with a warning.

Run all of these from the repo root — the compose project name is derived from the directory, so running them elsewhere targets a different (or empty) project.

## Development

Install dev dependencies, in a virtualenv:

```bash
python -m venv .venv && source .venv/bin/activate
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

### Infra checks

Three test files validate the stack's configuration rather than any Python module — `docker-compose.yml`, `prometheus.yml` and the provisioned Grafana files. They run inside the normal `tox` and need no Docker. CI additionally validates the same files with the tools that own them:

```bash
docker compose --profile '*' config -q
docker run --rm --entrypoint promtool \
  -v "$PWD/prometheus.yml:/etc/prometheus/prometheus.yml:ro" \
  prom/prometheus:v3.13.2 \
  check config /etc/prometheus/prometheus.yml
```

The `--profile '*'` is load-bearing: without it `config` resolves no services and validates an empty file, exiting `0`.

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

`pip-compile` breaks in both directions when `pip` and `pip-tools` disagree, and the two failures need opposite fixes:

- `AttributeError: 'PackageFinder' object has no attribute 'allow_all_prereleases'` — `pip-tools` is older than the installed `pip`. Fix with `pip install --upgrade pip-tools`.
- `ImportError: cannot import name 'stdlib_pkgs' from 'pip._internal.utils.compat'` — the reverse: `pip` is **newer** than any released `pip-tools` supports (`piptools.sync` imports a private symbol that pip 26 removed). Upgrading `pip-tools` does not help, because 7.6.0 is already the latest. Downgrade pip instead, or run the compile from a throwaway virtualenv:

```bash
pip install "pip<26"    # in the environment you compile from

# or, leaving your environment untouched:
python -m venv /tmp/compilevenv
/tmp/compilevenv/bin/pip install "pip==25.3" "pip-tools==7.6.0"
/tmp/compilevenv/bin/pip-compile --output-file=requirements/dev.txt requirements/dev.in
```

Notes:

- Because `base.in` and `dev.in` are compiled independently, a shared transitive dependency can resolve to slightly different versions in each `.txt` file. This isn't harmful by itself, but keep it in mind when comparing dev vs. container behaviour. `tox -e safety` is immune, since it audits the two files in separate invocations — but a hand-written `pip-audit -r requirements/base.txt -r requirements/dev.txt` will abort with a resolution error instead of reporting vulnerabilities. If that happens, look for the same package pinned differently in the two files.
- `requirements/base.in` deliberately requests `fastapi[standard-no-fastapi-cloud-cli]`, not `fastapi[standard]` — the latter pulls in `fastapi-cloud-cli` and its dependencies (`sentry-sdk`, `fastar`, `rignore`), which this project doesn't use. Keep that extra as-is when upgrading FastAPI.
- After regenerating, also update the version ranges in `pyproject.toml` (`[tool.poetry.dependencies]` / `[tool.poetry.dev-dependencies]`) to match — nothing enforces this automatically.
- Re-run `tox` after regenerating to confirm the new pins still pass tests, lint, and the audit.

## Project layout

```text
app/
  main.py                 # FastAPI app, instrumentation, router registration
  api/endpoints/          # one module per route group (example, load)
  core/config.py          # pydantic-settings Settings singleton
worker/
  load_driver.py          # standalone async load generator (calls app's /load/* endpoints)
grafana/                  # provisioned datasource + "FastAPI Metrics" dashboard
prometheus.yml            # Prometheus scrape config
docker-compose.yml        # the four services, their profiles and named volumes
tests/                    # pytest suite: one file per module, plus four that check config
requirements/             # pip-compile sources (base.in/dev.in) and lockfiles (base.txt/dev.txt)
```

For the conventions to follow when changing any of this, see [CLAUDE.md](CLAUDE.md).
