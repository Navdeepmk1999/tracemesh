# TraceMesh Architecture

TraceMesh is a multi-tenant workflow orchestrator. Users build a DAG of nodes on a canvas, then
execute it. A worker runs the nodes in dependency order, and the UI shows each node's progress
live.

This document describes the system as implemented (through PR 9).

## Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16.4 (App Router) · React 19.3 · TypeScript · Tailwind CSS 4 · React Flow (`@xyflow/react` 12) |
| Auth | Supabase Auth (email + password, email OTP verification, password reset) via `@supabase/ssr` 0.12 |
| API | FastAPI 0.159 on uvicorn · Pydantic 2 · Python 3.12 |
| Database | PostgreSQL (Supabase) · SQLAlchemy 2.1 async + asyncpg · Alembic, via the Supavisor pooler (transaction mode) |
| Task queue | RabbitMQ (CloudAMQP) via aio-pika 10 |
| Live telemetry | Redis Pub/Sub (Upstash) via redis-py 8 (`redis.asyncio`) |
| Tests / CI | Pytest 9 + pytest-asyncio, httpx / httpx-ws, fakeredis · GitHub Actions with a Postgres 16 service |

## Components

```
Browser ──(Supabase JS: sign-up, OTP, login, reset)──────────────► Supabase Auth
   │  session cookies (@supabase/ssr), refreshed by src/proxy.ts
   ├── REST, Authorization: Bearer <access token> ──► FastAPI ──► Postgres
   └── WebSocket /ws/executions/{id} ───────────────► FastAPI ◄── Redis Pub/Sub ◄── Worker
                                                         │                            ▲
                                                         └──► RabbitMQ (tracemesh_tasks) ┘
                                                                  └─ DLX ─► tracemesh_tasks.dead
```

