from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path
from typing import Any

from .database import connect, transaction, utc_now
from .providers import MockProvider, OllamaProvider, choose_ollama_model, get_ollama_status
from . import services

ALLOWED_STATES = {
    'queued','planning','retrieving','running_tool','waiting_approval',
    'verifying','completed','failed','cancelled'
}

DEFAULT_AGENTS = [
    ('coordinator','Coordinator','Plans tasks and delegates work','auto','auto'),
    ('researcher','Research Agent','Scans files and gathers evidence','auto','auto'),
    ('worker','Worker Agent','Drafts edits and creates artifacts','auto','auto'),
    ('verifier','Verifier Agent','Checks outputs, tests, and constraints','auto','auto'),
]


def ensure_default_agents(project_id: int) -> None:
    now = utc_now()
    with transaction() as conn:
        for slug, name, role, provider, model in DEFAULT_AGENTS:
            conn.execute(
                '''INSERT OR IGNORE INTO agents(project_id,slug,name,role,provider,model,tools_json,status,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)''',
                (project_id, slug, name, role, provider, model,
                 json.dumps(['search_project','read_file','propose_patch','run_tests']), 'idle', now, now)
            )


def list_agents(project_id: int) -> list[dict[str, Any]]:
    ensure_default_agents(project_id)
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            'SELECT * FROM agents WHERE project_id=? ORDER BY id', (project_id,)
        )]


def create_agent(data: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    tools = data.get('tools') or ['search_project','read_file']
    with transaction() as conn:
        cur = conn.execute(
            '''INSERT INTO agents(project_id,slug,name,role,provider,model,tools_json,status,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)''',
            (data['project_id'], data['slug'], data['name'], data['role'], data.get('provider','auto'),
             data.get('model','auto'), json.dumps(tools), 'idle', now, now)
        )
        row = conn.execute('SELECT * FROM agents WHERE id=?', (cur.lastrowid,)).fetchone()
    return dict(row)


def _event(conn, task_id: int, agent_id: int | None, state: str, message: str, data: dict | None = None) -> None:
    if state not in ALLOWED_STATES:
        raise ValueError(f'Invalid task state: {state}')
    conn.execute(
        'INSERT INTO agent_events(task_id,agent_id,state,message,data_json,created_at) VALUES(?,?,?,?,?,?)',
        (task_id, agent_id, state, message, json.dumps(data or {}), utc_now())
    )
    conn.execute('UPDATE tasks SET status=?,updated_at=? WHERE id=?', (state, utc_now(), task_id))
    if agent_id:
        agent_status = 'idle' if state in {'completed','failed','cancelled','waiting_approval'} else 'working'
        conn.execute('UPDATE agents SET status=?,updated_at=? WHERE id=?', (agent_status, utc_now(), agent_id))


def create_task(project_id: int, title: str, instruction: str, provider: str = 'auto') -> dict:
    ensure_default_agents(project_id)
    now = utc_now()
    with transaction() as conn:
        cur = conn.execute(
            '''INSERT INTO tasks(project_id,title,instruction,status,provider,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?)''',
            (project_id, title, instruction, 'queued', provider, now, now)
        )
        task_id = cur.lastrowid
        _event(conn, task_id, None, 'queued', 'Task created')
        row = conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
    return dict(row)


def list_tasks(project_id: int) -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            'SELECT * FROM tasks WHERE project_id=? ORDER BY created_at DESC', (project_id,)
        )]


def task_detail(task_id: int) -> dict:
    with connect() as conn:
        task = conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not task:
            raise KeyError('Task not found')
        events = [dict(r) for r in conn.execute(
            'SELECT * FROM agent_events WHERE task_id=? ORDER BY id', (task_id,)
        )]
    return {'task': dict(task), 'events': events}


def _choose_agent(project_id: int, slug: str) -> dict:
    ensure_default_agents(project_id)
    with connect() as conn:
        row = conn.execute('SELECT * FROM agents WHERE project_id=? AND slug=?', (project_id, slug)).fetchone()
    if not row:
        raise KeyError(f'Agent {slug} not found')
    return dict(row)


