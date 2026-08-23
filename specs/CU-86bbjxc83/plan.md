# CU-86bbjxc83 — Rebuild dashboard (plan)

Spec: [./spec.md](./spec.md)

## Context

Everything this feature touches is provisioning: `grafana/dashboards/` holds the dashboard JSON,
`grafana/provisioning/` holds the datasource and the file-provider that reads the first directory,
and `docker-compose.yml` bind-mounts both into the Grafana container read-only. No application code
changes. The service that produced the problem — `service-go`, on 8003 — was delivered by
CU-86bbdrkm7, and the series it exports are transcribed in that ticket's `plan.md`; this plan reads
them rather than remeasuring the ones it already recorded.

The current dashboard is `grafana/dashboards/fastapi_metrics.json`: seven panels, all
`type: "graph"`, `schemaVersion: 36`, no panel `id`, datasource referenced by the bare string
`"prometheus"`, and a single template variable `handler` that selects routes. It draws anyway,
because Grafana's frontend migrates the schema at load time. The seven numbered requirements the
rebuilt file has to satisfy are the ones `./spec.md` lists in its acceptance criteria; the panel
inventory and the query behind each panel are written out under the tasks below, so this plan is
the whole instruction and nothing has to be read alongside it.

The tests are `tests/test_grafana_provisioning.py`, four of them, all structural, and the module
docstring states in as many words that nothing there looks at a query, a panel type or a grid
position. That sentence is what this feature has to make false.

## Facts verified against the repo

Measured 2026-08-23 against the running stack — five containers, all four healthchecked ones
`healthy`, `loadgen` driving both services.

- **The app labels `status` by class and the Go service labels `code` by exact code.**
  `curl -s localhost:9090/api/v1/label/status/values` → `["2xx","4xx"]`;
  `.../label/code/values` → `["200","500","503"]`. The two legends will never have the same
  granularity.
- **Those `500` and `503` are not requests.** `match[]=promhttp_metric_handler_requests_total`
  returns exactly three series, all on `service-go:8003`, one per code — `client_golang` registers
  that collector by default and it measures the `/metrics` handler itself. A variable built on `code`
  would list failures that never happened.
- **The `le` sets differ in resolution, and one contains the other.** From
  `match[]=http_request_duration_seconds_bucket`: `fastapi-app` has `0.1, 0.5, 1.0, +Inf`;
  `service-go` has the twelve `client_golang` defaults, `0.005` through `10` plus `+Inf`. **Corrected
  2026-08-23, in review** — this first read "common bounds: `1.0` and `+Inf`", and that is wrong:
  all four of the app's bounds appear in the Go service's set, so the app's is a strict subset.
  Summing across jobs is still meaningless, for a reason the wrong version got right by accident —
  the merged histogram carries eight bounds the app never reports, so every bucket below `0.1`
  counts the Go service alone and the quantile describes neither service. That is what forces `job`
  into every bucket grouping.
- **A negative matcher matches the series that lack the label — measured, not reasoned.**
  `match[]=http_requests_total{code!="200"}` returns 8 series, **all of them `fastapi-app`**, and
  zero from `service-go`. The app carries no `code` label at all, so the matcher returned exactly
  the service it was meant to exclude and excluded the one it was meant to filter. `!=""` is the
  presence test.
- **`handler` has eight values:** `/`, `/health`, `/metrics`, the four `/load/*` routes, and `none`
  — the last is how the instrumentator labels a 404. The Go service contributes none of them: it
  carries no route label, which is why 15 series cover everything it exposes against the app's 145.
- **`job` has exactly two values**, `fastapi-app` and `service-go`, and
  `tests/test_prometheus_config.py::test_scrape_job_names_are_unique` already guarantees they stay
  distinct. That is what makes `job` usable as the separating axis without re-proving it here.
- **The provisioned datasource has a generated uid and is read-only.** `/api/datasources` returns
  `id: 1`, `uid: P1809F7CD0C75ACF3`, `name: prometheus`, `isDefault: true`, `readOnly: true` —
  generated because `datasource.yaml` declares only a name. `readOnly: true` means the uid cannot be
  changed through the UI or the API; the file plus a Grafana restart is the only path.
- **The API returns the stored model, not the migrated one.**
  `/api/dashboards/uid/fastapi-dashboard` answers `schemaVersion: 36`, `version: 1`, all seven
  panels `type: "graph"` and every `id` absent, while the browser shows `timeseries` with ids
  assigned. `meta.provisioned: true`, `meta.provisionedExternalId: fastapi_metrics.json`. Third
  confirmation of the method finding recorded against CU-86bbaf36c: only a browser answers
  "does it render?".
- **Grafana is `12.4.7`** (`/api/health`), which is the version whose UI export decides the
  `schemaVersion` written into the new file.
