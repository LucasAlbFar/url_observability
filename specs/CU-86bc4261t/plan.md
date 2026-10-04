# CU-86bc4261t — 08 correlation (plan)

Spec: [./spec.md](./spec.md)

## Context

The three pillars exist and share a trace id; nothing links them. Every link lands in configuration —
the Collector, the Prometheus command, the three Grafana datasources, one panel — except the
failure route, the only application code this feature writes. The request metrics are derived from
spans in the `span_metrics` connector, so that is where an exemplar is born, not in any service.

## Facts verified against the repo

Checked on 2026-10-04, at `b4a3d87`.

- **Nothing mentions an exemplar.** `grep -i "exemplar\|enable-feature"` returns nothing in
  `docker-compose.yml`, `prometheus.yml`, `otel-collector-config.yaml`, `grafana/` or `tests/`.
- **The Prometheus command has two flags**, `--config.file` and `--storage.tsdb.path`, and
  `test_prometheus_command_sets_the_storage_path` already reads it flag by flag.
- **No datasource has a link.** Prometheus carries only `jsonData.timeInterval`, Tempo only
  `streamingEnabled`, Loki no `jsonData` at all. Tempo and Loki were born with their `uid` and
  have no `deleteDatasources` entry, so editing them is in place.
- **The Collector's `prometheus` exporter sets only `endpoint: 0.0.0.0:8888`**, and the connector
  has no `exemplars` key.
- **Latency is drawn by one panel**: id 9, *p95 by route*, `histogram_quantile(0.95, sum by (le,
  job, http_route) (rate(traces_span_metrics_duration_seconds_bucket…)))`.
- **Loki keeps everything.** `loki.yaml` has no `retention_period` and no `compactor`. Prometheus
  keeps `7d` / `512MB`. `tempo.yaml` names no retention, so Tempo runs on its default.
- **Scrape limits:** `sample_limit: 8000`, `body_size_limit: 4MB`.
- **No route fails on purpose.** The app raises only `HTTPException(502)` in `/chain`, so its
  `@app.exception_handler(Exception)` in `app/main.py` is reached by nothing. `service-node` is the
  last hop and has no reachable `logError`. In `service-node/main.js`, `ioBound` writes from a
  `setTimeout` callback the dispatch `try`/`catch` never sees; a throw there ends the process.
- **CI has four jobs** — `build`, `go`, `node`, `infra` — and none starts a container that serves
  traffic.
- **Published ports:** app 8002, `service-go` 8003, `service-node` 8004, Prometheus 9090, Grafana
  3000 (`admin`/`admin`). Collector, Tempo and Loki publish none.
- **Prometheus discovery reads the socket through `${DOCKER_GID:-983}`**; a CI runner's `docker`
  group id is not 983.

**Hypotheses, to measure with the stack up:**

- Whether `derivedFields` on Grafana 12.4.7 can match structured metadata (`matcherType: label`),
  or only a regex over the line, which does not contain the id.
- Whether switching the exporter to OpenMetrics leaves the series names and the sample count as
  they are — OpenMetrics treats `_total` and `_created` differently.
- Whether Prometheus v3.13.2 negotiates OpenMetrics by default, and whether the `job` re-key in
  `metric_relabel_configs` keeps the exemplar attached.
- How much the exposition grows against `body_size_limit`.
- Whether Grafana draws exemplars on a `histogram_quantile` panel or only on a raw bucket query.
- Tempo 3.0.3's default block retention.
- Whether the app's span carries status 500 when the exception handler, not the route, answers.
- How long the stack takes to come up healthy on a cold CI runner.

## Affected files

| File | Change |
| --- | --- |
| `app/api/endpoints/fail.py` (new), `app/main.py` | `/fail`, and its router |
| `service-go/main.go`, `service-go/main_test.go` | `/fail` |
| `service-node/main.js`, `service-node/main.test.js` | `/fail`, and the async path wrapped |
| `tests/test_fail.py` (new) | The app's `/fail` |
| `otel-collector-config.yaml` | Exemplars in the connector, OpenMetrics in the exporter |
| `docker-compose.yml` | `--enable-feature=exemplar-storage` |
| `prometheus.yml` | Only if a measurement requires it |
| `grafana/provisioning/datasources/datasource.yaml` | One link per datasource |
| `grafana/dashboards/services.json` | Exemplars on the panel the measurement picks |
| `loki.yaml` | `retention_period` and the compactor |
| `tests/test_collector_config.py`, `tests/test_compose_config.py`, `tests/test_grafana_provisioning.py`, `tests/test_loki_config.py` | The new fields |
| `.github/workflows/python-app.yml` | The `smoke` job |
| `CLAUDE.md`, `README.md` | The links, the walk, attaching a service |

## Design

### Three links, one per datasource

| Link | Where | What it maps |
| --- | --- | --- |
| Graph → trace | Prometheus `exemplarTraceIdDestinations` | Exemplar label `trace_id` → datasource `tempo` |
| Trace → logs | Tempo `tracesToLogsV2` | `service.name` → `service_name`, filtered by trace id |
| Logs → trace | Loki `derivedFields` | Structured metadata `trace_id` → datasource `tempo` |

Every link names its target by `uid`, never by name; a test asserts each `uid` is declared in the
same file. No service code is touched for any of them.

If `derivedFields` cannot read structured metadata, the id goes into the line body as well, in the
three services' log calls. It never becomes a Loki label: a label per trace id is a stream per
request.

