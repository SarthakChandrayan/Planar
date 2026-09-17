import { createContext, useContext } from 'react'
import type { TraceEntry } from '../trace'

export const TraceIndexContext = createContext<Map<string, TraceEntry>>(
  new Map(),
)
export const TraceNavContext = createContext<(id: string) => void>(() => {})

export function useTraceIndex() {
  return useContext(TraceIndexContext)
}

export function useTraceNav() {
  return useContext(TraceNavContext)
}