def _safe_test_command(project_path: Path) -> list[str] | None:
    if (project_path / 'package.json').exists():
        return ['npm', 'test', '--', '--runInBand']
    if (project_path / 'pyproject.toml').exists() or (project_path / 'pytest.ini').exists():
        return ['python', '-m', 'pytest', '-q']
    return None


async def run_task(task_id: int) -> dict:
    with connect() as conn:
        task_row = conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
    if not task_row:
        raise KeyError('Task not found')
    task = dict(task_row)
    if task['status'] in {'completed','cancelled'}:
        return task_detail(task_id)

    project_id = task['project_id']
    project = services.get_project(project_id)
    coordinator = _choose_agent(project_id, 'coordinator')
    researcher = _choose_agent(project_id, 'researcher')
    worker = _choose_agent(project_id, 'worker')
    verifier = _choose_agent(project_id, 'verifier')

    try:
        with transaction() as conn:
            _event(conn, task_id, coordinator['id'], 'planning', 'Coordinator is creating a bounded execution plan')
        instruction = task['instruction']
        plan = [
            {'agent':'researcher','action':'retrieve_context'},
            {'agent':'worker','action':'produce_result'},
            {'agent':'verifier','action':'verify_result'},
        ]
        with transaction() as conn:
            conn.execute('UPDATE tasks SET plan_json=? WHERE id=?', (json.dumps(plan), task_id))

        with transaction() as conn:
            _event(conn, task_id, researcher['id'], 'retrieving', 'Research Agent is retrieving project evidence')
        context, citations = services.build_context(project_id, instruction, max_chars=10000)

        with transaction() as conn:
            _event(conn, task_id, worker['id'], 'running_tool', 'Worker Agent is generating a grounded result', {'citations': citations})

        ollama = await get_ollama_status()
        requested_provider = task.get('provider') or 'auto'
        messages = [
            {'role':'system','content':(
                'You are the InMyAI Worker Agent. Use only supplied context. '
                'Do not claim tools ran unless tool results are included. '
                'Return a concise work result and explicitly label suggestions.\n\n' + context
            )},
            {'role':'user','content':instruction}
        ]
        if requested_provider in {'auto','ollama'} and ollama.get('available'):
            model = choose_ollama_model('coding', ollama.get('models', []), None)
            result = await OllamaProvider().chat(messages, model)
        else:
            result = await MockProvider().chat(messages)

        artifact_dir = Path(project['path']) / '.inmyai' / 'artifacts'
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / f'task-{task_id}-result.md'
        artifact_path.write_text(result.text, encoding='utf-8')

        with transaction() as conn:
            conn.execute('UPDATE tasks SET result_text=?,artifact_path=? WHERE id=?', (result.text, str(artifact_path), task_id))
            _event(conn, task_id, verifier['id'], 'verifying', 'Verifier Agent is checking result and project state')

        verification: dict[str, Any] = {'artifact_exists': artifact_path.exists(), 'citations_count': len(citations)}
        command = _safe_test_command(Path(project['path']))
        if command:
            try:
                proc = subprocess.run(command, cwd=project['path'], capture_output=True, text=True, timeout=120)
                verification['test_command'] = ' '.join(shlex.quote(x) for x in command)
                verification['test_exit_code'] = proc.returncode
                verification['test_output_tail'] = (proc.stdout + proc.stderr)[-4000:]
            except Exception as exc:
                verification['test_error'] = str(exc)
        else:
            verification['test_command'] = None
            verification['test_note'] = 'No supported project test command detected.'

        with transaction() as conn:
            conn.execute('UPDATE tasks SET verification_json=? WHERE id=?', (json.dumps(verification), task_id))
            _event(conn, task_id, verifier['id'], 'completed', 'Task completed and checkpointed', verification)
        return task_detail(task_id)
    except Exception as exc:
        with transaction() as conn:
            _event(conn, task_id, coordinator['id'], 'failed', f'Task failed safely: {exc}')
        raise


def cancel_task(task_id: int) -> dict:
    with transaction() as conn:
        row = conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not row:
            raise KeyError('Task not found')
        _event(conn, task_id, None, 'cancelled', 'Task cancelled by user')
    return task_detail(task_id)
