# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A demo/learning project showing FastAPI observability with Prometheus + Grafana. The `app` service is a small FastAPI API instrumented via `prometheus-fastapi-instrumentator`; the `loadgen` service is a standalone async script that continuously hits the app's `/load/*` endpoints purely to generate metrics traffic for the Grafana dashboards. There is no database and no task queue (Celery/RQ) — "worker" here means load generator, not background job processor.

## Stack & versions

Pinned versions live in `requirements/base.txt` / `requirements/dev.txt` (generated via `pip-compile` from `base.in`/`dev.in`) — treat these as the source of truth for what actually gets installed (tox and Docker both install from them). `pyproject.toml`'s `[tool.poetry]` ranges are kept aligned with these pins by hand; if you bump a version in one place, update the other too — there's no automation enforcing this.

- **Python**: 3.11 (`python:3.11.15` base image, tox `py311`)
- **Web framework**: FastAPI 0.139.2, served by Uvicorn 0.51.0 (`uvicorn[standard]`, uvloop/httptools)
- **Validation/config**: Pydantic 2.13.4, pydantic-settings 2.14.2
- **Observability**: prometheus-fastapi-instrumentator 8.0.2, prometheus-client 0.25.0
- **HTTP client**: httpx 0.28.1 (used by the loadgen worker and by tests via `TestClient`)
- **Testing**: pytest 9.1.1, pytest-asyncio 1.4.0, pytest-cov 7.1.0 / coverage 7.15.2
- **Lint/format**: black 26.5.1, isort 8.0.1, flake8 7.3.0 — no mypy, no ruff, no custom config (stock defaults)
- **Infra**: Docker Compose (`app`, `prometheus`, `grafana`, `loadgen` services, all behind `profiles`), Prometheus (`prom/prometheus:v3.13.2`), Grafana (`grafana/grafana:12.4.7`)

Every image reference is pinned to an exact patch version, and `tests/test_compose_config.py` fails on any tag that is not `^v?\d+\.\d+\.\d+$` — that catches `:latest` and a floating minor like `python:3.11` alike. Bumping a pin means editing `docker-compose.yml` (or the two `Dockerfile`s) **and** this list; the Prometheus tag additionally appears in the `infra` CI job, which runs `promtool` through that same image.

**`fastapi[standard-no-fastapi-cloud-cli]`, not `fastapi[standard]`**: since FastAPI 0.139, the `standard` extra pulls in `fastapi-cloud-cli` and its dependencies (`sentry-sdk`, `fastar`, `rignore`, `detect-installer`) — deployment tooling this project has no use for. `requirements/base.in` intentionally uses the `standard-no-fastapi-cloud-cli` extra instead to keep that out of the dependency tree. Don't switch it back to `standard` without a reason.

**Dependency drift risk**: `base.txt` and `dev.txt` are compiled independently (`pip-compile requirements/base.in` / `pip-compile requirements/dev.in`), so shared transitive packages can in principle resolve to different versions across the two files (this happened before with `prometheus-client` — resolved by the most recent `--upgrade`, but nothing prevents it from recurring on the next upgrade). If `pip-audit -r requirements/base.txt -r requirements/dev.txt` ever fails with a pip dependency-resolution error instead of a vulnerability report, that's this happening again — check both files for the conflicting package.

## Commands

### Tests

```bash
tox -e py311                                            # full suite via tox (uses requirements/dev.txt)
pytest tests/                                           # full suite directly (after pip install -r requirements/dev.txt)
pytest tests/test_load.py                               # single file
pytest tests/test_load.py::test_io_bound_endpoint -v    # single test
pytest --cov=app --cov=worker --cov-fail-under=80 --cov-report term-missing tests/   # with coverage (tox's gate: 80%)
```

### Lint / format

```bash
tox -e lint      # black --check, isort --check-only, flake8 (what CI/tox enforces)
black .          # auto-format
isort .          # auto-sort imports
flake8 .         # lint only
```

No custom config for any of the three — all run with stock defaults, which leaves flake8 at 79 columns and black at 88. That mismatch is no longer latent: it fired while writing the infra tests. Keep new lines under 79 by construction — see "Testing conventions" for the shape of the failure and the way out.

### Markdown lint

No command: Markdown is checked live by the `markdownlint` VS Code extension, not by `tox` or CI. `.markdownlint.jsonc` at the repo root is the rule set — the stock rules with two changes: `MD013` (line-length) is disabled, because prose here is written one paragraph per line and enforcing a column limit would mean rewrapping every documentation file; and `MD060` (`table-column-style`) is pinned to `compact`, because its default of `any` only asks each table to be internally consistent, so a new table written entirely tight would pass and the repo would end up with two styles. This needs an extension bundling markdownlint v0.39.0 or newer, which is where `MD060` landed. Nothing gates a commit on any of it, so check the editor's Problems panel after editing any `.md`.

### Security / dependency audit

```bash
tox -e safety    # pip-audit against requirements/base.txt and requirements/dev.txt
```