- **Grafana already holds a second, hand-made dashboard.** `/api/search?type=dash-db` returns two
  entries: `fastapi-dashboard` / *FastAPI Metrics* (provisioned) and `adgmx4s` / *T12 live test* —
  the latter created by hand during the F1 teardown verification and living in `grafana_data`. It
  is not provisioned and this feature does not touch it. It does mean the search endpoint will not
  return one row after the rebuild, and any verification written as "nothing else" would fail for
  the wrong reason.
- **The provider deletes what it no longer finds.** `grafana/provisioning/dashboards/dashboard.yml`
  sets `disableDeletion: false` and reads `/var/lib/grafana/dashboards`; compose mounts
  `./grafana/dashboards` there `:ro`, and `updateIntervalSeconds` is unset, so the default poll
  applies to dashboard files. Datasource provisioning, by contrast, runs at startup.
- **The current file's defects are all present as described.** Seven `graph` panels, no `id`,
  datasource as the string `"prometheus"`, `[1m]` windows, `CPU Usage` querying
  `process_cpu_seconds_total` raw with the static legend `CPU seconds`, and the `5xx` and `4xx`
  panels sharing both `gridPos {x:0,y:24,w:24,h:8}` and `refId: "F"`.
- **The guard test cannot reuse the existing config fixture.** `prometheus_config` is defined inside
  `tests/test_prometheus_config.py`, not in `conftest.py`, so it is not visible to another module.
  Only `repo_root` is shared.
- **Four sentences in prose name the dashboard:** `README.md:11`, `:102`, `:238` and `CLAUDE.md:121`,
  the last carrying the file path. The rename makes all four false.

## Affected files

| File | Change |
| --- | --- |
| `grafana/dashboards/services.json` | new — the rebuilt dashboard: two variables, three rows, fourteen panels |
| `grafana/dashboards/fastapi_metrics.json` | removed |
| `grafana/provisioning/datasources/datasource.yaml` | gains `uid: prometheus` |
| `tests/test_grafana_provisioning.py` | content assertions plus the genericity guard; module docstring rewritten |
| `CLAUDE.md` | the new path, what the panels separate, and the rule against summing buckets across jobs |
| `README.md` | the three sentences naming the old dashboard, and the panel description |

## Tasks

One commit per task; the checkbox is ticked in the same commit. Any sentence in `CLAUDE.md` or
`README.md` that a task makes false is corrected inside that task's commit — the two documentation
tasks at the end add what is new, they do not repair what earlier tasks broke.

- [x] **Capture the baseline.** With the stack up and the current file still on disk, open the
      dashboard in a browser and record, panel by panel: what it draws, how many series, and what
      the legend reads. Seven panels; the two error panels are expected at `No data`. Also record
      that `Settings → JSON Model` currently marks the dashboard as having unsaved changes, since
      that is the before half of requirement 4's proof. No code, and **before** any edit — the
      baseline exists only while `fastapi_metrics.json` is the provisioned file.
      Done: captured 2026-08-23 at 17:01 local, on a 5-minute window with `loadgen` running,
      against the existing volumes. **All seven panels render**, series counts read off the legend
      buttons in the DOM rather than eyeballed:

      | # | Panel | Series drawn | Distinct legend labels | Legend |
      | --- | --- | --- | --- | --- |
      | 1 | Request Latency (p95) | 5 | 5 | the four `/load/*` routes plus `/health` |
      | 2 | Request Throughput (req/s) | 5 | 5 | same five |
      | 3 | CPU Usage | 2 | **1** | `CPU seconds`, `CPU seconds` |
      | 4 | Memory Usage (bytes) | 2 | **1** | `Memory`, `Memory` |
      | 5 | HTTP Status Codes per Endpoint | 5 | 5 | `<route> - 2xx` |
      | 6 | 5xx Error Rate by Handler | 0 | 0 | `No data` |
      | 7 | 4xx Error Rate by Handler | 0 | 0 | `No data` |

      Panels 3 and 4 are requirement 7's before-state with a number on it: two series, one label.
      Panel 1 shows `/load/stress/{seconds}` pinned flat at exactly **1.0** for the whole window —
      the bucket cap, visible on screen. Panel 3 climbs monotonically 0 → 27 with no relation to
      load, which is requirement 2's before-state.
      **The `gridPos` collision does not overlap on screen.** Panels 6 and 7 both declare
      `{x:0, y:24}` and the layout engine stacks them: measured page offsets 1057 px and 1361 px,
      296 px tall each. The earlier reading that the file does not determine the layout is
      reconfirmed, and "overlap" remains the wrong word for it.
      **The runtime model against the stored model, read side by side in the same page:** the
      settings editor holds `schemaVersion: 42`, all seven panels `timeseries`, ids `1..7`; the API
      returns `schemaVersion: 36`, all seven `graph`, every id absent. That answers the question
      this plan left open — **42 is the migration target of Grafana `12.4.7`, measured rather than
      inferred from the bundle.** Two defects survive the migration untouched: panels 6 and 7 keep
      `{x:0, y:24}` and both keep `refId: "F"`. One more does too, and it was not predicted:
      the migrated model still carries `"datasource": "prometheus"` as a bare string, so nothing in
      the migration path would ever have fixed requirement 5.
      **The unsaved-changes symptom did not reproduce, and the task's own premise is what fell.**
      Opening `Settings → JSON Model`, then `Back to dashboard`, then `Exit edit` returned to the
      read-only view with **no unsaved-changes prompt**. The dashboard enters edit mode and a
      `Save dashboard` button appears, but leaving costs nothing. The likely mechanism: Grafana
      migrates the stored JSON on load and keeps the *migrated* model as its baseline for the dirty
      check, so a stored-versus-runtime divergence is invisible to that comparison by construction.
      Consequence for requirement 4: the criterion as approved cannot distinguish before from after,
      because its "before" is already clean. The proof that does work is the one measured above —
      the stored file and the runtime model agreeing on `schemaVersion`, panel type and ids — and
      the verification step is rewritten to that.
      Commit: `docs(specs): record the dashboard baseline before the rebuild`
