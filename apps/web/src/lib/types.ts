export type Project = { id: number; name: string; path: string; status: string; indexed_at?: string }
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
