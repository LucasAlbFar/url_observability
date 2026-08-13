# CU-86bbdrkm7 — 02a build second service

Status: Approved

Plan: [./plan.md](./plan.md)

## Summary

Add a second observed service to the stack, deliberately in another language: a small Go program
built on `prometheus/client_golang`, serving `/health`, `/load/io-bound`, `/load/cpu-bound` and
`/metrics` on port 8003. It gets its own scrape job in `prometheus.yml`, its own block in
`docker-compose.yml` with a healthcheck sized against a measurement, and its routes in the load
generator's `URLS`. Three of its routes carry the same paths the FastAPI app serves — on purpose —
and one of those, `/health`, is added to the FastAPI app in the same change, so that both services
answer the same path and both healthchecks probe it. The Go service exports the metric and label
names its own library emits, with no attempt to imitate `handler` and `status`. What those names
and labels actually are is measured against the running service and written down; that record is the
deliverable this feature exists to produce, and the input the dashboard rebuild consumes. This
feature does not fix the dashboard.

## Objective

**The central promise has never been tested.** The project claims the observability stack is
attachable to any service, and every service it has ever observed is the same FastAPI app. A claim
demonstrated on one case is a claim about that case. The second service is what turns it into a
result — and only if the service is allowed to stay itself. That is why it exports idiomatic names:
a proof in which the attached service had to rewrite its instrumentation to fit the dashboard proves
the opposite of what was wanted. The friction this creates is not a side effect to be minimised; it
is evidence, and the feature that unifies the metric model later needs it in hand rather than
assumed.

**A defect is currently hidden by there being one service.** No panel filters by service. The
queries group `by (handler)` and `by (le, handler)`, and the two resource panels group by nothing at
all. The day two services expose a route with the same name, their series merge into one line with
no error, no warning and no visible symptom — the failure mode is a chart that looks right. The
surface is wider than the panels: the dashboard declares a template variable `handler` querying
`label_values(http_requests_total{handler!="/metrics"}, handler)`, so if the second service happened
to use that metric and that label, its routes would join the dropdown as though they belonged to the
first. The compose hardening feature already saw this coming and reserved `/health` for here, giving
the FastAPI healthcheck `/metrics` instead with a note that the route "belongs to F2, where it
becomes the example of collision between services". This is that feature, and the collision is the
thing to demonstrate rather than avoid.

**Doing it later is the most expensive rework available.** Every feature after this one adds
configuration on the assumption of however many services exist when it is written; target discovery,
cardinality limits, traces and logs all inherit that assumption. And the dashboard rebuild cannot go
first: every panel is a PromQL query written against label names, so authoring the JSON before the
Go service exists means authoring it against guessed names. That mistake has a recorded history in
this project — twice a conclusion was drawn from a plausible measurement of the wrong thing — and
this ordering is what avoids a third instance.

## Scope

### In

- **A new `service-go/` directory** holding `go.mod`, `go.sum`, `main.go`, `main_test.go` and a
  `Dockerfile`. Flat: no `cmd/`, no layers. The name is symmetrical with the `service-node/` that
  the target-discovery feature will add, so the pattern is obvious by the third service, and it does
  not suggest a role the service does not have — nothing calls it, and service-to-service traffic is
  a later feature.
- **Four routes on port 8003**: `/health` returning a minimal 200 body, `/load/io-bound` sleeping,
  `/load/cpu-bound` spinning, and `/metrics` served by the library's own handler. The three
  application routes mirror the FastAPI app's paths deliberately — same name, comparable latency —
  because a route that exists on both services is what makes the merge observable. The service reads
  no environment at all, for the same reason the load generator reads none: the list of things any
  code reads should be one list, in one place.
- **Idiomatic instrumentation.** `client_golang` with the default registry, which already carries
  the process and runtime collectors, plus request metrics through the library's own helpers. No
  hand-rolled counters shaped to look like the FastAPI ones. Which names and labels this produces is
  measured against the running service, not assumed by this document.
- **A pinned multi-stage image**, `golang:1.26.5` building and `alpine:3.24.1` running, with
  `CGO_ENABLED=0`. Both tags are bare because `assert_pinned` in `tests/test_compose_config.py`
  requires an exact `major.minor.patch` after the last colon, which rules out every suffixed variant
  — measured 2026-08-11, and recorded so the next reader knows the constraint comes from the test
  rather than from taste. Alpine specifically, because it ships BusyBox `wget --spider`, the same
  probe the existing healthchecks use.
