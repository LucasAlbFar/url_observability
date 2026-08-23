# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A demo/learning project showing observability with Prometheus + Grafana across **two** services in different languages. The `app` service is a small FastAPI API instrumented via `prometheus-fastapi-instrumentator`; `service-go` is a small Go program instrumented via `prometheus/client_golang`, and it exists to test the claim that the stack attaches to something that is not the FastAPI app. The `loadgen` service is a standalone async script that continuously hits both services' `/load/*` endpoints purely to generate metrics traffic for the Grafana dashboards. There is no database and no task queue (Celery/RQ) — "worker" here means load generator, not background job processor.

## Stack & versions

`requirements/base.txt` / `requirements/dev.txt` (compiled from `base.in`/`dev.in`) are the source of truth for what gets installed — tox and Docker both install from them. `pyproject.toml`'s `[tool.poetry]` ranges are kept aligned by hand; if you bump a version in one place, update the other too, because nothing enforces it.

What those files don't tell you:

- Python 3.11 — `python:3.11.15` base image, tox `py311`.
- Prometheus `prom/prometheus:v3.13.2`, Grafana `grafana/grafana:12.4.7`. Every image reference is pinned to an exact patch version, and `tests/test_compose_config.py` rejects anything looser, including a floating minor like `python:3.11`. A Prometheus bump is one line in `docker-compose.yml` — the `infra` job derives the tag from there rather than repeating it — but every copy of a tag in this file and `README.md` has to move with it, and `tests/test_docs_versions.py` fails and names the file when one does not.
- Go 1.25 (`service-go/go.mod`) with `prometheus/client_golang`, built by `golang:1.26.5` and run on `alpine:3.24.1` — Alpine because its BusyBox `wget --spider` is the healthcheck probe. Nothing in `tox.ini` sees Go: `--cov=app --cov=worker` does not reach it and black/isort/flake8 only read Python, so its checks are a CI job of their own.
- No mypy, no ruff, and no custom config for black or isort. flake8's only setting is `max-line-length = 88` in `tox.ini`.

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

`tox.ini` sets flake8 to `max-line-length = 88`, the width black already formats to, so `tox -e lint` accepts what black produces. Left at its 79-column default, flake8 rejects lines black considers finished and no formatting satisfies both.

### Go service

```bash
cd service-go
gofmt -l .       # prints the files it would rewrite — and still exits 0
go vet ./...
go test ./...    # ~2s: two of the routes cost real time by design
```

These three are the `go` job in CI, which reads its toolchain from `service-go/go.mod` rather than naming a version. `gofmt` reporting through stdout while exiting 0 is why the job tests its *output*; do the same in any script that calls it.

### Markdown lint

No command: Markdown is checked live by the `markdownlint` VS Code extension, not by `tox` or CI, so check the editor's Problems panel after editing any `.md`. `.markdownlint.jsonc` is the rule set — stock rules, with `MD013` (line-length) disabled and `MD060` (`table-column-style`) pinned to `compact`, so write tables in the compact style (`| --- | --- |`). Needs an extension bundling markdownlint v0.39.0 or newer.

### Security / dependency audit

```bash
tox -e safety    # pip-audit against requirements/base.txt and requirements/dev.txt
```

Part of the default `envlist` (`py311, lint, safety`). It audits `base.txt` and `dev.txt` in **separate** invocations — keep it that way; a combined run can abort with a dependency-resolution error that reads as "no findings". On a real CVE, either bump the pin via `pip-compile --upgrade-package <name> requirements/<base|dev>.txt` or ignore it explicitly with `pip-audit --ignore-vuln <ID>` — don't drop the env from `envlist` to make CI green.

### Infra checks

```bash
pytest tests/test_compose_config.py tests/test_prometheus_config.py tests/test_grafana_provisioning.py tests/test_docs_versions.py

docker compose --profile '*' config -q      # compose file parses and resolves
docker run --rm --entrypoint promtool \
  -v "$PWD/prometheus.yml:/etc/prometheus/prometheus.yml:ro" \
  prom/prometheus:v3.13.2 \
  check config /etc/prometheus/prometheus.yml
```

