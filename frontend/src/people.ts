/** Helpers for showing people (task owners) consistently. */

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/)
  return ((parts[0]?.[0] ?? '') + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase()
}

/** Stable colour per person, so the same owner looks the same everywhere. */
export function hue(name: string): number {
  let hash = 0
  for (const char of name) {
    hash = (hash * 31 + char.charCodeAt(0)) % 360
  }
  return hash
}
