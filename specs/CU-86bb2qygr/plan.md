# CU-86bb2qygr — Markdownlint coverage (plan)

Spec: [./spec.md](./spec.md)

## Context

The change lands in three places: a new `.markdownlint.jsonc` at the repo root, and edits to
`CLAUDE.md` and `README.md`. Nothing under `app/`, `worker/`, `tests/` or `requirements/` is
touched.

There is no Markdown tooling in the repository today — no `.markdownlint*` config, no
`.editorconfig`, no `package.json`, no `.pre-commit-config.yaml`. The `markdownlint` VS Code
extension is already installed and already lints every open Markdown file, but with stock defaults,
because nothing tells it otherwise. `tox -e lint` covers only `black`, `isort` and `flake8` on
Python sources and is not extended here.

Each task below is its own commit, and the task's checkbox is ticked in that same commit, so this
file stays a traceable record of what was done.

## Facts verified against the repo

- `.gitignore` does not match `.markdownlint.jsonc`, so the new config will be tracked. It does
  ignore `.vscode/` (`.gitignore:52`), and `.vscode/settings.json` holds only `cSpell.words` — the
  config therefore has to live at the repo root to be shared, not in `.vscode/`.
- Node, `npm` and `npx` are not installed on this machine, and no Markdown linter is available on
  the command line. The VS Code extension is the only checker present, which is why it is the
  verification mechanism.
- `pymarkdownlnt`, the pure-Python option, implements rules MD001–MD048. The `markdownlint` the
  extension runs covers MD001–MD060, and MD060 `table-column-style` was added in markdownlint
  v0.40.0. No `requirements/dev.txt` package can report the rule that prompted this work.
- With `MD013` off, exactly 15 violations remain, spread across two files:

| Rule | Location | Fix |
| --- | --- | --- |
| MD060 `table-column-style` | `README.md` L15, L40, L59 | Delimiter rows are tight (`\|---\|---\|`) while header and body rows are compact; pad them to `\| --- \| --- \|` |
| MD031 `blanks-around-fences` | `CLAUDE.md` L29, L38, L43, L47, L49, L53, L58, L71 | Blank line before the opening fence, or after the closing fence |
| MD034 `no-bare-urls` | `README.md` L41–43 | Wrap the `http://localhost:*` cells in backticks |
| MD040 `fenced-code-language` | `README.md` L147 | The "Project layout" fence declares no language |
| MD032 `blanks-around-lists` | `README.md` L139–140 | `Notes:` is immediately followed by a list item |

- The four files under `specs/` are already clean: the CU-86bb2m2t2 tables use compact delimiter
  rows, and in the CU-86bb2qygr scaffolds the HTML comments, empty `-` items and empty `- [ ]`
  checkboxes trigger no rule in the default set.
- MD042, cited when this work was requested, is not violated by any file in the repository's
  current state.
- At the default `MD013` limit of 80 columns the same files produce roughly 198 violations, and
  `CLAUDE.md`'s longest line is 905 characters. Disabling the rule is what makes the remaining
  output readable.

## Affected files

| File | Change |
| --- | --- |
| `.markdownlint.jsonc` | New. Declares `"default": true` and `"MD013": false` |
| `README.md` | MD060 delimiter rows, MD034 URLs, MD040 fence language, MD032 blank line, plus one bullet in `## Stack` |
| `CLAUDE.md` | Eight blank lines around fences, plus a `### Markdown lint` subsection under `## Commands` |

## Tasks

One commit per task, each ticking its own checkbox in the same commit.

- [x] Create `.markdownlint.jsonc` at the repo root with `"default": true`, `"MD013": false`, and a
      comment recording that prose is written one paragraph per line so the line-length rule would
      force rewrapping every documentation file.
      Commit: `chore(markdownlint): add rule config with MD013 disabled`
- [ ] `README.md`: pad the three delimiter rows at L15, L40 and L59 to `| --- | --- | --- |` so each
      table is consistently compact (MD060).
      Commit: `style(docs): pad README table delimiter rows`
- [ ] `README.md`: wrap the three `http://localhost:*` values at L41–43 in backticks, keeping the
      existing backticks around `admin` in the Grafana row (MD034).
      Commit: `style(docs): wrap README localhost urls in backticks`
- [ ] `README.md`: declare `text` as the language of the "Project layout" fence at L147 (MD040).
      Commit: `style(docs): declare language for README layout fence`
- [ ] `README.md`: insert a blank line between `Notes:` and the list that follows it at L139–140
      (MD032).
      Commit: `style(docs): surround README notes list with blank line`
- [ ] `CLAUDE.md`: insert the eight blank lines around fenced blocks — before the opening fences at
      L29, L38, L47, L53 and L58, and after the closing fences at L43, L49 and L71 (MD031). Apply
      them bottom-up so earlier insertions do not shift the later line numbers.
      Commit: `style(docs): surround CLAUDE.md code fences with blank lines`
- [ ] `CLAUDE.md`: add a short `### Markdown lint` subsection under `## Commands`, after
      `### Lint / format`, stating that the `markdownlint` VS Code extension checks Markdown live,
      that `.markdownlint.jsonc` at the repo root is the rule set, and that neither `tox` nor CI
      enforces it.
      Commit: `docs: record markdownlint setup in CLAUDE.md`
- [ ] `README.md`: add one bullet to the `## Stack` list naming markdownlint and pointing at
      `.markdownlint.jsonc`.
      Commit: `docs: list markdownlint in README stack`
- [ ] Reload the VS Code window so the extension picks up the new config, then open all six Markdown
      files and confirm the Problems panel is empty. No commit — this task only verifies.

## Edge cases

- The eight `CLAUDE.md` insertions shift every line number after the first one. Work bottom-up, or
  re-read the file between edits.
- The first commit only adds the config, so the seven commits that follow are each made against a
  tree the linter still reports violations for. That is expected: the run is only clean once the
  last fix lands.
- Nothing enforces conformance. Without a gate, a Markdown violation reaches a commit whenever
  nobody looks at the Problems panel. This is the deliberate trade recorded in the spec, not an
  oversight.
- MD060 only exists in markdownlint v0.40.0 and later. An outdated extension will not report it,
  and will also not report MD059 or the other table rules.
- A collaborator who opens the repository without the extension installed gets no checking at all.
  The config is inert on its own.
- `.markdownlint.jsonc` uses JSONC comments. The extension and `markdownlint-cli2` both accept
  them; a strict JSON parser would not.
- Editors configured to format Markdown on save can rewrap prose. With `MD013` disabled the long
  lines are intentional, and rewrapping them would produce a large unrelated diff.

## Verification steps

- After each commit, `git show --stat HEAD` names only the file that task targets plus this
  `plan.md`, confirming the commits stayed separate.
- With the VS Code window reloaded, open `CLAUDE.md`, `README.md` and the four files under `specs/`
  in turn; the Problems panel reports no `markdownlint` entry for any of them.
- `git diff main...HEAD` on `CLAUDE.md` and `README.md` shows only inserted blank lines, respaced
  delimiter rows, added backticks, the `text` language tag and the two documentation additions. No
  paragraph of prose is rewrapped.
- `git diff --stat main...HEAD` confirms `requirements/`, `tox.ini` and
  `.github/workflows/python-app.yml` are untouched.
- Preview `README.md` and confirm the three tables and the "Project layout" block still render as
  before — the MD060 and MD040 fixes must not change the rendered output.
