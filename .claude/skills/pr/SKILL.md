---
name: pr
description: Push the current branch and open a GitHub pull request with a generated title and body. Use when the user wants to raise a PR for their committed work.
---

# Pull Request

Push the current branch and open a PR against `main`, using the project's
branch + commit conventions (`.claude/rules/version-control.md`).

## Steps

1. **Survey the branch** (run in parallel):
   - `git status` — uncommitted work? If so, suggest committing first (`/commit`).
   - `git branch --show-current` — current branch.
   - `git log main..HEAD --oneline` — ALL commits that will land in the PR.
   - `git diff main...HEAD` — the full branch diff (not just the last commit).
   - `git rev-parse --abbrev-ref @{u} 2>/dev/null` — does it track a remote yet?

2. **Branch naming.** If still on `main` or a non-conventional name, create/rename to:
   - `feature/<description>` · `fix/<description>` · `hotfix/<description>`.
   - `main` is protected — never push commits straight to it; never force-push it.

3. **Draft title + body** from the *whole* branch diff (every commit, not just HEAD):
   - Title < 70 chars, same `type(scope): <gitmoji> …` style as commits.
   - Body uses the template below.

4. **Push + open PR** (run in parallel where possible):
   - Push with `-u` if no upstream yet.
   - `gh pr create` with a HEREDOC body:
   ```bash
   gh pr create --title "feat(engine): ✨ add R3 pairing" --body "$(cat <<'EOF'
   ## Summary
   - <1-3 bullets on what changed and why>

   ## Related docs
   - docs/REQUIREMENTS.md (R3), docs/features/Validation/story-XXX.md

   ## Test plan
   - [ ] `make test` (engine + ML unit)
   - [ ] `make test-all` if DB-touching
   - [ ] manual UI check if frontend
   EOF
   )"
   ```

5. **Return the PR URL** so the user can open it.

## Guardrails

- Don't open a PR with uncommitted changes — commit first.
- Never push secrets, `data/ml/`, `frontend/dist/`, or `backend/.venv/`.
- Don't merge the PR; just open it. Don't force-push without an explicit ask.
- Use `gh` for all GitHub work (checks, comments, status).
