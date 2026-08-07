# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A demo/learning project showing FastAPI observability with Prometheus + Grafana. The `app` service is a small FastAPI API instrumented via `prometheus-fastapi-instrumentator`; the `loadgen` service is a standalone async script that continuously hits the app's `/load/*` endpoints purely to generate metrics traffic for the Grafana dashboards. There is no database and no task queue (Celery/RQ) — "worker" here means load generator, not background job processor.

## Stack & versions

`requirements/base.txt` / `requirements/dev.txt` (compiled from `base.in`/`dev.in`) are the source of truth for what gets installed — tox and Docker both install from them. `pyproject.toml`'s `[tool.poetry]` ranges are kept aligned by hand; if you bump a version in one place, update the other too, because nothing enforces it.

What those files don't tell you:

- Python 3.11 — `python:3.11.15` base image, tox `py311`.
- Prometheus `prom/prometheus:v3.13.2`, Grafana `grafana/grafana:12.4.7`. Every image reference is pinned to an exact patch version, and `tests/test_compose_config.py` rejects anything looser, including a floating minor like `python:3.11`. A Prometheus bump also has to touch the `infra` job in `.github/workflows/python-app.yml`, which runs `promtool` through the same image.
- No mypy, no ruff, and no custom config for black, isort or flake8.

**`fastapi[standard-no-fastapi-cloud-cli]`, not `fastapi[standard]`**: since FastAPI 0.139, the `standard` extra pulls in `fastapi-cloud-cli` and its dependencies — deployment tooling this project has no use for. Don't switch `requirements/base.in` back to `standard` without a reason.

**Dependency drift risk**: `base.txt` and `dev.txt` are compiled independently, so a shared transitive package can resolve to different versions across them. If `pip-audit -r requirements/base.txt -r requirements/dev.txt` fails with a pip dependency-resolution error instead of a vulnerability report, that is what happened — check both files for the conflicting package.

## Commands

### Tests

```bash
tox -e py311                                            # full suite via tox (uses requirements/dev.txt)
pytest tests/                                           # full suite directly (after pip install -r requirements/dev.txt)
pytest tests/test_load.py                               # single file
pytest tests/test_load.py::test_load_io_bound -v         # single test
pytest --cov=app --cov=worker --cov-fail-under=80 --cov-report term-missing tests/   # with coverage (tox's gate: 80%)
```

### Lint / format

```bash
tox -e lint      # black --check, isort --check-only, flake8 (what CI/tox enforces)
black .          # auto-format
isort .          # auto-sort imports
flake8 .         # lint only
```

Stock defaults leave flake8 at 79 columns and black at 88. Keep lines under 79 by construction: when black wants to collapse a wrapped expression onto a line between 80 and 88 columns, `tox -e lint` fails on code black considers already formatted, and no formatting satisfies both. Shorten the expression — bind intermediate values to names — rather than wrapping harder.

### Markdown lint

No command: Markdown is checked live by the `markdownlint` VS Code extension, not by `tox` or CI, so check the editor's Problems panel after editing any `.md`. `.markdownlint.jsonc` is the rule set — stock rules, with `MD013` (line-length) disabled and `MD060` (`table-column-style`) pinned to `compact`, so write tables in the compact style (`| --- | --- |`). Needs an extension bundling markdownlint v0.39.0 or newer.

### Security / dependency audit

```bash
tox -e safety    # pip-audit against requirements/base.txt and requirements/dev.txt
```

Part of the default `envlist` (`py311, lint, safety`). It audits `base.txt` and `dev.txt` in **separate** invocations — keep it that way; a combined run can abort with a dependency-resolution error that reads as "no findings". On a real CVE, either bump the pin via `pip-compile --upgrade-package <name> requirements/<base|dev>.txt` or ignore it explicitly with `pip-audit --ignore-vuln <ID>` — don't drop the env from `envlist` to make CI green.

### Infra checks

```bash
pytest tests/test_compose_config.py tests/test_prometheus_config.py tests/test_grafana_provisioning.py

docker compose --profile '*' config -q      # compose file parses and resolves
docker run --rm --entrypoint promtool \
  -v "$PWD/prometheus.yml:/etc/prometheus/prometheus.yml:ro" \
  prom/prometheus:v3.13.2 \
  check config /etc/prometheus/prometheus.yml
```

The three test files ride along in the normal `tox -e py311` run and need no Docker. They are **structural**: they assert the configuration files parse and carry the fields the stack depends on, and say nothing about whether a query returns data or a dashboard panel is correct. Don't read a green run as a dashboard review.

