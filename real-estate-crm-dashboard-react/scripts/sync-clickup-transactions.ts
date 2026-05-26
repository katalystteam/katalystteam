/**
 * Pull property tasks from the ClickUp space "Transactions - Sales & Purchases"
 * (lists named like `Properties - 2026`, `Properties - 2025`, …).
 *
 * Requires `.env.local`:
 *   CLICKUP_API_TOKEN=pk_...   (or CLICKUP_API_KEY — same value)
 *   CLICKUP_SPACE_ID=90100208161   (space ID — URL …/v/s/SPACE_ID in ClickUp 3.0, or from API)
 *
 * Optional legacy: CLICKUP_FOLDER_ID — only if your lists live under a classic folder.
 *
 * Writes `src/data/generated/dashboardData.ts`.
 */
import fs from 'node:fs'
import path from 'node:path'
import dotenv from 'dotenv'

dotenv.config({ path: path.resolve(process.cwd(), '.env.local') })
dotenv.config()
import type { DashboardData, Listing, ListingAssoc, Owner } from '../src/types.ts'
import { normalizeAttorneyLine, splitPartyNames } from '../src/lib/parsePartyNames.ts'

const API = 'https://api.clickup.com/api/v2'

type CuCustomField = { id: string; name: string; type: string; value?: unknown }

type CuTask = {
  id: string
  name: string
  status?: { status?: string }
  date_updated?: string
  date_created?: string
  creator?: { username?: string; email?: string }
  custom_fields?: CuCustomField[]
}

function envOptional(name: string): string | undefined {
  const v = process.env[name]?.trim()
  return v || undefined
}

function clickUpToken(): string {
  const t =
    envOptional('CLICKUP_API_TOKEN') ?? envOptional('CLICKUP_API_KEY') ?? envOptional('clickup_api_key')
  if (!t) throw new Error('Set CLICKUP_API_TOKEN (or CLICKUP_API_KEY) in .env.local')
  return t
}

async function collectLists(token: string, spaceId: string): Promise<Array<{ id: string; name: string }>> {
  const seen = new Map<string, { id: string; name: string }>()
  const root = await cuFetch<{ lists?: Array<{ id: string; name: string }> }>(
    token,
    `/space/${spaceId}/list?archived=false`,
  )
  for (const l of root.lists ?? []) seen.set(l.id, l)

  const foldersWrap = await cuFetch<{ folders?: Array<{ id: string }> }>(
    token,
    `/space/${spaceId}/folder?archived=false`,
  )
  for (const folder of foldersWrap.folders ?? []) {
    const ld = await cuFetch<{ lists?: Array<{ id: string; name: string }> }>(
      token,
      `/folder/${folder.id}/list?archived=false`,
    )
    for (const l of ld.lists ?? []) seen.set(l.id, l)
  }
  return [...seen.values()]
}

async function cuFetch<T>(token: string, path: string): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    headers: { Authorization: token },
  })
  const text = await res.text()
  if (!res.ok) throw new Error(`${path} → ${res.status} ${text.slice(0, 400)}`)
  return JSON.parse(text) as T
}

function formatCfValue(f: CuCustomField): string {
  const v = f.value
  if (v == null || v === '') return ''
  if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') return String(v)
  if (Array.isArray(v)) {
    return v
      .map((x) => (typeof x === 'object' && x && 'name' in x ? String((x as { name: string }).name) : String(x)))
      .filter(Boolean)
      .join(', ')
  }
  if (typeof v === 'object' && v !== null && 'name' in v && typeof (v as { name: string }).name === 'string') {
    return (v as { name: string }).name
  }
  return ''
}

function pickCustomField(fields: CuCustomField[] | undefined, mustInclude: string): string {
  if (!fields?.length) return ''
  const needle = mustInclude.toLowerCase()
  for (const f of fields) {
    if (f.name.toLowerCase().includes(needle)) {
      const val = formatCfValue(f)
      if (val) return val
    }
  }
  return ''
}

