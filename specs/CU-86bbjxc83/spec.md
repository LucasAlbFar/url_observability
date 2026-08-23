# CU-86bbjxc83 — Rebuild dashboard

Status: Approved

Plan: [./plan.md](./plan.md)

## Summary

Replace the provisioned Grafana dashboard with one written from scratch. The seven `type: "graph"`
panels in a `schemaVersion: 36` file become `timeseries` panels in a file that declares what it
renders; `grafana/dashboards/fastapi_metrics.json` is deleted and `grafana/dashboards/services.json`
takes its place, titled `Services Overview` under `uid: services-overview`. The provisioned
datasource gains an explicit `uid: prometheus`, and every panel and every target references it by
that uid instead of by name. The panels gain a dimension they have never had — the service: a
template variable over `job`, `job` inside every grouping, and two rows that select services by
which label convention they carry rather than by naming them. That last part is not stylistic: the
two services in the stack export ten metric names in common and disagree on the labels underneath
them, and this dashboard is the first artefact that has to work with both vocabularies at once.
`tests/test_grafana_provisioning.py`, which says in its own docstring that nothing in it looks at a
query or a panel type, starts asserting the structure the new file promises. This feature changes no
instrumentation: it does not reconcile the label conventions at collection time and it does not
widen the app's latency buckets.

## Objective

**The file does not declare what it renders.** Its seven panels are `type: "graph"`, a panel plugin
that no longer ships with the pinned image — absent from `public/app/plugins/panel/` and absent from
the 27 panels `/api/frontend/settings` reports. The dashboard nevertheless draws, and the reason is
a schema migration that runs in the browser at load time and rewrites the panel type before the
plugin is ever resolved. Measured on screen in 2026-08-11, correcting a reading taken from the API
in 2026-08-10 that had called the dashboard broken. Both readings matter here: the dashboard works
today, and what keeps it working is a compatibility path that is invisible to every endpoint and
that nobody in this project controls. The day it is dropped, the dashboard goes with it and no file
in the repository will have changed. The same migration is why opening `Settings → JSON Model`
marks the dashboard as having unsaved changes — the runtime model already differs from the stored
one, which is the symptom of the file describing something other than what is on screen.

**A second service turned a latent defect into a live one.** No panel filters by service. The
request panels group by route and the two resource panels group by nothing at all, with static
legends: `CPU seconds`, `Memory`. That was survivable while one service was observed. It is not
survivable now — the second service exports ten metric names the first one also exports, six of
them `process_*`, including the two the resource panels query, with nothing but `job` and `instance`
separating them. On screen in 2026-08-20 the CPU panel showed two legend entries both reading
`CPU seconds`. The failure mode of this class of defect is a chart that looks correct, which is why
it survived a year of being looked at.

**The two services do not share a vocabulary, and never will.** The app is instrumented by
`prometheus-fastapi-instrumentator` and labels requests `handler` and `status`, the latter by class
(`2xx`, `4xx`); the Go service is instrumented by `client_golang` and labels them `code` and
`method`, by exact code and lowercase verb. That divergence was produced deliberately by the
previous feature and is the evidence the metrics-from-traces feature will consume; erasing it here
to make the queries tidy would destroy the thing it was created to prove. So the dashboard has to
hold both conventions at once, visibly, and the shape it finds for doing that is part of what this
feature delivers.

**Why rebuild rather than repair, and why now.** The roadmap enumerates seven defects in this file —
no service variable, a raw counter on the CPU panel, two panels sharing a `gridPos`, `type: "graph"`
instead of `timeseries`, a datasource referenced by name, a duplicated `refId`, and resource panels
without aggregation. Fixing them one at a time means touching every panel anyway, so they stop being
seven repairs and become the requirements of a new file, which is the cheaper of the two and the
only one that also fixes the format. And the next feature depends on this one: discovering targets
automatically is worth nothing while the dashboard cannot tell targets apart.

One advantage the 2026-08-10 reading had written off as lost is real and is used: **the current
dashboard draws.** It is a baseline. Every new panel can be checked against what the old one shows
rather than against the intent of whoever wrote it — provided the baseline is captured before the
file is replaced, because it exists only while that file is on disk.

## Scope

### In

- **A dashboard written from scratch**, at `grafana/dashboards/services.json`, titled
  `Services Overview`, under `uid: services-overview`, with `grafana/dashboards/fastapi_metrics.json`
  deleted in the same change. The identity moves in full because a dashboard stores no series:
  the reason that forbids renaming the `fastapi-app` scrape job — the history already keyed by that
  label — has no equivalent here, and leaving a file named after one of the two services it now
  describes would be a lie the next reader has to discover.
- **`uid: prometheus` in `grafana/provisioning/datasources/datasource.yaml`**, referenced as an
  explicit `{type, uid}` object by every target and also at panel level. Panel level too, because a
  panel with no datasource inherits the org default, and "there is only one datasource" is true
  today and is not a guarantee. This is requirement 5, and it is here rather than in the previous
  debt-closing feature precisely because the JSON is being reauthored: half of it would have been
  thrown away days later.
