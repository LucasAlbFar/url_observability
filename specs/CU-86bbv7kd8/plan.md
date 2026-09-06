# CU-86bbv7kd8 — 05 traces (plan)

Spec: [./spec.md](./spec.md)

## Context

The stack has one pillar. Metrics say a request took two seconds and cannot say where the two
seconds went, and every feature after this one depends on there being a trace identifier to carry:
logs attach to it, and a graph links to it.

There is also nothing to trace. The three services are observed side by side with no edge between
them — the only caller in the repository is `worker/load_driver.py`, which is not observed. So the
order is the substance, as it was for the cardinality guard with the sign flipped: **build the
crossing, watch it produce a single-service trace, then instrument it.**

The work lands in six places. A `/chain` route written three times, once per language. Two
infrastructure services — an OpenTelemetry Collector and Tempo — each with a configuration file of a
kind this repo has never held. The OTel SDK in three toolchains, configured by environment variables
declared in the compose blocks. A second Grafana datasource. The tests that already derive their
expectations from the compose file. And the two documents.

One thing has to be measured before it is edited: the scrape limits added by the previous ticket
live in `global:` and were sized against three small applications. Tempo and the Collector are
exporters of a different order, and a ceiling tripped by a legitimate target is nearly mute.

## Facts verified against the repo

Read against `main` on 2026-09-04. Nothing here was measured against a running stack — the
measurements this feature needs are tasks, and they are marked as such below.

- **No service calls another.** `URLS` in `worker/load_driver.py` is the only list of edges in the
  project, and all ten leave `loadgen`. The crossing this feature observes does not exist yet.
- **`httpx==0.28.1` is already in `requirements/base.txt`**, pulled by the FastAPI extra. The app's
  HTTP client is not a new dependency; instrumenting it is.
- **The debt the roadmap booked for this feature was paid by the previous one.** `driven_services` in
  `tests/conftest.py` requires the scrape label **and** the `load` profile, and both sibling tests
  read that fixture. A scraped target the generator does not drive — which is what the Collector and
  Tempo are — fails neither.
- **`serving_services` in `tests/test_compose_config.py` derives from `ports:`**, with an
  `assert checked` against vacuity: publishing a port is what obliges a healthcheck. Publishing none
  is what excuses the two new services from the rule, with no hand-written exception.
- **`test_scrape_job_labels_are_unique`** forbids two services claiming the same `prometheus.io/job`.
  The two new values must collide with none of `fastapi-app`, `service-go`, `service-node`, `noisy`.
- **`test_every_datasource_declares_a_uid`** reads every provisioning file, so the Tempo datasource
  is covered the moment the file exists.
- **`tests/test_docs_versions.py` reads every `Dockerfile` `FROM` and every compose `image:`**, maps a
  repository to the **set** of tags the stack gives it, and asserts that set has one member. Both new
  images have to be quoted with the same tag in `CLAUDE.md` and in `README.md`.
- **`assert_pinned` requires `^v?\d+\.\d+\.\d+$`** — three bare components, every suffix rejected.
  The Collector and Tempo tags enter that rule on their own.
- **`PATH_LABELS = ("handler", "route")` in `tests/test_prometheus_config.py` is hand-written**, and
  is the one place in the repo where that is the honest answer: the set comes from instrumentation
  libraries, not from a file here. A new path-carrying label needs an entry there and a third drop
  rule in `prometheus.yml`.
- **The scrape limits apply to every target.** `sample_limit: 1000` was sized against 156 samples per
  scrape (`service-node`), `body_size_limit: 4MB` against a 15.2 KB body, and
  `label_value_length_limit: 256` against a 27-character value. Neither new target has been measured
  against any of them.
- **`sample_limit` cannot be set per target**, recorded when the guard was built: it is a static
  `scrape_config` field, so a per-target ceiling means a second job and service names back in
  `prometheus.yml`.
- **The dashboard's genericity guard forbids naming a scrape job in a query**, reading the
  `prometheus.io/job` values out of the compose file. The two new values join that ban by themselves
  — a further reason no trace panel belongs here.
- **The app mounts one router per feature file**, each exporting `router = APIRouter()` and included
  from `app/main.py`; the load routes are mounted under the `/load` prefix. `/chain` follows the same
  shape.
- **The root `Dockerfile` ends in `CMD ["uvicorn", "app.main:app", …]`.** Auto-instrumentation wraps
  that command; the healthcheck, which probes `/health` with `urllib`, is untouched by it.
- **`tox` gates coverage at 80% over `app`, `noisy` and `worker`.** The new route needs its own test
  or the gate absorbs the loss.
- **Grafana's `start_period` is 90s** and does not come down. Nothing in this feature should depend
  on Grafana being healthy.

**Hypotheses, each resolved by a task below rather than by argument:**

