# CU-86bbw0j24 — 06 spanmetrics (plan)

Spec: [./spec.md](./spec.md)

## Context

The same request is counted three times, under three label conventions, and every consumer pays for
it. The dashboard pays in panels: two error panels carry two targets each, and two whole rows —
*Routes (`handler`)* and *Requests (`code`)* — exist only because no query reaches all three
services. The Node service appears in neither. The guard pays in rules: with no wildcard over label
values, each live convention costs a drop rule of its own in `prometheus.yml`.

The split was produced deliberately, by the second service and measured by the third. This is the
feature that consumes it. The tracing feature left the way out: a span from every service carries
`http.route` in the same form, written by hand in the two services that have no framework to read a
template from. The `spanmetrics` connector turns those spans into latency, throughput and error
count — one instrumentation, one convention, and a route on a graph that cannot drift from the route
in a trace because it is the same string.

**This is the first feature that removes**, and that inverts the usual order. Nothing is switched
off until the two sources have been drawn side by side under load: the claim is that the new source
measures the same thing, and the evidence for it exists only while both are alive. It is not
reproducible afterwards — retention removes the old series in seven days.

The work lands in three layers: the Collector gains a connector, a metrics pipeline and an exporter
port; Prometheus gains a rule that keys the derived series by their originating service and loses two
drop rules for one; and the three services lose their HTTP instrumentation while keeping the
`/metrics` that carries their process and runtime series.

## Facts verified against the repo

Read against the branch on 2026-09-07. Nothing here was measured against a running stack — the
measurements this feature needs are tasks, and are marked as such below.

- **The three conventions, in the files.** `Instrumentator().instrument(app).expose(app)` on
  `app/main.py:14` gives `handler`/`status`; the `promauto` pair on `service-go/main.go:47-59` with
  `promhttp.InstrumentHandlerCounter`/`Duration` in `instrument` gives `code`/`method`; the
  hand-written `Counter`/`Histogram` on `service-node/main.js:33-45` give
  `route`/`status_code`/`method`. All three export `http_requests_total` and
  `http_request_duration_seconds`.
- **All three already write the route into the span.** The app from the FastAPI template,
  automatically; `service-go` in `semconv.HTTPRoute(route)` inside `instrument`; `service-node` in
  `span.setAttribute("http.route", route)` inside its own. All three also set the span name from the
  same value, so no instrumentation of the trace pillar is touched by this feature.
- **All three keep `/metrics` out of the trace**, by three different mechanisms —
  `OTEL_PYTHON_EXCLUDED_URLS=metrics`, an unwrapped `mux.Handle("/metrics", …)`, and an early return
  in `tracing.mjs`. So no derived series will carry the scrape, and the `handler!="/metrics"`
  selector in four panels has nothing to replace it.
- **`newMux` leaves the unmatched path out of both pillars.** It registers four routes and
  `/metrics`, and no `/` pattern, so an unknown path is served by the default `ServeMux` 404 with no
  span and no counter. The 404 debt does not close by itself: it closes with an instrumented
  catch-all, under the same `unmatched` value `service-node/main.js:183` already uses.
- **The app has no route for a 404**, so no template matches and `http.route` arrives absent. The
  fallback value is this feature's decision, not an SDK default.
- **The Collector publishes on 8888 today**, declared in `otel-collector-config.yaml` under
  `service.telemetry.metrics.readers.pull` with `host: 0.0.0.0`, and `prometheus.io/port: "8888"` in
  its compose block. `tests/test_collector_config.py::test_the_collector_publishes_its_metrics_where_prometheus_looks`
  compares the two.
- **`PATH_LABELS = ("handler", "route")`** at `tests/test_prometheus_config.py:25` is hand-written,
  and `test_a_drop_rule_covers_every_path_carrying_label` fails a path-carrying label with no rule.
  `test_no_drop_rule_selects_on_a_target_label` constrains **drop** rules only, so a `replace` rule
  reading a label the exporter produced is not in its scope.
- **Eighteen panels, four rows.** Panels 9–11 and 13–14 are the two convention rows; 5 and 6 carry
  two targets each; 3, 9, 10 and 11 select `handler!="/metrics"`. The `job` variable is
  `label_values(up, job)`, and `up` is synthetic — it never passes through
  `metric_relabel_configs`, so rewriting `job` there cannot affect the dropdown.
- **`test_no_query_names_a_scrape_job`** forbids any `prometheus.io/job` value in any query,
  `otel-collector` included. A panel selecting the new source by the Collector's job name fails —
  which is the assertion that forces the `job` rewrite rather than merely recommending it.