- **A service variable over `job`**, queried from `up` — the one series Prometheus synthesises for
  every target regardless of what the target exports, and therefore the only one the Node service of
  the next feature is guaranteed to have. Multi-select, with an `All` default. This is requirement 1.
  The existing `handler` variable is not repurposed: it separates routes, not services, and the
  roadmap warns in the requirement itself against confusing the two. A route variable survives, but
  chained to the service variable, so the dropdown stops listing two services' routes as though they
  belonged to one.
- **Three panel rows.** One cross-service row grouped by `job` — targets up, throughput, 4xx, 5xx,
  CPU as a rate, resident memory — and two convention rows, one for services that label routes and
  one for services that label response codes. Explicit `gridPos` and explicit unique `id` on every
  panel, which is requirements 3 and 4; unique `refId` within each panel, which is requirement 6;
  `by (job, instance)` and a legend naming both on the resource panels, which is requirement 7; and
  a rate on the CPU panel, which is requirement 2.
- **Three rules for how the two conventions coexist**, written into the spec because rediscovering
  them panel by panel is how they get broken:
  - **`job` goes inside every bucket grouping.** Not a legend preference. The two services' `le`
    sets share only `1` and `+Inf` — the app has four buckets, the Go service has the twelve
    `client_golang` defaults — so a grouping that omits `job` sums buckets from incompatible
    histograms and produces a number with no meaning. The rule survives the day two services agree
    on their buckets, because the third one will not.
  - **An error panel carries two targets, one per convention.** A single selector cannot do it:
    naming both labels is an `AND` no service satisfies, and any negative form silently matches the
    series that lack the label — verified in 2026-08-23, a `code!="200"` matcher returns the app's
    series, and the app carries no `code` at all. Two targets with the same legend format keep one
    chart and leave the divergence legible in the file, which is where the later feature will look
    for it.
  - **A convention row never names a job.** It selects on the presence of the label. That is what
    makes a new service appear on its own in the row that fits it, and it is the difference between
    a generic dashboard and one written for exactly two services that happens to work.
- **`$__rate_interval` on every rate**, rather than the fixed `[1m]` the current panels use, which
  breaks as soon as anyone changes the dashboard's time range.
- **A measured `schemaVersion`**, taken from a Grafana `12.4.7` UI export. Writing a number picked by
  hand would reproduce the exact defect this feature exists to remove: a file that declares one thing
  and relies on a migration to become another.
- **Content assertions in `tests/test_grafana_provisioning.py`** — no panel of type `graph`, unique
  panel ids, `refId` unique within a panel, no two `gridPos` overlapping, every target referencing
  the datasource by a uid the `datasource.yaml` actually declares, and the service variable present.
  The module docstring changes in the same commit, because the sentence saying nothing here looks at
  a query or a panel type stops being true.
- **A genericity guard**: no `job_name` read from `prometheus.yml` may appear verbatim in any panel
  expression. Read from the file rather than hard-coded, so the next feature inherits the guard
  without editing the test. It is what stands in for the third service that does not exist yet.
- **The baseline, captured in a browser before anything is edited** and recorded in `plan.md`:
  what each of the seven current panels draws, and how many series. It cannot be captured
  afterwards.
- **`CLAUDE.md` and `README.md` updated.** Four sentences name the dashboard today —
  `README.md:11`, `:102` and `:238`, and `CLAUDE.md:121`, the last one with the file path — and the
  rename makes all four false. Beyond the rename: what the panels separate and why, and the rule
  against summing buckets across jobs.

### Out

- **Widening the app's latency buckets.** The instrumentator's default gives the app four, so a
  2-second route lands in `+Inf` and the p95 reads a flat 1s — the panel has never measured latency
  above a second, and comparison with the Go service is only what made it visible. Measured
  2026-08-23 and recorded in the roadmap's "Pontas soltas do F2". It stays out because widening
  buckets is an instrumentation change that adds new `le` values to series already written to
  `prometheus_data`, and because the metrics-from-traces feature may retire that histogram outright.
  What this feature does instead is state the limitation in the p95 panel's own description: without
  it, a line that touches 1s and goes flat reads as a measurement when it is an artefact.
- **Reconciling the conventions at collection time.** No `metric_relabel_configs`, no recording
  rules. Renaming `code` to `status` in the scrape path would erase the evidence the previous
  feature was written to produce, and would make every new service need its own rule in the very
  file the next feature exists to stop editing.
- **Renaming the `fastapi-app` job**, for the reason already recorded: the series in
  `prometheus_data` are keyed by it, and symmetry buys nothing that pays for a split history.
- **A third service to prove the dashboard is generic.** That is the next feature's job. What is in
  scope here is the guard that would fail if the file stopped being generic.
- **Automatic target discovery, exemplars, alerting rules, and any trace or log panel.** Later
  features, each with its own verification.
- **A variable built on the response-code label.** `label_values` over it is polluted by
  `promhttp_metric_handler_requests_total`, which the Go client registers by default and which
  reports `500` and `503` without a single request having failed. The code panels query the request
  counter directly instead.
