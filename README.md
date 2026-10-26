# Multi-Agent Cognitive Robot System

A fully working, software-only multi-agent cognitive system: 8 specialized
"bot" agents cooperate over a real async message bus, reason about a live
simulated environment, plan and execute actions, verify outcomes, and
coordinate missions — all observable in real time through a React dashboard.
No physical hardware, and no paid API key, is required to run or demo it.

## What this actually is

- **Backend**: FastAPI + Pydantic + SQLAlchemy(async/SQLite) + a hand-rolled
  async pub/sub message bus. 8 agent roles (Perception, World Model,
  Planning, Reasoning, Critic, Mission Coordinator, Action Executor,
  Memory/Learning) run as independent asyncio tasks, each with its own
  cognitive loop: observe → retrieve memory → reason → form a goal → plan →
  critique → coordinate → execute → verify → reflect. The cycle is
  event-driven (agents react to bus messages, not a fixed turn order), so it
  can be interrupted mid-mission by a new world event.
- **Simulation engine**: a tick-based world model (entities, zones,
  obstacles, resources) with 6 independently runnable, data-driven
  scenarios (not hardcoded to any one of them — see `app/scenarios/definitions.py`,
  and new ones can be registered at runtime via `POST /api/scenarios`
  without touching any code).
- **Frontend**: React + TypeScript + Tailwind + React Flow, driving off a
  live WebSocket stream plus REST, with 5 real views: Dashboard,
  Environment/Map, Agent Control Room, Communication Center, Mission
  Inspector. Every control (start/pause/resume/step/speed/reset scenario,
  approve/reject, cancel/retry mission, export mission log, remove an
  agent) calls a real backend endpoint — nothing in the UI is decorative or
  fed by mock data.
- **No LLM required**: reasoning/planning/critique route through a
  deterministic, evidence-sensitive fallback policy by default (see
  `app/core/llm_provider.py`). Set `ANTHROPIC_API_KEY` to route through the
  Claude API instead; the system runs identically either way, and the
  no-key path is exercised by the automated test suite as a first-class
  path, not an afterthought.

## Quick start

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt
cp .env.example .env   # optional — defaults work with no edits
uvicorn app.main:app --reload --port 8000
```

This boots the 8-agent roster, initializes the SQLite database
(`cognitive_robots.db`, created automatically — no manual migration step),
and serves:

- REST API at `http://localhost:8000/api/...`
- Interactive API docs (OpenAPI/Swagger) at `http://localhost:8000/docs`
- WebSocket live event stream at `ws://localhost:8000/ws`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The dev server proxies `/api` and `/ws` to
`localhost:8000`, so the backend must be running first. Pick a scenario from
the dropdown in the control bar and click **Start scenario** to watch the
agents actually work.

### Running the automated tests

```bash
cd backend
pip install -r requirements.txt   # includes pytest + pytest-asyncio
python -m pytest app/tests/ -v
```

30 tests, all passing as of this delivery (see `backend/test_results.txt`
for the last captured run). They are real tests against real code paths,
not placeholders:

- `test_unit_core.py` — message schema validation, message bus delivery
  semantics (direct/broadcast/unknown-recipient/ack/timeout/history), world
  model upsert/conflict-detection/reset.
- `test_agents_integration.py` — drives real agents over the real message
  bus (no HTTP, no mocks): full roster registration, dynamically adding a
  custom agent, agent timeout-and-recovery, bounded replan-then-terminal-failure
  (regression test for a duplicate-replanning bug found during development —
  see "Bugs found via live execution" below), mission/task persistence
  across a simulated backend restart, and a full real end-to-end cognitive
  cycle producing a completed task with ≥5 distinct agents participating.
- `test_api_e2e.py` — drives the real FastAPI app end-to-end over HTTP and
  WebSocket: agent CRUD, scenario listing/registration, a scenario running
  to completion with the mission log correctly reconstructing the outcome,
  the resource-coordination conflict/human-approval flow, simulation
  pause/resume/reset/step correctness, a live WebSocket client receiving
  real events, and explicit confirmation the no-LLM deterministic fallback
  still produces real, inspectable decisions.

## Project layout

```
backend/
  app/
    core/        # schemas, message bus, runtime orchestrator, world model,
                  # simulation engine, persistence, LLM provider abstraction
    agents/      # the 8 agent implementations + base class
    scenarios/   # data-driven scenario definitions
    api/         # REST routes, WebSocket endpoint, request schemas
    tests/       # the 30-test automated suite described above
  main.py        # FastAPI entrypoint
  requirements.txt
  .env.example
  pytest.ini
frontend/
  src/
    api/         # REST client, WebSocket-backed global store
    components/  # shared UI + sim controls + approvals panel
    pages/       # the 5 dashboard views
  package.json
```

## Implemented features (checked against the spec)

- [x] 8 named cognitive agent roles with the specified responsibilities,
      plus a `custom` role so more agents can be added at runtime without
      rewriting the framework (`POST /api/agents`).
- [x] Event-driven cognitive cycle, not a rigid sequential loop — a new
      world event (e.g. a blocked corridor) interrupts and triggers
      replanning mid-mission.
- [x] Structured `DecisionRecord` persisted for every decision (objective,
      observations, candidate actions, selected action, rationale,
      confidence, risks, approval requirement).
