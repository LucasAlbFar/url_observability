# CU-86bbpx4by — 03b node service

Status: Approved

Plan: [./plan.md](./plan.md)

## Summary

Add a third service, in Node, that joins the scrape by declaring `prometheus.io/scrape`,
`prometheus.io/job` and `prometheus.io/port` in its own compose block — and by nothing else.
`prometheus.yml` and `grafana/dashboards/services.json` are not edited, and the absence of both from
the diff is the deliverable. The service is instrumented with `prom-client` and emits its own label
convention, `route`/`status_code`/`method`, which is a third one beside the app's `handler`/`status`
and the Go service's `code`/`method`. Which dashboard panels that convention reaches, and which it
does not, is measured against the running stack and recorded rather than corrected. The fourth
`Dockerfile` falls due on two tests that only look like they cover it, and two more of the same
pattern are paid alongside them.

## Objective

**The mechanism is unproven.** The previous ticket replaced two hand-written `static_configs` with
one `docker_sd_configs` job, and its verification was that nothing changed: the same two targets,
the same series. Nobody has walked through the new door. A service that joins without a line of
configuration is the only evidence that it opens.

**So is the dashboard's genericity.** The rebuild before it claimed panels written against no
service in particular. That claim has only ever been tested by the two services it was written
against. A third one either appears without an edit or the claim was aspiration.

**The third convention is the point, not a side effect.** `prom-client` does not instrument HTTP,
so its labels are the author's choice, and the choice is governed by a decision already taken: each
service emits the idiom of its own library, and nothing is renamed to make a panel light up. The
cost of that decision has been an argument until now. With three conventions live it becomes a
measurement — the input a later feature consumes to justify unifying them.

**The fourth `Dockerfile` calls two debts.** `compose_images` reads only services declaring
`image:`, so a locally built one's base tag drifts against the prose unchecked; and the install
pinning parser understands `pip` alone, so an `npm install` passes it vacuously. Both are the
project's most expensive failure pattern — a test whose symptom is a green CI. Two more instances of
it are paid here because they sit in the same code: the parser discards a whole command on seeing
`-r`, and `CORE_SERVICES` is a hand-written tuple that a new service silently escapes.

## Scope

### In

- **A Node service on 8004**, flat like `service-go/`: source, test, `package.json`,
  `package-lock.json`, `Dockerfile`. Node's `http` and `prom-client`, no framework — three routes do
  not justify one, and `prom-client` is the reference client the way `client_golang` was for Go. It
  reads no environment and is called by nothing but the load generator.
- **The same three load routes as the Go service** — `/health`, `/load/io-bound`,
  `/load/cpu-bound`, plus `/metrics`. A route that exists on all three services is what makes the
  merge observable.
- **A third label convention, deliberately.** `route`, `status_code` and `method` on
  `http_requests_total` and `http_request_duration_seconds`. The metric names follow the Prometheus
  convention the other two libraries already follow; the labels are what differ, and renaming them
  to `handler` or `code` would falsify the proof this ticket exists to produce.
- **Joining by label only.** Three labels in the compose block, and no `prometheus.io/path`, so the
  `/metrics` default is exercised by a real service instead of by a regex alone.
- **A measured table of what the dashboard reaches**, produced against the running stack with the
  queries that measure it: which panels the Node service populates, which it does not, and why. This
  is the ticket's most valuable output and the successor feature's evidence.
- **Four debts paid.** The image fixture reads the `FROM` lines of every `Dockerfile` alongside the
  compose tags; the install parser reads `npm` and stops discarding a command on `-r`;
  `CORE_SERVICES` is derived from the compose file. `package-lock.json` plus `npm ci` is accepted in
  writing as the analogue of `go.sum`, the way the Go service's vacuous pass was accepted before.
- **A `node` CI job**, in the mould of the `go` one, reading its version from `package.json` rather
  than naming it.
- **`CLAUDE.md` and `README.md` updated** — the third service, the third convention and what it does
  not reach, and the pinning by lock file.

### Out

