# CU-86bbw724z — 07 logs (plan)

Spec: [./spec.md](./spec.md)

## Context

The third pillar, and the only one with no producer at all. The Go service prints two boot lines
with the stdlib `log`, the Node service one `console.log`, the load generator uses `print`, and the
app writes nothing — `import logging` appears in no file under `app/`, `worker/` or `noisy/`. So the
feature has two halves and the first is writing logs.

The path to carry them is already half built. `OTEL_LOGS_EXPORTER=none` sits in all three compose
blocks — lines 23, 77 and 116 — waiting to be turned, and the Collector is already the control point
both other signals pass through. The same choice the previous feature made in rejecting Tempo's
`metrics_generator` applies whole: derive and route at the control point, not in the store.

Two recorded debts name this feature as their payer. The scrape ceiling, because Loki is a second
infrastructure target and `sample_limit: 4000` was justified against a measurement that does not
include it; and the missing assertion that `/metrics` stays out of the traces, which this feature is
the moment to close because it touches the instrumentation of all three services anyway.

## Facts verified against the repo

Checked against the working tree on this branch, after the previous feature merged.

- **No Python file logs.** `grep -rn "import logging\|getLogger" app/ worker/ noisy/` returns
  nothing.
- **`service-go/main.go` imports `"log"`** and uses it three times: `log.Fatalf` on tracing setup
  failure (line 219), `log.Printf` on boot (221), `log.Fatal` around `ListenAndServe` (222).
  `service-node/main.js:160` has the one `console.log`.
- **`OTEL_LOGS_EXPORTER=none` is declared in all three service blocks**, with a comment saying it is
  off because nothing here logs — that comment becomes false in this feature.
- **`opentelemetry-distro`, `opentelemetry-sdk` and `opentelemetry-instrumentation` are already in
  `requirements/base.txt`** (1.44.0 / 0.65b0), and the app image starts through
  `opentelemetry-instrument` in `Dockerfile`. `requirements/base.in` lists four OTel entries, none
  of them a logging one.
- **Neither of the other two services has a log bridge.** `service-go/go.mod` requires only the
  trace side (`otlptracehttp`, `sdk`, `otelhttp` v0.71.0); `service-node/package.json` has
  `@opentelemetry/sdk-node` 0.222.0, `exporter-trace-otlp-proto` and `instrumentation-http`, and no
  logging package. Both would take new dependencies, with `go.sum` and `package-lock.json`
  following.
- **Tempo is the model for the new service block**: `core` profile, config file mounted `:ro`, a
  named volume `tempo_data`, three `prometheus.io/*` labels, no `ports:` and no healthcheck, with
  the comment saying publishing nothing is what excuses it from the rule derived from `ports:`.
- **`serving_services` in `tests/test_compose_config.py:303` derives from `ports:`**, so a service
  that publishes nothing is not asked for a healthcheck.
- **`driven_services` in `tests/conftest.py` requires scrape *and* the `load` profile**, so an
  infrastructure target that is observed and not called fails nothing.
- **The Tempo datasource is the model for the new one**: born with `uid: tempo`, no
  `deleteDatasources` entry, and the comment beside it explains that a datasource born with a uid
  has no rename for Grafana to abort on. The Prometheus one is the opposite case and needs its
  entry.
- **The Collector's receiver already accepts both protocols on `0.0.0.0`**, and its `service:`
  block has four pipelines. A logs pipeline is a fifth consumer of the same receiver.
- **The `infra` job resolves each image from the compose file with `jq`** rather than naming it, one
  step per validator. A fourth step follows the same shape.
- **The ceiling is `sample_limit: 4000`** with the reading recorded beside it: Tempo 1510, Collector
  343, applications 16, 48 and 96. `label_limit: 20` is called the tightest of the five, and
  `target_limit: 20` is commented against "today's number is 5".
- **Nothing asserts the `/metrics` exclusion.** It exists in three different forms —
  `OTEL_PYTHON_EXCLUDED_URLS=metrics` in the app's compose block,
  `ignoreIncomingRequestHook` in `service-node/tracing.mjs:32`, an unwrapped handler in the Go
  service — and `grep` for the first two under `tests/` and `service-node/main.test.js` returns
  nothing.

