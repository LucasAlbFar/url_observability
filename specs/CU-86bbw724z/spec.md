# CU-86bbw724z — 07 logs

Status: Approved

Plan: [./plan.md](./plan.md)

## Summary

Add the third pillar. Today no service in this project logs anything: two boot lines from the Go
stdlib `log`, one `console.log` in the Node service, `print` in the load generator, and nothing at
all from the app. So the feature has two halves — make the three services emit structured logs, and
collect them — and only the second half is infrastructure. Loki joins as the log store, the services
export log records over OTLP to the Collector that already carries their spans, and a new logs
pipeline delivers them. The record that decides the value of the whole feature is the **trace id**:
the SDK reads it off the active span and attaches it, so no application has to print it and no
parser has to recover it. Loki enters the scrape by the same four labels as every other target, with
no line edited in `prometheus.yml`, and its datasource is born with a `uid`. Two recorded debts fall
due here: the scrape ceiling, because Loki is a new infrastructure target, and the assertion that
`/metrics` stays out of the traces in all three services.

## Objective

**The third pillar is the one that does not exist in any form.** Metrics and traces are both in
place and both derived from the same instrumentation; logs have no producer and no store. Without
them the project's done-criterion cannot be reached, because going from a graph to the request and
from the request to its logs is the last leg.

**A log without a trace id is an isolated log.** That is the entire reason the transport is OTLP and
not text on stdout: the SDK attaches the id from the active span. Parsing stdout puts the id on the
application's account, needs a parser per format, and makes the Collector read the host's Docker log
directory — a second coupling to the host beside the socket.

**Label cardinality is the guard again, in a store where the ceiling does not reach.** In Prometheus
a high-cardinality label costs series, bounded by `sample_limit` and the drop rules. In Loki every
label combination is a **stream** with its own index, and a label per trace id breaks the store in a
way nothing in `prometheus.yml` covers. So the rule has to be decided in this feature, not
discovered later: labels are service and severity, everything else is structured metadata or line
content.

**Two debts name this feature as their payer.** The scrape ceiling was left at `sample_limit: 4000`
with today's reading recorded beside it, and its owner is the next feature that adds an
infrastructure target — Loki. And nothing asserts that `/metrics` stays out of the traces in any of
the three services; since the request metrics are derived from spans, a missed exclusion is now
traffic on the throughput panel **and** a log line every five seconds. This feature touches the
instrumentation of all three, so closing it here costs no second pass.

## Scope

### In

- **Loki as the log store**, configured from a file of its own, writing to a named volume, in the
  `core` profile, publishing no port and therefore carrying no healthcheck — the same arrangement
  Tempo and the Collector have.
- **Loki in the scrape by the four labels alone**, with no target named in `prometheus.yml`, which
  is the contract every service has entered under since discovery replaced static targets.
- **A logs pipeline in the Collector**, on the receiver that already accepts the spans, exporting to
  Loki's native OTLP endpoint. The trace and metrics pipelines are not touched: this is one more
  consumer, as the connector was.
- **`OTEL_LOGS_EXPORTER` turned on** in the three compose blocks where it has sat at `none` since
  tracing was added.
- **Structured logging in all three services**, emitting on error and on dependency failure — the
  502 `/chain` returns when the next service is down, and the unhandled exception. Every line
  emitted inside a request carries the trace id of that request.
- **The Loki label rule**: service and severity, and nothing else. Trace id, route, status and
  message go as structured metadata or inside the line, where they cost storage and not index.
- **A Loki datasource provisioned with a `uid` from the first `up`**, and therefore with no
  `deleteDatasources` entry — giving a uid to an already-provisioned datasource aborts Grafana's
  provisioning entirely.
- **The scrape ceiling measured against Loki's reading before any value is written**, and changed
  only if the measurement requires it, with the headroom re-justified beside the value and the panel
  threshold moved in the same commit.
- **The `/metrics` trace exclusion asserted in all three services**, closing the recorded debt.
- **Structural tests** for the Loki configuration, the Collector's logs pipeline, the new compose
  service and volume, and the new datasource — in the form the existing infra tests already have.
- **The Loki configuration validated in the `infra` CI job**, reading its image from
  `docker-compose.yml` the way the other three validators do. No new job.
- **`CLAUDE.md` and `README.md`** carrying the third pillar, the Loki label rule, what stays on
  stdout, and how to find the log lines of one request.

### Out

