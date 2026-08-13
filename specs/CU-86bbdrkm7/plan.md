# CU-86bbdrkm7 — 02a build second service (plan)

Spec: [./spec.md](./spec.md)

## Context

This lands as one new top-level directory plus edits spread thin across everything that already
describes the stack. `service-go/` is new — five files, no package layout. `docker-compose.yml`
gains a fifth service and both existing healthchecks change their probe. `prometheus.yml` gains a
second scrape job. `app/` gains one endpoint module and one router registration.
`worker/load_driver.py` gains three URLs and `loadgen` a second dependency. Three test files that
already exist grow assertions, one new test file appears for the new FastAPI route, the CI workflow
gains a third job, and both Markdown documents stop describing a four-service stack.

The design comes from `~/.claude/plans/url-observability/02a_segundo-servico-go.md`, written
2026-08-11 against the repository, which is where the roadmap's F2 was split into F2.1 (this
feature) and F2.2 (the dashboard rebuild). Three earlier consequences come due here, because this is
the first feature to add a service: readiness is measured from Docker's own timestamps and never
from wall-clock around `up -d`; every documented lifecycle command carries `--profile`, teardown
included; and anything declaring `depends_on: grafana` inherits its ninety-second wait, which is why
the new service declares no such thing.

The deliverable that decides whether this feature succeeded is not code. It is the list of series
the Go service actually exports — names and labels — recorded below under Verification steps, and
read by the dashboard rebuild that follows.

Each task below is its own commit, and the task's checkbox is ticked in that same commit.

## Facts verified against the repo

Measured 2026-08-13 on this branch, unless marked otherwise. Docker **29.7.2** / Compose **v5.4.0**
— both newer than the 29.7.1 / v5.3.1 the previous two features measured on, so any behaviour those
plans recorded about profiles is worth watching rather than assuming.

- **`assert_pinned` rejects every suffixed tag, re-run against nine candidates.** Passing:
  `golang:1.26.5`, `alpine:3.24.1`. Failing: `golang:1.26.5-alpine3.22`, `golang:1.25-alpine`,
  `golang:1.26.5-bookworm`, `alpine:3.24` (two components), `debian:12.9` (two components),
  `gcr.io/distroless/static:nonroot`, and a bare `scratch` (no `:` at all). The multi-stage build is
  therefore limited to bare `major.minor.patch` tags, and the final stage cannot be distroless or
  scratch without rewriting the test.
- **The `FROM` regex already handles multi-stage.** `^FROM\s+(\S+)` over a two-stage Dockerfile
  returns `['golang:1.26.5', 'alpine:3.24.1']` — `AS build` is not captured and `COPY --from=build`
  does not match. No change to `test_every_dockerfile_base_image_is_pinned` is needed.
- **Dockerfile discovery is `rglob("Dockerfile")`** in `tests/test_compose_config.py:44`, so
  `service-go/Dockerfile` inherits both pinning rules without anyone listing it.
- **`installed_packages` yields nothing for a Go Dockerfile.** Run against the exact two-stage file
  this feature will write, it returns `[]` — `PIP_INSTALL` is `\bpip\d?\s+install\b` and matches
  nothing there. `test_every_dockerfile_pins_what_it_installs` therefore passes **vacuously**, which
  is the hole the roadmap assigned to this feature.
- **`tests/test_docs_versions.py` cannot reach this service.** Its `compose_images` fixture is built
  from services declaring `image:`; a locally built service declares `build:`. What covers the Go
  image is the `FROM` test, and only that.
- **`prometheus.yml` has exactly one job**, `job_name: "fastapi-app"`, `metrics_path: /metrics`,
  target `app:8002`, with `global.scrape_interval: 5s` and the `storage.tsdb.retention` block the
  previous feature moved in. Nothing asserts job-name uniqueness today.
- **`docker-compose.yml` has four services.** `app` probes `/metrics` through
  `python -c "import urllib.request; urllib.request.urlopen(...)"`; `prometheus` and `grafana` probe
  with `wget --spider -q`. `loadgen` depends only on `app` with `condition: service_healthy`.
  `grafana` carries `start_period: 90s`, `prometheus` `10s` with its justification written beside it.
- **The app has no `/health`.** `app/main.py` registers `/`, the `example` router and the `load`
  router under the `/load` prefix; `Instrumentator().instrument(app).expose(app)` provides
  `/metrics`.
