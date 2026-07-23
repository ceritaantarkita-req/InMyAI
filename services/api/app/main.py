from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import connect, migrate, transaction, utc_now
from .git_tools import git_blame, git_branches, git_diff, git_log, git_status
from .indexer import index_project
from .providers import MockProvider, OllamaProvider, ProviderResult, choose_ollama_model, get_ollama_install_state, get_ollama_status
from .image_provider import generate_with_comfyui, generate_with_diffusers
from .router_engine import route, to_dict
from .security import BLOCKED_FILENAMES, looks_like_project, resolve_browsable_path, safe_join
from . import terminal as terminal_module
from .schemas import (
    AgentCreate, AllowedRootCreate, ChatRequest, DecisionCreate, ImageRequest, MemoryCreate, OCRRequest,
    ProjectCreate, SearchRequest, TaskCreate, WriteProposalCreate
)
from . import services
from . import agent_runtime

@asynccontextmanager
async def lifespan(_app: FastAPI):
    migrate()
    # Restores allowed roots added through the Settings UI in a previous
    # run - they live in the `allowed_roots` table, not `.env`, so the
    # in-memory `settings.allowed_roots` needs to be rebuilt from the DB on
    # every process start.
    services.sync_allowed_roots()
    services.reset_interrupted_indexing()
    yield


app = FastAPI(title='InMyAI Local API', version='0.1.0', lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://127.0.0.1:3000', 'http://localhost:3000'],
    allow_origin_regex=r'^http://(10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+|192\.168\.\d+\.\d+):3000$',
    allow_credentials=False,
    allow_methods=['*'],
    allow_headers=['*']
)

# Dependency-free static UI (plain HTML/JS/CSS, no Node/npm required) served
# straight from the API process. Optional: only mounted if the directory
# exists, so the API still runs standalone in environments that only ship the
# apps/web (Next.js) frontend separately.
_local_ui = (Path(__file__).resolve().parents[3] / 'apps' / 'local-ui').resolve()
if _local_ui.exists():
    app.mount('/app', StaticFiles(directory=str(_local_ui), html=True), name='local-ui')


@app.get('/api/health')
def health() -> dict:
    return {'ok': True, 'app': 'InMyAI', 'version': '0.1.0', 'database': str(settings.database_path)}


@app.get('/api/hardware')
def hardware() -> dict:
    return services.hardware_snapshot()


@app.get('/api/models/status')
async def models_status() -> dict:
    return {'ollama': await get_ollama_status(), 'configured_provider': settings.provider}


@app.get('/api/models/onboarding')
async def models_onboarding() -> dict:
    """Single state object the onboarding wizard renders from.

    `phase` tells the UI which step to show:
      download_ollama | start_ollama | pull_model | ready
    `recommended` lists registry profiles matching the device's hardware class,
    each with a ready-to-copy `pull_command`.
    """
    from .model_registry import recommend_for_hardware

    state = await get_ollama_install_state()
    snapshot = services.hardware_snapshot()
    hardware_profile = snapshot['profile']

    installed = state['installed']
    running = state['running']
    models = state.get('models', [])
    if not installed:
        phase = 'download_ollama'
    elif not running:
        phase = 'start_ollama'
    elif not models:
        phase = 'pull_model'
    else:
        phase = 'ready'

    recommended = [
        {
            'id': p.id,
            'model': p.model,
            'task_types': p.task_types,
            'peak_ram_mb': p.peak_ram_mb,
            'pull_command': f'ollama pull {p.model}',
            'notes': p.notes,
        }
        for p in recommend_for_hardware(hardware_profile)
    ]
    return {
        'phase': phase,
        'installed': installed,
        'version': state.get('version'),
        'running': running,
        'models': [{'name': m.get('name', '')} for m in models],
        'hardware_profile': hardware_profile,
        'recommended': recommended,
    }


@app.get('/api/projects')
def projects() -> list[dict]:
    return services.list_projects()


