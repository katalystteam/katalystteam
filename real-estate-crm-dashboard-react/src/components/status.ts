import type { ListingStatus } from '../types'

/** Lead / document workflow badges only (not ClickUp listing status). */
export function statusClass(s: ListingStatus) {
  return `status-badge status-${s}`
}

export function statusLabel(s: ListingStatus) {
  return s.charAt(0).toUpperCase() + s.slice(1)
}
