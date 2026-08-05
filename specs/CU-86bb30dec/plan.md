# CU-86bb30dec — Improve docker compose (plan)

Spec: [./spec.md](./spec.md)

## Context

The change is concentrated in `docker-compose.yml`, with satellites: the two `Dockerfile`s pin their
base image, three new test files and one fixture land under `tests/`,
`.github/workflows/python-app.yml` gains a second job, `requirements/dev.in` gains one line, and
`CLAUDE.md` and `README.md` are corrected where they describe behaviour this feature changes.

Nothing under `app/` or `worker/` is touched — no runtime behaviour changes here. The dashboard JSON
is read by a new test but never edited; its known defects belong to the next feature.

Each task below is its own commit, and the task's checkbox is ticked in that same commit, so this
file stays a traceable record of what was done.

## Facts verified against the repo

- `docker compose config --volumes` prints nothing: there are no named volumes today. The only
  volume in play is the anonymous one Docker creates for `/prometheus`, because `prom/prometheus`
  declares `VOLUME /prometheus`. `grafana/grafana` declares none at all
  (`docker image inspect ... --format '{{json .Config.Volumes}}'` → `null`).
- `docker-compose.yml:1` still carries `version: '3.8'`. Compose v5.3.1 on this machine prints
  `the attribute 'version' is obsolete, it will be ignored` on every invocation.
- `prom/prometheus` has `WORKDIR=/prometheus` and a default `CMD` of
  `["--config.file=/etc/prometheus/prometheus.yml", "--storage.tsdb.path=/prometheus"]`. The compose
  file overrides `command` with only `--config.file`, so `--storage.tsdb.path` currently falls back
  to the binary default (`data/`, relative to the working directory) and lands inside the volume by
  accident of the `WORKDIR`. With a named volume the flag has to be explicit.
- The image cached here is Prometheus `v3.13.1` (digest `3c42b892`), while `latest` on Docker Hub
  already resolves to `v3.13.2` (pushed 2026-07-30). The Grafana image was pulled 2026-07-20 and its
  digest matches no tag among the 300 most recently updated — `latest` today is `13.1.2`. The pins
  this feature adopts, both confirmed to exist: `prom/prometheus:v3.13.2` and
  `grafana/grafana:12.4.7` (pushed 2026-08-04, newest of the mature 12.4 line). `python:3.11.15` is
  the newest 3.11 patch (2026-07-21).
- No service declares `healthcheck`, `restart` or `deploy`. The only `depends_on` is `loadgen` →
  `app` in short form, which orders the start and says nothing about readiness.
- `--profile` is a top-level Compose flag (`docker compose --help` → `--profile stringArray`), not a
  flag of `up`. It has to precede the subcommand.
- `pyyaml==6.0.3` is already resolved into `requirements/base.txt:83` and
  `requirements/dev.txt:129`, but only as a transitive dependency of `uvicorn[standard]`. Nothing
  keeps it there across a future `pip-compile --upgrade`.
- The project venv is `/home/lucas/venvurlobs` (Python 3.11.15, tox 4.58.0, pip 26.2) and is not on
  `PATH`. It has `tox`, `pytest`, `black`, `isort`, `flake8` and, since 2026-08-04, `pip-tools`
  7.6.0.
- **`pip-compile` is installed but cannot run there.** It fails at startup with
  `ImportError: cannot import name 'stdlib_pkgs' from 'pip._internal.utils.compat'`: `piptools.sync`
  imports a private pip symbol that pip 26.2 removed. 7.6.0 is the newest release on PyPI, so no
  upgrade fixes it — the constraint runs the other way, pip has to be older. Verified working in a
  throwaway venv with `pip==25.3` and the same `pip-tools==7.6.0`. This is the mirror image of the
  `AttributeError: 'PackageFinder' object has no attribute 'allow_all_prereleases'` failure the
  README already documents, where pip-tools was the stale side.
- Recompiling `requirements/dev.txt` from the current `dev.in`, without `--upgrade`, reproduces the
  existing file **byte for byte** (checked with `pip-compile --dry-run`). Adding `pyyaml` therefore
  produces a diff limited to its own `# via` block — no pin moves. Note that `--dry-run` writes the
  result to stderr, not stdout.
- The header of `requirements/dev.txt` records the literal argv of the run that produced it:
  `pip-compile --output-file=requirements/dev.txt requirements/dev.in`. Using the `-o` spelling
  instead rewrites that header line for no reason, so keep the `--output-file=` form.
- `pip-compile` also warns that `--strip-extras` becomes the default in pip-tools 8.0.0. The current
  lockfiles keep extras (`coverage[toml]`, `uvicorn[standard]`), so the flag stays unset here and
  the eventual 8.0 upgrade is its own decision.
