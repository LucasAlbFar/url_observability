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
- **What the Collector reads after the change.** It now carries the request series of three services
  and its own telemetry on one port. Measure against `sample_limit: 4000` **before** writing any new
  value — and measure the fall on the other side, since the three services lose their HTTP series.
  (551 idle and 1253 with traces flowing are **Tempo's** readings, not the Collector's; this bullet
  attributed them to the wrong target until the measurement below.)
- **Whether the two sources converge.** The acceptance criterion, and the only evidence that
  switching off is safe. Read sample age explicitly, for the reason under "Edge cases".
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
| `noisy/raw_path_emitter.py`, `tests/test_noisy.py` | Not foreseen: it misbehaved in a convention the retirements removed the guard for |
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

- [x] The `span_metrics` connector, the server-span filter, the metrics pipeline and the `prometheus`
      exporter in the Collector, with its internal telemetry on the same port and the compose label
      pointing at it — plus the structural assertions on both. Nothing is switched off: what this
      proves is that a second source exists beside the first. —
      `feat(collector): derive request metrics from spans`
- [x] **Measurement, before any new value is written:** the Collector's samples per scrape against
      `sample_limit`, under which label the originating service and the route arrive and in what
      spelling, and which mechanism folds the internal telemetry. Record the numbers and the query
      behind each one here. — verification

      Measured 2026-09-07 against the running stack under `core` + `load`, every number by instant
      query on `/api/v1/query`.

      **Samples per scrape: the Collector went from 43 to 279**, and Tempo's 1508 is still the
      largest target by five times. `scrape_samples_post_metric_relabeling` per job, the before
      taken from the same series at `time=` three hours back. The 279 decompose as **224 derived
      from spans, 51 internal telemetry, 9** for `up`, `scrape_*` and `target_info` —
      `count({job="otel-collector",__name__=~"traces_span_metrics.*"})` and its two complements.
      Against `sample_limit: 4000` that is 14x headroom, so **no limit moves.**

      **The tightest limit is no longer the sample count.** Labels per sample reached **14** against
      `label_limit: 20`, where the largest before was 8 at the exporter and 10 at ingest. Six spare,
      and five of the fourteen are labels nothing asked for: `collector_instance_id`,
      `otel_scope_name`, `otel_scope_schema_url`, `otel_scope_version`, and a `service_name` that
      repeats `exported_job`. A `labeldrop` is layer one's shape and belongs in the next task. The
      other two limits are untouched: longest label name **25** (`http_response_status_code`)
      against 64, longest value **85** against 256, and the body is **97 KB** against 4MB.

      **The originating service arrives as `exported_job`.** The exporter emits `job` derived from
      `service.name`, Prometheus renames the collision, and `service_name` carries the same value a
      second time — so the rewrite has two labels to choose from and reads the one that is not a
      duplicate. **The route arrives as `http_route`**, underscored: the dotted spelling that would
      have forced `{"http.route"=…}` through the guard and every panel did not happen.

      **The internal telemetry is folded by the self-scrape**, not by the OTLP loop: a `prometheus`
      receiver reads the pull reader on a loopback port and the exporter republishes it on 8888, so
      `prometheus.io/port` never moved. What the plan did not foresee is the cost — the receiver
      synthesises its **own** `up` and `scrape_*`, and republishing them made Prometheus read two
      targets for one container: `up{job="otel-collector"}` returned two series, and the Cardinality
      row drew 51 beside 279. `metric_relabel_configs` on that scrape does not reach them, because
      the receiver adds them outside the relabel path; a `filter` on the pipeline does. Both halves
      are asserted now.

      **The 404 debt is confirmed from the new source.** Five unmatched paths on each service:
      `fastapi-app` records `http_route="unmatched"` through the connector's `default`, proving the
      fallback works where no route template exists; `service-node` records the same value from its
      own handler; **`service-go` records nothing at all**, having no span to derive from.
- [x] The `job` rewrite and a drop rule on the new route label, with their assertions and
      `PATH_LABELS`. Three rules stand here on purpose — the two they replace die with the
      conventions they guard. — `feat(prometheus): key the derived metrics by their own service`

      **The rewrite reads `service_name`, not `exported_job`.** Both carry the originating service,
      but only `service_name` is absent from the Collector's own telemetry: measured, 54 internal
      series arrive under `exported_job=otelcol-contrib` with no `service_name`, so the other choice
      would have renamed the Collector out of its own dashboard row — undoing what sharing one port
      was for.

      **The labeldrop the measurement asked for is in.** Labels per sample fell from 14 to **7**
      against `label_limit: 20`, and the derived series now carry exactly the four the design named
      plus `__name__`, `job` and `instance`. No collision: all five targets stayed at `up=1`, which
      is what a collapsed pair would have broken.
