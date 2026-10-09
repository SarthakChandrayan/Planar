/**
 * Demo mode: the same UI, reading recorded runs instead of a backend.
 *
 * Built with VITE_DEMO=1 for the website, where no local model is available.
 * The runs in ../demo/ were produced by the real pipeline (qwen3:8b on a
 * laptop) and exported by backend/scripts/build_demo.py.
 */
export const DEMO = import.meta.env.VITE_DEMO === '1'

const DATA_ROOT = new URL('../demo/', document.baseURI)

export function demoUrl(path: string): string {
  return new URL(path, DATA_ROOT).toString()
}

export async function demoJson<T>(path: string): Promise<T> {
  const response = await fetch(demoUrl(path))
  if (!response.ok) {
    throw new Error(`Demo data missing: ${path}`)
  }
  return (await response.json()) as T
}

/** Where public files (icons) live: the site root in dev, next to the app in a build. */
export function asset(path: string): string {
  return `${import.meta.env.BASE_URL}${path.replace(/^\//, '')}`
}

export const DEMO_MODEL = 'qwen3:8b · recorded'
