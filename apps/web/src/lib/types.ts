export type Project = { id: number; name: string; path: string; status: string; indexed_at?: string }
export type IndexStatus = {
  status: string
  phase: 'scanning' | 'indexing' | 'done' | 'failed' | 'idle'
  total_files: number
  processed_files: number
  error: string | null
  indexed_at: string | null
}
export type IndexedFile = { id: number; relative_path: string; extension: string; size_bytes: number; indexed_at: string }
export type Memory = { id: number; kind: string; title: string; content: string; source: string; confidence: number; updated_at: string }
export type Decision = { id: number; statement: string; rationale: string; status: string; supersedes_id?: number; created_at: string }
export type Relation = { id: number; source_node: string; relation: string; target_node: string; confidence: string }
export type Proposal = { id: number; relative_path: string; diff: string; status: string; backup_path?: string; created_at: string }
export type Hardware = {
  cpu: { physical_cores: number; logical_cores: number; percent: number }
  ram: { total_gb: number; available_gb: number; percent: number }
  storage: { total_gb: number; free_gb: number; percent: number }
  profile: string
  guard: { allow_new_engine: boolean; max_active_models: number }
}
export type ChatResponse = {
  conversation_id: number
  answer: string
  citations: { relative_path: string; snippet: string }[]
  route: { task: string; engine: string; provider: string; reason: string; estimated_ram_mb: number; context_limit: number }
  model: string
  provider: string
}
export type ModelRecommendation = {
  id: string
  model: string
  task_types: string[]
  peak_ram_mb: number | null
  pull_command: string
  notes: string
}
export type OnboardingState = {
  phase: 'download_ollama' | 'start_ollama' | 'pull_model' | 'ready'
  installed: boolean
  version: string | null
  running: boolean
  models: { name: string }[]
  hardware_profile: string
  recommended: ModelRecommendation[]
}
export type Agent = {
  id: number
  project_id: number
  slug: string
  name: string
  role: string
  provider: string
  model: string
  tools_json: string
  status: string
  created_at: string
  updated_at: string
}
export type Task = {
  id: number
  project_id: number
  title: string
  status: string
  instruction: string
  provider: string
  plan_json: string
  result_text: string
  verification_json: string
  artifact_path: string | null
  created_at: string
  updated_at: string
}
export type AgentEvent = {
  id: number
  task_id: number
  agent_id: number | null
  state: string
  message: string
  data_json: string
  created_at: string
}
export type TaskDetail = { task: Task; events: AgentEvent[] }
export type BrowseEntry = { name: string; path: string; is_dir: boolean; is_project: boolean }
export type BrowseResult = { path: string; parent: string | null; entries: BrowseEntry[]; truncated: boolean }
export type AllowedRoot = { id: number | null; source: 'workspace' | 'env' | 'dynamic'; path: string; created_at: string | null }
export type FolderScope = {
  is_dangerous: boolean
  dangerous_match: string | null
  direct_subdirs: number
  large_folder: boolean
}