- **`worker/load_driver.py` has four URLs**, all `http://app:8002`, fired together every 5 s.
- **The dashboard confirms the collision surface.** Seven panels, all `type: "graph"`; the panels
  `5xx Error Rate by Handler` and `4xx Error Rate by Handler` share `gridPos {x:0, y:24, w:24, h:8}`;
  and one template variable, `handler`, querying
  `label_values(http_requests_total{handler!="/metrics"}, handler)`. If the Go library labels its
  route `handler` on a metric of that name, the new routes join that dropdown unannounced.
- **The suite is at 32 passing tests** (`pytest -q tests/`, 1 warning), which is the baseline the
  negative proofs below are counted against.
- **Adding a fifth service falsifies more prose than the `02a` plan listed.** That plan tracked the
  three sentences counting *four test files* — `README.md:140`, `CLAUDE.md:70` and `CLAUDE.md:109` —
  which stay true as long as new assertions land in existing files. Found today, and about *services*
  rather than test files: `README.md:55` says a full `up` brings up "all four"; `README.md:57-58`
  enumerate what each profile brings up; `README.md:59` names `app`, `prometheus` and `grafana` as
  the three that report `healthy`; `README.md:215` calls `docker-compose.yml` "the four services";
  and `README.md:210` describes `api/endpoints/` as "one module per route group (example, load)".
  Each is made false by a specific task, and is corrected in that task's commit.
- **The local Go is 1.23.2**, older than the build image. With `GOTOOLCHAIN=auto` — the default
  since 1.21 — a `go.mod` requiring a newer toolchain downloads it on first use, so a version error
  locally is a toolchain fetch, not a code problem.
- **`jq` is available on the CI runner** and already used by the `infra` job, so the `go` job needs
  no extra installation step for anything it reads.

Carried from `02a_segundo-servico-go.md`, measured 2026-08-11 and **not** re-measured today:

- Docker Hub carries `golang:1.26.5` and `alpine:3.24.1`. The first `docker compose build` is what
  confirms this; if either tag has moved, the fix is a tag bump inside this feature, not a redesign.
- `alpine:3.24.1` ships `wget` at `/usr/bin/wget` (BusyBox v1.37.0) whose `--help` lists
  `--spider  Only check URL existence: $? is 0 if exists` — the same probe form the Prometheus and
  Grafana healthchecks already use.
- `actions/setup-go@v7` is the current major (v7.0.0, 2026-07-16) and declares `using: node24`, so
  the new job does not reintroduce the deprecation annotation the previous feature removed.
- The provisioned dashboard renders under Grafana 12.4.7 and five of its seven panels draw data —
  read in a browser, which is the only instrument that answers that question.

## Affected files

| File | Change |
| --- | --- |
| `service-go/go.mod`, `go.sum` | new — module definition and committed checksums |
| `service-go/main.go` | new — four routes, default registry, port 8003 |
| `service-go/main_test.go` | new — the three application routes plus `/metrics` responding |
| `service-go/Dockerfile` | new — multi-stage `golang:1.26.5` → `alpine:3.24.1`, `CGO_ENABLED=0` |
| `app/api/endpoints/health.py` | new — `/health` route with its own `router` |
| `app/main.py` | registers the health router |
| `docker-compose.yml` | the `service-go` block; both healthchecks move to `/health`; `loadgen` waits on both services |
| `prometheus.yml` | second scrape job, `service-go` → `service-go:8003` |
| `worker/load_driver.py` | three Go routes added to `URLS` |
| `tests/test_health.py` | new — the FastAPI `/health` route |
| `tests/test_compose_config.py` | `CORE_SERVICES` grows; Go modules must be committed; the pip parser's docstring states its limit |
| `tests/test_prometheus_config.py` | `job_name` asserted unique across jobs |
| `tests/test_load_driver.py` | follows the longer `URLS` |
| `.github/workflows/python-app.yml` | new `go` job — `gofmt -l`, `go vet`, `go test` |
| `CLAUDE.md` | architecture, commands, the new directory and port, what the pinning tests cover without `pip` |
| `README.md` | stack, ports, profile table, project layout, the endpoints the Go service serves |

## Tasks

One commit per task; the checkbox is ticked in the same commit. Any sentence in `CLAUDE.md` or
`README.md` that a task makes false is corrected inside that task's commit — the two documentation
tasks at the end add what is new, they do not repair what earlier tasks broke.

