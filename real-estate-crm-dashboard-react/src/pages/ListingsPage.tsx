import { useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useDashboardData } from '../data/useDashboardData'
import type { Listing } from '../types'
import { CLICKUP_STATUS_TAB_ORDER, clickUpStatusBadgeClass, normClickUpStatusKey } from '../lib/clickUpStatus'
import { dedupeListingsByAddress } from '../lib/listingDedupe'
import { sortListings, type ListingSortKey, type SortDir } from '../lib/listingSort'
import { ListingAssocPanel } from './partials/ListingAssocPanel'

/** Year cohort: `all` or calendar year from Properties export / ClickUp list name. */
export type YearFilter = 'all' | number

function parseYearParam(v: string | null): YearFilter {
  if (!v || v === 'all') return 'all'
  const n = Number(v)
  return Number.isFinite(n) ? n : 'all'
}

function parseSortKey(v: string | null): ListingSortKey {
  return v === 'name' ? 'name' : 'updated'
}

function parseSortDir(v: string | null, key: ListingSortKey): SortDir {
  if (v === 'asc' || v === 'desc') return v
  return key === 'name' ? 'asc' : 'desc'
}

function sortArrow(dir: SortDir): string {
  return dir === 'asc' ? '↑' : '↓'
}

/** Builds status pills for a year: preferred order first, then other statuses present (sorted). */
function statusesForYear(listings: Listing[], year: number): string[] {
  const seenNorm = new Map<string, string>()
  for (const l of listings) {
    if (l.datasetYear !== year) continue
    const raw = (l.status ?? '').trim()
    if (!raw) continue
    const k = normClickUpStatusKey(raw)
    if (!seenNorm.has(k)) seenNorm.set(k, raw)
  }

  const preferred = CLICKUP_STATUS_TAB_ORDER as readonly string[]
  const ordered: string[] = []
  for (const p of preferred) {
    if (seenNorm.has(p)) ordered.push(seenNorm.get(p)!)
  }
  const extras = [...seenNorm.entries()]
    .filter(([k]) => !(preferred as readonly string[]).includes(k))
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([, display]) => display)
  return [...ordered, ...extras]
}

function listingMatches(
  l: Listing,
  yearFilter: YearFilter,
  cuNorm: string | null,
  q: string,
): boolean {
  const matchQ = !q || l.name.toLowerCase().includes(q) || l.address.toLowerCase().includes(q)
  if (!matchQ) return false

  if (yearFilter === 'all') return true
  if (l.datasetYear !== yearFilter) return false

  if (!cuNorm || cuNorm === 'all') return true
  return normClickUpStatusKey(l.status) === cuNorm
}

function ListingCard({ listing, active, onSelect }: { listing: Listing; active: boolean; onSelect: () => void }) {
  return (
    <div className={`listing-card${active ? ' active' : ''}`} onClick={onSelect}>
      <div className="listing-img" aria-hidden="true">
        {listing.imageUrl ? (
          <img
            src={listing.imageUrl}
            alt=""
            style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
            loading="lazy"
          />
        ) : (
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z" />
            <polyline points="9 22 9 12 15 12 15 22" />
          </svg>
        )}
      </div>
      <div className="listing-name">{listing.name}</div>
      <div className="listing-address">{listing.address}</div>
      <div className="listing-meta">
        <div className="listing-price">{listing.price ?? '—'}</div>
        <span className={clickUpStatusBadgeClass(listing.status)}>{listing.status}</span>
      </div>
      <div style={{ marginTop: 8, fontSize: 11, color: 'var(--color-text-tertiary)' }}>
        {listing.dateUpdated ? <>Updated {listing.dateUpdated}</> : '—'}
        {listing.datasetYear !== undefined ? (
          <>
            {' '}
            · <span style={{ fontWeight: 600, color: 'var(--color-brand-700)' }}>{listing.datasetYear}</span>
          </>
        ) : null}
      </div>
    </div>
  )
}

