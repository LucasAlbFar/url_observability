# CU-86bbkjcj1 — 03a label discovery (plan)

Spec: [./spec.md](./spec.md)

## Context

`prometheus.yml` declares two scrape jobs, each a `static_configs` with one hand-written address.
Three test modules read that file: `tests/test_prometheus_config.py` asserts its structure,
`tests/test_grafana_provisioning.py` borrows its job names to keep the dashboard generic, and the CI
`infra` job runs `promtool check config` against it through the image read from `docker-compose.yml`.

The change replaces both jobs with one `docker_sd_configs` job and moves the per-service
configuration into container labels. Nothing else in the stack changes shape: no service is added,
and `grafana/dashboards/services.json` is not edited.

What makes this more than a config swap is `prometheus_data`. Its series are keyed by `job` and
`instance`, and under discovery both labels come from `relabel_configs` rather than from the file.
The deliverable is the swap **without a break in those series**, and the verification is built
around proving that rather than around the new mechanism working at all.

## Facts verified against the repo

Measured 2026-08-24 unless dated otherwise.

- **`prometheus.yml` has two jobs**, `fastapi-app` → `app:8002` and `service-go` → `service-go:8003`,
  both `static_configs`, `metrics_path: /metrics`, under a global `scrape_interval: 5s`.
- **`test_every_scrape_job_has_a_target` fails on a discovery job** (`tests/test_prometheus_config.py:59`):
  it collects targets by iterating `job.get("static_configs", [])` and asserts the list is non-empty.
- **The genericity guard goes green and empty.** The `scrape_job_names` fixture
  (`tests/test_grafana_provisioning.py:196`) reads `job_name` from `prometheus.yml`, and
  `test_no_query_names_a_scrape_job` (`:228`) forbids those strings in every panel expression. With
  the only job named after the discovery mechanism, it forbids that name and nothing else.
- **`test_scrape_job_names_are_unique` becomes trivially true** with a single job. The invariant it
  carried — two services cannot land under the same `job` label — has to move to the compose labels.
- **The dashboard names no job.** Its 13 `expr` and 2 template variables select by `job=~"$job"` and
  by label presence; the service variable is `label_values(up, job)`. Nothing depends on `job`
  having the values it has, only on the set not changing.
- **The socket needs a supplementary group.** `/var/run/docker.sock` is `srw-rw---- root:983`
  (group `docker`), mode `660`, and `docker image inspect prom/prometheus:v3.13.2` reports
  `User=nobody`. Reading it without `group_add` fails on permission.
- **`app:8002` and `service-go:8003` resolve from inside the Prometheus container** — that is what
  the current `static_configs` uses, so rewriting `__address__` to the compose service name is not a
  bet.
- **`prometheus_data` exists and holds 13 MB.** The baseline and the continuity check are therefore
  meaningful; against an empty volume they would prove nothing.
- **Baseline before the switch**, measured 2026-08-29 16:24Z against the existing
  `prometheus_data`: `/api/v1/targets` returns two active targets, both `up` — `fastapi-app` at
  `app:8002` and `service-go` at `service-go:8003`. Series per job, from `count({job="<name>"})`:
  136 for `fastapi-app`, 68 for `service-go`. `label_values(job)` returns those two names and
  nothing else.
- **No `.env` exists in the repo**, so a new compose interpolation needs an inline default or the
  CI `config -q` resolves it empty.
- **Prometheus does not scrape itself today**, and will not start to: without `prometheus.io/scrape`
  the `keep` discards its container like any other.
- **`tests/test_compose_config.py` already carries what the new assertions need** — a session-scoped
  `compose` fixture, a `CORE_SERVICES` tuple naming the four healthchecked services, and a
  module-level `FROM_IMAGE` and `dockerfiles` fixture. No new helper is required.
- **Four places describe the scrape in prose:** `README.md:10` (the two addresses and the two job
  names), `:99`, `:241`, and the `Observability wiring` section of `CLAUDE.md`.

**Confirmed in task 3, 2026-08-29, with `promtool check config` and `/api/v1/targets`:**

- **The meta-label naming holds.** `prometheus.io/scrape` reaches relabelling as
  `__meta_docker_container_label_prometheus_io_scrape`, and the compose service name as
  `__meta_docker_container_label_com_docker_compose_service`.
- **A container yields more than one candidate target, and the rewrite collapses them.**
  `prometheus` and `grafana` each appear twice in the dropped list at the same address; `app` and
  `service-go` produce one active target each, not one per published port.
- **A stopped container leaves the target list.** With `service-go` stopped the list holds one
  target and its `up` series disappears rather than reading 0; starting it again restores the
  target within the refresh interval, with no configuration edit.

## Affected files