- **`test_the_sample_ceiling_drawn_matches_the_one_enforced`** ties panel 16's threshold to
  `global.sample_limit`: the ceiling and the line move in one commit or not at all.
- **`test_no_two_panels_share_grid_space`** and `test_every_panel_declares_a_unique_id` mean removing
  a row is a re-layout, not a deletion.
- **Nothing asserts the app serves `/metrics`.** `tests/test_main.py` covers `/` alone, so the
  retirement can silently take the endpoint with it. That assertion is written before the
  instrumentation is removed.
- **The discovery contract gives one port per container and has no cheap extension.** A
  `relabel_config` regex is static, RE2 has no backreference, and `keepequal` compares one label with
  another rather than with a set. A second port means naming a target in `prometheus.yml` — what
  discovery removed from that file.
- **No service declares `depends_on` for the Collector**, and `test_no_service_waits_for_the_collector`
  keeps it that way. With request metrics coming from it, the Collector going down now empties
  panels; taking an application down stays forbidden.
- **`OTEL_METRICS_EXPORTER=none` in all three blocks is still right.** The calculation belongs to the
  Collector; turning the SDK exporters on adds a fourth source.
- **`prometheus-fastapi-instrumentator` is a direct entry in `requirements/base.in`**, and
  `prometheus_client` reaches the image only through it.

**Hypotheses, to be measured with the stack up. Each is a task, not an assumption:**

- **How the Collector's internal telemetry reaches the exporter port.** Two candidates: a
  `prometheus` receiver self-scraping the pull reader into the same metrics pipeline, or the
  `periodic` reader pushing OTLP into the Collector's own receiver. The first brings its own
  `job`/`instance` that collide with the scrape's; the second closes a loop of telemetry over
  itself. A third arrangement avoids moving the compose label at all — the exporter takes 8888 and
  the pull reader moves to a loopback-only port that the receiver scrapes. Measure, then write which
  and why.
- **Under what label the originating service arrives.** The OTel `prometheus` exporter derives `job`
  and `instance` from `service.name` and `service.instance.id`, and Prometheus renames a colliding
  label to `exported_*` unless `honor_labels` is on. The decision — the series ends with `job` equal
  to the service — does not move; which label the rule reads comes from the measurement.
- **Whether the dot becomes an underscore.** `http.route` should arrive as `http_route`. If it
  arrives dotted, the drop rule and every panel have to cite it as `{"http.route"=…}`, and the guard
  gains a label PromQL reaches only quoted.
- **What the Collector reads after the change.** It carried 551 samples per scrape idle and 1253 with
  traces flowing; it now also carries the request series of three services and its own telemetry on
  one port. Measure against `sample_limit: 4000` **before** writing any new value — and measure the
  fall on the other side, since the three services lose their HTTP series.
- **Whether the two sources converge.** The acceptance criterion, and the only evidence that
  switching off is safe. By instant query, for the reason under "Edge cases".
- **How the app keeps `/metrics` without the instrumentator.** Either `Instrumentator().expose(app)`
  with no `.instrument(app)`, or `prometheus_client.make_asgi_app()` mounted directly — in which case
  `prometheus-client` becomes a direct entry in `requirements/base.in` and the instrumentator leaves
  it.

## Affected files

| File | Change |
| --- | --- |
| `otel-collector-config.yaml` | The `spanmetrics` connector, a server-span filter, the metrics pipeline, the `prometheus` exporter, and the internal telemetry folded onto its port |
| `docker-compose.yml` | The Collector's `prometheus.io/port`, only if the measurement moves it |
| `prometheus.yml` | The `job` rewrite, one drop rule on the new route label in place of two, and the ceiling only if the measurement requires it |
| `app/main.py` | The HTTP instrumentation goes; `/metrics` stays |
| `service-go/main.go`, `main_test.go` | The instrumented catch-all; then the two collectors and the `promhttp.InstrumentHandler*` wrapping go |
| `service-node/main.js`, `main.test.js` | The two hand-written collectors go; `collectDefaultMetrics` and `/metrics` stay |
| `requirements/base.in`, `base.txt`, `dev.txt` | Only if the app's `/metrics` stops coming from the instrumentator |
| `grafana/dashboards/services.json` | Two convention rows become one, the error panels lose their second target, the route variable moves to the new label |
| `tests/test_prometheus_config.py` | `PATH_LABELS`, and the `job` rewrite |
| `tests/test_collector_config.py` | The metrics pipeline and the port it publishes, against the compose label |
| `tests/test_main.py` | That `/metrics` still answers after the instrumentator goes |
| `tests/test_grafana_provisioning.py` | What the dashboard rewrite changes |
| `CLAUDE.md` | One convention instead of three, the new metric path, the rewritten `job`, and every sentence describing the split |
| `README.md` | The dashboard tour, to the extent it describes the split |

