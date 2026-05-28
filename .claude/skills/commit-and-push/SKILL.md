---
name: commit-and-push
description: "Commit (and optionally push) staged or working changes in the flight-perdiem repo. Picks a valid Conventional Commits type + gitmoji, writes a well-formed message with the Claude co-author trailer, respects the secrets pre-commit hook, runs make lint/test, and pushes only when asked. Use when the user asks to commit and/or push changes."
---

You commit and push changes in the flight-perdiem repo. Authority on the rules:
`.claude/rules/git-commit.instructions.md` and `.claude/rules/version-control.md`
(read them — they are the source of truth for types, format, and procedure).

## Step 1 — Inspect the change

- `git status` (never `-uall`) and `git diff --cached` (and `git diff` for
  unstaged) to see what is actually changing. Stage what the user intends, **by
  name**, if nothing is staged.
- Summarize the change in one sentence — you'll use it to choose the type.
- If the tree mixes unrelated changes, propose splitting into multiple commits.

## Step 2 — Choose the type

Title must match
`^(feat|fix|docs|style|refactor|test|chore)(\(scope\))?: <gitmoji> <subject≥3>`.

| Intent | Type | Gitmoji |
|--------|------|---------|
| New user-facing capability | `feat` | ✨ |
| Bug fix | `fix` | 🐛 |
| Behavior-preserving restructure | `refactor` | ♻️ |
| Tests only | `test` | 🧪 |
| Docs only | `docs` | 📝 |
| Formatting / no logic change | `style` | 🎨 |
| Tooling/deps/config/`.claude/` | `chore` | 🔧 |

Scopes: `engine`, `web`, `worker`, `ocr`, `web/ui`, `db`, `ml`, `deploy`, `docs`.
Pick by **intent**, not convenience.

## Step 3 — Quality gate (no CI gate exists — run it yourself)

- `make lint` (ruff) · `make format` to auto-fix.
- `make test` (engine + ML unit). Add `make test-all` if the change touches
  `db/` or web/worker DB paths.
- Fix failures before committing — never bypass with `--no-verify`.

## Step 4 — Write the message

```bash
git commit -m "$(cat <<'EOF'
<type>(<scope>): <gitmoji> <subject>

<body: what & why, bullets ok>

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

- The secrets pre-commit hook blocks `git add` of `.env*` / `secrets/` /
  `google-credentials.json`. If it fires, stop and tell the user.
- On a pre-commit failure: fix, re-stage, make a **NEW** commit (never `--amend`).
- Then run `git status` to confirm.

## Step 5 — Push (only when asked)

- `main` is protected — never push commits straight to it. Use a `feature/…` /
  `fix/…` branch and open a PR via `gh pr create` (title < 70 chars, body with
  Summary / Related docs / Test plan).
- If push fails for auth reasons, report it and ask the user to push — don't
  retry blindly.

## Constraints

- Commit/push only when the user asked.
- One logical change per commit; don't sweep in unrelated edits.
- No secrets or PII (roster images, real names) in the message or the diff.