**Hypotheses, to be measured with the stack up.** Each is a measurement task below, and each can
move the design:

- **Loki's OTLP ingest path** — the exact endpoint, whether a tenant header is required with auth
  off, and how it maps resource attributes to labels by default. That last one decides whether the
  label guard is configuration or already correct.
- **Whether the app needs a new dependency.** The logging instrumentation may ship inside what is
  installed, or may need an entry in `base.in` plus a variable beyond `OTEL_LOGS_EXPORTER`.
- **What Loki reads per scrape**, against `sample_limit`, and what values it puts in its own labels
  against the existing drop rule — a rule that selects on the shape of the value and does not know
  whose series it is, which is the risk that was measured for Tempo when it joined.
- **Whether a trace id reaches every line emitted inside a request**, in all three services.
- **What is lost on exit.** `log.Fatal` in Go kills the process before the batcher exports; the same
  cost was accepted for spans, and it is worth measuring to write down how much.

## Affected files

| File | Change |
| --- | --- |
| `loki.yaml` | New: the log store, writing to the named volume |
| `docker-compose.yml` | The `loki` service in `core` with the four labels and no port; `loki_data`; `OTEL_LOGS_EXPORTER` turned on in the three blocks |
| `otel-collector-config.yaml` | A logs pipeline on the existing receiver, exporting `otlphttp` to Loki |
| `grafana/provisioning/datasources/datasource.yaml` | The Loki datasource, with `uid` from the first `up` |
| `app/`, `requirements/*`, `Dockerfile` | The app's logging, and a dependency only if the measurement requires it |
| `service-go/main.go`, `main_test.go`, `go.mod`, `go.sum` | `log/slog` with the OTel bridge, in place of the stdlib `log` |
| `service-node/main.js`, `main.test.js`, `tracing.mjs`, `package.json`, `package-lock.json` | The logger and its bridge, mounted where the SDK already is |
| `prometheus.yml` | The ceiling only if the measurement requires it; a label rule only if Loki brings a raw-path value |
| `grafana/dashboards/services.json` | The panel threshold, which moves with the ceiling. Added to this table 2026-09-20, after the diff check found it missing |
| `tests/test_loki_config.py` | New: structural assertions, in the shape `test_collector_config.py` has |
| `tests/test_collector_config.py` | The logs pipeline and its destination |
| `tests/test_compose_config.py`, `tests/test_grafana_provisioning.py` | The new service, the volume, the datasource |
| `tests/test_chain.py`, `tests/test_main.py` | The app's two log paths. Added to this table 2026-09-20, after the diff check found `test_chain.py` missing |
| `tests/test_compose_config.py`, `service-go/main_test.go`, `service-node/main.test.js` | The `/metrics` trace exclusion, in all three — the app's is a declared value, so it lands beside the compose assertions rather than in `test_main.py` |
| `tests/test_docs_versions.py` | Follows on its own once the Loki image is pinned and quoted |
| `.github/workflows/python-app.yml` | The Loki validator, in the shape of the other three |
| `CLAUDE.md`, `README.md` | The third pillar, the Loki label rule, what stays on stdout, how to find one request's log |

## Design

### The path a log takes

The three SDKs emit log records by OTLP to the receiver that already accepts their spans. A new logs
pipeline in the Collector hands them to Loki's native OTLP endpoint. Nobody writes the trace id: the
SDK reads it off the active span and attaches it, which is the whole reason the transport is OTLP
and not text on stdout.

The traces and metrics pipelines are untouched. The receiver is the same; what is added is one more
consumer, the way the connector was.

Rejected, with the reason recorded: a `filelog` receiver over the host's Docker log directory. It is
the common production shape, but it puts the trace id on the application, needs a parser per format,
and gives the Collector a second coupling to the host beside the socket. Rejected too: the contrib
`loki` exporter, deprecated and translating labels on its own — the one decision this feature cannot
delegate.

### A Loki label is the cardinality guard again