- [x] **Give the datasource an explicit uid.** Add `uid: prometheus` to
      `grafana/provisioning/datasources/datasource.yaml`, and assert in
      `tests/test_grafana_provisioning.py` that every provisioned datasource declares a uid. The
      cross-check between that uid and the dashboard's targets belongs to the assertions task, not
      here: at this point the dashboard still references the datasource by name, and asserting the
      link now would fail for a reason this task did not cause. Restart Grafana and confirm through
      `/api/datasources` that the uid changed in place against the **existing** volume; if
      provisioning refuses to update a `readOnly` datasource, add the planned `deleteDatasources:`
      block to the same file and record which of the two paths was needed.
      Done: **the planned exit was needed, and the failure it guards against is harder than this
      plan predicted.** Adding `uid: prometheus` alone does not fail to update in place — it stops
      Grafana from starting at all. Measured 2026-08-23: the container entered a restart loop and
      the log read `Failed to provision data sources … Datasource provisioning error: data source
      not found`, followed by `starting module provisioning: invalid service state: Failed`. The
      mechanism is that Grafana matches the existing datasource by name, then looks it up by the
      *new* uid in order to update it, does not find it, and aborts the whole provisioning module
      rather than that one datasource. With the `deleteDatasources:` block in front, the same
      restart came up in **~6 s**, `healthy`, with zero `level=error` lines in the boot, one
      datasource, `uid: prometheus`, `isDefault: true`, `readOnly: true` — and `id: 2`, because
      delete-then-insert recreates the row rather than editing it. The block stays in the file
      permanently: on a volume provisioned before this change it is what makes Grafana boot, and on
      a fresh volume it is a no-op. A comment beside it says exactly that, because a future reader
      finding a `deleteDatasources:` for the only datasource in the file would otherwise read it as
      leftover debris.
      Checked in the same restart, since it is what the ordering of this task depends on: the old
      dashboard still resolves. It references the datasource by the bare name `prometheus`, and
      Grafana matches that against the name whatever the uid is, so the panels kept drawing —
      `up` through the datasource proxy returns both jobs. That is why the assertion linking the
      dashboard's targets to this uid belongs to the assertions task and not to this one.
      Commit: `feat(grafana): give the provisioned datasource an explicit uid`
