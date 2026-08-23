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
- **The `le` sets diverge and share almost nothing.** From
  `match[]=http_request_duration_seconds_bucket`: `fastapi-app` has `0.1, 0.5, 1.0, +Inf`;
  `service-go` has the twelve `client_golang` defaults, `0.005` through `10` plus `+Inf`. Common
  bounds: `1.0` and `+Inf`. Summing across jobs is meaningless, which is what forces `job` into
  every bucket grouping.
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
- [ ] **Rebuild the dashboard.** Create `grafana/dashboards/services.json` with `uid:
      services-overview`, title `Services Overview`, every target and every panel referencing the
      datasource as `{"type": "prometheus", "uid": "prometheus"}`, explicit unique `id`, explicit
      non-overlapping `gridPos`, and `$__rate_interval` on every rate. Delete `fastapi_metrics.json`
      in the same commit. Two variables:

      | Variable | Query | Why |
      | --- | --- | --- |
      | `job` | `label_values(up, job)` | multi, `includeAll`, default `All`. `up` is synthesised for every target whatever it exports, so it is the one series a future service is guaranteed to have |
      | `handler` | `label_values(http_requests_total{job=~"$job", handler!="", handler!="/metrics"}, handler)` | chained on `$job`, so the dropdown stops listing two services' routes as one set. `handler!=""` is what empties it when only services without that label are selected |

      One `row` panel, *Serviços*, and the six cross-service panels under it:

      | Panel | Expression | Legend |
      | --- | --- | --- |
      | Alvos no ar | `up{job=~"$job"}` | `{{job}} — {{instance}}` |
      | Throughput por serviço | `sum by (job) (rate(http_requests_total{job=~"$job"}[$__rate_interval]))` | `{{job}}` |
      | Taxa de 5xx | two targets: `sum by (job) (rate(http_requests_total{job=~"$job", status=~"5.."}[$__rate_interval]))` and the same with `code=~"5.."` | `{{job}}` on both |
      | Taxa de 4xx | the same pair with `4..` | `{{job}}` on both |
      | CPU por serviço | `rate(process_cpu_seconds_total{job=~"$job"}[$__rate_interval])` | `{{job}} — {{instance}}` |
      | Memória residente | `process_resident_memory_bytes{job=~"$job"}` | `{{job}} — {{instance}}` |

      **The `schemaVersion` is measured, not chosen:** let Grafana load the hand-written file, then
      `Export → Export as JSON` with *export for sharing externally* **off**, and adopt the exported
      model as the file after confirming it kept the queries, ids and positions that were written.
      Anything else leaves the stored model differing from the runtime one, which is the defect this
      feature exists to remove.
      Commit: `feat(grafana): rebuild the dashboard for multiple services`
- [ ] **Add the per-convention rows.** Two `row` panels and the five panels under them, selected by
      label presence and never by job name, with `job` inside every bucket grouping:

      | Row | Panel | Expression |
      | --- | --- | --- |
      | Rotas (`handler`) | p95 por rota | `histogram_quantile(0.95, sum by (le, job, handler) (rate(http_request_duration_seconds_bucket{job=~"$job", handler=~"$handler", handler!="/metrics"}[$__rate_interval])))` |
      | Rotas (`handler`) | Throughput por rota | `sum by (job, handler) (rate(http_requests_total{job=~"$job", handler=~"$handler", handler!="/metrics"}[$__rate_interval]))` |
      | Rotas (`handler`) | Códigos por rota | `sum by (job, handler, status) (rate(http_requests_total{job=~"$job", handler=~"$handler", handler!="/metrics"}[$__rate_interval]))` |
      | Requisições (`code`) | p95 por código | `histogram_quantile(0.95, sum by (le, job, code) (rate(http_request_duration_seconds_bucket{job=~"$job", code!=""}[$__rate_interval])))` |
      | Requisições (`code`) | Throughput por código e método | `sum by (job, code, method) (rate(http_requests_total{job=~"$job", code!=""}[$__rate_interval]))` |

      The route row's p95 panel carries in its own `description` field the limitation stated in
      full, not a pointer: the FastAPI app exposes four latency buckets — `0.1`, `0.5`, `1.0`,
      `+Inf` — so any route slower than one second falls in `+Inf` and this panel reads a flat 1s
      for it. The text has to stand on its own, because it is read inside Grafana by someone with no
      access to this repository. Re-export and re-adopt as in the previous task.
      Commit: `feat(grafana): add the per-convention panel rows`