Part of the default `envlist` (`py311, lint, safety`). Runs `pip-audit` against `base.txt` and `dev.txt` **separately**, not in one combined invocation — a combined run can fail outright with a pip dependency-resolution error if the two files ever drift on a shared transitive package's version (see "Dependency drift risk" above), which would be a false negative for `tox -e safety` as a whole. If this env starts failing with actual CVE findings, decide whether to bump the affected pin(s) via `pip-compile --upgrade-package <name> requirements/<base|dev>.txt` or accept/ignore the finding (`pip-audit --ignore-vuln <ID>`) — don't silently drop the env from `envlist` to make CI green again.

### Infra checks

```bash
pytest tests/test_compose_config.py tests/test_prometheus_config.py tests/test_grafana_provisioning.py

docker compose --profile '*' config -q      # compose file parses and resolves
docker run --rm --entrypoint promtool \
  -v "$PWD/prometheus.yml:/etc/prometheus/prometheus.yml:ro" \
  prom/prometheus:v3.13.2 \
  check config /etc/prometheus/prometheus.yml
```

The three test files ride along in the normal `tox -e py311` run — they need no Docker and import neither `app` nor `worker`, so they add nothing to the coverage denominator. They are **structural**: they assert the configuration files parse and carry the fields this stack depends on. They say nothing about whether a query returns data or a dashboard panel is correct, and they are named so they cannot be mistaken for that.

The two `docker` commands are what the `infra` job in `.github/workflows/python-app.yml` runs, and they cover the semantics no Python test can reach — `promtool` rejects a `scrape_interval: not-a-duration` that `yaml.safe_load` happily parses. Note that `config -q` exits **0** when it resolves zero services, which is why the CI job follows it with `config --services | grep -q .`; without the wildcard profile it would validate an empty file and report success.

### Run everything at once

```bash
tox              # tests (py311) + lint + safety in one go
```

### Run the app / stack locally

```bash
docker compose --profile core --profile load up --build   # the whole stack
# app:        http://localhost:8002
# prometheus: http://localhost:9090
# grafana:    http://localhost:3000 (admin/admin)

docker compose --profile core up -d    # app + prometheus + grafana, no synthetic traffic
docker compose --profile load up -d    # app + loadgen, no observability side

uvicorn app.main:app --host 0.0.0.0 --port 8002   # app standalone, without Docker

# Ctrl+C in a foreground run -> graceful stop (second Ctrl+C force-kills)
docker compose --profile '*' stop             # stop containers, keep them (resume with `--profile '*' start`)
docker compose --profile '*' down             # + remove containers and the default network
docker compose --profile '*' down --volumes   # + DESTROY both databases — see below
docker compose --profile '*' down --rmi all   # + all four service images
```

All of these must run from the repo root — the compose project name comes from the directory, so running them elsewhere targets a different (or empty) project.

**Every service sits behind a profile, so `--profile` is not optional.** `app` is in both `core` and `load` (so `--profile load` boots something worth hitting); `prometheus` and `grafana` are in `core`; `loadgen` is in `load`. A bare `docker compose up` starts nothing, and — the part that costs an afternoon — most other subcommands **silently do nothing** rather than complain. Measured on Compose v5.3.1:

| Command without `--profile` | What actually happens |
| --- | --- |
| `up` | starts nothing |
| `down`, `stop`, `start` | no output, exit 0, containers untouched |
| `logs` | prints nothing |
| `config -q` | validates an empty file, exit 0 |
| `build` | warns `No services to build`, exit 0 |
| `ps` | **not** filtered — lists the running containers |

`ps` being the exception is what makes the rest confusing: a bare `down` looks like it hung, because `ps` right afterwards still shows everything running. Use `--profile '*'` for anything that acts on the whole stack, or export `COMPOSE_PROFILES=core,load` once per shell.

**Named volumes, and what survives what.** `docker compose config --volumes` prints `prometheus_data` and `grafana_data`. Both databases now outlive their containers: Prometheus's TSDB at `/prometheus` and Grafana's `grafana.db` at `/var/lib/grafana` (hand-made dashboards, users, preferences). A `down` without `--volumes` keeps both — only `down --volumes` destroys them, and it destroys *both*, which makes it considerably more dangerous than it used to be. The four configuration bind mounts (`./prometheus.yml`, the two `grafana/provisioning` directories, `./grafana/dashboards`) are mounted `:ro` and are repo content, so they are never removed and come back on the next `up`. Note `./grafana/dashboards` mounts *inside* `/var/lib/grafana`: Docker orders mounts by path depth, so the volume lands first and the bind on top — it works, but it looks broken when something else breaks.

`--rmi all` deletes the two built images (`app`, `loadgen`) **and** the two pulled ones (`prom/prometheus:v3.13.2`, `grafana/grafana:12.4.7`) — the pulled ones are shared with any other project on the machine using them, and Docker skips any image still referenced by another container, so the command can partially succeed with a warning. The next `up --build` then has to re-pull and rebuild; a `down` without `--rmi` keeps images and the build cache, so prefer it and use `--rmi all` only to reclaim disk.