_BROWSE_ENTRY_LIMIT = 1000


@app.get('/api/browse')
def browse(path: str = Query(...)) -> dict:
    """Read-only directory listing for the Explorer tab's mind-map.

    Intentionally not subject to INMYAI_ALLOWED_ROOTS - see
    security.resolve_browsable_path for why. Lists folder AND file names
    (never file contents) so a user can visually navigate their disk to find
    a project before registering it with POST /api/projects, which still
    enforces the normal allowed-roots policy.
    """
    try:
        target = resolve_browsable_path(path)
        raw_entries = sorted(
            target.iterdir(),
            key=lambda item: (not item.is_dir(), item.name.lower())
        )
        entries = []
        truncated = False
        for child in raw_entries:
            if len(entries) >= _BROWSE_ENTRY_LIMIT:
                truncated = True
                break
            if child.name.lower() in BLOCKED_FILENAMES or child.name.lower().startswith('.env'):
                continue
            try:
                is_dir = child.is_dir()
            except OSError:
                continue
            entries.append({
                'name': child.name,
                'path': str(child),
                'is_dir': is_dir,
                'is_project': is_dir and looks_like_project(child),
            })
        parent = str(target.parent) if target.parent != target else None
        return {'path': str(target), 'parent': parent, 'entries': entries, 'truncated': truncated}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=f'Permission denied: {exc}') from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.websocket('/ws/terminal')
async def terminal_ws(websocket: WebSocket, path: str = '.') -> None:
    """Interactive local terminal (real PTY, see terminal.py) rooted at
    `path` if it resolves to a real directory, else the API process's own
    cwd. Not subject to INMYAI_ALLOWED_ROOTS, same reasoning as /api/browse:
    a local terminal already has, by definition, at least as much access as
    your OS user account - restricting its starting directory would not add
    real protection, only friction.
    """
    try:
        cwd = str(resolve_browsable_path(path))
    except ValueError:
        cwd = str(Path.cwd())
    await terminal_module.run_terminal_session(websocket, cwd=cwd)


@app.get('/api/settings/allowed-roots')
def get_allowed_roots() -> list[dict]:
    """Every folder currently accepted by POST /api/projects, from all three
    sources (see services.list_allowed_roots): the workspace root, whatever
    INMYAI_ALLOWED_ROOTS says in .env (read-only here), and whatever has
    been added at runtime through this endpoint (deletable). Lets the
    Settings UI show and manage this without anyone touching .env by hand.
    """
    return services.list_allowed_roots()


