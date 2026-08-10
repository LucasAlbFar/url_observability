# CU-86bbaf36c — 01b fix and improvements (plan)

Spec: [./spec.md](./spec.md)

## Context

This lands entirely in configuration and its tests. The compose file, `prometheus.yml`, the CI
workflow, `worker/Dockerfile`, `tox.ini`, `CLAUDE.md` and `README.md` change; three of the four
existing test files gain or move assertions and one new test file appears. Nothing under `app/`,
`grafana/` or `worker/load_driver.py` is touched, and no image is bumped.

The eight items come from three sources: `specs/CU-86bb30dec/plan.md` recorded the retention
deprecation, the duplicated Prometheus tag, the dead environment variables and the flake8/black
mismatch as debt it chose not to fix; the first green CI run of that feature produced the Node.js 20
annotation; and a sweep of `avaliacao-inicial-CONGELADO.md` against the repo on 2026-08-07 found the
unpinned `httpx` and the never-remeasured Prometheus `start_period`. The roadmap entry is
`~/.claude/plans/url-observability/00_roadmap-observabilidade-features.md` under F1.1.

Each task below is its own commit, and the task's checkbox is ticked in that same commit.

## Facts verified against the repo

Measured 2026-08-07 on Docker 29.7.1 / Compose v5.3.1, against `prom/prometheus:v3.13.2`.

- **The deprecated flags name their own replacement.** `docker run --rm prom/prometheus:v3.13.2
  --help` marks `--storage.tsdb.retention.time` and `--storage.tsdb.retention.size` `[DEPRECATED]`
  and says for each: *"use the `storage.tsdb.retention.time` field in the config file instead"*. So
  the YAML shape is `storage.tsdb.retention.{time,size}`, not a guess.
  `--storage.tsdb.path` carries no such marking and stays on the command.
- **`promtool check config` accepts the config-file form.** A `prometheus.yml` carrying
  `storage: {tsdb: {retention: {time: 7d, size: 512MB}}}` returns
  `SUCCESS: ... is valid prometheus config file syntax`, exit **0**.
