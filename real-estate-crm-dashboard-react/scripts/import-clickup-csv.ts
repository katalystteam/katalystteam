import fs from 'node:fs'
import path from 'node:path'
import Papa from 'papaparse'
import type { DashboardData, Listing, Owner } from '../src/types.ts'
import { normalizeAttorneyLine, splitPartyNames } from '../src/lib/parsePartyNames.ts'

type Row = Record<string, string>

/** Listings already imported from the main Properties 2026 export get this year tag when merging. */
const DEFAULT_YEAR_FOR_EXISTING = 2026

function norm(s: string) {
  return (s ?? '')
    .toLowerCase()
    .replaceAll('&', 'and')
    .replaceAll(',', ' ')
    .replaceAll('.', ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function get(row: Row, key: string) {
  return (row[key] ?? '').trim()
}

export function inferDatasetYearFromFilename(filePath: string): number | undefined {
  const base = path.basename(filePath)
  const m =
    base.match(/Properties[^\d]*(\d{4})/i) ??
    base.match(/(\d{4})\s*\.csv$/i) ??
    base.match(/(\d{4})\.csv$/i)
  if (!m) return undefined
  const y = Number(m[1])
  return y >= 2000 && y <= 2100 ? y : undefined
}

function maxOwnerNumericId(owners: Owner[]): number {
  let m = 0
  for (const o of owners) {
    const mm = /^o_(\d+)$/.exec(o.id)
    if (mm) m = Math.max(m, Number(mm[1]))
  }
  return m
}

function formatDateCell(raw: string): string {
  if (!raw) return ''
  const t = Date.parse(raw)
  if (!Number.isFinite(t)) return raw
  try {
    return new Date(t).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  } catch {
    return raw
  }
}

function buildListingFromRow(
  r: Row,
  datasetYear: number | undefined,
  ctx: { ensureOwner: (name: string) => { id: string; name: string } | null },
): Listing {
  const id = get(r, 'Task ID') || `l_${Math.random().toString(36).slice(2)}`
  const name = get(r, 'Task Name') || '(untitled)'
  const status = get(r, 'Status') || '—'

  const seller = get(r, 'Seller (short text)')
  const buyer = get(r, 'Buyer (short text)')
  const ownersAssoc = splitPartyNames(seller)
    .map((n) => ctx.ensureOwner(n))
    .filter(Boolean)
    .map((o) => ({ id: o!.id, name: o!.name }))

  const attorney = normalizeAttorneyLine(get(r, 'Closing Attorney - Buyer (text)'))
  const lawyers = attorney ? [{ name: attorney }] : []

  const agent = get(r, 'Agent (drop down)')
  const agents = agent ? [{ name: agent, role: 'Agent' as const }] : []

  const units = get(r, '# of Units (short text)')
  const price = get(r, 'LYSTing Price (currency)') || get(r, 'Purchase Price (currency)') || ''

  const listing: Listing = {
    id,
    name,
    address: name,
    status,
    datasetYear,
    dateUpdated: formatDateCell(get(r, 'Date Updated')),
    createdBy: get(r, 'Created By'),
    abstracting: get(r, 'Abstracting (short text)'),
    agent: agent || undefined,
    buyer: buyer || undefined,
    closingAttorneyBuyer: get(r, 'Closing Attorney - Buyer (text)') || undefined,
    lenderBuyer: get(r, 'Lender - Buyer (text)') || undefined,
    seller: seller || undefined,
    titleOpinion: get(r, 'Title Opinion (text)') || undefined,
    price: price || undefined,
    type: units ? 'Multifamily' : '—',
    sqm: units ? `${units} units` : '—',
    assoc: {
      owners: ownersAssoc,
      lawyers,
      agents,
      leads: [],
      transactions: [],
      documents: [],
    },
  }
  return listing
}

function parseCsvFile(
  absCsv: string,
  datasetYear: number | undefined,
  ctx: { ensureOwner: (name: string) => { id: string; name: string } | null },
) {
  const csv = fs.readFileSync(absCsv, 'utf8')
  const parsed = Papa.parse<Row>(csv, { header: true, skipEmptyLines: true })
  if (parsed.errors.length) {
    console.error(parsed.errors.slice(0, 3))
    process.exit(1)
  }

  const rows = parsed.data.filter(Boolean)
  return rows
    .filter((r) => get(r, 'Task Type').toLowerCase() === 'task' || get(r, 'Task Type') === '')
    .map((r) => buildListingFromRow(r, datasetYear, ctx))
}

function parseCli(argv: string[]) {
  let mergeExisting = false
  let replaceYear: number | undefined
  const paths: string[] = []
  const rest = [...argv]
  while (rest.length) {
    const a = rest.shift()
    if (a === undefined) break
    if (a === '--merge-existing') mergeExisting = true
    else if (a === '--replace-year') {
      const y = Number(rest.shift())
      if (!Number.isFinite(y)) {
        console.error('--replace-year requires a number (e.g. 2025)')
        process.exit(1)
      }
      replaceYear = y
    } else paths.push(a)
  }
  const csvPaths = paths.map((p) => (path.isAbsolute(p) ? p : path.resolve(process.cwd(), p)))
  return { mergeExisting, replaceYear, csvPaths }
}

async function main() {
  const { mergeExisting, replaceYear, csvPaths } = parseCli(process.argv.slice(2))

  if (!csvPaths.length && !mergeExisting) {
    console.error(
      'Usage:\n  npm run import:clickup -- "<export>.csv"\n  npm run import:clickup -- --merge-existing [--replace-year 2025] "<Properties 2025.csv>"\n\nFilenames should contain "Properties YYYY" so the cohort year is inferred.',
    )
    process.exit(1)
  }

  let existing: DashboardData | null = null
  if (mergeExisting) {
    const mod = await import('../src/data/generated/dashboardData.ts')
    existing = mod.dashboardData
  }

  const ownerByName = new Map<string, { id: string; name: string }>()
  let ownerCounter = 0

  if (existing) {
    ownerCounter = maxOwnerNumericId(existing.owners)
    for (const o of existing.owners) {
      ownerByName.set(norm(o.name), { id: o.id, name: o.name })
    }
  }

  const ensureOwner = (nameRaw: string) => {
    const name = nameRaw.trim()
    if (!name) return null
    const k = norm(name)
    const hit = ownerByName.get(k)
    if (hit) return hit
    ownerCounter += 1
    const id = `o_${ownerCounter}`
    const o = { id, name }
    ownerByName.set(k, o)
    return o
  }

  const listingById = new Map<string, Listing>()

  if (existing) {
    for (const l of existing.listings) {
      if (replaceYear !== undefined && l.datasetYear === replaceYear) continue
      const tagged: Listing = {
        ...l,
        datasetYear: l.datasetYear ?? DEFAULT_YEAR_FOR_EXISTING,
      }
      listingById.set(tagged.id, tagged)
    }
    if (replaceYear !== undefined) console.log(`Removed existing listings with datasetYear ${replaceYear} before import.`)
  }

  for (const csvPath of csvPaths) {
    if (!fs.existsSync(csvPath)) {
      console.error(`Missing file: ${csvPath}`)
      process.exit(1)
    }
    const year = inferDatasetYearFromFilename(csvPath)
    if (year === undefined) {
      console.error(`Could not infer year from filename (want "…Properties 2025…"): ${csvPath}`)
      process.exit(1)
    }
    console.log(`Importing ${path.basename(csvPath)} → datasetYear ${year}`)
    const listings = parseCsvFile(csvPath, year, { ensureOwner })
    for (const li of listings) {
      if (listingById.has(li.id)) {
        console.warn(`Duplicate Task ID ${li.id} — skipping row (already in dashboard)`)
        continue
      }
      listingById.set(li.id, li)
    }
  }

  const listings = Array.from(listingById.values())
  const owners: Owner[] = Array.from(ownerByName.values()).sort((a, b) => a.id.localeCompare(b.id))

  const outPath = path.join(process.cwd(), 'src', 'data', 'generated', 'dashboardData.ts')
  const file = `import type { DashboardData } from '../../types';
export const dashboardData: DashboardData = ${JSON.stringify({ owners, listings }, null, 2)} as unknown as DashboardData;
`

  fs.mkdirSync(path.dirname(outPath), { recursive: true })
  fs.writeFileSync(outPath, file, 'utf8')
  console.log(`Wrote ${outPath} with ${owners.length} owners and ${listings.length} listings`)
}

main()
