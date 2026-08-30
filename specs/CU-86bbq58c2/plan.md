# CU-86bbq58c2 — 04 cardinality guard (plan)

Spec: [./spec.md](./spec.md)

## Context

Discovery arrived two tickets ago and was proven one ticket ago: a service joins the scrape by
declaring four labels on its own compose block, and `prometheus.yml` names no service. What that
mechanism has no answer for is a service that opts in and then writes without bound. The `keep` rule
discards a container that did not ask; nothing discards a series that should never have been
written.

The work lands in five places. A new `noisy/` module that misbehaves on purpose, running on the
app's image behind a `chaos` profile. Two blocks in `prometheus.yml` — the limits in `global:` and
the drop rules in `metric_relabel_configs`, neither of which exists in that file today. A fourth row
in the dashboard. Two sibling tests whose derivation reads the wrong source and which the noisy
service breaks before the guard can be written. And the two documents.

The order is the substance: **produce the degradation, measure it, then limit it.** All three
services are immune to this failure by design, so a guard written first is a guard nobody has
watched fire.

## Facts verified against the repo

Measured 2026-08-30 against `main`, with the stack running under `core` and `load`.

- **Seven scrape limits, all accepted in `global:`.** `sample_limit`, `label_limit`,
  `label_name_length_limit`, `label_value_length_limit`, `target_limit`, `body_size_limit` and
  `keep_dropped_targets`, validated by `promtool check config` against `prom/prometheus:v3.13.2`.
  The draft of this feature listed six and missed `body_size_limit`.
- **Every limit fails the whole scrape for the target that trips it**, rather than discarding the
  offending sample. `target_limit` is the exception: it marks targets failed without scraping them.
- **The limits are evaluated after `metric_relabel_configs`.** A drop rule therefore reduces the
  count the ceiling then judges, which is why the two layers add up instead of competing.
- **`sample_limit` cannot be set per target.** It is a static `scrape_config` field with no
  meta-label behind it, so a per-service ceiling means a second scrape job — service names back in
  `prometheus.yml`, which is what discovery removed.
- **There is no wildcard over label values.** `source_labels` names labels explicitly, and
  `labeldrop`/`labelkeep` match label *names*. A rule selecting on the shape of a value has to
  enumerate the path-carrying labels: `handler` and `route`. The Go service carries neither — it has
  no path label at all — so two rules cover this stack and a fourth convention would want a third.
- **Prometheus does not scrape itself.** Its compose block declares no `prometheus.io/*` labels, so
  the `keep` rule discards it: `prometheus_target_scrapes_exceeded_sample_limit_total` and
  `prometheus_tsdb_head_series` return empty from `/api/v1/query`. The guard's own counters exist on
  `:9090/metrics` and are **not** in the TSDB, so no panel can read them without adding a fourth job
  to every by-job panel and to the `$job` dropdown.
- **The per-target synthetic metrics are in the TSDB and need no self-scrape.**
  `scrape_samples_scraped` and `scrape_series_added` both carry `job` and `instance`, so both work
  under the existing `{job=~"$job"}` filter. `scrape_series_added` is the ramp indicator: it reads
  `0` for all three services at rest.
- **`scrape_samples_scraped` is 146 (app), 63 (Go), 156 (Node).** This is the unit `sample_limit`
  counts. The 136/68/128 recorded by the previous ticket are *stored series*, a different measure —
  sizing the ceiling against them would size it against the wrong number.
- **Active series are now 151, 68 and 161**, above that 136/68/128. The difference is the 404
  traffic the previous ticket's own verification generated, which added label combinations that
  never expire. A well-behaved service's count drifts upward on its own, so the ceiling needs real
  headroom rather than a snapshot plus ten percent.
- **All three services are immune, confirmed by their label values.** The app reports
  `handler="/load/stress/{seconds}"` and puts every unmatched path under `handler="none"`; the Node
  service reports `route="unmatched"`; the Go service exports no path label. Nothing in the stack
  can currently produce the failure this ticket guards against.
