# CU-86bbpx4by — 03b node service (plan)

Spec: [./spec.md](./spec.md)

## Context

The previous ticket replaced two `static_configs` with one `docker_sd_configs` job that keeps
containers declaring `prometheus.io/scrape`, filtered to this compose project, and drops one that
opted in without `prometheus.io/job` or `prometheus.io/port`. Its verification was that nothing
changed. This ticket is the first thing to arrive through that mechanism.

The work lands in four places that barely touch each other: a new `service-node/` directory beside
`service-go/`; three lines of labels in `docker-compose.yml` plus the routes in
`worker/load_driver.py`; four assertions in the infra test modules that a fourth `Dockerfile` makes
false or vacuous; and a `node` job in CI beside the `go` one.

What makes this more than adding a service is what must **not** move. `prometheus.yml` and
`grafana/dashboards/services.json` staying out of the diff is the deliverable, and the measurement
of which panels the third service reaches is what the work produces for the feature after next.

## Facts verified against the repo

Measured 2026-08-29 against `main`, with the discovery ticket merged.

- **The dashboard depends on metric names, not only on labels.** Its eleven `expr` use
  `http_requests_total`, `http_request_duration_seconds_bucket`, `process_cpu_seconds_total`,
  `process_resident_memory_bytes` and `up`. Which panels a third service reaches follows from which
  of those names it exports.
- **The two convention rows select on label presence** — `handler!=""` and `code!=""` — so a series
  carrying `route`/`status_code` enters neither. The *Services* row groups by `job` and filters on no
  convention at all. The error-rate panels carry one target per convention, `status=~"5.."` beside
  `code=~"5.."`, and neither matches `status_code`.
- **`CORE_SERVICES` is a hand-written tuple** (`tests/test_compose_config.py:17`), read only by
  `test_core_services_declare_a_healthcheck` (`:209`). A service not listed escapes the assertion
  silently — a new instance of the project's most expensive pattern, found while planning this.
- **`compose_images` reads only services declaring `image:`** (`tests/test_docs_versions.py:24`).
  `app`, `service-go` and `loadgen` declare `build:`, so the base tags they name in prose go
  unchecked. A fourth `Dockerfile` adds one more.
- **The install parser understands `pip` alone** (`PIP_INSTALL`,
  `tests/test_compose_config.py:29`), and on seeing `-r` it discards the whole command
  (`REQUIREMENT_FLAGS`, `:30`), so `pip install -r base.txt gunicorn` passes green. An `npm install`
  matches nothing at all.
- **`assert_pinned` (`:60`) requires `^v?\d+\.\d+\.\d+$`**, and `Dockerfile` discovery is by
  `rglob`, so the new file inherits the rule without being listed. Every suffixed tag is rejected:
  `node:24-alpine` and `node:24.10.0-slim` both fail.
- **`FROM_IMAGE` (`:16`) is module-level and reusable** — the regex the image fixture needs.
- **`compose_labels` in `tests/conftest.py:32`** is the precedent for a session fixture two modules
  read; an image fixture reading the compose file and the `Dockerfile` set belongs beside it.
- **`URLS` in `worker/load_driver.py` is the only list any code reads.** No environment variable,
  and `CLAUDE.md` forbids reintroducing one.
- **The CI `go` job has its own `working-directory`** and reads its toolchain from `go.mod` rather
  than naming a version. It is the mould for the `node` job.
- **The project filter covers the new service for free:** it is born in the same compose project, so
  `com.docker.compose.project` matches with nothing to do.
- **The Go service's healthcheck depends on the image.** `wget --spider` exists because Alpine's
  BusyBox provides it, while the app probes with `python -c`. The pinning rule forbids a suffixed
  tag, so the Node image is the bare Debian-based one — and a probe written against the runtime
  rather than against the image keeps that coupling from being made twice.

**Not measured yet — confirmed in task 2, against the running stack:**

- That `collectDefaultMetrics()` exports `process_cpu_seconds_total` and
  `process_resident_memory_bytes` on Linux, which is what lights the CPU and memory panels with no
  edit.
- That a series carrying no `handler` label matches the `handler!="/metrics"` selector in
  *Throughput by service*, and therefore that the Node service appears there.
- The `le` bounds `prom-client`'s default histogram uses — a third set, with no consequence for the
  dashboard because every bucket grouping already includes `job`, but worth recording.
- How long the target takes to appear after `up`, expected within the 15s refresh interval.
- The exact `node:<x.y.z>` tag to pin, which has to be a published one.

## Affected files

| File | Change |
| --- | --- |
| `service-node/` | New: source, test, `package.json`, `package-lock.json`, `Dockerfile` |
| `docker-compose.yml` | The service with its three scrape labels, healthcheck and profiles; `loadgen` waiting on it |
| `worker/load_driver.py` | The Node routes in `URLS` |
| `tests/conftest.py` | An image fixture reading the compose tags and the `Dockerfile` `FROM` lines |
| `tests/test_docs_versions.py` | Reads that fixture instead of `compose_images` |
| `tests/test_compose_config.py` | `CORE_SERVICES` derived from the file; the install parser reading `npm` and no longer discarding a command on `-r` |
| `.github/workflows/python-app.yml` | A `node` job in the mould of `go` |
| `CLAUDE.md` | The third service, the third convention and what it does not reach, pinning by lock file |
| `README.md` | The service in the stack description and in the routes tables |

