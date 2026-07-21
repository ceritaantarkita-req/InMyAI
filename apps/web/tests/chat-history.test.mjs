import test from 'node:test'
import assert from 'node:assert/strict'

import {
  conversationStorageKey,
  parseApiMessage,
  parseConversationResponse
} from '../src/lib/chat-history.ts'

test('conversationStorageKey is namespaced and project-scoped', () => {
  assert.equal(conversationStorageKey(7), 'inmyai:conversation:7')
  assert.equal(conversationStorageKey(0), 'inmyai:conversation:0')
})

test('parseApiMessage maps an assistant row with JSON string columns into parsed fields', () => {
  const row = {
    id: 42,
    conversation_id: 9,
    role: 'assistant',
    content: 'You are using SQLite.',
    citations_json: '[{"relative_path":"README.md","snippet":"..."}]',
    router_json: '{"task":"general","engine":"small-llm","provider":"mock","reason":"x","estimated_ram_mb":100,"context_limit":4096}',
    created_at: '2026-07-21T00:00:00Z'
  }
  const parsed = parseApiMessage(row)
  assert.equal(parsed.role, 'assistant')
  assert.equal(parsed.content, 'You are using SQLite.')
  assert.deepEqual(parsed.citations, [{ relative_path: 'README.md', snippet: '...' }])
  assert.equal(parsed.route?.engine, 'small-llm')
})

test('parseApiMessage tolerates missing citations/router columns', () => {
  const parsed = parseApiMessage({ role: 'user', content: 'hi' })
  assert.equal(parsed.role, 'user')
  assert.equal(parsed.content, 'hi')
  assert.equal(parsed.citations, undefined)
  assert.equal(parsed.route, undefined)
})

test('parseApiMessage tolerates malformed JSON columns without throwing', () => {
  const parsed = parseApiMessage({
    role: 'assistant',
    content: 'x',
    citations_json: 'not json',
    router_json: 'also not json'
  })
  assert.equal(parsed.citations, undefined)
  assert.equal(parsed.route, undefined)
})

test('parseConversationResponse drops system messages and parses the rest in order', () => {
  const body = {
    conversation: { id: 9, project_id: 1, title: 't', created_at: 'a', updated_at: 'b' },
    messages: [
      { role: 'system', content: 'system prompt' },
      { role: 'user', content: 'first' },
      { role: 'assistant', content: 'second', citations_json: '[]', router_json: '{}' }
    ]
  }
  const result = parseConversationResponse(body)
  assert.equal(result.conversation.id, 9)
  assert.equal(result.messages.length, 2)
  assert.deepEqual(result.messages.map((m) => m.role), ['user', 'assistant'])
  assert.equal(result.messages[0].content, 'first')
})

test('parseConversationResponse returns empty messages for an unexpected shape', () => {
  const result = parseConversationResponse({})
  assert.deepEqual(result.messages, [])
})
