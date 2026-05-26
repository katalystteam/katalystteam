import type { Listing } from '../types'
import { parseUpdatedMs } from './listingDedupe'

export type ListingSortKey = 'name' | 'updated'
export type SortDir = 'asc' | 'desc'

export function sortListings(listings: Listing[], key: ListingSortKey, dir: SortDir): Listing[] {
  const mult = dir === 'asc' ? 1 : -1
  return [...listings].sort((a, b) => {
    if (key === 'name') {
      const byName = a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })
      if (byName !== 0) return mult * byName
      return mult * a.address.localeCompare(b.address, undefined, { sensitivity: 'base' })
    }
    const byDate = parseUpdatedMs(a.dateUpdated) - parseUpdatedMs(b.dateUpdated)
    if (byDate !== 0) return mult * byDate
    return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })
  })
}
