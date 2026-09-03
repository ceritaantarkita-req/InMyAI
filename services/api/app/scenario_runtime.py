"""Q11.3 Piece 1 -- bounded simulation, Phase 12 rung 1: replayable
deterministic scenario (docs/plans/inmy_master_roadmap.md SS12).

A *scenario* is a versioned, named script of fixed task instructions run
against a freshly seeded, throwaway fixture project -- never one of the
user's real, mutable projects, whose content can drift between runs and
would make "replay produces the identical trace" meaningless before any
code is even wrong. Every run walks the existing agent_runtime
Coordinator -> Researcher -> Worker -> Verifier pipeline (agent_runtime.py)
with `provider` pinned to `'mock'` -- never `'auto'`/`'ollama'` -- so the
Worker step never depends on live model availability.

A canonical trace is built per step from its checkpoint state sequence, a
sha256 of its result_text, and its non-volatile verification fields; the
whole trace is hashed into one trace_hash. Replaying the same scenario
version (a fresh, independently-seeded fixture project, same script) must
reproduce the identical trace_hash -- that reproducibility across two
completely separate seedings IS the "deterministic" half of Phase 12's
first rung, and is a materially stronger claim than merely rerunning
against the same already-seeded project.

Deliberate fixture design note (found during Piece 1 discovery, before any
code was written): services.build_context() renders active decisions as
literal `D{id}` using the database's global autoincrement decision id (see
services.py). Since every scenario run seeds a brand-new fixture project,
that id is different on every run, which would make result_text diverge
across runs for a reason that has nothing to do with a real determinism
bug in this module. The built-in scenario below therefore seeds no
decisions at all -- only a memory (rendered as `{kind} / {title}: {content}`,
no id) and a file citation (rendered as `relative_path` + a content
excerpt, no id), both of which are genuinely id-free in the rendered
context and safe to compare byte-for-byte across independently-seeded
fixture projects.

Explicitly NOT in scope for Piece 1 (see the discovery doc for the full
Q11.3 piece breakdown): no Hub authority call (authorize/intent/record --
that is Piece 2/3, mirroring Q11.1/Q11.2's Sandbox/R&D authority modules),
no frontend UI (Piece 4), no stochastic/randomized scenario (Phase 12 rung
2), no *multiple* interacting agent instances sharing mutable state (rung
3 -- materially different from this module's fixed four-agent pipeline).
"""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from . import agent_runtime, services
from .config import settings
from .database import connect, transaction, utc_now
from .indexer import index_project

# Fields inside a completed task's verification_json (see agent_runtime.py's
# run_task) that are safe to fold into the canonical trace as-is: no
# timestamp, no absolute path, no subprocess-derived content. The fixture
# project below deliberately contains neither package.json nor
# pyproject.toml/pytest.ini, so agent_runtime._safe_test_command() always
# returns None for it and test_exit_code/test_output_tail never appear --
# see test_verification_trace_excludes_volatile_subprocess_fields.
_VERIFICATION_TRACE_KEYS = ('artifact_exists', 'citations_count', 'test_command', 'test_note')


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


# ---- built-in scenario: q11-3-context-recall-v1 ----
#
# Rung 1's first shipped scenario. Fixture: exactly one file and one memory
# (no decisions -- see module docstring). Three fixed instructions exercise
# memory recall, file-citation-grounded explanation, and a combined
# question pulling from both sources, so a determinism regression in either
# retrieval path would be caught.