The two `docker` commands are what the `infra` job in `.github/workflows/python-app.yml` runs, and they reach semantics no Python test does. `config -q` exits **0** when it resolves zero services, so never run it without a profile and read success as validation.

### Run everything at once

```bash
tox              # tests (py311) + lint + safety in one go
```

### Run the app / stack locally

```bash
docker compose --profile core --profile load up --build   # the whole stack
uvicorn app.main:app --host 0.0.0.0 --port 8002           # app standalone, without Docker
```

Run from the repo root — the compose project name comes from the directory. `README.md` ("Running the stack", "Stopping and cleaning up") owns the full command set: the profile groups, the teardown variants and what each one destroys. Three things from it change how you work on the code:

- **Every service sits behind a profile**, so `--profile` belongs on every `docker compose` subcommand, teardown included. Without it most of them do nothing and still exit 0 — only `build` warns, and only `ps` ignores profiles and lists the containers anyway.
- **`prometheus_data` and `grafana_data` survive a `down`.** Only `down --volumes` destroys them, and it destroys both.
- **`app`, `prometheus` and `grafana` have healthchecks**, so `loadgen` waits for a healthy `app` rather than racing it. Don't lower Grafana's 90s `start_period`: a cold boot spends most of a minute on schema migrations before its HTTP port opens, and anything declaring `depends_on: grafana: {condition: service_healthy}` inherits that wait. `restart: unless-stopped` reacts to a container *exiting*, not to it going unhealthy.

Measurements and the reasoning behind each of these: `specs/CU-86bb30dec/plan.md`.

## Architecture

**Routing.** Each feature lives in `app/api/endpoints/<feature>.py` and exports `router = APIRouter()`; `main.py` imports it and calls `app.include_router(...)`. Follow this pattern for any new endpoint group rather than adding routes directly to `main.py`. `/metrics` comes from `Instrumentator().instrument(app).expose(app)` in `app/main.py` — don't hand-roll a route for it.

**Synthetic load.** The `/load/*` endpoints each exercise a different resource on purpose — async sleep, blocking busy-loops, a large allocation — so the Grafana dashboard has something to plot. To put a new one into the continuous load, add it to `URLS` in `worker/load_driver.py`; that list is the only one any code reads.

**The load generator is intentionally decoupled** from the `app` package: its own `Dockerfile`, only `httpx`, no shared requirements file. Keep it that way. The `LOADGEN_INTERVAL`/`LOADGEN_URLS` env vars on the `app` service in `docker-compose.yml` are dead — no code reads them, and `LOADGEN_URLS` merely duplicates `URLS`.

**Observability wiring.** `prometheus.yml` scrapes `app:8002/metrics` every 5s under job `fastapi-app`. Grafana auto-provisions its datasource and `grafana/dashboards/fastapi_metrics.json` from `grafana/provisioning/`.

## Testing conventions

- `tests/conftest.py` provides `client`, `test_settings` and `repo_root` — the last is session-scoped and returns the repository root, for tests that read files rather than call code.
- One test file per module (`test_config.py`, `test_example.py`, `test_main.py`, `test_load.py`, `test_load_driver.py`), asserting exact status code + JSON body.
- Three files break that rule on purpose: `test_compose_config.py`, `test_prometheus_config.py` and `test_grafana_provisioning.py` have no Python module behind them — they parse `docker-compose.yml`, `prometheus.yml` and the provisioned Grafana files. See "Infra checks" for what they do and do not cover.
- Async worker tests use `pytest-asyncio` with `unittest.mock.AsyncMock`/`patch` to mock `httpx.AsyncClient.get` (both success and exception paths) and `monkeypatch` to run `main(cycles=1)` instead of an infinite loop — follow this pattern rather than making real network calls in tests.

## Feature specs & plans

Feature documentation lives in `specs/<CU-code>/` — one folder per ClickUp ticket, holding exactly two files:

- `spec.md` — the what and the why: summary, objective, scope (in/out), expected behaviour, acceptance criteria, status (`Draft` / `Approved`).
- `plan.md` — the how: context, facts verified against the repo, affected files, tasks, edge cases, verification steps. Links back to `./spec.md`.

`<CU-code>` is the ticket code alone (e.g. `CU-86bb2m2t2`), taken from the branch name `feat/<CU-code>-<slug>` — the descriptive slug belongs in the document title, not in the folder name. The two files cross-link with sibling relative links (`./spec.md`, `./plan.md`). Nothing reads these files automatically, so follow the convention by hand when starting a new feature.
