# CU-86bbaf36c — 01b fix and improvements

Status: Approved

Plan: [./plan.md](./plan.md)

## Summary

Close the debt the compose-hardening feature recorded and left behind, without changing anything the
stack does. Prometheus retention moves out of the two command-line flags the pinned image marks
deprecated and into `prometheus.yml`. The `prom/prometheus` tag stops being copied by hand into the
CI workflow and starts being derived from `docker-compose.yml`, with a test that fails when a
documentation copy drifts from it. The load generator's image pins the version of `httpx` it
installs, and the pinning test grows to notice when one does not. `flake8` is given the same line
width `black` already formats to, ending a nine-column disagreement the previous feature predicted
would recur in every new file. Five environment variables that no code reads are deleted before the
next feature copies the blocks holding them. The Prometheus healthcheck's `start_period`, calibrated
against an empty database, is measured again now that a populated volume exists. The two GitHub
Actions still targeting Node.js 20 move to the majors that target Node.js 24. And `CLAUDE.md`'s
`### Run the app / stack locally`, at roughly twice the length of any of its siblings, is cut back to
its conclusions.

## Objective

Eight defects were found during the previous feature or in the sweep that followed it, judged out of
its approved scope, and written down rather than fixed. Each is small on its own; each gets more
expensive the moment a second service exists.

**Configuration that no check can see.** Retention is set through two flags the pinned image's own
`--help` marks `[DEPRECATED]`, pointing at the config file instead. Nothing breaks today —
deprecated is not removed inside the 3.x line — but the more immediate cost is that the flags are
opaque to every check the repo has. To Compose and to `tests/test_compose_config.py` they are
strings in a list, so `--storage.tsdb.retention.time=7x` reaches `main` green and is discovered when
a container refuses to start. Whether moving them into `prometheus.yml` fixes that is an open
question, not a known benefit: the previous plan records that a `storage:` block *passes*
`promtool check config`, and passing is not the same as being validated. Nobody has yet shown that
promtool would *reject* a bad value, nor that a value accepted from the config file is applied
rather than silently falling back to the fifteen-day default. The same blindness has a second
instance: `worker/Dockerfile` installs `httpx` with no version, so the load generator's image is not
reproducible — inside the feature whose purpose was to make the stack reproducible — and
`test_every_dockerfile_base_image_is_pinned` reads only `FROM` lines, so the test that appears to
cover this does not.

**One image tag written out in seven places across four files.** `docker-compose.yml` pins it, the
`infra` job repeats it to run `promtool`, and `CLAUDE.md` and `README.md` carry five more copies
between prose and runnable snippets. Only one of those can fail silently, and it is the worst one:
if a bump touches the compose file alone, CI carries on validating `prometheus.yml` against a
different Prometheus than the stack runs, and reports success while doing it. The remaining copies
are prose a human reads and pastes, so they cannot be derived — but nothing notices when they go
stale either.

**Noise that trains the reader to ignore the signal.** Both CI jobs are annotated as deprecated on
every run, because `actions/checkout@v4` and `actions/setup-python@v5` target Node.js 20 and the
runner forces them onto Node.js 24. An annotation that is always present is an annotation nobody
reads, and it will be sitting there when a real one arrives. `flake8` runs at its default of 79
columns while `black` formats to 88, so a wrapped expression black considers finished can fail
`tox -e lint` with no formatting that satisfies both; the previous plan states plainly that this
recurs in every future file until the repo sets `max-line-length`, and it already cost one file in
that feature. And five environment variables sit in `docker-compose.yml` doing nothing —
`LOADGEN_INTERVAL` and `LOADGEN_URLS` on `app`, which duplicate a list only `worker/load_driver.py`
reads, and `GF_SECURITY_ADMIN_USER`, `GF_SECURITY_ADMIN_PASSWORD` and `DEBUG` on `loadgen`, which is
not Grafana and reads none of them. They were seen and left alone; the argument has changed, because
the next feature writes its service block by copying one of these, and that copy has already
happened once.

