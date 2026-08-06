# CU-86bb30dec — Improve docker compose

Status: Approved

Plan: [./plan.md](./plan.md)

## Summary

Harden the Docker Compose stack so it survives a teardown and comes back the same on any machine.
Prometheus and Grafana state moves into named volumes, the two pulled images stop tracking `latest`
and get pinned to an exact release, every service declares a healthcheck, a restart policy and a
Compose profile, and the Prometheus command gains an explicit storage path plus retention bounds.
Alongside the Compose changes, the project gets its first infrastructure smoke test: a set of pytest
files that assert the invariants of `docker-compose.yml`, `prometheus.yml` and the provisioned
Grafana files, and a new CI job that validates the same files with `docker compose config` and
`promtool check config`.

## Objective

Three defects make the current stack unreliable to build on, and every feature that follows adds
more containers and more configuration on top of them.

Grafana keeps its runtime state — hand-made dashboards, users, preferences — in `grafana.db`, and
the `grafana/grafana` image declares no `VOLUME`, so that file lives in the container's writable
layer and is discarded by any `docker compose down`. Iterating on a dashboard while losing the
state on every teardown is the friction the next feature runs into immediately.

Both pulled images track `latest`, so the stack can change behaviour between two `up` runs with no
change in the repository. The Prometheus image cached on the development machine is `v3.13.1` while
the published `latest` is already `v3.13.2`, and the cached Grafana predates the current `latest` by
weeks — a clean machine does not run what this machine runs.

Nothing validates infrastructure. The CI workflow runs `tox`, which covers pytest, lint and
`pip-audit` over Python sources only; `prometheus.yml` and the dashboard JSON are never opened. A
malformed scrape config or a broken dashboard reaches `main` green today.

Finally, the roadmap ends at roughly eight containers. Without profiles, every future test requires
bringing the whole stack up.

## Scope

### In

- Named volumes `prometheus_data` (mounted at `/prometheus`) and `grafana_data` (mounted at
  `/var/lib/grafana`), so both databases outlive the containers. Configuration bind mounts —
  `prometheus.yml`, the two `grafana/provisioning` directories and `grafana/dashboards` — become
  read-only in the same change.
- Pinned image tags: `prom/prometheus:v3.13.2`, `grafana/grafana:12.4.7`, and `python:3.11.15` in
  both `Dockerfile` and `worker/Dockerfile`.
- Removal of the top-level `version: '3.8'` key, which current Compose ignores with a warning.
- An explicit `--storage.tsdb.path=/prometheus` on the Prometheus command, plus
  `--storage.tsdb.retention.time=7d` and `--storage.tsdb.retention.size=512MB`. The path is not
  cosmetic: the Compose `command` overrides the image's default arguments, so today the flag is
  absent and the data directory only lands inside the volume because of the image's `WORKDIR`.
- A healthcheck on `app`, `prometheus` and `grafana`, `restart: unless-stopped` on all four
  services, and `depends_on` upgraded to `condition: service_healthy` where it applies. `loadgen`
  gets no healthcheck — it serves no port.
- A Compose profile on every service: `core` for `app`, `prometheus` and `grafana`; `load` for
  `loadgen`. `app` also carries `load`, so that profile boots on its own instead of leaving the
  generator retrying against nothing.
- Infrastructure smoke tests: `tests/test_compose_config.py`, `tests/test_prometheus_config.py` and
  `tests/test_grafana_provisioning.py`, backed by a `repo_root` fixture in `tests/conftest.py`. They
  parse the files and assert the invariants this feature introduces — no image on `:latest`, both
  named volumes declared and mounted, every service carrying a profile, healthchecks present, the
  dashboard JSON parsing with `uid`, `title` and non-empty `panels`.
- `pyyaml` promoted from a transitive dependency of `uvicorn[standard]` to a direct entry in
  `requirements/dev.in`, with `requirements/dev.txt` recompiled and `pyproject.toml` realigned. The
  new tests import it, so nothing should leave it to chance on the next `pip-compile --upgrade`.
- A second CI job running `docker compose --profile '*' config -q` and `promtool check config`
  against the pinned Prometheus image, covering the semantics no Python test can check.
- `CLAUDE.md` and `README.md` updated: the documented commands now carry `--profile`, the pinned
  versions replace `latest`, and the teardown sections are rewritten — both currently describe the
  anonymous-volume behaviour and the loss of Grafana state in detail, and both become factually
  wrong with this change.

### Out

- Resource limits (`mem_limit`, `cpus`). The `/load/memory-spike` and `/load/cpu-bound` endpoints
  exist precisely to spike memory and CPU so the dashboard has something to plot; a ceiling on the
  `app` service turns the demo into an OOM kill. Recorded as a decision, not an omission.
