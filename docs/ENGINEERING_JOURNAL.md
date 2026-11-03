## PR 1: Async Database Scaffolding
**What we built:** Initialized the FastAPI application structure and SQLAlchemy 2.0 ORM models for `workflows`, `nodes`, and `executions`. 
**Key architectural decision:** Configured SQLAlchemy to use `NullPool` and disabled `asyncpg` statement caching to support Supavisor in transaction mode (Port 6543). This prevents "prepared statement already exists" errors when the pooler swaps our underlying Postgres connection.

## PR 2: RabbitMQ Message Broker & Async Workers
**What we built:** Integrated CloudAMQP RabbitMQ using `aio-pika` to decouple the API gateway from long-running agent tasks. 
**Key architectural decisions:** 
* Implemented a connection pool and channel multiplexing to prevent socket exhaustion.
* Configured a Dead-Letter Queue (`tracemesh_tasks.dead`) to capture malformed payloads without crashing the worker loop.
* Implemented graceful shutdown (handling `SIGINT`/`SIGTERM`) so the worker finishes active tasks before terminating, ensuring no lost work during deployments: a message is acknowledged only after its run finishes, so any run interrupted mid-flight is redelivered by RabbitMQ and re-run from the start.

## PR 3: Multi-Tenancy & Execution Engine
**What we built:** Enforced strict multi-tenancy using Supabase JWT authentication and wired the FastAPI DAG validation to the asynchronous RabbitMQ worker.
**Key architectural decisions:** 
* Implemented zero-trust endpoints; verifying the `aud=authenticated` claim and extracting the `sub` (user_id) blocks anonymous and service-role JWT forgeries.
* Prevented IDOR (Insecure Direct Object Reference) by returning 404s instead of 403s for cross-tenant data requests.
* Designed the worker with strict state-machine transitions, ensuring duplicate RabbitMQ deliveries cannot overwrite `COMPLETED` executions.

## PR 4: Schema Refinement & Redis Telemetry
**What we built:** Migrated workflow dependencies to a relational `edges` table and implemented real-time execution telemetry via Upstash Redis.
**Key architectural decisions:** 
* Pushed cross-tenant constraints down to the PostgreSQL database engine for the `edges` table.
* Implemented fail-open telemetry with 2-second timeouts, ensuring a Redis outage degrades observability without crashing the execution worker.
* Added `simulate_failure` injection to easily demonstrate Dead-Letter Queue and error state handling in the UI.

## PR 5: WebSocket Telemetry & State Hydration
**What we built:** Implemented `/ws/executions/{execution_id}` to stream live trace events from Redis to the client.
**Key architectural decisions:** 
* Added a `node_runs` table to track granular state, allowing mid-execution state hydration.
* Subscribed to Redis *before* fetching the database snapshot to prevent race conditions where events are dropped between the read and the socket connection.
* Secured the WebSocket by requiring the JWT in the first incoming payload message, preventing token leakage in HTTP access logs.

## PR 6: Frontend Canvas & SSR Authentication
**What we built:** Initialized the Next.js App Router frontend, secured routes using Supabase SSR middleware, and built the interactive React Flow canvas.
**Key architectural decisions:** 
* Enforced server-side JWT claim validation in `src/proxy.ts` (Next 16) rather than trusting client-side cookies.
* Implemented client-side DAG validation rules (no cycles, no self-loops) inside the React Flow `onConnect` handler to prevent bad edge creation before API submission.
* Rendered the canvas strictly on the client to prevent SSR hydration mismatches with the dark mode theme.

## PR 7: API & WebSocket Integration
**What we built:** Wired the React Flow canvas to the FastAPI backend, implementing delta-saves and real-time execution telemetry.
**Key architectural decisions:** 
* Decoupled save logic from execution logic, forcing a state sync before dispatching the RabbitMQ task to ensure the worker acts on the exact visual state.
* Managed client-side UUID generation mapped to server-side UUID generation during partial saves.
* Handled WebSocket authentication via initial payload message to securely authorize the streaming telemetry session.

## PR 8: Automated Integration Testing
**What we built:** Developed a 117-test Pytest suite and a GitHub Actions CI pipeline.
**Key architectural decisions:** 
* Tested against a live PostgreSQL container to validate `JSONB`.
* Mocked RabbitMQ (`aio_pika`) and Redis (`fakeredis`) to ensure fast, deterministic test execution.