**A measurement that did not follow what changed under it.** Grafana's healthcheck `start_period`
was measured and raised from ten seconds to ninety after a cold boot marked it unhealthy. The
Prometheus one is still ten seconds, calibrated against an empty TSDB — before `prometheus_data`
existed to replay a write-ahead log at startup. `grafana` waits on `prometheus` with
`condition: service_healthy`, and the previous plan records that under that condition a short
`start_period` does not produce a misleading `ps` line, it fails the whole `up`. Separately,
`CLAUDE.md`'s `### Run the app / stack locally` has grown to roughly two hundred words over three
long bullets and two paragraphs, one line of it alone about 430 characters, against siblings of four
to sixteen lines. The excess is derivation — why Grafana needs ninety seconds, what
`restart: unless-stopped` does not react to, which subcommands are silent without a profile. The
project's rule puts the conclusion in `CLAUDE.md` and the derivation in the plan, and the derivation
here is already in the plan the section links to.

None of this adds behaviour. It is debt-closing work, and it lands before the next feature because
that feature grows `prometheus.yml`, adds a service to `docker-compose.yml`, extends the `infra`
job, and introduces a third `Dockerfile` — every file listed above.

## Scope

### In

- **Retention moves from the compose `command` to `prometheus.yml`.** Both deprecated flags leave
  `docker-compose.yml`; `--storage.tsdb.path=/prometheus` stays, because it is not deprecated and it
  is load-bearing — the compose `command` overrides the image's default arguments, so without it the
  TSDB path falls back to a default that only lands inside the named volume by accident of the
  image's `WORKDIR`. `prometheus.yml` gains one `storage:` block carrying the same seven days and
  512 MB, so the change is behaviour-neutral by construction.
- **The assertion moves with the setting.** `test_prometheus_command_bounds_storage` in
  `tests/test_compose_config.py` narrows to the path flag alone, and the retention check lands in
  `tests/test_prometheus_config.py` beside the other checks on that file. Net test count does not
  drop.
- **Evidence that a malformed retention value cannot reach `main` green.** What
  `promtool check config` does with a bad value under the pinned image is measured, and the exact
  command, exit code and output are recorded in `plan.md` as a fact. The check then sits at whichever
  layer the measurement requires: if promtool rejects the value, the `infra` job already carries it
  and the Python test stays presence-only; if promtool accepts it, `tests/test_prometheus_config.py`
  validates the value's shape, because otherwise the move would trade one unvalidated setting for
  another. Either way the property is demonstrated by injecting the bad value and watching a check
  fail.
- **Proof that config-file retention is in force**, not merely accepted: the running server's
  reported retention is read through the Prometheus HTTP API, so "the setting moved" is
  distinguished from "the setting was dropped and the default took over".
- **The `infra` job derives the Prometheus image from `docker-compose.yml`** rather than repeating
  it, reading it out of `docker compose --profile '*' config` and passing the result to the existing
  `docker run`. The step guards its own derivation the way the job already guards `--profile '*'`:
  an empty or null result fails the step instead of being handed to `docker run`.
- **The compose `image:` value stays a literal `repository:tag` string.** No variable, no `.env`, no
  digest — see `### Out`. Both pinning tests keep passing unchanged, which is the point.
- **A test that the documentation copies match the compose file.** For every image
  `docker-compose.yml` pins, any reference to that repository in `CLAUDE.md` or `README.md` must
  carry the same tag. `README.md`'s stack bullet, which names a bare `v3.13.2`, is normalised to the
  full reference so that it falls under the rule.
- **`worker/Dockerfile` pins the version of `httpx` it installs**, inline on the existing `RUN`
  line. No `worker/requirements.txt`: the load generator is deliberately decoupled from the `app`
  package — its own Dockerfile, one dependency, no shared requirements file — and that stays true.
- **The pinning test grows to reach installed packages, not just base images.** A `RUN pip install`
  without an exact version fails it, in any Dockerfile in the repo, so the next language's image
  inherits the rule rather than the omission.
- **`flake8` is configured to `max-line-length = 88`**, matching what `black` already formats to.
  Nothing is reformatted; the change only stops flake8 rejecting code black considers finished.
- **Five dead environment variables are deleted** — `LOADGEN_INTERVAL` and `LOADGEN_URLS` from
  `app`, and `GF_SECURITY_ADMIN_USER`, `GF_SECURITY_ADMIN_PASSWORD` and `DEBUG` from `loadgen`.
  `DEBUG` on `app` stays: `app/core/config.py` reads it and `tests/test_config.py` covers it. The
  `GF_SECURITY_ADMIN_*` pair on the `grafana` service stays too; there they are the real thing.