## Design

### The new path

The services keep pushing OTLP to the Collector. A second traces pipeline reads the same receiver,
filters to server spans, and feeds `spanmetrics`; the connector emits call count and duration, and a
`prometheus` exporter publishes them on a port. Prometheus keeps pulling, under the same four-label
contract — what changes is that one target now answers for three services.

The pipeline that writes to Tempo is untouched. The filter sits on the connector's branch alone, or
it would decide what the trace store holds.

**Server spans only.** Without the filter each hop of `/chain` is counted twice — once on the client
that called and once on the server that answered — and throughput comes out multiplied with nothing
visibly wrong.

**Dimensions are explicit:** service, `http.route`, `http.request.method`, `http.response.status_code`,
with a chosen default for the route so a request that matched none is one named group rather than a
series missing the label. `span.name` stays out: it is redundant where the route names the span, and
unbounded where it does not — the two internal ASGI spans are already that case.

**One bucket list**, in the connector, in seconds. This is where the bucket debt dies: one set for
three services, instead of the app's four bounds against the Go service's twelve.

### One port, two things

The discovery contract gives one port per container. So the port the Collector declares serves both
the derived metrics and its own telemetry. Which mechanism folds them is the measurement; what is not
negotiable is that the Collector stays observed in the feature that puts it on the critical path of
metrics.

### `job` keeps naming the service

The exporter is one target, so without intervention every request series arrives under the
Collector's job and the dashboard loses the only dimension by which it separates services. A rule in
`metric_relabel_configs` copies the originating service into `job`, selecting on label presence and
naming no service — the same shape the drop rules have, for the same reason.

The cost, written beside it: for these series `job` stops meaning "the target that was scraped",
while `instance` still names the Collector. That is what keeps `by (job)` working in eighteen panels,
and what makes the side-by-side comparison a difference of metric name rather than of label schema.

### Add, compare, retire

Three stages, in that order, and the middle one is the deliverable of the feature: both sources
alive under load, the same graph drawn both ways. Converging, the old instrumentation goes.
Diverging, the reason is recorded before anything is switched off.

### What no span carries

CPU, resident memory and the runtime metrics have no span to come from. They keep arriving from each
service's `/metrics`, which is what keeps the three in the scrape after the retirement and the
*Services* row out of the diff.

## Tasks

One commit per task, with the checkbox ticked in the same commit. Any sentence in `CLAUDE.md` or
`README.md` that a task makes false is corrected in that task's commit; so is the drop rule that a
task makes dead.

- [ ] The `spanmetrics` connector, the server-span filter, the metrics pipeline and the `prometheus`
      exporter in the Collector, with its internal telemetry on the same port and the compose label
      pointing at it — plus the structural assertions on both. Nothing is switched off: what this
      proves is that a second source exists beside the first. —
      `feat(collector): derive request metrics from spans`
- [ ] **Measurement, before any new value is written:** the Collector's samples per scrape against
      `sample_limit`, under which label the originating service and the route arrive and in what
      spelling, and which mechanism folds the internal telemetry. Record the numbers and the query
      behind each one here. — verification
- [ ] The `job` rewrite and a drop rule on the new route label, with their assertions and
      `PATH_LABELS`. Three rules stand here on purpose — the two they replace die with the
      conventions they guard. — `feat(prometheus): key the derived metrics by their own service`
- [ ] **The comparison, under load and by instant query:** latency, throughput and error rate from
      both sources, per service and per route. Record the numbers and the decision to retire. Nothing
      is switched off before this task is ticked. — verification
- [ ] The instrumented catch-all in `service-go`, under the same `unmatched` value the Node service
      uses, with its test. `/metrics` stays registered explicitly, so the longer pattern still wins
      over `/`. — `feat(service-go): trace and count unmatched paths`
- [ ] The HTTP instrumentation out of the app; `/metrics` and the `process_*` series stay, now with
      the test that says so. The `handler` drop rule and its `PATH_LABELS` entry go with it. —
      `refactor(app): retire the HTTP metrics instrumentation`