In Prometheus a high-cardinality label costs series, and two layers bound it. In Loki every label
combination is a **stream**, with its own index and its own files, and a label per trace id breaks
the store in a way nothing in `prometheus.yml` reaches — those limits do not apply to Loki.

So the rule of this feature: **labels are service and severity, and nothing else.** Trace id, route,
status and the message go as structured metadata or inside the line, where they cost storage and not
index. Querying by trace id is a filter over content rather than a stream selection — slower and
correct, against fast and unsustainable.

Neither half of that rule is what the two defaults give, and they fail in opposite directions. Loki
indexes four resource attributes, one of which is `service.instance.id` — a UUID the Python SDK
generates per process, so the app alone would open a stream on every restart. And severity is not
reachable as a label at all from Loki's side. So the guard is two pieces: `otlp_config` on Loki
narrowing the indexed set to `service.name` plus the severity attribute, and two processors on the
Collector's logs pipeline putting severity where Loki can index it — `transform` onto a **record**
attribute and `groupbyattrs` to split the batch by it. Writing the resource attribute directly is
the trap: one resource per batch means the last record's severity labels all of them.

Loki is still a Prometheus target like any other, by the same four labels, and its own `/metrics`
is subject to the existing drop rules and ceiling. That is the second half of the measurement below.

### What gets logged, and what does not

Errors and dependency failures: the 502 `/chain` returns when the next hop is down, and the
unhandled exception. That is what the correlation demo has to find, and what the derived metric
cannot say — it counts that a 502 happened, not what it said.

Access logging stays out, recorded as debt. One line per request at the generator's rate repeats
what `traces_span_metrics_calls_total` already counts, and the next feature will say whether it is
missed.

### Boot lines stay on stdout

The boot lines of all three services stay where they are. They have no active span, would carry no
trace id, and `docker logs` remains where one looks when a container does not come up — exactly the
moment the OTLP path does not yet exist.

### Order: store, path, producers

Loki first, exporting nothing, which proves a third store nobody wrote enters the scrape on its own.
Then the datasource and the Collector pipeline, still with no producer — the pipeline exists and a
test says so. Then the three services, one commit each. Measurement gates each decision that writes
a number: the ceiling before any limit is edited, Loki's default attribute mapping before any label
rule is written.

## Tasks

One commit per task, with the checkbox ticked in the same commit. Any sentence in `CLAUDE.md` or
`README.md` that a task makes false is corrected in that task's commit.

- [x] Loki in `docker-compose.yml` with its configuration file, the four labels, no published port
      and a named volume, plus `tests/test_loki_config.py` and the compose assertions. Nothing
      exports yet. — `feat(compose): add the log store`
- [x] **Measurement, before any limit:** samples per scrape for Loki against `sample_limit`, body
      size against `body_size_limit`, and the values it puts in its own labels against the existing
      drop rule. Record the numbers and the query behind each. — verification only

      Measured 2026-09-20 against the running stack under `core` + `load`, every number by instant
      query on `/api/v1/query` except the body, which Prometheus only reports behind
      `--enable-feature=extra-scrape-metrics` and was read with a `GET /metrics` from inside the
      compose network instead.

      **Loki is the largest target in the stack, and its count is not a plateau.**
      `scrape_samples_post_metric_relabeling` per job: **1197 at boot, 2115 after one push of 50
      records and two queries, 2132 eight minutes in** — against Tempo's 1290 climbing toward the
      1510 already recorded for it, the Collector's 279, and the three applications at 16, 48 and
      96. So a single exercise of the write and read paths added **918 samples**, which is what
      decides the margin: `sample_limit: 4000` is **1.9x** the reading, where the value was written
      for Tempo's 2.6x, and nothing has logged yet.

      **No other limit is close.** Labels per sample **10** against `label_limit: 20`; longest label
      name **18** (`is_internal_stream`) against 64; longest label value **82**, a metric name, with
      the longest real value at **55**, against 256. The body is **267 KB** against `body_size_limit:
      4MB`, up from 158 KB at boot and now the largest in the stack ahead of Tempo's 142 KB.

      **The drop rule does not reach Loki, and that is by construction rather than by luck.** Loki
      carries no `http_route` — `has http_route: False` over every series in `{job="loki"}` — so the
      one rule in `metric_relabel_configs` selects nothing here. Its `route` label holds five fixed
      values (`metrics` and three gRPC method paths), none carrying an id. What the reading does show
      is **three values whose shape the drop regex matches** — `status_code="200"`, `status_code="204"`
      and `level="0"` — none of them touched, because the rule names `http_route` in `source_labels`
      instead of testing every label's value. A rule written the other way would discard Loki's
      request counters as raw paths.

      **What came free, and belongs to the label-mapping task below.** Loki's indexed stream label
      set after the push is **`service_name` alone** — `/loki/api/v1/labels` returns one name.
      `trace_id`, `span_id`, `severity_text`, `severity_number` and a `detected_level` Loki adds
      itself come back on the query response as structured metadata and are not indexed. So the
      default mapping already puts the trace id where the design requires it; what is not yet true
      is the other half of the rule, severity as a label.
