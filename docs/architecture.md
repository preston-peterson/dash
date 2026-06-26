# Architecture

dash is a single FastAPI application that serves both the JSON API and the static
frontend. There is no separate web server, build step, or client framework.

## Components

- **`app.py`** — the FastAPI app: config, SQLite access, the background status
  checker, the update checker, auth, and all routes. Served by uvicorn over TLS.
- **`static/`** — `index.html`, `styles.css`, `app.js` (vanilla JS, no build).
- **SQLite** (`/data/dashboard.db`) — `links`, `users`, and `sessions` tables.
- **Background tasks** (asyncio) — the status-checker loop and the update-checker
  loop, started in the app lifespan.

## Status checking

Checks run inside the event loop under a concurrency cap. Results live in an
in-memory cache (`{status, latency_ms, last_checked, resolved}`) keyed by link id;
`GET /api/links` merges that cache onto the stored rows. tcp checks use
`asyncio.open_connection`; http checks use a shared `httpx` client (TLS verification
disabled, redirects followed). The DNS counterpart (name⇄IP) is resolved per check.

## Auth

Passwords are pbkdf2-HMAC-SHA256 hashed (200k iterations, per-user salt). A login
mints a `secrets.token_urlsafe` session token, stored in the `sessions` table and
set as a Secure/HttpOnly cookie. The `require_auth` and `require_admin` dependencies
gate the routes.

## TLS

On startup `ensure_cert()` generates a 10-year self-signed RSA certificate (via the
`cryptography` library) if one isn't present, then uvicorn serves HTTPS with it.
You can supply your own cert/key instead — see [Deployment](./deployment.md#https--certificate).

## HTTP API

All `/api/links*`, `/api/check-all`, `/api/users*`, and `/api/update*` require a
session; `/api/users*` additionally require an admin.

| Method | Path | Description |
|---|---|---|
| GET | `/` | Serve the app |
| GET | `/api/me` | `{setup_required, authenticated, user, version}` |
| POST | `/api/setup` | Create the first admin (only when no users exist) |
| POST | `/api/login` | `{username, password}` → set session cookie |
| POST | `/api/logout` | Clear the session |
| GET | `/api/users` | List users (admin) |
| POST | `/api/users` | Create a user (admin) |
| DELETE | `/api/users/{id}` | Delete a user (admin) |
| POST | `/api/users/{id}/password` | Set a password (admin, or self) |
| GET | `/api/links` | All links with current status |
| POST | `/api/links` | Create a link |
| PUT | `/api/links/{id}` | Update a link |
| DELETE | `/api/links/{id}` | Delete a link |
| POST | `/api/links/{id}/check` | Check one link now |
| POST | `/api/check-all` | Check all links now |
| GET | `/api/update` | Update status (current / latest / available / command) |
| POST | `/api/update/check` | Force an update check now |