- There is no `setup.cfg`, no `.flake8` and no flake8 section in `tox.ini`, so flake8 runs at its
  default limit of 79 columns while black formats to 88. No Python file in the repo exceeds 79
  columns today; the new test files must not either, or `tox -e lint` fails on code black considers
  already formatted.
- `tox.ini` runs `pytest --cov=app --cov=worker --cov-fail-under=80 tests/`. The new tests import
  neither package, so they add nothing to the coverage denominator and the 80% gate is unaffected.
- `.github/workflows/python-app.yml` has a single job, `build`, and workflow-level
  `permissions: contents: read`. There is no Docker step anywhere in CI.
- `grafana/provisioning/dashboards/dashboard.yml` sets `options.path` to
  `/var/lib/grafana/dashboards` — inside the directory `grafana_data` will occupy. See "Edge cases".
- `CLAUDE.md` ("Run the app / stack locally", "Stack & versions", "Testing conventions") and
  `README.md` ("Stack", "Running the stack", "Stopping and cleaning up") describe the anonymous
  volume, the loss of Grafana state and the `:latest` images in detail. They become factually wrong
  with this change, which is why documentation is a task and not a footnote.

## Affected files

| File | Change |
| --- | --- |
| `docker-compose.yml` | `version` removed; pinned tags; named volumes; `:ro` config binds; retention flags; healthchecks; `restart`; `depends_on` conditions; `profiles` |
| `Dockerfile` | `FROM python:3.11` → `FROM python:3.11.15` |
| `worker/Dockerfile` | Same pin |
| `tests/conftest.py` | New session-scoped `repo_root` fixture |
| `tests/test_compose_config.py` | New — compose invariants |
| `tests/test_prometheus_config.py` | New — scrape config structure |
| `tests/test_grafana_provisioning.py` | New — dashboard JSON and provisioning YAML |
| `.github/workflows/python-app.yml` | New `infra` job |
| `requirements/dev.in` | `pyyaml` added |
| `requirements/dev.txt` | Recompiled |
| `pyproject.toml` | `pyyaml` under `[tool.poetry.dev-dependencies]` |
| `CLAUDE.md` | Commands, versions, teardown paragraphs, infra-check subsection, testing conventions |
| `README.md` | Stack list, run and teardown sections, development section |

## Tasks

One commit per task, each ticking its own checkbox in the same commit.

- [x] Delete the `version: '3.8'` line from `docker-compose.yml`. Confirm with
      `docker compose config -q` that the obsolescence warning is gone.
      Commit: `chore(compose): drop obsolete version attribute`
- [ ] Pin `prom/prometheus:v3.13.2` and `grafana/grafana:12.4.7` in `docker-compose.yml`, and
      `python:3.11.15` in `Dockerfile` and `worker/Dockerfile`.
      Commit: `chore(compose): pin image tags`
- [ ] Add a top-level `volumes:` block declaring `prometheus_data` and `grafana_data`; mount them at
      `/prometheus` and `/var/lib/grafana`; append `:ro` to the four configuration bind mounts
      (`./prometheus.yml`, both `grafana/provisioning/*` directories, `./grafana/dashboards`).
      Commit: `feat(compose): persist prometheus and grafana state in named volumes`
- [ ] Extend the Prometheus `command` with `--storage.tsdb.path=/prometheus`,
      `--storage.tsdb.retention.time=7d` and `--storage.tsdb.retention.size=512MB`. The path flag is
      not redundant — see "Facts verified against the repo".
      Commit: `feat(compose): bound prometheus retention`
- [ ] Add `restart: unless-stopped` to all four services and a `healthcheck` to three: `app` probing
      `http://localhost:8002/metrics` with `python -c` (the image is `python:3.11`, so no new
      dependency), `prometheus` probing `http://localhost:9090/-/healthy` with `wget --spider -q`,
      and `grafana` probing `http://localhost:3000/api/health` the same way. Use `interval: 10s`,
      `timeout: 3s`, `retries: 3`, and `start_period: 30s` on `app` against `10s` on the other two.
      Convert `loadgen`'s `depends_on` to the long form with `condition: service_healthy`, and add
      the same for `grafana` → `prometheus`.
      Commit: `feat(compose): add healthchecks and restart policy`
- [ ] Declare `profiles` on every service: `["core", "load"]` on `app`, `["core"]` on `prometheus`
      and `grafana`, `["load"]` on `loadgen`. `app` sits in both on purpose, so `--profile load`
      boots something useful instead of a generator retrying against nothing, and so the behaviour
      does not depend on how a given Compose version auto-enables a dependency's profile.
      Commit: `feat(compose): group services into profiles`