- [ ] The same in `service-go`: the two collectors and the `promhttp.InstrumentHandler*` wrapping go,
      `promhttp.Handler()` and the route attribute stay. —
      `refactor(service-go): retire the HTTP metrics instrumentation`
- [ ] The same in `service-node`: the two hand-written collectors go, `collectDefaultMetrics` and
      `/metrics` stay. The `route` drop rule and its `PATH_LABELS` entry go with it, and so does the
      499-on-close convention, which was a property of the counter. —
      `refactor(service-node): retire the HTTP metrics instrumentation`
- [ ] The dashboard: the two convention rows become one, the error panels lose their second target,
      the route variable reads the new label, and the layout closes the gap the removed row leaves.
      Between the retirements above and this commit the old rows draw a plateau, not traffic. —
      `feat(grafana): draw one convention instead of three`
- [ ] The ceiling, **only if the measurement requires it**, with the headroom re-justified beside the
      value and the panel threshold in the same commit. No commit if it does not. —
      `feat(prometheus): re-fit the ceiling to the derived metrics`
- [ ] `CLAUDE.md`: one convention instead of three, the new metric path, the rewritten `job`, and the
      correction of every sentence describing the split — the three-convention table, the two
      convention rows, the two drop rules, the 499 counting, and the debts this closes. Conclusions
      only; the derivation stays here. — `docs: document the single metric convention`
- [ ] `README.md`, to the extent it describes the dashboard and the guard. —
      `docs: update the dashboard tour`
- [ ] Run the verification steps and record each outcome here. No commit beyond the tick. —
      `docs(specs): record the verification outcomes`

## Edge cases

- **`spanmetrics` measures in milliseconds by default.** Left there, the bucket list, the panel units
  and every threshold in the dashboard change meaning silently.
- **The `prometheus` exporter keeps a series alive for `metric_expiration`** after its last sample —
  a route that stops being called keeps being exported for that window.
- **`query_range` carries the last sample forward for five minutes**, so a switched-off source draws
  a plateau until retention clears it. Conclude by instant query.
- **The ceiling and the panel threshold are one number in two files**, and a test fails when they
  disagree.
- **The guard now protects a target that speaks for three services.** Tripping the Collector's
  ceiling empties the request metrics of the whole stack rather than of one service. Size with that
  in the calculation.
- **The Collector going down now empties panels** that used to draw. That is the accepted cost of a
  single source; what stays forbidden is it taking an application down, and no `depends_on` is added.
- **Removing a dashboard row is a re-layout.** `gridPos` may not overlap and panel ids must stay
  unique, and both are asserted.
- **Nothing asserts the app serves `/metrics` today**, so the retirement can take it silently. The
  assertion goes in before the removal.
- **`prometheus_client` reaches the image only through the instrumentator.** If the app's `/metrics`
  stops coming from it, `prometheus-client` becomes a direct entry in `requirements/base.in`.
- **Recompiling `requirements/` needs `pip<26`**, if the app's dependency moves.
- **The Go catch-all must not swallow `/metrics`.** It is registered as an explicit pattern, which is
  longer than `/` and therefore wins — but registering it after the catch-all, or as a prefix, breaks
  the scrape rather than the tests.
- **`--profile` on every lifecycle command**, teardown included, against nine services.
- **The coverage gate is 80%** over `app`, `noisy` and `worker`.
- **Markdownlint** on both document edits: `compact` tables (MD060), blank lines around fences and
  lists.

## Verification steps

1. `tox` passes end to end — `py311` with the changed tests, `lint`, `safety`.
2. `docker compose --profile '*' config -q` exits clean and `config --services` resolves **nine**
   services.
3. `promtool check config` accepts `prometheus.yml`, and the Collector validator accepts the new
   configuration.
4. **Six targets at `up=1`**, the Collector included: its internal telemetry is still read, on the
   port that now also publishes the derived metrics.
5. **One request, one line:** under load, latency, throughput and error rate for all three services
   come from a single query with no duplicate target.
6. **The route on the graph is the route in the trace:** the same value in the panel and in the span,
   for all three services.
7. **The Go service's unmatched paths appear** in the error panel beside the other two.
8. **No series of the retired instrumentation receives a new sample** — by instant query, not
   `query_range`.
9. **The resource metrics are intact:** CPU and resident memory still draw per service.
10. **The Collector stopped:** the three services still answer `/health` and `/chain`, the request
    panels empty and the resource panels do not.
11. A CI run on the branch, green on all four jobs.
12. `git diff --stat main...HEAD` names only the files in "Affected files", plus this ticket's two
    documents.
