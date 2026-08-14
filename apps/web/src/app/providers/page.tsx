'use client'

import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '@/lib/api'

type PortableProvider = {
  provider_id: string
  display_name: string
  transport: string
  connection_owner: string
  execution_state: string
  risk_class: string
  selection_mode: string
  automatic_routing_allowed: boolean
  dispatch_allowed: boolean
  credential_resolution: string
  raw_credential_exposure_allowed: boolean
  browser_session_credentials_allowed: boolean
  model_discovery_state: string
  default_model: string | null
}

type OpenRouterModel = {
  id: string
  name: string | null
  contextLength: number | null
  maxCompletionTokens: number | null
  pricing: {
    prompt: string | null
    completion: string | null
    request: string | null
    image: string | null
  }
  supportedParameters: string[]
}

type ModelsReceipt = {
  outputs?: {
    provider?: string
    models?: OpenRouterModel[]
    truncated?: boolean
  }
  provider?: string
  models?: OpenRouterModel[]
  truncated?: boolean
}

type SelectionPlan = {
  schema_version: string
  provider: string
  model: string
  selection_mode: string
  selection_status: 'SELECTED_GOVERNED_PATH'
  connection_owner: string
  credential_resolution: string
  risk_class: string
  execution_state: string
  raw_credential_exposure_allowed: false
  browser_session_credentials_allowed: false
  automatic_routing_allowed: false
  dispatch_allowed: true
  network_call_performed: false
  next_gate: 'CONNECT_RUNTIME_AND_HUB_SERVICE_IDENTITY'
}

const CONNECTION_KEY = 'inmyai:openrouter:connectionId'
const MODEL_KEY = 'inmyai:openrouter:modelId'

const shell = {
  minHeight: '100vh',
  padding: '40px 20px',
  background: 'var(--bg)',
  color: 'var(--text)'
} as const

const panel = {
  maxWidth: 960,
  margin: '0 auto',
  padding: 24,
  border: '1px solid var(--line)',
  borderRadius: 14,
  background: 'var(--surface)',
  boxShadow: 'var(--shadow)'
} as const

const field = {
  display: 'grid',
  gap: 7,
  marginTop: 18
} as const

const input = {
  width: '100%',
  minHeight: 42,
  padding: '0 12px',
  border: '1px solid var(--line-strong)',
  borderRadius: 8,
  background: 'white',
  color: 'var(--text)'
} as const

function newIdempotencyKey(prefix: string) {
  const random = typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID().replace(/-/g, '')
    : `${Date.now()}${Math.random().toString(16).slice(2)}`
  return `${prefix}-${random}`.slice(0, 128)
}

