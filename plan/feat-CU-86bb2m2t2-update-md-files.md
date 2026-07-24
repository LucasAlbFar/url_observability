# Implementation plan — CU-86bb2m2t2 · Document how to stop and tear down the local stack

- **Branch**: `feat/CU-86bb2m2t2-update-md-files`
- **Ticket**: CU-86bb2m2t2
- **Spec**: [spec/feat-CU-86bb2m2t2-update-md-files.md](../spec/feat-CU-86bb2m2t2-update-md-files.md) (status: Approved)

## Context

`README.md` and `CLAUDE.md` document only how to **start** the local stack. Both stop at the
service URL table / the `uvicorn` one-liner, so after following the docs the user is left with
four running containers, a compose network, Grafana's anonymous volume and four images on disk,
with no documented way to stop or clean any of it.

The spec asks for a "stopping / cleaning up" category in both files, presenting the teardown
options in order of increasing destructiveness — from `Ctrl+C` up to
`docker compose down --volumes --rmi all` — with accurate statements about what each command
actually destroys in *this* compose file.

Documentation-only change. Scope is exactly two files.

## Facts verified against the repo (do not contradict these)

Checked in `docker-compose.yml`:

- No top-level `volumes:` key → **no named volumes exist**; `docker compose config --volumes`
  prints nothing.
- All declared volumes are bind mounts: `./prometheus.yml`, `./grafana/provisioning/dashboards`,
  `./grafana/provisioning/datasources`, `./grafana/dashboards`.
- `./grafana/dashboards` is mounted *inside* `/var/lib/grafana` (at `/var/lib/grafana/dashboards`).
  The `grafana/grafana` image declares `VOLUME /var/lib/grafana`, so an **anonymous** volume is
  created for Grafana's runtime state (`grafana.db`: manually created dashboards, users,
  preferences). That anonymous volume is what `--volumes` removes; the nested bind mount is repo
  content and is untouched.
- Neither `Dockerfile` (app) nor `worker/Dockerfile` declares a `VOLUME`, so `app`/`loadgen` have
  no anonymous volumes.
- Four service images: locally built `app` and `loadgen`, pulled `prom/prometheus:latest` and
  `grafana/grafana:latest` → that is what `--rmi all` removes.
- Services have no `container_name`; the compose project name comes from the directory
  (`url_observability`), so every command below must be run from the repo root.

## Affected files

| File | Change |
| --- | --- |
| `README.md` | New user-facing `### Stopping and cleaning up` section inside "Running the stack" |
| `CLAUDE.md` | Teardown commands + gotchas appended to `### Run the app / stack locally` |

This plan file itself (`plan/feat-CU-86bb2m2t2-update-md-files.md`) is already written and is not
part of the implementation diff — the spec's acceptance criterion "no file other than `README.md`
and `CLAUDE.md` is changed" applies to the two commits below.

Explicitly **not** touched: `docker-compose.yml`, `Dockerfile`, `worker/Dockerfile`,
`prometheus.yml`, `grafana/**`, any `app/`, `worker/`, `tests/` or `requirements/` file, `tox.ini`,
`pyproject.toml`.

---

## Tasks

Tasks 1 and 2 are each one commit, independent of each other, and can be done or reverted in any
order; task 3 is a verification pass with no commit of its own.

### Task 1 — `README.md`: add the "Stopping and cleaning up" section

- **Where:** inside `## Running the stack`, after the standalone `uvicorn` snippet
  (currently README.md:45-50), as `### Stopping and cleaning up`. This keeps the reading order
  *start → access → run standalone → stop*, and lets the `Ctrl+C` line cover both the compose run
  and the `uvicorn` process in one place.