- **Editing the dashboard.** The Node service appearing in the *Services* row without an edit is the
  proof; a third convention row would be the opposite of it, and a later feature retires that row by
  unifying the conventions anyway.
- **Editing `prometheus.yml`.** A diff naming it fails the ticket regardless of what else is green.
- **Renaming the Node labels to an existing convention.** It would light up two more rows and
  destroy the measurement they were lit for.
- **Cardinality limits.** A third service adds series; the guard against a badly behaved one is the
  next feature and is not started here. What this ticket owes it is a number: what the third service
  cost in series.
- **The `-r` parser debt's wider question** of whether the install check should read every
  ecosystem. `npm` is added because a service needs it; `gem` and `go get` are not.
- **The app's low-resolution latency buckets.** Recorded without a feature, owned by the metrics
  rework, and untouched by adding a service.

## Expected behaviour

`docker compose --profile core --profile load up -d` brings up five services with healthchecks, all
reaching `healthy`, and `config --services` resolves six. Within the discovery refresh interval,
`/api/v1/targets` lists **three** targets, all `up`, the Node one carrying a `job` and an `instance`
that came from its labels alone. `git diff` does not name `prometheus.yml`.

`label_values(job)` returns three values, the two existing ones unchanged. In Grafana, the *Services*
row draws the Node service beside the other two — targets up, CPU, resident memory, and throughput —
with no panel edited and `git diff` not naming the dashboard file. The two convention rows do not
draw it, and neither do the error-rate panels, because they select on `handler`, `code` and `status`
and the Node service carries none of them. That gap is reported as a measurement, with the queries
that produce it.

Stopping the Node service removes its target; starting it again restores it without a configuration
edit, within the same interval.

`tox` fails if a `Dockerfile` base tag drifts from the tag quoted in the documents, if an `npm
install` names an unpinned package, if a `pip install` hides an unpinned package behind a `-r` flag,
or if a service that serves traffic declares no healthcheck — the last three being failures the
current suite would not produce.

## Acceptance criteria

- [ ] `git diff main...HEAD` does not name `prometheus.yml` or `grafana/dashboards/services.json`,
      and names only the files this ticket's plan lists plus its own two documents.
- [ ] `service-node/` is flat, reads no environment, pins its base image to a bare
      `<major>.<minor>.<patch>` tag, installs with `npm ci`, and commits `package-lock.json`.
- [ ] The service answers `/health` with the same `{"status": "ok"}` body the other two answer, and
      exposes `/metrics`.
- [ ] Its metrics carry `route`, `status_code` and `method` — not `handler`, `status` or `code`.
- [ ] `docker compose --profile '*' config -q` exits clean and resolves six services; the five
      services with healthchecks reach `healthy`.
- [ ] `/api/v1/targets` returns three targets, all `up`, the Node one with `job` and `instance`
      derived from its labels; `label_values(job)` returns three values with the first two unchanged.
- [ ] The time from `up` to the target appearing is measured and within the refresh interval.
- [ ] The dashboard draws the Node service in the *Services* row in a browser, unedited.
- [ ] The panels the Node service does and does not reach are recorded in `plan.md`, each backed by
      the query that measures it against the running stack rather than by inspection of the JSON.
- [ ] The series the third service added are counted and recorded, for the cardinality feature to
      size against.
- [ ] Stopping the service removes its target; starting it again restores it with no configuration
      edit.
- [ ] The image-tag check covers locally built services: changing a `Dockerfile` base tag without
      changing the documents fails, and the check is not passing on an empty scan.
- [ ] The install-pinning check fails an `npm install <package>` with no version, and fails
      `pip install -r requirements/base.txt <package>`; `npm ci` passes.
- [ ] `CORE_SERVICES` is derived from the compose file: a service that serves traffic and declares no
      healthcheck fails, without anyone adding its name to a list.
- [ ] `tox` passes end to end, and a CI run on the branch is green on all four jobs.
- [ ] `CLAUDE.md` and `README.md` describe the third service, its convention and what that convention
      does not reach in the dashboard, and the lock-file pinning; no sentence describing a two-service
      stack survives.
