# Frontend Standards

Standards for the frontend, built with **React + Vite + pnpm + Tailwind CSS v4**
(TypeScript). Read this before working on any file under `frontend/`.

## Project Structure

```
frontend/
├── src/
│   ├── pages/           # one screen per route (RunPage, ResultsPage, ExceptionsPage, ConfigPage, AuditPage, LoginPage)
│   ├── components/
│   │   ├── ui/          # Catalyst UI Kit components (copy-paste, NOT an npm package)
│   │   └── *.tsx        # project-specific widgets (VerdictBadge, ProgressBar, …)
│   ├── hooks/           # useRun, usePolling, useAuth
│   ├── contexts/        # AuthContext
│   ├── lib/             # API client + helpers
│   ├── config/  types/  styles/
│   ├── App.tsx          # router + StackedLayout
│   └── main.tsx
└── index.html  vite.config.ts
```

- Page-level screens go in `src/pages/`; shared widgets in `src/components/`.
- Catalyst UI primitives live in `src/components/ui/` — edit them in place when needed.
- The API client lives in `src/lib/`; all network calls go through it.

## UI Components — Catalyst UI Kit (`src/components/ui/`)

Copy-pasted from `/docs/../templates/catalyst-ui-kit/typescript/`. **Not an npm package** —
files live directly in the repo and can be modified freely. This is the **only** UI kit;
do not add component libraries (flowbite-react, MUI, etc.) — extend Catalyst or use native
HTML elements styled with Tailwind instead.

Key components available:
- `Button` — solid/outline/plain, many color variants; pass `color="blue"`, `color="green"`, etc.
- `Badge` / `BadgeButton` — status chips with semantic colours.
- `Field`, `Label`, `Description`, `ErrorMessage`, `FieldGroup`, `Fieldset` — accessible form layout.
- `Input` — styled text/date input wrapping Headless UI; supports `type="month"` (used for the
  Cycle month picker — a native month+year picker, no extra dependency needed).
- `Heading`, `Subheading` — page/section titles in zinc scale.
- `Text`, `TextLink`, `Strong` — body copy styles.
- `Divider` — `<hr>` with optional `soft` variant.
- `Navbar`, `NavbarItem`, `NavbarSection`, `NavbarSpacer`, `NavbarDivider` — top nav with animated active indicator.
- `StackedLayout` — full-page shell with header + mobile sidebar drawer.
- `Link` — wraps `react-router-dom`'s `<Link>` for internal routes; falls back to `<a>` for external URLs.

Dependencies Catalyst needs: `@headlessui/react`, `clsx`, `motion`.

Design language: **zinc scale** (zinc-950 text, zinc-100 backgrounds, zinc-950/10 borders).
Use `dark:` variants consistently. Prefer Catalyst components over raw Tailwind for interactive elements.

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
- Use React Query for server state; handle loading/error states explicitly.
- Long runs are **polled** via `GET /api/runs/{id}` (see `usePolling`); show live
  progress + counts. Never block the UI on a run.
- Global state (auth) via Context; keep other state local.

## Styling (Tailwind v4)

- Tailwind CSS v4, **mobile-first**; utility-first classes. No `tailwind.config.ts` —
  configuration is CSS-first via `src/styles/index.css` (imported once in `main.tsx`).
- Use Catalyst's zinc-based design tokens; avoid one-off colours.
- Consistent, responsive design; avoid ad-hoc inline styles.

## Dark / light mode

- **Class-based**, not `prefers-color-scheme`. `src/styles/index.css` declares
  `@custom-variant dark (&:where(.dark, .dark *))`, so `dark:` utilities activate only
  when a `.dark` class is present on `<html>`.
- `ThemeContext` (`src/contexts/ThemeContext.tsx`) owns the theme: it toggles `.dark`
  on `<html>` and persists the choice to `localStorage` under the `theme` key.
- An anti-FOUC script in `index.html` applies the saved/system theme **before paint**.
  First-time visitors fall back to the OS `prefers-color-scheme`; after that the user's
  explicit toggle wins.
- The navbar exposes a sun/moon `ThemeToggle` (in `App.tsx`).
- **Every screen must render clearly in BOTH modes.** When you add bespoke chrome
  (cards, tables, inputs not from Catalyst), always pair light + dark classes, e.g.
  `bg-white dark:bg-zinc-900`, `text-zinc-900 dark:text-white`,
  `ring-zinc-950/5 dark:ring-white/10`. Catalyst components already ship dark variants —
  prefer them over hand-rolled markup.
- `color-scheme` is set per mode in `index.css` so native controls (scrollbars, the
  date-picker popup, file-input button) match the active theme.

## PII & auth

- Every protected page is behind the auth guard; redirect to `/login` if no session.
- **Roster image previews are PII** — fetched from the auth-gated backend endpoint,
  never embedded with a public URL.

## Accessibility

- Semantic HTML, keyboard navigation, focus management, adequate contrast, alt text.
- Catalyst components (built on Headless UI) handle ARIA roles automatically.

## Code Quality

- Follow ESLint config; format with Prettier (`pnpm format`); fix all TS errors
  before committing; remove unused imports/vars.
