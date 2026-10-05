const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

export class ApiError extends Error {
  readonly status?: number

  constructor(message: string, status?: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export function apiUrl(path: string): string {
  return `${API_BASE_URL}${path}`
}

function userMessageFromDetail(detail: unknown): string | null {
  if (typeof detail === 'string' && detail.trim()) {
    return detail
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (item && typeof item === 'object' && 'msg' in item) {
          const msg = (item as { msg?: unknown }).msg
          return typeof msg === 'string' ? msg : null
        }
        return null
      })
      .filter((msg): msg is string => Boolean(msg))
    if (messages.length > 0) {
      return messages.join(' ')
    }
  }
  return null
}

function messageForStatus(status: number, detail: string | null): string {
  if (detail) {
    return detail
  }
  if (status === 422) {
    return 'The request could not be validated. Check that the transcript is not empty.'
  }
  if (status === 503) {
    return 'The analysis service is unavailable. Confirm the backend and Ollama are running.'
  }
  if (status === 504) {
    return 'The model timed out. Try again, or try a shorter transcript.'
  }
  if (status >= 500) {
    return 'The server could not complete the request. Try again.'
  }
  return 'The request was rejected.'
}

export async function request<T>(
  path: string,
  init: { method?: string; body?: unknown; signal?: AbortSignal } = {},
): Promise<T> {
  let response: Response
  try {
    response = await fetch(apiUrl(path), {
      method: init.method ?? 'GET',
      headers: init.body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      signal: init.signal,
    })
  } catch (caught) {
    if (caught instanceof DOMException && caught.name === 'AbortError') {
      throw caught
    }
    throw new ApiError(
      'Could not reach the Planar API. Start the backend, or check VITE_API_BASE_URL.',
    )
  }

  if (response.status === 204) {
    return undefined as T
  }

  let payload: unknown = null
  try {
    payload = await response.json()
  } catch {
    payload = null
  }

  if (!response.ok) {
    const detail =
      payload && typeof payload === 'object'
        ? userMessageFromDetail((payload as { detail?: unknown }).detail)
        : null
    throw new ApiError(messageForStatus(response.status, detail), response.status)
  }
  return payload as T
}
