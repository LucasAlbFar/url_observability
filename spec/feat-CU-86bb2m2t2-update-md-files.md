# Feature — Document how to stop and tear down the local stack

- **Branch**: `feat/CU-86bb2m2t2-update-md-files`
- **Ticket**: CU-86bb2m2t2
- **Status**: Approved
- **Affected files**: `README.md`, `CLAUDE.md`

## 1. Summary

Add a "stopping / cleaning up" category to both `README.md` and `CLAUDE.md` so the documented lifecycle of the local stack is symmetric: today the docs only explain how to **start** it. The new section documents the graceful interrupt shortcut (`Ctrl+C`) and the escalation ladder of Docker Compose teardown commands, up to the full `docker compose down --volumes --rmi all`.

## 2. Objective

Someone who followed the "Running the stack" instructions should be able to answer, from the docs alone:

- How do I stop the stack I just started in this terminal?
- How do I remove the containers and network it created?
- How do I reclaim everything (images, anonymous volumes) and start from a clean slate?
- What exactly does each of those commands destroy, and what survives?

## 3. Motivation

- `README.md` "Running the stack" (README.md:33-50) ends at the service URL table and the standalone `uvicorn` snippet — no stop instructions.
- `CLAUDE.md` "Run the app / stack locally" (under `## Commands`) has the same gap.
- The result is that after following the docs the user is left with running containers, a compose network, Grafana's anonymous volume, and four images on disk (`prom/prometheus:latest`, `grafana/grafana:latest`, plus the locally built `app` and `loadgen` images), with no documented way to clean any of it up.

## 4. Scope

### In scope

- `README.md` — new user-facing section.
- `CLAUDE.md` — equivalent entry in the commands reference.

### Out of scope

- `docker-compose.yml` and any other infra file.
- Makefiles, shell scripts, aliases, or CI changes.
- Any application, worker, or test code.

## 5. Expected behaviour — content to document

The docs should present the options in order of increasing destructiveness:

| Goal | Command / key |
| --- | --- |
| Interrupt a foreground `docker compose up` | `Ctrl+C` (graceful shutdown; a second `Ctrl+C` force-kills instead of waiting) |
| Interrupt the standalone `uvicorn app.main:app ...` process | `Ctrl+C` |
| Stop containers but keep them | `docker compose stop` |
| Stop and remove containers + the default network | `docker compose down` |
| Run detached, stop later from any terminal | `docker compose up -d --build` → `docker compose down` |
| Full teardown: containers, network, anonymous volumes, **all** service images | `docker compose down --volumes --rmi all` |

Both documents must use the same commands, with no contradictions between them.

## 6. Accuracy constraints (verified against `docker-compose.yml`)

The wording must stay true to what this compose file actually declares:

- **No named volumes exist.** The only volumes are bind mounts: `./prometheus.yml`, `./grafana/provisioning/dashboards`, `./grafana/provisioning/datasources`, `./grafana/dashboards`. `docker compose config --volumes` returns nothing.
- **`--volumes` therefore only removes *anonymous* volumes** — in practice Grafana's `/var/lib/grafana`. That means Grafana runtime state (manually created dashboards, users, preferences) is lost. The provisioned datasource and the "FastAPI Metrics" dashboard come back on the next `up`, because they are bind-mounted from the repo.
- **Bind-mounted repo files are never deleted** by `down --volumes`. Say this explicitly so the command doesn't read as dangerous to the working tree.
- **`--rmi all` removes the images of every service**: the two locally built images (`app`, `loadgen`) and the two pulled ones (`prom/prometheus:latest`, `grafana/grafana:latest`). The next `docker compose up --build` has to re-pull and rebuild, so present it as the "reclaim disk / start fully clean" option, not the routine one.
- **`Ctrl+X` is not a stop shortcut** in this context — it is an editor binding (e.g. nano's "exit"). Neither `docker compose up` nor `uvicorn` reacts to it. State this once, plainly, so the docs don't propagate a shortcut that does nothing.

## 7. Placement and style

### `README.md`

- Add `## Stopping the stack` (alternatively `### Stopping and cleaning up` nested under "Running the stack") directly after the service URL table at README.md:43, before the standalone `uvicorn` snippet or right after it — whichever keeps the reading order start → access → stop.
- Match the existing style: short prose, Markdown tables, fenced `bash` blocks.
- Tone stays user-facing/tutorial.

### `CLAUDE.md`

- Extend the "Run the app / stack locally" block under `## Commands` with the same commands, in the file's terse, comment-annotated `bash` block style.
- Keep CLAUDE.md's "why / gotcha" register: the anonymous-volume behaviour and the cost of `--rmi all` belong here as notes, not in the README's happy path.

## 8. Acceptance criteria

- [ ] `README.md` has a stop/cleanup section; `CLAUDE.md` has the equivalent entry.
- [ ] `Ctrl+C` is documented for both `docker compose up` and standalone `uvicorn`.
- [ ] `docker compose down` and `docker compose down --volumes --rmi all` are both present, each with a one-line explanation of what it removes.
- [ ] The `Ctrl+X` clarification appears (once) so the shortcut is not mistaken for a stop key.
- [ ] The volume and image side effects are described accurately per section 6 — in particular, no claim that named volumes exist.
- [ ] The two documents agree with each other.
- [ ] No file other than `README.md` and `CLAUDE.md` is changed.

## 9. Out of scope / possible follow-ups

- A `make down` target or `scripts/stop.sh` wrapper.
- Adding a named volume for Grafana so dashboards/users survive `down` (would change the semantics documented here).
- Documenting `--remove-orphans` for containers left over from earlier compose-file revisions.

## 10. Verification

The change is documentation-only, so verification is manual:

1. Follow the README from `docker compose up --build` through the new stop section on a clean machine; each command should behave as described.
2. Confirm the claims about volumes and images:

   ```bash
   docker compose config --volumes   # expected: no output (no named volumes)
   docker compose config --images    # expected: the app, loadgen, prometheus and grafana images
   ```

3. After `docker compose down --volumes --rmi all`, check that `docker compose ps` is empty and `docker images` no longer lists the four service images, while `grafana/dashboards/fastapi_metrics.json` and the rest of the working tree are untouched.
4. Re-run `docker compose up --build` and confirm Grafana comes back with the provisioned datasource and dashboard.
