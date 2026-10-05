/** Planar mark: three stacked planes, from raw notes to a plan. */
export function Logo({ size = 24 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path d="M3 16.2 12 20.5l9-4.3-9-4.3-9 4.3Z" fill="currentColor" opacity="0.3" />
      <path d="M3 11.9 12 16.2l9-4.3-9-4.3-9 4.3Z" fill="currentColor" opacity="0.6" />
      <path d="M3 7.6 12 11.9l9-4.3L12 3.3 3 7.6Z" fill="currentColor" />
    </svg>
  )
}
