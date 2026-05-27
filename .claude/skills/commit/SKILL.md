---
name: commit
description: Stage changes and create a git commit following the project's version-control conventions (gitmoji + type(scope) format). Use when the user wants to commit pending work.
---

# Commit

Create a clean, conventional commit for the flight-perdiem repo. Follow
`.claude/rules/version-control.md` for message format.

## Steps

1. **Inspect** (run in parallel):
   - `git status` — see untracked + modified files. **Never** use `-uall`.
   - `git diff` and `git diff --staged` — see what will be committed.
   - `git log --oneline -10` — match the repo's existing message style.

2. **Stage deliberately.** Add files **by name** — never `git add -A` / `git add .`.
   - Group related changes into one logical commit. If the working tree mixes
     unrelated changes, stage only the subset the user asked for (or propose
     splitting into multiple commits).
   - **Never stage secrets:** `.env*`, `secrets/`, `google-credentials.json`.
     A pre-commit hook blocks these — if it fires, stop and tell the user.
   - Don't stage generated/PII artefacts: `data/ml/`, `frontend/dist/`,
     `backend/.venv/`, uploads/reports dirs.

3. **Draft the message** per `version-control.md`:
   ```
   type(scope): <gitmoji> short present-tense summary   ← first line < 50 chars

   - change item 1
   - change item 2
   ```
   - **Types:** feat · fix · docs · style · refactor · test · chore.
   - **Scope** (optional): `engine`, `web`, `ocr`, `web/ui`, `db`, `deploy`, `ml`.
   - **Gitmoji:** ✨ feat · 🐛 fix · 📝 docs · 🎨 style · ♻️ refactor · 🧪 test · 🔧 chore.
   - Focus the body on the **why**, not a restatement of the diff.

4. **Commit** with a HEREDOC so formatting survives:
   ```bash
   git commit -m "$(cat <<'EOF'
   feat(engine): ✨ add out-and-back pairing for R3

   - pair DMK→HKT day N with HKT→DMK day N+1
   - handle month-boundary pairings
   EOF
   )"
   ```
   Then run `git status` to confirm.

5. **On pre-commit hook failure:** fix the underlying issue, re-stage, and create a
   **NEW** commit. Never `--amend` (the failed commit didn't happen) and never
   `--no-verify`.

## Guardrails

- Only commit what the user asked for. Don't sweep in unrelated edits.
- Never amend, force, or skip hooks unless the user explicitly says so.
- Don't push — that's `/pr`'s job. Stop after the commit.
