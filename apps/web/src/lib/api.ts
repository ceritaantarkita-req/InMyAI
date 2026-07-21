export const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000'

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { 'content-type': 'application/json', ...(init?.headers || {}) },
    cache: 'no-store'
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(body.detail || `Request failed: ${response.status}`)
  }
  return body as T
}
