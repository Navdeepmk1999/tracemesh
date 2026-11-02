# TraceMesh

A multi-tenant workflow orchestrator for agent pipelines. Build a DAG of triggers, agents and
webhooks on a visual canvas, run it on a reliable task queue, and watch every node execute live.

## Features

- **Visual workflow builder:** React Flow canvas with drag-and-drop nodes. Connection rules block
  self-loops, duplicates and cycles as you draw, and the API enforces the same rules.
- **Reliable execution:** executions are queued on RabbitMQ with at-least-once delivery and handled
  idempotently, so duplicate deliveries are harmless. Bad messages go to a dead-letter queue, and
  workers shut down gracefully.
- **Live run status:** workers record each node's progress in Postgres, then publish it over Redis
  Pub/Sub. The browser gets a snapshot over an authenticated WebSocket, then the live stream, so
  it's correct even when it joins mid-run.
- **Accounts:** sign-up with password confirmation and email verification code, sign-in, and
  password reset (Supabase Auth).
- **Workflow management:** create, rename and delete workflows from the dashboard.
- **Tenant isolation:**
  - Every API request is authenticated with the user's Supabase JWT.
  - Every query is scoped to the caller, and other users' resources return 404.
  - The database prevents edges between workflows.
  - Row-level security blocks Supabase's public REST API from reaching the tables.

## Tech stack

| | |
|---|---|
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4, React Flow 12, `@supabase/ssr` |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 (async, asyncpg), Alembic, aio-pika, redis-py |
| Infrastructure | PostgreSQL + Auth (Supabase), RabbitMQ (CloudAMQP), Redis (Upstash) |
| Testing / CI | Pytest, pytest-asyncio, httpx-ws, fakeredis; GitHub Actions with Postgres 16 |

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for components, data flows and guarantees, and
[docs/MASTER_PLAN.md](docs/MASTER_PLAN.md) for the roadmap.

## Repository layout

```
backend/
  app/            FastAPI app, worker, broker, telemetry, models
  alembic/        database migrations
  tests/          pytest suite (real Postgres, mocked RabbitMQ and Redis)
frontend/
  src/app/        Next.js routes (auth pages, /workflows dashboard, /workflows/[id] canvas)
  src/components/ canvas, nodes, auth forms, dashboard
  src/proxy.ts    session refresh and route protection
docs/             architecture, roadmap, engineering journal
```

## Local development

### Prerequisites
- Python 3.12 and Node.js 20.9+ (required by Next.js 16).
- A Supabase project: Postgres plus Auth.
- A RabbitMQ broker: CloudAMQP's free tier, or local `docker run -p 5672:5672 rabbitmq:3`.
- A Redis instance: Upstash's free tier, or local `docker run -p 6379:6379 redis:7`.

### 1. Backend
```bash
cd backend
python3.12 -m venv tracemesh-env
tracemesh-env/bin/pip install -r requirements-dev.txt
cp .env.example .env          # fill in DATABASE_URL, SUPABASE_JWT_SECRET, SUPABASE_URL, RABBITMQ_URL, REDIS_URL
tracemesh-env/bin/alembic upgrade head
```

### 2. Frontend
```bash
cd frontend
npm install
cp .env.example .env.local    # fill in NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY
```

### 3. Supabase Auth settings (dashboard)
- **Email templates:** add `{{ .Token }}` to the *Confirm signup* and *Reset password* templates,
  so users receive a code. The links in those emails also work.
- **Redirect URLs:** under URL Configuration, add `http://localhost:3000/auth/confirm`.
- **SMTP:** the built-in mailer only delivers to project team members and is rate-limited. Configure
  custom SMTP before inviting other users.

### 4. Run it (three terminals)
```bash
# API — http://127.0.0.1:8000 (docs at /docs)
cd backend && tracemesh-env/bin/uvicorn app.main:app --reload

# Worker
cd backend && tracemesh-env/bin/python -m app.worker

# UI — open http://localhost:3000
cd frontend && npm run dev
```

Open the app at `http://localhost:3000`, not `127.0.0.1:3000`: the API's `CORS_ORIGINS` allows
`http://localhost:3000` by default. The API won't start if it can't reach RabbitMQ.

### Tests
The backend suite needs a disposable local Postgres. RabbitMQ and Redis are mocked:

```bash
docker run -d --name tm-test-db -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=tracemesh_test -p 5432:5432 postgres:16
cd backend && tracemesh-env/bin/pytest
```

The suite refuses to run against any database that isn't local or whose name doesn't contain
`test`, because it truncates tables. Set `TEST_DATABASE_URL` to use a different database. CI runs
the same suite on every PR that touches `backend/`.

Frontend checks:
```bash
cd frontend && npm run lint && npx tsc --noEmit && npm run build
```
