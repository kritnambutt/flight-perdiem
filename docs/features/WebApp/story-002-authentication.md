| Property     | Value                                              |
| ------------ | -------------------------------------------------- |
| Story ID     | PD-WEB-002                                         |
| Title        | Authentication (staff sign-in)                     |
| Epic         | EP-WEB — Web Application                           |
| Dependencies | FastAPI, React, PostgreSQL/session store           |
| Story Type   | Feature                                            |
| Source       | REQUIREMENTS.md → §6.6 (F14); §7 (N5)             |

## 🗂 Epic Overview — EP-WEB

See [overview.md](./overview.md). This story gates the whole app — it handles
PII (roster images, names, staff IDs), so every screen and API requires a signed-in staff user.

## 📝 Feature Overview — PD-WEB-002

### User Story

```gherkin
As an admin
I want to sign in before using the system
So that crew roster images and per diem data are protected

As the system
I want all API routes and roster previews to require a valid session
So that PII is never served to an unauthenticated request
```

### Pre-conditions

- A list of allowed staff accounts (or a single shared admin credential) is configured.

### Scope

#### Included

- Login screen + session/token issuance.
- Auth guard on **all** API routes (except login/health) and on roster image previews.
- SPA route guard: redirect to `/login` when unauthenticated; logout clears session.
- Option for **Google sign-in restricted to allowed AirAsia accounts** (acceptable per F14).

#### Excluded

- Per-feature role permissions (single validator role assumed for now).

## 🎯 Acceptance Criteria

### Functional Requirements

1. **Login (F14)** — staff authenticate; a valid session/token is issued on success.
2. **API protection** — every non-public endpoint requires a valid session;
   unauthenticated requests get `401`.
3. **PII gating (N5)** — roster image preview endpoints require auth.
4. **SPA guard** — protected pages redirect to login if no valid session; logout
   returns to login.
5. **Allowed accounts** — only configured/allowed identities can sign in
   (e.g. AirAsia Google accounts, or the shared admin secret).

### Error Scenarios

- Wrong credentials → clear error, no session issued.
- Expired/missing session → redirect to login; API returns `401`.
- Direct API call without auth (bypassing the SPA) → rejected.

## 🧩 Technical Documentation

### Endpoints

```
POST /api/auth/login     -> sets session / returns token
POST /api/auth/logout
GET  /api/auth/me        -> current user (or 401)
```

### Frontend

- `LoginPage.tsx`, `AuthContext`, `useAuth`; an auth guard wrapper around
  protected routes; token/session attached to API client (`lib/`).

### Security

- Sessions/tokens stored appropriately (httpOnly cookie preferred over
  localStorage for a PII app); CSRF considered if cookie-based.
- Cloudflare Access can sit in front as an extra layer (see Platform).

## 🔨 Implementation Plan

1. 📝 **TODO** Decide mechanism: shared-secret vs Google-OAuth-restricted (see Open Q).
2. 📝 **TODO** Login/logout/me endpoints + session middleware.
3. 📝 **TODO** API dependency that enforces auth on all protected routes.
4. 📝 **TODO** SPA AuthContext + route guard + API client integration.
5. 📝 **TODO** Auth tests (401 paths, expiry, allowed-account enforcement).

## 🏗 Structure

```
backend/perdiem/web/auth.py
backend/perdiem/web/deps.py            # current-user dependency
frontend/src/pages/LoginPage.tsx
frontend/src/contexts/AuthContext.tsx
frontend/src/hooks/useAuth.ts
```

## 📌 Notes / Open Questions

- **Mechanism:** Google sign-in restricted to AirAsia domain (matches the
  `@airasia.com` accounts already in the data) vs a single shared admin secret
  (simpler, like the wedding example). Lean: Google-restricted for a real
  multi-staff team; shared-secret if it's effectively one operator.