- [ ] **Assert the dashboard declares what it renders.** In `tests/test_grafana_provisioning.py`:
      no panel of type `graph`; every panel carries an `id` and the ids are unique; `refId` unique
      **within** each panel and free to repeat across panels; no two `gridPos` rectangles intersect;
      every target and every panel references the datasource by a uid that `datasource.yaml`
      actually declares; and the dashboard declares a `job` variable. Panel iteration walks nested
      `panels`, because a collapsed row carries its children inside itself and a flat loop would
      skip them. Rewrite the module docstring: the sentence saying nothing here looks at a query, a
      panel type or a grid position stops being true in this commit.
      Commit: `test(grafana): assert the dashboard declares what it renders`
- [ ] **Forbid literal job names in queries.** A test that reads the `job_name` values out of
      `prometheus.yml` and asserts none appears verbatim in any panel `expr`. It parses the file in
      its own session-scoped fixture rather than moving `prometheus_config` into `conftest.py`:
      promoting a fixture is a refactor of a file this feature has no other reason to touch. Read
      from the file, never hard-coded, so the next feature's service inherits the guard without
      editing the test.
      Commit: `test(grafana): forbid literal job names in panel queries`
- [ ] **Document it in `CLAUDE.md`.** The new path, the three panel rows and what separates them,
      the rule that `job` belongs inside every bucket grouping, and why a convention row never names
      a job. Conclusions only — the derivation stays in this plan.
      Commit: `docs: document the multi-service dashboard`
- [ ] **Update `README.md`.** The three sentences naming *FastAPI Metrics*, including the project
      layout line, and a description of what the rebuilt dashboard shows.
      Commit: `docs: update the readme for the services dashboard`
- [ ] **Run the verification script and record every outcome below.** No commit beyond the tick.

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
- **Summing buckets across jobs produces a meaningless number.** The two `le` sets share `1.0` and
  `+Inf`. Any `by (le, …)` without `job` inside is a defect, not a style choice.
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
- **New test code is Python and goes through `tox -e lint`** — black at 88 columns and flake8
  configured to match. The JSON file is not linted by anything except the tests written here.
- **Markdownlint** on the `CLAUDE.md` and `README.md` edits: compact tables (MD060), blank lines
  around lists and fences, checked in the VS Code Problems panel.

## Verification steps

1. `tox` passes end to end — `py311` with the new assertions, `lint`, `safety`.
2. `docker compose --profile '*' config -q` exits clean and `config --services` resolves five
   services.
3. `docker compose --profile core --profile load up -d` against the **existing** `grafana_data`;
   `app`, `service-go`, `prometheus` and `grafana` all reach `healthy`.
4. **Requirement 5:** `curl -s -u admin:admin localhost:3000/api/datasources` returns one
   datasource with `uid: prometheus`, not two, and not the generated uid.
5. `curl -s -u admin:admin 'localhost:3000/api/search?type=dash-db'` returns *Services Overview*
   and no longer returns *FastAPI Metrics*. *T12 live test* is expected to still be there.
6. **Panel by panel in a browser**, against the baseline captured in task 1: does it draw, how many
   series, does the legend distinguish the services. The two error panels at `No data` remain
   expected.
7. **Requirement 4:** the stored file and the runtime model agree. Read the settings editor's model
   in the browser and the API's `/api/dashboards/uid/services-overview` side by side: same
   `schemaVersion`, same panel types, same ids. The baseline recorded them disagreeing — `42` /
   `timeseries` / `1..7` against `36` / `graph` / absent — and the rebuilt file must close that gap.
   The unsaved-changes symptom is **not** used as the proof: measured in task 1, Grafana `12.4.7`
   does not raise it, because its dirty check compares against the migrated model on both sides.
   Plus `grep -c '__inputs' services.json` → 0.
8. **Requirement 1:** unselecting a service in `$job` removes it from every cross-service panel,
   the two resource panels included.
9. **Requirement 7:** the CPU and memory panels show two series with distinct legends, not two
   entries both reading `CPU seconds`.
10. **Requirement 2:** the CPU panel shows a rate that moves with load, not a monotonic climb.
11. **Requirement 6:** no panel repeats a `refId` among its own targets — asserted by test and read
    once on screen through `Inspect → Panel JSON` on the panel that carries two targets.
12. **Genericity, with no third service to prove it:** the guard test passes and
    `grep -o 'fastapi-app\|service-go' grafana/dashboards/services.json` returns nothing.
13. **Requirement 3, negative proof:** give two panels the same `gridPos`, confirm the intersection
    test fails, revert.
14. **Requirement 5, negative proof:** change one target's uid, confirm exactly one test fails,
    revert.
15. A CI run on the branch, green on all three jobs.
16. `git diff --stat main...HEAD` names only the files in "Affected files" plus this ticket's two
    documents, and `git show --stat HEAD` at each commit names only that task's files.
