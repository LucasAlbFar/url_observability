# CU-86bbq58c2 — 04 cardinality guard

Status: Approved

Plan: [./plan.md](./plan.md)

## Summary

Cap what a single target can write to the TSDB, and drop the series that carry a raw path as a label
value. The guard is two layers in `prometheus.yml`: `metric_relabel_configs` discarding a
path-shaped label value, and the scrape limits in `global:` as the backstop for what no rule
anticipated. Because nothing in this stack misbehaves — all three services label by route template
or by a fixed value, on purpose and under test — the failure has to be produced before it can be
guarded against: a deliberately noisy service, behind its own compose profile, joins the scrape by
the same four labels everyone else uses and emits a new raw-path series on every scrape. The
degradation is measured without the guard, then measured again with it. A dashboard row makes the
guard visible, and the "group instead of drop" option the roadmap offers is measured once and
recorded rather than assumed.

## Objective

**The discovery door is half open.** The `keep` rule added with `docker_sd_configs` discards a
container that did not ask to be scraped. It says nothing about one that did. A service reporting
`/users/1`, `/users/2`, `/users/3` writes one series per ID until Prometheus consumes the machine —
the first failure mode of any stack that accepts arbitrary services, and one that arrives during a
demonstration rather than during development.

**The guard cannot be proven against this stack as it stands.** The FastAPI app groups by route
template, the Go service instruments only its matched routes, and the Node service labels every
unknown path with one fixed value and has a test asserting it. All three are immune by design to the
failure this ticket prevents. Shipping the rules without producing the failure first ships a rule
nobody has watched fire — the reason the previous feature was split into a mechanism half and a
proof half.

**One derivation reads the wrong source.** Two tests treat "scraped" as a synonym for "driven by the
load generator": one asserts set equality between the hosts in `URLS` and the scraped services, the
other derives from the same set who `loadgen` must wait for. A scraped service that the generator
does not drive fails both — which the noisy service is, so the derivation has to be corrected before
it can exist.

**"Drop or group" is currently an assumption.** The roadmap offers both. Collapsing two label values
into one inside a single scrape produces two samples with identical label sets, which Prometheus
rejects. Measuring that once costs one task and replaces a sentence written from expectation with a
recorded fact.

## Scope

### In

- **A noisy service**, one stdlib module in `noisy/` with its test, listening on 8005 and serving a
  hand-assembled `/metrics`. It runs on the app's image — the root `Dockerfile` already does
  `COPY . .`, so `build: .` with a different `command:` needs no new Dockerfile, CI job, lock file
  or dependency. It emits more raw-path series on every scrape, so the growth is a ramp rather than
  a step.
- **A `chaos` profile**, outside `core` and `load`, so the everyday stack still resolves the same
  services and the demonstration's series only reach `prometheus_data` when someone asks.
- **No published port and no healthcheck.** Prometheus reaches it over the compose network, which is
  the first real exercise of `prometheus.io/port` being the port the process listens on rather than
  one it publishes.
- **Layer one: `metric_relabel_configs` with `action: drop`**, selecting on the *shape of the label
  value* — a path segment that is a number or an identifier — in `handler` and `route`, the two
  path-carrying labels this stack has. Never on a job name.
- **Layer two: the scrape limits in `global:`** — a sample ceiling and the label limits — sized
  against the largest measured service, with the headroom justified beside the value the way the
  Prometheus `start_period` is.
- **The problem measured before the guard and after it.** The noisy target's series counted on a
  ramp with no guard, then counted again with it, and the three well-behaved services counted both
  times to show the guard costs them nothing.
- **The grouping option measured once** against the noisy service, with the duplicate-sample counter
  read before and after. The deliverable is the recorded result, not code.
- **A cardinality row in the dashboard** — series per target and the limit-exceeded counters, both
  from Prometheus's own metrics, under the rules the dashboard already enforces: `job` inside every
  grouping, no scrape job name in any query.
- **The debt paid first:** `driven` derived from the `load` profile rather than from the scrape
  label, in both sibling tests. Still derived — the exception is a consequence of the service being
  outside the load profile, not a hand-written name.
- **`CLAUDE.md` and `README.md` updated** — the two layers, the `chaos` profile, how to provoke the
  failure and how to watch the guard fire.