- [x] **Rebuild the dashboard.** Create `grafana/dashboards/services.json` with `uid:
      services-overview`, title `Services Overview`, every target and every panel referencing the
      datasource as `{"type": "prometheus", "uid": "prometheus"}`, explicit unique `id`, explicit
      non-overlapping `gridPos`, and `$__rate_interval` on every rate. Delete `fastapi_metrics.json`
      in the same commit. Two variables:

      | Variable | Query | Why |
      | --- | --- | --- |
      | `job` | `label_values(up, job)` | multi, `includeAll`, default `All`. `up` is synthesised for every target whatever it exports, so it is the one series a future service is guaranteed to have |
      | `handler` | `label_values(http_requests_total{job=~"$job", handler!="", handler!="/metrics"}, handler)` | chained on `$job`, so the dropdown stops listing two services' routes as one set. `handler!=""` is what empties it when only services without that label are selected |

      One `row` panel, *Services*, and the six cross-service panels under it:

      | Panel | Expression | Legend |
      | --- | --- | --- |
      | Targets up | `up{job=~"$job"}` | `{{job}} — {{instance}}` |
      | Throughput by service | `sum by (job) (rate(http_requests_total{job=~"$job"}[$__rate_interval]))` | `{{job}}` |
      | 5xx error rate | two targets: `sum by (job) (rate(http_requests_total{job=~"$job", status=~"5.."}[$__rate_interval]))` and the same with `code=~"5.."` | `{{job}}` on both |
      | 4xx error rate | the same pair with `4..` | `{{job}}` on both |
      | CPU by service | `rate(process_cpu_seconds_total{job=~"$job"}[$__rate_interval])` | `{{job}} — {{instance}}` |
      | Resident memory | `process_resident_memory_bytes{job=~"$job"}` | `{{job}} — {{instance}}` |

      **The `schemaVersion` is measured, not chosen:** let Grafana load the hand-written file, then
      `Export → Export as JSON` with *export for sharing externally* **off**, and adopt the exported
      model as the file after confirming it kept the queries, ids and positions that were written.
      Anything else leaves the stored model differing from the runtime one, which is the defect this
      feature exists to remove. **Every string the dashboard puts on screen is in English** — panel
      titles, row titles, variable labels and panel descriptions — the same rule the rest of the
      repository follows.
      Done: **the file and the runtime model are now byte-identical**, comparing the settings
      editor's model against `/api/dashboards/uid/services-overview` with `id` and `version` — the
      two fields the database assigns — removed from both, and every object key sorted. 6154
      characters each way, no first differing index. That is requirement 4 in its strongest form,
      and it replaces the unsaved-changes symptom that task 1 showed does not reproduce.
      **The export loop cost three passes and none of them was the `schemaVersion`.** That number
      was already measured in task 1 — `42`, read off the old dashboard's runtime model — so the
      hand-written file carried it from the start and matched. What Grafana adds that a hand-written
      file has no way to guess is smaller and duller: four top-level defaults
      (`fiscalYearStartMonth: 0`, `preload: false`, `timepicker: {}`, `weekStart: ""`), the built-in
      `Annotations & Alerts` entry that every dashboard gets whether its file declares it or not,
      and `regexApplyTo: "value"` on each query variable. The old file declared none of these
      either. Convergence is iterative by nature: each pass reveals only the next divergence, so
      budget more than one for task 4.
      **What the six panels draw**, read from the DOM with `loadgen` running:

      | Panel | Series | Distinct labels | Legend |
      | --- | --- | --- | --- |
      | Targets up | 2 | 2 | `fastapi-app — app:8002`, `service-go — service-go:8003` |
      | Throughput by service | 2 | 2 | `fastapi-app`, `service-go` |
      | CPU by service | 2 | 2 | `fastapi-app — app:8002`, `service-go — service-go:8003` |
      | 5xx error rate | 0 | 0 | `No data`, as expected |
      | 4xx error rate | 0 | 0 | `No data`, as expected |
      | Resident memory | 2 | 2 | `fastapi-app — app:8002`, `service-go — service-go:8003` |

      Against the baseline: the two resource panels went from two series under one label to two
      series under two, which is requirement 7; the CPU panel went from a monotonic climb to a rate
      oscillating between 10% and 15% with the load, which is requirement 2.
      **Requirement 1, proven by selection rather than by reading the JSON:** loading with
      `var-job=service-go` drops every cross-service panel to a single series — the two resource
      panels included, and those are the ones the old dashboard could not filter at all.
      **The provider deleted the old dashboard on its own.** Removing `fastapi_metrics.json` from
      disk made `/api/dashboards/uid/fastapi-dashboard` return `Dashboard not found` within ~5 s,
      with no restart. `disableDeletion: false` behaves as the plan read it.
      Commit: `feat(grafana): rebuild the dashboard for multiple services`
