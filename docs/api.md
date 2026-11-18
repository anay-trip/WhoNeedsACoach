# WhoNeedsACoach HTTP API

FastAPI on a single process with SQLite. Access is a short-lived JWT in the JSON body / `Authorization` header. Refresh is an opaque HttpOnly cookie. Fitness providers are connected through `/integrations/*` (Garmin first). Plans are created asynchronously and polled.

Run locally:

```bash
uv sync
uv run uvicorn whoneedsacoach.api.app:app --reload --port 8000
```

Set `AUTH_JWT_SECRET` in production. Optional: `AUTH_ACCESS_TTL_SECONDS` (default 900), `AUTH_COOKIE_SECURE` (`true` in HTTPS), `CORS_ORIGINS`, `COACH_DB`, `COACH_TOKENS`.

## Tokens

| Token | Type | Lifetime | Transport | Used on |
| --- | --- | --- | --- | --- |
| Access | JWT HS256 (`sub` = user id, `exp`, `jti`) | ~15 minutes | JSON `access_token`; send as `Authorization: Bearer …` | All protected routes |
| Refresh | Opaque 32+ bytes | Until logout (no TTL, no rotation) | `Set-Cookie` only: `HttpOnly`, `Secure` in prod, `SameSite=Lax`, `Path=/auth` | `POST /auth/refresh`, `POST /auth/logout` |

Only `sha256(refresh)` is stored. Logout revokes that hash and clears the cookie. Access JWTs may remain valid until `exp`.

## Auth

| Method | Path | Auth | Behavior |
| --- | --- | --- | --- |
| `POST` | `/auth/register` | — | `{email, password, display_name?}` → access JWT + refresh cookie |
| `POST` | `/auth/login` | — | same |
| `POST` | `/auth/refresh` | refresh cookie | new access JWT; same refresh cookie |
| `POST` | `/auth/logout` | refresh cookie | revoke hash; clear cookie |

Invalid app login returns a generic `401 Invalid credentials`.

## Integrations (provider-agnostic)

Login required. Connecting a provider does **not** create a plan. Creating a plan does **not** require a connection.

| Method | Path | Behavior |
| --- | --- | --- |
| `POST` | `/integrations/connect` | `{provider, email, password}` → `connected` or `challenge_required` + `challenge_id` + `challenge_type` |
| `POST` | `/integrations/challenge` | `{provider, challenge_id, code}` completes MFA |
| `GET` | `/integrations` | list `{provider, status, connected_at}` |
| `DELETE` | `/integrations/{provider}` | disconnect; delete token files best-effort |

v1 `provider` value: `garmin`. Challenge state is in-process (~5 minutes) and bound to `user_id` + `provider`. Tokens live under `TOKEN_ROOT / user_id / provider` with directory mode `0700` and file mode `0600`.

## Plan

| Method | Path | Behavior |
| --- | --- | --- |
| `GET` | `/me` | profile, integrations summary, current plan `status` or null |
| `GET` | `/plan` | whole plan resource, or `404` if none |
| `POST` | `/plan` | create or **overwrite**; enqueue build; returns quickly with `status: pending` (`202`) |

No week sub-route. No accept/reject. A second `POST /plan` always overwrites (never `409`). If a build is in flight, a newer `generation_id` supersedes stale job results.

### `POST /plan` body

```json
{
  "race": { "distance": "half_marathon", "date": "2027-06-01" },
  "schedule": { "run_days": ["wed", "fri", "sun"], "long_run_day": "sun" },
  "baseline": { "weekly_km": 30.0, "long_run_km": 12.0 },
  "pr": { "time": "1:45:00", "date": "2026-06-01" }
}
```

`pr` is optional (`null` / omit = no personal best). When set, it is treated as a best for the race distance. Without a connected provider, `baseline` plus race/schedule must pass profile validation. With a connected Garmin account, the job may enrich the snapshot from history and push the current week after build; client baseline/PR still win when provided.

### Async statuses

| Status | Meaning |
| --- | --- |
| `pending` | Accepted; job not started or queued |
| `building` | Snapshot (if provider) + LLM + guardrails + optional calendar push |
| `active` | Done; `plan` populated |
| `failed` | Terminal; `error_message` and `failed_at` set |

```text
POST /plan → pending → building → active
                          ↘ failed
active|failed → pending (on overwrite POST /plan)
```

Poll `GET /plan` until `active` or `failed`.

## ER diagram

```text
Relationships
-------------
users 1 --- * refresh_tokens
users 1 --- * provider_connections
users 1 --- 0..1 plans
users 1 --- * activities
plans 1 --- * activities

users
  id                  PK
  email               UNIQUE
  password_hash
  display_name
  created_at

refresh_tokens
  id                  PK
  user_id             FK -> users
  token_hash          UNIQUE
  created_at
  revoked_at

provider_connections
  id                  PK
  user_id             FK -> users
  provider            UNIQUE with user_id
  token_dir
  status
  connected_at

plans
  id                  PK
  user_id             FK -> users, UNIQUE
  status
  race_json
  schedule_json
  snapshot_json
  plan_json
  error_message
  failed_at
  updated_at

activities
  id                  PK
  user_id             FK -> users
  plan_id             FK -> plans
  session_date
  garmin_activity_id
  distance_km
  duration_seconds
  workout_id
```

`provider_connections.status` is `connected` or `disconnected`. Unique `(user_id, provider)`. `plans` is one row per user. CLI paths may still use `pending_json` and review statuses; the HTTP path uses `pending` / `building` / `active` / `failed` only.
