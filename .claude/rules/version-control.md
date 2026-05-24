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
- **Scope:** affected area (optional) — e.g. `engine`, `web`, `ocr`, `web/ui`, `db`, `deploy`.
- **Description:** short, present-tense ("Add" not "Added"); first line < 50 chars.
- **Common Gitmoji:** ✨ feat · 🐛 fix · 📝 docs · 🎨 style · ♻️ refactor · 🧪 test · 🔧 chore.

## Secrets

- **Never commit** `.env*`, `secrets/`, or `google-credentials.json`. Commit
  `.env.example` instead. A pre-commit guard blocks `git add` of `.env` files
  (see `.claude/settings.json`).