function pickBuyerShort(fields: CuCustomField[] | undefined): string {
  if (!fields?.length) return ''
  for (const f of fields) {
    if (/^buyer\s*\(/i.test(f.name)) {
      const val = formatCfValue(f)
      if (val) return val
    }
  }
  for (const f of fields) {
    const n = f.name.toLowerCase()
    if (n.includes('buyer') && !n.includes('lender') && !n.includes('1031') && !n.includes('closing attorney')) {
      const val = formatCfValue(f)
      if (val) return val
    }
  }
  return ''
}

function pickSellerPrimary(fields: CuCustomField[] | undefined): string {
  if (!fields?.length) return ''
  for (const f of fields) {
    if (/^seller\s*\(/i.test(f.name)) {
      const val = formatCfValue(f)
      if (val) return val
    }
  }
  for (const f of fields) {
    const n = f.name.toLowerCase()
    if (n.includes('seller') && !n.includes('1031')) {
      const val = formatCfValue(f)
      if (val) return val
    }
  }
  return ''
}

function formatTimestamp(ms: string | undefined): string {
  if (!ms) return ''
  const n = Number(ms)
  if (!Number.isFinite(n)) return ''
  try {
    return new Date(n).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  } catch {
    return ''
  }
}

function inferYearFromListName(name: string): number | undefined {
  const m = name.match(/properties[^\d]*(\d{4})/i) ?? name.match(/(\d{4})/)
  if (!m) return undefined
  const y = Number(m[1])
  return y >= 2000 && y <= 2100 ? y : undefined
}

function norm(s: string) {
  return (s ?? '')
    .toLowerCase()
    .replaceAll('&', 'and')
    .replaceAll(',', ' ')
    .replaceAll('.', ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

async function fetchAllTasksForList(token: string, listId: string): Promise<CuTask[]> {
  const out: CuTask[] = []
  let page = 0
  for (;;) {
    const q = new URLSearchParams({
      page: String(page),
      include_closed: 'true',
      subtasks: 'false',
    })
    const data = await cuFetch<{ tasks?: CuTask[] }>(token, `/list/${listId}/task?${q}`)
    const batch = data.tasks ?? []
    out.push(...batch)
    if (batch.length < 100) break
    page += 1
  }
  return out
}

function taskToListing(task: CuTask, datasetYear: number | undefined, ctx: { ensureOwner: (name: string) => { id: string; name: string } | null }): Listing {
  const statusRaw = task.status?.status?.trim() || '—'
  const seller = pickSellerPrimary(task.custom_fields)
  const buyer = pickBuyerShort(task.custom_fields)
  const closingBuyer = pickCustomField(task.custom_fields, 'closing attorney - buyer')
  const lenderBuyer = pickCustomField(task.custom_fields, 'lender - buyer')
  const agentName = pickCustomField(task.custom_fields, 'agent')

  const ownersAssoc = splitPartyNames(seller)
    .map((n) => ctx.ensureOwner(n))
    .filter(Boolean)
    .map((o) => ({ id: o!.id, name: o!.name }))

  const attorney = normalizeAttorneyLine(closingBuyer)
  const lawyers = attorney ? [{ name: attorney }] : []
  const agents = agentName ? [{ name: agentName, role: 'Agent' as const }] : []

  const assoc: ListingAssoc = {
    owners: ownersAssoc,
    lawyers,
    agents,
    leads: [],
    transactions: [],
    documents: [],
  }

  return {
    id: task.id,
    name: task.name,
    address: task.name,
    status: statusRaw,
    datasetYear,
    dateUpdated: formatTimestamp(task.date_updated),
    createdBy: task.creator?.username || task.creator?.email || '',
    abstracting: pickCustomField(task.custom_fields, 'abstracting'),
    agent: agentName || undefined,
    buyer: buyer || undefined,
    closingAttorneyBuyer: closingBuyer || undefined,
    lenderBuyer: lenderBuyer || undefined,
    seller: seller || undefined,
    titleOpinion: pickCustomField(task.custom_fields, 'title opinion'),
    assoc,
  }
}

async function main() {
  const token = clickUpToken()
  const spaceId = envOptional('CLICKUP_SPACE_ID') ?? envOptional('CLICKUP_TRANSACTIONS_SPACE_ID')
  const folderId = envOptional('CLICKUP_FOLDER_ID')

  let lists: Array<{ id: string; name: string }> = []

  if (spaceId) {
    lists = await collectLists(token, spaceId)
    console.log(`Using space ${spaceId} — ${lists.length} list(s).`)
  } else if (folderId) {
    const folder = await cuFetch<{ lists?: Array<{ id: string; name: string }> }>(token, `/folder/${folderId}`)
    lists = folder.lists ?? []
    console.log(`Using folder ${folderId} — ${lists.length} list(s).`)
  } else {
    console.error('Set CLICKUP_SPACE_ID to your "Transactions - Sales & Purchases" space ID (see .env.example).')
    process.exit(1)
  }

  if (!lists.length) {
    console.error('No lists found. Add lists named e.g. Properties - 2026 under the space.')
    process.exit(1)
  }

  const ownerByName = new Map<string, { id: string; name: string }>()
  let ownerCounter = 0

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

  for (const list of lists) {
    const year = inferYearFromListName(list.name)
    console.log(`List "${list.name}" → year ${year ?? '(none)'}`)
    const tasks = await fetchAllTasksForList(token, list.id)
    for (const t of tasks) {
      const li = taskToListing(t, year, { ensureOwner })
      listingById.set(li.id, li)
    }
  }

  const listings = Array.from(listingById.values())
  const owners: Owner[] = Array.from(ownerByName.values()).sort((a, b) => a.id.localeCompare(b.id))

  const data: DashboardData = { owners, listings }
  const outPath = path.join(process.cwd(), 'src', 'data', 'generated', 'dashboardData.ts')
  const file = `import type { DashboardData } from '../../types';
export const dashboardData: DashboardData = ${JSON.stringify(data, null, 2)} as unknown as DashboardData;
`
  fs.mkdirSync(path.dirname(outPath), { recursive: true })
  fs.writeFileSync(outPath, file, 'utf8')
  console.log(`Wrote ${outPath} — ${owners.length} owners, ${listings.length} listings`)

  const missingYear = listings.filter((l) => l.datasetYear === undefined).length
  if (missingYear) {
    console.warn(`Note: ${missingYear} tasks are missing datasetYear — rename lists to include the year (e.g. Properties 2026).`)
  }
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
