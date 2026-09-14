/**
 * Reads the "Want to Meet With / Research" block (Name / Called / Notes-Tasks / RealNex Notes)
 * from each new weekly tab of Jared's "Weekly To-Do's" Google Sheet and pushes a GHL note
 * for every row where Called=TRUE and Notes/Tasks has text, matched to a GHL contact by name.
 *
 * Tabs are named e.g. "9.14.26 Economics" (no zero-padding), one per Monday.
 *
 * Setup:
 *   cp .env.example .env.local   # add GHL_API_TOKEN, GHL_LOCATION_ID, CALL_NOTES_SHEET_ID,
 *                                 # GOOGLE_OAUTH_CLIENT_ID/SECRET/REFRESH_TOKEN (never commit)
 *   Reads the sheet as whichever Google account authorized the refresh token — that account
 *   already needs view access (e.g. it's the sheet owner).
 *   npm run sync:call-notes-to-ghl -- --dry-run   # preview without writing to GHL
 *   npm run sync:call-notes-to-ghl                # push notes + advance the checkpoint
 *
 * Checkpoint: scripts/.ghl-call-notes-checkpoint.json — the last fully-synced tab.
 * Rows whose name can't be matched with high confidence to exactly one GHL contact are
 * skipped and reported, never pushed on a guess.
 */
import fs from 'node:fs'
import path from 'node:path'
import { config } from 'dotenv'

config({ path: path.join(process.cwd(), '.env.local') })
config({ path: path.join(process.cwd(), '..', '.env.local') })

const GHL_BASE_URL = process.env.GHL_BASE_URL ?? 'https://services.leadconnectorhq.com'
const GHL_API_VERSION = '2021-07-28'
const CHECKPOINT_PATH = path.join(process.cwd(), 'scripts', '.ghl-call-notes-checkpoint.json')
const DRY_RUN = process.argv.includes('--dry-run')

type SheetRow = string[]

type CallNoteRow = {
  tab: string
  name: string
  called: boolean
  notesTasks: string
}

type Checkpoint = { lastSyncedTab: string; lastSyncedAt: string }

function ghlHeaders(): HeadersInit {
  return {
    Authorization: `Bearer ${process.env.GHL_API_TOKEN ?? ''}`,
    'Content-Type': 'application/json',
    Version: GHL_API_VERSION,
  }
}

// --- Google OAuth (user refresh token, not a service-account key) ---

async function googleAccessToken(): Promise<string> {
  const clientId = process.env.GOOGLE_OAUTH_CLIENT_ID
  const clientSecret = process.env.GOOGLE_OAUTH_CLIENT_SECRET
  const refreshToken = process.env.GOOGLE_OAUTH_REFRESH_TOKEN
  if (!clientId || !clientSecret || !refreshToken) {
    throw new Error('Missing GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET, or GOOGLE_OAUTH_REFRESH_TOKEN')
  }

  const res = await fetch('https://oauth2.googleapis.com/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'refresh_token',
      client_id: clientId,
      client_secret: clientSecret,
      refresh_token: refreshToken,
    }),
  })
  if (!res.ok) throw new Error(`Google token refresh failed: ${res.status} ${await res.text()}`)
  const data = (await res.json()) as { access_token: string }
  return data.access_token
}

