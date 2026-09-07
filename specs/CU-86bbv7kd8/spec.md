# CU-86bbv7kd8 — 05 traces

Status: Approved

Plan: [./plan.md](./plan.md)

## Summary

Add the missing pillar: a request is recorded as a trace, so the stack stops saying only *how long*
something took and starts saying *where* the time went. The three services are instrumented with
OpenTelemetry and export over OTLP to a Collector, which writes to Tempo; Grafana reads it. Because
nothing in this stack calls anything, the crossing has to be built before it can be traced — a
`/chain` route on each service, app → `service-go` → `service-node`, delivered and driven before any
instrumentation exists. The Collector and Tempo join the scrape by the same four labels every other
service uses, which puts them under a ceiling sized against application targets: the cost is measured
before any limit is rewritten. `OTEL_SERVICE_NAME` takes the same value as `prometheus.io/job`, so
both pillars call a service by one name.

## Objective

**One pillar answers half the question.** The dashboard shows `/load/io-bound` taking 2 seconds. It
cannot show which part of the work took them, and no metric can — that is what a trace is for, and
it is the foundation the remaining features stand on: without trace identifiers there is nothing for
logs to carry and nothing for a graph to link to.

**A distributed trace has nothing to record here.** The three services are observed side by side and
there is not one edge between them; the only caller in the project is the load generator, which is
not observed. Shipping Tempo against this stack ships a store of single-hop traces — the same shape
as shipping a guard nobody watched fire. The crossing is produced first, seen without traces, and
only then instrumented.

**Two identities have to agree while agreeing is free.** The series in `prometheus_data` are keyed by
`job`; a trace is keyed by `service.name`. Letting them diverge costs nothing now and costs a
hand-written translation in every query that crosses the two pillars later.

**Two risks are already named and both are cheapest at the first line.** The OTel HTTP semantic
conventions changed between versions, and a dashboard that breaks on that breaks silently; and a
Grafana datasource given a `uid` after it was first provisioned aborts the whole provisioning module
rather than updating.

**The scrape ceiling has never seen an infrastructure target.** `sample_limit` is global and was
sized against 156 samples per scrape, the largest of three small applications. Tempo and the
Collector are exporters of a different order, and a limit tripped by a legitimate target is nearly
mute: `up=0`, still listed, the reason in a log line.

## Scope

### In

- **A `/chain` route on all three services**, app → `service-go` → `service-node`, added to `URLS` in
  `worker/load_driver.py`. A route of its own rather than delegation inside an existing one, so no
  series already in `prometheus_data` changes meaning. Every hop is I/O: the Node service has one
  thread, and a route that burns CPU blocks its `/health` with it.
- **OpenTelemetry on all three services**, exporting OTLP to the Collector. All three rather than the
  two a distributed trace needs, because the feature that unifies the metric conventions consumes
  this instrumentation, and leaving one service out means instrumenting it twice.
- **Configuration by environment variable in each compose block**, alongside the scrape labels, with
  `OTEL_SERVICE_NAME` carrying the same value as `prometheus.io/job`. The sentences in `CLAUDE.md`
  saying `service-go` and `service-node` read no environment stop being true and are corrected in the
  commit that breaks them.
- **The semantic convention version pinned explicitly**, not left to each SDK's default, with the
  value written beside the pin and what each language actually emits recorded.
- **A Collector and a Tempo service** in the `core` profile, joining the scrape by the same four
  labels, publishing no port — which is what excuses them from the healthcheck rule derived from
  `ports:`, and what avoids needing a probe binary inside an image that may ship no shell. Tempo
  writes to a named volume, so a trace survives a `down` the way the dashboard state does.
- **A Tempo datasource with its `uid` declared from the first `up`**, and no second
  `deleteDatasources` entry: a datasource born with a `uid` never needs the delete-and-recreate that
  the existing one does.
- **The ceiling measured before it is touched:** samples per scrape for each new target against
  `sample_limit`, and the value Tempo puts in its own `route` label against the drop rule the guard
  already applies. `prometheus.yml` changes only if the measurement requires it, with the headroom
  re-justified beside the value.
- **Structural tests for the two new configuration files**, in the shape `tests/test_prometheus_config.py`
  already has, plus the new route, the new list entry and the new datasource in the existing files.
- **`CLAUDE.md` and `README.md` updated** — the telemetry path, the shared identity, the environment
  correction, and how to follow one request across three services.

### Out

- **Metrics derived from traces, and retiring the current instrumentation.** The three label
  conventions stay exactly as they are; `spanmetrics` and the decision to switch belong to the
  metrics rework, and doing both here changes two variables at once.