@app.post('/api/settings/allowed-roots')
def add_allowed_root(payload: AllowedRootCreate) -> dict:
    try:
        return services.add_allowed_root(payload.path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete('/api/settings/allowed-roots/{root_id}')
def delete_allowed_root(root_id: int) -> dict:
    services.remove_allowed_root(root_id)
    return {'ok': True}


@app.get('/api/projects/scope')
def project_scope(path: str = Query(...)) -> dict:
    """Pre-registration guardrail classification for a folder path.

    Used by both registration flows (Settings modal and Explorer 'Open as
    project') to decide whether to show a confirmation dialog (dangerous) or a
    non-blocking notice (very large folder). Does not mutate anything.
    """
    return services.classify_folder_scope(path)


@app.post('/api/projects')
def create_project(payload: ProjectCreate, background_tasks: BackgroundTasks) -> dict:
    try:
        project = services.create_project(payload.name, payload.path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(index_project, project['id'], Path(project['path']))
    return project


@app.post('/api/projects/{project_id}/index')
def index(project_id: int) -> dict:
    try:
        project = services.get_project(project_id)
        status = services.get_index_status(project_id)
        if status['status'] == 'indexing':
            raise HTTPException(status_code=409, detail='Indexing is already in progress.')
        return index_project(project_id, Path(project['path']))
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get('/api/projects/{project_id}/index-status')
def index_status(project_id: int) -> dict:
    try:
        return services.get_index_status(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get('/api/projects/{project_id}/files')
def files(project_id: int) -> list[dict]:
    return services.list_files(project_id)


@app.get('/api/projects/{project_id}/file')
def file(project_id: int, path: str = Query(...)) -> dict:
    try:
        return services.read_project_file(project_id, path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post('/api/search')
def search(payload: SearchRequest) -> dict:
    return {'results': services.search_project(payload.project_id, payload.query, payload.limit)}


@app.get('/api/projects/{project_id}/memories')
def memories(project_id: int) -> list[dict]:
    return services.list_memories(project_id)


@app.post('/api/memories')
def create_memory(payload: MemoryCreate) -> dict:
    return services.create_memory(payload.model_dump())


@app.get('/api/projects/{project_id}/decisions')
def decisions(project_id: int) -> list[dict]:
    return services.list_decisions(project_id)


@app.post('/api/decisions')
def create_decision(payload: DecisionCreate) -> dict:
    try:
        return services.create_decision(payload.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get('/api/projects/{project_id}/graph')
def graph(project_id: int, node: str = '') -> dict:
    if node:
        return services.graph_query(project_id, node)
    return {'relations': services.list_relations(project_id)}


def _git_project_path(project_id: int) -> Path:
    """Resolve a registered project's path for git operations. Raises KeyError/HTTPException."""
    project = services.get_project(project_id)
    return Path(project['path']).resolve()


@app.get('/api/projects/{project_id}/git/status')
def git_status_endpoint(project_id: int) -> dict:
    try:
        return git_status(_git_project_path(project_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get('/api/projects/{project_id}/git/log')
def git_log_endpoint(project_id: int, limit: int = Query(50, ge=1, le=500)) -> dict:
    try:
        return {'entries': git_log(_git_project_path(project_id), limit=limit)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get('/api/projects/{project_id}/git/branches')
def git_branches_endpoint(project_id: int) -> dict:
    try:
        return git_branches(_git_project_path(project_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get('/api/projects/{project_id}/git/diff')
def git_diff_endpoint(project_id: int, path: str = Query('')) -> dict:
    try:
        project_path = _git_project_path(project_id)
        # Validate an optional path against the project root before handing to git.
        relative = safe_join(project_path, path, must_exist=False).relative_to(project_path).as_posix() if path else None
        return {'diff': git_diff(project_path, relative)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get('/api/projects/{project_id}/git/blame')
def git_blame_endpoint(project_id: int, path: str = Query(...)) -> dict:
    try:
        project_path = _git_project_path(project_id)
        relative = safe_join(project_path, path, must_exist=False).relative_to(project_path).as_posix()
        return {'lines': git_blame(project_path, relative)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get('/api/projects/{project_id}/proposals')
def proposals(project_id: int) -> list[dict]:
    return services.list_write_proposals(project_id)


@app.post('/api/proposals')
def create_proposal(payload: WriteProposalCreate) -> dict:
    try:
        return services.create_write_proposal(payload.project_id, payload.relative_path, payload.proposed_content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post('/api/proposals/{proposal_id}/apply')
def apply_proposal(proposal_id: int) -> dict:
    try:
        return services.apply_write_proposal(proposal_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post('/api/proposals/{proposal_id}/reject')
def reject_proposal(proposal_id: int) -> dict:
    try:
        return services.reject_write_proposal(proposal_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post('/api/ocr')
def ocr(payload: OCRRequest) -> dict:
    try:
        return services.run_ocr(payload.project_id, payload.relative_path, payload.language)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post('/api/images/generate')
async def generate_image(payload: ImageRequest) -> dict:
    snapshot = services.hardware_snapshot()
    if not snapshot['guard']['allow_new_engine']:
        raise HTTPException(status_code=503, detail='Available RAM is below the 1.5 GB safety threshold.')
    if payload.provider == 'simulator':
        return services.simulate_image(payload.project_id, payload.prompt, payload.width, payload.height, payload.seed)
    # Both real backends are heavy; best-effort release the chat model first.
    try:
        await OllamaProvider().unload()
    except Exception:
        pass
    try:
        if payload.provider == 'diffusers':
            return generate_with_diffusers(
                payload.project_id, payload.prompt, payload.negative_prompt,
                payload.width, payload.height, payload.steps, payload.seed
            )
        return await generate_with_comfyui(
            payload.project_id, payload.prompt, payload.negative_prompt,
            payload.width, payload.height, payload.steps, payload.seed
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def run_local_tool_decision(decision, message: str, project_id: int) -> ProviderResult:
    """Honor the router's local-tool decisions instead of silently using Mock.

    OCR with a named, present file is actually executed (Tesseract/pypdf). OCR
    without a usable file, and diff/image tasks, return honest guidance pointing
    the user at the right surface rather than pretending an LLM answered.
    """
    if decision.task == 'ocr':
        reference = services.extract_file_reference(message)
        if not reference:
            return ProviderResult(
                text=(
                    'OCR needs a specific file. Mention a supported path in your '
                    'message, for example "ocr invoice.png", or open the Studio tab '
                    'and pick a PDF or image to extract text from.'
                ),
                model='local-tool:ocr',
                provider='local-tool',
            )
        project = services.get_project(project_id)
        try:
            path = services.safe_join(Path(project['path']), reference)
            if not path.exists():
                raise FileNotFoundError(reference)
            ocr_result = services.run_ocr(project_id, reference)
            extracted = ocr_result['text'].strip() or '(no text could be extracted)'
            text = (
                f"OCR result for {reference} ({ocr_result['engine']}):\n\n"
                f"{extracted}\n\n"
                "This text was extracted by a deterministic tool, not generated by a model."
            )
            return ProviderResult(text=text, model=f"local-tool:ocr:{ocr_result['engine']}", provider='local-tool')
        except FileNotFoundError:
            return ProviderResult(
                text=(
                    f"I could not find '{reference}' in this project. "
                    'Check the path, index the project, or pick the file from the Studio tab.'
                ),
                model='local-tool:ocr',
                provider='local-tool',
            )
        except ValueError as exc:
            # safe_join policy rejection (traversal / blocked path)
            return ProviderResult(
                text=f"I can't OCR that path: {exc}",
                model='local-tool:ocr',
                provider='local-tool',
            )
        except RuntimeError as exc:
            # e.g. Tesseract not installed / OCR unsupported format
            return ProviderResult(
                text=f"OCR could not run: {exc}",
                model='local-tool:ocr',
                provider='local-tool',
            )

    if decision.task == 'diff':
        return ProviderResult(
            text=(
                'File comparison uses a deterministic diff. Open the Files tab, '
                'edit a file, and create a proposal to see a staged unified diff '
                'before applying changes.'
            ),
            model='local-tool:diff',
            provider='local-tool',
        )

    if decision.task == 'image':
        return ProviderResult(
            text=(
                'Image generation runs in the Studio tab. The core workflow '
                'simulator verifies the job; configure ComfyUI or the optional '
                'Diffusers plugin for real local generation.'
            ),
            model='local-tool:image',
            provider='local-tool',
        )

    # Defensive: unknown local-tool task — return generic guidance.
    return ProviderResult(
        text='This task is handled by a local tool. See the relevant workspace tab.',
        model='local-tool',
        provider='local-tool',
    )


@app.post('/api/chat')
async def chat(payload: ChatRequest) -> dict:
    ollama = await get_ollama_status()
    decision = route(payload.message, payload.provider, ollama['available'])
    context, citations = services.build_context(payload.project_id, payload.message, max_chars=decision.context_limit * 3)
    now = utc_now()
    with transaction() as conn:
        conversation_id = payload.conversation_id
        if not conversation_id:
            cur = conn.execute(
                'INSERT INTO conversations(project_id,title,created_at,updated_at) VALUES(?,?,?,?)',
                (payload.project_id, payload.message[:80], now, now)
            )
            conversation_id = cur.lastrowid
        conn.execute(
            'INSERT INTO messages(conversation_id,role,content,created_at) VALUES(?,?,?,?)',
            (conversation_id, 'user', payload.message, now)
        )

    system_message = (
        'You are InMyAI, a local-first project assistant. Use only the supplied project context. '
        'Distinguish verified facts, inferred relationships, and suggestions. Never claim a file was changed unless a tool result proves it.\n\n'
        + context
    )
    messages = [{'role': 'system', 'content': system_message}, {'role': 'user', 'content': payload.message}]
    try:
        if decision.provider == 'local-tool':
            result = run_local_tool_decision(decision, payload.message, payload.project_id)
        elif decision.provider == 'ollama':
            selected_model = choose_ollama_model(decision.task, ollama.get('models', []), payload.model)
            result = await OllamaProvider().chat(messages, selected_model)
        else:
            result = await MockProvider().chat(messages, payload.model)
    except Exception as exc:
        result = await MockProvider().chat(messages, payload.model)
        decision.provider = 'mock'
        decision.reason = f'Ollama failed safely: {exc}'

    with transaction() as conn:
        conn.execute(
            '''INSERT INTO messages(conversation_id,role,content,citations_json,router_json,created_at)
               VALUES(?,?,?,?,?,?)''',
            (conversation_id, 'assistant', result.text, json.dumps(citations), json.dumps(to_dict(decision)), utc_now())
        )
        conn.execute('UPDATE conversations SET updated_at=? WHERE id=?', (utc_now(), conversation_id))
    return {
        'conversation_id': conversation_id,
        'answer': result.text,
        'citations': citations,
        'route': to_dict(decision),
        'model': result.model,
        'provider': result.provider
    }


@app.get('/api/conversations/{conversation_id}')
def conversation(conversation_id: int) -> dict:
    with connect() as conn:
        conversation_row = conn.execute('SELECT * FROM conversations WHERE id=?', (conversation_id,)).fetchone()
        if not conversation_row:
            raise HTTPException(status_code=404, detail='Conversation not found')
        messages = [dict(row) for row in conn.execute(
            'SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at', (conversation_id,)
        )]
    return {'conversation': dict(conversation_row), 'messages': messages}


@app.get('/api/generated-file')
def generated_file(project_id: int, path: str = Query(...)):
    try:
        project = services.get_project(project_id)
        file_path = Path(project['path']) / path
        file_path = file_path.resolve()
        root = (Path(project['path']) / '.inmyai' / 'generated').resolve()
        if root not in file_path.parents:
            raise ValueError('Only generated artifacts can be downloaded from this route.')
        return FileResponse(file_path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get('/api/projects/{project_id}/agents')
def agents(project_id: int) -> list[dict]:
    return agent_runtime.list_agents(project_id)


@app.post('/api/agents')
def create_agent(payload: AgentCreate) -> dict:
    try:
        return agent_runtime.create_agent(payload.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get('/api/projects/{project_id}/tasks')
def tasks(project_id: int) -> list[dict]:
    return agent_runtime.list_tasks(project_id)


@app.post('/api/tasks')
def create_task(payload: TaskCreate) -> dict:
    try:
        return agent_runtime.create_task(payload.project_id, payload.title, payload.instruction, payload.provider)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get('/api/tasks/{task_id}')
def task_detail(task_id: int) -> dict:
    try:
        return agent_runtime.task_detail(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post('/api/tasks/{task_id}/run')
async def run_task(task_id: int) -> dict:
    try:
        return await agent_runtime.run_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post('/api/tasks/{task_id}/cancel')
def cancel_task(task_id: int) -> dict:
    try:
        return agent_runtime.cancel_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