- [x] **Write the Go service.** `go.mod`, `go.sum`, and `main.go` with `/health`,
      `/load/io-bound` (a sleep), `/load/cpu-bound` (a busy loop) and `/metrics` from
      `promhttp.Handler()`, listening on 8003 against the default registry. No `cmd/`, no layers, no
      environment variables read.
      Done: **`client_golang` ships no HTTP request metric**, so the request metric names are a
      choice this task had to make rather than inherit — the default registry carries only the
      process and Go runtime collectors plus `promhttp_metric_handler_requests_total`, which measures
      the `/metrics` handler itself. Chosen: `http_requests_total` and
      `http_request_duration_seconds`, labelled `code` and `method` — the labels `promhttp`'s own
      instrumentation helpers fill in. **No `handler` label**, because adding one would be copying
      the FastAPI instrumentator's choice, which is what the idiomatic-instrumentation decision
      forbids. The consequence is measured rather than assumed: the metric *name* collides with the
      FastAPI one while the label set does not, so the dashboard's `by (handler)` panels will
      collapse every Go route into one unlabelled bucket beside the app's named ones. Also
      measured: `process_cpu_seconds_total` and `process_resident_memory_bytes` come out under
      exactly the names the Python client uses, so the two resource panels collide unconditionally.
      `client_golang` is **v1.24.1** and requires `go 1.25.0`, which `go mod tidy` wrote into
      `go.mod`; the local Go 1.23.2 fetched the 1.25.0 toolchain by itself, as `GOTOOLCHAIN=auto`
      predicted, and the build image at 1.26.5 is comfortably above it. The CPU loop runs two billion
      iterations, not the FastAPI equivalent's ten million: measured here, Python takes 0.79s for ten
      million and Go 0.62s for two billion, so the two routes cost about the same wall time.
      `.gitignore` gains one line — `go build` inside the directory writes a 12 MB binary named after
      it, and that came within one `git add` of being committed.
      Commit: `feat(service-go): add a minimal instrumented go service`
- [ ] **Test the handlers.** `main_test.go` covering the three application routes' status and body
      and that `/metrics` responds, using `net/http/httptest`.
      Commit: `test(service-go): cover the handlers`
- [ ] **Build it reproducibly.** `service-go/Dockerfile`, two stages, bare tags, `CGO_ENABLED=0`,
      dependencies through `go mod download` and never `go install`.
      Commit: `build(service-go): add a pinned multi-stage image`
- [ ] **Cover what the pip parser cannot.** In `tests/test_compose_config.py`, assert that every
      directory holding a Dockerfile whose `FROM` names `golang` carries a non-empty `go.mod` and
      `go.sum`; and rewrite `installed_packages`' docstring to say it recognises `pip` only, that a
      Dockerfile in another language passes it vacuously, and what stands in for the guarantee.
      Commit: `test(infra): require committed go module checksums`
- [ ] **Add the service to the compose file.** Profiles `["core", "load"]`, port 8003,
      `restart: unless-stopped`, healthcheck `wget --spider -q http://localhost:8003/health`, and a
      `start_period` taken from the measurement described in Verification steps, with the reasoning
      written beside the value the way the Prometheus one is. No `depends_on: grafana`. Correct
      `README.md`'s profile table, its "all four", its list of services reporting `healthy` and its
      project-layout comment in this same commit.
      Commit: `feat(compose): add the go service`
- [ ] **Scrape it.** A second job in `prometheus.yml` — `job_name: "service-go"`,
      `metrics_path: /metrics`, target `service-go:8003`. `fastapi-app` keeps its name.
      Commit: `feat(prometheus): scrape the go service`
- [ ] **Assert both.** `CORE_SERVICES` in `tests/test_compose_config.py` grows to include
      `service-go`; `tests/test_prometheus_config.py` gains a test that job names are unique across
      `scrape_configs`.
      Commit: `test(infra): assert the second service and scrape job`
- [ ] **Give the app a health route.** `app/api/endpoints/health.py` exporting `router`, registered
      in `app/main.py`, with `tests/test_health.py` asserting the exact status code and JSON body.
      Correct `README.md`'s "one module per route group (example, load)" here.
      Commit: `feat(app): add a health route`