| File | Change |
| --- | --- |
| `prometheus.yml` | Both `static_configs` jobs become one `docker_sd_configs` job with four relabel rules |
| `docker-compose.yml` | Socket mount and `group_add` on `prometheus`; the scrape labels on `app` and `service-go` |
| `tests/test_prometheus_config.py` | `test_every_scrape_job_has_a_target` redefined; new assertion that discovery is opt-in |
| `tests/conftest.py` | The shared `compose_labels` fixture both guards read |
| `tests/test_compose_config.py` | The label contract: complete, unique, and the socket declared |
| `tests/test_grafana_provisioning.py` | The genericity guard reads job values from the compose labels |
| `CLAUDE.md` | `Observability wiring` rewritten, plus the socket trap |
| `README.md` | The scrape description and how a service joins |

## Tasks

One commit per task, with the checkbox ticked in the same commit. Any sentence in `CLAUDE.md` or
`README.md` that a task makes false is corrected in that task's commit.

- [x] Record the baseline here: both targets from `/api/v1/targets` with their `job` and `instance`,
      and the series count per job. No code, and **before** any edit — continuity is only
      demonstrable against a before. — `docs(specs): record the target labels before the switch`
- [x] Compose: the scrape labels on `app` and `service-go`, the socket mount and `group_add` on
      `prometheus`. `prometheus.yml` is untouched, so the labels stay inert and the stack behaves
      exactly as before. — `feat(compose): label the scraped services and mount the docker socket`
- [x] `prometheus.yml`: the `docker_sd_configs` job with its four relabel rules, replacing both
      static jobs. Confirm the three unmeasured items here. — `feat(prometheus): discover scrape targets from container labels`
- [x] `tests/test_prometheus_config.py`: `test_every_scrape_job_has_a_target` accepting a
      `*_sd_configs` source, and the new assertion that a discovery job carries `action: keep`. —
      `test(prometheus): accept discovery jobs and require the scrape opt-in`
- [x] `tests/test_compose_config.py`: a scraped service declares job and port, no two services claim
      the same job label, and `prometheus` declares the socket and `group_add`. —
      `test(compose): assert the scrape opt-in labels are complete and unique`
- [x] `tests/test_grafana_provisioning.py`: the guard's fixture reads `prometheus.io/job` from the
      compose file, with the docstring recording why the source moved. —
      `test(grafana): read job values from the compose labels`
- [x] `CLAUDE.md`: label discovery, the four-label contract, why `job` and `instance` cannot change,
      and the socket trap. Conclusions only — the derivation stays in this file. —
      `docs: document label-based target discovery`
- [x] `README.md`: the scrape description and a short section on how a service joins. —
      `docs: explain how a service joins the scrape`
- [x] Run the verification steps and record each outcome here. No commit beyond the tick. —
      `docs(specs): record the verification outcomes`

## Edge cases

- **Socket permission is the expected failure, and it surfaces at `up`.** The socket is `root:983`,
  mode `660`, and Prometheus runs as `nobody`. Planned exit: `group_add: ["${DOCKER_GID:-983}"]` —
  the inline default is required because no `.env` exists and CI would otherwise resolve it empty.
- **`user: root` is the wrong exit and is a one-way door.** `prometheus_data` belongs to `nobody`;
  files written as root are not readable again after a revert.
- **`:ro` on the socket is not a security boundary.** It protects the file node, not the API:
  whoever reads the socket enumerates every container on the host. Accepted for a local stack, and
  written down rather than left implicit.
- **One target per published port.** Latent today, since each service publishes one. Rewriting
  `__address__` from labels should collapse a container's targets into one — verify the list shows
  two, not four.
- **A stopped service leaves the target list instead of reporting `up=0`.** Real signal loss against
  `static_configs`: the `Targets up` panel loses the line rather than drawing a zero. No mitigation
  short of reinstating the fixed list this ticket removes.
- **Without `prometheus.io/job` the target carries no `job` label at all** — measured 2026-08-29,
  after review: `replace` *deletes* the label when the value is empty, so there is no fallback to
  the discovery job name. Recorded here as the correction to what this plan first claimed. The
  config now drops such a container with a `keep` on job and port, and the compose test still
  demands the labels, so the omission is reported rather than merely survived.
- **The optional path rule needs `regex: (.+)`.** Without it, a service that omits
  `prometheus.io/path` gets an empty `__metrics_path__` instead of the `/metrics` default.
- **`refresh_interval: 15s` is delay, not failure.** A container that starts takes up to 15s to
  become a target; the next ticket times this and should not read the wait as a broken discovery.
- **Only `promtool` reads the relabel semantics.** No Python test can tell whether a `source_labels`
  entry names a meta-label that exists, which is why the CI `infra` job is part of the verification
  rather than a formality.