- [ ] Add `pyyaml` to `requirements/dev.in`, then regenerate the lockfile with
      `pip-compile --output-file=requirements/dev.txt requirements/dev.in` — **without**
      `--upgrade`, so the existing pins are honoured, and with that exact spelling, since the
      command is echoed into the file's header. `pip-compile` cannot run in the project venv as it
      stands (see "Facts verified against the repo"), so first downgrade its pip with
      `/home/lucas/venvurlobs/bin/pip install "pip<26"`, or run the compile from a separate venv
      holding `pip==25.3` and `pip-tools==7.6.0`. Expect the diff to be `pyyaml`'s `# via` block
      turning from one line into a list, and nothing else. Add `pyyaml = "^6.0.3"` to
      `[tool.poetry.dev-dependencies]` in `pyproject.toml`.
      Commit: `chore(deps): declare pyyaml as a direct dev dependency`
- [ ] Add a session-scoped `repo_root` fixture to `tests/conftest.py` returning
      `Path(__file__).resolve().parent.parent`, then write the three test files.
      `test_compose_config.py`: no floating tag, both named volumes declared and mounted, every
      service carries a non-empty `profiles`, the three core services have a `healthcheck`,
      `loadgen` depends on `app` with `condition: service_healthy`, no `version` key, both retention
      flags present. `test_prometheus_config.py`: `global.scrape_interval` set, `scrape_configs`
      non-empty, every job has a `job_name` and at least one target.
      `test_grafana_provisioning.py`: every `grafana/dashboards/*.json` parses and has `uid`, `title`
      and non-empty `panels`; both provisioning YAMLs parse; the provider's `options.path` matches
      the container path the compose file mounts. Keep every line under 79 columns.
      Commit: `test(infra): validate compose, prometheus and grafana config`
- [ ] Add an `infra` job to `.github/workflows/python-app.yml`, parallel to `build`, on
      `ubuntu-latest`: checkout, then `docker compose --profile '*' config -q`, then `promtool check
      config` run through `docker run --rm --entrypoint promtool prom/prometheus:v3.13.2` with
      `prometheus.yml` bind-mounted read-only. The `--profile '*'` is load-bearing: without it
      `config` skips every profiled service and validates an empty file.
      Commit: `ci: validate compose and prometheus config with docker`
- [ ] Update `CLAUDE.md`: pinned versions in "Stack & versions"; every `docker compose` command in
      "Run the app / stack locally" carrying `--profile`; a rewrite of the three paragraphs on
      anonymous volumes and Grafana state loss, which this feature invalidates; a new
      "### Infra checks" subsection under "## Commands"; and a line in "Testing conventions" noting
      that the infra test files check configuration rather than a Python module.
      Commit: `docs: update CLAUDE.md for the hardened compose stack`
- [ ] Update `README.md`: pinned versions in "## Stack"; `--profile` in "## Running the stack" plus a
      short table of what each profile brings up; a rewritten "### Stopping and cleaning up" — the
      teardown table's `--volumes` row now destroys both databases, and the paragraph claiming
      Grafana state is already lost on `down` is no longer true; a note in "## Development" on
      running the infra checks; and, next to the existing `allow_all_prereleases` note in
      "### Updating dependencies", the opposite failure — `pip-compile` aborting with
      `ImportError: ... stdlib_pkgs` when pip is newer than pip-tools supports, which upgrading
      `pip-tools` does not fix.
      Commit: `docs: update README for named volumes and profiles`
- [ ] Run the verification steps below end to end and record the outcome here. No commit beyond the
      tick.

## Edge cases

- **The dashboards bind sits inside the Grafana volume.** `./grafana/dashboards` mounts at
  `/var/lib/grafana/dashboards`, i.e. *inside* `grafana_data`. Docker orders mounts by path depth, so
  the volume is mounted first and the bind lands on top; on first creation the volume is seeded from
  the image's `/var/lib/grafana`. It works, but it is the kind of arrangement that looks broken when
  something else breaks. Moving the bind to `/etc/grafana/dashboards` and adjusting `options.path`
  was considered and rejected: it trades documented Docker behaviour for a non-standard provisioning
  path.
- **`build` and `config` skip profiled services.** With every service behind a profile, a bare
  `docker compose build` or `docker compose config` sees nothing. This affects CI and anyone working
  locally, so it belongs in the README rather than being rediscovered.
- **`down` is not profile-filtered.** It removes the project's containers whatever profiles were
  enabled. That is the desired behaviour, but it contradicts the intuition of someone who just
  started a single profile. Confirm the same for `ps` and `logs` during implementation rather than
  assuming it.
