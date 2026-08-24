# CU-86bbkjcj1 — 03a label discovery

Status: Approved

Plan: [./plan.md](./plan.md)

## Summary

Replace the two hand-written `static_configs` jobs in `prometheus.yml` with one
`docker_sd_configs` job that discovers targets from container labels. A service joins the scrape by
declaring four labels in its own compose block — `prometheus.io/scrape`, `prometheus.io/job`,
`prometheus.io/port` and an optional `prometheus.io/path` — and nothing else. Prometheus gets the
Docker socket mounted and reaches it through `group_add` rather than by running as root. Relabelling
preserves the labels the existing history is keyed by: `job` stays `fastapi-app` and `service-go`,
`instance` stays `app:8002` and `service-go:8003`. No service is added and the dashboard is not
touched.

## Objective

**Adding a service means editing the observability system.** Every target is an address written by
hand, so a new service costs an edit to `prometheus.yml` and a Prometheus restart. That is the
opposite of the claim this project exists to demonstrate.

**Two tests stop meaning what they say.** `test_every_scrape_job_has_a_target` iterates
`static_configs` and fails outright on a discovery job — a loud failure, and the easy one. The
quiet one is the dashboard's genericity guard: it reads `job_name` from `prometheus.yml` and
forbids those strings in panel queries, so once the only job is named after the discovery mechanism
it forbids `docker` and none of the names that matter, while staying green. It is the fourth
instance in this project of a test that appears to cover something and does not.

**The history constrains the design.** `prometheus_data` holds series keyed by `job` and `instance`.
Under discovery both labels come from `relabel_configs` instead of from the file, so getting them
wrong splits two months of history in a way nothing reports. That is why the label contract carries
a fourth label, `prometheus.io/job`, beyond the three the mechanism itself needs: deriving `job`
from the compose service name would rename `fastapi-app`, which is already forbidden for this
reason.

**Why without the Node service.** Proving discovery needs a service that enters without touching
configuration, and that service is the next ticket. Introducing it here would mean a relabelling
mistake and a brand-new service producing the same symptom at the same time. With the two known
services, the only thing to verify is that nothing changed.

## Scope

### In

- **One `docker_sd_configs` job** replacing both `static_configs` jobs, reading the Docker socket
  with `refresh_interval: 15s`. The default of 60s would make a new container take up to a minute to
  appear, which is the demonstration the next ticket depends on.
- **Opt-in by label, enforced with `action: keep`.** A container without `prometheus.io/scrape` is
  discarded, Prometheus and Grafana included. Without the `keep`, discovery means scraping every
  container that starts — the cardinality door a later feature exists to close, left open early.
- **Label continuity as the deliverable.** `prometheus.io/job` becomes the `job` label;
  `__address__` is rewritten from the compose service name and the port label, so `instance` keeps
  its current value instead of becoming a container IP that changes on every recreate. The optional
  path rule uses `regex: (.+)` so an absent label leaves the `/metrics` default alone.
- **Socket access through `group_add`.** The socket is `root:docker`, mode `660`, and the Prometheus
  image runs as `nobody`. `user: root` would also work and is a one-way door: the existing
  `prometheus_data` belongs to `nobody`, and files created by root are not readable again after a
  revert.
- **`tests/test_prometheus_config.py` redefined.** `test_every_scrape_job_has_a_target` accepts a
  job that declares either `static_configs` with targets or at least one `*_sd_configs` key — "does
  this job scrape anything" stops having a static answer, so the test asks for a source of targets
  rather than a list. A new assertion requires every discovery job to carry a `keep` action.
- **The label contract asserted in `tests/test_compose_config.py`**: a service declaring
  `prometheus.io/scrape: "true"` also declares `prometheus.io/job` and `prometheus.io/port`; no two
  services claim the same `prometheus.io/job`; the Prometheus service mounts the socket and declares
  `group_add`. The uniqueness assertion is where the invariant behind `test_scrape_job_names_are_unique`
  now lives, that test having become trivially true with a single job.
- **The genericity guard rebased.** Its fixture reads the `prometheus.io/job` values from
  `docker-compose.yml` — the values the `job` label actually takes — instead of `job_name` from
  `prometheus.yml`. The docstring records why the source moved and that a static job returning later
  must be unioned into that set.
- **The baseline captured before anything is edited** and recorded in `plan.md`: the two targets
  from `/api/v1/targets` with their `job` and `instance`, and a series count per job. Continuity is
  only demonstrable against a before.
- **`CLAUDE.md` and `README.md` updated.** Both describe hand-written addresses today —
  `README.md:10`, `:99` and `:241`, and the `Observability wiring` section of `CLAUDE.md`. Beyond
  correcting those: the four-label contract, why `job` and `instance` cannot change, and the socket
  trap.

### Out

- **Any new service.** The Node service that proves discovery is the next ticket, and adding it here
  would give a relabelling error and a new service the same symptom.