- [ ] **Move both probes onto it.** The `app` healthcheck stops requesting `/metrics` and both
      services probe `/health`.
      Commit: `refactor(compose): probe readiness through the health route`
- [ ] **Drive the new service.** Add the Go service's three routes to `URLS`, make `loadgen` depend
      on both services with `condition: service_healthy`, and extend `tests/test_load_driver.py`.
      Commit: `feat(loadgen): drive the go service too`
- [ ] **Check the Go code in CI.** A `go` job parallel to `build` and `infra`, on
      `actions/checkout@v7` and `actions/setup-go@v7`, running `gofmt -l .` (failing if it prints
      anything), `go vet ./...` and `go test ./...` from `service-go/`.
      Commit: `ci: vet, format-check and test the go service`
- [ ] **Record the series.** Capture the Go service's `/metrics` whole and transcribe its request
      and process series into this file — name, labels, and the command that produced them. No code.
      Commit: `docs(specs): record the series the go service exports`
- [ ] **Document it in `CLAUDE.md`.** Two-service architecture, the `service-go/` directory and its
      port, the `go` job and how to run it locally, and what the pinning tests do and do not cover
      for a Dockerfile without `pip`. Conclusions only — the derivation stays here.
      Commit: `docs: document the go service`
- [ ] **Update `README.md`.** Stack list, the service/URL table, the endpoint table, and whatever the
      earlier tasks left approximate rather than false.
      Commit: `docs: update the readme for the second service`
- [ ] **Run the verification script and record every outcome below.** No commit beyond the tick.

## Edge cases

- **`CGO_ENABLED=0` is not an optimisation, it is what makes the binary run.** `golang:1.26.5` is
  Debian with glibc and `alpine:3.24.1` is musl. A binary built with cgo enabled dies in the final
  stage with a loader error, and the symptom appears at `docker compose up`, not at `go build`. The
  obvious alternative — a Debian final stage — is blocked by `assert_pinned`, which rejects
  `debian:12.9` for having two version components.
- **The suffixed tags are forbidden by the test, not by taste.** Measured above against nine
  candidates. Whoever later swaps the runtime image for an `-alpine` variant will see the test fail
  and may read it as a bug; it is written here that it is not.
- **The pip pinning test passes vacuously on the Go Dockerfile, and that is accepted in writing.**
  What replaces the guarantee is `go.sum` — a cryptographic hash per module, stronger than pip's
  `==` — plus the new assertion that it exists and is committed. A `go install pkg@latest` in the
  Dockerfile would escape both, which is why the design uses `go mod download` and the task says so.
- **`start_period` is measured from Docker's own timestamps.** Read `.State.StartedAt` against the
  readiness log line or `.State.Health.Log[].Start`. Timing the wall clock around `up -d` measures
  nothing: under `depends_on: condition: service_healthy` that command returns only after health has
  already been reached. And the ~5 s before the first probe is Docker's `--health-start-interval`
  cadence, not initialisation — no value of `start_period` changes that number.
- **Under `service_healthy`, a short `start_period` fails the whole `up`.** `loadgen` will wait on
  two services; if the Go one is set too tight, the failure is not a misleading `ps` line, it is the
  `up` aborting. This is what raised Grafana from 10 s to 90 s in the first feature.
- **`--profile` belongs on every subcommand, teardown included.** Without it `down`, `stop` and
  `logs` are silent no-ops that exit 0 while leaving the stack running; `ps` is the exception, which
  is exactly what makes the ineffective command look like a hang. Measured under Compose v5.3.1 and
  worth re-confirming on the v5.4.0 this branch runs.
- **The collision can hide by working.** If both services label the route with the same label name,
  the series add up with no error at all. The verification has to read the *list of series*, not the
  chart — a chart with one line is the symptom, and it is indistinguishable from a correct chart.
- **The root `Dockerfile` will copy `service-go/` into the app image.** `COPY . .` with no
  `.dockerignore`. It already carries `worker/`, `grafana/` and `tests/`; this breaks nothing and
  creating a `.dockerignore` is a larger change than this feature.
- **`/health` in `URLS` is asymmetric on purpose.** The list grows from four to seven — the Go
  service's three routes — and the FastAPI `/health` is deliberately left out: its own healthcheck
  already drives it every ten seconds, so the collision has samples on both sides without the load
  list duplicating a probe. Three of the seven now hit CPU-bound endpoints, and the first feature
  recorded that machine load is what makes Grafana's cold boot vary between 35 s and 55 s.