### Out

- **A fourth real service, in a fourth language.** The previous ticket already proved any language
  joins; a new Dockerfile, lock file and CI job would buy nothing this one needs.
- **A per-service ceiling.** `sample_limit` is a static `scrape_config` field with no meta-label
  behind it, so a per-service ceiling means a second scrape job — which puts service names back in
  `prometheus.yml`, exactly what discovery removed.
- **Fixing the noisy service.** It exists to misbehave; instrumenting it correctly would delete the
  only failure this ticket can point at.
- **Grouping as the shipped guard.** If the collision hypothesis holds it is unsafe at ingest, and if
  it does not, the recorded measurement is what a later feature acts on.
- **Guarding label values that are not paths.** A service putting an ID in a label of its own naming
  passes the drop rules and is caught only by the ceiling. Accepted in writing, and the reason the
  second layer exists.
- **Reconciling the three label conventions.** The drop rules have to name `handler` and `route`
  separately, and a fourth convention would need a third rule. That cost is recorded as further
  input to the metrics rework, not paid here.
- **The Go service's missing 404s and the app's low-resolution buckets.** Both are recorded debts
  owned by the metrics rework; neither is instrumentation this ticket touches.

## Expected behaviour

`docker compose --profile '*' config -q` exits clean and resolves seven services. Under `core` and
`load` the stack is unchanged: the same targets, the same three `job` values, the same series counts.

Adding `--profile chaos` brings up the noisy service, and within the discovery refresh interval it
becomes a fourth target — by declaring the same four labels as everyone else, which is what makes
the ceiling necessary rather than optional. With no guard, its series count climbs on every scrape
and does not level off.

With the guard in place, the raw-path series are gone from the TSDB, and a run that outpaces the drop
rules trips the ceiling instead: that target's scrape fails, it reports `up=0` while staying in the
target list, and Prometheus's limit-exceeded counter rises. The other three targets are untouched —
still `up=1`, still the same series counts they had before the noisy service existed.

The dashboard's cardinality row draws series per target and the guard firing, without naming any job
in a query. Removing a drop rule brings the raw-path series back; restoring it removes them again.

`tox` fails if the limits or the drop rules are missing from `prometheus.yml`, and no longer fails
when a scraped service is absent from the load generator's list because it sits outside the load
profile.

## Acceptance criteria

- [ ] `driven` is derived from the `load` profile in both sibling tests, and a scraped service
      outside that profile fails neither; a service inside it and absent from `URLS` still fails.
- [ ] `noisy/` is one stdlib module plus its test, adds no dependency and no `Dockerfile`, publishes
      no port and declares no healthcheck, and sits in the `chaos` profile alone.
- [ ] It joins the scrape by the same four labels as every other service, with no edit to the
      discovery job.
- [ ] `docker compose --profile '*' config -q` exits clean and resolves seven services; `core` plus
      `load` resolves the same set as before this ticket.
- [ ] `promtool check config` accepts the limits and the drop rules.
- [ ] **Without the guard**, the noisy target's series count is recorded at two or more instants and
      is rising; the query that produced each number is recorded with it.
- [ ] **With the guard**, that count is bounded — the raw-path series absent, or the target at `up=0`
      with the limit-exceeded counter above zero.
- [ ] The three well-behaved services are unchanged: `up=1` and the same per-job series counts as the
      previous ticket recorded.
- [ ] Removing a drop rule brings the raw-path series back and restoring it removes them, verified
      against the running stack rather than by reading the file.
- [ ] No drop rule and no limit names a job, a service or an instance.
- [ ] The limits live in `global:`, and the headroom of the sample ceiling is justified beside the
      value against the measured baseline.
- [ ] The grouping option is attempted once against the noisy service, the duplicate-sample counter
      read before and after, and the outcome recorded in `plan.md` either way.
- [ ] The dashboard's cardinality row draws in a browser, names no job in any query, and keeps `job`
      inside every grouping.
- [ ] `tox` passes end to end and a CI run on the branch is green on every job.
- [ ] `CLAUDE.md` and `README.md` describe both layers, the `chaos` profile, what the guard does not
      cover, and how to provoke the failure and watch the guard fire.
