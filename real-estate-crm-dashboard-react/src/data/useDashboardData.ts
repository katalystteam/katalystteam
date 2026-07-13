import { useMemo } from 'react'
import type { DashboardData } from '../types'
import { addressKey } from '../lib/addressKey'
import { dashboardData } from './generated/dashboardData'
import { ghlCampaignEngagementByListingId } from './generated/ghlCampaignEngagement'
import { ghlContactEngagementByListingId } from './generated/ghlContactEngagement'
import { ghlEngagementByListingId } from './generated/ghlEngagement'
import { siteImages } from './generated/siteImages'
import { katalystDocuments } from './generated/katalystDocuments'
import { gdriveDocuments } from './generated/gdriveDocuments'
import { isDocumentsFolderPlaceholder, DROPBOX_LINK_PLACEHOLDER } from '../lib/listingDetails'

type PrivateGhlContactEngagementModule = {
  ghlContactEngagementByListingId: Record<string, { contacts: unknown[] }>
}

function privateGhlContactEngagementByListingId(): Record<string, { contacts: unknown[] }> {
  // Optional local-only file (contains contact PII); absent in Vercel builds.
  const modules = import.meta.glob('./generated/ghlContactEngagement.private.ts', { eager: true }) as Record<
    string,
    PrivateGhlContactEngagementModule
  >
  const first = Object.values(modules)[0]
  return (first?.ghlContactEngagementByListingId ?? {}) as Record<string, { contacts: unknown[] }>
}

function mergeGhlEngagement(data: DashboardData): DashboardData {
  const privateMap = privateGhlContactEngagementByListingId()
  return {
    ...data,
    listings: data.listings.map((l) => {
      const tagSynced = ghlEngagementByListingId[l.id]
      const campaignSynced = ghlCampaignEngagementByListingId[l.id]
      const contactSynced = ghlContactEngagementByListingId[l.id] ?? (privateMap[l.id] as { contacts?: unknown[] } | undefined)
      if (tagSynced === undefined && campaignSynced === undefined && contactSynced === undefined) return l

      const ghlScore =
        campaignSynced?.ghlScore ??
        tagSynced?.ghlScore ??
        l.assoc.engagement?.ghlScore

      return {
        ...l,
        assoc: {
          ...l.assoc,
          engagement: {
            ...l.assoc.engagement,
            ghlScore,
            ghlCampaigns: campaignSynced?.campaigns ?? l.assoc.engagement?.ghlCampaigns,
            ghlTopContacts: (contactSynced?.contacts as never[] | undefined) ?? l.assoc.engagement?.ghlTopContacts,
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

function mergeGdriveDocuments(data: DashboardData): DashboardData {
  const map = gdriveDocuments.byNormalizedAddress as Record<string, string>
  return {
    ...data,
    listings: data.listings.map((l) => {
      const folderUrl = map[addressKey(l.address)]
      if (!folderUrl) return l

      const documents = l.assoc.documents.map((d) =>
        isDocumentsFolderPlaceholder(d.name) && !d.url
          ? { ...d, name: DROPBOX_LINK_PLACEHOLDER, url: folderUrl }
          : d,
      )

      return {
        ...l,
        assoc: {
          ...l.assoc,
          documents,
        },
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
    () => mergeGhlEngagement(mergeKatalystDocuments(mergeGdriveDocuments(mergeSiteImages(dashboardData)))),
    [dashboardData],
  )
  return useMemo(() => ({ data, loading: false, error: null as string | null }), [data])
}