- That **Tempo exceeds `sample_limit: 1000`**. If it does, the target goes to `up=0`, stays in the
  target list, and says why only in a log line and a counter. **Resolved in task 2: it does not, at
  551 of 1000** — but that is 1.8x headroom on a file whose own rule is a measured worst case with
  room, so the ceiling moves anyway.
- That the `route` label Tempo puts on its own metrics carries a route **name** rather than a raw
  path, and so survives the existing drop rule. If it does not, the rule deletes part of Tempo's
  metrics and the symptom is an empty panel, not an error. **Resolved in task 2: it does** — three
  values, none matched by the rule.
- That the Collector image ships no shell — which would make the decision not to publish a port also
  the decision that avoids a healthcheck nobody can write. **Resolved in task 1: neither image ships
  one**, the Collector's nor Tempo's, and both run as uid 10001.
- That Python auto-instrumentation covers FastAPI **and** the httpx client with no code, and that
  Node covers both sides of `node:http` through `--require`. Go has no auto-instrumentation:
  `otelhttp` is hand-written on the server and on the client. That is what makes Go the last and
  most expensive of the three tasks.
- That the stable HTTP convention names (`http.route`, `http.request.method`,
  `http.response.status_code`) need an explicit opt-in in at least one of the three SDKs.
- That the Collector validates its own configuration through a subcommand, which would give the CI
  `infra` job the semantic check `promtool` gives `prometheus.yml`. If it does not, the structural
  test in pytest is all there is, and that goes in writing. **Resolved in task 1: both binaries do**
  — `validate --config=…` and `-config.verify=true`, each exiting non-zero on a file its process
  would refuse. Both are steps in the `infra` job now.

## Affected files

| File | Change |
| --- | --- |
| `otel-collector-config.yaml` | New: OTLP receiver, exporter to Tempo, the Collector's own `/metrics` |
| `tempo.yaml` | New: the trace store, writing to the named volume |
| `docker-compose.yml` | The two services in `core` with the four labels and no ports; `tempo_data`; the OTel variables on the three services |
| `grafana/provisioning/datasources/datasource.yaml` | The Tempo datasource, with its `uid` |
| `tests/test_grafana_provisioning.py` | The trace datasource's URL, and the scrape-interval rule scoped to Prometheus |
| `app/api/endpoints/chain.py`, `app/main.py` | The new route, by the router pattern already in use |
| `service-go/main.go`, `main_test.go`, `go.mod`, `go.sum` | `/chain`, then the hand-written server and client instrumentation |
| `service-node/main.js`, `main.test.js`, `package.json`, `package-lock.json` | `/chain`, then the `--require` bootstrap |
| `Dockerfile`, `requirements/base.in`, `base.txt`, `dev.txt` | The OTel packages and the wrapped start command |
| `worker/load_driver.py` | `/chain` in `URLS` |
| `prometheus.yml` | Only if the measurement requires it |
| `grafana/dashboards/services.json` | Only with `prometheus.yml`: a panel draws the ceiling as a threshold |
| `tests/test_collector_config.py` | New: structural assertions on the two configuration files |
| `.github/workflows/python-app.yml` | The two config validators, in the shape the `promtool` step already has |
| `tests/test_chain.py` | The new route's status code and body |
| `tests/test_compose_config.py`, `tests/test_load_driver.py`, `tests/test_grafana_provisioning.py` | The two new services, the new list entry, the new datasource |
| `CLAUDE.md` | The telemetry path, the shared identity, and the correction of the sentences saying Go and Node read no environment |
| `README.md` | Running the stack with traces, and following one request across three services |

## Tasks

One commit per task, with the checkbox ticked in the same commit. Any sentence in `CLAUDE.md` or
`README.md` that a task makes false is corrected in that task's commit.

- [x] The Collector and Tempo in `docker-compose.yml` with their two configuration files, the four
      scrape labels, no published port, the `tempo_data` volume — and the structural assertions on
      both files. Nothing exports yet: what this proves is that two services nobody wrote join the
      scrape on their own. — `feat(compose): add the collector and the trace store`
- [x] **Measurement, before any limit is edited:** samples per scrape for each new target against
      `sample_limit`, body size against `body_size_limit`, and the actual values of Tempo's `route`
      label against the drop rule. Record the numbers and the query behind each one here. —
      verification
- [x] The ceiling adjusted **only if the measurement requires it**, with the new headroom justified
      beside the value. No commit if it does not. —
      `feat(prometheus): raise the ceiling for the infrastructure targets`
      **Done: `sample_limit` 1000 → 4000**, ~7x Tempo's 551, plus the five stale measurements beside
      the other limits and the dashboard threshold that has to track the value. No other limit
      moved. `promtool` accepts the file and all five targets stay at `up=1` after a restart.
