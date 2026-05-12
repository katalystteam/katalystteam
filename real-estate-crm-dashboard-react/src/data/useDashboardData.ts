import { useMemo } from 'react'
import type { DashboardData } from '../types'
import { addressKey } from '../lib/addressKey'
import { dashboardData } from './generated/dashboardData'
import { ghlEngagementByListingId } from './generated/ghlEngagement'
import { siteImages } from './generated/siteImages'
import { katalystDocuments } from './generated/katalystDocuments'

function mergeGhlEngagement(data: DashboardData): DashboardData {
  return {
    ...data,
    listings: data.listings.map((l) => {
      const synced = ghlEngagementByListingId[l.id]
      if (synced === undefined) return l
      return {
        ...l,
        assoc: {
          ...l.assoc,
          engagement: {
            ...l.assoc.engagement,
            ghlScore: synced.ghlScore,
          },
        },
      }
    }),
  }
}

function mergeSiteImages(data: DashboardData): DashboardData {
  const map = siteImages.byNormalizedAddress as Record<
    string,
    { imageUrl?: string; listingUrl?: string }
  >
  return {
    ...data,
    listings: data.listings.map((l) => {
      const k = addressKey(l.address)
      const m = map[k]
      return {
        ...l,
        imageUrl: l.imageUrl ?? m?.imageUrl,
        listingUrl: l.listingUrl ?? m?.listingUrl,
      }
    }),
  }
}

function mergeKatalystDocuments(data: DashboardData): DashboardData {
  const map = katalystDocuments.byNormalizedAddress as Record<
    string,
    readonly { name: string; url: string }[]
  >
  return {
    ...data,
    listings: data.listings.map((l) => {
      const extra = map[addressKey(l.address)]
      if (!extra?.length) return l
      const existing = l.assoc.documents
      const urls = new Set(existing.map((d) => d.url).filter(Boolean) as string[])
      const merged = [...existing]
      for (const d of extra) {
        if (urls.has(d.url)) continue
        urls.add(d.url)
        merged.push({ name: d.name, url: d.url })
      }
      return {
        ...l,
        assoc: {
          ...l.assoc,
          documents: merged,
        },
      }
    }),
  }
}

type DataSource =
  | { kind: 'mock' }
  | {
      kind: 'gsheets_csv'
      listingsCsvUrl: string
      ownersCsvUrl: string
    }

const DEFAULT_SOURCE: DataSource = { kind: 'mock' }

export function useDashboardData(_source: DataSource = DEFAULT_SOURCE) {
  // Merge website images by normalized address (see `siteImages.ts`).
  // Per-listing `imageUrl` / `listingUrl` in `dashboardData.ts` wins if set.
  const data = useMemo(
    () => mergeGhlEngagement(mergeKatalystDocuments(mergeSiteImages(dashboardData))),
    [dashboardData],
  )
  return useMemo(() => ({ data, loading: false, error: null as string | null }), [data])
}