- **Content** (user-facing tone, existing style: short prose + Markdown table + fenced `bash`):
  1. One sentence: `Ctrl+C` in the terminal running `docker compose up` sends a graceful shutdown;
     a second `Ctrl+C` force-kills instead of waiting. The same applies to the standalone
     `uvicorn` process.
  2. One sentence, once, in the whole feature: **`Ctrl+X` is not a stop shortcut** — it is an
     editor binding (e.g. nano's "exit"); neither `docker compose up` nor `uvicorn` reacts to it.
  3. The escalation table, in this order:

     | Goal | Command |
     | --- | --- |
     | Stop the foreground run | `Ctrl+C` |
     | Stop containers, keep them | `docker compose stop` (restart with `docker compose start`) |
     | Stop + remove containers and the default network | `docker compose down` |
     | Run detached, stop later from any terminal | `docker compose up -d --build` → `docker compose down` |
     | Full teardown (containers, network, anonymous volumes, all four images) | `docker compose down --volumes --rmi all` |

  4. A short "what survives" note: `--volumes` only removes *anonymous* volumes — in practice
     Grafana's `/var/lib/grafana`, so dashboards/users created by hand in the Grafana UI are lost;
     the provisioned datasource and the "FastAPI Metrics" dashboard come back on the next `up`
     because they are bind-mounted from the repo. Bind-mounted repo files are **never** deleted.
  5. One line framing `--rmi all` as "reclaim disk / start fully clean", not the routine option:
     the next `docker compose up --build` has to re-pull and rebuild.
  6. Run all commands from the repo root (the compose project name comes from the directory).
- Commit: `docs(readme): document how to stop and tear down the local stack`

### Task 2 — `CLAUDE.md`: extend "Run the app / stack locally"

- **Where:** `### Run the app / stack locally` (CLAUDE.md:57-65), extending the existing `bash`
  block and adding a short prose note under it — matching the file's terse, comment-annotated
  style (same shape as `### Security / dependency audit`).
- **Content:**
  - Append to the fenced block, aligned trailing comments, same commands as README (no drift):

    ```bash
    docker compose up -d --build    # detached; stop later from any terminal
    # Ctrl+C in the foreground run  -> graceful stop (second Ctrl+C force-kills)
    docker compose stop             # stop containers, keep them (resume: docker compose start)
    docker compose down             # + remove containers and the default network
    docker compose down --volumes --rmi all   # + anonymous volumes + all four service images
    ```

  - Prose note below the block, in CLAUDE.md's "why / gotcha" register:
    - No named volumes are declared (`docker compose config --volumes` is empty); `--volumes` only
      drops Grafana's anonymous `/var/lib/grafana`, i.e. hand-made dashboards/users/preferences.
      The provisioned datasource + `grafana/dashboards/fastapi_metrics.json` are bind mounts and
      come back on the next `up`; bind-mounted repo files are never removed.
    - `--rmi all` deletes the two built images (`app`, `loadgen`) **and** the two pulled ones
      (`prom/prometheus:latest`, `grafana/grafana:latest`) — the pulled ones are shared with any
      other project on the machine using them, and the next `up --build` re-pulls and rebuilds.
      Use it to reclaim disk, not routinely.
- Commit: `docs(claude): document stack teardown commands and their side effects`

### Task 3 — Consistency + accuracy verification (no commit unless it finds a fix)

- Diff the command sets in both files: identical commands, identical flags, no contradictory
  claims (acceptance criterion "the two documents agree with each other").
- The `Ctrl+X` clarification appears **once** across the feature (in README, per Task 1) — check it
  wasn't duplicated into CLAUDE.md.
- Run the spec's verification commands and confirm the docs match reality:

  ```bash
  docker compose config --volumes   # expect: no output
  docker compose config --images    # expect: app, loadgen, prom/prometheus:latest, grafana/grafana:latest
  ```

- `git status` shows only `README.md` and `CLAUDE.md` modified.

---

## Edge cases and gotchas to keep in mind while writing

1. **No named volumes.** The most likely wrong sentence to write is "removes the named volumes".
   There are none — say *anonymous*.
2. **The bind mount nested under an anonymous volume.** `./grafana/dashboards` lives at
   `/var/lib/grafana/dashboards`, inside the anonymous volume's mount point. `--volumes` removing
   `/var/lib/grafana` must not be described as touching `grafana/dashboards/*.json` in the repo.
3. **`--rmi all` has machine-wide effects.** `prom/prometheus:latest` and `grafana/grafana:latest`
   are shared images; other projects lose them too. Docker skips removal if another *container*
   still uses them, so the command can partially succeed with a warning — don't promise a clean
   wipe unconditionally.
4. **`--rmi all` vs `--rmi local`.** Only `all` also drops the pulled images. Don't blur the two.
5. **`docker compose down` does not remove images or the build layer cache**, so a following
   `up --build` is fast — worth one clause so users pick `down` by default.
6. **`Ctrl+C` twice.** The second interrupt force-kills rather than waiting for the grace period;
   containers may be left in a stopped-but-present state, cleaned by `down`.
7. **`loadgen` error-loops if only `app` is stopped** (`docker compose stop app`): the driver keeps
   firing at `http://app:8002` and logs failures. If a per-service stop is mentioned, mention this;
   otherwise keep the docs whole-stack to avoid the trap.
8. **The compose project name comes from the directory.** Running `down` from another directory
   silently targets a different (or empty) project. State "from the repo root".
9. **Detached mode ordering:** `docker compose up -d --build` — keep the exact string identical in
   both files so a copy-paste diff between them is empty.
10. **`version: '3.8'` in `docker-compose.yml` is obsolete** and makes recent Compose print a
    warning on every command. Out of scope — do **not** "fix" it in this feature (the spec forbids
    touching `docker-compose.yml`); just don't let the warning be mistaken for a broken command.
11. **The README line references in the spec (`README.md:33-50`, `:43`) are still accurate today** —
    but do Task 1 and Task 2 as separate commits so a shift in one file never invalidates the other.
12. **`docker compose down -v` vs `--volumes`** are the same flag; pick the long form everywhere
    (self-documenting, and matches the spec's table).
13. **Out of scope, do not add:** a `make down` target, `scripts/stop.sh`, `--remove-orphans`, or a
    named volume for Grafana persistence (that last one would invalidate the wording above).

## Verification (manual — documentation-only change)

1. Two commits on the branch: `docs(readme): ...` and `docs(claude): ...`, touching only
   `README.md` / `CLAUDE.md` respectively (`git show --stat` on each).
2. From the repo root, replay the documented ladder on a clean machine:
   `docker compose up --build` → `Ctrl+C` → `docker compose up -d --build` → `docker compose down`
   → `docker compose up --build` → `docker compose down --volumes --rmi all`.
3. After the full teardown: `docker compose ps` is empty, `docker images` no longer lists the four
   service images, and `git status` is clean (`grafana/dashboards/fastapi_metrics.json` and the
   rest of the working tree untouched).
4. Re-run `docker compose up --build`: Grafana comes back with the provisioned Prometheus
   datasource and the "FastAPI Metrics" dashboard; the manually created Grafana state is gone —
   exactly as documented.
5. Walk the spec's acceptance-criteria checklist (section 8) item by item against the two files.
6. No test/lint run is required (no Python touched); `tox` remains green by construction.
