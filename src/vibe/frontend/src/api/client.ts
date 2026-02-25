const BASE = ''

export async function get<T = any>(path: string): Promise<T> {
  const res = await fetch(BASE + path)
  if (!res.ok) throw new Error(`GET ${path}: ${res.status}`)
  return res.json()
}

export async function post<T = any>(path: string, body?: any): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }))
    throw new Error(err.error || `POST ${path}: ${res.status}`)
  }
  return res.json()
}

export async function put<T = any>(path: string, body: any): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }))
    throw new Error(err.error || `PUT ${path}: ${res.status}`)
  }
  return res.json()
}

export async function del<T = any>(path: string): Promise<T> {
  const res = await fetch(BASE + path, { method: 'DELETE' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }))
    throw new Error(err.error || `DELETE ${path}: ${res.status}`)
  }
  return res.json()
}

export function createSSE(path: string, onMessage: (data: string) => void, onError?: () => void): EventSource {
  const es = new EventSource(BASE + path)
  es.onmessage = (e) => onMessage(e.data)
  es.onerror = () => { if (onError) onError() }
  return es
}
