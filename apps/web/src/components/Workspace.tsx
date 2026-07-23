'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import {
  Bot, BrainCircuit, Check, Code2, Copy, Download, ExternalLink, FileCode2,
  FileText, FolderOpen, GitBranch, HardDrive, ImageIcon, Laptop, Loader2,
  MemoryStick, MessageSquareText, Network, PlayCircle, Plus, RefreshCw, Save,
  Search, Send, Settings, ShieldCheck, Sparkles, StopCircle, TerminalSquare,
  Users, Workflow, X
} from './Icons'
import { api, API_URL } from '@/lib/api'
import { conversationStorageKey, parseConversationResponse } from '@/lib/chat-history'
import { dismissOnboarding, shouldShowWizard } from '@/lib/onboarding'
import type { Agent, ChatResponse, Decision, Hardware, IndexedFile, Memory, OnboardingState, Project, Proposal, Relation, Task, TaskDetail } from '@/lib/types'

type View = 'chat' | 'files' | 'memory' | 'graph' | 'studio' | 'git' | 'agents'
type ChatMessage = { role: 'user' | 'assistant'; content: string; route?: ChatResponse['route']; citations?: ChatResponse['citations'] }

const nav: { id: View; label: string; icon: typeof Bot }[] = [
  { id: 'chat', label: 'Chat', icon: MessageSquareText },
  { id: 'files', label: 'Files', icon: FileCode2 },
  { id: 'memory', label: 'Memory', icon: BrainCircuit },
  { id: 'graph', label: 'Graph', icon: Network },
  { id: 'studio', label: 'Studio', icon: Sparkles },
  { id: 'git', label: 'Git', icon: GitBranch },
  { id: 'agents', label: 'Agents', icon: Workflow }
]