- [x] The Loki datasource with `uid` in its first provisioned version and no `deleteDatasources`
      entry, with its assertions. — `feat(grafana): provision the log datasource`
- [x] The logs pipeline in the Collector, exporting `otlphttp` to Loki, with its assertions and the
      CI validator step. No service emits yet. The validator step landed with the store, in the
      first task. The exporter is spelled `otlp_http`, not the `otlphttp` alias, for the reason
      `otlp_grpc/tempo` is spelled out — and its endpoint stops at `/otlp`, since the exporter
      appends `/v1/logs` itself. — `feat(collector): carry logs to the store`
- [x] **Measurement, before any label rule:** what Loki does with resource attributes by default,
      and what becomes a stream. This decides whether the label guard is configuration or already
      correct. — verification only

      Measured 2026-09-20 against the running stack, by pushing OTLP records through the Collector
      and reading `/loki/api/v1/labels`, `/label/<name>/values` and `/series` — never the
      `query_range` response, whose `stream` object **merges labels and structured metadata** and
      makes an indexed set of one look like an indexed set of thirteen. That merge is the trap of
      this measurement.

      **Loki indexes four resource attributes by default**, not one: `service_name`,
      `service_instance_id`, `service_namespace` and `deployment_environment_name`. Everything else
      is structured metadata — a resource attribute off that list (`host.name`, a made-up
      `custom.unlisted.attribute`), every log record attribute, and `trace_id`, `span_id`,
      `severity_text`, `severity_number` and the `detected_level` Loki derives itself. Forty records
      carrying **forty distinct trace ids and a raw-path attribute** (`http.target=/users/0…39`)
      produced **one stream**.

      **So the default is right about the trace id and wrong about the app.** The Python SDK sets
      `service.instance.id` to a **UUID generated per process** — read off the app's resource in
      Tempo, `4ef2f024-…`; neither the Go nor the Node service sets it. Loki indexes that attribute,
      so the app alone would open a new stream on **every container restart**, from two defaults
      meeting rather than from anything anyone wrote. The guard is needed, and that is what it is
      for.

      **The guard works, and its shape is decided.** `limits_config.otlp_config.resource_attributes`
      with `ignore_defaults: true` and `service.name` as the only `index_label`: measured against a
      throwaway Loki on the compose network, the indexed set came back as `service_name` alone, with
      `service_instance_id`, `service_namespace` and `deployment_environment_name` demoted to
      structured metadata — values kept, index not.

      **Severity cannot be a label, and no configuration reaches it.** Loki's OTLP translation puts
      severity into structured metadata before the attribute lists are consulted, so
      `log_attributes` never sees it: listing `severity_text`, `detected_level` and `level` there
      changed nothing, and three severities still produced one stream. Reaching the rule as written
      means the Collector copying severity into a resource attribute first.

      **Decided 2026-09-20: keep the rule, and pay for it in the Collector.** Measured against a
      throwaway Collector and Loki on the compose network, and it takes **two** processors, not one.
      A `transform` writing straight to `resource.attributes` is wrong in a way that looks right: the
      resource is shared by every record in the batch, so the last one processed wins — five records
      of three severities arrived as **one** stream labelled `INFO`, and selecting
      `log_severity="ERROR"` returned **0 lines** with two ERROR records in the store. What works is
      writing a **record** attribute and regrouping on it: `transform` sets
      `log.attributes["log.severity"]` from `log.severity_text`, then `groupbyattrs` with that key
      splits the batch into one resource per severity. The same five records then arrived as **three**
      streams, and ERROR, WARN and INFO selected 2, 1 and 2 lines. The OTTL path needs its context
      spelled — `log.severity_text`, not `severity_text`, which fails validation.