- **The documentation-drift gap in `tests/test_docs_versions.py`**, which only maps services
  declaring `image:`. It is real and it is recorded against the previous feature, and it belongs to
  whoever adds the next `Dockerfile`. This feature adds none.

## Expected behaviour

`docker compose --profile core --profile load up -d`, run against the **existing** `grafana_data`
rather than a fresh volume, brings the stack up with the four healthchecked services reporting
`healthy`. Grafana's datasource API returns one datasource, not two, and its uid is `prometheus`
rather than the value Grafana generated for itself. Its dashboard search returns `Services Overview`
and nothing else: the provider runs with `disableDeletion: false`, so removing the old file from
disk removes the dashboard it provisioned.

The dashboard opens with a service selector at the top. Every panel in the first row honours it,
including the two resource panels, which today ignore every filter that exists. Those two now draw
one line per target with a legend that names the job and the instance, instead of two lines both
called `CPU seconds`. The CPU panel shows a rate that rises and falls with the load generator rather
than a monotonic ramp.

Below that, each service appears in the row that matches its instrumentation, and in its own
vocabulary. The route row shows the app's named routes — including `none`, which is how the
instrumentator labels a 404, and including a flat ten-second heartbeat on `/health` that comes from
the healthcheck probes rather than from load. The code row shows the Go service's exact response
codes. Response classes on one side and exact codes on the other are not reconciled and are not
meant to be; the disagreement is legible on screen, which is the point. The two error panels stay
at `No data`, as they do today, because the load generator provokes no errors.

What stops happening is as important as what starts. Opening `Settings → JSON Model` no longer
marks the dashboard as having unsaved changes, because the stored model and the runtime model no
longer differ. No panel depends on a plugin the image does not ship. And `tox` fails if a future
edit reintroduces a `graph` panel, an overlapping `gridPos`, a duplicated `refId` inside a panel, a
datasource referenced by name, or a service name written into a query.

## Acceptance criteria

- [ ] **Requirement 1 — service selection.** The dashboard declares a `job` variable queried from
      `up`, and unselecting one service in it removes that service from every panel in the
      cross-service row, the two resource panels included.
- [ ] **Requirement 2 — CPU as a rate.** The CPU panel shows a rate that varies with load, not a
      monotonic climb, observed in a browser under load.
- [ ] **Requirement 3 — determined layout.** No two panels' `gridPos` rectangles overlap, asserted
      by a test; giving two panels the same position makes that test fail, and reverting makes it
      pass.
- [ ] **Requirement 4 — the file declares what it renders.** No panel is `type: "graph"`, every
      panel carries a unique `id`, and opening `Settings → JSON Model` in the browser does not mark
      the dashboard as having unsaved changes.
- [ ] **Requirement 5 — datasource by uid.** `datasource.yaml` declares `uid: prometheus`; the
      Grafana datasource API returns that uid and exactly one datasource; every target and every
      panel references the datasource by uid, asserted against the uid read from the yaml. Changing
      one target's uid makes exactly one test fail; reverting makes the suite green.
- [ ] **Requirement 6 — unique `refId`.** No panel repeats a `refId` among its own targets,
      asserted by a test. Repetition across panels stays legal and is not asserted against.
- [ ] **Requirement 7 — resource panels aggregated.** The CPU and memory panels draw one series per
      target with legends naming the job and the instance, and no two legend entries are identical.
- [ ] The baseline is captured in a browser **before** the current dashboard file is replaced —
      each of the seven panels, what it draws and how many series — and recorded in `plan.md`.
- [ ] Every panel is verified in a browser against that baseline, panel by panel, with the result
      recorded in `plan.md` as an observation. No API response is accepted as proof that a series
      drew: the API returns the stored model, the browser returns the migrated one, and the gap
      between them is what produced a wrong conclusion in this project once already.
- [ ] `job` appears inside the grouping of every panel that aggregates histogram buckets.
- [ ] Each error-rate panel carries one target per label convention, and no panel selects a
      convention with a negative matcher.
- [ ] The p95 panel's description states that the app's buckets cap its reading at one second, and
      points at where the measurement is recorded.
- [ ] No scrape job name from `prometheus.yml` appears verbatim in any panel expression: the guard
      test passes, and grepping the dashboard for either job name returns nothing.
- [ ] `tox` passes end to end — `py311` with the new assertions, `lint`, and `safety`.
- [ ] `docker compose --profile '*' config -q` exits without error and resolves five services.
- [ ] A `docker compose --profile core --profile load up -d` against the **existing**
      `grafana_data` reaches `healthy` for `app`, `service-go`, `prometheus` and `grafana`.
- [ ] Grafana's dashboard search returns `Services Overview` and does not return the old dashboard.
- [ ] The docstring of `tests/test_grafana_provisioning.py` no longer claims that nothing in the
      module looks at a query, a panel type or a panel's position.
- [ ] `CLAUDE.md` and `README.md` name the new dashboard, describe what the panels separate, and
      carry the rule against summing buckets across jobs; none of the four sentences naming the old
      dashboard survives.
- [ ] A CI run on the branch is green on all three jobs.
- [ ] `git diff --stat main...HEAD` names only the files this ticket's plan lists, plus the two
      documents of this ticket.