- [x] Real async message bus with typed schema, direct/broadcast delivery,
      priorities, ack/timeout semantics, and a fully observable history
      (`GET /api/messages`, the live WebSocket `message` event, and the
      Communication Center's message graph + full correlation-id trace).
- [x] Live simulation engine: map, zones, entities, obstacles, resources,
      scripted events; 6 independently runnable example scenarios, plus
      the ability to register arbitrary new ones at runtime — unattended
      object monitoring is one example among several, not the whole app.
- [x] Fully functional dashboard: all 5 required views, every control
      wired to a real backend call (verified live via automated browser
      screenshots against the running backend, not just unit-tested).
- [x] SQLite persistence survives a backend restart (missions/tasks/
      messages/decisions reload from disk — see
      `test_mission_and_task_survive_a_simulated_restart`).
- [x] Human-in-the-loop approval queue for high-impact actions
      (`GET/POST /api/approvals`), demonstrated by the resource-coordination
      scenario.
- [x] Deterministic, no-API-key reasoning fallback as a first-class, tested
      path (`ANTHROPIC_API_KEY` unset by default).
- [x] Agent timeout/recovery, bounded retry + terminal failure (not an
      infinite loop), structured error reporting (never a silently
      swallowed exception — see `app/agents/base.py`'s timeout handling and
      `runtime.shutdown()`'s drained background tasks).
- [x] Graceful shutdown: every agent, the simulation tick loop, and any
      in-flight background DB writes are stopped/drained cleanly, not
      abandoned mid-write.

## Bugs found via live execution (not just code review)

Per the project's own engineering standard — implement and actually run
the system rather than stopping at a plan or a first passing test — the
following real, non-obvious bugs were found by booting the server and
watching it run, and by running the automated suite repeatedly rather than
once, then root-caused and fixed (not patched symptomatically):

1. **Method-name shadowing crash**: `MissionCoordinatorBot` had an internal
   method named `_dispatch`, which silently shadowed `BaseAgent._dispatch`
   and crashed the agent's run loop. Renamed to `_dispatch_task`.
2. **Stalled cognition**: `PerceptionBot` only handled `EVENT_NOTICE`
   messages, silently dropping `INFO_REQUEST` messages from Reasoning —
   so confidence could never climb and no task was ever created. Fixed by
   handling `INFO_REQUEST` with a genuine re-observation of live world
   state.
3. **Duplicate replanning**: both `_on_execution_result` and
   `_on_verification` could independently trigger a replan for the same
   failure, double-counting retries. Fixed by scoping `_on_verification`'s
   replan trigger to the "execution succeeded but post-condition failed"
   case only.
4. **Stale world-state reference**: `move_bot_toward` read a target
   entity's `blocked` flag from a snapshot captured before a world patch
   was applied, causing spurious first-attempt failures on every reroute.
   Fixed by re-reading the entity live from the world model.
5. **Missing state reset across scenario switches**: agents' episodic
   state (recent observations, decision counters, revision rounds) wasn't
   cleared on scenario switch or simulation reset, so a fresh run could
   reason over leftover data from a previous, unrelated scenario. Added
   `BaseAgent.reset_episodic_state()` (with subclass overrides where
   needed), called from both `reset_simulation()` and `start_scenario()`.
6. **SQLite concurrent-writer failures**: repeated automated test runs
   (not just a single run) intermittently hit `database is locked`, because
   8 concurrent agents plus the HTTP layer all write through one SQLite
   file with no WAL mode or busy timeout, and `Runtime.notify_decision`/etc.
   fired untracked, unawaited background tasks that could still be mid-write
   when a test's event loop closed. Fixed with WAL mode + `busy_timeout`,
   and by tracking every background persistence/broadcast task so
   `Runtime.shutdown()` can drain them before the DB engine or loop goes
   away.
7. **Entity label corruption**: found by watching the live map, not by code
   review — `WorldModelBot` set an entity's `label` to the free-text
   `description` of *every* observation about it, so a resource's label
   would mutate into whatever sentence last mentioned it (e.g. "Charging
   Station" becoming "Worker-2 also requests the charging station"). Fixed
   by keeping an entity's existing label stable once it has one.
8. **Overlapping entities hidden on the map**: when two entities land on
   the same grid cell (e.g. a bot moving onto the resource it's holding),
   the frontend drew them exactly on top of each other, making one
   invisible. Fixed by spreading co-located entities around a small offset
   so nothing the simulation does is hidden from the operator.

## Known limitations

- The deterministic reasoning fallback is rule-based and seeded by content
  hash, not a trained model — it is reproducible and evidence-sensitive
  (more/better observations raise confidence), but it will not generalize
  to novel scenario types the way an actual LLM call would. This is by
  design (see "No LLM required" above) and is the documented trade-off for
  running with zero paid API dependency.
- SQLite (not Postgres) is used for persistence, which is appropriate for
  this single-process demo scale but would need to move to a real
  multi-writer database for a production multi-process deployment.
- The React Flow message graph lays out the 8 fixed default agent roles in
  a fixed position map; a custom agent added at runtime renders with a
  randomized position rather than a curated layout slot.
- There is no authentication/authorization layer on the REST API or
  WebSocket — this is a local demo system, not hardened for multi-tenant
  or public deployment.