- [x] **Add the per-convention rows.** Two `row` panels and the five panels under them, selected by
      label presence and never by job name, with `job` inside every bucket grouping:

      | Row | Panel | Expression |
      | --- | --- | --- |
      | Routes (`handler`) | p95 by route | `histogram_quantile(0.95, sum by (le, job, handler) (rate(http_request_duration_seconds_bucket{job=~"$job", handler!="", handler=~"$handler", handler!="/metrics"}[$__rate_interval])))` |
      | Routes (`handler`) | Throughput by route | `sum by (job, handler) (rate(http_requests_total{job=~"$job", handler!="", handler=~"$handler", handler!="/metrics"}[$__rate_interval]))` |
      | Routes (`handler`) | Status codes by route | `sum by (job, handler, status) (rate(http_requests_total{job=~"$job", handler!="", handler=~"$handler", handler!="/metrics"}[$__rate_interval]))` |
      | Requests (`code`) | p95 by code | `histogram_quantile(0.95, sum by (le, job, code) (rate(http_request_duration_seconds_bucket{job=~"$job", code!=""}[$__rate_interval])))` |
      | Requests (`code`) | Throughput by code and method | `sum by (job, code, method) (rate(http_requests_total{job=~"$job", code!=""}[$__rate_interval]))` |

      The route row's p95 panel carries in its own `description` field the limitation stated in
      full, not a pointer: the FastAPI app exposes four latency buckets — `0.1`, `0.5`, `1.0`,
      `+Inf` — so any route slower than one second falls in `+Inf` and this panel reads a flat 1s
      for it. The text has to stand on its own, because it is read inside Grafana by someone with no
      access to this repository. Re-export and re-adopt as in the previous task.
      Done: **the query table above was wrong when this plan was written, and the error was the one
      this feature exists to fix.** The route panels selected with `handler=~"$handler"` and no
      presence test. With the variable on `All`, Grafana substitutes `.*`, and `.*` matches a series
      that carries no `handler` label at all — so measured 2026-08-23, that grouping returned six
      series: the app's five named routes plus `('service-go', <no label>)`, the whole Go service
      collapsed into one unlabelled group. That is verbatim the defect the baseline recorded in the
      old dashboard. `handler!=""` is required in every route panel, not only in the variable's own
      query; with it the same grouping returns five, all `fastapi-app`. The table is corrected
      above. The spec never had this wrong — it says the convention rows select by label presence —
      so this was the plan's transcription, and worth stating because the query reads correct.
      **The two conventions on screen, side by side, with no job name anywhere in the file:**

      | Panel | Series | Legend |
      | --- | --- | --- |
      | p95 by route | 5 | `fastapi-app — /health`, and the four `/load/*` |
      | Throughput by route | 5 | the same five |
      | Status codes by route | 5 | `fastapi-app — /load/io-bound — 2xx`, and so on |
      | p95 by code | 1 | `service-go — 200` |
      | Throughput by code and method | 1 | `service-go — get 200` |

      `2xx` on one row and `200` on the other, `get` in lowercase — the divergence is legible on
      screen and in the file, which is what the later feature needs from it. Each service appears in
      exactly the row that fits its instrumentation, and neither query names a job.
      **The bucket debt turned out to be visible without reading anything.** The two p95 panels sit
      one above the other, and both services run a 2-second `/load/io-bound`: the route row reads a
      flat **1s** for the app, the code row reads **~2.2s** for the Go service. The same latency,
      one measured and one capped. That comparison is a better argument for widening the app's
      buckets than the sentence in the panel description, and it exists only because the dashboard
      now puts the two conventions on one page.
      **Byte-identity held on the first pass this time** — 11344 characters both ways, fourteen
      panels, ids `1..14`. The three convergence passes task 3 needed bought this: panels of the
      same shape inherit the defaults that were already discovered.
      **One trap worth writing down, and it is not the file's fault.** After a forced navigation
      that discarded a "Leave site?" dialog, the dashboard rendered with its row titles and no
      panels at all — which reads exactly like a broken JSON. A plain reload rendered everything.
      The scene state was stale, not the file; check with a clean load before believing a blank
      dashboard.
      Commit: `feat(grafana): add the per-convention panel rows`
- [x] **Assert the dashboard declares what it renders.** In `tests/test_grafana_provisioning.py`:
      no panel of type `graph`; every panel carries an `id` and the ids are unique; `refId` unique
      **within** each panel and free to repeat across panels; no two `gridPos` rectangles intersect;
      every target and every panel references the datasource by a uid that `datasource.yaml`
      actually declares; and the dashboard declares a `job` variable. Panel iteration walks nested
      `panels`, because a collapsed row carries its children inside itself and a flat loop would
      skip them. Rewrite the module docstring: the sentence saying nothing here looks at a query, a
      panel type or a grid position stops being true in this commit.
      Done: six new tests, eleven in the file, and **every one of them proved by breaking the
      dashboard on purpose** — each probe applied one defect, ran the suite, and was reverted:

      | Defect introduced | Test that failed |
      | --- | --- |
      | a panel typed `graph` | `test_no_panel_uses_the_retired_graph_type` |
      | a panel with its `id` removed | `test_every_panel_declares_a_unique_id` |
      | two panels sharing an `id` | `test_every_panel_declares_a_unique_id` |
      | a `refId` repeated inside one panel | `test_ref_ids_are_unique_within_each_panel` |
      | two panels given the same `gridPos` | `test_no_two_panels_share_grid_space` |
      | a target's datasource written as the bare name | `test_every_query_references_a_declared_datasource_uid` |
      | a uid the `datasource.yaml` does not declare | `test_every_query_references_a_declared_datasource_uid` |
      | the `job` variable removed | `test_every_dashboard_declares_the_service_variable` |

      Eight probes, eight single failures, each the intended one. The docstring's claim about
      collapsed rows was proved the same way rather than asserted: none of this dashboard's three
      rows is collapsed, so a ninth probe collapsed one, moved a `graph` panel inside it, and
      confirmed `test_no_panel_uses_the_retired_graph_type` still catches it. A flat loop over the
      top-level list would have passed that file.
      Two scoping decisions worth the words. **Row panels are exempt from the datasource
      assertion**: a `row` carries no query and Grafana's own migrated model gives it no datasource,
      so requiring one would fail against the very model the file was converged to. And the
      **`gridPos` intersection check reads only the top-level list**, because coordinates inside a
      collapsed row are relative to that row rather than to the dashboard grid — comparing the two
      sets would produce false collisions.
      Commit: `test(grafana): assert the dashboard declares what it renders`
