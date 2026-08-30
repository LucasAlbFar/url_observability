# FastAPI Observability Demo

Three small services — one FastAPI, one Go, one Node — instrumented end-to-end with **Prometheus** and **Grafana**, paired with a synthetic load generator so the dashboards always have real traffic to show. No database, no task queue — this project is purely a hands-on observability playground.

## How it works

- **`app`** — a FastAPI service (`app/main.py`) instrumented via `prometheus-fastapi-instrumentator`, which exposes a `/metrics` endpoint.
- **`service-go`** — a small Go service (`service-go/main.go`) instrumented via `prometheus/client_golang`. It exists to test the claim the stack is language-agnostic, so it mirrors the app's paths and keeps its own library's metric labels (`code`/`method`, not `handler`/`status`) instead of imitating them. Ten metric names end up exported by both it and the app, separated only by the `job` label.
- **`service-node`** — a small Node service (`service-node/main.js`) instrumented via `prom-client`. It exists to prove a service joins the observability stack by declaring labels on its own container, with no edit to `prometheus.yml` — it was added that way. Its labels are a third convention again (`route`/`status_code`/`method`), because `prom-client` does not instrument HTTP and leaves the naming to whoever writes the middleware.
- **`loadgen`** — a standalone async script (`worker/load_driver.py`) that continuously calls every service's `/load/*` endpoints over HTTP, purely to generate traffic for the metrics/dashboards.
- **`prometheus`** — finds what to scrape by reading the Docker socket every 15s, and scrapes whatever it finds every 5s. No address is written down: a service opts in with labels in its own compose block (see [Joining the scrape](#joining-the-scrape)). The scrape interval and the retention window (7 days, capped at 512 MB) live in `prometheus.yml`; the container's command line only points it at that file and at the volume its TSDB writes to.
- **`grafana`** — auto-provisioned with a Prometheus datasource and a ready-made "Services Overview" dashboard. Fourteen panels in three rows: *Services* compares the two side by side (targets up, throughput, CPU, resident memory, 4xx/5xx), and *Routes* and *Requests* each hold whichever services use that label convention — routes for the app, response codes for the Go service. Two dropdowns sit at the top: `Service` filters every panel on the dashboard, and `Route` narrows the *Routes* row to particular endpoints.

The `/load/*` endpoints each stress a different resource on purpose, so the dashboard has something to plot. On the FastAPI app (`:8002`):

| Endpoint | What it does | Dashboard panel it feeds |
| --- | --- | --- |
| `GET /health` | Returns `{"status": "ok"}` — what the healthcheck probes | Throughput by route — the flat 10s baseline |
| `GET /load/io-bound` | `asyncio.sleep(2)` | p95 by route |
| `GET /load/cpu-bound` | Blocking CPU-heavy loop | CPU by service |
| `GET /load/stress/{seconds}` | Blocking busy-wait for N seconds | CPU by service |
| `GET /load/memory-spike` | Allocates a large in-memory list | Resident memory |

The Go service (`:8003`) and the Node service (`:8004`) serve the same three paths, deliberately — a route that exists on all three is what makes their series merge visible:

| Endpoint | What it does |
| --- | --- |
| `GET /health` | Returns the same `{"status": "ok"}` body the app does |
| `GET /load/io-bound` | Sleeps 2s |
| `GET /load/cpu-bound` | Spins for roughly as long as the FastAPI one takes |

**Three services, three label conventions, on purpose.** Each one emits what its own library gives it, and nothing is renamed to make a panel light up. The dashboard's *Services* row groups by `job` and draws all three; its *Routes* and *Requests* rows each hold whichever services carry that label, so the Node service appears in neither. That is the measured cost of a new convention rather than a defect — it is recorded in `specs/CU-86bbpx4by/plan.md`.

### Joining the scrape

A service is scraped because it says so, not because someone edited `prometheus.yml`. Four labels in its own compose block are the whole contract:

```yaml
services:
  my-service:
    labels:
      prometheus.io/scrape: "true"    # required: without it the container is ignored
      prometheus.io/job: "my-service" # the value the job label takes
      prometheus.io/port: "8004"      # the port the process listens on
      prometheus.io/path: "/metrics"  # optional, and already the default
```

Start the container and its target appears within 15s; stop it and the target goes away. Nothing else changes — no configuration edit, no Prometheus restart. Declaring `scrape` without `job` or `port` is not a half-measure: the container is dropped rather than scraped under a broken identity, and the test suite fails the compose file.

Discovery is scoped to this compose project. The socket lists every container on the machine, and `prometheus.io/scrape` is a convention other stacks use too, so a filter on the project label keeps a neighbouring stack's containers out. Rename the project directory, or set `COMPOSE_PROJECT_NAME`, and that filter needs the new name — a test compares the two for you.

Two things are worth knowing. `prometheus.io/job` is a value the metrics history is keyed by, so two services must not claim the same one and an existing one must not be renamed — `app` stays `fastapi-app`. And a service that is not running has no target at all, rather than a target reporting `up=0`: a stopped service disappears from the *Targets up* panel instead of drawing a zero.

Reading the Docker socket is what makes this work, and it is why the `prometheus` service mounts `/var/run/docker.sock` and joins the `docker` group. Read-only protects the file, not the API — anything that reads that socket can enumerate every container on the machine. Fine for a local playground; not something to copy into a shared host.

## Stack

- Python 3.11
- Go 1.25 with `prometheus/client_golang`, built by `golang:1.26.5` and run on `alpine:3.24.1`
- Node 24 with `prom-client`, on `node:24.20.0`
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
export DOCKER_GID=$(getent group docker | cut -d: -f3)   # see below
docker compose --profile core --profile load up --build
```

**`DOCKER_GID` is worth exporting once per shell.** Prometheus finds its targets by reading `/var/run/docker.sock`, which is mode `660` and owned by the `docker` group, and it runs as `nobody` — so it needs that group id. The compose file defaults to `983`, which is this machine's; Debian and Ubuntu usually hand out `999`. Getting it wrong fails **quietly**: the container still reports `healthy`, because `/-/healthy` says nothing about discovery, and the only symptom is that Prometheus finds zero targets and every Grafana panel is empty. The reason is in the log, once you look:

```text
level=ERROR ... err="error while listing containers: permission denied
while trying to connect to the docker API at unix:///var/run/docker.sock"
```

| Service | URL |
| --- | --- |
| FastAPI app | <http://localhost:8002> |
| Go service | <http://localhost:8003> |
| Prometheus | <http://localhost:9090> |
| Grafana | <http://localhost:3000> (login: `admin` / `admin`) |

**Every service sits behind a profile, so `--profile` is required on every `docker compose` command** — teardown included. Without it most subcommands do nothing at all: `up` starts nothing, and `down`, `stop`, `start` and `logs` print nothing and exit `0` while leaving the containers untouched. Only `build` warns (`No services to build`), and only `ps` ignores profiles and lists the containers anyway — which is what makes a bare `down` look like it hung rather than like it did nothing. Use `--profile '*'` for anything acting on the whole stack, or export `COMPOSE_PROFILES=core,load` once per shell.

Pick the group you need:

| Command | Brings up | Use it for |
| --- | --- | --- |
| `docker compose --profile core up -d` | `app`, `service-go`, `service-node`, `prometheus`, `grafana` | dashboards, without synthetic traffic |
| `docker compose --profile load up -d` | `app`, `service-go`, `service-node`, `loadgen` | exercising the APIs, without the observability side |
| `docker compose --profile core --profile load up -d` | all six | the full demo |

The three observed services belong to both profiles on purpose, so `--profile load` boots something worth hitting instead of a generator retrying against nothing.

The first `up` takes a while to go green: Grafana runs its schema migrations against an empty database before opening its HTTP port, so `docker compose ps` can show it as `starting` for the better part of a minute. Every service that publishes a port reports `healthy` once ready, and `loadgen` waits for all three observed services before it starts generating traffic.

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
| `prometheus_data` | the scraped metrics history (`/prometheus`), kept for the retention window set in `prometheus.yml` |
| `grafana_data` | dashboards, users and preferences you created by hand (`/var/lib/grafana`) |

Everything else survives: a `down` without `--volumes` keeps both databases, so the metrics history and any dashboard you built in the UI are still there after the next `up`. The provisioned datasource and the "Services Overview" dashboard are bind-mounted from the repo, and bind-mounted repo files are **never** deleted.

One exception, and it is a one-off: the provisioned datasource gained an explicit `uid` after this stack had already run, so `datasource.yaml` deletes and recreates it on every start. A dashboard you built by hand *before* that change points at the uid Grafana had generated for itself and will come back with its datasource missing — pick `prometheus` again in each panel. Dashboards built from now on are unaffected.

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

`tox` covers the Python side only — the coverage gate, black, isort and flake8 never look at `service-go/` or `service-node/`. Each has its own CI job, and locally:

```bash
cd service-go
gofmt -l .       # prints the files it would rewrite, and still exits 0
go vet ./...
go test ./...
```

```bash
cd service-node
npm ci           # installs exactly package-lock.json, and fails if it drifted
npm test
```

### Infra checks

Four test files validate the stack's configuration rather than any Python module — `docker-compose.yml`, `prometheus.yml`, the provisioned Grafana files, and the image versions this README and `CLAUDE.md` quote. They run inside the normal `tox` and need no Docker. CI additionally validates the same files with the tools that own them:

```bash
docker compose --profile '*' config -q
docker run --rm --entrypoint promtool \
  -v "$PWD/prometheus.yml:/etc/prometheus/prometheus.yml:ro" \
  prom/prometheus:v3.13.2 \
  check config /etc/prometheus/prometheus.yml
```

The `--profile '*'` is load-bearing: without it `config` resolves no services and validates an empty file, exiting `0`.

CI reads the Prometheus image out of `docker-compose.yml` rather than naming it, so it always checks `prometheus.yml` against the version the stack actually runs. Bumping Prometheus is one line in the compose file — the tag written above is a copy-pasteable convenience, and `tests/test_docs_versions.py` fails if it is left behind.

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
  api/endpoints/          # one module per route group (example, health, load)
  core/config.py          # pydantic-settings Settings singleton
service-go/
  main.go                 # the Go service: /health, /load/*, /metrics on :8003
  main_test.go            # its tests — run by `go test`, not by pytest
  go.mod / go.sum         # module definition and committed checksums
service-node/
  main.js                 # the Node service: /health, /load/*, /metrics on :8004
  main.test.js            # its tests — run by `npm test`, not by pytest
  package.json / package-lock.json   # manifest and committed lockfile
worker/
  load_driver.py          # standalone async load generator (calls every service's endpoints)
grafana/                  # provisioned datasource + "Services Overview" dashboard
prometheus.yml            # scrape settings + the label-discovery job
docker-compose.yml        # the six services, their profiles and named volumes
tests/                    # pytest suite: one file per module, plus four that check config
requirements/             # pip-compile sources (base.in/dev.in) and lockfiles (base.txt/dev.txt)
```

For the conventions to follow when changing any of this, see [CLAUDE.md](CLAUDE.md).