- **`promtool check config` *rejects* a malformed value.** This is the fact the previous feature
  assumed and never measured, and it decides where the check lives. All three cases exit **1**:
  - `time: 7x` → `FAILED: parsing YAML file ...: unknown unit "x" in duration "7x"`
  - `size: 512XB` → `FAILED: parsing YAML file ...: units: unknown unit XB in 512XB`
  - a typo'd key (`retentionn:`) → `FAILED: ... yaml: unmarshal errors: line 12: field retentionn
    not found in type config.plain` — the unmarshal is strict.
  **Consequence:** the CI `infra` job already carries the check. `tests/test_prometheus_config.py`
  stays presence-only; no value-shape regex is needed, and adding one would duplicate a check that
  reads the real parser.
- **Config-file retention is genuinely in force, not silently dropped.** A throwaway container run
  with only `--config.file` and `--storage.tsdb.path`, no retention flags, reports
  `storageRetention: "1w or 512MiB"` at `/api/v1/status/runtimeinfo` — **byte-identical** to what the
  current flag-configured stack reports — and logs
  `msg="TSDB retention updated" duration=1w size=512MiB percentage=0` at startup. The move is
  therefore behaviour-neutral by measurement, not by assertion.
- **The image tag derives cleanly from the compose file.**
  `docker compose --profile '*' config --format json | jq -r '.services.prometheus.image'` prints
  `prom/prometheus:v3.13.2`. The alternative `config --images` also works but is **not**
  service-scoped: it prints all four images including the two locally-built ones
  (`url_observability-app`, `url_observability-loadgen`), so it would need grepping and would get
  worse as F2 adds services. `--format json` is the form to use.
- **`jq` ships on the runner.** `actions/runner-images` lists `jq 1.7.1-3ubuntu0.24.04.2` for
  Ubuntu 24.04, so the derivation needs no install step.
- **The tag has seven copies across four files**, not the two the previous feature recorded:
  `docker-compose.yml:24`, `.github/workflows/python-app.yml:52`, `CLAUDE.md:16` and `:66`, and
  `README.md:31`, `:101` and `:146`. `README.md:31` is the awkward one — it names a bare `v3.13.2`
  with no repository, so a grep for `prom/prometheus:` does not find it.
- **`assert_pinned` forbids templating the compose `image:` value.**
  `tests/test_compose_config.py:34-37` splits on the last `:` and requires `^v?\d+\.\d+\.\d+$`, so
  `${PROMETHEUS_VERSION}` and `@sha256:...` both fail. Deriving on the reading side leaves it alone.
- **`actions/checkout@v5` and `actions/setup-python@v6` are not the current majors.** Reading
  `action.yml` at each tag: `checkout@v4` and `setup-python@v5` declare `using: node20`;
  `checkout@v5`, `checkout@v7`, `setup-python@v6` and `setup-python@v7` all declare `using: node24`.
  Latest releases are `checkout` **v7.0.1** and `setup-python` **v7.0.0**. The spec originally named
  v5/v6 and was amended before implementation started.
- **`pip install httpx` resolves to 0.28.1 today** under `python:3.11.15`. That is the version the
  current `worker/Dockerfile` silently gets, and the one to pin so the change is a no-op at build
  time.
- **`test_every_dockerfile_base_image_is_pinned` cannot see the unpinned install.**
  `tests/test_compose_config.py:57-68` matches `^FROM\s+(\S+)` only, so `worker/Dockerfile:4`'s
  `RUN pip install httpx` is invisible to it. The root `Dockerfile` installs from
  `requirements/base.txt` and is unaffected.
- **flake8 reads a `[flake8]` section from `tox.ini`.** Verified with a probe file carrying 82- and
  83-column lines: with the section appended to `tox.ini` flake8 exits 0, without it exits 1 with
  two `E501`. `tox.ini` currently has only `[tox]`, `[testenv]`, `[testenv:lint]` and
  `[testenv:safety]`, and there is no `.flake8` or `setup.cfg` in the repo. **No new file is needed.**
- **The repo passes flake8 at both 79 and 88 today.** `flake8 .` and `flake8 --max-line-length=88 .`
  both exit 0, so the change fixes nothing currently broken — it is purely forward-looking, which is
  exactly the claim the previous plan made.
- **`DEBUG` is dead on `loadgen` and live on `app`.** `app/core/config.py:10` declares
  `DEBUG: bool = True` and `tests/test_config.py` covers both the default and the override.
  `worker/load_driver.py` reads no environment at all, so `GF_SECURITY_ADMIN_USER`,
  `GF_SECURITY_ADMIN_PASSWORD` and `DEBUG` on `loadgen` (`docker-compose.yml:77-79`) are inert, as
  are `LOADGEN_INTERVAL` and `LOADGEN_URLS` on `app` (`:9-10`). The `GF_SECURITY_ADMIN_*` pair on
  the `grafana` service (`:50-51`) is the real one.
- **Prometheus reaches `healthy` in 6 seconds against the existing volume**, first probe passing,
  `FailingStreak: 0`. **But the measurement is weak and must not be read as reassurance:**
  `url_observability_prometheus_data` holds only **480 KB** — two block directories, `chunks_head`
  and the WAL — so it does not exercise the write-ahead-log replay the check was meant to test. See
  Edge cases.
- **The stack was down before this measurement and was returned to down afterwards**, with
  `docker compose --profile '*' down`. Both named volumes survive, as F1 established.

## Affected files

| File | Change |
| --- | --- |
| `prometheus.yml` | gains a `storage.tsdb.retention` block with `7d` / `512MB` |
| `docker-compose.yml` | both retention flags leave the `prometheus` command; five dead env vars deleted; `start_period` reviewed |
| `worker/Dockerfile` | `httpx` pinned to an exact version, inline |
| `.github/workflows/python-app.yml` | promtool image derived from compose; `checkout@v7`, `setup-python@v7` |
| `tox.ini` | new `[flake8]` section with `max-line-length = 88` |
| `tests/test_compose_config.py` | retention assertion narrows to the path flag; pinning test reaches `RUN pip install` |
| `tests/test_prometheus_config.py` | gains the retention assertion |
| `tests/test_docs_versions.py` | new — doc copies of compose images must match the compose file |
| `CLAUDE.md` | three false sentences corrected; `### Run the app / stack locally` cut to sibling size |
| `README.md` | version bullet normalised; retention location stated; promtool snippet reviewed |