async function fetchSheetTabTitles(sheetId: string, token: string): Promise<string[]> {
  const res = await fetch(`https://sheets.googleapis.com/v4/spreadsheets/${sheetId}?fields=sheets.properties.title`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error(`Sheets API (list tabs) ${res.status}: ${await res.text()}`)
  const data = (await res.json()) as { sheets?: { properties?: { title?: string } }[] }
  return (data.sheets ?? []).map((s) => s.properties?.title ?? '').filter(Boolean)
}

async function fetchTabValues(sheetId: string, tab: string, token: string): Promise<SheetRow[]> {
  const range = encodeURIComponent(`'${tab}'`)
  const res = await fetch(`https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values/${range}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error(`Sheets API (values ${tab}) ${res.status}: ${await res.text()}`)
  const data = (await res.json()) as { values?: SheetRow[] }
  return data.values ?? []
}

// --- Tab naming: "M.D.YY Economics" (no zero-padding), one per Monday ---

function parseTabDate(title: string): Date | null {
  const m = title.match(/^(\d{1,2})\.(\d{1,2})\.(\d{2})\s+Economics\s*$/i)
  if (!m) return null
  const [, mo, day, yy] = m
  return new Date(2000 + Number(yy), Number(mo) - 1, Number(day))
}

// --- Extract the "Want to Meet With / Research" block from a tab's values ---

function extractCallNoteRows(tab: string, rows: SheetRow[]): CallNoteRow[] {
  let headerRow = -1
  let calledCol = -1
  for (let r = 0; r < rows.length; r++) {
    const c = rows[r].findIndex((cell) => (cell ?? '').trim().toLowerCase() === 'called')
    if (c > 0) {
      headerRow = r
      calledCol = c
      break
    }
  }
  if (headerRow === -1) return []

  const nameCol = calledCol - 1
  const notesCol = calledCol + 1

  const out: CallNoteRow[] = []
  let blankStreak = 0
  for (let r = headerRow + 1; r < rows.length; r++) {
    const row = rows[r]
    const name = (row[nameCol] ?? '').trim()
    if (!name) {
      blankStreak++
      if (blankStreak >= 5) break
      continue
    }
    blankStreak = 0
    const called = (row[calledCol] ?? '').trim().toUpperCase() === 'TRUE'
    const notesTasks = (row[notesCol] ?? '').trim()
    out.push({ tab, name, called, notesTasks })
  }
  return out
}

// --- Fuzzy name matching against GHL contacts ---

function normalizeName(s: string): string {
  return s
    .toLowerCase()
    .replace(/["']/g, '')
    .replace(/[^a-z0-9\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

async function searchGhlContacts(locationId: string, query: string): Promise<{ id: string; name: string }[]> {
  const params = new URLSearchParams({ locationId, query, limit: '10' })
  const res = await fetch(`${GHL_BASE_URL}/contacts/?${params}`, { headers: ghlHeaders() })
  if (!res.ok) throw new Error(`GHL contact search ${res.status}: ${await res.text()}`)
  const data = (await res.json()) as { contacts?: Record<string, unknown>[] }
  return (data.contacts ?? []).map((c) => ({
    id: String(c.id ?? ''),
    name: [c.firstName, c.lastName].filter(Boolean).join(' ') || String(c.name ?? ''),
  }))
}

/** Returns the single exact-normalized-name match, or null if zero or multiple candidates. */
function pickExactMatch(candidates: { id: string; name: string }[], sheetName: string): { id: string; name: string } | null {
  const target = normalizeName(sheetName)
  const exact = candidates.filter((c) => normalizeName(c.name) === target)
  return exact.length === 1 ? exact[0] : null
}

async function pushGhlNote(contactId: string, body: string): Promise<void> {
  const res = await fetch(`${GHL_BASE_URL}/contacts/${contactId}/notes`, {
    method: 'POST',
    headers: ghlHeaders(),
    body: JSON.stringify({ body }),
  })
  if (!res.ok) throw new Error(`GHL create note ${res.status}: ${await res.text()}`)
}

// --- Checkpoint ---

function loadCheckpoint(): Checkpoint {
  if (!fs.existsSync(CHECKPOINT_PATH)) {
    throw new Error(`Missing checkpoint file at ${CHECKPOINT_PATH}`)
  }
  return JSON.parse(fs.readFileSync(CHECKPOINT_PATH, 'utf8')) as Checkpoint
}

function saveCheckpoint(tab: string) {
  const data: Checkpoint = { lastSyncedTab: tab, lastSyncedAt: new Date().toISOString() }
  fs.writeFileSync(CHECKPOINT_PATH, JSON.stringify(data, null, 2) + '\n', 'utf8')
}

// --- Main ---

async function main() {
  const sheetId = process.env.CALL_NOTES_SHEET_ID
  const locationId = process.env.GHL_LOCATION_ID
  if (!sheetId || !locationId || !process.env.GHL_API_TOKEN) {
    console.error('Missing CALL_NOTES_SHEET_ID, GHL_LOCATION_ID, or GHL_API_TOKEN. Copy .env.example → .env.local.')
    process.exit(1)
  }

  const checkpoint = loadCheckpoint()
  const lastSyncedDate = parseTabDate(checkpoint.lastSyncedTab)
  if (!lastSyncedDate) throw new Error(`Bad checkpoint tab name: ${checkpoint.lastSyncedTab}`)

  // Only sync fully-elapsed weeks: exclude the current in-progress week's tab.
  const now = new Date()
  const startOfThisWeek = new Date(now)
  startOfThisWeek.setDate(now.getDate() - now.getDay() + 1) // most recent Monday
  startOfThisWeek.setHours(0, 0, 0, 0)

  const token = await googleAccessToken()
  const titles = await fetchSheetTabTitles(sheetId, token)

  const pending = titles
    .map((title) => ({ title, date: parseTabDate(title) }))
    .filter((t): t is { title: string; date: Date } => t.date != null)
    .filter((t) => t.date > lastSyncedDate && t.date < startOfThisWeek)
    .sort((a, b) => a.date.getTime() - b.date.getTime())

  if (pending.length === 0) {
    console.log(`Nothing new since checkpoint "${checkpoint.lastSyncedTab}".`)
    return
  }

  let pushed = 0
  let skippedNoMatch = 0
  let latestSyncedTab = checkpoint.lastSyncedTab

  for (const { title } of pending) {
    const rows = await fetchTabValues(sheetId, title, token)
    const callNotes = extractCallNoteRows(title, rows).filter((r) => r.called && r.notesTasks)
    console.log(`\n${title}: ${callNotes.length} called row(s) with notes`)

    for (const row of callNotes) {
      const candidates = await searchGhlContacts(locationId, row.name)
      const match = pickExactMatch(candidates, row.name)
      if (!match) {
        skippedNoMatch++
        console.log(`  SKIP (no confident GHL match): "${row.name}" — ${candidates.length} candidate(s)`)
        continue
      }

      const noteBody = `[${title}] ${row.notesTasks}`
      if (DRY_RUN) {
        console.log(`  DRY-RUN would push note to ${match.name} (${match.id}): ${noteBody}`)
      } else {
        await pushGhlNote(match.id, noteBody)
        console.log(`  pushed note to ${match.name} (${match.id})`)
      }
      pushed++
    }

    if (!DRY_RUN) latestSyncedTab = title
  }

  console.log(`\nDone. ${pushed} note(s) ${DRY_RUN ? 'would be pushed' : 'pushed'}, ${skippedNoMatch} skipped (no confident match).`)

  if (!DRY_RUN) {
    saveCheckpoint(latestSyncedTab)
    console.log(`Checkpoint advanced to "${latestSyncedTab}".`)
  } else {
    console.log('Dry run — checkpoint not advanced.')
  }
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
