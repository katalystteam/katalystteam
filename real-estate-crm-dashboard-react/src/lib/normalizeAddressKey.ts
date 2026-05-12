/** Same rules as `scripts/extract-site-images.ts` → keys match `siteImages.byNormalizedAddress`. */
export function normalizeAddressKey(raw: string): string {
  let s = (raw ?? '').trim()
  s = s.replace(/&amp;/gi, '&').replace(/&#038;/g, '&')
  return s
    .toLowerCase()
    .replace(/&/g, ' ')
    .replaceAll(',', ' ')
    .replaceAll('.', ' ')
    .replace(/\s+/g, ' ')
    .trim()
}