export function ListingsPage() {
  const { data } = useDashboardData()
  const [params, setParams] = useSearchParams()

  const q = (params.get('q') ?? '').toLowerCase()
  const yearFilter = parseYearParam(params.get('year'))
  const cuNorm = params.get('cu')
  const activeListingId = params.get('listing')
  const sortKey = parseSortKey(params.get('sort'))
  const sortDir = parseSortDir(params.get('dir'), sortKey)

  const yearsInData = useMemo(() => {
    const s = new Set<number>()
    for (const l of data.listings) {
      if (l.datasetYear !== undefined) s.add(l.datasetYear)
    }
    return [...s].sort((a, b) => b - a)
  }, [data.listings])

  const statusOptions = useMemo(() => {
    if (yearFilter === 'all') return []
    return statusesForYear(data.listings, yearFilter as number)
  }, [data.listings, yearFilter])

  const setYear = (y: YearFilter) => {
    const next = new URLSearchParams(params)
    if (y === 'all') {
      next.delete('year')
      next.delete('cu')
    } else {
      next.set('year', String(y))
      next.delete('cu')
    }
    next.delete('listing')
    setParams(next, { replace: true })
  }

  const setCu = (normKey: string) => {
    const next = new URLSearchParams(params)
    if (!normKey || normKey === 'all') next.delete('cu')
    else next.set('cu', normKey)
    next.delete('listing')
    setParams(next, { replace: true })
  }

  const setSort = (key: ListingSortKey) => {
    const next = new URLSearchParams(params)
    const currentKey = parseSortKey(params.get('sort'))
    const currentDir = parseSortDir(params.get('dir'), currentKey)
    if (currentKey === key) {
      next.set('sort', key)
      next.set('dir', currentDir === 'asc' ? 'desc' : 'asc')
    } else {
      next.set('sort', key)
      next.set('dir', key === 'name' ? 'asc' : 'desc')
    }
    setParams(next, { replace: true })
  }

  const listings = useMemo(() => {
    const cuKey = cuNorm && cuNorm !== 'all' ? cuNorm : null
    const filtered = data.listings.filter((l) => listingMatches(l, yearFilter, cuKey, q))
    // Same property often has a task in 2024, 2025, and 2026 — show one card on “All”.
    const base = yearFilter === 'all' ? dedupeListingsByAddress(filtered) : filtered
    return sortListings(base, sortKey, sortDir)
  }, [data.listings, yearFilter, cuNorm, q, sortKey, sortDir])

  const activeListing = useMemo(
    () => data.listings.find((l) => l.id === activeListingId) ?? null,
    [activeListingId, data.listings],
  )

  const selectListing = (id: string) => {
    const next = new URLSearchParams(params)
    if (activeListingId === id) next.delete('listing')
    else next.set('listing', id)
    setParams(next, { replace: true })
  }

  const yearActive = yearFilter === 'all' ? 'all' : String(yearFilter)
  const cuActive = cuNorm && cuNorm !== 'all' ? cuNorm : 'all'

  return (
    <div className="main">
      <div className="listings-panel">
        <div className="section-header">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <span className="section-title">{`${listings.length} listing${listings.length !== 1 ? 's' : ''}`}</span>
              <div className="filters" role="tablist" aria-label="Year cohort">
                <button type="button" className={`filter-pill${yearActive === 'all' ? ' active' : ''}`} onClick={() => setYear('all')}>
                  All
                </button>
                {yearsInData.map((y) => (
                  <button
                    key={y}
                    type="button"
                    className={`filter-pill${yearActive === String(y) ? ' active' : ''}`}
                    onClick={() => setYear(y)}
                  >
                    {y}
                  </button>
                ))}
              </div>
            </div>

            {yearFilter !== 'all' ? (
              <div className="filters" role="tablist" aria-label="ClickUp status within year">
                <button type="button" className={`filter-pill${cuActive === 'all' ? ' active' : ''}`} onClick={() => setCu('all')}>
                  All statuses
                </button>
                {statusOptions.map((display) => {
                  const nk = normClickUpStatusKey(display)
                  return (
                    <button
                      key={nk}
                      type="button"
                      className={`filter-pill${cuActive === nk ? ' active' : ''}`}
                      onClick={() => setCu(nk)}
                    >
                      {display}
                    </button>
                  )
                })}
              </div>
            ) : null}

            <div className="filters" role="group" aria-label="Sort listings">
              <span className="filter-label">Sort</span>
              <button
                type="button"
                className={`filter-pill${sortKey === 'name' ? ' active' : ''}`}
                onClick={() => setSort('name')}
                aria-pressed={sortKey === 'name'}
                title={sortKey === 'name' ? (sortDir === 'asc' ? 'A–Z (click to reverse)' : 'Z–A (click to reverse)') : 'Sort by property name'}
              >
                Name {sortKey === 'name' ? sortArrow(sortDir) : ''}
              </button>
              <button
                type="button"
                className={`filter-pill${sortKey === 'updated' ? ' active' : ''}`}
                onClick={() => setSort('updated')}
                aria-pressed={sortKey === 'updated'}
                title={
                  sortKey === 'updated'
                    ? sortDir === 'desc'
                      ? 'Newest first (click to reverse)'
                      : 'Oldest first (click to reverse)'
                    : 'Sort by date updated'
                }
              >
                Updated {sortKey === 'updated' ? sortArrow(sortDir) : ''}
              </button>
            </div>
          </div>
        </div>

        <div className="listings-grid">
          {listings.length ? (
            listings.map((l) => (
              <ListingCard key={l.id} listing={l} active={activeListingId === l.id} onSelect={() => selectListing(l.id)} />
            ))
          ) : (
            <div className="empty-state" style={{ gridColumn: '1 / -1' }}>
              No listings found.
            </div>
          )}
        </div>
      </div>

      <div className={`assoc-panel${activeListing ? '' : ' hidden'}`}>
        <div className="assoc-inner">{activeListing ? <ListingAssocPanel listing={activeListing} /> : null}</div>
      </div>
    </div>
  )
}
