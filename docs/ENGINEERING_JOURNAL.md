## [Today's Date] PR 1: Async Database Scaffolding
**What we built:** Initialized the FastAPI application structure and SQLAlchemy 2.0 ORM models for `workflows`, `nodes`, and `executions`. 
**Key architectural decision:** Configured SQLAlchemy to use `NullPool` and disabled `asyncpg` statement caching to support Supavisor in transaction mode (Port 6543). This prevents "prepared statement already exists" errors when the pooler swaps our underlying Postgres connection.

## [Today's Date] PR 2: RabbitMQ Message Broker & Async Workers
**What we built:** Integrated CloudAMQP RabbitMQ using `aio-pika` to decouple the API gateway from long-running agent tasks. 
**Key architectural decisions:** 
* Implemented a connection pool and channel multiplexing to prevent socket exhaustion.
* Configured a Dead-Letter Queue (`tracemesh_tasks.dead`) to capture malformed payloads without crashing the worker loop.
* Implemented graceful shutdown (handling `SIGINT`/`SIGTERM`) so the worker finishes active tasks before terminating, ensuring zero data loss during deployments.

## [Today's Date] PR 3: Multi-Tenancy & Execution Engine
**What we built:** Enforced strict multi-tenancy using Supabase JWT authentication and wired the FastAPI DAG validation to the asynchronous RabbitMQ worker.
**Key architectural decisions:** 
* Implemented zero-trust endpoints; verifying the `aud=authenticated` claim and extracting the `sub` (user_id) blocks anonymous and service-role JWT forgeries.
* Prevented IDOR (Insecure Direct Object Reference) by returning 404s instead of 403s for cross-tenant data requests.
* Designed the worker with strict state-machine transitions, ensuring duplicate RabbitMQ deliveries cannot overwrite `COMPLETED` executions.

## [Today's Date] PR 4: Schema Refinement & Redis Telemetry
**What we built:** Migrated workflow dependencies to a relational `edges` table and implemented real-time execution telemetry via Upstash Redis.
**Key architectural decisions:** 
* Pushed cross-tenant constraints down to the PostgreSQL database engine for the `edges` table.
* Implemented fail-open telemetry with 2-second timeouts, ensuring a Redis outage degrades observability without crashing the execution worker.
* Added `simulate_failure` injection to easily demonstrate Dead-Letter Queue and error state handling in the UI.

## [Today's Date] PR 5: WebSocket Telemetry & State Hydration
**What we built:** Implemented `/ws/executions/{execution_id}` to stream live trace events from Redis to the client.
**Key architectural decisions:** 
* Added a `node_runs` table to track granular state, allowing mid-execution state hydration.
* Subscribed to Redis *before* fetching the database snapshot to prevent race conditions where events are dropped between the read and the socket connection.
* Secured the WebSocket by requiring the JWT in the first incoming payload message, preventing token leakage in HTTP access logs.

## [Today's Date] PR 6: Frontend Canvas & SSR Authentication
**What we built:** Initialized the Next.js App Router frontend, secured routes using Supabase SSR middleware, and built the interactive React Flow canvas.
**Key architectural decisions:** 
* Enforced server-side JWT claim validation in `src/proxy.ts` (Next 16) rather than trusting client-side cookies.
* Implemented client-side DAG validation rules (no cycles, no self-loops) inside the React Flow `onConnect` handler to prevent bad edge creation before API submission.
* Rendered the canvas strictly on the client to prevent SSR hydration mismatches with the dark mode theme.