_FIXTURE_FILE_RELATIVE_PATH = 'notes/architecture.md'
_FIXTURE_FILE_CONTENT = (
    '# Architecture\n\n'
    'InMyAI keeps a context kernel outside every model: active decisions, project memory, '
    'and indexed file citations are stored in SQLite and assembled fresh for every request. '
    'A task pipeline of four agents -- Coordinator, Researcher, Worker, Verifier -- walks a '
    'fixed sequence and checkpoints every state transition so progress survives a restart.\n'
)
_FIXTURE_MEMORY: dict[str, Any] = {
    'kind': 'note',
    'title': 'Scenario fixture purpose',
    'content': (
        'This fixture project exists only to prove Q11.3 Piece 1 scenario replay determinism. '
        'It is recreated fresh for every scenario run and is not meant for real project work.'
    ),
    'source': 'scenario-fixture',
    'confidence': 1.0,
}
_CONTEXT_RECALL_SCRIPT = [
    {
        'title': 'Recall project memory',
        'instruction': (
            'Summarize the project memory notes recorded for this project and explain what '
            'this fixture is for.'
        ),
    },
    {
        'title': 'Explain the architecture note',
        'instruction': (
            'Using the indexed project files, explain what the architecture note says about '
            'how InMyAI keeps context outside the model.'
        ),
    },
    {
        'title': 'Combine memory and files',
        'instruction': (
            'Drawing on both the project memory and the indexed architecture note, explain '
            'why this scenario is expected to produce the exact same result every time it runs.'
        ),
    },
]

BUILTIN_SCENARIOS: list[dict[str, Any]] = [
    {
        'slug': 'q11-3-context-recall-v1',
        'name': 'Context recall (memory + file citations)',
        'version': 1,
        'description': (
            'Rung 1 of Phase 12 (replayable deterministic scenario): a fixed 3-step task '
            'script against a freshly seeded fixture project (1 memory, 1 file, no decisions '
            '-- see module docstring), provider pinned to mock throughout.'
        ),
        'script': _CONTEXT_RECALL_SCRIPT,
    },
]


def ensure_builtin_scenarios() -> None:
    now = utc_now()
    with transaction() as conn:
        for scenario in BUILTIN_SCENARIOS:
            conn.execute(
                '''INSERT OR IGNORE INTO scenarios(slug,name,version,description,script_json,created_at)
                   VALUES(?,?,?,?,?,?)''',
                (scenario['slug'], scenario['name'], scenario['version'], scenario['description'],
                 _canonical_json(scenario['script']), now)
            )


def list_scenarios() -> list[dict]:
    ensure_builtin_scenarios()
    with connect() as conn:
        return [dict(r) for r in conn.execute('SELECT * FROM scenarios ORDER BY id')]


def get_scenario(slug: str) -> dict:
    ensure_builtin_scenarios()
    with connect() as conn:
        row = conn.execute('SELECT * FROM scenarios WHERE slug=?', (slug,)).fetchone()
    if not row:
        raise KeyError(f'Scenario {slug!r} not found')
    return dict(row)


def list_scenario_runs(scenario_id: int) -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            'SELECT * FROM scenario_runs WHERE scenario_id=? ORDER BY id DESC', (scenario_id,)
        )]


def scenario_run_detail(run_id: int) -> dict:
    with connect() as conn:
        row = conn.execute('SELECT * FROM scenario_runs WHERE id=?', (run_id,)).fetchone()
    if not row:
        raise KeyError(f'Scenario run {run_id} not found')
    return dict(row)


def _seed_fixture_project(scenario_slug: str) -> dict:
    """Create a brand-new, throwaway project seeded with fixed content and
    index it -- never reuses or mutates a real, user-registered project.
    Left in place after the run (no cleanup): cheap, and matches the same
    tolerance test_agent_runtime.py's own _demo_project() helper already
    has for a persistent demo project in the local SQLite DB."""
    fixture_root = settings.workspace_root / 'scenario-fixtures' / f'{scenario_slug}-{uuid.uuid4().hex[:12]}'
    file_path = fixture_root / _FIXTURE_FILE_RELATIVE_PATH
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(_FIXTURE_FILE_CONTENT, encoding='utf-8')

    project = services.create_project(f'scenario-fixture-{scenario_slug}', str(fixture_root))
    index_project(project['id'], Path(project['path']))
    services.create_memory({'project_id': project['id'], **_FIXTURE_MEMORY})
    return project


