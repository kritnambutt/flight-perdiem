# Git Commit & Push — Instructions

These rules govern **every** commit and push in the flight-perdiem repo. They
extend `.claude/rules/version-control.md` (branch strategy, dependency pinning,
secrets) with the concrete commit/push procedure. Read both.

## Conventional Commits + Gitmoji

The commit **title** (first line) must match:

```
^(feat|fix|docs|style|refactor|test|chore)(\(scope\))?: <gitmoji> <subject>
```

- First line **< 50 chars**; subject is present-tense ("Add" not "Added").
- Scope is optional, lower-case, in parentheses — e.g. `feat(engine): …`.
- **Allowed types:** `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`.
- **Scopes** (this repo): `engine`, `web`, `worker`, `ocr`, `web/ui`, `db`,
  `ml`, `deploy`, `docs`. Engine vs web/worker/db matters — the engine is the
  pure library; keep its commits scoped `engine`.

### Type → gitmoji

| Type | Gitmoji | Use for |
|------|---------|---------|
| `feat` | ✨ | New user-facing capability |
| `fix` | 🐛 | Bug fix |
| `refactor` | ♻️ | Behavior-preserving restructure |
| `test` | 🧪 | Tests only |
| `docs` | 📝 | Docs only (incl. `docs/features`, `docs/analysis`) |
| `style` | 🎨 | Formatting / ruff-format / no logic change |
| `chore` | 🔧 | Tooling, deps, config, `.claude/` changes |

Pick the type by **intent**, not convenience: a runtime fix is `fix`, a
behavior-preserving restructure is `refactor`, pure docs are `docs`.

## Commit Message Format

```
<type>(<scope>): <gitmoji> <subject ≥3 chars>

<body — what & why, wrapped, bullet list ok>

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
```

- End every Claude-authored commit with the `Co-Authored-By` trailer above
  (blank line before it).
- Body explains the **why**, not a restatement of the diff.
- Do not include secrets, tokens, or credentials in the message.

## Staging discipline

- Stage files **by name** — never `git add -A` / `git add .`.
- **One logical change per commit.** If the working tree mixes unrelated changes
  (e.g. an engine fix + a frontend tweak + docs), split into separate commits.
- Never stage generated / PII output: `data/ml/`, `frontend/dist/`,
  `backend/.venv/`, uploads/reports dirs.

## Pre-commit hook — secrets guard

A `PreToolUse` hook (see `.claude/settings.json`) **blocks** `git add` of `.env*`,
`secrets/`, and `google-credentials.json`. If it fires, stop — do not work around
it. Commit `.env.example` instead. Never use `--no-verify`.

## Quality before committing

There is no CI commit gate, so run the relevant checks yourself first:

- `make lint` — ruff check (and `make format` to auto-fix).
- `make test` — engine + ML unit tests (no DB, runs anywhere).
- `make test-all` — only when the change touches `db/` or web/worker DB paths
  (needs Docker).

## Commit & Push Procedure

1. Inspect staged scope (`git status` — never `-uall`; `git diff --cached`) and
   write a title whose **type matches the change's intent**.
2. Run the relevant quality checks (above).
3. Commit with a HEREDOC so the body + trailer survive. On a pre-commit failure,
   fix the cause, re-stage, and create a **NEW** commit — never `--amend` a failed
   commit, never `--no-verify`.
4. Push **only when the user asks**. `main` is protected — never push commits
   straight to it; use a `feature/…` / `fix/…` branch and open a PR via `gh`.
5. If push fails for auth reasons, report it and ask the user to push — don't
   retry blindly.

## What NOT to Do

- **Never** use a type outside the allowed seven.
- **Never** commit when `make lint` / `make test` is failing — fix it first.
- **Never** commit secrets or PII (roster images, real names, `.env`, `secrets/`).
- **Never** force-push to rewrite shared `main` history — add a follow-up commit.
- **Never** commit or push unless the user asked.
