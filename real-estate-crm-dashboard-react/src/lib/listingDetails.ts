import type { Listing } from '../types'

export const DROPBOX_LINK_PLACEHOLDER = 'Dropbox link'

export function listingDisplayPrice(listing: Listing): string {
  return listing.lystingPrice || listing.purchasePrice || listing.price || '—'
}

/** ClickUp custom fields for the property details panel (only non-empty). */
export function listingDetailFields(listing: Listing): { label: string; value: string }[] {
  const pairs: Array<[string, string | undefined]> = [
    ['LYSTing price', listing.lystingPrice],
    ['Purchase price', listing.purchasePrice],
    ['# of units', listing.unitCount],
    ['Appraisal company', listing.appraisalCompany],
    ['Appraisal date', listing.appraisalDate],
    ['Earnest money', listing.earnestMoney],
    ['Closing credit', listing.closingCredit],
    ['Closing date', listing.closingDate],
    ['Commission amount', listing.commissionAmount],
    ['Commission rate', listing.commissionRate],
    ['Double side', listing.doubleSide],
    ['Due diligence end', listing.dueDiligenceEnd],
    ['Inspection date', listing.inspectionDate],
    ['Abstracting', listing.abstracting],
    ['Agent', listing.agent],
    ['Buyer', listing.buyer],
    ['Seller', listing.seller],
    ['Lender — buyer', listing.lenderBuyer],
    ['Lender — seller', listing.lenderSeller],
    ['Closing attorney — buyer', listing.closingAttorneyBuyer],
    ['Closing attorney — seller', listing.closingAttorneySeller],
    ['1031 exchange — buyer', listing.exchange1031Buyer],
    ['1031 exchange — seller', listing.exchange1031Seller],
    ['Title opinion', listing.titleOpinion],
    ['Tags', listing.tags],
    ['Date updated', listing.dateUpdated],
    ['Created by', listing.createdBy],
  ]
  return pairs
    .filter(([, v]) => v?.trim())
    .map(([label, value]) => ({ label, value: value!.trim() }))
}