- Every dashboard defect: panels sharing a `gridPos` and a `refId`, the CPU panel plotting a raw
  counter without `rate()`, the datasource referenced by name instead of `uid`, the seven Angular
  `graph` panels, and the missing per-service variable. They are real, and they belong to the
  multi-service feature that reauthors the dashboard.
- A `/health` route on the app. The healthcheck targets `/metrics`, which already exists. A
  `/health` route arrives with the second service, where two services owning the same path is the
  point being demonstrated.
- `docker_sd_configs` and any change to how targets are discovered — `prometheus.yml` keeps its
  single static target here.
- OpenTelemetry, the Collector, Tempo and Loki. Later features, by design.
- Grafana authentication, the fixed `admin`/`admin` credentials, and any exposure hardening of
  `/metrics`.
- Alerting: no `rule_files`, no recording rules, no Alertmanager.
- Any change to `app/`, `worker/` or the existing tests — no runtime behaviour changes in this
  feature.
- Grafana 13.x. The 13 line was published days before this work and the dashboard's schema
  migration under it is unverified; the upgrade is a deliberate act for the feature that reauthors
  the panels.

## Expected behaviour

`docker compose --profile '*' down` followed by an `up` returns the stack with its history intact:
the Prometheus series scraped before the teardown are still queryable, and a dashboard created by
hand in the Grafana UI is still there. Only `down --volumes` discards them, and it now discards
both — which the documentation states plainly, because that command is considerably more
destructive than it used to be.

The stack starts one group at a time. `docker compose --profile core up` brings the app, Prometheus
and Grafana without the synthetic traffic; `--profile load up` brings the app and its load
generator without the observability side; `--profile core --profile load up --build` reproduces
today's full stack. Since every service declares a profile, a bare `docker compose up` starts
nothing, and every other subcommand needs `--profile` too — `build`, `config`, and the teardown
commands, which otherwise exit 0 having done nothing at all. The documented commands change
accordingly.

Containers report their own readiness. `docker compose ps` shows `app`, `prometheus` and `grafana`
as `healthy` rather than merely running, the load generator waits for the app to be healthy instead
of racing it, and a crashed container comes back on its own unless it was stopped deliberately.

Two identical `up` runs on two different machines pull the same image digests, because no tag
floats.

A configuration mistake fails the build. `tox` fails on a compose file that reintroduces `:latest`,
drops a named volume or leaves a service without a profile; the CI infrastructure job fails on a
`prometheus.yml` that Prometheus itself would reject.

## Acceptance criteria

- [x] `docker compose --profile '*' config --volumes` prints `prometheus_data` and `grafana_data`.
      The `--profile` is required: with every service behind a profile, the bare form resolves no
      services and prints nothing.
- [x] `docker compose --profile '*' config -q` exits zero and emits no obsolete-`version` warning.
- [x] No image reference in `docker-compose.yml`, `Dockerfile` or `worker/Dockerfile` resolves to a
      floating tag; Prometheus is `v3.13.2`, Grafana is `12.4.7`, Python is `3.11.15`.
- [x] With the stack up, `docker compose ps` reports `app`, `prometheus` and `grafana` as `healthy`.
- [x] `docker compose --profile core up -d` starts three containers and no load generator;
      `docker compose --profile load up -d` starts the app and the generator and neither Prometheus
      nor Grafana.
- [x] After creating a dashboard by hand in Grafana, letting the stack scrape for a few minutes,
      then running `docker compose --profile '*' down` and bringing it back up: the dashboard is
      still present and a `http_requests_total` query returns points from before the teardown. The
      `--profile` is required here too — the bare form silently does nothing.
- [x] The Prometheus command passes an explicit `--storage.tsdb.path` and both retention flags.
- [x] `promtool check config` reports `SUCCESS` for `prometheus.yml` under the pinned image.
- [x] `tox` passes end to end, including the three new infrastructure test files.
- [x] Replacing a pinned tag with `:latest` makes `pytest tests/test_compose_config.py` fail —
      the tests are proven to bite, not merely to pass.
- [x] `pyyaml` appears in `requirements/dev.in`, in the recompiled `requirements/dev.txt` and in
      `pyproject.toml`.
- [x] The CI workflow has a job that runs `docker compose config` and `promtool check config`.
- [x] `CLAUDE.md` and `README.md` no longer claim Grafana state is lost on `down`, document the
      `--profile` commands, and name the pinned versions.
- [x] No runtime behaviour changes: `app/`, `worker/load_driver.py` and `grafana/dashboards/` are
      untouched. `worker/Dockerfile` does change — pinning its base image is in scope — so the
      check names the driver rather than the whole `worker/` directory.
