/** Helpers for showing people (task owners) consistently. */

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/)
  return ((parts[0]?.[0] ?? '') + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase()
}

// Hues for avatars: reds, oranges, yellows, greens, teals, blues. No purples.
const AVATAR_HUES = [4, 18, 32, 45, 95, 140, 165, 185, 200, 212]

/** Stable colour per person, so the same owner looks the same everywhere. */
export function hue(name: string): number {
  let hash = 0
  for (const char of name) {
    hash = (hash * 31 + char.charCodeAt(0)) % 9973
  }
  return AVATAR_HUES[hash % AVATAR_HUES.length]
}
