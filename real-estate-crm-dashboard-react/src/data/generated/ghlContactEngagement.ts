/** Generated locally — safe default checked into git (no PII). */
export type GhlContactEngagementRow = {
  id: string
  name: string
  email?: string
  phone?: string
  opened: number
  clicked: number
  score: number
}

export const ghlContactEngagementByListingId: Record<string, { contacts: GhlContactEngagementRow[] }> = {}