- **`--volumes` becomes genuinely destructive.** Today it only discards Prometheus history; after
  this change it also erases `grafana_data`, the state the feature just protected. The README table
  has to say so in as many words.
- **Named volumes outlive image upgrades.** Once created, `prometheus_data` keeps its TSDB across
  pins. If a future Prometheus changes the TSDB format, the container starts against old data and
  `down --volumes` stops being optional.
- **Size-based retention is approximate.** `--storage.tsdb.retention.size=512MB` governs persisted
  blocks, not the WAL, so disk use can exceed it transiently.
- **`wget` is a property of the image variant.** The Prometheus image is the busybox variant
  (`io.prometheus.image.variant`) and Grafana's is Alpine-based; both ship `wget`. A future pin to a
  `distroless` variant silently breaks the healthcheck. The pin and the probe are coupled decisions.
- **`restart: unless-stopped` does not react to `unhealthy`.** Docker restarts containers that
  *exit*; a container that stays up while failing its healthcheck is left alone. The healthcheck is a
  readiness signal for `depends_on` and for `docker compose ps`, not a self-healing mechanism.
- **A short `start_period` breaks the `up` outright.** With `condition: service_healthy`, `loadgen`
  does not merely wait — if `app` never reaches healthy the whole `up` fails. Hence 30s of slack on
  the app probe.
- **The infra tests are structural, not semantic.** They do not catch the duplicated `gridPos` and
  `refId` the dashboard actually has, nor a query that returns nothing. They assert the file parses
  and carries the fields this feature introduces. Name the test functions so they cannot be mistaken
  for a dashboard correctness check.
- **The lockfile task cannot use the venv as it stands.** `pip-compile` is installed there but
  aborts against pip 26.2, and no newer `pip-tools` exists to fix it. Downgrading the venv's pip is
  the smaller move, but it means the project venv now carries a pip older than the system default —
  worth a line in the documentation task so the next person does not "helpfully" upgrade it back.
  The alternative, a dedicated compile venv, keeps the project venv clean at the cost of one more
  environment to remember.
- **flake8 at 79 columns, black at 88.** The new test files are the first realistic chance for this
  latent mismatch to fire, since black will happily leave an 85-column line that flake8 rejects. Keep
  lines short by construction.
- **Intermediate commits are not all green.** The infra tests land after the compose changes they
  assert, on purpose. Any ordering that puts them earlier leaves a red tree behind.
- **`loadgen` carries two `GF_SECURITY_ADMIN_*` environment variables** that do nothing — it is not
  Grafana. Noticed and deliberately left alone: the spec's scope does not include it, and removing
  them belongs in a change that is about the load generator.
- **Markdownlint.** The `CLAUDE.md` and `README.md` edits are checked live by the VS Code extension
  against `.markdownlint.jsonc` — compact tables (MD060), blank lines around fences and lists. Check
  the Problems panel; nothing gates a commit on it.

## Verification steps

- `docker compose --profile '*' config -q` exits zero and prints no obsolescence warning.
- `docker compose config --volumes` prints `prometheus_data` and `grafana_data`.
- `docker compose --profile core --profile load up --build -d`, then `docker compose ps` reports
  `app`, `prometheus` and `grafana` as `healthy` and `loadgen` as running.
- `docker compose --profile core up -d` starts three containers and no load generator;
  `docker compose --profile load up -d` starts `app` and `loadgen` and neither Prometheus nor
  Grafana.
- **Persistence, the test that defines the feature:** with the full stack up, create a dashboard by
  hand in the Grafana UI and note the time; let it scrape for a few minutes; `docker compose down`;
  bring it back with `docker compose --profile core --profile load up -d`. The hand-made dashboard is
  still there, and a `http_requests_total` query in Prometheus returns points from before the
  teardown.
- `promtool check config /etc/prometheus/prometheus.yml`, run through
  `docker run --rm --entrypoint promtool prom/prometheus:v3.13.2` with `prometheus.yml` bind-mounted
  read-only, reports `SUCCESS`.
- `/home/lucas/venvurlobs/bin/tox` passes end to end — `py311` with the three new files, `lint` and
  `safety`.
- Negative proof: temporarily replace a pinned tag with `:latest` and confirm
  `/home/lucas/venvurlobs/bin/pytest tests/test_compose_config.py` fails; revert, then repeat with
  one `profiles` key removed.
- `git show --stat HEAD` after each commit names only that task's files plus this `plan.md`.
- `git diff --stat main...HEAD` shows nothing under `app/`, `worker/` or `grafana/dashboards/`.