## Tasks

One commit per task; the checkbox is ticked in the same commit.

- [x] **Move retention into `prometheus.yml`.** Add
      `storage: {tsdb: {retention: {time: 7d, size: 512MB}}}` and delete the two flags from the
      compose `command`, keeping `--config.file` and `--storage.tsdb.path`. Values carry over
      unchanged so the move is behaviour-neutral.
      Commit: `refactor(prometheus): configure retention in the config file`
- [x] **Move the assertion with the setting.** Narrow `test_prometheus_command_bounds_storage` in
      `tests/test_compose_config.py` to `--storage.tsdb.path` alone (shrinking `RETENTION_FLAGS`
      accordingly) and add a retention-presence assertion to `tests/test_prometheus_config.py`
      hanging off the existing `prometheus_config` fixture. Presence only — promtool validates the
      values, as measured above.
      Commit: `test(infra): assert retention where it is now configured`
- [x] **Derive the promtool image from the compose file.** Replace the literal in the `infra` job
      with a `--format json` + `jq` read of `.services.prometheus.image`, guarded so an empty or
      `null` result fails the step rather than reaching `docker run` — the same shape as the
      `--profile '*'` guard the job already carries.
      Commit: `ci(infra): derive the prometheus image from the compose file`
- [x] **Make the documentation copies enforceable.** Add `tests/test_docs_versions.py`: for every
      image `docker-compose.yml` pins, any `<repository>:<tag>` reference to that repository in
      `CLAUDE.md` or `README.md` must carry the same tag. Normalise `README.md:31` from a bare
      `v3.13.2` to the full reference so it falls under the rule.
      Done: the file also carries a second test that fails if the scan matches nothing at all, so a
      renamed repository cannot leave the drift check vacuously green. Adding a fourth
      config-parsing test file made three sentences counting them stale — `CLAUDE.md`'s `### Infra
      checks` command and prose, its testing-conventions bullet, and `README.md`'s project-layout
      comment — so those are corrected in the same commit rather than left lying.
      Commit: `test(docs): fail when a documented image tag drifts from compose`
- [x] **Pin `httpx` in the worker image.** `RUN pip install httpx==0.28.1` — inline, no
      `worker/requirements.txt`, keeping the load generator decoupled as `CLAUDE.md` requires.
      Commit: `build(worker): pin the httpx version`
- [x] **Teach the pinning test about installed packages.** Extend the Dockerfile test so a
      `RUN pip install` naming a package without `==` fails, in any Dockerfile in the repo. The root
      `Dockerfile` installs from a requirements file and must keep passing.
      Done: both Dockerfile tests now discover their inputs with `rglob("Dockerfile")` instead of
      naming two paths, so F2's third image inherits both rules. The parser was probed directly
      against six shapes — the two real lines, a `\`-continuation, a chained `&&` install, the long
      `--requirement` form and `pip3` — and yields the package names expected in each.
      Commit: `test(infra): reject unpinned pip installs in dockerfiles`
- [x] **Give flake8 the width black uses.** Append `[flake8]` with `max-line-length = 88` to
      `tox.ini`. No new file.
      Commit: `chore(lint): align flake8 with black at 88 columns`
- [ ] **Delete the dead environment variables.** Remove `LOADGEN_INTERVAL` and `LOADGEN_URLS` from
      `app` and `GF_SECURITY_ADMIN_USER`, `GF_SECURITY_ADMIN_PASSWORD` and `DEBUG` from `loadgen`.
      Keep `DEBUG` on `app` and `GF_SECURITY_ADMIN_*` on `grafana`.
      Commit: `chore(compose): drop environment variables nothing reads`
- [ ] **Settle the Prometheus `start_period`.** Record the measurement and either keep 10s with the
      evidence attached or raise it. Do not raise it for symmetry with Grafana — the two boot for
      different reasons, and the reasoning belongs in Edge cases either way.
      Commit: `chore(compose): justify the prometheus start_period`
- [ ] **Bump the actions.** `actions/checkout@v7` in both jobs, `actions/setup-python@v7`.
      Commit: `ci: move the actions off node 20`
- [ ] **Correct the three false sentences in `CLAUDE.md`.** The Prometheus-bump instruction, the
      description of what the `infra` job runs, and the paragraph telling the reader to stay under
      79 columns. Each is made false by a task above.
      Commit: `docs: correct the claims this feature invalidates`
- [ ] **Cut `### Run the app / stack locally` to sibling size.** Keep the two commands, the
      repo-root rule, `--profile` on every subcommand, both volumes surviving a `down`, and the
      ninety-second Grafana `start_period`. Everything else is derivation and already lives in
      `specs/CU-86bb30dec/plan.md`; confirm each dropped fact is there before dropping it.
      Commit: `docs: trim the stack section to its conclusions`