### Next.js app (`frontend/`)
- **Routing and session:** `src/proxy.ts` (Next 16's replacement for `middleware.ts`) runs on every
  non-asset request. It refreshes the Supabase session cookie using `getClaims()`, which verifies
  the JWT, and does *optimistic* redirects:
  - signed-out users are sent from `/workflows*` and `/reset-password` to `/login`;
  - signed-in users are sent away from `/login`, `/signup`, `/verify` and `/forgot-password`.
- **Server-side verification:** protected pages call `requireUser()` (`src/lib/auth.ts`) to check
  again on the server.
- **Auth pages:** `/signup`, `/verify` (email OTP), `/login`, `/forgot-password` → `/reset-password`,
  and `/auth/confirm` (the email-link landing route, which handles both PKCE `?code=` links and
  `token_hash` links).
- **Dashboard** (`/workflows`): list, create (with a name prompt), rename and delete through the
  FastAPI API.
- **Canvas** (`/workflows/[id]`):
  - React Flow editor, rendered client-only, with `trigger`, `agent` and `webhook` node types.
  - Client-side graph rules that mirror the API's (`components/canvas/graph-rules.ts`).
  - Delta save (`components/canvas/graph-sync.ts`).
  - Execute, plus live run state from `hooks/use-execution-trace.ts`.
- **Talking to the API:** the browser calls FastAPI **directly**, using `NEXT_PUBLIC_API_URL` and the
  user's Supabase access token as a bearer token (`src/lib/api/client.ts`). Next.js doesn't proxy
  API traffic.

### FastAPI service (`backend/app/`)
| Module | Responsibility |
|---|---|
| `main.py` | App, CORS, lifespan (connects to RabbitMQ on startup, so an unreachable broker fails startup; closes RabbitMQ, Redis and the DB engine on shutdown), health endpoints |
| `auth.py` | `get_current_user`: verifies the Supabase JWT, returns `user_id` |
| `api.py` | Tenant-scoped REST: workflows, nodes, edges, executions |
| `dag.py` | Topological order, cycle detection, execution payload |
| `broker.py` | Pooled RabbitMQ connections and channels, `publish_task`, queue topology |
| `telemetry.py` | Shared Redis client, `publish_trace` to `trace:{execution_id}` |
| `websockets.py` | `/ws/executions/{id}`: auth handshake, state hydration, trace forwarding |
| `database.py` | Async engine and sessions, set up for Supavisor transaction mode |
| `models.py` / `pydantic_schemas.py` | ORM models and request/response schemas |

### Worker (`backend/app/worker.py`, run as `python -m app.worker`)
A standalone process that consumes `tracemesh_tasks`, runs executions, records progress in
Postgres and publishes trace events. Node execution is currently simulated: one second per node,
and `config_json.simulate_failure` makes a node raise. Nodes run sequentially in topological order.

## Data model

| Table | Key columns | Notes |
|---|---|---|
| `workflows` | `id`, `user_id` (indexed), `name` (default `'Untitled Workflow'`), `description`, `created_at` | The tenant boundary: `user_id` is the Supabase user (JWT `sub`) |
| `nodes` | `id`, `workflow_id` → workflows (cascade), `node_type`, `config_json` (JSONB) | `UNIQUE (workflow_id, id)` is the target for the edges' composite FKs |
| `edges` | `id`, `workflow_id`, `source_node_id`, `target_node_id` | Composite FKs `(workflow_id, source/target) → nodes(workflow_id, id)`: an edge can't cross workflows. `CHECK source <> target`, `UNIQUE (source, target)` |
| `executions` | `id`, `workflow_id` (cascade), `status` (`PENDING`/`RUNNING`/`COMPLETED`/`FAILED`), `started_at`, `completed_at`, `error_message` | |
| `node_runs` | `id`, `execution_id` (cascade), `node_id` (cascade), `status`, timestamps, `error_message` | One row per (execution, node), created with the execution; the source for WebSocket hydration |

Node display data (label, model, URL and so on) and canvas position are stored in `config_json`. All
primary keys are UUIDs. Migrations live in `backend/alembic/versions/`.

## API surface

All REST routes require `Authorization: Bearer <Supabase JWT>`, except `/health*`.

| Method | Path | |
|---|---|---|
| `POST` / `GET` | `/workflows` | Create (name optional) / list, newest first (`limit` ≤ 200, `offset`) |
| `GET` / `PATCH` / `DELETE` | `/workflows/{id}` | Read / rename or edit description / delete (cascades) |
| `POST` / `GET` | `/workflows/{id}/nodes` | Create / list |
| `GET` / `PATCH` / `DELETE` | `/workflows/{id}/nodes/{node_id}` | Read / update `node_type` or `config_json` / delete (its edges cascade) |
| `POST` / `GET` | `/workflows/{id}/edges` | Create (validated) / list |
| `GET` / `PATCH` / `DELETE` | `/workflows/{id}/edges/{edge_id}` | Read / re-point (validated) / delete |
| `POST` | `/workflows/{id}/execute` | `202 {execution_id, status: "PENDING"}` |
| `GET` | `/workflows/{id}/executions`, `/executions/{id}` | Run history / one run |
| `WS` | `/ws/executions/{id}` | Live trace (protocol below) |
| `GET` | `/health`, `/health/db`, `/health/broker` | Liveness / readiness |

**Errors:**
- **404** for any resource the caller doesn't own, never 403, so IDs don't reveal other tenants'
  data.
- **422** for validation failures, including self-loops, cycles, edges to another workflow's nodes,
  and empty or cyclic workflows on execute.
- **409** for duplicate edges.
- **503** when the broker rejects a publish.

## Data flows

### 1. Authentication
1. **Sign-up:**
   1. `supabase.auth.signUp()` creates the account, and Supabase emails a code and a link.
   2. `/verify` calls `verifyOtp({type: "signup"})`, or the email link lands on `/auth/confirm`.
   3. Either way, a session is created.
2. **Session storage:** the session is held in cookies managed by `@supabase/ssr`. `src/proxy.ts`
   refreshes it on each request.
3. **API calls:** the browser reads the access token with `getSession()` (which refreshes it if
   expired) and sends it as a bearer token.
4. **Verification in the API:** FastAPI verifies the token in `auth.py`.
   - The **algorithm selects the key:** HS256 uses `SUPABASE_JWT_SECRET`, and ES256/RS256 use the
     project JWKS when `SUPABASE_URL` is set. The token can never choose its own verification key.
   - Required claims: `exp`, `sub`, and `aud=authenticated`. `iss` is checked when `SUPABASE_URL`
     is set. A token without `sub` (anon or service keys) is rejected.
5. **Password reset:** `resetPasswordForEmail()` sends a code and a link → `verifyOtp({type:
   "recovery"})` or `/auth/confirm` → `/reset-password` → `updateUser({password})`.

### 2. Editing and saving a workflow
The canvas loads the workflow, its nodes and its edges, then keeps a snapshot of what the server
last confirmed. Save sends only the difference, in this order:

1. Delete removed edges.
2. Delete removed nodes.
3. Create new nodes. The server assigns their IDs, and local IDs are remapped.
4. Patch moved or edited nodes.
5. Create new edges, using server node IDs.

The snapshot advances after each successful call, so retrying a partly failed save only replays
what's left.

The API validates every edge write, rejecting self-loops, nodes outside the workflow, duplicates and
cycles. The database's composite foreign keys enforce the same-workflow rule independently.

### 3. Executing
1. `POST /workflows/{id}/execute` checks ownership. It loads the nodes and edges and validates the DAG
   (`graphlib.TopologicalSorter`, with IDs sorted for a deterministic order).
2. In one transaction it inserts a `PENDING` execution and a `PENDING` `node_runs` row per node, then
   commits.
3. It then publishes the payload to RabbitMQ: a persistent message with publisher confirms and
   `mandatory`/`on_return_raises`. The payload is `{execution_id, workflow_id, user_id, nodes,
   edges, order}`. If the publish fails, the execution is marked `FAILED` and the API returns 503.

### 4. Running (worker)
1. **Consume** with `prefetch_count` (default 1) and manual acks.
2. **Claim** with a single conditional UPDATE: `PENDING`/`RUNNING` → `RUNNING`, resetting that run's
   `node_runs` to `PENDING` in the same transaction. If no row is claimed, the run is already
   terminal or deleted, so the message is acked and skipped. A `RUNNING` row on delivery means a
   previous worker crashed, so it runs again.
3. **For each node in topological order:**
   1. Write `node_runs.status = RUNNING`, then publish `node.started`.
   2. Run the node.
   3. Write `COMPLETED` (or `FAILED` with `error_message`), then publish `node.completed` (or
      `node.failed`).
4. **Finish:** write the execution's final status, publish `execution.completed` or
   `execution.failed`, then ack.

Error handling:

| Case | Message handling |
|---|---|
| Malformed message | `reject(requeue=False)`, so it goes to `tracemesh_tasks.dead` |
| Node failure | Execution `FAILED` with `error_message`; ack (a final outcome) |
| Infrastructure failure (e.g. the database) | `nack`, requeued once (when `redelivered` is false), then dead-lettered |
| Trace publishing | Best-effort, 2s timeout, failures logged and dropped |

On SIGTERM/SIGINT the worker stops consuming, finishes and acks in-flight messages, then exits.

### 5. Live telemetry (WebSocket)
1. The client opens `/ws/executions/{id}` and sends `{"type": "auth", "token": "<jwt>"}` within 10s.
   Putting the token in a message rather than the URL keeps it out of access logs.
2. The server verifies the token, **subscribes to `trace:{id}` first**, then reads the execution and
   its `node_runs` from Postgres, checking ownership in the same query.
3. It sends one `state.hydrated` event, then forwards each Redis message verbatim.
4. Close codes:

| Code | When |
|---|---|
| **1000** | After a terminal event, or straight after hydration if the run had already finished |
| **1008** | Any auth or ownership failure (no data is sent first) |
| **1011** | Redis or DB failure mid-stream |

Because of subscribe-then-snapshot, an event may repeat something the snapshot already shows. The
client applies events as idempotent state updates, and node statuses never move backwards except
on `execution.started`. It reconnects with backoff (up to 5 attempts) on 1011 or a dropped
connection, getting a fresh snapshot each time.

## Event format (`trace:{execution_id}`)

Every event has `execution_id`, `timestamp`, `event` and `seq` (per execution attempt, starting at 1).

| `event` | Extra fields |
|---|---|
| `state.hydrated` (WebSocket only, from Postgres) | `execution` (`ExecutionRead`), `nodes` (`NodeRunRead[]`) |
| `execution.started` | `status`, `node_count`, `order`, `redelivered` |
| `node.started` | `node_id`, `node_type`, `index`, `total` |
| `node.completed` | node fields + `duration_ms` |
| `node.failed` | node fields + `duration_ms`, `error` |
| `execution.completed` | `status`, `duration_ms` |
| `execution.failed` | `status`, `duration_ms`, `error` |

## Security model

- **Authentication:** every REST route and the WebSocket verify a Supabase JWT. A test walks the
  OpenAPI schema and asserts that every non-health route returns 401 without a token.
- **Tenant isolation (application layer):**
  - every handler first loads the owning workflow, or joins to it, filtered on `user_id = sub`;
  - child queries are scoped to that verified workflow or execution;
  - `user_id` and `workflow_id` are never taken from request bodies;
  - cross-tenant isolation tests cover every resource type.
- **Tenant isolation (schema):** composite foreign keys stop edges from linking nodes in different
  workflows.
- **Supabase Data API lockdown:** RLS is enabled on every `public` table **with no policies**, and
  `anon` and `authenticated` grants are revoked (migration `4ec12bc82981`). This blocks the public
  anon key from reading or writing tables through PostgREST.
  - The backend connects as the table owner, so RLS doesn't restrict the API's own queries. Tenant
    isolation there is the application layer above.
  - A test fails CI if any `public` table lacks RLS.
- **Redirect safety:** post-login `next` targets and `/auth/confirm` only allow same-site paths.

## Reliability guarantees

- **At-least-once delivery:**
  - durable queue, persistent messages, publisher confirms;
  - a message is acked only after its outcome is committed;
  - unacked messages are redelivered when a worker's channel closes.
- **Idempotent state changes:** status changes are conditional (`UPDATE … WHERE status IN (…)
  RETURNING`), so a duplicate delivery of a finished execution changes nothing.
- **Database first:** every status write is committed before its trace event is published, so a
  database snapshot is never behind the live stream.
- **Telemetry is non-critical:** a Redis outage drops live events but never fails or slows an
  execution beyond the 2s publish timeout.

## Configuration

| Backend (`backend/.env`) | |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://…` Supavisor transaction-mode URL (port 6543) |
| `MIGRATION_DATABASE_URL` | Optional direct/session URL for Alembic |
| `SUPABASE_JWT_SECRET` / `SUPABASE_URL` | HS256 secret / project URL (enables JWKS verification and the issuer check) |
| `RABBITMQ_URL`, `WORKER_PREFETCH_COUNT` | Broker URL, unacked messages per worker (default 1) |
| `REDIS_URL` | `rediss://…` for Upstash |
| `CORS_ORIGINS` | JSON list of allowed browser origins |

| Frontend (`frontend/.env.local`) | |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase project |
| `NEXT_PUBLIC_API_URL` | FastAPI base URL (default `http://127.0.0.1:8000`) |
| `NEXT_PUBLIC_WS_URL` | Optional; defaults to the API URL with `http(s)` → `ws(s)` |

**Database connections:** the engine uses `NullPool`, because Supavisor does the pooling. It also
disables asyncpg's prepared-statement cache and gives each statement a unique name, because in
transaction mode consecutive statements can run on different Postgres backends.

## Testing

`backend/tests/` has 126 tests and runs in about 6 seconds:
- **Real PostgreSQL,** because the constraints, JSONB, enums and conditional UPDATEs are part of what's
  under test. The schema is built by running the migrations down to base and back up.
- **Mocked RabbitMQ** (a publish recorder and fake aio-pika channels) and **fakeredis** for Redis.
- **A safety guard** refuses to run against any database that isn't local or whose name doesn't
  contain `test`.
- **CI:** `.github/workflows/backend-tests.yml` runs on pushes to `main` and on PRs that touch
  `backend/`.

The frontend has no automated tests in CI yet.

## Known limitations

- **Lost tasks:** if the API crashes between committing an execution and publishing it, the
  execution stays `PENDING` (no outbox yet).
- **Double runs:** `RUNNING` executions are re-claimable for crash recovery. Without worker leases,
  a network partition could let two workers run the same execution.
- **Dead connections:** the WebSocket has no server heartbeat event, so a half-open connection isn't
  detected by the client.
- **Expired tokens:** a socket isn't closed when its token expires.
- **Redis connections:** each WebSocket holds its own Redis Pub/Sub connection.
- **Saves aren't atomic:** a save is several REST calls, not one transaction.
- **Graph size:** the canvas loads at most 200 nodes and 200 edges.
- **Sequential runs:** nodes run one after another; independent branches don't run in parallel.
- **User deletion:** `workflows.user_id` has no foreign key to `auth.users`, so deleting a user
  doesn't remove their workflows.
- **Simulated nodes:** node execution is simulated.
