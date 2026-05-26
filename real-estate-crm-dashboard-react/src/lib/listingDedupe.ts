import type { Listing } from '../types'
import { addressKey } from './addressKey'

function parseUpdatedMs(s: string | undefined): number {
  if (!s) return 0
  const t = Date.parse(s)
  return Number.isFinite(t) ? t : 0
}

/** When the same property exists in multiple year lists, keep the newest cohort / update. */
export function pickCanonicalListing(a: Listing, b: Listing): Listing {
  const yearA = a.datasetYear ?? 0
  const yearB = b.datasetYear ?? 0
  if (yearB !== yearA) return yearB > yearA ? b : a
  return parseUpdatedMs(b.dateUpdated) >= parseUpdatedMs(a.dateUpdated) ? b : a
}

/** One card per property address (for the “All” year tab). */
export function dedupeListingsByAddress(listings: Listing[]): Listing[] {
  const byAddr = new Map<string, Listing>()
  for (const l of listings) {
    const k = addressKey(l.address)
    const prev = byAddr.get(k)
    byAddr.set(k, prev ? pickCanonicalListing(prev, l) : l)
  }
  return [...byAddr.values()]
}
