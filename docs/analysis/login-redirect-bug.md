# Login Redirect Bug Analysis

**Date:** 2026-05-24  
**Status:** Fixed  
**Symptom:** Login returns HTTP 200 with a valid JWT but the browser stays on `/login` instead of navigating to `/`.

---

## Observed Behaviour

1. User enters password on `/login` and submits.
2. `POST /api/auth/login` responds **200 OK** with `{ access_token: "eyJ…", token_type: "bearer" }`.
3. Page stays on `/login`. No redirect occurs.

---

## System Overview (Auth Flow)

```
Browser (Vite :5173)
  └─ POST /api/auth/login  ──proxy──►  FastAPI :8000
                                          │ verify password
                                          │ create JWT
                                          │ Set-Cookie: session_token=<jwt>; HttpOnly; SameSite=lax
                                        ◄─┘
  cookie stored by browser for localhost

  GET /api/auth/me  ──proxy──►  FastAPI reads session_token cookie ──► returns { user: "admin" }
```

The backend is **cookie-based**: `session_token` is an HttpOnly cookie, not a Bearer header. The `access_token` in the response body is informational only; the frontend does not need to store or send it.

---

## Root Cause

`AuthContext` calls `getMe()` exactly once — on mount — via `useEffect([], ...)`.

```
Page load
  └─ AuthProvider mounts
       └─ getMe() → 401 (not logged in yet) → user = null, loading = false

User submits password
  └─ LoginPage: await login(password)          ← cookie is set ✓
       └─ navigate('/')                        ← triggers AuthGuard
            └─ AuthGuard reads user from context  ← still null (getMe() never re-ran)
                 └─ <Navigate to="/login" />   ← bounced back ✗
```

**The context never knew the user logged in.** `getMe()` ran once before login and cached `null`. After the cookie was set, nobody re-fetched.

---

## What Is NOT the Bug

| Component | Status | Reason |
|-----------|--------|--------|
| `POST /api/auth/login` | ✅ Correct | Sets HttpOnly cookie, returns token |
| Cookie forwarding (Vite proxy) | ✅ Correct | `Set-Cookie` header forwarded back through proxy |
| `GET /api/auth/me` | ✅ Correct | Reads cookie, returns user |
| `AuthGuard` logic | ✅ Correct | Correctly blocks `user === null` |
| `LoginPage.navigate('/')` | ✅ Correct | Route change fires, but context state was stale |

---

## Fix

Add a `login` function to `AuthContext` that calls the API **and** refreshes `user` state before returning. `LoginPage` uses `useAuth().login()` instead of calling `apiClient.login` directly.

### Files changed

| File | Change |
|------|--------|
| `frontend/src/contexts/AuthContext.tsx` | Add `login(password)` to context; after API call, call `getMe()` to set `user` |
| `frontend/src/pages/LoginPage.tsx` | Use `const { login } = useAuth()` instead of importing `login` from `apiClient` |

### Flow after fix

```
User submits password
  └─ useAuth().login(password)
       ├─ POST /api/auth/login  → cookie set ✓
       ├─ GET /api/auth/me      → user = "admin"
       └─ setUser("admin")      ← context updated ✓

LoginPage: navigate('/')
  └─ AuthGuard reads user = "admin" → renders protected page ✓
```