- [x] The app's structured logging over OTLP, on error and on dependency failure, with
      `OTEL_LOGS_EXPORTER` turned on in its block. Recompiling `requirements/` needs `pip<26` in a
      container. **No dependency moved** — the SDK and the instrumentation were already installed,
      so `requirements/` did not change. What it needed instead was a second variable:
      `OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED=true`, read in
      `opentelemetry.sdk._configuration` and defaulting to `"false"`. Measured — with the exporter
      on and the variable absent the app logs, nothing leaves, and nothing anywhere reports it. —
      `feat(app): log what failed, with its trace`
- [x] The same in `service-go`, with `log/slog` and the OTel bridge replacing the stdlib `log` for
      everything but the boot lines. Four modules added — `otelslog`, `otel/log`, `sdk/log` and
      `otlploghttp` — with `go.sum` following. **No `OTEL_LOGS_EXPORTER` in this block**, unlike the
      other two: the Go SDK does not read it, `startLogging` decides, and a variable nothing reads
      is the dead configuration this compose file was cleaned of once already. —
      `feat(service-go): log what failed, with its trace`
- [x] The same in `service-node`. One dependency, `@opentelemetry/api-logs`, promoted from
      transitive to declared — the API rather than a logging library, since this service has no
      framework. Its two error paths are the registry `/metrics` awaits and the dispatch every other
      route goes through; neither is reachable from outside, so each test provokes it at its seam.
      `OTEL_LOGS_EXPORTER` moves to `otlp` here because NodeSDK **does** read it and defaults to
      `otlp` when empty — `none` was the only thing holding the logs back. —
      `feat(service-node): log what failed, with its trace`
- [x] The ceiling refitted **only if the measurement requires it**, with the headroom re-justified
      beside the value and the panel threshold moved in the same commit. No commit if it does not.
      **Moved here from before the datasource**, 2026-09-20: the measurement above read Loki at
      1.9x the ceiling with nothing logging yet, and its count moves with the paths it exercises —
      so the worst case is not knowable until the three services log, and a value written earlier
      would be written twice. — `feat(prometheus): re-fit the ceiling to the log store`

      **It required it: 4000 to 8000**, and the deferral is what found the right number. Measured
      2026-09-20 with all three services logging, `core` + `load`, every number by instant query.
      Loki read **1147 at boot, 1444** after eight minutes of the three services logging errors —
      lower than the 2132 of the first measurement, which was the clue — and **2627** once five
      queries and a series lookup had been run against it. The count tracks the **code paths Loki
      has exercised**, not the volume it holds, and the read path is the expensive one: it is what a
      person opening Explore exercises and what no synthetic load reaches. A measurement taken after
      the services logged but before anybody looked would have read 1444 and justified leaving 4000
      alone.

      8000 is 3x the 2627, in the spirit of the 2.6x that 4000 was written for. Loki also took the
      body record at **324 KB** against `body_size_limit: 4MB`, and now reaches the same **10**
      labels per sample Tempo does. No other limit moved: longest label name 18, longest value 82,
      longest real value 55, and the target count is 6. The panel threshold moved in the same
      commit, and `tests/test_grafana_provisioning.py` is what would have failed if it had not.