- [x] **Forbid literal job names in queries.** A test that reads the `job_name` values out of
      `prometheus.yml` and asserts none appears verbatim in any panel `expr`. It parses the file in
      its own session-scoped fixture rather than moving `prometheus_config` into `conftest.py`:
      promoting a fixture is a refactor of a file this feature has no other reason to touch. Read
      from the file, never hard-coded, so the next feature's service inherits the guard without
      editing the test.
      Done: `test_no_query_names_a_scrape_job`, twelve tests in the file. It reads the job names
      out of `prometheus.yml` in its own session-scoped fixture, for the reason recorded above —
      `prometheus_config` belongs to the module that tests that file and is not importable from
      here — and the duplicated two-line load is cheaper than promoting a fixture into
      `conftest.py`, which would edit a file this feature otherwise leaves alone.
      **It covers variable queries as well as panel expressions**, which is one step past what this
      plan asked for. A variable defined as `label_values(http_requests_total{job="service-go"}, …)`
      locks the dashboard to a service exactly as firmly as a panel does, and it is the more likely
      place to write one by accident because the variable is where a service name feels natural.
      What it deliberately does not read is panel titles and descriptions: naming a service in
      prose is documentation, not coupling, and forbidding it would have made the descriptions
      written in task 4 illegal.
      Proved by three probes, each reverted:

      | Probe | Result |
      | --- | --- |
      | a panel `expr` filtered on `job="fastapi-app"` | fails, only this test |
      | a variable query filtered on `job="service-go"` | fails, only this test |
      | a `service-node` job added to `prometheus.yml`, and a panel filtered on it | fails, only this test |

      The third is the one that matters, and it is the closest this feature can get to proving
      genericity without a third service: the guard caught a job name it had never been told about,
      because it had read it from the scrape configuration a moment earlier. The next feature adds
      that service for real and inherits the guard without touching this file.
      Commit: `test(grafana): forbid literal job names in panel queries`
- [x] **Document it in `CLAUDE.md`.** The new path, the three panel rows and what separates them,
      the rule that `job` belongs inside every bucket grouping, and why a convention row never names
      a job. Conclusions only — the derivation stays in this plan.
      Done: one new `**The dashboard.**` block in the architecture section, plus two sentences
      elsewhere that this feature made false. `**Observability wiring.**` named
      `fastapi_metrics.json`; the `### Infra checks` paragraph said the four infra test files "say
      nothing about whether a query returns data or a dashboard panel is correct", which stopped
      being true in task 5 — it now separates the three that stayed purely structural from
      `test_grafana_provisioning.py`, which does read panel types, ids, positions, datasource
      references and queries, and keeps the part that still holds: none of them proves a panel drew.
      **Written twice, because the first draft was 243 words** against 45, 53, 124 and 58 for its
      neighbours in the same section — the shape the earlier debt-closing feature flagged as out of
      proportion. Trimmed to 170 with no fact dropped: what went was restatement, not content. The
      three coexistence rules, the presence-test trap, the p95 cap and the `deleteDatasources:`
      requirement are all still there, one clause of reasoning each; the measurements behind them
      stay here.
      Commit: `docs: document the multi-service dashboard`
- [x] **Update `README.md`.** The three sentences naming *FastAPI Metrics*, including the project
      layout line, and a description of what the rebuilt dashboard shows.
      Done: the three renames — the `grafana` bullet in "How it works", the teardown paragraph and
      the project-layout line — plus the panel description, which now names the three rows and the
      `Service` dropdown instead of listing six panel titles.
      **A fourth thing was false and was not on the list.** The endpoint table has a column
      *"Dashboard panel it feeds"*, and every value in it was an old panel title: `Request latency`,
      `CPU usage` twice, `Memory usage`. They now read `p95 by route`, `CPU by service` and
      `Resident memory`. `/health` was marked `—`, meaning it fed nothing; that was true while the
      dashboard filtered it out and stopped being true when the route panels started showing it, so
      it now reads "Throughput by route — the flat 10s baseline", which is also where a reader meets
      the healthcheck traffic the architecture notes warn about.
      Left alone deliberately: the teardown proof that tells the reader to build a dashboard by hand
      and confirm it survives a `down`. It is about hand-made dashboards, not provisioned ones, and
      the *T12 live test* dashboard sitting in `grafana_data` is what someone following those steps
      leaves behind. The `deleteDatasources:` trap is not in `README.md` either: it bites whoever
      edits the provisioning file, not whoever brings the stack up, and `CLAUDE.md` carries it.
      Commit: `docs: update the readme for the services dashboard`
- [x] **Run the verification script and record every outcome below.** No commit beyond the tick.

## Edge cases

- **Changing a provisioned datasource's uid is the only change here that touches state, and it is
  a hard boot failure, not a silent one.** Measured in task 2 against the populated volume: adding
  a `uid` to a datasource Grafana had already provisioned under a generated one aborts the entire
  provisioning module and the container never becomes healthy. The `deleteDatasources:` block is
  not a fallback to reach for if something looks wrong — it is required, and it stays in the file.
  This is also why the verification runs against the existing volume: a fresh one would have come
  up clean and hidden the failure completely.