export function Workspace() {
  const [view, setView] = useState<View>('chat')
  const [projects, setProjects] = useState<Project[]>([])
  const [projectId, setProjectId] = useState<number | null>(null)
  const [hardware, setHardware] = useState<Hardware | null>(null)
  const [ollama, setOllama] = useState<{ available: boolean; models: { name: string }[]; error?: string } | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [wizardOpen, setWizardOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')

  const project = projects.find((item) => item.id === projectId) || null

  const loadSystem = useCallback(async () => {
    try {
      const [projectData, hardwareData, modelData] = await Promise.all([
        api<Project[]>('/api/projects'),
        api<Hardware>('/api/hardware'),
        api<{ ollama: { available: boolean; models: { name: string }[]; error?: string } }>('/api/models/status')
      ])
      setProjects(projectData)
      setHardware(hardwareData)
      setOllama(modelData.ollama)
      setProjectId((current) => current ?? projectData[0]?.id ?? null)
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Unable to connect to the local API.')
    }
  }, [])

  useEffect(() => { void loadSystem() }, [loadSystem])

  // Auto-open the onboarding wizard the first time we learn Ollama is not
  // usable (unavailable, or running with zero models). shouldShowWizard also
  // checks the dismissed flag, so a user who already dismissed it once this
  // session/device is not interrupted again.
  useEffect(() => {
    if (!ollama) return
    if (shouldShowWizard(ollama.available, ollama.models.length)) setWizardOpen(true)
  }, [ollama])

  function closeWizard() {
    dismissOnboarding()
    setWizardOpen(false)
  }

  async function indexActiveProject() {
    if (!projectId) return
    setBusy(true); setNotice('')
    try {
      const result = await api<{ indexed: number; unchanged: number; errors: string[] }>(`/api/projects/${projectId}/index`, { method: 'POST' })
      setNotice(`Index complete: ${result.indexed} updated, ${result.unchanged} unchanged${result.errors.length ? `, ${result.errors.length} skipped` : ''}.`)
      await loadSystem()
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Index failed.')
    } finally { setBusy(false) }
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark"><Bot size={17}/></span><div><strong>InMyAI</strong><small>Local AI Workspace</small></div></div>
        <div className="project-picker">
          <span>Active project</span>
          <select value={projectId ?? ''} onChange={(event) => setProjectId(Number(event.target.value))} aria-label="Active project">
            {!projects.length && <option value="">No project</option>}
            {projects.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}
          </select>
          {project && <small title={project.path}>{project.path}</small>}
        </div>
        <nav>{nav.map((item) => { const Icon = item.icon; return <button key={item.id} className={view === item.id ? 'active' : ''} onClick={() => setView(item.id)}><Icon size={17}/><span>{item.label}</span></button> })}</nav>
        <div className="sidebar-spacer"/>
        <button className="settings-button" onClick={() => setSettingsOpen(true)}><Settings size={17}/>Settings</button>
        <div className="local-status"><span className={ollama?.available ? 'status-dot online' : 'status-dot'}/><div><strong>{ollama?.available ? 'Ollama ready' : 'Safe mock mode'}</strong><small>{hardware ? `${hardware.profile} profile · ${hardware.ram.available_gb} GB free` : 'Checking hardware'}</small></div></div>
      </aside>

      <section className="main-column">
        <header className="topbar">
          <div><h1>{nav.find((item) => item.id === view)?.label}</h1><p>{project ? project.name : 'Add a local project to begin.'}</p></div>
          <div className="top-actions">
            <button className="icon-button" title="Index project" onClick={indexActiveProject} disabled={!project || busy}>{busy ? <Loader2 className="spin" size={18}/> : <RefreshCw size={18}/>}</button>
            <button className="icon-button" title="Settings" onClick={() => setSettingsOpen(true)}><Settings size={18}/></button>
          </div>
        </header>
        {notice && <div className="notice"><span>{notice}</span><button onClick={() => setNotice('')} aria-label="Close notice"><X size={15}/></button></div>}
        {!project ? <EmptyProject onOpen={() => setSettingsOpen(true)}/> : (
          <div className="content-area">
            {view === 'chat' && <ChatView project={project} ollamaAvailable={!!ollama?.available}/>} 
            {view === 'files' && <FilesView project={project}/>} 
            {view === 'memory' && <MemoryView project={project}/>} 
            {view === 'graph' && <GraphView project={project}/>}
            {view === 'studio' && <StudioView project={project}/>}
            {view === 'git' && <GitView project={project}/>}
            {view === 'agents' && <AgentsView project={project}/>}
          </div>
        )}
      </section>

      <ContextRail project={project} hardware={hardware} ollama={ollama} onOpenWizard={() => setWizardOpen(true)}/>
      <MobileNav view={view} setView={setView}/>
      {settingsOpen && (
        <SettingsModal
          projects={projects}
          hardware={hardware}
          ollama={ollama}
          onClose={() => setSettingsOpen(false)}
          onChanged={loadSystem}
          onOpenWizard={() => { setSettingsOpen(false); setWizardOpen(true) }}
        />
      )}
      {wizardOpen && <OnboardingWizard onClose={closeWizard} onReady={loadSystem}/>}
    </main>
  )
}

function EmptyProject({ onOpen }: { onOpen: () => void }) {
  return <div className="empty-state"><FolderOpen size={38}/><h2>Add a local project</h2><p>InMyAI only indexes folders you explicitly register. Private data stays on your device.</p><button className="primary" onClick={onOpen}><Plus size={16}/>Add project</button></div>
}

function ChatView({ project, ollamaAvailable }: { project: Project; ollamaAvailable: boolean }) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: 'assistant', content: `Project ${project.name} is selected. Ask about its architecture, files, decisions, or errors. I will retrieve local context before answering.` }
  ])
  const [input, setInput] = useState('')
  const [provider, setProvider] = useState<'auto' | 'mock' | 'ollama'>('auto')
  const [sending, setSending] = useState(false)
  const [conversationId, setConversationId] = useState<number | null>(null)
  const [resuming, setResuming] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  // Auto-resume the last conversation for this project. When the project
  // changes (or the component first mounts), look up a stored conversation id
  // and reload its history. If none exists, fall back to a fresh greeting.
  useEffect(() => {
    let cancelled = false
    const stored = typeof window !== 'undefined' ? window.localStorage.getItem(conversationStorageKey(project.id)) : null
    const storedId = stored ? Number(stored) : NaN
    if (!storedId) {
      setMessages([{ role: 'assistant', content: `Project ${project.name} is selected. What should we inspect?` }])
      setConversationId(null)
      return
    }
    setResuming(true)
    api<{ conversation: unknown; messages: unknown }>(`/api/conversations/${storedId}`)
      .then((body) => {
        if (cancelled) return
        const parsed = parseConversationResponse(body as Parameters<typeof parseConversationResponse>[0])
        if (parsed.messages.length) {
          setMessages(parsed.messages)
          setConversationId(parsed.conversation?.id ?? storedId)
        } else {
          setMessages([{ role: 'assistant', content: `Project ${project.name} is selected. What should we inspect?` }])
          setConversationId(null)
        }
      })
      .catch(() => {
        if (cancelled) return
        // Stored id is stale (deleted, server reset). Clear it and start fresh.
        window.localStorage.removeItem(conversationStorageKey(project.id))
        setMessages([{ role: 'assistant', content: `Project ${project.name} is selected. What should we inspect?` }])
        setConversationId(null)
      })
      .finally(() => { if (!cancelled) setResuming(false) })
    return () => { cancelled = true }
  }, [project.id, project.name])

  function startNewConversation() {
    if (typeof window !== 'undefined') window.localStorage.removeItem(conversationStorageKey(project.id))
    setConversationId(null)
    setMessages([{ role: 'assistant', content: `Started a new conversation for ${project.name}.` }])
  }

  async function send() {
    const message = input.trim(); if (!message || sending) return
    setMessages((current) => [...current, { role: 'user', content: message }]); setInput(''); setSending(true)
    try {
      const result = await api<ChatResponse>('/api/chat', { method: 'POST', body: JSON.stringify({ project_id: project.id, message, conversation_id: conversationId, provider }) })
      setConversationId(result.conversation_id)
      if (typeof window !== 'undefined') window.localStorage.setItem(conversationStorageKey(project.id), String(result.conversation_id))
      setMessages((current) => [...current, { role: 'assistant', content: result.answer, route: result.route, citations: result.citations }])
    } catch (error) {
      setMessages((current) => [...current, { role: 'assistant', content: `Request failed safely: ${error instanceof Error ? error.message : 'Unknown error'}` }])
    } finally { setSending(false) }
  }

  return <div className="chat-layout">
    <section className="chat-panel">
      <div className="chat-toolbar"><div><strong>Project conversation</strong><small>{conversationId ? `Conversation #${conversationId}` : 'New conversation'} · context is retrieved from indexed files and active decisions.</small></div><div className="chat-toolbar-actions"><button className="icon-button" title="Start a new conversation" onClick={startNewConversation} disabled={!!resuming || sending}><Plus size={16}/></button><select value={provider} onChange={(e) => setProvider(e.target.value as typeof provider)}><option value="auto">Automatic router</option><option value="mock">Safe mock</option><option value="ollama" disabled={!ollamaAvailable}>Ollama local</option></select></div></div>
      <div className="messages">{messages.map((message, index) => <article key={index} className={`message ${message.role}`}><div className="avatar">{message.role === 'assistant' ? <Bot size={16}/> : 'U'}</div><div className="message-body"><pre>{message.content}</pre>{message.route && <div className="route-card"><strong>{message.route.engine}</strong><span>{message.route.reason}</span><small>{message.route.estimated_ram_mb ?? '—'} MB estimate · {message.route.context_limit?.toLocaleString() ?? '—'} token budget</small></div>}{message.citations?.length ? <div className="citations"><b>Sources</b>{message.citations.map((source) => <span key={source.relative_path}>{source.relative_path}</span>)}</div> : null}</div></article>)}{sending && <article className="message assistant"><div className="avatar"><Bot size={16}/></div><div className="message-body typing"><span/><span/><span/></div></article>}<div ref={bottomRef}/></div>
      <div className="composer"><textarea value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send() } }} placeholder="Ask about this project…"/><button onClick={send} disabled={!input.trim() || sending}><Send size={16}/><span>Send</span></button></div>
    </section>
    <aside className="activity-panel"><h3>Suggested tasks</h3>{['Explain the architecture', 'Find active database decisions', 'Trace the login dependency path', 'Search for TODO and FIXME'].map((item) => <button key={item} onClick={() => setInput(item)}>{item}<span>↗</span></button>)}<div className="safety-box"><ShieldCheck size={18}/><div><strong>Controlled tools</strong><p>File changes require a diff, explicit approval, and an automatic backup.</p></div></div></aside>
  </div>
}

