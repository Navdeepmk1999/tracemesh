# TraceMesh Master Plan

## Goal
A secure, multi-tenant workflow orchestrator. Users build DAGs of agent and webhook nodes on a
canvas, run them on a reliable task queue, and watch each node execute live.

## Completed

| PR | Phase | Delivered |
|---|---|---|
| 1 | Data layer | Async FastAPI app; SQLAlchemy 2 + asyncpg configured for Supabase Supavisor (transaction mode: `NullPool`, no statement cache); UUID-keyed `workflows`, `nodes`, `executions`; async Alembic |
| 2 | Task queue | aio-pika RabbitMQ broker (connection/channel pools, publisher confirms, persistent messages); durable `tracemesh_tasks` queue with dead-letter queue; standalone worker with manual acks, prefetch and graceful shutdown |
| 3 | Auth + execution engine | Supabase JWT verification (HS256 and JWKS); `workflows.user_id` and tenant-scoped CRUD (404 for other tenants); `POST /execute` with DAG validation; worker state machine with idempotent conditional updates |
| 4 | Graph model + telemetry | Relational `edges` with composite FKs (no cross-workflow edges) and write-time cycle/duplicate checks; `executions.error_message`; Redis Pub/Sub trace events (best-effort, 2s timeout) |
| 5 | Live streaming | `node_runs` table; `/ws/executions/{id}` with first-message auth, subscribe-then-snapshot hydration, 1000/1008/1011 close semantics |
| 6 | Frontend foundation | Next.js 16 App Router, Supabase SSR auth (`proxy.ts` + server-side checks), React Flow canvas with trigger/agent/webhook nodes and client-side graph rules |
| 7 | Canvas ↔ API | Load/save via delta sync with server-ID remapping and retry-safe partial saves; Execute; live node status over WebSocket with reconnect and re-hydration |
| 8 | Testing + CI | Pytest suite on real Postgres with mocked RabbitMQ and fakeredis; migration round trip and drift checks; GitHub Actions with a Postgres 16 service container |
| 9 | Security + auth UI + CRUD | Security audit: RLS on all tables and revoked `anon`/`authenticated` grants (closing Supabase REST API access); `'Untitled Workflow'` default; sign-up with password confirmation and email OTP, password reset, `/auth/confirm` link handling; dashboard create/rename/delete |

Current state: 126 backend tests passing in CI; frontend typechecks, lints and builds.

## Upcoming

### PR 10 — Deployment
- **Backend API on Render** (web service: `uvicorn app.main:app`) and **worker on Render**
  (background worker: `python -m app.worker`), both from `backend/`.
- **Frontend on Vercel** (`frontend/`).
- **Production environment variables:**
  - `CORS_ORIGINS` set to the Vercel domain;
  - `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_WS_URL` set to the Render URL (`https`/`wss`);
  - Supabase, RabbitMQ and Redis credentials stored as platform secrets.
- **Migrations:** run `alembic upgrade head` against the session-mode URL as a release step, before
  the new API version starts.
- **Supabase Auth for production:**
  - custom SMTP (the built-in mailer only reaches project team members and is heavily rate-limited);
  - email templates for sign-up and recovery that include `{{ .Token }}`;
  - Site URL and Redirect URLs that include `https://<domain>/auth/confirm`.
- **Health checks** wired to `/health` (liveness) and `/health/db` + `/health/broker` (readiness).
- **Custom domains** and TLS.

### PR 11 — Production hardening
- Rate limiting on the API (Upstash Redis token bucket), especially `/execute` and edge writes.
- Transactional outbox (or a PENDING sweeper) so a crash between commit and publish can't strand an
  execution.
- Worker leases and fencing tokens, so a network partition can't cause two concurrent runs.
- WebSocket server heartbeats; close sockets when their token expires.
- Frontend tests in CI (lint, typecheck, build, plus browser tests for auth, dashboard and canvas).

### Later
- Per-user Postgres RLS policies so the database also enforces tenancy for the API's own queries.
- Real node executors (LLM calls, outbound webhooks) with per-node idempotency keys.
- Parallel execution of independent branches (per-node messages).
- A shared Redis subscriber per API process; Redis Streams for replayable traces.
- A transactional bulk graph-save endpoint.
- Foreign key from `workflows.user_id` to `auth.users` with cascade on user deletion.
