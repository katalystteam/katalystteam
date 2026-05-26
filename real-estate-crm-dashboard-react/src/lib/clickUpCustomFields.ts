/** Parse ClickUp task custom field payloads (dropdown indices, labels, etc.). */

export type ClickUpCustomField = {
  id: string
  name: string
  type: string
  value?: unknown
  type_config?: {
    options?: Array<{ id?: string; name?: string; orderindex?: number }>
  }
}

function formatCurrencyValue(v: unknown, currency = 'USD'): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return ''
  return new Intl.NumberFormat('en-US', { style: 'currency', currency, maximumFractionDigits: 0 }).format(n)
}

function formatDateValue(v: unknown): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return ''
  try {
    return new Date(n).toLocaleDateString('en-US', { dateStyle: 'medium' })
  } catch {
    return ''
  }
}

export function formatClickUpCustomField(f: ClickUpCustomField): string {
  const v = f.value
  if (v == null || v === '') return ''

  if (f.type === 'currency') {
    const cfg = f.type_config as { currency_type?: string } | undefined
    return formatCurrencyValue(v, cfg?.currency_type ?? 'USD')
  }

  if (f.type === 'date') {
    return formatDateValue(v)
  }

  if (f.type === 'number') {
    const n = Number(v)
    if (!Number.isFinite(n)) return ''
    const name = f.name.toLowerCase()
    if (name.includes('rate') || name.includes('%')) return `${n}%`
    return String(n)
  }

  if (f.type === 'drop_down') {
    const opts = f.type_config?.options ?? []
    if (typeof v === 'number') {
      const byIndex = opts.find((o) => o.orderindex === v) ?? opts[v]
      return (byIndex?.name ?? '').trim()
    }
    if (typeof v === 'string') {
      const byId = opts.find((o) => o.id === v)
      if (byId?.name) return byId.name.trim()
      const byName = opts.find((o) => o.name === v)
      if (byName?.name) return byName.name.trim()
      return v.trim()
    }
  }

  if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') {
    return String(v).trim()
  }

  if (Array.isArray(v)) {
    return v
      .map((x) => {
        if (typeof x === 'object' && x && 'name' in x) return String((x as { name: string }).name)
        if (typeof x === 'object' && x && 'username' in x) return String((x as { username: string }).username)
        return String(x)
      })
      .filter(Boolean)
      .join(', ')
  }

  if (typeof v === 'object' && v !== null && 'name' in v && typeof (v as { name: string }).name === 'string') {
    return (v as { name: string }).name.trim()
  }

  return ''
}

/** Match field name exactly (case-insensitive), ignoring parenthetical suffixes. */
export function fieldBaseName(name: string): string {
  return name.trim().replace(/\s*\([^)]*\)\s*$/i, '').trim().toLowerCase()
}

export function pickFieldByBaseName(fields: ClickUpCustomField[] | undefined, baseName: string): string {
  if (!fields?.length) return ''
  const want = baseName.toLowerCase()
  for (const f of fields) {
    if (fieldBaseName(f.name) === want) {
      const val = formatClickUpCustomField(f)
      if (val) return val
    }
  }
  return ''
}

export function pickFieldIncluding(
  fields: ClickUpCustomField[] | undefined,
  mustInclude: string,
  exclude: string[] = [],
): string {
  if (!fields?.length) return ''
  const needle = mustInclude.toLowerCase()
  for (const f of fields) {
    const n = f.name.toLowerCase()
    if (exclude.some((ex) => n.includes(ex))) continue
    if (n.includes(needle)) {
      const val = formatClickUpCustomField(f)
      if (val) return val
    }
  }
  return ''
}