- **The Prometheus `start_period` is measured against a populated `prometheus_data`** and set to
  whatever that measurement justifies. The deliverable is the recorded measurement, not a particular
  number — if ten seconds turns out to be enough, the value stays and the evidence is what changes.
- **`actions/checkout@v4` → `@v5` in both jobs and `actions/setup-python@v5` → `@v6`**, the majors
  that target Node.js 24.
- **Three sentences in `CLAUDE.md` that this feature makes false are corrected.** That a Prometheus
  bump "also has to touch the `infra` job" stops being true once the job derives the tag; the
  description of what that job runs becomes approximate for the same reason; and the paragraph
  instructing the reader to keep lines under 79 columns by construction stops applying once flake8
  is set to 88. All three are mandatory, not optional tidying.
- **`CLAUDE.md`'s `### Run the app / stack locally` is cut to sibling size**, keeping only the rules
  a reader could otherwise violate: the two commands, the repo-root requirement, `--profile` on
  every subcommand including teardown, both named volumes surviving a `down`, and the instruction not
  to lower Grafana's ninety-second `start_period`. The measurements and Docker semantics behind them
  stay in `specs/CU-86bb30dec/plan.md`, which already holds them and which the section already links.
- **`README.md` updated** where these changes make it wrong: the promtool snippet, the pinned-version
  bullet, and where retention now lives.
- **A manual verification step with the exact command** proving retention is applied from the config
  file, and a negative one proving the malformed-value check bites.
- **A recorded answer to whether the provisioned dashboard still renders under the pinned Grafana.**
  It produces no code and no test — the seven panels use a legacy type whose compatibility layer is
  off by default, and if the dashboard is already blank on `main` then the next feature is rebuilding
  it rather than migrating it. Cheap to know now, expensive to discover mid-feature.

### Out

- **Any change to what the stack runs.** No new service, no dashboard work, no alerting rules, no
  OpenTelemetry. This is a debt-closing feature; F2 owns the second service and everything that
  follows from it.
- **Every dashboard defect** — the two panels sharing a `gridPos` and a `refId`, the CPU panel
  plotting a raw counter without `rate()`, the resource panels missing `by (job, instance)`, the
  seven Angular panels, and the datasource referenced by name instead of `uid`. They are real and
  they are enumerated in the roadmap's F2 entry so none is lost. A test covering them could not even
  land here: it would fail on `main`, because the dashboard is still broken. The `uid` in particular
  is kept whole rather than split — its provisioning half would be one line here, but F2 reauthors
  the dashboard JSON regardless, and half a fix landing two features apart is worse than one
  coherent change.
- **Templating the image tag inside `docker-compose.yml`** — a `${PROMETHEUS_VERSION}` with an
  `.env`, a YAML anchor, or a `@sha256:` digest. Rejected on evidence: `assert_pinned` in
  `tests/test_compose_config.py` splits the image on the last colon and requires an exact
  `major.minor.patch`, so a variable fails it outright and a digest either fails it or forces the
  regex to be loosened until it no longer proves the tag is exact. Deriving on the reading side
  leaves both pinning tests untouched, which is why that is the route taken. Pinning by digest is a
  real idea and a separate feature, one that rewrites the pinning test deliberately.
- **Deriving the Grafana or Python tags.** Only the Prometheus tag is duplicated into an executable
  position. Grafana's other copies are prose, and the Python tag lives in the two `Dockerfile`s where
  a failing build, not a silently-green CI job, is the feedback. The documentation-consistency test
  covers every compose image generically, so Grafana is protected from drift without anything being
  derived for it.
- **A `worker/requirements.txt`.** Pinning `httpx` is in scope; giving the load generator a
  requirements file is not. Its independence from the `app` package is a deliberate property, and one
  dependency does not need a lockfile to be reproducible — an exact version on the install line is
  enough.
- **`--enable-feature=exemplar-storage`.** The Prometheus `command` block is open and the flag would
  be one line, which is exactly the temptation. It is dead configuration three features before a
  producer exists, `promtool` does not validate it, and F8 has to enable it and prove it end to end
  regardless.
- **Resource limits, Grafana authentication and `/metrics` exposure.** All three now sit on the
  roadmap's deliberately-out list, where they were missing. Resource limits were rejected by the
  previous feature for a substantive reason — the `app` service exists to exhaust CPU and memory
  under synthetic load, and a ceiling turns the demo into an OOM kill — and that has not changed.