- **A datasource change needs a Grafana restart; a dashboard change does not.** Datasource
  provisioning runs at startup. The dashboard provider polls the mounted directory, so editing the
  JSON on the host is picked up without a restart.
- **`Export as JSON` has a sharing mode that would break requirement 5.** With *export for sharing
  externally* on, Grafana replaces the datasource with a `${DS_PROMETHEUS}` input and adds
  `__inputs`/`__requires`. That is the opposite of referencing a fixed uid. The export must be the
  plain one, and the adopted file must be grepped for `__inputs` before it is committed.
- **Grafana holds a hand-made dashboard the rebuild does not touch.** *T12 live test*, uid
  `adgmx4s`, lives in `grafana_data` from an earlier feature's verification. The search endpoint
  will therefore return two dashboards after the rebuild. The check is that *FastAPI Metrics* is
  gone and *Services Overview* is present — not that the list has one row. Spec's "and nothing
  else" is read that way.
- **Removing the old JSON depends on the provider to remove the dashboard.** `disableDeletion:
  false` says it should. If it does not, two dashboards survive and the stale one is the one in the
  browser history of anyone who already opened it. It is a verification step, not an assumption.
- **A negative matcher matches series without the label.** Measured above: `code!="200"` returned
  only `fastapi-app`. Every convention row selects with `!=""`, and no cross-service panel uses a
  negative form on a convention label.
- **Summing buckets across jobs produces a meaningless number.** Not because the `le` sets are
  disjoint — the app's four bounds are all present in the Go service's twelve — but because the
  merged histogram then carries bounds only one service reports. Any `by (le, …)` without `job`
  inside is a defect, not a style choice.
- **The app's p95 is capped at one second** by its own bucket resolution — its four buckets end at
  `1.0` before `+Inf`, and widening them is instrumentation work this feature excludes. Measured
  2026-08-23, and stated in full in the panel description by task 4. Without that note, a line that
  touches 1s and flattens reads as a measurement when it is an artefact.
- **`2xx` on one side and `200` on the other.** The route row shows classes and the code row shows
  exact codes. Not reconcilable without rewriting instrumentation, which is what the previous
  feature decided against.
- **`handler="none"` shows up in the route panels.** It is how the app labels a 404, one series
  today. Not filtered out: a recurring 404 is exactly what someone would want to see.
- **`label_values` over `code` is polluted** by `promhttp_metric_handler_requests_total`, which
  reports `500` and `503` with no request having failed. No variable is built on `code`; the code
  panels query the request counter directly.
- **The ten-second `/health` heartbeat is inherited from CU-86bbdrkm7** and shows up in the route
  and throughput panels at roughly 0.1 req/s per service. It is probe traffic, not load, and
  `CLAUDE.md` already says so.
- **`$__rate_interval` varies with panel width.** With a 5s scrape it never drops below the safe
  minimum, which is why it beats a fixed `[1m]`, but two panels at different zooms can smooth the
  same metric differently. Behaviour, not defect.
- **The API cannot answer "does it render?".** It returns the stored model. Every panel-level
  verification is done in a browser.
- **`$__rate_interval` is derived from the datasource, not from `prometheus.yml`.** Found in review,
  2026-08-23: the provisioned datasource declared no `jsonData.timeInterval`, so Grafana assumed its
  own 15s default against a 5s scrape and floored every rate window in the dashboard at 60s —
  invisible until someone zooms in expecting to see a burst. Declaring `timeInterval: 5s` duplicates
  a value that lives in `prometheus.yml`, which is the drift shape this project has been bitten by
  before, so `test_datasource_time_interval_matches_the_scrape_interval` holds the two together.
- **The app instruments its own `/metrics` route and the Go service does not.** Measured in review:
  0.200 req/s of the app's 0.857, against 0.514 for the Go service — a fifth of one side of the
  panel that exists to compare them, and none of the other. The cross-service throughput panel
  filters it out. This is the one place a negative matcher on a convention label is correct rather
  than a trap: `handler!="/metrics"` keeps every series that carries no `handler` at all, which is
  exactly the services the filter must not touch.
- **`deleteDatasources:` runs on every boot, so it orphans hand-made dashboards once.** The
  `T12 live test` dashboard in `grafana_data` points at `{"uid": "P1809F7CD0C75ACF3"}`, the uid this
  feature deleted, and its panels come back without a datasource. `README.md` promised that
  hand-made dashboards survive a `down`; it now carries the one-off exception beside that promise.
- **New test code is Python and goes through `tox -e lint`** — black at 88 columns and flake8
  configured to match. The JSON file is not linted by anything except the tests written here.
- **Markdownlint** on the `CLAUDE.md` and `README.md` edits: compact tables (MD060), blank lines
  around lists and fences, checked in the VS Code Problems panel.

## Verification steps

Run 2026-08-23, against the volumes that already existed. Every step carries what it returned.