- [x] **Measurement:** a provoked error, and its line found in Loki by the trace id of that request,
      in each service that took part. The feature's acceptance test and the rehearsal of the next
      one. — verification only

      Measured 2026-09-20, `core` + `load`, with `service-node` stopped so both hops that call out
      fail. The trace id was **chosen rather than discovered** — the request carried a
      `traceparent` header of our own — which is what makes this a test instead of a search: the
      id is known before the line exists.

      `GET /chain` on the app answered **502**, and
      `{service_name=~".+"} | trace_id="5fecef063a304de183d257599930020d"` returned **two lines, one
      per service that took part**, each naming the neighbour it could not reach: the app's says
      `server.address=http://service-go:8003/chain, error.type=HTTPStatusError`, the Go service's
      says `server.address=http://service-node:8004/chain, error.type=*url.Error`. Different spans,
      one trace. Nothing propagated the id by hand — each SDK read it off the active span.

      **The rehearsal half:** the same id in Tempo holds six spans across the two services, the two
      server spans both carrying `http.response.status_code=502`. That is the whole path the next
      feature has to make clickable — graph to trace to logs — walked by hand and working.

      **And it showed the guard is not hypothetical.** The indexed label set was still the default
      four, and `/series` returned **four streams for three services**: the app had **two**, one per
      `service_instance_id`, from the two container recreates this session. One stream per restart,
      exactly as predicted, visible in the reading rather than in an argument.
- [x] The label guard, in both places the measurement showed it needs to be: `otlp_config` on Loki
      with `ignore_defaults: true`, indexing `service.name` and the severity attribute and nothing
      else; and `transform` + `groupbyattrs` on the Collector's logs pipeline to put severity there.
      No longer conditional — `service.instance.id` makes it required. Verified against the stack
      with the log volume dropped first, so the reading is the guard's and not the old index's:
      indexed labels came back **`service_name` and `log_severity`**, four streams for two services
      and three severities, and a record pushed with a **fresh `service.instance.id` opened no
      stream of its own**. Selecting by severity returns the right lines, and a filter by trace id
      still finds its line — the metadata is untouched. —
      `feat(loki): bound what becomes a stream`
- [x] **The recorded debt:** the `/metrics` trace exclusion asserted in all three services. Three
      mechanisms, so three suites, and the app's lands in `tests/test_compose_config.py` rather
      than `test_main.py`: its exclusion is a declared value, not code. Each assertion carries a
      control, because a pattern or predicate matching everything excludes everything and passes
      a test that only checks the scrape is covered. `service-node` needed the hook lifted out of
      the SDK constructor into an exported `isScrape`, and `sdk.start()` guarded the way
      `main.js` guards `listen` — the two see the same `argv[1]` and fail together. Verified in
      the container afterwards: Tempo holds `GET /chain` and `GET /health` for that service and
      no span naming metrics. — `test: assert the scrape stays out of the traces`
- [x] `CLAUDE.md`: the third pillar, the Loki label rule, what stays on stdout. Conclusions only —
      the derivation stays here. A second table beside the three-ways-to-start-an-SDK one, because
      the three ways to switch the **logs** on do not follow the same split: two variables for the
      app, one for Node, and none for Go. — `docs: document the logging pillar`
- [x] `README.md`: bringing the stack up with logs, and finding the lines of one request. A
      "Finding the log lines of one request" section beside the trace one, with both LogQL queries
      run verbatim against the stack first: the severity selector returns the error lines, and the
      trace-id filter returns two lines from the two services that took part. The four caveats it
      ends on are the ones a reader would otherwise discover by being surprised — only errors are
      logged, only two labels may go inside the `{}`, boot lines are not there, and the volume
      survives a `down`. — `docs: explain how to find the log of one request`