## Tasks

One commit per task, with the checkbox ticked in the same commit. Any sentence in `CLAUDE.md` or
`README.md` that a task makes false is corrected in that task's commit.

- [ ] The Node service on its own: source, test, `package.json`, `package-lock.json`, `Dockerfile`.
      Not in the compose file yet, so the stack still runs two services and nothing is observed. —
      `feat(service-node): add a third service instrumented with prom-client`
- [ ] The service in `docker-compose.yml` with its three labels, and its routes in `URLS`. **This is
      the proof:** `git diff` names no `prometheus.yml`, the target appears on its own, and the time
      it takes is measured here. Confirm the unmeasured items and record the panel table. —
      `feat(compose): let the node service join the scrape by label`
- [ ] A `node` job in CI, reading its version from `package.json`. —
      `ci: check the node service on its own job`
- [ ] Debt: the image fixture reads the `FROM` lines of every `Dockerfile` alongside the compose
      tags. — `test(docs): check the tags of locally built images too`
- [ ] Debt: the install parser reads `npm`, and `-r` stops discarding the command it appears in. —
      `test(compose): read npm installs and stop discarding piped pip commands`
- [ ] Debt: `CORE_SERVICES` derived from the compose file. —
      `test(compose): derive the healthchecked services from the file`
- [ ] `CLAUDE.md`: the third service, the third convention and its reach, the lock-file pinning.
      Conclusions only — the derivation stays in this file. —
      `docs: document the node service and its label convention`
- [ ] `README.md`: the service in the stack description and the routes tables. —
      `docs: add the node service to the stack description`
- [ ] Run the verification steps and record each outcome here. No commit beyond the tick. —
      `docs(specs): record the verification outcomes`

## Edge cases

- **The base image tag cannot carry a suffix.** `assert_pinned` rejects `node:24-alpine` and
  `node:24.10.0-slim`; only a bare `<major>.<minor>.<patch>` passes. The bare image is large, and the
  alternative — loosening the rule — would open pinning for every `Dockerfile` in the repo to buy
  convenience for one. Accept the size.
- **The healthcheck should not depend on what the image ships.** `node -e` uses the runtime that is
  already there, the way the app probes with `python -c`. `wget --spider` would work today and would
  tie the choice of image to the choice of probe a second time.
- **`npm install` in the `Dockerfile` defeats the lock.** Only `npm ci`, which fails when the lock is
  out of sync with the manifest — that failure is what makes the pin worth anything.
- **The Node service missing from the convention rows is not a bug.** The instinct will be to rename
  its labels to `handler` or `code`; that is what the instrumentation decision forbids, and it would
  destroy the measurement the ticket exists to produce.
- **A third service adds series, and the guard is a later feature.** What is owed here is the count,
  so the cardinality work has a number to size against.
- **`prometheus.io/port` is the port the process listens on**, and discovery drops a container that
  declares `scrape` without `job` or `port`. The failure shows up as a missing target, not as an
  error.
- **The target is not instant:** up to the 15s refresh interval before it appears. Timing it without
  knowing that makes working discovery look broken.
- **A diff naming `prometheus.yml` or `grafana/dashboards/services.json` fails the ticket**, however
  green everything else is. Their absence is the deliverable.
- **Deriving `CORE_SERVICES` needs a rule, not a list.** `loadgen` serves nothing and stays out; the
  rule that separates it has to be written down, or the test trades a silent gap for a silent
  exclusion.
- **Markdownlint** on the `CLAUDE.md` and `README.md` edits: compact tables (MD060), blank lines
  around fences and lists.

## Verification steps

1. `tox` passes end to end — `py311` with the new assertions, `lint`, `safety`.
2. What the `node` job runs passes locally, in the service directory.
3. `docker compose --profile '*' config -q` exits clean, and `config --services` resolves six
   services.
4. `docker compose --profile core --profile load up -d` against the existing `prometheus_data`; the
   five services with healthchecks all reach `healthy`.
5. **Discovery proof:** `git diff main...HEAD -- prometheus.yml` is empty, and `/api/v1/targets`
   returns three targets, all `up`, the Node one with `job` and `instance` coming from its labels.
6. **Time to appear:** with the stack already up, start the Node service alone and time it to
   target — expected within 15s.
7. `label_values(job)` returns three values, the first two unchanged.
8. **Genericity proof:** the dashboard draws the Node service in the *Services* row in a browser,
   and `git diff` does not name `grafana/dashboards/services.json`.
9. **The third convention measured:** each row of the panel table confirmed against the running
   stack with the query that produces it, not read off the JSON.
10. **Series cost:** `count({job="service-node"})`, recorded for the cardinality feature.
11. **Negative proof of each debt fixed**, one at a time and reverted: an `npm install <package>`
    with no version fails; `pip install -r requirements/base.txt gunicorn` fails; a `Dockerfile`
    base tag changed without the documents fails; a service that serves traffic with no healthcheck
    fails. Each of the last three passes today.
12. Stopping the Node service removes its target; starting it again restores it with no
    configuration edit.
13. A CI run on the branch is green on all four jobs.
14. `git diff --stat main...HEAD` names only the files in "Affected files", plus this ticket's two
    documents; `git show --stat HEAD` at each commit names only that task's files.