export default function PortableProvidersPage() {
  const [providers, setProviders] = useState<PortableProvider[]>([])
  const [providerId, setProviderId] = useState('')
  const [connectionId, setConnectionId] = useState('')
  const [modelId, setModelId] = useState('')
  const [models, setModels] = useState<OpenRouterModel[]>([])
  const [plan, setPlan] = useState<SelectionPlan | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadingModels, setLoadingModels] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (typeof window !== 'undefined') {
      setConnectionId(window.localStorage.getItem(CONNECTION_KEY) || '')
      setModelId(window.localStorage.getItem(MODEL_KEY) || '')
    }
    let cancelled = false
    api<PortableProvider[]>('/api/providers/portable')
      .then((catalog) => {
        if (cancelled) return
        setProviders(catalog)
        setProviderId((current) => current || catalog[0]?.provider_id || '')
      })
      .catch((cause) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : 'Unable to load portable providers.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [])

  const selectedProvider = useMemo(
    () => providers.find((provider) => provider.provider_id === providerId) || null,
    [providers, providerId]
  )

  async function loadModels() {
    if (providerId !== 'openrouter' || !connectionId.trim() || loadingModels) return
    setLoadingModels(true)
    setError('')
    setSaved(false)
    try {
      const result = await api<ModelsReceipt>('/api/providers/openrouter/models', {
        method: 'POST',
        body: JSON.stringify({
          connection_id: connectionId.trim(),
          idempotency_key: newIdempotencyKey('openrouter-models')
        })
      })
      const payload = result.outputs || result
      const nextModels = Array.isArray(payload.models) ? payload.models : []
      setModels(nextModels)
      if (modelId && !nextModels.some((model) => model.id === modelId)) setModelId('')
    } catch (cause) {
      setModels([])
      setError(cause instanceof Error ? cause.message : 'OpenRouter model discovery failed safely.')
    } finally {
      setLoadingModels(false)
    }
  }

  async function selectProvider(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!providerId || !connectionId.trim() || !modelId || submitting) return
    setSubmitting(true)
    setError('')
    setPlan(null)
    setSaved(false)
    try {
      const result = await api<SelectionPlan>('/api/providers/portable/select', {
        method: 'POST',
        body: JSON.stringify({
          provider_id: providerId,
          model_id: modelId,
          selection_mode: 'manual'
        })
      })
      setPlan(result)
      if (typeof window !== 'undefined') {
        window.localStorage.setItem(CONNECTION_KEY, connectionId.trim())
        window.localStorage.setItem(MODEL_KEY, modelId)
      }
      setSaved(true)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Provider selection failed safely.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main style={shell}>
      <section style={panel}>
        <a href="/" style={{ color: 'var(--accent)', fontSize: 12, textDecoration: 'none' }}>← Back to InMyAI</a>
        <div style={{ marginTop: 20 }}>
          <span style={{ display: 'inline-block', padding: '5px 9px', borderRadius: 999, background: 'var(--accent-soft)', color: 'var(--accent-2)', fontSize: 10, fontWeight: 700, letterSpacing: '.05em', textTransform: 'uppercase' }}>Hub-governed provider</span>
          <h1 style={{ margin: '12px 0 6px', fontSize: 26, letterSpacing: '-.03em' }}>OpenRouter connection</h1>
          <p style={{ margin: 0, maxWidth: 740, color: 'var(--muted)', fontSize: 13, lineHeight: 1.6 }}>
            Choose the opaque InMyConnect connection, load the models available to that account, then select one model explicitly. InMyAI never asks for or stores your OpenRouter API key.
          </p>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(210px,1fr))', gap: 10, marginTop: 20 }}>
          {['Credentials stay in InMyConnect', 'Models come from the connected account', 'No automatic routing or silent fallback'].map((label) => (
            <div key={label} style={{ padding: 12, border: '1px solid var(--line)', borderRadius: 9, background: 'var(--surface-2)', fontSize: 11, color: 'var(--muted)' }}>{label}</div>
          ))}
        </div>

        {loading ? (
          <p style={{ marginTop: 24, color: 'var(--muted)' }}>Loading provider catalog…</p>
        ) : (
          <form onSubmit={selectProvider} style={{ marginTop: 24 }}>
            <label style={field}>
              <span style={{ fontSize: 11, fontWeight: 700 }}>Provider</span>
              <select value={providerId} onChange={(event) => { setProviderId(event.target.value); setModels([]); setModelId(''); setPlan(null); setSaved(false) }} style={input} aria-label="Portable provider">
                {providers.length === 0 && <option value="">No portable provider registered</option>}
                {providers.map((provider) => <option key={provider.provider_id} value={provider.provider_id}>{provider.display_name}</option>)}
              </select>
            </label>

            <label style={field}>
              <span style={{ fontSize: 11, fontWeight: 700 }}>InMyConnect connection ID</span>
              <input
                value={connectionId}
                onChange={(event) => { setConnectionId(event.target.value); setModels([]); setModelId(''); setPlan(null); setSaved(false) }}
                placeholder="conn_…"
                autoComplete="off"
                spellCheck={false}
                style={input}
                aria-label="OpenRouter connection ID"
              />
              <small style={{ color: 'var(--soft)' }}>This is an opaque connection identifier, not an API key.</small>
            </label>

            <button type="button" onClick={() => void loadModels()} disabled={providerId !== 'openrouter' || !connectionId.trim() || loadingModels} style={{ marginTop: 12 }}>
              {loadingModels ? 'Loading models…' : 'Load account models'}
            </button>

            <label style={field}>
              <span style={{ fontSize: 11, fontWeight: 700 }}>Model</span>
              <select value={modelId} onChange={(event) => { setModelId(event.target.value); setPlan(null); setSaved(false) }} style={input} aria-label="OpenRouter model">
                <option value="">Select a model explicitly</option>
                {models.map((model) => <option key={model.id} value={model.id}>{model.name ? `${model.name} — ${model.id}` : model.id}</option>)}
              </select>
              <small style={{ color: 'var(--soft)' }}>No cloud model is selected or defaulted automatically.</small>
            </label>

            {selectedProvider && (
              <div style={{ marginTop: 16, padding: 14, border: '1px solid var(--line)', borderRadius: 9, background: 'var(--surface-2)', fontSize: 11, lineHeight: 1.65 }}>
                <strong>{selectedProvider.display_name}</strong>
                <div style={{ color: 'var(--muted)', marginTop: 5 }}>
                  Transport: {selectedProvider.transport} · Risk: {selectedProvider.risk_class} · Execution: {selectedProvider.execution_state}
                </div>
                <div style={{ color: 'var(--muted)' }}>Credential resolution: {selectedProvider.credential_resolution}</div>
                <div style={{ color: 'var(--muted)' }}>Model discovery: {selectedProvider.model_discovery_state}</div>
              </div>
            )}

            <button className="primary" type="submit" disabled={!providerId || !connectionId.trim() || !modelId || submitting} style={{ marginTop: 18 }}>
              {submitting ? 'Saving…' : 'Save explicit selection'}
            </button>
          </form>
        )}

        {error && <div role="alert" style={{ marginTop: 18, padding: 12, borderRadius: 9, background: '#fff0f0', color: 'var(--danger)', fontSize: 11 }}>{error}</div>}

        {plan && (
          <section style={{ marginTop: 22, padding: 18, border: '1px solid #cfe4d9', borderRadius: 10, background: '#f3fbf7' }} aria-label="Portable provider selection result">
            <strong style={{ display: 'block', fontSize: 13 }}>{plan.selection_status}</strong>
            <p style={{ margin: '6px 0 0', color: 'var(--muted)', fontSize: 11, lineHeight: 1.6 }}>
              {plan.provider} / {plan.model} is pinned for the governed path. Every R1 chat still requires Hub authorization at execution time.
            </p>
            <dl style={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '6px 14px', margin: '14px 0 0', fontSize: 10 }}>
              <dt>Credentials</dt><dd style={{ margin: 0 }}>{plan.credential_resolution}</dd>
              <dt>Automatic routing</dt><dd style={{ margin: 0 }}>{String(plan.automatic_routing_allowed)}</dd>
              <dt>Governed dispatch path</dt><dd style={{ margin: 0 }}>{String(plan.dispatch_allowed)}</dd>
              <dt>Selection network call</dt><dd style={{ margin: 0 }}>{String(plan.network_call_performed)}</dd>
              <dt>Saved locally</dt><dd style={{ margin: 0 }}>{String(saved)}</dd>
            </dl>
          </section>
        )}
      </section>
    </main>
  )
}