- [x] Run the verification script below and record each result. No commit beyond the tick. —
      verification only

      Run 2026-09-20. **Eleven of twelve pass; the twelfth is the CI run, which needs the branch
      pushed.**

      1. `tox` green end to end — py311, lint, and safety with no known vulnerabilities in either
         requirements file.
      2. `config -q` clean, **ten** services resolved.
      3. All four validators accept their files, each image read out of the compose file.
      4. **Six targets at `up=1`** — the three services, the Collector, Tempo and Loki — with
         `prometheus.yml` naming none of them: a grep for every service name in that file returns 0.
      5. Two provoked failures, each with a trace id chosen in the request's own `traceparent`. The
         app's returned **two lines** — `fastapi-app` naming `service-go`, `service-go` naming
         `service-node` — and the Go service's, called directly, returned **one**. The line count
         follows how many hops took part, which is the point.
      6. **13 of 13 lines carry a trace id**, 7 from the app and 6 from the Go service.
         `service-node` has none, and that is correct rather than missing: it is the last hop, calls
         nobody, and has no dependency failure to report.
      7. Indexed labels are **`service_name` and `log_severity`**, and `/series` returns **four**
         streams — service by severity, none per request or per instance.
      8. **Both earlier pillars intact.** The derived request series still separate by job — 112,
         80 and 64 for the three services — `process_cpu_seconds_total` still arrives per job, and
         a fresh `/chain` is one trace of **three services and seven spans**.
      9. **Loki stopped:** all three answer `/health`, `/chain` answers 200, and no container goes
         unhealthy.
      10. **The Collector stopped:** the same, and the target list drops to five — every signal it
          carries stops together, while nothing stops answering.
      11. **Green, all four jobs** — `build`, `lint` within it, `infra`, `go`, `node` — on run
          35538539025, the pull request's first. The workflow listens on `push` to main and
          `pull_request` against it, so pushing the branch alone triggers nothing; the run needed
          the PR.
      12. The diff names 28 files. Twenty-six are in the table above; **two were not, and the table
          was corrected rather than the claim softened** — `grafana/dashboards/services.json`,
          which the ceiling task required moving in the same commit, and `tests/test_chain.py`,
          which holds the app's dependency-failure line. `requirements/` and `Dockerfile` did not
          move, as the table allowed for; `tests/test_docs_versions.py` did not either, and did not
          need to.

## Edge cases

- **The trace id exists only inside a request.** Boot lines, background work and startup failures
  have no active span; a query by trace id does not find them, and that is correct.
- **`log.Fatal` kills the process before the batcher exports.** The last line — the one that
  explains the death — is the most likely to be lost on the OTLP path, and the one stdout still has.
  Same cost accepted for spans; measure it to write down how much.
- **Loki down may not block a response.** No new `depends_on`, and the export path does not wait for
  delivery.
- **A scraped `/metrics` would now cost two things** — a span and a log line every five seconds —
  which is why the exclusion debt is closed here.
- **Loki's retention is its own decision**, not an inheritance of the 7 days in `prometheus.yml`.
- **One port per container**, by the discovery contract. Loki serves `/metrics` on the same port it
  answers queries on, so it needs no equivalent of the loopback arrangement the Collector has.
- **`--profile` on every lifecycle command**, teardown included, now with ten services.
- **`down --volumes` destroys the log volume** along with the other three.
- **Recompiling `requirements/` needs `pip<26` in a container**: the project venv's `pip-compile`
  dies against its own pip, and `--no-index` on pip-tools 7.6 disables PyPI rather than only
  omitting the URL — use `--no-emit-index-url`.
- **Markdownlint** on both documents: `compact` tables (MD060), blank lines around fences and lists.

## Verification steps

1. `tox` passes end to end — py311 with the new tests, lint, safety.
2. `docker compose --profile '*' config -q` exits clean and `config --services` resolves **ten**.
3. All four validators accept their configurations, Loki's included.
4. **Six targets at `up=1`**, Loki included, having joined by the four labels with `prometheus.yml`
   unedited.
5. **A provoked error, its line found** in Loki by filtering on that request's trace id.
6. **Every line emitted inside a request carries a trace id**, in all three services.
7. **The streams in Loki are countable and few** — service by severity, none per request.
8. **The two earlier pillars intact:** series per job and a trace crossing all three services, read
   against the reading recorded in the previous feature.
9. **Loki stopped:** the three services still answer `/health` and `/chain`, and no container goes
   unhealthy.
10. **The Collector stopped:** the same, now with all three signals stopping together.
11. A CI run with all four jobs green.
12. `git diff --stat main...HEAD` names only the files in "Affected files", plus this ticket's two
    documents.