- **A compose block in the shape of the existing ones**: profiles `["core", "load"]`, for the same
  reason the app declares both — `--profile load` has to be bootable on its own — plus
  `restart: unless-stopped` and a healthcheck on `/health`. The `start_period` comes from a
  measurement taken with Docker's own timestamps, not from symmetry with its neighbours. The service
  does not declare `depends_on: grafana`; it would inherit Grafana's ninety-second wait for nothing.
- **A second scrape job in `prometheus.yml`**, named `service-go`, targeting `service-go:8003`,
  written by hand. The existing `fastapi-app` job keeps its name: the job label is what the series
  already in `prometheus_data` are keyed by, and renaming it would split the history at the rename
  for the sake of a symmetry no query needs.
- **A `/health` route on the FastAPI app**, in `app/api/endpoints/health.py` exporting its own
  `router`, registered from `main.py` — the routing pattern `CLAUDE.md` prescribes — with
  `tests/test_health.py` asserting the exact status code and body. This closes the reservation the
  compose-hardening feature wrote down.
- **Both healthchecks switch to `/health`.** The FastAPI probe stops proving that the instrumentator
  came up and starts proving that the router came up; both are adequate, and what decides is that the
  two services then answer readiness the same way. It is a deliberate trade, not a detail.
- **The Go service's routes in `URLS`**, in `worker/load_driver.py` — the only list any code reads —
  and `loadgen` depending on **both** services with `condition: service_healthy`, with
  `tests/test_load_driver.py` following the longer list.
- **New assertions inside test files that already exist**: `CORE_SERVICES` grows to include the new
  service, `job_name` is asserted unique across jobs, and every directory holding a Go `Dockerfile`
  is required to carry a non-empty `go.mod` and `go.sum`. No fifth infrastructure test file, because
  three sentences of prose in `README.md` and `CLAUDE.md` count four of them and would silently
  become false.
- **Written acknowledgement of what the pinning tests do and do not cover here.**
  `test_every_dockerfile_pins_what_it_installs` only understands `pip`, so a Go Dockerfile passes it
  vacuously; `tests/test_docs_versions.py` only maps services declaring `image:`, so a locally built
  service is outside it. What replaces the guarantee is `go.sum`, a cryptographic hash per module,
  plus the new assertion that it is present and committed — which is why the image resolves
  dependencies through `go mod download` and never through `go install`. The docstring of the parser
  says it is pip-only and why.
- **A `go` job in the CI workflow**, parallel to `build` and `infra`, running `gofmt -l`,
  `go vet ./...` and `go test ./...` with `actions/checkout@v7` and `actions/setup-go@v7` — the
  current majors, both on Node 24, so the job does not reintroduce the deprecation annotation the
  previous feature removed.
- **The deliverable that is not code**: the Go service's `/metrics` captured whole, and its request
  and process series transcribed into `plan.md` name by name and label by label, with the command
  that produced them. This is the input the dashboard rebuild is written against.
- **Proof of the collision, by query and on screen.** A metric both services export under the same
  name, queried without and with `by (job)` — merged, then separated. **Amended 2026-08-13, before
  the second task began**, from a query over the `/health` route: `client_golang` ships no HTTP
  request metric at all, so the Go service's request metric names are declared by hand rather than
  inherited, and the idiomatic-instrumentation decision rules out giving them the FastAPI
  instrumentator's `handler` label. A query filtered by `handler="/health"` therefore returns one
  service's series, not two. The collision is real in two other shapes, and those are what get
  proved: `process_cpu_seconds_total` and `process_resident_memory_bytes`, which both client
  libraries export under exactly those names with nothing but `job` and `instance` to separate them;
  and `http_requests_total`, which both export under the same name with different label sets, so a
  panel grouping `by (handler)` shows the app's named routes beside one unlabelled bucket holding
  every Go request. Then the dashboard opened in a browser, recording whether the Go service appeared
  unannounced in the existing panels and in the `handler` dropdown. The screen reading does not
  replace the series list: a chart with one line is exactly the symptom being looked for, and it is
  indistinguishable from a correct chart.