## PR 9 (Backend): Security Audit & RLS Hardening
**What we built:** Enabled Postgres Row-Level Security (RLS) on all tables to lock down the public Supabase REST API, and updated schema defaults.
**Key architectural decisions:** 
* Blocked Supabase REST API data leaks by enabling RLS and revoking public schema grants from the `anon` and `authenticated` roles.
* Kept tenant isolation in the application layer: the FastAPI backend connects as the table owner, which bypasses RLS, so every query is scoped to the authenticated `user_id` from the verified JWT.
* Standardized workflow creation with database-level 'Untitled Workflow' defaults to simplify the frontend UI layer.

## PR 9 (Frontend): Auth UI & Dashboard Management
**What we built:** Implemented secure Next.js authentication flows and workflow CRUD controls.
**Key architectural decisions:**
* Integrated Supabase native Auth with email OTP verification and password reset routes.
* Added dashboard UI controls for renaming and deleting workflows, mapping to the hardened FastAPI endpoints.

## PR 10: Inline Node Renaming
**What we built:** Made each node's title on the React Flow canvas an editable text field.
**Key architectural decisions:**
* Wrote edits straight into the node's `data.label` through `useReactFlow().setNodes`, so renames ride the existing delta save with no new API surface.
* Marked the input `nodrag nopan` so selecting text doesn't drag the node or zoom the canvas, and fell back to a per-type default name when a title is left blank.

## PR 11: Infrastructure as Code
**What we built:** Added a `render.yaml` Blueprint describing the Render deployment.
**Key architectural decision:** Kept deployment configuration in version control, with secrets declared as `sync: false` so their values live only in the Render dashboard.

## PR 12: Modular Monolith
**What we built:** Merged the RabbitMQ worker into the FastAPI process, so the whole backend runs in one container, and one terminal locally.
**Key architectural decisions:**
* Started the consumer with `asyncio.create_task()` inside the FastAPI lifespan, sharing uvicorn's event loop. Render's free tier has no background workers, so this saves the cost of a second paid service.
* Made startup wait until the consumer is registered with RabbitMQ, failing the deploy otherwise, so the API never accepts executions that nothing will run.
* Drained in-flight executions for up to 20 seconds on SIGTERM (inside Render's 30-second window), then cancelled the rest unacked so RabbitMQ redelivers them and the idempotent claim re-runs them.
* Kept the consumer on its own AMQP connection, separate from the publisher pool, and kept `python -m app.worker` working, so the consumer can be split back out without code changes.
* Moved `alembic upgrade head` into the build command, because Render's pre-deploy commands are paid-only.

## PR 13: Tolerant CORS Parsing & Startup Diagnostics
**What we built:** Hardened the `CORS_ORIGINS` parsing in the settings layer that feeds FastAPI's `CORSMiddleware`, and expanded the Pytest suite to 140 tests.
**Key architectural decisions:**
* Replaced strict JSON-only parsing with tolerant parsing (accepting comma-separated strings or JSON lists, and stripping whitespace and trailing slashes). Starlette still matches each browser origin exactly, so normalising at config load prevents silent `400 Disallowed CORS origin` preflight failures caused by malformed cloud environment variables.
* Implemented explicit startup logging (`CORS allowed origins: [...]`) so the parsed configuration is immediately verifiable in the Render deployment logs.

## PR 14: Documentation & Execution Boundaries
**What we built:** Documented the system's target AI/ML use case (Automated Codebase Onboarding & RAG Pipeline) and established strict execution boundaries in the architecture documentation.
**Key architectural decisions:**
* Designed the target DAG workflow mapping trigger, agent, and webhook nodes to real-world operations (AST parsing, Claude Sonnet summarization, pgvector upserting).
* Maintained strict engineering honesty for technical interviews by explicitly documenting the boundary between the *completed orchestration engine* (queueing, state management, WebSockets) and the *simulated execution layer*.
* Logged true parallel branch execution (Y-branches) and external LLM/HTTP calls as explicit roadmap constraints rather than overclaiming current capabilities.
