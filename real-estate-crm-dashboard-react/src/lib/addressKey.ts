import { normalizeAddressKey } from './normalizeAddressKey'

/** Match listing addresses to keys in `siteImages.byNormalizedAddress`. */
export function addressKey(raw: string): string {
  return normalizeAddressKey(raw)
}