function FilesView({ project }: { project: Project }) {
  const [files, setFiles] = useState<IndexedFile[]>([])
  const [selected, setSelected] = useState('')
  const [content, setContent] = useState('')
  const [draft, setDraft] = useState('')
  const [query, setQuery] = useState('')
  const [proposals, setProposals] = useState<Proposal[]>([])
  const [loading, setLoading] = useState(false)
  const filtered = files.filter((file) => file.relative_path.toLowerCase().includes(query.toLowerCase()))

  const load = useCallback(async () => {
    const [fileData, proposalData] = await Promise.all([
      api<IndexedFile[]>(`/api/projects/${project.id}/files`),
      api<Proposal[]>(`/api/projects/${project.id}/proposals`)
    ])
    setFiles(fileData); setProposals(proposalData)
  }, [project.id])
  useEffect(() => { void load() }, [load])

  async function openFile(path: string) {
    setLoading(true)
    try { const result = await api<{ content: string }>(`/api/projects/${project.id}/file?path=${encodeURIComponent(path)}`); setSelected(path); setContent(result.content); setDraft(result.content) } finally { setLoading(false) }
  }
  async function propose() {
    const result = await api<Proposal>('/api/proposals', { method: 'POST', body: JSON.stringify({ project_id: project.id, relative_path: selected, proposed_content: draft }) })
    setProposals((current) => [result, ...current])
  }
  async function applyProposal(id: number) { await api(`/api/proposals/${id}/apply`, { method: 'POST' }); await load(); if (selected) await openFile(selected) }
  async function rejectProposal(id: number) { await api(`/api/proposals/${id}/reject`, { method: 'POST' }); await load() }

  return <div className="files-layout"><aside className="file-list"><div className="search-input"><Search size={15}/><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search files…"/></div><div className="file-scroll">{filtered.map((file) => <button key={file.id} className={selected === file.relative_path ? 'selected' : ''} onClick={() => void openFile(file.relative_path)}><FileText size={15}/><span>{file.relative_path}</span><small>{formatBytes(file.size_bytes)}</small></button>)}</div></aside><section className="editor-panel">{!selected ? <div className="editor-empty"><FileCode2 size={34}/><h2>Select an indexed file</h2><p>Index the project first if this list is empty.</p></div> : <><div className="editor-toolbar"><div><strong>{selected}</strong><small>Changes stay staged until you approve the diff.</small></div><button className="primary small" onClick={propose} disabled={draft === content}><GitBranch size={15}/>Create proposal</button></div><textarea className="code-editor" value={draft} onChange={(e) => setDraft(e.target.value)} spellCheck={false}/></>}</section><aside className="proposal-panel"><h3>Change proposals</h3>{proposals.length === 0 && <p className="muted">No staged changes.</p>}{proposals.slice(0, 8).map((proposal) => <article key={proposal.id}><div><strong>{proposal.relative_path}</strong><span className={`status ${proposal.status}`}>{proposal.status}</span></div><pre>{proposal.diff || 'New file with no line-level diff.'}</pre>{proposal.status === 'pending' && <footer><button onClick={() => void rejectProposal(proposal.id)}>Reject</button><button className="primary small" onClick={() => void applyProposal(proposal.id)}><Check size={14}/>Apply</button></footer>}</article>)}</aside></div>
}

function MemoryView({ project }: { project: Project }) {
  const [memories, setMemories] = useState<Memory[]>([]); const [decisions, setDecisions] = useState<Decision[]>([])
  const [memoryTitle, setMemoryTitle] = useState(''); const [memoryContent, setMemoryContent] = useState('')
  const [statement, setStatement] = useState(''); const [supersedes, setSupersedes] = useState('')
  const load = useCallback(async () => { const [m, d] = await Promise.all([api<Memory[]>(`/api/projects/${project.id}/memories`), api<Decision[]>(`/api/projects/${project.id}/decisions`)]); setMemories(m); setDecisions(d) }, [project.id])
  useEffect(() => { void load() }, [load])
  async function addMemory() { await api('/api/memories', { method: 'POST', body: JSON.stringify({ project_id: project.id, kind: 'semantic', title: memoryTitle, content: memoryContent, source: 'user', confidence: 1 }) }); setMemoryTitle(''); setMemoryContent(''); await load() }
  async function addDecision() { await api('/api/decisions', { method: 'POST', body: JSON.stringify({ project_id: project.id, statement, rationale: '', supersedes_id: supersedes ? Number(supersedes) : null, source: 'user', approved_by: 'user' }) }); setStatement(''); setSupersedes(''); await load() }
  return <div className="memory-grid"><section><div className="section-heading"><div><h2>Project memory</h2><p>Stable facts and reusable project knowledge.</p></div><MemoryStick size={23}/></div><form className="inline-form" onSubmit={(e) => { e.preventDefault(); void addMemory() }}><input value={memoryTitle} onChange={(e) => setMemoryTitle(e.target.value)} placeholder="Memory title" required/><textarea value={memoryContent} onChange={(e) => setMemoryContent(e.target.value)} placeholder="What should InMyAI remember?" required/><button className="primary"><Save size={15}/>Save memory</button></form><div className="memory-list">{memories.map((item) => <article key={item.id}><span>{item.kind}</span><h3>{item.title}</h3><p>{item.content}</p><small>{item.source} · confidence {Math.round(item.confidence * 100)}%</small></article>)}</div></section><section><div className="section-heading"><div><h2>Decision ledger</h2><p>Active decisions override older, superseded choices.</p></div><GitBranch size={23}/></div><form className="inline-form" onSubmit={(e) => { e.preventDefault(); void addDecision() }}><textarea value={statement} onChange={(e) => setStatement(e.target.value)} placeholder="Record a project decision…" required/><select value={supersedes} onChange={(e) => setSupersedes(e.target.value)}><option value="">Does not supersede another decision</option>{decisions.filter((item) => item.status === 'active').map((item) => <option value={item.id} key={item.id}>Supersedes D{item.id}: {item.statement}</option>)}</select><button className="primary"><Save size={15}/>Record decision</button></form><div className="decision-list">{decisions.map((item) => <article key={item.id} className={item.status}><header><strong>D{item.id}</strong><span className={`status ${item.status}`}>{item.status}</span></header><p>{item.statement}</p>{item.supersedes_id && <small>Supersedes D{item.supersedes_id}</small>}</article>)}</div></section></div>
}

