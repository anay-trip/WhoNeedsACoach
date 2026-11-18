# WhoNeedsACoach

An AI running coach that turns an athlete profile into a conservative race plan, with optional Garmin history and calendar push.

This repo is a FastAPI backend: JWT auth, provider integrations, SQLite persistence, and an async plan-build API. Python owns the calendar and guardrails; a model fills workouts only on dates the planner allows.

```text
POST /auth/register  →  POST /plan (202 pending)  →  poll GET /plan  →  active | failed
                              └─ background: optional Garmin snapshot → LLM → guardrails → optional week push
```

| Layer | Choice |
| --- | --- |
| API | FastAPI + Uvicorn, one process |
| Auth | Access JWT (Bearer) + HttpOnly refresh cookie |
| Data | SQLite (`Repo`), WAL, file-backed Garmin tokens |
| Jobs | In-process `BackgroundTasks` (no Redis / worker fleet) |
| Model | xAI Grok when `XAI_API_KEY` is set; otherwise local Ollama |
| Garmin | MCP stdio server (`garmin-mcp`) from a sibling checkout |

Deep dives: [coaching domain](docs/design.md) · [software design](docs/software-design.md) · [HTTP contract](docs/api.md)

---

## Quick start

**Needs:** Python 3.12+, [uv](https://docs.astral.sh/uv/), and either an [xAI API key](https://console.x.ai/) or a local [Ollama](https://ollama.com/) model.

```bash
git clone <this-repo>
cd WhoNeedsACoach
uv sync

cp .env.example .env
# edit .env — at minimum set AUTH_JWT_SECRET and XAI_API_KEY (or run Ollama)

uv run uvicorn whoneedsacoach.api.app:app --reload --port 8000
```

Open interactive docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

```bash
uv run pytest
# 37 tests — auth, integrations, plan async status machine, repo (no live Garmin / LLM)
```

Garmin is optional for a first plan. Without a connection, send `baseline` (and race/schedule) in `POST /plan`; the API validates the profile and still runs the LLM + guardrails path.

---

## Try the API (no UI)

Race date must be at least 56 days out (guardrail). Adjust the date below if you clone this later.

```bash
# 1) Register
curl -s -c cookies.txt -X POST http://127.0.0.1:8000/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"demo@example.com","password":"demo-pass-1","display_name":"Demo"}'

# 2) Copy access_token from the JSON, then create a plan
TOKEN='paste-access-token-here'

curl -s -X POST http://127.0.0.1:8000/plan \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "race": { "distance": "half_marathon", "date": "2027-06-01" },
    "schedule": { "run_days": ["wed", "fri", "sun"], "long_run_day": "sun" },
    "baseline": { "weekly_km": 30.0, "long_run_km": 12.0 },
    "pr": { "time": "1:45:00", "date": "2026-06-01" }
  }'

# 3) Poll until status is active or failed
curl -s http://127.0.0.1:8000/plan -H "Authorization: Bearer $TOKEN"
```

Refresh uses the cookie jar (`cookies.txt`) against `POST /auth/refresh` — the refresh token is never returned in JSON.

---

## Architecture

```text
Client / Swagger
   │  Bearer JWT ──────────────────────────────► FastAPI
   │  HttpOnly cookie ──► POST /auth/refresh ───►    │
   │                                                 ├─► SQLite (coach.db)
   │                                                 ├─► data/tokens/{user_id}/{provider}
   │                                                 │
   │                                                 └─ enqueue in-process job
   │                                                        ├─► profile checks + LLM + guardrails
   │                                                        └─► garmin-mcp (MCP stdio) ──► tokens
```

**Auth:** short-lived access JWT (`Authorization: Bearer`); opaque refresh in an HttpOnly cookie (`Path=/auth`). Passwords are bcrypt. Refresh hashes are stored; plaintext refresh is not.

**Integrations:** `POST /integrations/connect` with `{provider, email, password}` (v1: `garmin`). MFA returns `challenge_required`; complete via `POST /integrations/challenge`. Connecting does not create a plan; creating a plan does not require a connection.

**Plans:** one plan row per user. `POST /plan` always overwrites, returns `202` with `pending`, then `building` → `active` | `failed`. A newer `generation_id` supersedes a stale background job.

---

## Repository map

```text
src/whoneedsacoach/
  api/           FastAPI app, auth / integrations / plan routes
  auth/          JWT, refresh cookies, bcrypt, Garmin LoginService
  integrations/  Provider registry + Garmin adapter
  jobs/          Async plan build (pending → building → active|failed)
  planner/       Guardrails, schedule, training plan assembly
  agent/         CLI coach flow (separate from the HTTP path)
  store/         SQLite schema + Repo
  tools/         Garmin MCP client
docs/            Design + HTTP contract
tests/           API and domain tests with fakes
```

Entry point: `uvicorn whoneedsacoach.api.app:app`

---

## Configuration

Copy [`.env.example`](.env.example) → `.env`. Important variables:

| Variable | Purpose |
| --- | --- |
| `AUTH_JWT_SECRET` | HS256 secret for access tokens — required for anything beyond local play |
| `XAI_API_KEY` | Use Grok for plan generation (recommended for reviewers) |
| `GROK_MODEL` | Optional; default `grok-4.6` |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | Used when `XAI_API_KEY` is unset |
| `CORS_ORIGINS` | Comma-separated browser origins (credentials enabled) |
| `COACH_DB` / `COACH_TOKENS` | SQLite path and Garmin token root |
| `GARMIN_REPO` | Checkout of the `garmin-mcp` project (`uv run garmin-mcp` cwd) |
| `AUTH_COOKIE_SECURE` | `true` behind HTTPS |

Without `XAI_API_KEY`, the process expects Ollama at `http://localhost:11434/v1`. Auth and `/docs` still work; `POST /plan` fails at build time if no model is reachable.

---

## Design choices (worth reading in an interview)

- **Python owns safety; the model fills slots.** Race horizon, weekly km bounds, run-day constraints, and progression rules live in code (`docs/design.md`). The LLM never sees the raw Garmin activity list — only a reduced athlete profile.
- **Single process on purpose.** SQLite + in-process jobs keep the v1 surface small. That also means one replica, a real disk, and no scale-to-zero host if you deploy it.
- **Provider-agnostic HTTP, Garmin-first adapter.** Routes talk `provider`; the registry maps to adapters. Challenge state for MFA is in-memory (~5 minutes).
- **Overwrite, don’t merge.** A second `POST /plan` replaces the user’s plan and supersedes in-flight builds via `generation_id`.

---

## Optional: Garmin

1. Clone / install the `garmin-mcp` project and set `GARMIN_REPO` to that directory.
2. Ensure `uv` can run `garmin-mcp` from that cwd.
3. With a logged-in API user, call `POST /integrations/connect` (`provider: "garmin"`) and complete MFA if asked.
4. `POST /plan` may enrich baseline/PR from history and push the current week after build. Client-supplied baseline/PR still win when provided.

CLI (personal Garmin login helpers): `uv run coach login` / `uv run coach plan` — see `src/whoneedsacoach/cli.py`. Prefer the HTTP API for review.

---

## What this is not (yet)

No production deploy config in-repo, no separate worker, no Postgres, no web UI, no refresh-token rotation/TTL. Those are intentional v1 cuts documented in `docs/software-design.md`.