- **Editing the dashboard.** Its thirteen expressions and two variables already select by
  `job=~"$job"` and by label presence, over a `label_values(up, job)` variable. Nothing in it
  depends on `job` having the values it has, only on the set not changing. Needing to edit it means
  the relabelling is wrong, and that is a defect to fix, not scope to absorb.
- **Cardinality limits.** The `keep` closes the cheap half — only opted-in containers are scraped. A
  service that opted in and emits raw paths is a later feature and is not addressed here.
- **A socket proxy.** Mounting the socket lets Prometheus enumerate every container on the host, and
  `:ro` does not change that: it protects the file node, not the API. Accepted because the stack is
  local and authentication is already out of scope for this project, but stated rather than left
  implicit. The serious answer is a proxy container, which is not a two-line change.
- **Restoring the `up=0` signal for a stopped service.** Under discovery a container that is not
  running leaves the target list instead of reporting `up=0`, so the `Targets up` panel loses the
  line rather than drawing a zero. That is a real loss against `static_configs`, and no mitigation
  exists that does not reinstate the fixed list this ticket removes.
- **The documentation-drift gap in `tests/test_docs_versions.py` and the `npm` blind spot in the
  install-pinning test.** Both are triggered by a fourth `Dockerfile`. This ticket adds none.

## Expected behaviour

`docker compose --profile core --profile load up -d`, run against the **existing** `prometheus_data`
rather than a fresh volume, brings the stack up with the four healthchecked services reporting
`healthy`. Prometheus reads the Docker socket without a permission error.

`/api/v1/targets` returns two targets, both `up`, carrying the same `job` and `instance` values they
carried before the change — `fastapi-app` at `app:8002` and `service-go` at `service-go:8003`. A
container publishing more than one port does not produce a target per port, because the rewritten
address collapses them. `label_values(job)` returns the same two values as before: none added, none
lost. A range query spanning the restart shows no gap, and the series count per job matches the
baseline.

Stopping a service removes its target from the list within the refresh interval, and starting it
again brings the target back with no configuration edit. Removing `prometheus.io/scrape` from a
service and recreating it removes the target too. The dashboard draws all fourteen panels without
having been edited — which is the evidence that the previous ticket's genericity work was real
rather than intended.

`tox` fails if a scrape job is left with no source of targets, if a discovery job drops its opt-in
`keep`, if a scraped service omits its job or port label, if two services claim the same job label,
or if a service name is written into a dashboard query — the last of these being a failure the
current guard would not produce.

## Acceptance criteria

- [ ] The baseline is recorded in `plan.md` **before** `prometheus.yml` is edited: both targets from
      `/api/v1/targets` with their `job` and `instance`, and a series count per job.
- [ ] `prometheus.yml` declares one `docker_sd_configs` job and no `static_configs`, and
      `promtool check config` accepts it under the image read from `docker-compose.yml`.
- [ ] The discovery job carries `action: keep` on `prometheus.io/scrape`, asserted by a test.
- [ ] `app` and `service-go` declare `prometheus.io/scrape`, `prometheus.io/job` and
      `prometheus.io/port`; a test fails if a scraped service omits either of the last two, and
      fails if two services claim the same `prometheus.io/job`.
- [ ] The Prometheus service mounts the Docker socket and declares `group_add`, asserted by a test,
      and Prometheus does not run as root.
- [ ] `test_every_scrape_job_has_a_target` passes with a discovery job and still fails a job that
      declares no source of targets at all.
- [ ] The genericity guard reads its forbidden values from the compose labels: writing
      `job="fastapi-app"` into a dashboard expression makes it fail, and reverting makes it pass.
      The current guard does not fail that edit.
- [ ] `/api/v1/targets` returns exactly two targets, both `up`, with `job` and `instance` identical
      to the baseline — two targets, not one per published port.
- [ ] `label_values(job)` returns exactly `fastapi-app` and `service-go`.
- [ ] Series continuity is demonstrated across the change: a range query spanning the restart shows
      no gap, and the per-job series count matches the baseline.
- [ ] Stopping a service removes its target within the refresh interval; starting it again restores
      the target with no configuration edit.
- [ ] Removing `prometheus.io/scrape` from a service and recreating it removes its target.
- [ ] The dashboard draws all fourteen panels in a browser, and `git diff` does not name
      `grafana/dashboards/services.json`.
- [ ] `tox` passes end to end — `py311` with the new assertions, `lint`, and `safety`.
- [ ] `docker compose --profile '*' config -q` exits without error and resolves five services.
- [ ] `CLAUDE.md` and `README.md` describe label discovery, the four-label contract, why `job` and
      `instance` cannot change, and the socket trap; no sentence describing hand-written scrape
      addresses survives.
- [ ] A CI run on the branch is green on all three jobs.
- [ ] `git diff --stat main...HEAD` names only the files this ticket's plan lists, plus the two
      documents of this ticket.