function GraphView({ project }: { project: Project }) {
  const [relations, setRelations] = useState<Relation[]>([]); const [node, setNode] = useState(''); const [result, setResult] = useState<{ selected?: string; neighbors?: { direction: string; node: string; relation: string; confidence: string }[] } | null>(null)
  useEffect(() => { void api<{ relations: Relation[] }>(`/api/projects/${project.id}/graph`).then((data) => setRelations(data.relations)) }, [project.id])
  async function query() { setResult(await api(`/api/projects/${project.id}/graph?node=${encodeURIComponent(node)}`)) }
  const nodes = useMemo(() => Array.from(new Set(relations.flatMap((r) => [r.source_node, r.target_node]))).slice(0, 24), [relations])
  return <div className="graph-layout"><section className="graph-canvas"><div className="graph-search"><Search size={16}/><input value={node} onChange={(e) => setNode(e.target.value)} placeholder="Explain a file, symbol, or dependency"/><button className="primary small" onClick={() => void query()}>Trace</button></div><div className="node-cloud">{nodes.map((item, index) => <button key={item} onClick={() => { setNode(item); setTimeout(() => void query(), 0) }} style={{ '--i': index } as CSSProperties}>{item}</button>)}</div><div className="graph-caption"><Network size={17}/><p>The built-in graph uses deterministic imports and symbol extraction. Graphify graph.json can be integrated as an additional source.</p></div></section><aside className="graph-inspector"><h3>{result?.selected || 'Graph inspector'}</h3>{!result?.neighbors?.length ? <p className="muted">Select or trace a node to inspect its edges.</p> : result.neighbors.map((neighbor, index) => <article key={`${neighbor.node}-${index}`}><span>{neighbor.direction === 'out' ? '→' : '←'} {neighbor.relation}</span><strong>{neighbor.node}</strong><small>{neighbor.confidence}</small></article>)}</aside></div>
}

function StudioView({ project }: { project: Project }) {
  const [files, setFiles] = useState<IndexedFile[]>([]); const [ocrFile, setOcrFile] = useState(''); const [ocrText, setOcrText] = useState('')
  const [prompt, setPrompt] = useState('A clean navy industrial coverall product image on a white studio background.'); const [imageProvider, setImageProvider] = useState<'simulator' | 'comfyui' | 'diffusers'>('simulator'); const [imageResult, setImageResult] = useState<{ relative_path: string; notice: string; seed: number } | null>(null); const [busy, setBusy] = useState(false)
  useEffect(() => { void api<IndexedFile[]>(`/api/projects/${project.id}/files`).then(setFiles) }, [project.id])
  async function ocr() { setBusy(true); try { const result = await api<{ text: string }>('/api/ocr', { method: 'POST', body: JSON.stringify({ project_id: project.id, relative_path: ocrFile, language: 'eng' }) }); setOcrText(result.text) } finally { setBusy(false) } }
  async function generate() { setBusy(true); try { const result = await api<{ relative_path: string; notice: string; seed: number }>('/api/images/generate', { method: 'POST', body: JSON.stringify({ project_id: project.id, prompt, width: 512, height: 512, steps: 4, seed: -1, provider: imageProvider }) }); setImageResult(result) } finally { setBusy(false) } }
  return <div className="studio-grid"><section><div className="section-heading"><div><h2>OCR & extract</h2><p>PDF text extraction and local Tesseract OCR.</p></div><FileText size={22}/></div><select value={ocrFile} onChange={(e) => setOcrFile(e.target.value)}><option value="">Choose an indexed PDF or image path</option>{files.filter((file) => ['.pdf','.png','.jpg','.jpeg','.webp'].includes(file.extension)).map((file) => <option key={file.id}>{file.relative_path}</option>)}</select><button className="primary" onClick={() => void ocr()} disabled={!ocrFile || busy}>{busy ? <Loader2 className="spin" size={16}/> : <Search size={16}/>}Extract text</button><textarea className="output-area" value={ocrText} readOnly placeholder="Extracted text appears here…"/></section><section><div className="section-heading"><div><h2>Local image router</h2><p>Workflow simulator in core; real generation uses the optional local Diffusers or ComfyUI plugin.</p></div><ImageIcon size={22}/></div><textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Describe the image…"/><div className="image-controls"><label>512 × 512</label><label>4 low-memory steps</label><label>Batch 1</label></div><select value={imageProvider} onChange={(e) => setImageProvider(e.target.value as 'simulator' | 'comfyui' | 'diffusers')}><option value="simulator">Workflow simulator</option><option value="diffusers">Local Diffusers</option><option value="comfyui">Local ComfyUI</option></select><button className="primary" onClick={() => void generate()} disabled={busy}>{busy ? <Loader2 className="spin" size={16}/> : <Sparkles size={16}/>}Run {imageProvider === 'simulator' ? 'workflow simulator' : 'local generation'}</button>{imageResult && <div className="image-result"><img src={`${API_URL}/api/generated-file?project_id=${project.id}&path=${encodeURIComponent(imageResult.relative_path)}`} alt="Generated workflow simulation"/><p>{imageResult.notice}</p><small>Seed {imageResult.seed}</small></div>}</section></div>
}