The four test files ride along in the normal `tox -e py311` run and need no Docker. Three of them are purely **structural** — the configuration files parse and carry the fields the stack depends on. `tests/test_grafana_provisioning.py` goes further: since the dashboard rebuild it also asserts panel types, unique panel ids, non-overlapping `gridPos`, `refId` unique within each panel, datasource references by uid, the `job` variable, and that no scrape job name appears in any query. What none of them do is prove that a query returned data or that a panel drew — only a browser answers that, so don't read a green run as a dashboard review.

`tests/test_compose_config.py` reaches every Dockerfile in the repo through `rglob`, but not equally: the base-image pinning rule applies to all of them (bare `major.minor.patch` only — every suffixed tag such as `golang:1.26.5-alpine` is rejected, and so are `scratch` and distroless), while the rule that installed packages are pinned only understands `pip`, so a Dockerfile in another language passes it **vacuously**. For `service-go` what stands in for it is `go.sum` — a hash per module, stronger than pip's `==` — plus the assertion that both `go.mod` and `go.sum` exist and are non-empty. That guarantee is why the image resolves dependencies through `go mod download`; a `go install pkg@latest` would escape every check here. `tests/test_docs_versions.py` does not see this service at all: it maps services declaring `image:`, and a locally built one declares `build:`.

The `docker` commands are what the `infra` job in `.github/workflows/python-app.yml` runs, and they reach semantics no Python test does. One difference: the job reads the Prometheus image out of `docker-compose.yml` instead of naming it, so the tag written above is a copy-pasteable convenience that `tests/test_docs_versions.py` keeps in step. `config -q` exits **0** when it resolves zero services, so never run it without a profile and read success as validation.

### Run everything at once

```bash
tox              # tests (py311) + lint + safety in one go
```

### Run the app / stack locally

```bash
docker compose --profile core --profile load up --build   # the whole stack
uvicorn app.main:app --host 0.0.0.0 --port 8002           # app standalone, without Docker
```

Run from the repo root. `README.md` ("Running the stack", "Stopping and cleaning up") owns the full command set; three rules change how you work on the code:

- `--profile` belongs on every `docker compose` subcommand, teardown included. Without it most do nothing and still exit 0.
- `prometheus_data` and `grafana_data` survive a `down`. Only `down --volumes` destroys them, and it destroys both.
- Don't lower Grafana's 90s `start_period`. It was raised from 10s against a measurement, and anything waiting on `condition: service_healthy` inherits that wait.

Measurements and the reasoning behind each of these: `specs/CU-86bb30dec/plan.md`.

## Architecture

**Routing.** Each feature lives in `app/api/endpoints/<feature>.py` and exports `router = APIRouter()`; `main.py` imports it and calls `app.include_router(...)`. Follow this pattern for any new endpoint group rather than adding routes directly to `main.py`. `/metrics` comes from `Instrumentator().instrument(app).expose(app)` in `app/main.py` — don't hand-roll a route for it.

**Synthetic load.** The `/load/*` endpoints each exercise a different resource on purpose — async sleep, blocking busy-loops, a large allocation — so the Grafana dashboard has something to plot. To put a new one into the continuous load, add it to `URLS` in `worker/load_driver.py`; that list is the only one any code reads.

**The load generator is intentionally decoupled** from the `app` package: its own `Dockerfile`, one pinned dependency (`httpx`), no shared requirements file. Keep it that way. It reads no environment at all — `URLS` in `worker/load_driver.py` is the only list any code reads, so don't reintroduce a `LOADGEN_URLS` env var to duplicate it.

**The second service.** `service-go/` is flat on purpose — `main.go`, `main_test.go`, `go.mod`, `go.sum`, `Dockerfile`, no `cmd/` and no packages — and listens on **8003**. It serves `/health`, `/load/io-bound`, `/load/cpu-bound` and `/metrics`, reads no environment, and is called by nothing but the load generator. It deliberately mirrors the app's paths and deliberately does **not** mirror its metric labels: it exports what `client_golang` gives it (`code`/`method`, lowercase verb) rather than the instrumentator's `handler`/`status`. Ten metric names are now exported by both services, six of them `process_*` — including `process_cpu_seconds_total` and `process_resident_memory_bytes`, the two the dashboard's resource panels query — separated only by `job` and `instance`. That collision is the point of the service, not a defect to fix here; the full series list is in `specs/CU-86bbdrkm7/plan.md`.

