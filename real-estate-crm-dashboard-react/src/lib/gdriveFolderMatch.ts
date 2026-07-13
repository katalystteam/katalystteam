import { normalizeAddressKey } from './normalizeAddressKey'

export type GdriveFolder = {
  id: string
  title: string
  url: string
}

const CITY_STOP = new Set([
  'des',
  'moines',
  'ia',
  'waterloo',
  'ankeny',
  'ames',
  'cedar',
  'rapids',
  'west',
  'city',
  'point',
  'grimes',
  'norwalk',
  'earlham',
  'carlisle',
  'altoona',
  'anamosa',
  'boone',
  'osage',
  'prairie',
  'donnellson',
  'madrid',
  'davenport',
  'clive',
  'urbandale',
  'bondurant',
  'webster',
  'falls',
  'adel',
  'belle',
  'plaine',
  'tonawanda',
  'austin',
  'tx',
])

/** Normalize property / Drive folder titles for fuzzy address matching. */
export function normalizeGdriveTitle(raw: string): string {
  let s = (raw ?? '').trim().toLowerCase()
  s = s.replace(/&amp;/gi, '&').replace(/&#038;/g, '&').replace(/&#39;/g, "'")
  s = s.replace(/\([^)]*\)/g, ' ')
  s = s.replace(/\s-\s*(listing|buyer|mobile home park)\s*$/i, '')
  s = s.replace(/\bportfolio\b/g, ' ')
  s = s.replace(/&/g, ' ')
  s = s.replaceAll(',', ' ').replaceAll('.', ' ').replace(/-/g, ' ')
  s = s.replace(/\b\d{5}\b/g, ' ')
  s = s.replace(
    /\b(st|street|ave|avenue|rd|road|blvd|boulevard|ct|court|dr|drive|ln|lane|hwy|highway|trce|trace|ste|suite|unit|pkwy)\b/g,
    ' ',
  )
  s = s.replace(/\s+/g, ' ').trim()
  return s
}

function primaryNumber(raw: string): string | null {
  const m = normalizeGdriveTitle(raw).match(/^(\d+)/)
  return m ? m[1] : null
}

function isPortfolioLike(raw: string): boolean {
  return /\bportfolio\b/i.test(raw) || /\btriangle court\b/i.test(raw)
}

function tokens(raw: string): string[] {
  return normalizeGdriveTitle(raw).split(' ').filter(Boolean)
}

/** Score how well a listing address matches a Drive folder title (0–1). */
export function gdriveMatchScore(address: string, folderTitle: string): number {
  const numA = primaryNumber(address)
  const numB = primaryNumber(folderTitle)
  const portfolioA = isPortfolioLike(address)
  const portfolioB = /\bportfolio\b/i.test(folderTitle)

  if (portfolioA) {
    if (numB && !portfolioB) return 0
    const taEarly = tokens(address)
    const tbEarly = tokens(folderTitle)
    const distinctiveA = taEarly.filter((t) => !CITY_STOP.has(t) && t !== 'portfolio' && !/^\d+$/.test(t))
    const distinctiveB = tbEarly.filter((t) => !CITY_STOP.has(t) && t !== 'portfolio' && !/^\d+$/.test(t))
    if (!distinctiveA.some((t) => distinctiveB.includes(t))) return 0
  } else if (numA) {
    if (!numB || numA !== numB) return 0
  } else if (numB) {
    return 0
  }

  const ta = tokens(address)
  const tb = tokens(folderTitle)
  const overlap = ta.filter((t) => tb.includes(t))
  const nameOverlap = overlap.filter((t) => !CITY_STOP.has(t) && !/^\d+$/.test(t))

  if (nameOverlap.length === 0 && overlap.length < 2) return 0

  return overlap.length / Math.max(ta.length, tb.length)
}

const MATCH_THRESHOLD = 0.45

/** Pick the best Drive folder for a listing address, if any. */
export function matchGdriveFolder(address: string, folders: readonly GdriveFolder[]): GdriveFolder | null {
  let best: GdriveFolder | null = null
  let bestScore = 0
  for (const folder of folders) {
    const score = gdriveMatchScore(address, folder.title)
    if (score > bestScore) {
      bestScore = score
      best = folder
    }
  }
  return best && bestScore >= MATCH_THRESHOLD ? best : null
}

/** Keys match `addressKey()` / `siteImages.byNormalizedAddress`. */
export function gdriveAddressKey(raw: string): string {
  return normalizeAddressKey(raw)
}