- **Collapsing the near-verbatim duplication between `CLAUDE.md`'s `### Infra checks` and the
  identically-named `README.md` section.** It is real, and this feature edits inside both, but
  removing it means deciding which file owns the command set and pointing the other at it — a
  documentation-structure decision with a blast radius well past two lines and a test.
- **Trimming any other `CLAUDE.md` section.** `### Infra checks` is the next largest and this feature
  corrects two sentences inside it, but editing a line within a section is not a licence to
  restructure it. Only `### Run the app / stack locally` exceeds its siblings by the margin the rule
  is about.
- **A test asserting the GitHub Actions versions.** It would encode a moving target and need editing
  on every bump, and the runner already reports the fact for free. The check for this item is a CI
  run with no deprecation annotation, which is why it is an acceptance criterion and not a test.
- **Gating markdownlint in CI, packaging metadata, and the `fastapi_project` placeholder name in
  `pyproject.toml`.** None blocks the next feature, and each costs more than this feature's budget.
- **Bumping Prometheus, Grafana or Python.** This feature makes a bump cheap; it does not perform
  one. A bump changes what runs and carries its own verification.
- **Every other `prometheus.yml` key** — `rule_files`, remote write, `docker_sd_configs`,
  out-of-order ingestion. The file gains exactly one block, so the diff is reviewable as a
  behaviour-neutral move.
- **Choosing different retention values.** Seven days and 512 MB carry over unchanged, which is what
  makes the move provably behaviour-neutral. Sizing them against real disk is a question for whoever
  has real data, and it changes what the stack keeps.
- **Any change under `app/` or `grafana/`, or to `worker/load_driver.py`.** The only file that
  changes under `worker/` is its `Dockerfile`.
- **A fallback if the premise fails.** If the pinned image turns out not to accept retention in the
  config file in the form assumed, the retention item leaves this feature rather than growing
  workarounds inside it: the flags stay, the deprecation is documented, and the move becomes its own
  ticket. Recorded here so that outcome is a planned exit, not a mid-feature amendment.

## Expected behaviour

Prometheus retains the same seven days and 512 MB it retained before, configured in
`prometheus.yml`. The container starts with no deprecation warning in its log, and the running
server reports the retention it was given rather than the fifteen-day default — which is the
difference between the setting having moved and the setting having been quietly dropped. A mistyped
retention value fails a check instead of reaching `main`; which check catches it, and what it
prints, is measured under the pinned image and written down rather than inherited as an assumption.

Bumping Prometheus is one line in `docker-compose.yml`. CI then validates `prometheus.yml` against
exactly the image the stack runs, because it reads the tag out of that same file rather than
carrying its own copy. If a copy in `CLAUDE.md` or `README.md` still names the old tag, `tox` fails
and names the file, so the prose cannot drift in silence. `CLAUDE.md` documents that rule in place of
the manual instruction it carries today, which this change makes untrue.

Both images build from an exact set of versions. Rebuilding the load generator months from now
produces the same `httpx` it produces today, and an unpinned `pip install` in any Dockerfile — the
one the next feature adds included — fails the suite rather than passing unnoticed.

`tox -e lint` accepts what `black` produces. A line black leaves at 84 columns no longer has to be
rewritten to satisfy a linter reading a different limit, and `CLAUDE.md` stops teaching a workaround
for a conflict that no longer exists.

`docker-compose.yml` carries only environment variables something reads. The service blocks are safe
to copy, which is what the next feature will do with them.

A cold `up` against a populated volume brings Prometheus to `healthy` and Grafana up behind it,
with the wait sized against a measurement rather than against an empty database.

Both CI jobs run green with no deprecation annotation, so the next annotation to appear means
something.

`CLAUDE.md`'s `### Run the app / stack locally` reads like the sections around it: the commands, and
the handful of rules a reader could otherwise break. Everything it drops is still recorded — one
link away, in the plan of the feature that measured it.

## Acceptance criteria

- [ ] The `prometheus` service's `command` in `docker-compose.yml` carries
      `--storage.tsdb.path=/prometheus` and neither retention flag.