- [x] **The comparison, under load:** latency, throughput and error rate from both sources, per
      service and per route, with sample age read explicitly rather than trusted from an instant
      query. Record the numbers and the decision to retire. Nothing is switched off before this task
      is ticked. — verification

      Measured 2026-09-07, `core` + `load`, `rate(...[5m])` unless stated.

      **Throughput converges.** Two runs minutes apart: `fastapi-app` +0.9% both times,
      `service-go` +0.5% and +1.6%, `service-node` 0.0% both. Per route on the app every value is
      0.1356 or 0.1390 — one scrape's worth apart — and which source is the higher of the two flips
      between runs, so the residual is window jitter rather than a bias either way.

      **Latency agrees where buckets are not in the way.** The mean of `/load/io-bound` — sum over
      count, which needs no bucket — reads 2.0019309s against 2.0018993s in one run and 2.0018866s
      against 2.0018798s in the other: the two sources differ by **tens of microseconds**, an order
      of magnitude below the difference between consecutive runs of the same source. That is the evidence that the two sources measure the same
      thing. The p95 does *not* agree, and that is the bucket debt rather than a disagreement: the
      app reads a flat **1.000s** for a route whose true mean is 2.002s, while the new source reads
      2.95s. Both are interpolations; only one of them is below the mean it describes. The Go and
      Node services read 2.149/2.147 old against 2.765/2.746 new, the same effect at finer
      resolution.

      **Errors agree exactly, on a counted burst.** Twelve 404s to each service, counters snapshotted
      before and after: the app moved 12 on `handler="none"` and 12 on `http_route="unmatched"`;
      `service-node` moved 12 on both of its labels. **`service-go` moved on neither** — it has no
      404 series in the old source and no span in the new, which is the recorded debt seen from both
      sides at once. A 502 burst crossed both sources the same way.

      **One defect found here and fixed in `otel-collector-config.yaml`.** At the connector's default
      `metrics_flush_interval: 60s` the derived counter is flat for a minute and then jumps — steps
      measured at t=25, 85, 145 against a 5s scrape. Every rate window shorter than the flush reads
      wrong: `[20s]` gave 3.07 req/s against a true 0.80, `[30s]` gave 1.84. Grafana derives
      `$__rate_interval` from the 5s scrape, so that is exactly what the dashboard would have asked
      for. Set to 5s; the counter now advances every scrape and every window from `[1m]` up agrees
      with the old source.

      **Decision: retire.** The two sources agree on what they both can express, and where they
      differ the new one is the more accurate of the two.
- [x] The instrumented catch-all in `service-go`, under the same `unmatched` value the Node service
      uses, with its test. `/metrics` stays registered explicitly, so the longer pattern still wins
      over `/`. — `feat(service-go): trace and count unmatched paths`

      **The obvious test does not cover this.** Asserting that three unknown paths add one series to
      `/metrics` passes whether the catch-all is labelled `unmatched` or by the raw path, because
      this service's counter carries no route label at all — the leak would only ever show in the
      derived metrics. The assertion had to move to the span: an in-memory exporter, and
      `http.route` read off the three spans. The raw-path mutation escapes the first form and fails
      the second.

      Verified against the running stack: `/nada-aqui` answers 404 with the Node service's body,
      `/metrics` still answers 200, and all three services now report under
      `http_route="unmatched"` in the derived source. `go.mod` and `go.sum` did not move —
      `tracetest` ships in the SDK module the service already required.
- [x] The HTTP instrumentation out of the app; `/metrics` and the `process_*` series stay, now with
      the test that says so. The `handler` drop rule and its `PATH_LABELS` entry go with it. —
      `refactor(app): retire the HTTP metrics instrumentation`

      **The dependency left with the convention.** `prometheus-fastapi-instrumentator` is out of
      `requirements/base.in` and `prometheus-client` is in, since the only thing still needed from
      that side is the exposition. Recompiling had to happen in a container: the project venv's
      `pip-compile` dies against its own pip, and `python:3.11.15` ships pip 24. `--no-index` no
      longer means what the old header recorded — in pip-tools 7.6 it disables PyPI outright, so the
      files are compiled with `--no-emit-index-url` and the header says so. No pin moved and the two
      files agree on every shared package.

      **`app.mount("/metrics", make_asgi_app())` is wrong and the obvious test hides it.** A mount
      answers **307** and redirects to `/metrics/`, so every scrape pays a round trip — and
      `TestClient` follows redirects, so the test reported a clean 200. Found by curling the running
      container. It is a route returning `generate_latest()` now, and the test passes
      `follow_redirects=False`, which is what makes the mutation back to a mount fail.
