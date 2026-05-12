/** Normalize ClickUp status for filtering (lowercase, trim). */
export function normClickUpStatusKey(status: string): string {
  return (status ?? '').trim().toLowerCase()
}

/**
 * Preferred tab order when drilling into a year cohort (matches common ClickUp workflow names).
 * Other statuses present in data append after, sorted.
 */
export const CLICKUP_STATUS_TAB_ORDER = [
  'closed',
  'lost',
  'due diligence',
  'parked',
  'lysted',
  'opportunity',
  'marketing prep',
] as const

/** CSS modifier on `.status-badge` for coloring (exact ClickUp strings vary by workspace). */
export function clickUpStatusBadgeClass(status: string): string {
  const k = normClickUpStatusKey(status)
  if (k === 'closed') return 'status-badge status-cu-closed'
  if (k === 'lost') return 'status-badge status-cu-lost'
  if (k === 'due diligence' || k.includes('diligence')) return 'status-badge status-cu-diligence'
  if (k === 'parked') return 'status-badge status-cu-parked'
  if (k === 'lysted') return 'status-badge status-cu-lysted'
  if (k === 'opportunity') return 'status-badge status-cu-opportunity'
  if (k === 'marketing prep' || k.includes('marketing')) return 'status-badge status-cu-marketing'
  if (k.includes('prep') || k.includes('review')) return 'status-badge status-cu-pending'
  return 'status-badge status-cu-other'
}

/** Map legacy CRM slug → readable label (only when raw ClickUp status was not stored). */
export function legacyCrmStatusToLabel(slug: string): string {
  const m: Record<string, string> = {
    sold: 'Closed',
    active: 'Lysted',
    pending: 'Due diligence',
    inactive: 'Parked',
  }
  return m[slug] ?? slug
}

/** Whether listing counts as “active pipeline” for owner stats (ClickUp: Lysted). */
export function isClickUpLysted(status: string): boolean {
  return normClickUpStatusKey(status) === 'lysted'
}