**Readiness.** `app`, `prometheus` and `grafana` declare healthchecks, so `docker compose ps` reports `healthy` rather than merely `running`, and `loadgen` waits for a healthy `app` instead of racing it. Grafana's `start_period` is 90s on purpose: against a freshly created `grafana_data` it spends ~35–55s on schema migrations before binding its HTTP port, and a tighter grace marks it `unhealthy` just before it becomes ready. `restart: unless-stopped` reacts to a container *exiting*, not to it going unhealthy — the healthcheck is a readiness signal, not self-healing.

## Architecture

### Entry point & routing (`app/main.py`)

Composition root: creates the `FastAPI()` instance, wraps it with `Instrumentator().instrument(app).expose(app)` (this is what exposes `/metrics` for Prometheus scraping), and registers routers.

Routing convention: each feature lives in `app/api/endpoints/<feature>.py` and exports `router = APIRouter()`. `main.py` imports it aliased as `<feature>_route`/`<feature>_router` and calls `app.include_router(...)` (optionally with a `prefix`/`tags`). Follow this pattern for any new endpoint group rather than adding routes directly to `main.py`.

### API endpoints (`app/api/endpoints/`)

- `example.py` — placeholder route (`GET /example`).
- `load.py` — synthetic load endpoints mounted under `/load`, each deliberately exercising a different resource so the Grafana dashboard has data to show: `io-bound` (async sleep → latency), `cpu-bound` and `stress/{seconds}` (blocking busy-loops → CPU panel), `memory-spike` (large list allocation → memory panel). When adding new synthetic endpoints, also add them to `LOADGEN_URLS` in `docker-compose.yml` and to `worker/load_driver.py`'s `URLS` if they should be part of the continuous load.

### Config (`app/core/config.py`)

Single `Settings(BaseSettings)` (pydantic-settings) instantiated as a module-level singleton `settings`. This is the only thing in `core/` currently — no models or business logic beyond config. Env vars load from `.env`.

### Load generator worker (`worker/load_driver.py`)

Intentionally decoupled from the `app` package — it has its own `Dockerfile` and only depends on `httpx`, no shared requirements file with `app`. It loops forever (or `cycles` times, for testability), firing all URLs concurrently via `asyncio.gather` and sleeping 5s between rounds, talking to the app over the Docker network at `http://app:8002`. Note: the URLs/interval are hardcoded in this file — the `LOADGEN_INTERVAL`/`LOADGEN_URLS` env vars set on the `app` service in `docker-compose.yml` are not actually read by any code, so don't assume changing them has an effect.

### Observability wiring

`prometheus.yml` scrapes `app:8002/metrics` every 5s under job `fastapi-app`. Grafana auto-provisions a Prometheus datasource and a single dashboard (`grafana/dashboards/fastapi_metrics.json`, "FastAPI Metrics") from `grafana/provisioning/`. The dashboard's panels (p95 latency, req/s throughput, CPU, memory, status codes, 4xx/5xx rate — all templated by a `$handler` variable) are the reason the `/load/*` endpoints exist and shape what kind of load each one should generate.

## Testing conventions

- `tests/conftest.py` provides `client` (`TestClient(app)`), `test_settings` and `repo_root` fixtures — the last one is session-scoped and returns the repository root, for tests that read files rather than call code.
- One test file per module (`test_config.py`, `test_example.py`, `test_main.py`, `test_load.py`, `test_load_driver.py`), asserting exact status code + JSON body.
- Three files break that rule on purpose: `test_compose_config.py`, `test_prometheus_config.py` and `test_grafana_provisioning.py` have no Python module behind them — they parse `docker-compose.yml`, `prometheus.yml` and the provisioned Grafana files and assert the invariants the stack depends on. See "Infra checks" for what they do and do not cover.
- **flake8 runs at 79 columns while black formats to 88, and it bites.** A hand-wrapped expression that black wants to collapse onto an 87-column line makes `tox -e lint` fail on code black considers already formatted, and no formatting satisfies both. The fix is to shorten the expression — bind intermediate values to names — not to wrap harder.
- Async worker tests use `pytest-asyncio` with `unittest.mock.AsyncMock`/`patch` to mock `httpx.AsyncClient.get` (both success and exception paths) and `monkeypatch` to run `main(cycles=1)` instead of an infinite loop — follow this pattern rather than making real network calls in tests.

## Feature specs & plans

Feature documentation lives in `specs/<CU-code>/` — one folder per ClickUp ticket, holding exactly two files:

- `spec.md` — the what and the why: summary, objective, scope (in/out), expected behaviour, acceptance criteria, status (`Draft` / `Approved`).
- `plan.md` — the how: context, facts verified against the repo, affected files, tasks, edge cases, verification steps. Links back to `./spec.md`.

`<CU-code>` is the ticket code alone (e.g. `CU-86bb2m2t2`), taken from the branch name `feat/<CU-code>-<slug>` — the descriptive slug belongs in the document title, not in the folder name. The two files cross-link with sibling relative links (`./spec.md`, `./plan.md`), so the whole folder can be moved without breaking them. Nothing in CI, tox or any hook reads these files — the convention is manual, so follow it by hand when starting a new feature.