- **`CLAUDE.md` and `README.md` updated** for a two-service stack: the new directory, the port, the
  `go` job, the architecture section, the commands, the project layout, and what the pinning test
  covers and does not cover in a Dockerfile without `pip`.

### Out

- **Every dashboard fix.** The service-selection variable, `rate()` on the CPU panel, the shared
  `gridPos` and duplicated `refId` on the two error-rate panels, the datasource `uid`, rewriting the
  seven panels as `timeseries`, and `by (job, instance)` on the resource panels. They are the whole
  of the next feature, and they are enumerated in the roadmap so none is lost. A test covering them
  could not land here either: it would fail on `main`.
- **The baseline traffic `/health` adds to five panels.** Every dashboard query and the template
  variable filter `handler!="/metrics"` and not `/health`, so moving the probes onto `/health` makes
  a ten-second heartbeat visible on both services where the old probe was invisible by design. This
  is accepted, not overlooked: it breaks nothing, it does not change this feature's design, and it
  contradicts the plain reading that this feature leaves the dashboard alone — it does not fix the
  dashboard and still changes what the dashboard draws. Recorded here so that whoever sees the new
  flat line knows where it came from, and so the next feature treats it as a known input.
- **The mixed-install gap in the pinning parser.** On seeing `-r` the parser discards the whole
  command, so `pip install -r requirements/base.txt gunicorn` passes green. It is real and it is
  recorded against the previous feature; no Dockerfile in this repo mixes the two forms, and fixing
  it here would be unrelated debt riding into a feature about a new service. Extending the parser to
  understand Go is out for a stronger reason: it would be a second, worse verifier of what `go.sum`
  already guarantees.
- **Renaming the `fastapi-app` job.** Symmetric job names do not pay for a break in the recorded
  series. If the dashboard rebuild wants them symmetric, it can make that call with the reauthored
  JSON in hand and pay the cost knowingly.
- **`docker_sd_configs` or any automatic target discovery.** The new job is written by hand on
  purpose; discovery is the next-but-one feature, and it needs two hand-written jobs to replace.
- **A third service, OpenTelemetry, traces, logs, alerting rules and exemplars.** Later features,
  each with its own verification.
- **A `.dockerignore`.** The root `Dockerfile` does `COPY . .`, so the app image will now also carry
  `service-go/`. It already carries `worker/`, `grafana/` and `tests/`; this changes nothing that
  matters, and creating one is a larger change than this feature with its own blast radius.
- **Resource limits on the new service**, for the reason the compose-hardening feature recorded: the
  load routes exist to exhaust CPU and memory, and a ceiling turns the demo into an OOM kill.
- **Route parity with the FastAPI app.** The Go service gets no `/load/memory-spike` and no
  `/load/stress/{seconds}`. Two load routes are enough to produce series and to collide; the fan-out
  of the load generator grows either way.
- **Image bumps and any change to `tox.ini`.** `--cov=app --cov=worker` does not see Go, and `black`,
  `isort` and `flake8` only read Python. The Go toolchain gets its own CI job rather than a tox
  environment.

## Expected behaviour

`docker compose --profile core --profile load up --build` brings up five services, four of which
report `healthy`, and the load generator waits for both application services rather than one. The
Go service answers on port 8003; `curl localhost:8003/health` returns 200, and so does
`curl localhost:8002/health`, which did not exist before.

Prometheus scrapes two targets. `/api/v1/targets` reports both as `up`, and
`/api/v1/label/job/values` returns two job names instead of one. A query over a metric both services
export — `process_cpu_seconds_total` — without `by (job)` returns their series merged; the same
query with `by (job)` separates them. That pair of queries is the demonstration this feature exists
to produce, the before and after that the dashboard rebuild is aimed at.

The Go service's `/metrics` answers in its library's own vocabulary, not FastAPI's, and the two
halves of that vocabulary have different standing. The process and runtime metrics come from the
library with no say in the matter, and they land on exactly the names the Python client uses. The
request metrics have no library default at all, so their names are a choice the service makes; this
one names them `http_requests_total` and `http_request_duration_seconds` — the same names the
FastAPI app uses — and labels them `code` and `method` rather than the instrumentator's `handler`
and `status`. Every name and label is read off the endpoint and written into `plan.md` with the
command that produced it. The disagreement that survives is the input the dashboard rebuild works
from.