### The exemplar crosses three points and fails silently at each

Connector emits, exporter serves OpenMetrics, Prometheus negotiates and stores. Every failure looks
the same — a panel with no points — so each point is read in its own place: the Collector's
`/metrics` with an `Accept: application/openmetrics-text` header, Prometheus's
`/api/v1/query_exemplars`, and only then the panel.

### The failure route

`/fail` on each service, answering 500 and writing one error line through the logger that service
already has. Mirrored like `/health`, so the same call works on all three. How it fails follows what
each runtime has:

| Service | How `/fail` fails |
| --- | --- |
| `app` | Raises; the existing exception handler logs and answers |
| `service-node` | Throws synchronously; the existing dispatch `catch` logs and answers |
| `service-go` | `logError` and a 500 by hand — `net/http` recovers a panic by dropping the connection, which is no response at all |

It is **not** added to `URLS`: the load generator would turn the 5xx panel into a constant.
`service-node`'s `ioBound` gets its callback body wrapped in the same `try`/`catch` shape, since a
throw there is the one path that still kills the process.

### The smoke test is the manual walk, in CI

A `smoke` job: `docker compose --profile core up --build --wait` with `DOCKER_GID` read from the
runner, then a generated trace id sent in a `traceparent` header to the app's `/fail`. The id is
the test's own, so nothing has to be parsed out of a response. It then polls, with a deadline:

- Tempo through Grafana's datasource proxy, `/api/datasources/proxy/uid/tempo/api/traces/<id>`.
- Loki through the same proxy, `{service_name="fastapi-app"} | trace_id="<id>"`.
- Prometheus on 9090, six targets at `up=1`.

Going through Grafana exercises the provisioned datasources, and Tempo and Loki stay unpublished.
Teardown is `down --volumes` with `--profile core`, in an `if: always()` step.

### Retention

Loki gets `retention_period: 168h` with the compactor enabled — the 7d Prometheus keeps. The
`512MB` size bound has no Loki equivalent. Tempo's default is measured and written beside the
value in `tempo.yaml` as a comment; it changes only if it is shorter than 7d, in which case an
exemplar would point at a trace that is gone.

## Tasks

One commit per task, its checkbox ticked in the same commit.

- [x] `/fail` in the three services, with tests, and `service-node`'s async path wrapped. —
      `feat: give every service a way to fail on purpose`
- [ ] **Measure:** whether `derivedFields` reads structured metadata on Grafana 12.4.7, via a
      datasource edited in the UI and discarded. Decides the shape of the logs → trace link. —
      verification
- [ ] Exemplars in the connector, OpenMetrics in the exporter, with assertions. —
      `feat(collector): emit an exemplar with every derived metric`
- [ ] **Measure:** series names and sample count before and after, the exposition size, and an
      exemplar in `query_exemplars` after the flag is set by hand. — verification
- [ ] The flag in the Prometheus command, a limit only if the measurement requires it, with the
      assertion. — `feat(prometheus): store the exemplars`
- [ ] Graph → trace, and exemplars on the panel the measurement picks. —
      `feat(grafana): open a trace from a point on the graph`
- [ ] Trace → logs. — `feat(grafana): open the logs of a trace`
- [ ] Logs → trace, in the form the second task decided. —
      `feat(grafana): open the trace of a log line`
- [ ] Loki retention and compactor, asserted against Prometheus's; Tempo's measured and recorded. —
      `feat(loki): bound how long a line is kept`
- [ ] **Measure:** the full walk by hand from `/fail` and from a `/chain` 502, in two services;
      record whether the empty trace → logs result for a successful request is a problem. —
      verification
- [ ] The `smoke` job. — `ci: prove the chain answers, not just that it parses`
- [ ] `CLAUDE.md`: `/fail`, the three links and what each depends on. —
      `docs: document the correlation path`
- [ ] `README.md`: the walk as a script, and how to attach a new service. —
      `docs: explain the walk, and how to attach a service`
- [ ] Run the verification steps and record each result. — verification

## Edge cases

- **An exemplar outlives its trace**, or a line outlives its trace, when retentions disagree.
- **A successful request has no log line**, so trace → logs returns empty for it. Expected.
- **Go's `log.Fatal`** happens before the batcher exports; that line is never in Loki.
- **`/fail` stays out of `URLS`**, and is called by nothing but a person or the smoke test.
- **`--profile` on every `docker compose` call** in the smoke job, teardown included.
- **Grafana's 90s `start_period`** bounds how fast `--wait` can return.
- **Markdownlint** on both documents: `compact` tables, blank lines around fences and lists.

## Verification steps

1. `tox` passes end to end; `go test ./...` and `npm test` pass.
2. The four validators accept their configurations.
3. Six targets at `up=1`; the Collector within `sample_limit` and `body_size_limit`.
4. `/api/v1/query_exemplars` returns an exemplar whose trace id Tempo resolves.
5. The walk in clicks: exemplar → trace → logs of that request.
6. The way back: log line → its trace.
7. Steps 5 and 6 in two different services.
8. The three pillars intact: series per job, one trace crossing three services, a line found by
   trace id.
9. Collector stopped: all three services answer `/health` and `/chain`, none goes unhealthy.
10. The `smoke` job and the four existing jobs green on the branch.
11. `git diff --stat main...HEAD` names only the files in the table and the two ticket documents.