- **Two tests treat "scraped" as "driven by the load generator".**
  `test_urls_drive_every_scraped_service` (`tests/test_load_driver.py:31`) asserts set equality
  between the hosts in `URLS` and the scraped services;
  `test_loadgen_waits_for_every_service_it_drives` (`tests/test_compose_config.py:334`) derives the
  same set from `scraped_services` (`:160`). A scraped service the generator does not drive fails
  both.
- **`serving_services` (`tests/test_compose_config.py:305`) derives from `ports:`**, so a service
  publishing none owes no healthcheck. `test_every_service_declares_a_profile` (`:299`) still
  applies, and `chaos` satisfies it.
- **`test_no_query_names_a_scrape_job` (`tests/test_grafana_provisioning.py:241`)** reads the
  `prometheus.io/job` values from the compose file, so the noisy job joins that prohibition with no
  edit: the new panels may not name it.
- **The dashboard is fourteen panels, ids 1–14, ending at `y=35`**, with variables `job` and
  `handler` and every target pinned to datasource uid `prometheus`. A new row starts at `y=35` with
  ids continuing from 14.
- **The root `Dockerfile` is `COPY . .`**, so a new top-level directory ships in the app image
  already. `build: .` with a different `command:` needs no Dockerfile, CI job, lock file or
  dependency, and adds nothing to `assert_pinned` or the install parser.
- **`prometheus.yml` has no `metric_relabel_configs` and no limits today.** Both blocks are new.

**Hypotheses, to measure with the noisy service running:**

- That grouping collides: collapsing two label values into one inside a single scrape produces two
  samples with identical label sets and fails the scrape.
  `prometheus_target_scrapes_sample_duplicate_timestamp_total` exists on `:9090/metrics` and reads
  `0` now, so it is the instrument. If it holds, "drop **or** group" in the roadmap becomes "drop".
- That a tripped `sample_limit` fails only the target that tripped it, leaving the others at `up=1`.
  This is what makes one shared job acceptable for services of different sizes.
- That the limited target reports `up=0` and stays in the target list — unlike a stopped service,
  which discovery removes. If it holds, *Targets up* draws a zero and the guard is visible without
  the counter the dashboard cannot reach.
- That the drop rules cost the three well-behaved services nothing: same `scrape_samples_scraped`,
  same series.

**Measured in task 3, 2026-08-30, with the noisy service running and no guard in place:**

- **The ramp is real and linear.** `scrape_samples_scraped{job="noisy"}` read 50, 150, 250, 350,
  450 across five samples ten seconds apart, and `scrape_series_added{job="noisy"}` held at **50 on
  every scrape** — every scrape brings fifty series that never existed before. `up` stayed `1`
  throughout: nothing about this is an error state, which is the point.
- **At the stack's 5s interval that is +10 series a second: 600 a minute, ~36,000 an hour.** The
  whole rest of the stack is `prometheus_tsdb_head_series` 1088. One container, four labels, no
  privileges, and inside an hour it outweighs everything else by a factor of thirty.
- **The three well-behaved services were untouched** at the same instant: `scrape_samples_scraped`
  146 / 63 / 156, `scrape_series_added` 0 / 0 / 0, `up=1` on all three. The problem is entirely one
  target's, which is what makes a per-target ceiling the right shape of answer.
- **Discovery treats it like anybody else.** Stopped, it left the target list after 14s; started, it
  was back in **15.0s** — both inside the `refresh_interval`. There is no gate to fail here, which
  is the argument the ceiling replaces.
- **The ramp restarts with the container.** The count lives in the process, so a restart returns it
  to 50 and the demonstration is repeatable rather than needing a volume reset.
- **Measured against the real `prometheus_data`.** The edge case below was decided rather than
  avoided: a few thousand series for a few minutes is negligible against a 512 MB / 7d retention,
  and `down --volumes` would have destroyed the Grafana volume to save nothing.