- [ ] **Update `README.md`.** Where retention is configured, and whatever the derivation task made
      inaccurate in the infra-check snippet.
      Commit: `docs: update the readme for config-file retention`

## Edge cases

- **The retention move is provably neutral, and that is unusual enough to say out loud.** Both the
  flag form and the config-file form produce `storageRetention: "1w or 512MiB"`. `7d` renders as
  `1w` and `512MB` as `512MiB` in both — Prometheus normalises the units on read, so the runtime
  string is not a copy of the input and cannot be used to tell the two forms apart. The way to tell
  is the startup log line `TSDB retention updated`, which only the config-file form emits.
- **`promtool` rejecting bad values is what makes the Python test cheap.** If it had accepted them,
  `tests/test_prometheus_config.py` would have had to validate duration and size shapes with regexes
  — a second, worse parser. Measured, it rejects, so the Python test asserts presence and the real
  parser does the rest. This is the branch the spec left open, and it closed in the good direction.
- **`--storage.tsdb.path` is load-bearing and stays.** The compose `command` overrides the image's
  default arguments entirely; drop the path flag and the TSDB lands wherever the image's `WORKDIR`
  puts it, which coincides with the mount only by accident. It is also not deprecated.
- **The `start_period` measurement does not test what it was written to test.** Six seconds to
  `healthy` sounds like a clean pass, but `prometheus_data` holds 480 KB. WAL replay on a near-empty
  database is not evidence about WAL replay on a full one. What genuinely bounds the risk is the
  retention this feature is moving: 512 MB is the ceiling on the TSDB, so the worst case is bounded
  even though it has not been observed. Raising `start_period` on a guess would be worse than
  keeping 10s with this caveat written down — a `start_period` that is too long delays nothing but
  hides a real failure for that much longer.
- **A short `start_period` under `service_healthy` fails the `up`, it does not merely warn.**
  `grafana` waits on `prometheus` with `condition: service_healthy`, so this value is not cosmetic.
  The same mechanism raised Grafana's own `start_period` from 10s to 90s during F1.
- **Deleting `LOADGEN_URLS` removes a duplicate, not a source.** The list of endpoints under load
  lives in `URLS` in `worker/load_driver.py`, which is the only one any code reads. `LOADGEN_URLS`
  was a stale copy of it, and copies that nothing validates drift.
- **`DEBUG` appears twice and only one is dead.** On `app` it is read by `app/core/config.py` and
  covered by `tests/test_config.py`; on `loadgen` nothing reads it. Deleting the wrong one breaks a
  test, which is the good outcome, but the distinction should be made deliberately rather than
  discovered.
- **The documentation-consistency test constrains prose.** It makes a bump self-checking, at the
  cost of dictating that a version may only be written as `<repository>:<tag>` in the two documents
  it scans. `README.md:31` currently violates that and is normalised as part of the task. This is a
  real trade — a test that greps prose is unusual — accepted because the alternative leaves five
  copies as a manual checklist that `CLAUDE.md` then has to describe.
- **`config --images` is the wrong tool for the derivation.** It resolves, but it is not
  service-scoped: it prints the two locally-built images alongside the two pulled ones. F2 adds more
  services and makes that worse. `--format json` with a `jq` path is stable regardless.
