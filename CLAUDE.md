# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A demo/learning project showing FastAPI observability with Prometheus + Grafana. The `app` service is a small FastAPI API instrumented via `prometheus-fastapi-instrumentator`; the `loadgen` service is a standalone async script that continuously hits the app's `/load/*` endpoints purely to generate metrics traffic for the Grafana dashboards. There is no database and no task queue (Celery/RQ) — "worker" here means load generator, not background job processor.

## Stack & versions

Pinned versions live in `requirements/base.txt` / `requirements/dev.txt` (generated via `pip-compile` from `base.in`/`dev.in`) — treat these as the source of truth for what actually gets installed (tox and Docker both install from them). `pyproject.toml`'s `[tool.poetry]` ranges are kept aligned with these pins by hand; if you bump a version in one place, update the other too — there's no automation enforcing this.

- **Python**: 3.11 (`python:3.11` base image, tox `py311`)
- **Web framework**: FastAPI 0.139.2, served by Uvicorn 0.51.0 (`uvicorn[standard]`, uvloop/httptools)
- **Validation/config**: Pydantic 2.13.4, pydantic-settings 2.14.2
- **Observability**: prometheus-fastapi-instrumentator 8.0.2, prometheus-client 0.25.0
- **HTTP client**: httpx 0.28.1 (used by the loadgen worker and by tests via `TestClient`)
- **Testing**: pytest 9.1.1, pytest-asyncio 1.4.0, pytest-cov 7.1.0 / coverage 7.15.2
- **Lint/format**: black 26.5.1, isort 8.0.1, flake8 7.3.0 — no mypy, no ruff, no custom config (stock defaults)
- **Infra**: Docker Compose (`app`, `prometheus`, `grafana`, `loadgen` services), Prometheus (`prom/prometheus:latest`), Grafana (`grafana/grafana:latest`)

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
No custom config for any of the three — all run with stock defaults. Latent flake8-default (79) vs black-default (88) line-length mismatch to watch for if flake8 starts failing on long lines.

### Security / dependency audit
```bash
tox -e safety    # pip-audit against requirements/base.txt and requirements/dev.txt
```
Part of the default `envlist` (`py311, lint, safety`). Runs `pip-audit` against `base.txt` and `dev.txt` **separately**, not in one combined invocation — a combined run can fail outright with a pip dependency-resolution error if the two files ever drift on a shared transitive package's version (see "Dependency drift risk" above), which would be a false negative for `tox -e safety` as a whole. If this env starts failing with actual CVE findings, decide whether to bump the affected pin(s) via `pip-compile --upgrade-package <name> requirements/<base|dev>.txt` or accept/ignore the finding (`pip-audit --ignore-vuln <ID>`) — don't silently drop the env from `envlist` to make CI green again.

### Run everything at once
```bash
tox              # tests (py311) + lint + safety in one go
```

### Run the app / stack locally
```bash
docker compose up --build
# app:        http://localhost:8002
# prometheus: http://localhost:9090
# grafana:    http://localhost:3000 (admin/admin)

uvicorn app.main:app --host 0.0.0.0 --port 8002   # app standalone, without Docker

docker compose up -d --build    # detached; stop later from any terminal
# Ctrl+C in the foreground run  -> graceful stop (second Ctrl+C force-kills)
docker compose stop             # stop containers, keep them (resume: docker compose start)
docker compose down             # + remove containers and the default network
docker compose down --volumes --rmi all   # + anonymous volumes + all four service images
```
All of these must run from the repo root — the compose project name comes from the directory, so running them elsewhere targets a different (or empty) project.

No named volumes are declared (`docker compose config --volumes` prints nothing), so `--volumes` only drops the stack's single anonymous volume: Prometheus's `/prometheus` — the scraped metrics history. That ownership is easy to get backwards: `prom/prometheus:latest` declares `VOLUME /prometheus`, `grafana/grafana:latest` declares no `VOLUME` at all (`docker image inspect <img> --format '{{json .Config.Volumes}}'`), so Grafana's runtime state (`grafana.db`: hand-made dashboards, users, preferences) sits in the container's writable layer and is already lost on a plain `docker compose down` — only `stop`/`start` preserves it. The provisioned datasource and `grafana/dashboards/fastapi_metrics.json` are bind mounts and come back on the next `up`; bind-mounted repo files are never removed (note `./grafana/dashboards` is mounted *inside* `/var/lib/grafana`, but it's repo content and survives).

`--rmi all` deletes the two built images (`app`, `loadgen`) **and** the two pulled ones (`prom/prometheus:latest`, `grafana/grafana:latest`) — the pulled ones are shared with any other project on the machine using them, and Docker skips any image still referenced by another container, so the command can partially succeed with a warning. The next `up --build` then has to re-pull and rebuild; plain `docker compose down` keeps images and the build cache, so prefer it and use `--rmi all` only to reclaim disk.

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

- `tests/conftest.py` provides `client` (`TestClient(app)`) and `test_settings` fixtures.
- One test file per module (`test_config.py`, `test_example.py`, `test_main.py`, `test_load.py`, `test_load_driver.py`), asserting exact status code + JSON body.
- Async worker tests use `pytest-asyncio` with `unittest.mock.AsyncMock`/`patch` to mock `httpx.AsyncClient.get` (both success and exception paths) and `monkeypatch` to run `main(cycles=1)` instead of an infinite loop — follow this pattern rather than making real network calls in tests.

## Feature specs & plans

Feature documentation lives in `specs/<CU-code>/` — one folder per ClickUp ticket, holding exactly two files:

- `spec.md` — the what and the why: summary, objective, scope (in/out), expected behaviour, acceptance criteria, status (`Draft` / `Approved`).
- `plan.md` — the how: context, facts verified against the repo, affected files, tasks, edge cases, verification steps. Links back to `./spec.md`.

`<CU-code>` is the ticket code alone (e.g. `CU-86bb2m2t2`), taken from the branch name `feat/<CU-code>-<slug>` — the descriptive slug belongs in the document title, not in the folder name. The two files cross-link with sibling relative links (`./spec.md`, `./plan.md`), so the whole folder can be moved without breaking them. Nothing in CI, tox or any hook reads these files — the convention is manual, so follow it by hand when starting a new feature.