- [x] The Tempo datasource with its `uid` in its first provisioned version, and its assertions. —
      `feat(grafana): provision the trace datasource`
      **One thing the plan did not foresee:** Grafana opens two gRPC streaming channels to the
      datasource URL, and Tempo answers HTTP/1.1 on 3200, so both retry with backoff forever — four
      log lines a minute against a datasource whose every query works. Both are turned off in
      `jsonData`; turning off `search` alone leaves the metrics channel dialing.
- [x] The crossing, untraced: `/chain` on all three services, in `URLS`, with its tests. This is the
      baseline the next three tasks are a difference against. —
      `feat: make one request cross all three services`
      **One entry in `URLS`, not three:** the app's, which drives all three services in one request.
      Listing the other two would fill the trace store with one- and two-service traces of the same
      name; calling them directly is the manual proof of propagation, not traffic.
- [x] OTel on the app: packages, the wrapped start command, the variables in the compose block.
      Recompiling `requirements/` needs `pip<26`. — `feat(app): emit traces over OTLP`
      **Three things measured here.** The stable convention names arrive with
      `OTEL_SEMCONV_STABILITY_OPT_IN=http`: the server span carries `http.request.method`,
      `http.response.status_code`, `http.route`, `url.path`, `server.address`, and the client span
      the same three plus `url.full`. `OTEL_PYTHON_EXCLUDED_URLS=metrics` keeps the scrape out of
      the trace store — one trace every five seconds otherwise, which is most of what it would
      hold. And the ASGI instrumentation's internal `http send` spans **cannot** be turned off by
      environment: `exclude_spans` is a constructor argument, so auto-instrumentation has no way to
      pass it, and each app trace carries two of them.

      **The ceiling decision is vindicated by the traffic:** Tempo went from 551 samples per scrape
      to **1253** once traces began arriving. At the old `sample_limit: 1000` it would now be at
      `up=0`. The app itself stayed at its recorded 146 — with both non-trace exporters off, the
      SDK adds no metric series at all.
- [x] OTel on `service-node`, through `--require`. — `feat(service-node): emit traces over OTLP`
      **`--import`, not `--require`, and the difference is a silent failure.** This service is an ES
      module, and on Node 24 the instrumentation's patch of the CommonJS `require` never reaches an
      `import http from "node:http"`. Measured: with `--require` alone the SDK starts, logs that it
      patched `http`, and produces **no spans at all** — no error and no warning, an empty trace
      store. `tracing.mjs` registers `@opentelemetry/instrumentation/hook.mjs` through
      `node:module`'s `register`, which is what closes it; `--experimental-loader` also works and
      warns that it may be removed.

      **The SDK is assembled by hand rather than through `auto-instrumentations-node`**: this
      service serves `node:http` and nothing else, the bundle installs some forty instrumentations
      (82 MB of `node_modules` against 55 MB), and it is also the only place the scrape can be kept
      out of the trace store — this SDK has no environment variable for excluding a URL.

      **The route is set by hand too, for the reason the metric labels are.** With no framework,
      the instrumentation has nothing to read a route template from and names every span `GET`.
      Two lines in `instrument()` set `http.route` and the span name, so the trace reads
      `GET /chain`. The span is absent when the SDK is not loaded, which is how the tests run.
- [ ] OTel on `service-go`, hand-written on both the server and the client — the expensive one, and
      last because the other two settle the conventions it has to match. —
      `feat(service-go): emit traces over OTLP`
- [ ] `CLAUDE.md`: the telemetry path, the shared identity, the pinned convention version, and the
      environment correction. Conclusions only — the derivation stays in this file. —
      `docs: document the tracing pillar`
- [ ] `README.md`: bringing the stack up with traces and following one request across three
      services. — `docs: explain how to follow a request across services`
- [ ] Run the verification steps and record each outcome here. No commit beyond the tick. —
      `docs(specs): record the verification outcomes`

**The measurement, 2026-09-05, against the `core` stack.** Samples from
`scrape_samples_post_metric_relabeling` and `scrape_samples_scraped` on `/api/v1/query`; the label
shape from `/api/v1/series?match[]={job="…"}`; the body from `wget -qO- http://<target>/metrics |
wc -c` in a container on the compose network. Sixty three-span traces were pushed through the
Collector first, so both new targets are read with their path exercised rather than idle.

| Target | Samples/scrape | Body | Labels/series | Longest label value |
| --- | --- | --- | --- | --- |
| `tempo` | 551 | 61.9 KB | 10 | 71 |
| `otel-collector` | 43 | 2.4 KB | 6 | 46 |
| `service-node` | 93 | 9.9 KB | — | — |
| `fastapi-app` | 71 | 7.5 KB | — | — |
| `service-go` | 63 | — | — | — |

The app and the Node service read below the 146 and 156 samples `prometheus.yml` quotes because the
load profile was down: no traffic, so no per-route series. The Go service matches its recorded 63.
Neither affects the decision, which is driven by the largest target.