- **The derivation makes a `CLAUDE.md` sentence false, and that sentence is currently correct.**
  Until the derivation task lands, "a Prometheus bump also has to touch the `infra` job" is true.
  The correction is sequenced after it for exactly that reason, and the two are separate commits so
  neither tree lies.
- **Setting flake8 to 88 relaxes nothing that is currently violated.** The repo passes at 79 today.
  The change prevents a future conflict rather than fixing a present one, so no file is reformatted
  and no diff outside `tox.ini` is expected from that task.
- **Pinning `httpx` to 0.28.1 is a no-op at build time today** — it is what the unpinned install
  already resolves to. It becomes meaningful on the first rebuild after upstream releases 0.29, which
  is precisely when an unpinned install would have changed the image without anyone asking.
- **The pinning test has to tolerate the root `Dockerfile`.** It installs from
  `requirements/base.txt`, not a named package, so the new assertion must key on `pip install <name>`
  and not fire on `pip install -r`. It also must not fire on the `--upgrade pip` in the same line.
- **Whether the provisioned dashboard renders under Grafana 12.4.7 is still unknown.** The seven
  panels use `type: "graph"`, whose compatibility layer has been off by default since Grafana 11.
  Nothing in this feature depends on the answer, but F2's scope does: migration and reconstruction
  are different features. It stays a verification step here rather than a task, and needs a browser.
- **These are eight independent changes sharing one branch.** Nothing in the list depends on
  anything else except the `CLAUDE.md` correction depending on the derivation. If any single item
  turns out to be larger than it looks, it can be dropped from the branch without disturbing the
  rest — which is what the roadmap's "two lines and a test" rule is for.

## Verification steps

To be run against the finished branch; each step records its measured outcome here.

- `tox` end to end — tests, lint and safety.
- `docker compose --profile '*' config -q` and `config --services | grep -q .`, the two commands the
  `infra` job runs.
- `promtool check config` against the new `prometheus.yml` through the pinned image — expect
  `SUCCESS`.
- **Negative proof, retention:** set `time: 7x` in `prometheus.yml`, confirm the `infra` job's
  promtool step fails with `unknown unit "x"`, revert, confirm green.
- **Negative proof, docs drift:** change `prom/prometheus:v3.13.2` to `:v3.13.3` in
  `docker-compose.yml` alone; confirm `tests/test_docs_versions.py` fails and names the file, that
  the `infra` job would now pull `v3.13.3`, then revert.
- **Negative proof, unpinned install:** remove `==0.28.1` from `worker/Dockerfile`, confirm the
  pinning test fails, restore.
- **Negative proof, retention assertion:** delete the `storage:` block, confirm exactly one Python
  test fails.
- **Retention in force:** `docker compose --profile core up -d prometheus`, then
  `curl -s localhost:9090/api/v1/status/runtimeinfo | jq -r .data.storageRetention` — expect
  `1w or 512MiB`. Confirm `docker compose logs prometheus` carries `TSDB retention updated` and no
  deprecated-flag warning.
- **Cold `up` with a populated volume:** time `prometheus` to `healthy` and confirm `grafana` starts
  behind it without the `up` failing. Record the observed time and the volume's size, since the
  second number is what makes the first meaningful.
- `flake8` accepts an 88-column line and rejects an 89-column one, via a throwaway probe file.
- A CI run on the branch: both jobs green, no Node.js deprecation annotation.
- `git diff --stat main...HEAD` — nothing under `app/` or `grafana/`, and only `Dockerfile` under
  `worker/`.
- **Does the provisioned dashboard render under Grafana 12.4.7?** Bring the stack up, open the
  provisioned dashboard in a browser, and record what is actually shown — panels, empty panels, or
  an error. This produces no code. If it does not render, say so plainly here, because F2's scope
  changes from migrating the panels to rebuilding them.
- Word and line counts for the trimmed `CLAUDE.md` section against its siblings, and an item-by-item
  check that every dropped fact is present in `specs/CU-86bb30dec/plan.md` or `README.md`.
