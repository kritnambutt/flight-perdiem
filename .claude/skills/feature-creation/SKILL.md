---
name: feature-creation
description: Create a new feature/user-story doc for the flight-perdiem project. Use when the user wants to write a user story, spec out a feature, or capture a new requirement into docs/features.
---

# Feature / Story Creation

Create a single, well-structured story file under `docs/features/`.

## Before writing — clarify

- Ask questions to resolve requirements, assumptions, scope, and the technical approach before drafting.
- Do not invent acceptance criteria or business rules; confirm ambiguous points with the user.
- Check the decision gates in `docs/features/implementation-order.md` (R4 direction, Prisma vs Alembic, rate, auth) — surface any that affect this story.
- Document clarifications in the story.

## File naming & location

- Path: `docs/features/<Epic>/story-<NNN>-<short-slug>.md` (e.g. `docs/features/Validation/story-004-layover-rules.md`).
- Numbers (`NNN`) reset **per epic** (per folder).
- Keep a stable `Story ID` of the form `PD-<AREA>-<NNN>` inside (e.g. `PD-VAL-004`) even though the filename is the human-readable slug.
- Existing epics/areas: `Ingestion` (ING), `RosterOCR` (OCR), `Validation` (VAL), `Reporting` (REP), `WebApp` (WEB), `Platform` (PLAT). Reuse an area code; only create a new epic folder for genuinely new scope.
- One story per file.

## Structure

Use `template.md` (in this skill folder) as the starting point. Required sections:

1. **Property table** — Story ID, Title, Epic, Dependencies, Story Type, Source.
2. **Epic Overview** — short description + a table of stories in the epic and their status.
3. **Feature Overview** — Gherkin user story, pre-conditions, scope (included/excluded).
4. **🎯 Acceptance Criteria** — functional requirements, validation rules, error scenarios (+ UI when frontend).
5. **🧩 Technical Documentation** — data/engine models (Python dataclasses), SQLAlchemy schema where relevant, API contracts (FastAPI/Pydantic + TypeScript), config/env, security.
6. **🔨 Implementation Plan** — numbered tasks with status indicators and subtasks (1.1, 1.2…).
7. **🏗 Structure** — affected `backend/` and/or `frontend/` file tree.
8. **📌 Notes / Open Questions** — decisions, future work, blockers.

## Status indicators

- 📝 **TODO** · 🚧 **IN PROGRESS** · ✅ **DONE** · 🚫 **N/A** / ❌ **REMOVED**

Parent task status reflects its subtasks. Break complex tasks into numbered subtasks small enough to implement in one sitting.

## Consistency

- Tie the story back to `docs/REQUIREMENTS.md` (cite the relevant section / rule IDs in `Source`).
- Follow `.claude/rules/project-standards.md`, `backend-standards.md`, and `frontend-standards.md`.
- Keep the engine pure (no web/db coupling) when specifying engine work.
