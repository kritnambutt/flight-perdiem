# Version Control Rules

## Dependencies & Versioning

1. Pin dependencies: exact versions in `requirements.txt` / `pyproject.toml`
   (Python) and `package.json` (frontend).
2. Follow semantic versioning; document breaking changes.

## Change Awareness

When suggesting changes, indicate:
- Which files need updating and what sections are affected.
- Related docs to review (REQUIREMENTS, architecture, the relevant feature story).
- Complete file paths; highlight breaking changes and migrations.

## Branch Strategy

- Feature branches: `feature/description`
- Bug fixes: `fix/description`
- Hotfixes: `hotfix/description`
- Protected `main` branch.

## Commit Message Guidelines

```
type(scope): ✨ description

- Change item 1
- Change item 2
```

- **Types:** feat, fix, docs, style, refactor, test, chore.
- **Scope:** affected area (optional) — e.g. `engine`, `web`, `ocr`, `web/ui`, `db`, `deploy`, `ml`.
- **Description:** short, present-tense ("Add" not "Added"); first line < 50 chars.
- **Common Gitmoji:** ✨ feat · 🐛 fix · 📝 docs · 🎨 style · ♻️ refactor · 🧪 test · 🔧 chore.
- Body explains the **why**, not a restatement of the diff.

## Staging discipline

- Stage files **by name** — never `git add -A` / `git add .` (avoids sweeping in
  secrets, generated artefacts, or unrelated edits).
- **One concern per commit.** If the working tree mixes unrelated changes, split
  them into separate commits.
- Never stage generated / PII output: `data/ml/`, `frontend/dist/`,
  `backend/.venv/`, uploads/reports dirs.
- On a pre-commit hook failure: fix the cause, re-stage, and create a **NEW**
  commit. Never `--amend` a failed commit; never `--no-verify` or skip signing.

## Pull Requests

- Open against `main`; never push commits directly to the protected `main`.
- Title < 70 chars, same `type(scope): <gitmoji> …` style as commits.
- Write the body from the **whole branch diff** (`git diff main...HEAD`), not just
  the last commit. Include a Summary, Related docs, and a Test plan checklist
  (`make test` / `make test-all` / manual UI check as applicable).
- Use `gh` for all GitHub operations. Don't merge or force-push without an
  explicit request.

## Tooling

- `/commit` skill — stage + write a conventional message + commit.
- `/pr` skill — push the branch and open a PR.
- `commit-author` agent — runs the whole staging+commit flow autonomously.
- `code-reviewer` agent — review pending changes against the standards before commit.

## Secrets

- **Never commit** `.env*`, `secrets/`, or `google-credentials.json`. Commit
  `.env.example` instead. A pre-commit guard blocks `git add` of `.env` files
  (see `.claude/settings.json`).