- **Moving the probe changes what readiness means.** `/metrics` proved the instrumentator came up;
  `/health` proves the router came up. Both are adequate and symmetry between the two services is
  what decides — but it is a trade, not a detail.
- **Moving the probe also changes what the dashboard draws.** Every query and the template variable
  filter `handler!="/metrics"`, so the old probe traffic was invisible by design. Probing `/health`
  moves that traffic onto an unfiltered handler, on both services, every ten seconds: five panels
  gain a constant baseline that comes from a probe rather than from load. Accepted in the spec, and
  repeated here because whoever sees the new flat line will not otherwise know where it came from.
- **The local Go is 1.23.2 and the image is 1.26.5.** `GOTOOLCHAIN=auto` downloads what `go.mod`
  requires on first use. Worth knowing before reading a version error as a code problem.
- **Compose is v5.4.0 here, not the v5.3.1 the profile behaviour was measured on.** Nothing in this
  feature depends on that behaviour changing, but the verification script exercises `--profile '*'`
  on the new service anyway, so a regression would surface rather than be assumed away.
- **The tag bump is the planned exit if an image tag has moved.** `golang:1.26.5` and
  `alpine:3.24.1` were confirmed on Docker Hub on 2026-08-11 and not re-checked today. If the first
  build fails to pull, the fix is a newer bare `major.minor.patch` tag inside this feature — not a
  change of base image family, which would re-open the `wget` decision.
- **Markdownlint.** The `CLAUDE.md` and `README.md` edits go through the VS Code Problems panel:
  compact tables (`MD060`), blank lines around lists and fences.

## Verification steps

To be run against the finished branch; each step records its measured outcome here.

- `tox` end to end — `py311` with the new tests, `lint`, `safety`.
- `gofmt -l service-go` prints nothing; `go vet ./...` and `go test ./...` pass from inside
  `service-go/`.
- `docker compose --profile '*' config -q` exits clean and `config --services` resolves **five**
  services, so the first command was not validating an empty file.
- `promtool check config` reports `SUCCESS`, through the image derived from the compose file the way
  the `infra` job derives it.
- `docker compose --profile core --profile load up --build -d`; `docker compose ps` shows `app`,
  `service-go`, `prometheus` and `grafana` as `healthy`, and the `up` does not fail on a dependency
  condition.
- **`start_period` measured for the Go service** from `.State.StartedAt` against the readiness log
  line or `.State.Health.Log[].Start` — never from wall-clock around `up -d`. Record the observed
  readiness time, the time of the first probe, and the value chosen in `docker-compose.yml`.
- `curl -s localhost:9090/api/v1/targets` shows both targets with `health: "up"`.
- `curl -s 'localhost:9090/api/v1/label/job/values'` returns both job names, `fastapi-app` among
  them.
- **The deliverable:** `curl -s localhost:8003/metrics` captured whole, with the request and process
  series transcribed here — every name, every label. Specifically, whether
  `process_cpu_seconds_total` and `process_resident_memory_bytes` appear under the same names the
  Python client uses (which would let the dashboard rebuild keep one resource panel per resource,
  once it adds `by (job, instance)`), and whether the route label is called `handler` (which would
  make the merge worse, not better).
- **Proof of the collision:** a query over the `/health` route without `by (job)` returns the two
  services' series merged; the same query with `by (job)` separates them. Both queries and both
  outputs recorded.
- **Then on screen:** with the stack up, open the dashboard in a browser and record whether the Go
  service appeared unannounced in the existing panels and in the `handler` dropdown, and whether the
  new probe baseline is visible. This does **not** replace the series list — it is the cheapest read
  of the defect and it costs an `up` that already happened.
- **Negative proof, pinning:** replace the final-stage tag with a suffixed variant, confirm
  `tests/test_compose_config.py` fails, revert, confirm green.
- **Negative proof, `go.sum`:** delete `service-go/go.sum`, confirm **exactly one** test fails
  against the 32-test baseline plus this feature's additions, restore.
- A CI run on the branch with all three jobs green and no Node deprecation annotation.
- `git diff --stat main...HEAD` names only the files in Affected files, plus this ticket's two
  documents.
- `git show --stat HEAD` at each commit names only that task's files.
