# CU-86bbw0j24 — 06 spanmetrics

Status: Approved

Plan: [./plan.md](./plan.md)

## Summary

Derive the request metrics — latency, throughput, error rate — from the spans the three services
already emit, with the `spanmetrics` connector in the Collector, and retire the HTTP instrumentation
of all three libraries. Today the same request is counted three times under three label conventions;
after this it is counted once, under one, with the route label taken from the same value the trace
carries. The Collector exports the derived series on a port Prometheus pulls by the same four labels
every other target uses, and a relabel rule keys each series by its originating service so `by (job)`
keeps working. This is the first feature that **removes**: three conventions become one, two
dashboard rows become one, two drop rules become one. Hence the order — add, compare the two sources
side by side under load, and only then switch the old one off.

## Objective

**Three conventions is a cost paid on every query.** `handler`/`status` in the app, `code`/`method`
in the Go service, `route`/`status_code`/`method` in the Node service — so no single query reaches
all three. The dashboard pays for it row by row: two error panels with two targets each, and two
whole rows that exist only because the conventions do not meet. The Node service appears in neither.
The guard pays for it too — with no wildcard over label values, each live convention costs a drop
rule of its own.

**The spans already carry the route, in the same form, in all three services.** That was produced by
the tracing feature, by hand where there was no framework to read a template from. Deriving the
metric from those spans is the only arrangement in which the route on a graph cannot drift from the
route in a trace, because it is the same value.

**Two of the recorded debts have this feature as their owner and cannot be closed anywhere else.**
The app's four latency buckets, which make its p95 read a flat 1s for anything slower, die when the
connector defines one bucket list for all three services; the 404 the Go service never counts dies
when a metric derived from a span forces an instrumented catch-all. Widening the current histogram
first is work thrown away.

**Retiring before comparing throws away the evidence.** The claim is that the new source measures
the same thing; the only proof is the same graph drawn both ways, under load, while both sources are
alive. It is not reproducible afterwards — the old series expire with retention.

## Scope

### In

- **The `spanmetrics` connector and a metrics pipeline in the Collector**, reading the spans already
  flowing to Tempo. The trace pipeline is unchanged: the connector is one more consumer, not a
  detour.
- **Explicit dimensions** — service, route, method, response code — and a filter on `span.kind` so
  only server spans are counted. `span.name` stays out: with the route in the span name it is
  redundant, and the two internal ASGI spans make it unbounded.
- **One explicit bucket list in the connector**, the same for all three services, which is where the
  bucket debt closes.
- **A `prometheus` exporter on the Collector**, pulled by Prometheus under the existing four-label
  contract. Pushing by `prometheusremotewrite` would be the first metric path in the stack with no
  ceiling and no drop rules over it.
- **The Collector's own internal telemetry folded onto the same port**, because the discovery
  contract gives one port per container and the Collector may not fall out of the dashboard in the
  very feature that puts it on the critical path of metrics.
- **A `metric_relabel_configs` rule rewriting `job` from the originating service**, selecting on
  label presence and never on a service name. Without it every request series arrives under the
  Collector's job, the dashboard variable stops separating services, and every `by (job)` collapses.
- **An instrumented catch-all in `service-go`**, under the same `unmatched` value the Node service
  already uses, closing the recorded 404 debt.
- **Retiring the HTTP metrics instrumentation in all three services**, in one pass. Retiring only the
  app leaves two conventions, two drop rules and the same broken dashboard for nearly the same diff.
- **Process and runtime metrics stay** on each service's `/metrics`, since no span carries CPU or
  resident memory. That is what keeps the three in the scrape and the *Services* row out of the diff.
- **The dashboard reduced**: the two convention rows become one, the error panels lose their
  duplicate target, the route variable moves to the new label.
- **One drop rule over the new route label**, replacing the two that guarded the retired
  conventions, with `PATH_LABELS` in the test following.
- **The ceiling re-measured** against the Collector's new reading before any value is written, and
  changed only if the measurement requires it — with the headroom re-justified beside the value and
  the panel threshold moved in the same commit.
- **`CLAUDE.md` and `README.md` corrected** wherever they describe three conventions, the two
  convention rows, or the old metric path.

### Out

- **Keeping both sources alive at the end.** The comparison is a step, not a deliverable; two
  sources that survive it are the problem this feature exists to remove.
