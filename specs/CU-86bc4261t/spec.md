# CU-86bc4261t — 08 correlation

Status: Approved

Plan: [./plan.md](./plan.md)

## Summary

Connect the three pillars. Metrics, traces and logs all exist and share a trace id, but moving
between them is done by hand: copy an id, open another datasource, paste it. This feature makes each
step a click — a point on a graph opens the trace of that request, the trace opens its logs, a log
line opens its trace. The exemplar is born in the Collector's `span_metrics` connector, exposed over
OpenMetrics and stored by Prometheus; the links are provisioned datasource configuration. A
deliberate failure route in each service makes the walk reproducible, and a CI smoke test runs it.

## Objective

**This is the project's done-criterion.** Three stores that work side by side are three dashboards;
navigation between them is what makes them observability. The walk was done manually while verifying
the logs feature, and its first step — from the graph to a concrete request — does not exist in any
form today.

**Provoking an error is choreography today.** The only way to produce one is to stop a service so
the previous hop fails. `service-node`, the last hop, has no failure reachable from outside and
writes no log line in practice, and the app's unhandled-exception handler is reached by nothing.
That makes the demonstration fragile and a smoke test expensive.

**The three retentions disagree.** Prometheus keeps 7d/512MB and Loki keeps everything forever, so
an exemplar can find a trace whose lines are gone, or a line can outlive its trace. Correlation is
where that starts to matter.

## Scope

### In

- **Exemplars** emitted by the `span_metrics` connector, exposed in OpenMetrics by the Collector's
  `prometheus` exporter, and stored with `--enable-feature=exemplar-storage`.
- **Graph → trace**: `exemplarTraceIdDestinations` on the Prometheus datasource, and exemplars on
  the latency panel the measurement picks. No new panel.
- **Trace → logs**: `tracesToLogsV2` on the Tempo datasource, mapping `service.name` to Loki's
  `service_name`.
- **Logs → trace**: `derivedFields` on the Loki datasource, reading the trace id where it lives
  today — structured metadata.
- **The scrape ceiling measured** against the larger exposition before any limit is touched.
- **Loki retention**, with the compactor that applies it, aligned with Prometheus; Tempo's measured
  and recorded beside it.
- **A deliberate failure route** in all three services, and `service-node`'s async dispatch path
  wrapped so a throw there stops killing the process.
- **A CI smoke test** that brings the stack up, provokes an error through that route, and checks
  the trace id reaches both Tempo and Loki.
- **Structural tests** for the new connector, compose, Loki and datasource fields.
- **`CLAUDE.md` and `README.md`**: the three links and what each depends on, the walk as a script,
  and how to attach a new service to the stack.

### Out

- **The trace id as a Loki label.** If logs → trace cannot read structured metadata, the id goes
  into the line body as well — never into the index.
- **Access logging.** Only errors are logged, so trace → logs is empty for a successful request;
  this feature reports whether that hurts, it does not change it.
- **Go's `log.Fatal` reaching Loki.** The process dies before the batcher exports; a ticket of its
  own.
- **Sampling.** An exemplar must point at a trace that exists; sampling would break the walk
  intermittently.
- **Remote write** for exemplars — no ceiling and no drop rule apply to it.
- **Any edit to the services' instrumentation** for the links themselves; only the failure route
  touches application code.

## Expected behaviour

Under `core` and `load`, the latency panel shows exemplar points. Clicking one opens the trace of
that request in Tempo; from the trace, its logs open in Loki filtered to that trace id; from a log
line, its trace opens again. The same walk works starting from an error in two different services.

Calling the failure route on any of the three services produces an error span and a log line
carrying its trace id, with no service stopped.

Six targets stay at `up=1`, the Collector within both scrape ceilings. The three pillars read as
they did before. Stopping the Collector still leaves every service answering and healthy.

`tox` fails if exemplars are switched off in the connector or exporter, if the Prometheus flag goes
missing, if a datasource link points at an undeclared `uid`, or if Loki loses its retention. CI
fails if the chain stops answering, not only if a file stops parsing.

## Acceptance criteria

- [ ] Whether `derivedFields` reads structured metadata on Grafana 12.4.7 is measured **before** any
      datasource is written, and the logs → trace link takes the form the measurement allows.
- [ ] The exemplar is measured at each of its three points — what the Collector serves, what
      Prometheus stores after relabeling, and the exposition against `body_size_limit` and
      `sample_limit` — and a limit changes only if the measurement requires it.
- [ ] A latency panel shows exemplars, and clicking one opens the trace of that request in Tempo.
- [ ] From a trace, the logs of that request open in Loki; from a log line, its trace opens.
- [ ] The full walk — graph → request → where the time went → its logs — is done by hand from a
      provoked error, in two different services, and recorded.
- [ ] Each service has a deliberate failure route that produces an error span and a log line with
      no service stopped; a throw in `service-node`'s async path no longer kills the process.
- [ ] Loki has a retention aligned with Prometheus, applied by the compactor, and asserted; Tempo's
      retention is measured and recorded.
- [ ] A CI smoke test brings the stack up, provokes an error and finds its trace id in Tempo and
      Loki; the existing four jobs stay green.
- [ ] The three pillars are intact against the readings recorded by the two previous features, and
      with the Collector stopped every service answers and no container goes unhealthy.
- [ ] `tox` passes end to end, and the four validators accept their configurations.
- [ ] `CLAUDE.md` and `README.md` describe the three links, the walk, and how to attach a new
      service.
