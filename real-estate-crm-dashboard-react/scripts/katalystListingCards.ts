import { normalizeAddressKey } from '../src/lib/normalizeAddressKey.ts'

export type SiteListing = {
  addressText: string
  listingUrl: string
  imageUrl: string
}

function decodeHtmlEntities(s: string) {
  return s
    .replaceAll('&amp;', '&')
    .replaceAll('&nbsp;', ' ')
    .replaceAll('&#8217;', "'")
    .replaceAll('&#8211;', '-')
    .replaceAll('&#038;', '&')
    .replaceAll('&quot;', '"')
}

/** Sold LYSTings uses bare `<figure><img>` (no link); address is in the preceding cover `<p>`. */
function extractAddressBefore(html: string, containerIndex: number): string | null {
  const window = html.slice(Math.max(0, containerIndex - 16000), containerIndex)
  const paras = [...window.matchAll(/<p[^>]*class="[^"]*has-contrast-light[^"]*"[^>]*>([^<]+)<\/p>/gi)]
  for (let i = paras.length - 1; i >= 0; i--) {
    const t = decodeHtmlEntities((paras[i][1] ?? '').trim())
    if (!/\d/.test(t) || t.length < 8 || t.length > 200) continue
    if (/sale price|lot size|cap rate|building size|year built|transactions done/i.test(t)) continue
    return t
  }
  return null
}

function addressFromListingHref(href: string): string | null {
  try {
    const u = new URL(href)
    const q = u.searchParams.get('wpf6458_10')
    if (q) return decodeURIComponent(q.replace(/\+/g, ' '))
  } catch {
    /* relative URL */
  }
  const m = href.match(/[?&]wpf6458_10=([^&]+)/)
  if (m) {
    try {
      return decodeURIComponent(m[1].replace(/\+/g, ' '))
    } catch {
      return m[1].replace(/\+/g, ' ')
    }
  }
  return null
}

export function extractFromHtml(html: string): SiteListing[] {
  const results: SiteListing[] = []

  const cardRe =
    /<div class="wp-block-group lysting-link-container[^"]*"[^>]*>([\s\S]*?)<\/div>\s*<\/div>/gi

  for (const m of html.matchAll(cardRe)) {
    const idx = m.index ?? 0
    const chunk = m[1] ?? ''

    const linked = chunk.match(
      /<figure[^>]*>[\s\S]*?<a\s+href="([^"]+)"[\s\S]*?<img[^>]*\ssrc="([^"]+)"/i,
    )
    const bare = chunk.match(/<figure[^>]*>[\s\S]*?<img[^>]*\ssrc="([^"]+)"/i)

    let listingUrl = 'https://katalystteam.com/'
    let imageUrl = ''
    let addressText: string | null = null

    if (linked) {
      listingUrl = linked[1].startsWith('http') ? linked[1] : `https://katalystteam.com${linked[1]}`
      imageUrl = linked[2]
      addressText = addressFromListingHref(listingUrl) ?? extractAddressBefore(html, idx)
    } else if (bare) {
      imageUrl = bare[1]
      addressText = extractAddressBefore(html, idx)
    }

    if (!imageUrl || !addressText?.trim()) continue
    results.push({ addressText: addressText.trim(), listingUrl, imageUrl })
  }

  return results
}

export function buildSiteImagesMapping(items: SiteListing[]) {
  const byNormalizedAddress: Record<string, { imageUrl: string; listingUrl: string; addressText: string }> = {}
  for (const it of items) {
    const k = normalizeAddressKey(it.addressText)
    if (!k) continue
    byNormalizedAddress[k] = { imageUrl: it.imageUrl, listingUrl: it.listingUrl, addressText: it.addressText }
  }
  return { byNormalizedAddress }
}