- **Access logging.** One line per request at the load generator's rate repeats what the derived
  request counter already says. Recorded as debt; end-to-end correlation will show whether it is
  missed.
- **Boot lines moving off stdout.** They have no active span, would carry no trace id, and
  `docker logs` is where one looks when a container fails to start — exactly when the OTLP path does
  not yet exist.
- **A `filelog` receiver reading the host's Docker log directory**, rejected with its reason: it is
  the common production shape and teaches something else, but it puts the trace id on the
  application, needs a parser per format, and adds a second host coupling.
- **The deprecated `loki` exporter in the Collector contrib distribution**, which translates labels
  on its own — the one decision this feature cannot delegate.
- **Any new `depends_on`**, on Loki or on the Collector. Telemetry being down may not take an
  application down, and now may not block a response while it tries to deliver either.
- **Exemplars and the links between graph, trace and logs.** That is end-to-end correlation, the
  next feature; this one only guarantees the id those links will need exists on every line.
- **A log panel in the dashboard.** The surface of a log here is Explore, the way a trace's is.
- **Loki retention tuned to match Prometheus.** It is a decision of its own, not an inheritance of
  the 7 days in `prometheus.yml`.
- **A per-target scrape ceiling.** Closed since the cardinality guard was built, unchanged here.

## Expected behaviour

Under `core` and `load` the stack resolves ten services and answers the same paths it did. Six
targets report `up=1` — the three applications, the Collector, Tempo and now Loki — and Loki got
there by declaring four labels, with `prometheus.yml` unedited.

A request that fails leaves a log line in Loki carrying the trace id of that request, and filtering
by that id returns the lines of that request and no others, across the services it touched. Lines
emitted outside a request — boot, startup failure — carry no trace id and are not found by that
filter, which is correct.

The streams in Loki are countable and few: service times severity, with nothing per request, per
route or per trace. Both earlier pillars are unchanged — the same series per job, the same trace
crossing three services.

With Loki stopped, the three services still answer `/health` and `/chain` and no container goes
unhealthy; with the Collector stopped, the same, and all three signals stop together.

`tox` fails if the Loki configuration or the Collector's logs pipeline disagree with the compose
labels, if the datasource is provisioned without a `uid`, if the panel threshold drifts from
`global.sample_limit`, or if a service stops excluding `/metrics` from its traces.

## Acceptance criteria

- [ ] Loki runs from its own configuration file, stores to a named volume, publishes no port, and is
      scraped by the four labels alone with no target named in `prometheus.yml`.
- [ ] The Collector has a logs pipeline on the existing OTLP receiver, exporting to Loki's native
      OTLP endpoint, with the trace and metrics pipelines unchanged.
- [ ] Samples per scrape for Loki are measured against `sample_limit` **before** any limit is
      written, together with the values it puts in its own labels against the drop rule; the numbers
      and the queries are recorded.
- [ ] If the ceiling changes, the headroom is re-justified beside the value and the panel threshold
      moves in the same commit; if it does not, the measurement says so and nothing is edited.
- [ ] What Loki does with resource attributes by default is measured **before** any label rule is
      written, and the rule exists only if that measurement requires it.
- [ ] Loki's labels are service and severity and nothing else; trace id, route and status are
      structured metadata or line content, and the stream count stays proportional to services times
      severities.
- [ ] All three services emit structured logs on error and on dependency failure, and every line
      emitted inside a request carries the trace id of that request.
- [ ] A deliberately provoked error is found in Loki by filtering on the trace id of that specific
      request — the acceptance test of the feature and the rehearsal of end-to-end correlation.
- [ ] The Loki datasource is provisioned with a `uid` in its first version and has no
      `deleteDatasources` entry.
- [ ] The exclusion of `/metrics` from the traces is asserted in all three services, closing the
      recorded debt.
- [ ] Boot lines stay on stdout in all three services and `docker logs` still explains a container
      that fails to start.
- [ ] No `depends_on` on Loki or on the Collector was added; with either stopped, the three services
      answer `/health` and `/chain` and no container goes unhealthy.
- [ ] The two earlier pillars are intact: the series per job and the trace crossing all three
      services, read against the reading recorded in the previous feature.
- [ ] `docker compose --profile '*' config -q` exits clean and resolves ten services; the four
      validators accept their configurations, Loki's included.
- [ ] `tox` passes end to end and a CI run on the branch is green on every job.
- [ ] `CLAUDE.md` and `README.md` describe the third pillar, the Loki label rule, what stays on
      stdout, and how to find the log lines of one request.