- [ ] `prometheus.yml` configures the same retention that was removed — seven days and 512 MB — in
      the config-file form the pinned image documents.
- [ ] `promtool check config` reports `SUCCESS` for the new `prometheus.yml` under the image pinned
      in `docker-compose.yml`.
- [ ] With the stack up, the running server reports the configured retention through
      `/api/v1/status/runtimeinfo`, not the fifteen-day default, and its startup log carries no
      deprecated-flag warning.
- [ ] What `promtool check config` does with a malformed retention value is measured under the
      pinned image and recorded in `plan.md` with the exact command, exit code and output.
- [ ] Injecting that malformed value makes an automated check fail — the `infra` job if promtool
      rejects it, `tests/test_prometheus_config.py` if promtool accepts it — and reverting it makes
      the check green again.
- [ ] `tests/test_compose_config.py` no longer asserts the retention flags,
      `tests/test_prometheus_config.py` does, and deleting the `storage:` block from
      `prometheus.yml` fails exactly one test.
- [ ] `.github/workflows/python-app.yml` contains no literal `prom/prometheus:` reference, and
      changing the tag in `docker-compose.yml` alone changes the image its promtool step runs
      through, with no other file edited.
- [ ] The `infra` job fails, rather than invoking `docker run` on an empty value, when the image
      cannot be resolved from the compose file.
- [ ] A test fails when a `prom/prometheus` or `grafana/grafana` reference in `CLAUDE.md` or
      `README.md` names a tag `docker-compose.yml` does not.
- [ ] Every `image:` value in `docker-compose.yml` is still a literal `repository:tag` string, and
      `test_every_compose_image_is_pinned` and `test_every_dockerfile_base_image_is_pinned` still
      pass with their meaning unchanged.
- [ ] `worker/Dockerfile` installs `httpx` at an exact version on its existing `RUN` line, and no
      requirements file is added under `worker/`.
- [ ] Removing that version makes a test fail, and restoring it makes the suite green — demonstrated,
      not asserted.
- [ ] `flake8` runs at `max-line-length = 88`; `tox -e lint` passes; an 88-column line is accepted
      and an 89-column line is rejected.
- [ ] `docker-compose.yml` contains no `LOADGEN_INTERVAL`, no `LOADGEN_URLS`, and no
      `GF_SECURITY_ADMIN_*` or `DEBUG` under `loadgen`; `DEBUG` under `app` and `GF_SECURITY_ADMIN_*`
      under `grafana` are still there.
- [ ] `tox -e py311` passes after the deletion, showing no test depended on the removed variables.
- [ ] The Prometheus `start_period` is measured against a populated `prometheus_data`, the observed
      time to `healthy` is recorded in `plan.md`, and the value in `docker-compose.yml` is consistent
      with it.
- [ ] A cold `docker compose --profile core up` against a populated volume reaches `healthy` for
      `prometheus` and starts `grafana` behind it, without the `up` failing.
- [ ] `.github/workflows/python-app.yml` uses `actions/checkout@v5` in both jobs and
      `actions/setup-python@v6`, with no older major of either remaining.
- [ ] A CI run on the branch is green on both jobs and raises no Node.js deprecation annotation.
- [ ] `CLAUDE.md` no longer states that a Prometheus bump has to touch the `infra` job, describes
      accurately what that job runs, and no longer instructs the reader to keep lines under 79
      columns.
- [ ] `CLAUDE.md`'s `### Run the app / stack locally` fits within the length range of the other
      subsections of `## Commands`, and its longest line is comparable to theirs rather than four
      hundred characters.
- [ ] That section still states the `--profile`-on-every-subcommand rule, that both named volumes
      survive a `down`, and that Grafana's ninety-second `start_period` must not be lowered, and
      still links `specs/CU-86bb30dec/plan.md`.
- [ ] Every fact removed from that section is verifiably present in `specs/CU-86bb30dec/plan.md` or
      `README.md`, checked item by item and recorded in `plan.md`.
- [ ] `README.md` states where retention is configured, and its infra-check snippet still works when
      pasted into a shell.
- [ ] Whether the provisioned dashboard renders under the pinned Grafana is recorded in `plan.md`,
      with what was observed.
- [ ] `tox` passes end to end.
- [ ] `git diff --stat main...HEAD` shows no change under `app/` or `grafana/`, and under `worker/`
      only `Dockerfile`.