- [x] The same in `service-go`: the two collectors and the `promhttp.InstrumentHandler*` wrapping go,
      `promhttp.Handler()` and the route attribute stay. —
      `refactor(service-go): retire the HTTP metrics instrumentation`

      `instrument` now wraps one pillar rather than two, and the test that asserted the counter moved
      became its inverse: serving a request must publish no request series at all, since a library
      left in place but unused keeps publishing the convention. Verified on the running container —
      `/metrics` answers 200 with 44 process and runtime series and no `http_request*`, and both the
      route and the 404 still answer. Two mutations checked: reintroducing the counter fails the
      inverse test, and labelling the span by the raw path still fails the route-value test.
- [x] The same in `service-node`: the two hand-written collectors go, `collectDefaultMetrics` and
      `/metrics` stay. The `route` drop rule and its `PATH_LABELS` entry go with it, and so does the
      499-on-close convention, which was a property of the counter. —
      `refactor(service-node): retire the HTTP metrics instrumentation`

      **The route assertion could not move to the span here, the way it did in Go.** The Go test
      drives the mux in process, so the span the handler writes on is the one the test opened; over
      real HTTP the active span inside the handler is the one the HTTP instrumentation opens, which
      no client-side test reaches. Registering an in-memory SDK does not fix that, and it cost a
      dependency for nothing. What the property actually is — which label a path reports under — is
      now decided in an exported `routeFor`, asserted directly. Both mutations fail it: returning
      the raw path, and reintroducing a counter.

      `PATH_LABELS` is down to one entry and `prometheus.yml` to one drop rule. Measured after the
      restart: the last `http_requests_total` series aged to 92s and kept aging, while all three
      services report on the derived source at 4s — verification step 8, by sample age rather than
      by an instant query.
- [x] The dashboard: the two convention rows become one, the error panels lose their second target,
      the route variable reads the new label, and the layout closes the gap the removed row leaves.
      Between the retirements above and this commit the old rows draw a plateau, not traffic. —
      `feat(grafana): draw one convention instead of three`

      Eighteen panels in four rows became **fifteen in three**. `Requests (code)` and its two panels
      are gone, `Routes (handler)` is now `Requests (http_route)`, both error panels carry one target,
      and the `handler` variable is `http_route`.

      **The rule `CLAUDE.md` said was asserted was not.** It claimed three dashboard rules were
      covered by `tests/test_grafana_provisioning.py`; no test read a bucket grouping or a presence
      selector. The bucket rule is asserted now — it is the one whose violation draws a plausible
      line — and the presence rule was dropped rather than restated, having existed only to keep
      three conventions apart.

      Every panel query run against Prometheus, since a green suite proves none of them returns
      data: all fifteen return series, and the 5xx panel drew both erring services once a 502 was
      provoked. Grafana reloaded with no provisioning error and serves the fifteen panels.
- [x] The ceiling, **only if the measurement requires it**, with the headroom re-justified beside the
      value and the panel threshold in the same commit. No commit if it does not. —
      `feat(prometheus): re-fit the ceiling to the derived metrics`

      **No value moved. Every justification beside one did.** Measured 2026-09-07 in the final
      state, samples per scrape: Tempo 1510, Collector **343**, `service-node` 96, `service-go` 48,
      `fastapi-app` **16**. The three applications fell from 156, 78 and 146 — the app hardest,
      having lost a histogram with six routes' worth of buckets — while the Collector rose 279 → 343
      carrying all of it. The stack now stores **2013** samples per scrape against 2167 before the
      feature: a whole new source, and 154 fewer samples, because one convention replaced three.

      The panel threshold did not move either, `sample_limit` being unchanged, so the test tying the
      two holds untouched.

      What the re-measurement found was six stale numbers quoted beside the five limits, all of them
      inherited rather than re-read: the sample ceiling claimed ~7x headroom against Tempo's 551
      when it is **2.6x** against 1510; the longest label name was 19 and is 25; the largest body
      61.9 KB and is 166 KB; the target count said 6 and is 5. Raising `sample_limit` to widen
      Tempo's margin was rejected: it is one number for every target, and the three applications
      reading 16 to 96 would be loosened by the same factor.
- [x] `CLAUDE.md`: one convention instead of three, the new metric path, the rewritten `job`, and the
      correction of every sentence describing the split — the three-convention table, the two
      convention rows, the two drop rules, the 499 counting, and the debts this closes. Conclusions
      only; the derivation stays here. — `docs: document the single metric convention`

      Most of the corrections went in with the commits that broke the sentences, as the rule above
      says. What is left here is the positive half: a **One instrumentation, two signals** section
      with the five rules the connector arrangement now depends on — server spans only, explicit
      dimensions with a route default, one bucket list in seconds, the flush at the scrape interval,
      and one port carrying two things. Plus three fixes the incremental edits had left: the drop
      rules still said "three today", the `job` exception was written before the rule it excepts,
      and *The tracing pillar* was still called that while describing both signals.