**The dashboard.** `grafana/dashboards/services.json` — `Services Overview`, uid `services-overview` — is fourteen panels in three rows: *Services* groups by `job`; *Routes (`handler`)* and *Requests (`code`)* each hold whichever services carry that label. Three rules, all asserted by `tests/test_grafana_provisioning.py`:

- **`job` goes inside every bucket grouping.** The app publishes four `le` bounds and the Go service twelve, the app's four being a subset — so a `by (le, …)` without `job` produces bounds the app never reports, and every bucket below `0.1` counts one service only.
- **A convention row selects on label presence — `handler!=""`, `code!=""` — never on a job name.** Not cosmetic: `handler=~".*"` also matches series carrying no `handler`, collapsing a whole service into one unlabelled group.
- **An error panel carries one target per convention**, `status=~"5.."` beside `code=~"5.."`. No single selector covers both, and a negative form matches the series that lack the label.

Three traps. The app's p95 reads a flat **1s** for anything slower, having four buckets against the Go service's twelve. The `deleteDatasources:` block in `datasource.yaml` is **required, not leftover** — giving a uid to an already-provisioned datasource makes Grafana abort provisioning and never start — and it runs on every boot, so a hand-made dashboard predating the uid loses its datasource. And `jsonData.timeInterval` must track `global.scrape_interval`: `$__rate_interval` is derived from it, not from `prometheus.yml`, and Grafana's silent 15s default floors every rate window at 60s. A test asserts the two agree.

**Readiness.** Both services answer `/health` with `{"status": "ok"}` and both healthchecks probe it. Keep the two bodies identical: a route that exists on both services is what makes the merge observable. The probe traffic lands on an unfiltered handler every ten seconds, so a flat baseline in the dashboard panels comes from the healthchecks rather than from load.

**Observability wiring.** `prometheus.yml` scrapes `app:8002/metrics` under job `fastapi-app` and `service-go:8003/metrics` under job `service-go`, both every 5s. Job names must stay unique — a test asserts it, because Prometheus itself accepts a duplicate and silently folds the second job's series under the first one's label. Don't rename `fastapi-app`: the series already in `prometheus_data` are keyed by it. Grafana auto-provisions its datasource and `grafana/dashboards/services.json` from `grafana/provisioning/`.

## Testing conventions

- `tests/conftest.py` provides `client`, `test_settings` and `repo_root` — the last is session-scoped and returns the repository root, for tests that read files rather than call code.
- One test file per module (`test_config.py`, `test_example.py`, `test_health.py`, `test_main.py`, `test_load.py`, `test_load_driver.py`), asserting exact status code + JSON body.
- The Go tests live beside the source in `service-go/main_test.go`, not under `tests/`, and run from `go test` rather than from pytest — the coverage gate never sees them.
- Four files break that rule on purpose: `test_compose_config.py`, `test_prometheus_config.py`, `test_grafana_provisioning.py` and `test_docs_versions.py` have no Python module behind them — they parse `docker-compose.yml`, `prometheus.yml`, the provisioned Grafana files, and the image versions quoted in `CLAUDE.md` and `README.md`. See "Infra checks" for what they do and do not cover.
- Async worker tests use `pytest-asyncio` with `unittest.mock.AsyncMock`/`patch` to mock `httpx.AsyncClient.get` (both success and exception paths) and `monkeypatch` to run `main(cycles=1)` instead of an infinite loop — follow this pattern rather than making real network calls in tests.

## Feature specs & plans

Feature documentation lives in `specs/<CU-code>/` — one folder per ClickUp ticket, holding exactly two files:

- `spec.md` — the what and the why: summary, objective, scope (in/out), expected behaviour, acceptance criteria, status (`Draft` / `Approved`).
- `plan.md` — the how: context, facts verified against the repo, affected files, tasks, edge cases, verification steps. Links back to `./spec.md`.

`<CU-code>` is the ticket code alone (e.g. `CU-86bb2m2t2`), taken from the branch name `feat/<CU-code>-<slug>` — the descriptive slug belongs in the document title, not in the folder name. The two files cross-link with sibling relative links (`./spec.md`, `./plan.md`). Nothing reads these files automatically, so follow the convention by hand when starting a new feature.