The dashboard keeps every defect it has today, now with a second service feeding it. It draws, the
same five panels as before show data, and it makes no distinction between the two services — plus a
new constant line on those panels, coming from the healthcheck probes rather than from load.

CI runs three green jobs. The Go one fails on unformatted code, on anything `go vet` objects to, or
on a failing test, and neither it nor the existing two raise a Node deprecation annotation. `tox`
still passes end to end, including the assertions that the new service is in the compose file, that
its scrape job is named uniquely, and that its module checksums are committed.

## Acceptance criteria

- [ ] `tox` passes end to end — `py311` with the new tests, `lint`, and `safety`.
- [ ] `gofmt -l service-go` prints nothing, and `go vet ./...` and `go test ./...` pass from inside
      `service-go/`.
- [ ] `docker compose --profile '*' config -q` exits without error and
      `docker compose --profile '*' config --services` resolves five services.
- [ ] `promtool check config` reports `SUCCESS` for `prometheus.yml`, run through the image derived
      from `docker-compose.yml` the way the `infra` job derives it.
- [ ] A cold `docker compose --profile core --profile load up --build -d` reaches `healthy` for
      `app`, `service-go`, `prometheus` and `grafana`, without the `up` failing on a dependency
      condition.
- [ ] The Go service's `start_period` is measured from Docker's own timestamps — `.State.StartedAt`
      against the readiness log line or `.State.Health.Log[].Start`, never wall-clock around
      `up -d` — the observed time is recorded in `plan.md`, and the value in `docker-compose.yml`
      carries its justification beside it.
- [ ] `curl -s localhost:9090/api/v1/targets` shows both targets with `health: "up"`.
- [ ] `curl -s 'localhost:9090/api/v1/label/job/values'` returns both job names, and the existing one
      is still `fastapi-app`.
- [ ] The Go service's `/metrics` is captured whole, and its request and process series are
      transcribed into `plan.md` with their labels and the command that produced them.
- [ ] A query over `process_cpu_seconds_total` without `by (job)` returns the two services' series
      merged, and the same query with `by (job)` returns them separated; both queries and both
      outputs are recorded. **Amended 2026-08-13** from a query over the `/health` route — see
      `### In` for why that filter does not return two services once the Go request metrics carry no
      `handler` label.
- [ ] What `sum by (handler) (rate(http_requests_total[5m]))` returns with both services under load
      is recorded: whether the Go service's requests land in a single unlabelled group beside the
      app's named routes, and whether the dashboard's `handler` variable query lists them.
- [ ] The dashboard is opened in a browser with both services under load, and whether the Go service
      appears in the existing panels and in the `handler` dropdown is recorded in `plan.md` as an
      observation, not as an inference from an API response.
- [ ] `curl -s localhost:8002/health` and `curl -s localhost:8003/health` both return 200, and
      `tests/test_health.py` asserts the FastAPI route's exact status code and body.
- [ ] Both healthchecks in `docker-compose.yml` probe `/health`, and neither probes `/metrics`.
- [ ] `worker/load_driver.py` drives the Go service's routes, `loadgen` depends on both services with
      `condition: service_healthy`, and `tests/test_load_driver.py` covers the longer list.
- [ ] Replacing the runtime image tag with a suffixed variant makes `tests/test_compose_config.py`
      fail; reverting makes it pass.
- [ ] Removing `service-go/go.sum` makes exactly one test fail; restoring it makes the suite green.
- [ ] `installed_packages` in `tests/test_compose_config.py` documents in its docstring that it
      recognises `pip` only, and why a Go Dockerfile passing it vacuously is accepted here.
- [ ] `service-go/Dockerfile` resolves dependencies through `go mod download` and contains no
      `go install`.
- [ ] A CI run on the branch is green on all three jobs and raises no Node deprecation annotation.
- [ ] `README.md` and `CLAUDE.md` describe a two-service stack — the new directory, port 8003, the
      `go` job, and the pinning coverage a Dockerfile without `pip` does and does not get — and the
      three sentences counting four infrastructure test files are still true.
- [ ] `git diff --stat main...HEAD` names only the files this feature's plan lists, plus the two
      documents of this ticket.
