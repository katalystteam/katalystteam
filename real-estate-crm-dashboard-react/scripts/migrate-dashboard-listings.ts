/**
 * Backfill flat ClickUp fields from legacy `clickUpFields` / `clickUpStatusRaw`,
 * set listing `status` to exact ClickUp strings, strip bulk export.
 * Run: npx tsx scripts/migrate-dashboard-listings.ts
 */
import fs from 'node:fs'
import path from 'node:path'
import { legacyCrmStatusToLabel } from '../src/lib/clickUpStatus.ts'
import type { DashboardData, Listing, ListingAssoc } from '../src/types.ts'

type LegacyAssoc = ListingAssoc & { clickUpFields?: Array<{ label: string; value: string }> }

function pickField(fields: Array<{ label: string; value: string }> | undefined, needle: string): string {
  if (!fields) return ''
  const n = needle.toLowerCase()
  const hit = fields.find((f) => f.label.toLowerCase().includes(n))
  return (hit?.value ?? '').trim()
}

function isLegacySlug(s: string): boolean {
  return s === 'sold' || s === 'active' || s === 'pending' || s === 'inactive'
}

function buyerFromFields(fields: LegacyAssoc['clickUpFields'], fallback?: string): string {
  if (!fields) return fallback ?? ''
  for (const row of fields) {
    const lab = row.label.toLowerCase()
    if (lab.includes('buyer') && !lab.includes('lender') && !lab.includes('1031') && !lab.includes('closing attorney')) {
      return row.value.trim()
    }
  }
  return fallback ?? ''
}

function sellerFromFields(fields: LegacyAssoc['clickUpFields'], fallback?: string): string {
  if (!fields) return fallback ?? ''
  for (const row of fields) {
    const lab = row.label.toLowerCase()
    if ((/^seller\b/i.test(row.label) || lab.includes('seller')) && !lab.includes('1031')) {
      return row.value.trim()
    }
  }
  return fallback ?? ''
}

async function main() {
  const mod = await import('../src/data/generated/dashboardData.ts')
  const data = mod.dashboardData as DashboardData

  const listings: Listing[] = data.listings.map((l) => {
    const assocLegacy = l.assoc as LegacyAssoc
    const fields = assocLegacy.clickUpFields
    const legacyRaw = (l as { clickUpStatusRaw?: string }).clickUpStatusRaw
    const statusCell = pickField(fields, 'status')

    let status = legacyRaw || ''
    if (!status && statusCell && !isLegacySlug(String(l.status))) status = statusCell
    if (!status) {
      if (isLegacySlug(String(l.status))) status = legacyCrmStatusToLabel(String(l.status))
      else status = String(l.status ?? '—')
    }

    const { clickUpFields: _drop, ...assocRest } = assocLegacy
    const assoc: ListingAssoc = { ...assocRest }

    const next: Listing = {
      ...l,
      status,
      dateUpdated: l.dateUpdated || pickField(fields, 'date updated'),
      createdBy: l.createdBy || pickField(fields, 'created by'),
      abstracting: l.abstracting || pickField(fields, 'abstracting'),
      agent: l.agent || pickField(fields, 'agent'),
      buyer: l.buyer || buyerFromFields(fields, l.buyer),
      closingAttorneyBuyer: l.closingAttorneyBuyer || pickField(fields, 'closing attorney - buyer'),
      lenderBuyer: l.lenderBuyer || pickField(fields, 'lender - buyer'),
      seller: l.seller || sellerFromFields(fields, l.seller),
      titleOpinion: l.titleOpinion || pickField(fields, 'title opinion'),
      assoc,
    }
    delete (next as { clickUpStatusRaw?: string }).clickUpStatusRaw
    return next
  })

  const out: DashboardData = { owners: data.owners, listings }
  const outPath = path.join(process.cwd(), 'src', 'data', 'generated', 'dashboardData.ts')
  const file = `import type { DashboardData } from '../../types';
export const dashboardData: DashboardData = ${JSON.stringify(out, null, 2)} as unknown as DashboardData;
`
  fs.writeFileSync(outPath, file, 'utf8')
  console.log(`Migrated ${listings.length} listings → ${outPath}`)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