**Measured in task 4, 2026-08-30, with the drop rules in place:**

- **The rules work and cost the well-behaved services nothing.** No raw-path series is stored,
  `scrape_samples_post_metric_relabeling{job="noisy"}` reads **0**, `scrape_series_added` is 0 on
  all four targets, and `up=1` on all four. The other three read 63 / 146 / 156 post-relabel, the
  same as their pre-relabel counts: the rules matched none of their labels.
- **`scrape_samples_scraped` keeps climbing anyway** — 350 while post-relabel was 0. It counts
  samples **before** metric relabeling, so it measures what the target emits and not what is stored.
  A panel showing only that number makes a working guard look broken; the pair is the fact, and the
  gap between them is the guard's work.
- **Negative proof:** with the `handler` rule removed, 800 raw-path series were stored and
  post-relabel read 800; with it restored, post-relabel returned to 0.
- **A drop rule stops new writes and deletes nothing already written.** The 800 series from the
  30s window without the rule stayed queryable afterwards and age out by staleness and retention.
  Read as "the rule did not work" this is the likeliest false alarm in the whole feature.

## Affected files

| File | Change |
| --- | --- |
| `noisy/` | New: one stdlib module serving a hand-assembled `/metrics` on 8005, and its test |
| `docker-compose.yml` | The service under `profiles: ["chaos"]`, scrape labels, no ports, no healthcheck |
| `prometheus.yml` | The limits in `global:`, the drop rules in `metric_relabel_configs` |
| `grafana/dashboards/services.json` | A *Cardinality* row from the per-target synthetic metrics |
| `tests/test_prometheus_config.py` | The limits and the drop rules asserted, with a vacuity guard |
| `tests/test_compose_config.py` | `driven` derived from the `load` profile, not from the scrape label |
| `tests/test_load_driver.py` | The same, in the sibling test |
| `tests/test_grafana_provisioning.py` | The new panels under the rules that already exist |
| `CLAUDE.md` | The two layers, the `chaos` profile, what the guard does not cover |
| `README.md` | How to provoke the failure and how to watch the guard fire |

## Tasks

One commit per task, with the checkbox ticked in the same commit. Any sentence in `CLAUDE.md` or
`README.md` that a task makes false is corrected in that task's commit.

- [x] Debt: `driven` derived from the `load` profile in both sibling tests. First, because the noisy
      service fails both before any guard exists. —
      `test: derive the driven services from the load profile`
- [x] The noisy service on its own: the module and its test. Not in the compose file yet. —
      `feat(noisy): add a service that emits raw paths on purpose`
- [x] The service in `docker-compose.yml` under `chaos`. **No guard yet:** bring it up, record
      `scrape_series_added` and `scrape_samples_scraped` climbing, and keep the numbers. This is the
      baseline of the problem. —
      `feat(compose): let the noisy service join the scrape behind its own profile`
- [x] The drop rules in `metric_relabel_configs`, and their structural assertions. —
      `feat(prometheus): drop series labelled with a raw path`
- [ ] The limits in `global:`, sized against the measured samples per scrape with the headroom
      justified beside the value. — `feat(prometheus): cap what a single target can write`
- [ ] Measure the grouping option: apply it, read the duplicate-sample counter before and after,
      record the outcome here either way. No code shipped if it collides. — verification
- [ ] The *Cardinality* row in the dashboard, and its assertions. —
      `feat(grafana): show how much each target writes`
- [ ] `CLAUDE.md`: both layers, the `chaos` profile, what the guard does not cover. Conclusions only
      — the derivation stays in this file. — `docs: document the cardinality guard`
- [ ] `README.md`: provoking the failure and watching the guard fire. —
      `docs: explain how to demonstrate the guard`
- [ ] Run the verification steps and record each outcome here. No commit beyond the tick. —
      `docs(specs): record the verification outcomes`

## Edge cases

- **Samples scraped and stored series are different numbers**, 146/63/156 against 151/68/161.
  `sample_limit` counts the first. Sizing it against the second — or against the previous ticket's
  136/68/128 — sizes it against a measure it does not use.
