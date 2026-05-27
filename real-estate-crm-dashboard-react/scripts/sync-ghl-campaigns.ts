/**
 * Matches GHL sent email campaigns to listings by address in campaign HTML,
 * then pulls aggregate open/click stats per campaign.
 *
 * Pilot: only listings in PILOT_LISTING_IDS (default Boston Ave task id).
 *
 *   npm run sync:ghl-campaigns
 */
import fs from 'node:fs'
import path from 'node:path'
import { config } from 'dotenv'
import { dashboardData } from '../src/data/generated/dashboardData'
import { normalizeAddressKey } from '../src/lib/normalizeAddressKey'

config({ path: path.join(process.cwd(), '.env.local') })
config({ path: path.join(process.cwd(), '..', '.env.local') })

const GHL_BASE_URL = process.env.GHL_BASE_URL ?? 'https://services.leadconnectorhq.com'
const GHL_API_VERSION = '2021-07-28'

/** ClickUp listing task ids to match (expand later). */
const PILOT_LISTING_IDS = (process.env.GHL_CAMPAIGN_PILOT_IDS ?? '86agdcyuv')
  .split(',')
  .map((s) => s.trim())
  .filter(Boolean)

type ScheduleRow = {
  id?: string
  name?: string
  subject?: string
  downloadUrl?: string
  bulkRequestId?: string
  dateScheduled?: number
  createdAt?: string
  successCount?: number
  totalCount?: number
}

type CampaignStats = {
  sent: number
  delivered: number
  opened: number
  clicked: number
  openRate: number
  clickRate: number
}

type MatchedCampaign = {
  campaignId: string
  bulkRequestId: string
  name: string
  subject: string
  sentAt: string | null
  stats: CampaignStats
}

function headers(): HeadersInit {
  const token = process.env.GHL_API_TOKEN ?? ''
  return {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
    Version: GHL_API_VERSION,
  }
}