- **Discovery reaches every container on the host, not only this project's.** The socket lists
  them all and `prometheus.io/scrape` is a shared convention, so a neighbouring stack's container
  would join with an address rebuilt from *its* compose service name — unresolvable here, a
  permanently down target and a foreign value in the `job` dropdown. Closed with a `filters:` on
  `com.docker.compose.project`, which names the project and therefore couples to the directory
  name; a test compares the two, because a mismatch returns zero targets silently.
- **A wrong `DOCKER_GID` fails quietly.** Measured with `DOCKER_GID=1234`: the container reports
  `healthy`, discovery returns zero targets, every panel is empty, and the only signal is a
  `permission denied` line in the log. `/-/healthy` reports the HTTP server, not the socket. Hence
  the export step in `README.md` rather than trusting the `983` default.
- **Markdownlint** on the `CLAUDE.md` and `README.md` edits: compact tables (MD060), blank lines
  around fences and lists.

## Verification steps

Run 2026-08-29 against the existing `prometheus_data`. Every step passed.

| # | Outcome |
| --- | --- |
| 1 | `tox` green: `py311` 50 passed, coverage 100%, `lint`, `safety` |
| 2 | `promtool check config` SUCCESS under `prom/prometheus:v3.13.2`, read out of the compose file |
| 3 | `config -q` clean; `config --services` resolves five, and `group_add` resolves to `983` with no `.env` |
| 4 | `down` then `up -d --build`: the four services reach `healthy`, and the Prometheus log carries no permission or `level=error` line |
| 5 | Two targets, both `up`, `fastapi-app`/`app:8002` and `service-go`/`service-go:8003` — two, not one per published port |
| 6 | `label_values(job)` → `['fastapi-app', 'service-go']` |
| 7 | 136 and 68 series per job, matching the baseline exactly. A 3h `query_range` over `up`, spanning the static config through the switch, holds **two** series and no new one: same labels throughout. Its one gap, 45s on `service-go`, is the stop in task 3 — which is the point, since it shows the query does reveal a target leaving |
| 8 | Stopping `service-go` drops the list to one target; starting it restores two, no configuration edit |
| 9 | Removing `prometheus.io/scrape` and recreating drops the target; restoring the label brings it back |
| 10 | All three rows and all eleven charts drew, legends reading `fastapi-app — app:8002` and `service-go — service-go:8003`. `git diff` does not name `grafana/dashboards/services.json` |
| 11 | `job="fastapi-app"` written into a panel expression fails the new guard; the same edit against the old fixture passed 13/13 |
| 12 | Green on all three jobs — `build`, `go`, `infra` — on PR #7 |
| 13 | The diff names the seven files in "Affected files" plus this ticket's two documents, and each commit names only its own task's files |

Two notes on what the run does **not** prove. The `up` range query carries a value forward for up
to five minutes, so it cannot see a gap shorter than that from a Prometheus restart; what it does
show is that no series ended and none began. And the `5xx`/`4xx` panels read `No data` — there is
no error traffic in this stack, and that predates the switch.

1. `tox` passes end to end — `py311` with the new assertions, `lint`, `safety`.
2. `promtool check config` accepts `prometheus.yml`, run through the image read out of
   `docker-compose.yml`, the way the CI `infra` job does it.
3. `docker compose --profile '*' config -q` exits clean, and `config --services` resolves five
   services.
4. `docker compose --profile core --profile load up -d` against the **existing** `prometheus_data`;
   `app`, `service-go`, `prometheus` and `grafana` all reach `healthy`, and the Prometheus log shows
   no socket permission error.
5. `/api/v1/targets` returns exactly two targets, both `up`, with `job` and `instance` identical to
   the baseline recorded in task 1 — two, not one per published port.
6. `label_values(job)` returns exactly `fastapi-app` and `service-go`.
7. **Series continuity:** a range query spanning the restart shows no gap
   (`count_over_time(up{job="fastapi-app"}[30m])`), and the series count per job matches the
   baseline.
8. **Discovery proof:** `docker compose --profile core stop service-go` and the target leaves the
   list; start it again and it returns within the refresh interval, with no configuration edit.
9. **Opt-in proof:** remove `prometheus.io/scrape` from one service, recreate it, and its target
   disappears; revert.
10. **The dashboard draws all fourteen panels** in a browser, and `git diff` does not name
    `grafana/dashboards/services.json`.
11. **Negative proof of the guard:** write `job="fastapi-app"` into a dashboard expression and
    confirm the test fails — today's guard would not fail it; revert.
12. A CI run on the branch is green on all three jobs.
13. `git diff --stat main...HEAD` names only the files in "Affected files", plus this ticket's two
    documents; `git show --stat HEAD` at each commit names only that task's files.
