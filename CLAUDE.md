# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A demo/learning project showing observability with Prometheus + Grafana across **three** services in different languages. The `app` service is a small FastAPI API instrumented via `prometheus-fastapi-instrumentator`; `service-go` is a small Go program instrumented via `prometheus/client_golang`, and it exists to test the claim that the stack attaches to something that is not the FastAPI app; `service-node` is a small Node program instrumented via `prom-client`, and it exists to prove a service joins by declaring container labels, with no edit to `prometheus.yml`. The `loadgen` service is a standalone async script that continuously hits every service's `/load/*` endpoints purely to generate metrics traffic for the Grafana dashboards. There is no database and no task queue (Celery/RQ) — "worker" here means load generator, not background job processor.

## Stack & versions

`requirements/base.txt` / `requirements/dev.txt` (compiled from `base.in`/`dev.in`) are the source of truth for what gets installed — tox and Docker both install from them. `pyproject.toml`'s `[tool.poetry]` ranges are kept aligned by hand; if you bump a version in one place, update the other too, because nothing enforces it.

What those files don't tell you:

- Python 3.11 — `python:3.11.15` base image, tox `py311`.
- Prometheus `prom/prometheus:v3.13.2`, Grafana `grafana/grafana:12.4.7`. Every image reference is pinned to an exact patch version, and `tests/test_compose_config.py` rejects anything looser, including a floating minor, a two-component `<repository>:<major>.<minor>`. A Prometheus bump is one line in `docker-compose.yml` — the `infra` job derives the tag from there rather than repeating it — but every copy of a tag in this file and `README.md` has to move with it, and `tests/test_docs_versions.py` fails and names the file when one does not.
- Node 24 (`service-node/package.json`) with `prom-client`, on `node:24.20.0`.
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

### Node service

```bash
cd service-node
npm ci           # installs exactly package-lock.json, and fails if it drifted
npm test         # node --test, ~2s: the two load routes run concurrently
```

Its own CI job, for the reason the Go one has one: `tox` never sees it. The job reads the version from `engines.node` in `package.json` rather than naming it, the way the Go job reads `go.mod`.

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

The four test files ride along in the normal `tox -e py311` run and need no Docker. Three of them are purely **structural** — the configuration files parse and carry the fields the stack depends on. `tests/test_grafana_provisioning.py` goes further: since the dashboard rebuild it also asserts panel types, unique panel ids, non-overlapping `gridPos`, `refId` unique within each panel, datasource references by uid, the `job` variable, and that no scrape job name appears in any query — the names it forbids read from the `prometheus.io/job` labels in `docker-compose.yml`, since `prometheus.yml` no longer names a service. What none of them do is prove that a query returned data or that a panel drew — only a browser answers that, so don't read a green run as a dashboard review.

`tests/test_compose_config.py` reaches every Dockerfile in the repo through `rglob`, but not equally: the base-image pinning rule applies to all of them (bare `major.minor.patch` only — every suffixed tag, an `-alpine` or `-slim` variant included, is rejected, and so are `scratch` and distroless), while the rule that installed packages are pinned understands `pip` and `npm`, so a Dockerfile in a third language passes it **vacuously**. For `service-go` what stands in for it is `go.sum` — a hash per module, stronger than pip's `==` — plus the assertion that both `go.mod` and `go.sum` exist and are non-empty. That guarantee is why the image resolves dependencies through `go mod download`; a `go install pkg@latest` would escape every check here. For `service-node` the same role is played by `package-lock.json` and `npm ci`, asserted the same way: `npm ci` installs exactly the lockfile and fails when the two have drifted, and a plain `npm install` fails the test. What follows the pin separator has to be a version — `express@latest` and `express@^5.0.0` are rejected alongside a bare `express`. Every one of these readers greps the instructions with the comments stripped — prose about an install command reads exactly like the command — and every `Dockerfile` walk skips `node_modules`, which exists after a local `npm ci` and never in CI. `tests/test_docs_versions.py` sees this service now: its `pinned_images` fixture reads the `FROM` of every `Dockerfile` alongside the compose `image:` keys, so a base tag bumped without the prose fails. It maps a repository to the **set** of tags the stack gives it and asserts that set has one member, because `Dockerfile` and `worker/Dockerfile` both pin `python` and a single mapping would let the last file read win. The repositories it matches are bare names now, so the scan anchors on a left boundary: without it, `service-node:8004` in prose reads as a `node` image on tag `8004`.

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

**The second and third services.** `service-go/` is flat on purpose — `main.go`, `main_test.go`, `go.mod`, `go.sum`, `Dockerfile`, no `cmd/` and no packages — and listens on **8003**. It serves `/health`, `/load/io-bound`, `/load/cpu-bound` and `/metrics`, reads no environment, and is called by nothing but the load generator. It deliberately mirrors the app's paths and deliberately does **not** mirror its metric labels: it exports what `client_golang` gives it (`code`/`method`, lowercase verb) rather than the instrumentator's `handler`/`status`. Ten metric names are exported by both the app and the Go service, six of them `process_*` — including `process_cpu_seconds_total` and `process_resident_memory_bytes`, the two the dashboard's resource panels query — separated only by `job` and `instance`. That collision is the point of the service, not a defect to fix here; the full series list is in `specs/CU-86bbdrkm7/plan.md`.

`service-node/` is flat for the same reason — `main.js`, `main.test.js`, `package.json`, `package-lock.json`, `Dockerfile`, no framework — and listens on **8004**. It mirrors the same paths and carries a **third** label convention, `route`/`status_code`/`method`, because `prom-client` does not instrument HTTP and leaves the names to the author. Two consequences of Node being single-threaded are written into the service: `/load/cpu-bound` burns to a **clock**, not to an iteration count, because a fixed count blocks `/health` for however long the machine takes while the healthcheck timeout does not stretch with it; and a request is counted on `close` as well as `finish`, under status 499, so one the client abandons is not lost from the graphs. Do not rename them to `handler` or `code`: three live conventions is what this service is for, and the cost of them is measured, not guessed:

| Panel | Reaches `service-node`? |
| --- | --- |
| *Targets up*, *CPU by service*, *Resident memory*, *Throughput by service* | Yes |
| *5xx / 4xx error rate* | No — the two targets select `status` and `code` |
| Rows *Routes (`handler`)* and *Requests (`code`)* | No |

Measured against the running stack in `specs/CU-86bbpx4by/plan.md`, which also records the cost in series. Two details from that measurement are worth carrying: a series with **no** `handler` label matches `handler!="/metrics"`, which is why the Node service reaches the throughput panel at all; and the 4xx panel draws the app alone, because the Go service does not instrument its unmatched handler and so counts no 404 anywhere.

**The dashboard.** `grafana/dashboards/services.json` — `Services Overview`, uid `services-overview` — is fourteen panels in three rows: *Services* groups by `job`; *Routes (`handler`)* and *Requests (`code`)* each hold whichever services carry that label. Three rules, all asserted by `tests/test_grafana_provisioning.py`:

- **`job` goes inside every bucket grouping.** The app publishes four `le` bounds and the Go service twelve, the app's four being a subset — so a `by (le, …)` without `job` produces bounds the app never reports, and every bucket below `0.1` counts one service only.
- **A convention row selects on label presence — `handler!=""`, `code!=""` — never on a job name.** Not cosmetic: `handler=~".*"` also matches series carrying no `handler`, collapsing a whole service into one unlabelled group.
- **An error panel carries one target per convention**, `status=~"5.."` beside `code=~"5.."`. No single selector covers both, and a negative form matches the series that lack the label.

Three traps. The app's p95 reads a flat **1s** for anything slower, having four buckets against the Go service's twelve. The `deleteDatasources:` block in `datasource.yaml` is **required, not leftover** — giving a uid to an already-provisioned datasource makes Grafana abort provisioning and never start — and it runs on every boot, so a hand-made dashboard predating the uid loses its datasource. And `jsonData.timeInterval` must track `global.scrape_interval`: `$__rate_interval` is derived from it, not from `prometheus.yml`, and Grafana's silent 15s default floors every rate window at 60s. A test asserts the two agree.

**Readiness.** All three services answer `/health` with `{"status": "ok"}` and every healthcheck probes it. Keep the bodies identical: a route that exists on all three is what makes the merge observable. The Node probe runs `node -e` rather than `wget`, so it depends on the runtime in the image rather than on what the base image happens to ship — the coupling `service-go` has to BusyBox, not repeated. The probe traffic lands on an unfiltered handler every ten seconds, so a flat baseline in the dashboard panels comes from the healthchecks rather than from load.

**Observability wiring.** `prometheus.yml` declares **one** job, `docker-labels`, which discovers its targets from the Docker socket every 15s and scrapes them every 5s. No address is written in that file. A service joins the scrape from its own compose block, by declaring four labels and nothing else:

| Label | Contract |
| --- | --- |
| `prometheus.io/scrape` | `"true"`, or a `keep` rule discards the container — Prometheus and Grafana included |
| `prometheus.io/job` | the value the `job` label takes |
| `prometheus.io/port` | the port the process listens on, not necessarily one it publishes |
| `prometheus.io/path` | optional, `/metrics` when absent |

A container declaring `scrape` without `job` or `port` is **dropped**, not scraped with a default. A `replace` rule deletes the label it targets when the value is empty, so such a target would carry no `job` at all — scraped, stored and invisible to a dashboard that groups by it. Discovery is also filtered to this compose project: the socket lists every container on the machine, and `prometheus.io/scrape` is a convention other stacks use too. That filter names the project, so renaming the directory or setting `COMPOSE_PROJECT_NAME` means editing it — a test compares it against the directory name.

**`job` and `instance` cannot change**, which is what the last two labels are for. The series in `prometheus_data` are keyed by both, so deriving `job` from the compose service name would rename `fastapi-app`, and letting `instance` become the container IP would re-key every series on each recreate. Instead `job` is copied from `prometheus.io/job` and `__address__` is rebuilt as `<compose service>:<port>` — which also collapses a container's several candidate targets into one. Don't rename `fastapi-app`, and don't let two services claim the same `prometheus.io/job`: `tests/test_compose_config.py` asserts uniqueness there now, because Prometheus folds the second one's series under the first one's label without complaining.

One behaviour is lost against the old `static_configs`: a stopped service leaves the target list rather than reporting `up=0`, so the `Targets up` panel loses the line instead of drawing a zero. That is inherent to discovery, not a defect.

**The Docker socket.** Prometheus mounts `/var/run/docker.sock` and reads it through `group_add: ["${DOCKER_GID:-983}"]`, staying `nobody`. **The `983` default is this machine's group id, and a wrong one fails quietly**: `/-/healthy` says nothing about discovery, so the container reports `healthy` while finding zero targets and every panel goes empty — the only signal is a `permission denied` line in the Prometheus log. `README.md` tells the reader to export `DOCKER_GID`; keep that instruction alive. `user: root` also works and is a one-way door — `prometheus_data` belongs to `nobody`, and files written as root are not readable again after a revert. The inline GID default is required: no `.env` exists, and CI would resolve the variable empty. And `:ro` is not a security boundary: it protects the file node, not the API, so whoever reads that socket enumerates every container on the host. Accepted because the stack is local; the real answer is a proxy container.

Grafana auto-provisions its datasource and `grafana/dashboards/services.json` from `grafana/provisioning/`.

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
