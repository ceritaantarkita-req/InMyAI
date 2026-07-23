# Agent Runtime

Ported from InMyAI v2 during the v1/v2 merge. Backend-complete and tested;
not yet surfaced in the Next.js Workspace UI (see "Known gap" below).

## Default agents

1. Coordinator — creates a bounded plan.
2. Researcher — retrieves project evidence.
3. Worker — generates a grounded result through the selected provider.
4. Verifier — records verification evidence and task completion.

Every registered project gets these four agents seeded lazily on first read
(`GET /api/projects/{id}/agents`); no setup step required.

## Current execution model

The runtime is deliberately sequential, matching the rest of this codebase's
"one heavy engine at a time" policy for 8-16 GB laptops. A task always walks
Coordinator -> Researcher -> Worker -> Verifier in that order; every state
transition is checkpointed to `agent_events` so progress survives a restart
(`GET /api/tasks/{id}` replays the full event history). Deterministic work —
scanning, search, hashing, file operations — does not require an LLM; only
the Worker step calls a provider (Ollama if available and requested,
otherwise the same honest Mock provider used everywhere else in this app).

Run a task:

```
POST /api/tasks        {"project_id": 1, "title": "...", "instruction": "...", "provider": "auto"}
POST /api/tasks/{id}/run
GET  /api/tasks/{id}          # task + full event timeline
POST /api/tasks/{id}/cancel
```

`scripts/simulate_engine.py` exercises this end-to-end (project -> index ->
decision -> task -> run -> proposal -> apply) three times against a throwaway
database and writes `docs/qa/ENGINE_SIMULATION_3X.json`; run it after
touching agent_runtime.py, indexer.py, or services.py to catch integration
regressions the unit tests might miss.

## Adding a custom agent

Use `POST /api/agents` with:

```json
{
  "project_id": 1,
  "slug": "documentation",
  "name": "Documentation Agent",
  "role": "Updates approved project documentation",
  "provider": "auto",
  "model": "auto",
  "tools": ["search_project", "read_file", "propose_patch"]
}
```

Custom agents are stored, displayed, and permission-scoped. The Coordinator
does not yet automatically delegate to arbitrary custom agents — the task
pipeline is still the fixed four-step plan above. Documented P1 limitation,
same status as in v2.

## Known gap: no Workspace UI panel yet

The dependency-free `apps/local-ui` (served at `/app/`) has an Agents view
that lists agents, runs tasks, and shows the event timeline. The richer
Next.js Workspace (`apps/web`, the default UI) does not have an equivalent
view yet — it only gained this backend during the merge. Adding an "Agents"
tab to Workspace.tsx (mirroring the Chat/Files/Memory/Graph/Studio/Git
pattern) is the natural next step; see the merge report for details.
