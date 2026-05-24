| Property     | Value                                            |
| ------------ | ------------------------------------------------ |
| Story ID     | PD-[AREA]-[NNN]                                  |
| Title        | [Descriptive Title]                              |
| Epic         | EP-[EPIC] — [Epic Name]                          |
| Dependencies | [List Dependencies]                              |
| Story Type   | Feature / Enhancement / Bug / Infrastructure     |
| Source       | REQUIREMENTS.md → "[section]" / rules [Rx]        |

## 🗂 Epic Overview — EP-[EPIC] ([Epic Name])

[1–2 sentence description of the epic.] See [overview.md](./overview.md).

| Story ID      | Title | Reqs | Status     |
| ------------- | ----- | ---- | ---------- |
| PD-[AREA]-001 | …     | …    | 📝 Planned |

## 📝 Feature Overview — PD-[AREA]-[NNN]

### User Story

```gherkin
As a [user type],
I want to [action/goal],
So that [benefit/value].
```

### Pre-conditions

- Technical prerequisites / required configurations / dependencies

### Scope

#### Included
- …

#### Excluded
- …

## 🎯 Acceptance Criteria

### Functional Requirements
- Core functionality, rules applied, state transitions (cite Rx / Fx)

### Validation Rules
- Input validation, business rules, thresholds

### Error Scenarios
- Error handling, review flags (NEEDS_REVIEW), recovery paths

### User Interface (frontend stories only)
- Tailwind/responsive behavior, accessibility, loading/error states

## 🧩 Technical Documentation

### Engine / Data Model
```python
# @dataclass models, or SQLAlchemy model sketch
```

### API Contracts (web stories)
```
# METHOD /api/...  -> response
```
```typescript
interface ResponseModel { /* ... */ }
```

### Required Configuration
- Environment variables, config keys (routes/flight numbers/rate/thresholds), services

### Security Requirements
- Auth, PII handling, secrets

## 🔨 Implementation Plan

1. 📝 **TODO** Main Task
   - 📝 **TODO** 1.1 Subtask
   - 📝 **TODO** 1.2 Subtask

## 🏗 Structure

```
# affected backend/ and/or frontend/ paths
```

## 📌 Notes / Open Questions

- Decisions, future improvements, known limitations, blockers
