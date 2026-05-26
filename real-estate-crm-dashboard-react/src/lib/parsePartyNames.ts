/**
 * Split seller/buyer strings without breaking names inside parentheses (e.g. "LLC (Zach Clayton, Lynda Clayton)").
 */
export function splitPartyNames(raw: string): string[] {
  const v = (raw ?? '').trim()
  if (!v) return []

  const parts: string[] = []
  let depth = 0
  let start = 0

  const push = (end: number) => {
    const piece = v.slice(start, end).trim()
    if (piece) parts.push(piece)
    start = end
  }

  let i = 0
  while (i < v.length) {
    const c = v[i]
    if (c === '(') {
      depth++
      i++
      continue
    }
    if (c === ')') {
      depth = Math.max(0, depth - 1)
      i++
      continue
    }
    if (depth === 0) {
      if (c === ',') {
        push(i)
        start = i + 1
        i++
        continue
      }
      const andMatch = v.slice(i).match(/^\s+and\s+/i)
      if (andMatch) {
        push(i)
        start = i + andMatch[0].length
        i = start
        continue
      }
      const ampMatch = v.slice(i).match(/^\s*&\s+/)
      if (ampMatch) {
        push(i)
        start = i + ampMatch[0].length
        i = start
        continue
      }
    }
    i++
  }
  push(v.length)

  if (parts.length <= 1) return parts.length ? parts : [v]
  return parts
}

/** Closing attorney / firm line — keep as one entry; strip trailing banker notes. */
export function normalizeAttorneyLine(raw: string): string {
  return (raw ?? '')
    .trim()
    .replace(/\s*\|\s*Banker:.*/i, '')
    .replace(/\s*--\s*Dave.*/i, '')
    .trim()
}