Four results:

- **The drop rules take nothing from either new target** — `scrape_samples_scraped` equals
  `scrape_samples_post_metric_relabeling` on both. Tempo does carry a `route` label, with three
  values (`/frontend.Frontend/Process`, `/tempopb.BackendScheduler/Next`, `metrics`), and the rule
  matches none of them.
- **Tempo is the new largest target by a factor of six**, at 551 samples against the 93 that used to
  lead. `sample_limit: 1000` holds today at 1.8x, which is not the headroom the value beside it
  claims, and Tempo's count grows with tenants, routes and queues rather than staying put. The
  ceiling moves in the next task.
- **Every other limit holds, and four of the numbers justifying them are now stale**: labels per
  series 8 at the exporter and 10 at ingest (written as 6 and 8), longest label name 19 —
  `service.instance.id` — (written as 14), longest label value 71 (written as 27), largest
  well-behaved body 61.9 KB (written as 15.2 KB), and six scraped targets rather than four.
- **The Collector brings the stack its first dotted label names.** Prometheus 3 stores
  `service.instance.id` as it arrives, and PromQL reaches it only in the quoted form
  `{"service.instance.id"="…"}`. Nothing queries it today; the metrics rework is where it starts to
  matter.

## Edge cases

- **A global ceiling kills a legitimate target almost silently:** `up=0`, still listed, the reason in
  a log line and a counter. It is the `DOCKER_GID` failure shape again. Measure before sizing.
- **The existing drop rule can bite Tempo's own `route` label.** It selects on the shape of a value
  and knows nothing about whose series it is; the symptom is a missing metric, not an error.
- **The Tempo datasource needs its `uid` in the first provisioned version.** Adding one later makes
  Grafana abort the whole provisioning module and restart-loop. No second `deleteDatasources` entry:
  a datasource born with a `uid` does not need one, and adding it would delete and recreate the line
  on every boot.
- **`OTEL_SERVICE_NAME` diverging from `prometheus.io/job`** breaks nothing here and breaks the
  correlation feature. Both values are declared in the same compose block, adjacent, so diverging
  takes ignoring the neighbouring line.
- **An image with no shell cannot carry a healthcheck**, and the pinning rule forbids picking an
  image for the probe's sake — the coupling `service-go` already pays with Alpine. Publishing no port
  is what keeps both problems out.
- **No application may depend on the Collector.** No `depends_on`, and the export path must not block
  a request while it tries to deliver.
- **The chain stays out of every healthcheck.** Readiness stays local, or a neighbour going down
  leaves three containers unhealthy for a reason that is not readiness.
- **Every hop is I/O.** The Node service has one thread, so a CPU-burning hop would block its
  `/health` for a stretch that grows with the machine while the probe timeout does not.
- **Wrapping the start command does not change readiness.** The healthcheck still probes `/health`.
- **New image tags are bare three-component tags**, and both have to be quoted identically in
  `CLAUDE.md` and `README.md` or `tests/test_docs_versions.py` fails and names the file.
- **Recompiling `requirements/` needs `pip<26`:** the installed `pip-compile` dies at startup against
  a newer pip, and the error reads as a broken install rather than a version conflict.
- **`--profile` on every lifecycle command**, teardown included, now against nine services.
- **The coverage gate is 80%** over `app`, `noisy` and `worker`: the new route ships with its test.
- **Markdownlint** on the `CLAUDE.md` and `README.md` edits: `compact` tables (MD060), blank lines
  around fences and lists.

## Verification steps

1. `tox` passes end to end — `py311` with the new tests, `lint`, `safety`.
2. `docker compose --profile '*' config -q` exits clean and `config --services` resolves **nine**
   services.
3. `promtool check config` accepts `prometheus.yml`, edited or not.
4. **The crossing:** `/chain` on the app returns 200 after reaching all three services.
5. **The trace:** in a browser, one trace carrying spans from `fastapi-app`, `service-go` and
   `service-node`, each named by the route in template form rather than by a raw path.
6. **Propagation as a difference:** `/chain` called directly on `service-go` produces a two-service
   trace; called on the app it produces a three-service one.
7. **Five targets at `up=1`:** the three services, the Collector and Tempo.
8. **The metrics intact:** per-job series counts against the recorded baseline of 136, 68 and 128,
   with every difference attributable to metrics the OTel SDK adds rather than to a series lost.
9. **The Collector stopped:** all three services still answer `/health`, the metrics dashboard still
   draws, `/chain` fails on its own terms, and no container is left unhealthy.
10. **Traces survive a restart:** `docker compose --profile core --profile load down` then up again,
    and a trace recorded before the restart is still readable.
11. A CI run on the branch, green on all four jobs.
12. `git diff --stat main...HEAD` names only the files in "Affected files", plus this ticket's two
    documents.
