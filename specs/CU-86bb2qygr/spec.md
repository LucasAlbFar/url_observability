# CU-86bb2qygr — Markdownlint coverage

Status: Approved

Plan: [./plan.md](./plan.md)

## Summary

Make the `markdownlint` VS Code extension a usable signal for this repository, and clear the
violations it reports. A `.markdownlint.jsonc` file is committed at the repo root declaring the
rule set — the stock rules with `MD013` (line-length) disabled — so every editor that opens the
project enforces the same thing. The violations currently present in `CLAUDE.md` and `README.md`
are corrected, and a short note in the documentation records where the rules live.

## Objective

`CLAUDE.md` and `README.md` were written for rendered output rather than for a linter. Opening them
unrendered with the `markdownlint` extension surfaces warnings (MD060, MD032 and others). They do
not stop any tool from rendering the files, but adopting a standard Markdown format keeps the
documentation maintainable as the project grows.

The linter is already installed and already runs continuously as you type — what is missing is
configuration. With no config file, the extension applies the default `MD013` limit of 80 columns
to prose written one paragraph per line, producing roughly 198 warnings and burying the handful of
genuine ones. The result is a wall of red that gets ignored, which is the actual problem: not the
absence of a checker, but a checker whose output carries no signal.

## Scope

### In

- A `.markdownlint.jsonc` file at the repo root declaring `"default": true` and `"MD013": false`,
  with a comment recording why the line-length rule is off.
- Correction of every violation reported once that config is in place, across `CLAUDE.md` and
  `README.md`: MD060 table column style, MD031 blank lines around fences, MD034 bare URLs, MD040
  missing fence language, MD032 blank lines around lists.
- A short subsection in `CLAUDE.md` recording that the `markdownlint` VS Code extension is the
  verification mechanism and that `.markdownlint.jsonc` is the source of truth for the rules, plus
  one line in `README.md`'s development tooling list.

### Out

- Any Python package added to `requirements/dev.in` or `requirements/dev.txt` for this purpose.
  `pymarkdownlnt`, the pure-Python option, implements only rules MD001–MD048; the `markdownlint`
  the extension runs goes up to MD060, and MD060 (`table-column-style`) is precisely the rule that
  prompted this work. A `dev.txt` package could never report it.
- A `markdown` environment in `tox.ini` running the `davidanson/markdownlint-cli2` Docker image.
  Evaluated and rejected as disproportionate: six Markdown files and fifteen mechanical violations
  do not justify a recurring external dependency that would fail the entire `tox` run whenever the
  Docker daemon is stopped.
- Changes to `.github/workflows/python-app.yml`.
- A `PostToolUse` hook in `.claude/settings.json`.
- Enforcing MD013 or rewrapping existing prose. Files stay one paragraph per line, which keeps
  diffs readable.
- Installing Node.js, `npm` or `npx`.
- Changes to the `/new-spec` templates or to the documents under `specs/`, which are already clean
  under this configuration.

## Expected behaviour

Opening any Markdown file in the project shows no markdownlint warning in the VS Code Problems
panel. Violations appear live, as they are introduced, and only for rules the project actually
cares about — long prose lines no longer register. The rule set travels with the repository, so
anyone opening the project with the extension installed gets the same result without configuring
anything locally.

Conformance rests on the editor rather than on a gate: nothing blocks a commit containing a
Markdown violation. This is a deliberate trade for a project of this size. Should formatting drift
become a real problem later, an automated gate reads the same `.markdownlint.jsonc` — the file is
also the config `markdownlint-cli2` looks for — so it can be added without redoing this work.

## Acceptance criteria

- [ ] `.markdownlint.jsonc` exists at the repo root, enables the default rule set and disables only
      `MD013`.
- [ ] The VS Code Problems panel reports no markdownlint violation for `CLAUDE.md`, `README.md` or
      any file under `specs/`.
- [ ] The three tables in `README.md` use a consistent column style, its bare `localhost` URLs are
      no longer bare, its "Project layout" fence declares a language, and its `Notes:` list is
      surrounded by blank lines.
- [ ] Every fenced code block in `CLAUDE.md` is preceded and followed by a blank line.
- [ ] No prose was rewrapped: `CLAUDE.md` and `README.md` remain one paragraph per line.
- [ ] `CLAUDE.md` and `README.md` state where the rules live and what enforces them.
- [ ] `requirements/dev.in`, `requirements/dev.txt`, `tox.ini` and
      `.github/workflows/python-app.yml` are unchanged.
