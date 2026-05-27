/** CRM pipeline slug used for lead rows only (not ClickUp listing workflow). */
export type ListingStatus = 'active' | 'pending' | 'sold' | 'inactive'

export type Owner = {
  id: string
  name: string
  phone?: string
  email?: string
  notes?: string
}

export type AssocPerson = { name: string }

export type GhlCampaignStats = {
  sent: number
  delivered: number
  opened: number
  clicked: number
  openRate: number
  clickRate: number
}

export type GhlMatchedCampaign = {
  campaignId: string
  bulkRequestId: string
  name: string
  subject: string
  sentAt: string | null
  stats: GhlCampaignStats
}

export type GhlContactEngagement = {
  id: string
  name: string
  email?: string
  phone?: string
  opened: number
  clicked: number
  score: number
}

/** Optional per-listing engagement (wire to GHL + Meta APIs later). Scores are typically 0–100. */
export type ListingEngagement = {
  /** GoHighLevel: contacts engaging with property-related content */
  ghlScore?: number | null
  /** Facebook / paid social interactions on property ads */
  socialScore?: number | null
  /** Email blasts matched to this property via GHL campaign HTML */
  ghlCampaigns?: GhlMatchedCampaign[]
  /** Top engaging contacts (imported from GHL Email Statistics Details export). */
  ghlTopContacts?: GhlContactEngagement[]
}

/** Listing document row: optional `url` opens the file (e.g. OM PDF from katalystteam.com). */
export type ListingDocument = {
  name: string
  status?: 'Verified' | 'Pending' | 'In progress'
  url?: string
}

export type ListingAssoc = {
  owners: Array<{ id: string; name: string }>
  lawyers: Array<{ name: string; firm?: string }>
  agents: Array<{ name: string; role?: string }>
  leads: Array<{ name: string; status?: 'Hot' | 'Warm' | 'Cold' }>
  transactions: Array<{ desc: string; amount?: string; date?: string }>
  documents: ListingDocument[]
  engagement?: ListingEngagement
}

export type Listing = {
  id: string
  /** ClickUp task name — property title. */
  name: string
  address: string
  /**
   * ClickUp workflow status (exact string from workspace: Closed, lysted, due diligence, …).
   */
  status: string
  /** Export cohort / list year (Properties 2026, etc.). */
  datasetYear?: number
  /** ClickUp `Date Updated` */
  dateUpdated?: string
  /** ClickUp `Created By` */
  createdBy?: string
  abstracting?: string
  /** Primary listing agent (drop-down). */
  agent?: string
  buyer?: string
  closingAttorneyBuyer?: string
  closingAttorneySeller?: string
  lenderBuyer?: string
  lenderSeller?: string
  seller?: string
  titleOpinion?: string
  /** ClickUp task description (text_content). */
  notes?: string
  lystingPrice?: string
  purchasePrice?: string
  unitCount?: string
  appraisalCompany?: string
  appraisalDate?: string
  closingCredit?: string
  closingDate?: string
  commissionAmount?: string
  commissionRate?: string
  doubleSide?: string
  dueDiligenceEnd?: string
  earnestMoney?: string
  inspectionDate?: string
  exchange1031Buyer?: string
  exchange1031Seller?: string
  tags?: string
  imageUrl?: string
  listingUrl?: string
  /** Card display — LYSTing price, else purchase price. */
  price?: string
  type?: string
  sqm?: string
  assoc: ListingAssoc
}

export type DashboardData = {
  owners: Owner[]
  listings: Listing[]
}