function GitView({ project }: { project: Project }) {
  type Tab = 'status' | 'log' | 'diff' | 'blame'
  const [tab, setTab] = useState<Tab>('status')
  const [status, setStatus] = useState<{ branch: string; staged: string[]; unstaged: string[]; untracked: string[] } | null>(null)
  const [log, setLog] = useState<{ entries: { hash: string; author: string; date: string; message: string }[] } | null>(null)
  const [branches, setBranches] = useState<{ current: string; local: string[]; remote: string[] } | null>(null)
  const [diffPath, setDiffPath] = useState('')
  const [diff, setDiff] = useState<string>('')
  const [blamePath, setBlamePath] = useState('')
  const [blame, setBlame] = useState<{ lines: { commit: string; author: string; content: string }[] } | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const run = useCallback(async (fn: () => Promise<void>) => {
    setBusy(true); setError('')
    try { await fn() } catch (e) { setError(e instanceof Error ? e.message : 'Git operation failed') } finally { setBusy(false) }
  }, [])

  const loadStatus = useCallback(() => run(async () => {
    const s = await api<{ branch: string; staged: string[]; unstaged: string[]; untracked: string[] }>(`/api/projects/${project.id}/git/status`)
    setStatus(s)
    const b = await api<{ current: string; local: string[]; remote: string[] }>(`/api/projects/${project.id}/git/branches`)
    setBranches(b)
  }), [project.id, run])

  const loadLog = useCallback(() => run(async () => {
    const l = await api<{ entries: { hash: string; author: string; date: string; message: string }[] }>(`/api/projects/${project.id}/git/log?limit=50`)
    setLog(l)
  }), [project.id, run])

  const loadDiff = useCallback(() => run(async () => {
    const qs = diffPath ? `?path=${encodeURIComponent(diffPath)}` : ''
    const d = await api<{ diff: string }>(`/api/projects/${project.id}/git/diff${qs}`)
    setDiff(d.diff)
  }), [project.id, diffPath, run])

  const loadBlame = useCallback(() => run(async () => {
    if (!blamePath) return
    const b = await api<{ lines: { commit: string; author: string; content: string }[] }>(`/api/projects/${project.id}/git/blame?path=${encodeURIComponent(blamePath)}`)
    setBlame(b)
  }), [project.id, blamePath, run])

  useEffect(() => {
    if (tab === 'status' && !status) void loadStatus()
    if (tab === 'log' && !log) void loadLog()
  }, [tab, status, log, loadStatus, loadLog])

  return <div className="git-layout">
    <section className="git-main">
      <div className="git-tabs">{(['status', 'log', 'diff', 'blame'] as Tab[]).map((t) => (
        <button key={t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>{t.charAt(0).toUpperCase() + t.slice(1)}</button>
      ))}</div>
      {error && <div className="notice"><span>{error}</span><button onClick={() => setError('')} aria-label="Close"><X size={15}/></button></div>}
      {busy && <div className="git-loading"><Loader2 className="spin" size={18}/> <span>Reading repository…</span></div>}
      {tab === 'status' && status && <div className="git-status">
        <div className="git-branch-row"><GitBranch size={16}/> <strong>{branches?.current || status.branch || '—'}</strong></div>
        <div className="git-status-grid">
          <div><h4>Staged ({status.staged.length})</h4>{status.staged.length ? status.staged.map((p) => <span key={p} className="git-entry staged">{p}</span>) : <span className="muted">clean</span>}</div>
          <div><h4>Unstaged ({status.unstaged.length})</h4>{status.unstaged.length ? status.unstaged.map((p) => <span key={p} className="git-entry unstaged">{p}</span>) : <span className="muted">clean</span>}</div>
          <div><h4>Untracked ({status.untracked.length})</h4>{status.untracked.length ? status.untracked.map((p) => <span key={p} className="git-entry untracked">{p}</span>) : <span className="muted">clean</span>}</div>
        </div>
      </div>}
      {tab === 'log' && log && <div className="git-log">{log.entries.length ? log.entries.map((e) => (
        <article key={e.hash} className="git-commit"><code>{e.hash.slice(0, 8)}</code><div><strong>{e.message}</strong><small>{e.author} · {e.date}</small></div></article>
      )) : <p className="muted">No commits yet.</p>}</div>}
      {tab === 'diff' && <div className="git-diff">
        <div className="git-input-row"><input value={diffPath} onChange={(e) => setDiffPath(e.target.value)} placeholder="Optional path (leave empty for full diff)"/><button className="primary small" onClick={() => void loadDiff()} disabled={busy}>Show diff</button></div>
        <pre className="code-editor">{diff || 'No diff loaded yet.'}</pre>
      </div>}
      {tab === 'blame' && <div className="git-blame">
        <div className="git-input-row"><input value={blamePath} onChange={(e) => setBlamePath(e.target.value)} placeholder="Relative file path"/><button className="primary small" onClick={() => void loadBlame()} disabled={busy || !blamePath}>Blame</button></div>
        {blame && <div className="git-blame-list">{blame.lines.map((line, i) => (
          <div key={i} className="git-blame-line"><code>{line.commit.slice(0, 8)}</code><small>{line.author}</small><span>{line.content}</span></div>
        ))}</div>}
      </div>}
    </section>
    <aside className="git-side">
      <div className="section-heading"><div><h3>Branches</h3><p>Current: {branches?.current || '—'}</p></div><GitBranch size={20}/></div>
      {branches ? <div className="git-branch-list">{branches.local.map((b) => <span key={b} className={b === branches.current ? 'git-entry current' : 'git-entry'}>{b}</span>)}</div> : <p className="muted">Load status to see branches.</p>}
      <div className="safety-box"><ShieldCheck size={18}/><div><strong>Read-only</strong><p>Git tools inspect the repository only. No commits, pushes, or branch changes are made through InMyAI.</p></div></div>
    </aside>
  </div>
}

const TERMINAL_TASK_STATES = new Set(['completed', 'failed', 'cancelled'])

function taskStatusClass(status: string) {
  if (status === 'completed') return 'applied'
  if (status === 'failed' || status === 'cancelled') return 'rejected'
  return 'pending'
}

function AgentsView({ project }: { project: Project }) {
  const [agents, setAgents] = useState<Agent[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null)
  const [detail, setDetail] = useState<TaskDetail | null>(null)
  const [title, setTitle] = useState('')
  const [instruction, setInstruction] = useState('')
  const [provider, setProvider] = useState<'auto' | 'mock' | 'ollama'>('auto')
  const [creating, setCreating] = useState(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    const [agentData, taskData] = await Promise.all([
      api<Agent[]>(`/api/projects/${project.id}/agents`),
      api<Task[]>(`/api/projects/${project.id}/tasks`)
    ])
    setAgents(agentData)
    setTasks(taskData)
  }, [project.id])
  useEffect(() => { void load() }, [load])

  const loadDetail = useCallback(async (taskId: number) => {
    try {
      const result = await api<TaskDetail>(`/api/tasks/${taskId}`)
      setDetail(result)
    } catch {
      // Task may have disappeared (e.g. a different project was selected mid-poll).
    }
  }, [])

  useEffect(() => {
    if (selectedTaskId) void loadDetail(selectedTaskId)
    else setDetail(null)
  }, [selectedTaskId, loadDetail])

  // Poll the open task's checkpoint timeline while it is still in flight, so
  // the Coordinator/Researcher/Worker/Verifier handoffs update live instead
  // of requiring a manual refresh.
  useEffect(() => {
    if (!selectedTaskId || !detail || TERMINAL_TASK_STATES.has(detail.task.status)) return
    const timer = setInterval(() => { void loadDetail(selectedTaskId) }, 2000)
    return () => clearInterval(timer)
  }, [selectedTaskId, detail, loadDetail])

  async function createTask(event: React.FormEvent) {
    event.preventDefault()
    if (!title.trim() || !instruction.trim() || creating) return
    setCreating(true); setError('')
    try {
      const task = await api<Task>('/api/tasks', { method: 'POST', body: JSON.stringify({ project_id: project.id, title, instruction, provider }) })
      setTitle(''); setInstruction('')
      await load()
      setSelectedTaskId(task.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to queue task.')
    } finally { setCreating(false) }
  }

  async function runSelected() {
    if (!selectedTaskId || running) return
    setRunning(true); setError('')
    try {
      await api(`/api/tasks/${selectedTaskId}/run`, { method: 'POST' })
    } catch (err) {
      // A failed run is still checkpointed as a 'failed' event server-side —
      // surface the message but keep refreshing so the timeline shows why.
      setError(err instanceof Error ? err.message : 'Task run failed.')
    } finally {
      await Promise.all([loadDetail(selectedTaskId), load()])
      setRunning(false)
    }
  }

  async function cancelSelected() {
    if (!selectedTaskId) return
    await api(`/api/tasks/${selectedTaskId}/cancel`, { method: 'POST' })
    await Promise.all([loadDetail(selectedTaskId), load()])
  }

  let verification: Record<string, unknown> | null = null
  if (detail?.task.verification_json && detail.task.verification_json !== '{}') {
    try { verification = JSON.parse(detail.task.verification_json) } catch { verification = null }
  }

  return (
    <div className="agents-layout">
      <aside className="agents-roster">
        <div className="section-heading"><div><h2>Agents</h2><p>Coordinator plans, Researcher retrieves, Worker drafts, Verifier checks — every handoff is a durable, replayable checkpoint.</p></div><Users size={22}/></div>
        <div className="agent-card-list">
          {agents.map((agent) => (
            <article key={agent.id} className="agent-card">
              <div><strong>{agent.name}</strong><span className={`status ${agent.status === 'working' ? 'pending' : 'applied'}`}>{agent.status}</span></div>
              <p>{agent.role}</p>
              <small>{agent.provider} · {agent.model}</small>
            </article>
          ))}
          {!agents.length && <p className="muted">Agents are created automatically the first time this tab loads.</p>}
        </div>
      </aside>

      <section className="agents-main">
        <form className="inline-form task-form" onSubmit={createTask}>
          <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Task title" required/>
          <textarea value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder="Describe what the Worker Agent should do. It only uses retrieved project context, and never claims a tool ran unless the result is attached." required/>
          <div className="task-form-row">
            <select value={provider} onChange={(event) => setProvider(event.target.value as typeof provider)}>
              <option value="auto">Automatic router</option>
              <option value="mock">Safe mock</option>
              <option value="ollama">Ollama local</option>
            </select>
            <button className="primary" disabled={creating}>{creating ? <Loader2 className="spin" size={15}/> : <Plus size={15}/>}Queue task</button>
          </div>
          {error && <p className="form-error">{error}</p>}
        </form>

        <div className="task-columns">
          <div className="task-list">
            <h3>Tasks</h3>
            {!tasks.length && <p className="muted">No tasks yet for this project.</p>}
            {tasks.map((task) => (
              <button key={task.id} className={selectedTaskId === task.id ? 'task-row selected' : 'task-row'} onClick={() => setSelectedTaskId(task.id)}>
                <span className={`status ${taskStatusClass(task.status)}`}>{task.status}</span>
                <strong>{task.title}</strong>
                <small>{new Date(task.created_at).toLocaleString()}</small>
              </button>
            ))}
          </div>

          <div className="task-detail">
            {!detail ? <p className="muted">Select a task to see its checkpoint timeline.</p> : <>
              <div className="task-detail-header">
                <div><strong>{detail.task.title}</strong><span className={`status ${taskStatusClass(detail.task.status)}`}>{detail.task.status}</span></div>
                <div className="task-detail-actions">
                  {(detail.task.status === 'queued' || detail.task.status === 'failed') && <button className="primary small" onClick={() => void runSelected()} disabled={running}>{running ? <Loader2 className="spin" size={13}/> : <PlayCircle size={13}/>}Run</button>}
                  {!TERMINAL_TASK_STATES.has(detail.task.status) && <button onClick={() => void cancelSelected()}><StopCircle size={13}/>Cancel</button>}
                </div>
              </div>
              <p className="task-instruction">{detail.task.instruction}</p>
              <div className="event-timeline">
                {detail.events.map((event) => (
                  <div key={event.id} className={`event-row ${event.state}`}>
                    <span className="event-dot"/>
                    <div><strong>{event.state}</strong><p>{event.message}</p><small>{new Date(event.created_at).toLocaleString()}</small></div>
                  </div>
                ))}
              </div>
              {!!detail.task.result_text && <div className="task-result"><h4>Worker result</h4><pre>{detail.task.result_text}</pre></div>}
              {verification && <div className="task-verification"><h4>Verifier checks</h4><pre>{JSON.stringify(verification, null, 2)}</pre></div>}
            </>}
          </div>
        </div>
      </section>
    </div>
  )
}

function ContextRail({ project, hardware, ollama, onOpenWizard }: { project: Project | null; hardware: Hardware | null; ollama: { available: boolean; models: { name: string }[]; error?: string } | null; onOpenWizard: () => void }) {
  return <aside className="context-rail"><h3>Context</h3><div className="context-block"><span>Active project</span><strong>{project?.name || 'None selected'}</strong><small>{project?.indexed_at ? `Indexed ${new Date(project.indexed_at).toLocaleString()}` : 'Not indexed yet'}</small></div><div className="context-block"><span>Resource profile</span><strong>{hardware?.profile || 'Checking'} mode</strong><div className="meter"><i style={{ width: `${hardware?.ram.percent || 0}%` }}/></div><small>{hardware ? `${hardware.ram.available_gb} GB RAM available` : 'Reading local hardware'}</small></div><div className="context-block"><span>Model runtime</span>{ollama?.available ? <strong>Ollama connected</strong> : <button className="link-button rail-action" onClick={onOpenWizard}>Safe Mock — click to set up Ollama</button>}<small>{ollama?.available ? `${ollama.models.length} model(s) installed` : 'Core remains testable without weights'}</small></div><div className="context-block"><span>Safety policy</span><ul><li>One heavy engine at a time</li><li>Write through approval only</li><li>Automatic file backup</li><li>1.5 GB RAM guard</li></ul></div></aside>
}

function SettingsModal({ projects, hardware, ollama, onClose, onChanged, onOpenWizard }: { projects: Project[]; hardware: Hardware | null; ollama: { available: boolean; models: { name: string }[]; error?: string } | null; onClose: () => void; onChanged: () => Promise<void>; onOpenWizard: () => void }) {
  const [name, setName] = useState('Synthetic demo'); const [path, setPath] = useState(''); const [error, setError] = useState(''); const [saving, setSaving] = useState(false)
  async function addProject(e: React.FormEvent) { e.preventDefault(); setSaving(true); setError(''); try { await api('/api/projects', { method: 'POST', body: JSON.stringify({ name, path }) }); await onChanged(); setName(''); setPath('') } catch (err) { setError(err instanceof Error ? err.message : 'Unable to add project') } finally { setSaving(false) } }
  return <div className="modal-backdrop" onMouseDown={onClose}><section className="settings-modal" onMouseDown={(e) => e.stopPropagation()}><header><div><h2>Settings</h2><p>Local paths and model runtimes remain under your control.</p></div><button className="icon-button" onClick={onClose}><X size={18}/></button></header><div className="settings-grid"><section><h3>Add a local project</h3><form onSubmit={addProject}><label>Project name<input value={name} onChange={(e) => setName(e.target.value)} required/></label><label>Absolute folder path<input value={path} onChange={(e) => setPath(e.target.value)} placeholder="C:\\dev\\my-project or /home/me/project" required/></label>{error && <p className="form-error">{error}</p>}<button className="primary" disabled={saving}>{saving ? <Loader2 className="spin" size={16}/> : <Plus size={16}/>}Register project</button></form><p className="helper">For the bundled demo, use the absolute path to <code>examples/synthetic-project</code>. Sensitive credential and system folders are blocked.</p></section><section><h3>Runtime status</h3><dl><div><dt>Hardware profile</dt><dd>{hardware?.profile || 'Unknown'}</dd></div><div><dt>Total RAM</dt><dd>{hardware?.ram.total_gb ?? '—'} GB</dd></div><div><dt>Available RAM</dt><dd>{hardware?.ram.available_gb ?? '—'} GB</dd></div><div><dt>Max active models</dt><dd>{hardware?.guard.max_active_models ?? 1}</dd></div><div><dt>Ollama</dt><dd>{ollama?.available ? 'Connected' : 'Not connected'}</dd></div></dl>{ollama?.available ? <div className="model-list">{ollama.models.map((model) => <span key={model.name}>{model.name}</span>)}</div> : <button className="primary small ollama-setup-button" onClick={onOpenWizard}><Download size={14}/>Set up Ollama</button>}</section><section className="wide"><h3>Registered projects</h3>{projects.map((project) => <div className="registered-project" key={project.id}><FolderOpen size={17}/><div><strong>{project.name}</strong><small>{project.path}</small></div><span>{project.indexed_at ? 'indexed' : 'not indexed'}</span></div>)}</section></div></section></div>
}

const ONBOARDING_STEPS: { id: OnboardingState['phase']; label: string }[] = [
  { id: 'download_ollama', label: 'Download' },
  { id: 'start_ollama', label: 'Start' },
  { id: 'pull_model', label: 'Pull model' },
  { id: 'ready', label: 'Ready' }
]

function OnboardingWizard({ onClose, onReady }: { onClose: () => void; onReady: () => Promise<void> }) {
  const [state, setState] = useState<OnboardingState | null>(null)
  const [checking, setChecking] = useState(false)
  const [copied, setCopied] = useState('')

  const check = useCallback(async () => {
    setChecking(true)
    try {
      const result = await api<OnboardingState>('/api/models/onboarding')
      setState(result)
      if (result.phase === 'ready') await onReady()
    } catch {
      // The API may be briefly unreachable; keep the last known state rather
      // than blanking the wizard.
    } finally {
      setChecking(false)
    }
  }, [onReady])

  useEffect(() => { void check() }, [check])

  function copy(text: string, key: string) {
    if (typeof navigator !== 'undefined' && navigator.clipboard) {
      navigator.clipboard.writeText(text).catch(() => { /* clipboard permission denied; command stays visible to copy manually */ })
    }
    setCopied(key)
    setTimeout(() => setCopied((current) => (current === key ? '' : current)), 1500)
  }

  const stepIndex = state ? ONBOARDING_STEPS.findIndex((step) => step.id === state.phase) : 0

  return <div className="modal-backdrop" onMouseDown={onClose}>
    <section className="onboarding-modal" onMouseDown={(e) => e.stopPropagation()}>
      <header>
        <div><h2>Set up Ollama</h2><p>Optional — InMyAI runs in Safe Mock mode without it.</p></div>
        <button className="icon-button" onClick={onClose} aria-label="Close"><X size={18}/></button>
      </header>
      <div className="onboarding-steps">
        {ONBOARDING_STEPS.map((step, index) => (
          <div key={step.id} className={`onboarding-step${index === stepIndex ? ' active' : ''}${index < stepIndex ? ' done' : ''}`}>
            <span>{index < stepIndex ? <Check size={12}/> : index + 1}</span>{step.label}
          </div>
        ))}
      </div>
      <div className="onboarding-body">
        {!state ? <p className="muted">Checking your machine…</p> : <>
          {state.phase === 'download_ollama' && <div className="onboarding-panel">
            <Download size={26}/>
            <h3>Install Ollama</h3>
            <p>Ollama runs local models on your device. InMyAI never uploads your files.</p>
            <button className="primary" onClick={() => window.open('https://ollama.com/download', '_blank', 'noopener')}><ExternalLink size={15}/>Download Ollama</button>
            <p className="helper">Already installed it? <button className="link-button" onClick={() => void check()}>Check again</button></p>
          </div>}
          {state.phase === 'start_ollama' && <div className="onboarding-panel">
            <TerminalSquare size={26}/>
            <h3>Start Ollama</h3>
            <p>{state.version ? `Ollama ${state.version} is` : 'Ollama is'} installed but not running. Start it from the system tray, or run:</p>
            <div className="code-row"><code>ollama serve</code><button className="icon-button" title="Copy command" onClick={() => copy('ollama serve', 'serve')}>{copied === 'serve' ? <Check size={14}/> : <Copy size={14}/>}</button></div>
            <button className="primary" onClick={() => void check()} disabled={checking}>{checking ? <Loader2 className="spin" size={15}/> : <RefreshCw size={15}/>}Check again</button>
          </div>}
          {state.phase === 'pull_model' && <div className="onboarding-panel">
            <HardDrive size={26}/>
            <h3>Pull a model</h3>
            <p>Recommended for your device ({state.hardware_profile} profile):</p>
            {state.recommended.length ? <div className="recommend-list">
              {state.recommended.map((rec) => <div className="recommend-card" key={rec.id}>
                <div><strong>{rec.model}</strong><small>{rec.task_types.join(', ')}{rec.peak_ram_mb ? ` · ~${rec.peak_ram_mb} MB` : ''}</small></div>
                <div className="code-row"><code>{rec.pull_command}</code><button className="icon-button" title="Copy command" onClick={() => copy(rec.pull_command, rec.id)}>{copied === rec.id ? <Check size={14}/> : <Copy size={14}/>}</button></div>
              </div>)}
            </div> : <p className="muted">No profile match yet for this device — you can still run, e.g. <code>ollama pull gemma3:1b</code>.</p>}
            <button className="primary" onClick={() => void check()} disabled={checking}>{checking ? <Loader2 className="spin" size={15}/> : <RefreshCw size={15}/>}Check again</button>
          </div>}
          {state.phase === 'ready' && <div className="onboarding-panel">
            <Check size={26}/>
            <h3>Ollama is ready</h3>
            <p>{state.models.length} model{state.models.length === 1 ? '' : 's'} installed. Pick "Ollama local" as the chat provider whenever you want it.</p>
            <button className="primary" onClick={onClose}>Start using InMyAI</button>
          </div>}
        </>}
      </div>
      <footer className="onboarding-footer">
        <button className="link-button" onClick={onClose}>Remind me later</button>
        <button className="link-button" onClick={onClose}>Skip, use Safe Mock</button>
      </footer>
    </section>
  </div>
}

function MobileNav({ view, setView }: { view: View; setView: (view: View) => void }) { return <nav className="mobile-nav">{nav.map((item) => { const Icon = item.icon; return <button key={item.id} className={view === item.id ? 'active' : ''} onClick={() => setView(item.id)}><Icon size={18}/><span>{item.label}</span></button> })}</nav> }
function formatBytes(bytes: number) { if (bytes < 1024) return `${bytes} B`; if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`; return `${(bytes / 1024 / 1024).toFixed(1)} MB` }