- **Moving process and runtime metrics through the Collector.** They have no span to come from and
  each service keeps exposing them; a second path for them is a different question.
- **`metrics_generator` in Tempo**, rejected: it puts the derivation in the store instead of the
  control point, and writes to Prometheus by remote write regardless.
- **Enabling the SDK metrics exporters.** `OTEL_METRICS_EXPORTER=none` stays in all three blocks —
  the calculation belongs to the Collector, and turning them on adds a fourth source.
- **A second port for the Collector**, which would mean naming a target in `prometheus.yml` again —
  exactly what discovery removed from that file.
- **A per-target scrape ceiling.** Closed since the guard was built and unchanged here.
- **Any `depends_on` on the Collector.** With request metrics coming from it, the Collector going
  down now empties panels; what it still may not do is take an application down.
- **Exemplars and links from a graph to a trace.** That is end-to-end correlation, a later feature.
- **Logs.** Nothing here makes a service log anything.
- **A new CI job.** The `infra` job already validates the Collector configuration; only its content
  changes.

## Expected behaviour

Under `core` and `load` the stack answers the same paths it did and every target still reports
`up=1`, the Collector included — its internal telemetry now sharing the port that publishes the
derived metrics. The Prometheus target list does not grow: the Collector is already discovered.

Latency, throughput and error rate for all three services come from one query with one label
convention, and the route drawn on a panel is the same string the span carries. The Go service's
unmatched paths appear in the error panel beside the other two services. The dashboard has lost a
row and the error panels their duplicate targets; the *Services* row, drawing CPU and resident
memory from each service's own `/metrics`, is untouched.

No series of the retired instrumentation receives a new sample — read by instant query, because a
range query carries the last sample forward for five minutes and a dead series keeps drawing. The
old series stay in `prometheus_data` until retention removes them.

With the Collector stopped, all three services still answer `/health` and `/chain`; the request
panels empty and the resource panels do not.

`tox` fails if the metrics pipeline or the port it publishes disagree with the compose label, if a
path-carrying label has no drop rule, if a query names a scrape job, or if the panel threshold drifts
from `global.sample_limit`.

## Acceptance criteria

- [ ] The `spanmetrics` connector feeds a metrics pipeline exported on a port Prometheus pulls by the
      four labels alone, with no target named in `prometheus.yml`.
- [ ] Dimensions are explicit — service, route, method, response code — `span.name` is not one, and
      only server spans are counted.
- [ ] The Collector's internal telemetry is still scraped, on that same port, and the mechanism that
      folds the two is recorded with the measurement that chose it.
- [ ] Samples per scrape for the Collector are measured against `sample_limit` **before** any limit is
      written, together with the drop on the application side; the numbers and the queries are
      recorded.
- [ ] Each derived series carries `job` equal to its originating service, by a rule selecting on label
      presence and naming no service; every `by (job)` panel separates the three services.
- [ ] The route label reaches PromQL in unquoted form, and the value the app reports for a request
      that matched no route is a chosen fallback rather than an absent label.
- [ ] **The two sources are compared side by side under load, by instant query**, for latency,
      throughput and error rate; the numbers and the decision to retire are recorded before anything
      is switched off.
- [ ] `service-go` counts and traces unmatched paths, under the same value the Node service uses.
- [ ] The HTTP metrics instrumentation is gone from all three services, `/metrics` still answers on
      each, and the process and runtime series the resource panels read are unchanged.
- [ ] The dashboard has one convention row instead of two, no error panel carries a duplicate target,
      and the route variable reads the new label.
- [ ] `prometheus.yml` has one drop rule over the new route label instead of the two it replaces, and
      `PATH_LABELS` in the test matches.
- [ ] If the ceiling changes, the headroom is re-justified beside the value and the panel threshold
      moves in the same commit.
- [ ] No series of the retired instrumentation receives a new sample, confirmed by instant query.
- [ ] With the Collector stopped, the three services answer `/health` and `/chain`, and no
      `depends_on` on the Collector was added.
- [ ] `docker compose --profile '*' config -q` exits clean and resolves nine services; `promtool` and
      the Collector validation accept the new files.
- [ ] `tox` passes end to end and a CI run on the branch is green on every job.
- [ ] `CLAUDE.md` and `README.md` describe one convention, the new metric path and the rewritten
      `job`, with every sentence describing the three-way split corrected.