- **A well-behaved service's count drifts upward.** The previous ticket's verification traffic
  permanently added label combinations. A ceiling set close to today's reading fails weeks later for
  no reason anybody will connect to this change.
- **A ceiling set too tight is nearly mute.** The target goes to `up=0` and the reason lives in the
  log and in a counter the dashboard cannot read. It is the sibling of the `DOCKER_GID` trap already
  in the roadmap: healthy container, empty panels, cause visible only in a log.
- **`sample_limit` does not filter, it drops the scrape.** Whoever expects it to discard the
  offending series and keep the rest will read the `up=0` as a bug. That is why the drop rules come
  first and the ceiling second.
- **The evaluation order belongs to Prometheus, not to the file.** `metric_relabel_configs` always
  runs before the limit check. Assuming the reverse makes the sizing wrong in the safe direction
  once and the unsafe direction later.
- **A rule that names `job` reopens what discovery closed.** It works and it is easier to write, and
  it puts the list of services back in `prometheus.yml`.
- **Prometheus does not scrape itself, so the limit counters are invisible to Grafana.** Reading
  them means `curl localhost:9090/metrics` by hand, or adding scrape labels to the Prometheus
  compose block — which puts a fourth job in every by-job panel and in the `$job` dropdown. Out of
  scope here; recorded as the option a later feature can take.
- **The noisy service must stay out of `core` and `load`.** Inside either, its cardinality reaches
  `prometheus_data` in normal operation and spends the 512 MB retention on demonstration garbage.
- **The measurement contaminates `prometheus_data`.** After recording the ramp, the baseline is
  dirty, and `down --volumes` destroys the Grafana volume alongside it. Decide before measuring
  whether the demonstration runs against a disposable volume.
- **The new panels may not name the noisy job**, and every bucket or by-job grouping keeps `job`
  inside it. New ids continue from 14 and the row starts at `y=35`.
- **The guard reaches path-shaped labels only.** A service putting an ID in a label of its own
  naming passes the drop rules entirely and is caught by the ceiling alone. Accepted in the spec,
  and the reason the second layer exists.
- **Markdownlint** on the `CLAUDE.md` and `README.md` edits: compact tables (MD060), blank lines
  around fences and lists.

## Verification steps

1. `tox` passes end to end — py311 with the new tests, lint, safety.
2. `docker compose --profile '*' config -q` exits clean and `config --services` resolves **seven**;
   `--profile core --profile load` resolves the same six as before this ticket.
3. `promtool check config` accepts the limits and the drop rules.
4. **The problem, without the guard:** with `--profile chaos` up and the rules absent,
   `scrape_series_added{job="noisy"}` stays above zero across scrapes and
   `scrape_samples_scraped{job="noisy"}` is recorded at two or more instants, rising. Both numbers
   and both queries recorded here.
5. **The guard firing:** with the rules and the ceiling in place, the noisy target is bounded — the
   raw-path series absent from `/api/v1/query`, or the target at `up=0` with
   `prometheus_target_scrapes_exceeded_sample_limit_total` above zero on `:9090/metrics`.
6. **The well-behaved services untouched:** `up=1` on all three, and `scrape_samples_scraped` back
   at 146/63/156 give or take the drift the ticket records.
7. **Negative proof of the drop rules:** remove one rule, watch the raw-path series return; restore
   it, watch them go. Against the running stack, not by reading the file.
8. **The grouping measurement:** the grouping rule applied against the noisy service, with
   `prometheus_target_scrapes_sample_duplicate_timestamp_total` read before and after, and the
   outcome written into the facts above.
9. **The dashboard in a browser:** the *Cardinality* row draws, shows the noisy target bounded and
   the three others flat, names no job in any query, and overlaps no existing panel.
10. A CI run on the branch green on every job.
11. `git diff --stat main...HEAD` names only the files in "Affected files" plus this ticket's two
    documents.
