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

- Tempo 3.0.3's default block retention.
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

`derivedFields` reads the id from structured metadata with `matcherType: label`, measured in the
second task, so the line body stays as it is. The id never becomes a Loki label: a label per trace
id is a stream per request.

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
- [x] **Measure:** whether `derivedFields` reads structured metadata on Grafana 12.4.7, via a
      datasource edited in the UI and discarded. Decides the shape of the logs → trace link. —
      verification

      Measured 2026-10-04 against the running stack under `core` + `load`, after one `GET /fail`
      on each service.

      **It does: the link is configuration, and no service changes.** A temporary Loki datasource
      created through `/api/datasources`, with one derived field — `matcherType: label`,
      `matcherRegex: trace_id`, `url: ${__value.raw}`, `datasourceUid: tempo` — showed a `TraceID`
      link in the details of each of the three lines in Explore. Clicked on the `service-go` one,
      it opened `service-go: GET /fail`, status 500, in a split Tempo pane. The datasource was then
      deleted, and `/api/datasources/uid/loki-probe` answers 404.

      **`trace_id` is structured metadata on all three services' lines**, read off the
      `query_range` response, and every one resolves through the Tempo proxy to a `GET /fail` server
      span carrying `http.response.status_code` 500 and `STATUS_CODE_ERROR`. That includes the app,
      where the exception handler answers rather than the route — the span still records the 500.
- [x] Exemplars in the connector, OpenMetrics in the exporter, with assertions. —
      `feat(collector): emit an exemplar with every derived metric`
- [x] **Measure:** series names and sample count before and after, the exposition size, and an
      exemplar in `query_exemplars` after the flag is set by hand. — verification

      Measured 2026-10-04 under `core` + `load`. The exposition was read from inside the compose
      network with Python in the app container — busybox `wget` in the Prometheus image does not
      resolve compose service names. The flag was set through a throwaway compose override, and
      Prometheus was recreated from the repository's own command afterwards.

      **OpenMetrics changes nothing Prometheus stores.** For the Collector's target: **45 metric
      names before and after, identical**, and `scrape_samples_post_metric_relabeling` **357 before
      and after**. No `_created` series appears. The body is **126 KB before, 128 KB in OpenMetrics
      after**, against `body_size_limit: 4MB`. Before the change the exporter answered the classic
      format even when OpenMetrics was asked for; after, it answers
      `application/openmetrics-text; version=1.0.0`. **No limit changes.**

      **Exemplars sit on both counters and buckets**: 20 in one exposition, ten on
      `traces_span_metrics_calls_total` and ten on `traces_span_metrics_duration_seconds_bucket`,
      each carrying `trace_id` and `span_id`.

      **Prometheus v3.13.2 negotiates OpenMetrics by default and the re-key keeps the exemplar.**
      With `--enable-feature=exemplar-storage` and nothing else changed, `/api/v1/query_exemplars`
      on the bucket series returned **73 exemplars over 19 series**, split across `fastapi-app`,
      `service-go` and `service-node` — `job` already re-keyed from `service_name`, which is
      dropped. One `GET /fail` per service gave one `/fail` exemplar per service, and each trace id
      resolved in Tempo to that service's `GET /fail` server span.

      **The exemplar store is a buffer, not a retention.** `prometheus_tsdb_exemplar_max_exemplars`
      is **100000** and it filled at **3.7 per second** under load — about **7.4 hours** before the
      oldest is evicted. That is a long way over the dashboard's default 30-minute range, so
      `storage.exemplars` is left at its default; an exemplar older than that is simply gone.
- [x] The flag in the Prometheus command, a limit only if the measurement requires it, with the
      assertion. — `feat(prometheus): store the exemplars`
- [x] Graph → trace, and exemplars on the panel the measurement picks. —
      `feat(grafana): open a trace from a point on the graph`

      Measured 2026-10-04 in the browser: with `"exemplar": true` on its target, the existing *p95
      by route* panel draws the points over its `histogram_quantile` lines — Grafana fetches the
      exemplars of the bucket series inside it. So no raw-bucket panel is added. A point's tooltip
      carries a *Query with tempo* link, and clicking one opened `service-go: GET /load/cpu-bound`
      in Tempo.
- [x] Trace → logs. — `feat(grafana): open the logs of a trace`

      Measured 2026-10-04 with a throwaway Tempo datasource before provisioning: the default
      `filterByTraceID` link already reaches structured metadata. For the app's `GET /fail` span it
      wrote `{service_name="fastapi-app"} | label_format log_line_contains_trace_id=…
      | log_line_contains_trace_id="true" or trace_id="<id>"` over the span's own 8 ms window, and
      returned that request's one line, in Explore and through the Loki API alike. So no
      `customQuery` and no time shift.
- [x] Logs → trace, in the form the second task decided. —
      `feat(grafana): open the trace of a log line`

      The field the second task measured, provisioned — with one difference the API-created probe
      could not show. **Provisioning expands `${...}` from the environment**, so `url:
      ${__value.raw}` reached Grafana as an empty string, read back off
      `/api/datasources/uid/loki`, and the link would have opened Tempo with no query. Escaped as
      `$${__value.raw}`, it arrives intact; the `service-node` line's *Open trace* then opened
      `service-node: GET /fail`, status 500.
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