def _canonicalize_step_trace(detail: dict) -> dict:
    task = detail['task']
    states = [event['state'] for event in detail['events']]
    verification = json.loads(task.get('verification_json') or '{}')
    canonical_verification = {
        key: verification[key] for key in _VERIFICATION_TRACE_KEYS if key in verification
    }
    return {
        'title': task['title'],
        'states': states,
        'result_text_sha256': _sha256_text(task.get('result_text') or ''),
        'verification': canonical_verification,
    }


async def run_scenario(slug: str) -> dict:
    """Seed a fresh fixture project, walk the scenario's script through the
    existing agent_runtime pipeline, and persist the canonical trace."""
    scenario = get_scenario(slug)
    script = json.loads(scenario['script_json'])

    project = _seed_fixture_project(scenario['slug'])

    now = utc_now()
    with transaction() as conn:
        cur = conn.execute(
            '''INSERT INTO scenario_runs(scenario_id,fixture_project_id,status,task_ids_json,trace_json,created_at)
               VALUES(?,?,?,?,?,?)''',
            (scenario['id'], project['id'], 'running', '[]', '{}', now)
        )
        run_id = cur.lastrowid

    try:
        task_ids: list[int] = []
        step_traces: list[dict] = []
        for step in script:
            task = agent_runtime.create_task(project['id'], step['title'], step['instruction'], provider='mock')
            task_ids.append(task['id'])
            detail = await agent_runtime.run_task(task['id'])
            step_traces.append(_canonicalize_step_trace(detail))

        trace = {
            'scenario_slug': scenario['slug'],
            'scenario_version': scenario['version'],
            'steps': step_traces,
        }
        trace_hash = _sha256_text(_canonical_json(trace))

        with transaction() as conn:
            conn.execute(
                '''UPDATE scenario_runs
                   SET status=?,task_ids_json=?,trace_json=?,trace_hash=?,completed_at=? WHERE id=?''',
                ('completed', _canonical_json(task_ids), _canonical_json(trace), trace_hash, utc_now(), run_id)
            )
        return scenario_run_detail(run_id)
    except Exception as exc:
        with transaction() as conn:
            conn.execute(
                'UPDATE scenario_runs SET status=?,error=?,completed_at=? WHERE id=?',
                ('failed', str(exc), utc_now(), run_id)
            )
        raise


async def replay_scenario(slug: str, against_run_id: int | None = None) -> dict:
    """Run the scenario again (a fresh, independently-seeded fixture
    project) and compare its trace_hash against a prior completed run --
    the given run, or the most recent completed run for this scenario if
    none is given. Does NOT raise on a mismatch: a mismatch here is a
    determinism finding to report (replay_match=False in the result), not
    a security gate to fail closed on the way the Hub authority pieces in
    Q11.1/Q11.2 do."""
    scenario = get_scenario(slug)

    if against_run_id is not None:
        baseline = scenario_run_detail(against_run_id)
        if baseline['scenario_id'] != scenario['id']:
            raise ValueError('against_run_id does not belong to this scenario')
    else:
        with connect() as conn:
            row = conn.execute(
                '''SELECT * FROM scenario_runs WHERE scenario_id=? AND status='completed'
                   ORDER BY id DESC LIMIT 1''', (scenario['id'],)
            ).fetchone()
        if not row:
            raise ValueError('No completed run exists yet for this scenario to replay against -- run it first.')
        baseline = dict(row)

    new_run = await run_scenario(slug)
    match = bool(new_run['trace_hash']) and new_run['trace_hash'] == baseline['trace_hash']

    with transaction() as conn:
        conn.execute(
            'UPDATE scenario_runs SET replay_of_run_id=?,replay_match=? WHERE id=?',
            (baseline['id'], 1 if match else 0, new_run['id'])
        )
    return scenario_run_detail(new_run['id'])