- **Moving metrics through the Collector.** Prometheus keeps pulling `/metrics` unchanged. The
  Collector arrives as the trace path and as the control point the next feature needs, nothing more.
- **Exemplars and correlation links.** Going from a graph to a trace, and from a trace to a log, is
  the end-to-end correlation feature. This ticket ends at a trace one can open in Grafana.
- **Logs.** Nothing here makes a service log anything; carrying the trace identifier into log lines
  is the logging feature's first requirement, not this one's.
- **A dashboard panel for traces.** The surface of a trace is Explore. The Collector and Tempo appear
  in *Targets up* and in the cardinality row on their own, with no panel edited — which is the
  dashboard's genericity being proven a third time rather than a deliverable of this ticket.
- **A per-target scrape ceiling.** Closed since the guard was built: `sample_limit` is a static
  `scrape_config` field, so a per-target ceiling means a second job, which puts service names back
  into `prometheus.yml`.
- **A sampling policy.** Every span is exported. Sampling is a decision that needs traffic worth
  sampling, and this stack's traffic is synthetic and fixed.
- **Any dependency of an application on the Collector.** No service declares `depends_on` for it and
  no export path may block a request. Trading application availability for telemetry availability
  inverts what the stack is for.

## Expected behaviour

`docker compose --profile '*' config -q` exits clean and resolves nine services. Under `core` and
`load` the stack answers the same paths it did, plus `/chain` on each of the three services, and the
Prometheus targets grow by two — the Collector and Tempo, discovered from their own labels with no
edit to the discovery job.

A request to `/chain` on the app returns 200 after crossing all three services. In Grafana that
request is one trace with spans from `fastapi-app`, `service-go` and `service-node`, each named by
the route in template form rather than by a raw path. Calling `/chain` directly on `service-go`
produces a two-service trace, so the propagation is visible as a difference rather than asserted.

The three services keep the series counts they had, plus whatever the OTel SDK adds; every target
including the two new ones reports `up=1`. Stopping the Collector leaves all three services answering
`/health`, leaves the metrics dashboard drawing, and makes `/chain` fail on its own terms.

`tox` fails if a configuration file loses a field the stack depends on, if the Tempo datasource is
missing its `uid`, or if the new image tags in the compose file disagree with the tags quoted in
`CLAUDE.md` and `README.md`.

## Acceptance criteria

- [ ] `/chain` exists on all three services, is listed in `URLS`, and no existing route changed
      behaviour or label values.
- [ ] The chain is delivered and driven **before** any OTel code, and no service's healthcheck probes
      anything but its own `/health`.
- [ ] All three services export OTLP to the Collector, configured by environment variables declared
      in their own compose blocks.
- [ ] `OTEL_SERVICE_NAME` equals `prometheus.io/job` for each of the three, and the two values sit in
      the same compose block.
- [ ] The semantic convention version is pinned explicitly, the value is written beside the pin, and
      what each of the three languages emits is recorded.
- [ ] The Collector and Tempo join the scrape by the four labels alone, with no edit to the discovery
      job, no published port, no healthcheck, and `prometheus.io/job` values that collide with
      nothing.
- [ ] Tempo's storage is a named volume declared and mounted like the two that already exist.
- [ ] The Tempo datasource declares a `uid` in its first provisioned version, and no
      `deleteDatasources` entry was added for it.
- [ ] Samples per scrape are measured for both new targets against `sample_limit`, and Tempo's own
      `route` values are checked against the drop rule, **before** `prometheus.yml` is edited; the
      numbers and the queries that produced them are recorded.
- [ ] If a limit changes, the new headroom is justified beside the value against the measurement, and
      `promtool check config` accepts the file.
- [ ] `docker compose --profile '*' config -q` exits clean and resolves nine services.
- [ ] A request to `/chain` returns 200 and produces **one** trace carrying spans from all three
      services, with the route in template form, opened in a browser rather than inferred from an
      API response.
- [ ] Calling `/chain` directly on `service-go` produces a trace of two services, demonstrating
      propagation as an observable difference.
- [ ] All five targets report `up=1`, and the per-job series counts of the three services differ from
      their recorded baseline only by metrics the OTel SDK adds.
- [ ] With the Collector stopped, the three services still answer `/health`, the metrics dashboard
      still draws, and no service is left unhealthy.
- [ ] `tox` passes end to end and a CI run on the branch is green on every job.
- [ ] `CLAUDE.md` and `README.md` describe the telemetry path, the shared identity, the pinned
      convention version, and how to follow one request across three services; the sentences saying
      `service-go` and `service-node` read no environment are corrected.
