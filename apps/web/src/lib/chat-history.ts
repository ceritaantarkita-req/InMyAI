/**
 * Pure helpers for restoring chat history from the backend conversation API.
 *
 * The backend `GET /api/conversations/{id}` returns message rows whose
 * `citations_json` and `router_json` are raw JSON strings (not parsed). These
 * helpers parse them defensively and map rows to the ChatMessage shape used by
 * the UI, so the component code stays free of JSON.parse bookkeeping.
 */
import type { ChatResponse } from './types'

/** Row shape returned by GET /api/conversations/{id} for each message. */
export type ApiMessage = {
  id?: number
  conversation_id?: number
  role: 'user' | 'assistant' | 'system'
  content: string
  citations_json?: string | null
  router_json?: string | null
  created_at?: string
}

/** Conversation header returned by GET /api/conversations/{id}. */
export type Conversation = {
  id: number
  project_id: number
  title: string
  created_at: string
  updated_at: string
}

/** UI message shape (mirrors the local ChatMessage type in Workspace.tsx). */
export type ChatHistoryMessage = {
  role: 'user' | 'assistant'
  content: string
  route?: ChatResponse['route']
  citations?: ChatResponse['citations']
}

type ConversationResponse = {
  conversation?: Conversation
  messages?: ApiMessage[]
}

/** localStorage key under which the last-used conversation id is remembered. */
export function conversationStorageKey(projectId: number): string {
  return `inmyai:conversation:${projectId}`
}

function safeParse<T>(value: string | null | undefined): T | undefined {
  if (!value) return undefined
  try {
    return JSON.parse(value) as T
  } catch {
    return undefined
  }
}

/** Map one API message row into a UI ChatMessage, parsing the JSON columns.
 * System rows are coerced to 'assistant' as a defensive fallback — callers
 * normally filter them out first via parseConversationResponse. */
export function parseApiMessage(row: ApiMessage): ChatHistoryMessage {
  return {
    role: row.role === 'user' ? 'user' : 'assistant',
    content: row.content,
    citations: safeParse<ChatResponse['citations']>(row.citations_json),
    route: safeParse<ChatResponse['route']>(row.router_json)
  }
}

/**
 * Parse the full GET /api/conversations/{id} response: drops the system prompt
 * message (never shown to the user) and parses each remaining row in order.
 * Tolerates missing/null fields without throwing.
 */
export function parseConversationResponse(body: ConversationResponse): {
  conversation: Conversation | undefined
  messages: ChatHistoryMessage[]
} {
  const messages = (body.messages ?? [])
    .filter((row) => row.role !== 'system')
    .map(parseApiMessage)
  return { conversation: body.conversation, messages }
}