function stripHtml(html: string): string {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function addressNeedles(address: string): string[] {
  const key = normalizeAddressKey(address)
  const needles = new Set<string>()
  if (key) needles.add(key)
  const street = key.replace(/\s+(des moines|ia|tx|fl|oh).*$/i, '').trim()
  if (street.length >= 8) needles.add(street)
  const num = key.match(/^\d+/)?.[0]
  if (num && key.includes('boston')) needles.add(`${num} boston`)
  return [...needles].sort((a, b) => b.length - a.length)
}

function htmlMatchesAddress(html: string, address: string): boolean {
  const text = normalizeAddressKey(stripHtml(html))
  return addressNeedles(address).some((n) => text.includes(n))
}

function ghlScoreFromStats(stats: CampaignStats): number {
  const base = stats.openRate + stats.clickRate
  if (base > 0) return Math.min(100, Math.round(base))
  const d = Math.max(1, stats.delivered)
  return Math.min(100, Math.round(((stats.opened + stats.clicked * 2) / d) * 100))
}

async function fetchSchedules(locationId: string): Promise<ScheduleRow[]> {
  const res = await fetch(`${GHL_BASE_URL}/emails/schedule?locationId=${locationId}`, { headers: headers() })
  if (!res.ok) throw new Error(`GHL schedule ${res.status}: ${(await res.text()).slice(0, 400)}`)
  const data = (await res.json()) as { schedules?: ScheduleRow[] }
  return data.schedules ?? []
}

async function fetchCampaignStats(locationId: string, bulkRequestId: string): Promise<CampaignStats> {
  const url = `${GHL_BASE_URL}/emails/public/v2/locations/${locationId}/campaigns/stats/bulk-actions/${bulkRequestId}`
  const res = await fetch(url, { headers: headers() })
  if (!res.ok) throw new Error(`GHL stats ${res.status}: ${(await res.text()).slice(0, 400)}`)
  const data = (await res.json()) as { stats?: Partial<CampaignStats> }
  const s = data.stats ?? {}
  return {
    sent: s.sent ?? 0,
    delivered: s.delivered ?? 0,
    opened: s.opened ?? 0,
    clicked: s.clicked ?? 0,
    openRate: s.openRate ?? 0,
    clickRate: s.clickRate ?? 0,
  }
}

function formatSentAt(row: ScheduleRow): string | null {
  const ms = row.dateScheduled
  if (typeof ms === 'number' && ms > 0) {
    try {
      return new Date(ms).toISOString().slice(0, 10)
    } catch {
      /* ignore */
    }
  }
  if (row.createdAt) return row.createdAt.slice(0, 10)
  return null
}

async function main() {
  const token = process.env.GHL_API_TOKEN
  const locationId = process.env.GHL_LOCATION_ID
  if (!token || !locationId) {
    console.error('Missing GHL_API_TOKEN or GHL_LOCATION_ID in .env.local')
    process.exit(1)
  }

  const pilotListings = dashboardData.listings.filter((l) => PILOT_LISTING_IDS.includes(l.id))
  if (pilotListings.length === 0) {
    console.error(`No listings found for pilot ids: ${PILOT_LISTING_IDS.join(', ')}`)
    process.exit(1)
  }

  console.log(`Pilot listings: ${pilotListings.map((l) => l.name).join('; ')}`)

  const schedules = await fetchSchedules(locationId)
  console.log(`Fetched ${schedules.length} scheduled/sent campaigns from GHL`)

  const byListing = new Map<string, MatchedCampaign[]>()

  for (const listing of pilotListings) {
    const matched: MatchedCampaign[] = []
    for (const row of schedules) {
      const downloadUrl = row.downloadUrl
      const bulkRequestId = row.bulkRequestId
      const campaignId = row.id
      if (!downloadUrl || !bulkRequestId || !campaignId) continue

      let html: string
      try {
        const hres = await fetch(downloadUrl)
        if (!hres.ok) continue
        html = await hres.text()
      } catch {
        continue
      }

      if (!htmlMatchesAddress(html, listing.address)) continue

      const stats = await fetchCampaignStats(locationId, bulkRequestId)
      matched.push({
        campaignId,
        bulkRequestId,
        name: row.name ?? 'Untitled campaign',
        subject: row.subject ?? '',
        sentAt: formatSentAt(row),
        stats,
      })
      console.log(`  ✓ ${row.name} → ${listing.name} (${stats.opened} opens, ${stats.clicked} clicks)`)
    }
    byListing.set(listing.id, matched)
  }

  const lines: string[] = [
    '/** Generated by scripts/sync-ghl-campaigns.ts — do not edit by hand. */',
    'export type GhlCampaignStats = {',
    '  sent: number',
    '  delivered: number',
    '  opened: number',
    '  clicked: number',
    '  openRate: number',
    '  clickRate: number',
    '}',
    'export type GhlMatchedCampaign = {',
    '  campaignId: string',
    '  bulkRequestId: string',
    '  name: string',
    '  subject: string',
    '  sentAt: string | null',
    '  stats: GhlCampaignStats',
    '}',
    'export type GhlListingCampaignEngagement = {',
    '  ghlScore: number',
    '  campaigns: GhlMatchedCampaign[]',
    '}',
    'export const ghlCampaignEngagementByListingId: Record<string, GhlListingCampaignEngagement> = {',
  ]

  for (const listing of pilotListings) {
    const campaigns = byListing.get(listing.id) ?? []
    const best =
      campaigns.length === 0
        ? 0
        : Math.max(...campaigns.map((c) => ghlScoreFromStats(c.stats)))
    lines.push(`  ${JSON.stringify(listing.id)}: {`)
    lines.push(`    ghlScore: ${best},`)
    lines.push(`    campaigns: ${JSON.stringify(campaigns, null, 4).replace(/\n/g, '\n    ')},`)
    lines.push('  },')
  }

  lines.push('}')
  lines.push('')

  const outPath = path.join(process.cwd(), 'src', 'data', 'generated', 'ghlCampaignEngagement.ts')
  fs.mkdirSync(path.dirname(outPath), { recursive: true })
  fs.writeFileSync(outPath, lines.join('\n'), 'utf8')
  console.log(`Wrote ${outPath}`)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
