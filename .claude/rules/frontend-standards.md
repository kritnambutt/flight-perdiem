# Frontend Standards

Standards for the frontend, built with **React + Vite + pnpm + Tailwind CSS**
(TypeScript). Read this before working on any file under `frontend/`.

## Project Structure

```
frontend/
├── src/
│   ├── pages/        # one screen per route (RunPage, ResultsPage, ExceptionsPage, ConfigPage, AuditPage, LoginPage)
│   ├── components/   # reusable UI (RosterPreview, ProgressBar, VerdictBadge, DecisionControls, …)
│   ├── hooks/        # useRun, usePolling, useAuth
│   ├── contexts/     # AuthContext
│   ├── lib/          # API client + helpers
│   ├── config/  types/  styles/
│   ├── App.tsx       # router + layout
│   └── main.tsx
└── index.html  vite.config.ts  tailwind.config.ts  postcss.config.js
```

- Page-level screens go in `src/pages/`; shared widgets in `src/components/`.
- The API client lives in `src/lib/`; all network calls go through it.

## Code Style

- TypeScript strict mode; small, focused functions; meaningful names.
- File naming: components PascalCase; hooks `useX.ts`; utilities camelCase; constants UPPER_CASE.
- **Use arrow functions + named exports.** Avoid `export default function`.
  ```tsx
  export const RunPage = () => {
    return /* JSX */;
  };
  ```

## Data fetching & state

- The app talks to the FastAPI backend on the **same origin** (`/api/...`) — no
  CORS layer. In dev, Vite proxies `/api` to `http://localhost:8000`.
- Use a query/fetch hook layer (e.g. React Query) for server state; handle
  loading/error states explicitly.
- Long runs are **polled** via `GET /api/runs/{id}` (see `usePolling`); show live
  progress + counts. Never block the UI on a run.
- Global state (auth) via Context; keep other state local.

## Styling (Tailwind)

- Tailwind CSS, **mobile-first**; utility-first classes; theme in
  `tailwind.config.ts`. Tailwind directives live in `src/styles/index.css`,
  imported once in `main.tsx`.
- Consistent, responsive design; avoid ad-hoc inline styles.

## PII & auth

- Every protected page is behind the auth guard; redirect to `/login` if no session.
- **Roster image previews are PII** — fetched from the auth-gated backend endpoint,
  never embedded with a public URL.

## Accessibility

- Semantic HTML, keyboard navigation, focus management, adequate contrast, alt text.

## Code Quality

- Follow ESLint config; format with Prettier (`pnpm format`); fix all TS errors
  before committing; remove unused imports/vars.