1. `tox` — **green end to end.** `py311` 46 passed after the review round (45 before it), coverage 100% against the 80% gate; `lint`
   clean on black, isort and flake8; `safety` reports no known vulnerabilities in either
   `requirements/base.txt` or `requirements/dev.txt`, audited separately as the convention requires.
   43.6 s total.
2. `docker compose --profile '*' config -q` — **exits clean**, and `config --services` resolves
   **five**: `prometheus service-go app grafana loadgen`.
3. A full `--profile '*' down` followed by `--profile core --profile load up -d` against the
   **existing** volumes — both named volumes survived the `down`, and all four healthchecked
   services reached `healthy` **within 10 s**. Prometheus still answered for the window before the
   teardown, so no history was lost. Worth recording next to the ninety-second `start_period` this
   project measured for a cold Grafana: against a populated volume the migrations are already
   applied and it comes up in seconds. The `start_period` is sized for the case that is slow, not
   for this one.
4. **Requirement 5** — `/api/datasources` returns **one** datasource, `uid: prometheus`,
   `isDefault: true`, `readOnly: true`. Its `id` moved 1 → 2 → 3 across the restarts of tasks 2 and
   this step, which is `deleteDatasources:` doing exactly what it says on every boot: the row is
   recreated rather than edited. Zero `level=error` lines in the boot, so the delete-then-insert is
   idempotent and not a one-time repair.
5. `/api/search?type=dash-db` returns `services-overview | Services Overview`, and **no longer
   returns** `fastapi-dashboard`. `adgmx4s | T12 live test` is still there, as the plan predicted —
   it is hand-made, lives in `grafana_data`, and nothing here touches it.
6. **Panel by panel in a browser, against the baseline captured in task 1** — eleven panels, all
   eleven behaving:

   | Panel | Series | Distinct labels | Against the baseline |
   | --- | --- | --- | --- |
   | Targets up | 2 | 2 | new panel |
   | Throughput by service | 2 | 2 | was one line per route, no service axis |
   | CPU by service | 2 | 2 | was 2 series under one label, `CPU seconds` twice |
   | 5xx error rate | 0 | — | `No data`, as before and as expected |
   | 4xx error rate | 0 | — | `No data`, as before and as expected |
   | Resident memory | 2 | 2 | was 2 series under one label, `Memory` twice |
   | p95 by route | 5 | 5 | was 5 unqualified route names; now each carries its job |
   | Throughput by route | 5 | 5 | same |
   | Status codes by route | 5 | 5 | same |
   | p95 by code | 1 | 1 | new row — the Go service had nowhere to appear before |
   | Throughput by code and method | 1 | 1 | new |

   Only `fastapi-app` appears in the route row and only `service-go` in the code row, with no job
   name anywhere in the file.
7. **Requirement 4** — the settings editor's model and `/api/dashboards/uid/services-overview` are
   **byte-identical**: 11344 characters each, `schemaVersion: 42` on both sides, panel types only
   `row` and `timeseries`, ids `1..14`. `grep -c '__inputs'` on the file returns 0, so the adopted
   export is the plain one and not the share-externally form that would have replaced the datasource
   with an input.
8. **Requirement 1** — loading with `var-job=service-go` leaves exactly one series in every
   cross-service panel, the two resource panels included. The route row goes empty at the same time,
   which is the chained `handler` variable behaving: its query is scoped to `$job`, and the Go
   service carries no route label.
9. **Requirement 7** — CPU and memory each draw two series with distinct legends,
   `fastapi-app — app:8002` beside `service-go — service-go:8003`.
10. **Requirement 2** — the CPU panel oscillates between roughly 7% and 16% and dips at 18:04 in
    step with the throughput panel. A rate reacting to load, where the baseline recorded a
    monotonic climb from 0 to 27.
11. **Requirement 6** — read from the runtime model rather than the file: refIds per panel are
    `-, A, A, A, AB, AB, A, -, A, A, A, -, A, A`. The two error panels carry two targets each under
    distinct refIds, and the rows carry none.
12. **Genericity** — `test_no_query_names_a_scrape_job` passes, and
    `grep -o 'fastapi-app\|service-go' grafana/dashboards/services.json` returns nothing.
13. **Requirement 3, negative proof** — giving two panels the same `gridPos` fails
    `test_no_two_panels_share_grid_space` and nothing else; reverted, suite green.
14. **Requirement 5, negative proof** — pointing one target at a uid the `datasource.yaml` does not
    declare fails `test_every_query_references_a_declared_datasource_uid` and nothing else;
    reverted, suite green.
15. CI on the branch — **green on all three jobs** (run 32666722315, PR #6): `go` 13 s, `infra`
    13 s, `build` 55 s, no Node deprecation annotations. `infra` matters most here: it is the job
    that runs `promtool check config` and `docker compose config -q` against the real binaries, and
    it passed with the rewritten provisioning.
16. `git diff --stat main...HEAD` names **exactly** the six files in "Affected files" plus this
    ticket's two documents, and nothing else. `git show --stat` on each of the eleven commits names
    only that task's files.