- [x] `README.md`, to the extent it describes the dashboard and the guard. —
      `docs: update the dashboard tour`

      The dashboard tour, the Collector's bullet — it carries metrics now, not only traces — the
      three-conventions paragraph, and the guard walkthrough's label and numbers.

      **Writing that walkthrough is what found a regression the plan never anticipated.** `noisy`
      emitted `handler="/users/1"`, the app's convention, and the drop rule that caught it was
      removed with that convention in the app's retirement. Measured with the chaos profile up: 400
      samples scraped and **400 stored**, where the guard used to store 0 — layer one had stopped
      covering the only service in the stack that misbehaves, and nothing failed. `noisy` emits
      `http_route` now, the one label the stack still puts a path in, and the guard is back to 550
      scraped and 0 stored. Fixed in its own commit, not this one.
- [x] Run the verification steps and record each outcome here. No commit beyond the tick. —
      `docs(specs): record the verification outcomes`

**Verification, run end to end on 2026-09-07. Each numbered step, with its outcome:**

1. **`tox` green** — `py311`, `lint` and `safety` in 84s. 89 tests, coverage 100%, no vulnerability
   in either requirements file.
2. **Nine services** — `config -q` clean, and `config --services` resolves `app grafana loadgen
   noisy otel-collector prometheus service-go service-node tempo`.
3. **All three validators accept their files** — `promtool check config`, the Collector's `validate`
   and Tempo's `-config.verify=true`.
4. **Five targets at `up=1`**, the Collector among them on 8888 — the port that now carries both the
   derived metrics and its own telemetry, which is still being read: `otelcol_process_uptime_total`
   arrives under `job=otel-collector`.
5. **One request, one line.** Throughput, p95 and the error rate each come from a single query
   returning all three services: 0.790/0.661/0.654 req/s, 2.709/2.768/2.759s p95.
6. **The route on the graph is the route in the trace.** One `/chain` trace carries
   `http.route=/chain` on the server span of all three services, and
   `traces_span_metrics_calls_total{http_route="/chain"}` exists for all three jobs. The templated
   form survives too: a span reading `/load/stress/{seconds}` rather than a path with a number in it.
7. **The Go service's unmatched paths appear beside the other two.** One query over 4xx/5xx returns
   five series, `unmatched`/404 for `fastapi-app`, `service-go` **and** `service-node` — the first
   time the Go service has counted a 404 at all.
8. **No series of the retired instrumentation exists**, let alone receives a sample:
   `http_requests_total` and `http_request_duration_seconds_bucket` return zero series.
9. **The resource metrics are intact** — `process_cpu_seconds_total` and
   `process_resident_memory_bytes` on all three services plus Tempo.
10. **The Collector stopped:** all three answer `/health` and `/chain` with 200, no container goes
    unhealthy, and after 100s the request series are gone while the resource series are 5s old. The
    asymmetry the spec accepted, observed.
11. **A CI run** — not run. It needs a push to the branch, which was not authorised.
12. **`git diff --stat main...HEAD` names 22 files, and the table named 20.** The two extra are
    `noisy/raw_path_emitter.py` and `tests/test_noisy.py` — the regression the README walkthrough
    uncovered. The table above is corrected rather than the step waved through: the plan did not
    foresee that retiring a convention takes the guard for the one service that abuses it.

## Edge cases

- **`spanmetrics` measures in milliseconds by default.** Left there, the bucket list, the panel units
  and every threshold in the dashboard change meaning silently.
- **The `prometheus` exporter keeps a series alive for `metric_expiration`** after its last sample —
  a route that stops being called keeps being exported for that window.
- **Prometheus carries the last sample forward for five minutes**, and an instant query is *not*
  exempt: the lookback delta is the same five minutes, so a dead series still answers. Measured
  while re-keying `job` — 16 stale series read as live. The instrument is
  `time() - timestamp(<selector>)`, which returns the real age of the sample.
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
4. **Five targets at `up=1`**, the Collector included: its internal telemetry is still read, on the
   port that now also publishes the derived metrics.
5. **One request, one line:** under load, latency, throughput and error rate for all three services
   come from a single query with no duplicate target.
6. **The route on the graph is the route in the trace:** the same value in the panel and in the span,
   for all three services.
7. **The Go service's unmatched paths appear** in the error panel beside the other two.
8. **No series of the retired instrumentation receives a new sample** — read by
   `time() - timestamp(...)`, since both query forms carry the last sample forward for five minutes.
9. **The resource metrics are intact:** CPU and resident memory still draw per service.
10. **The Collector stopped:** the three services still answer `/health` and `/chain`, the request
    panels empty and the resource panels do not.
11. A CI run on the branch, green on all four jobs.
12. `git diff --stat main...HEAD` names only the files in "Affected files", plus this ticket's two
    documents.
