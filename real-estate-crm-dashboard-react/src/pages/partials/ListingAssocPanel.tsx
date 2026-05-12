import { Link } from 'react-router-dom'
import type { Listing } from '../../types'
import { Avatar } from '../../components/Avatar'
import { clickUpStatusBadgeClass } from '../../lib/clickUpStatus'

function formatEngagementScore(value: number | null | undefined): string | null {
  if (typeof value === 'number' && !Number.isNaN(value)) return String(Math.round(Math.min(100, Math.max(0, value))))
  return null
}

function DetailRow({ label, value }: { label: string; value?: string }) {
  const v = value?.trim()
  if (!v) return null
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--color-text-tertiary)', marginBottom: 3 }}>{label}</div>
      <div style={{ fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.45 }}>{v}</div>
    </div>
  )
}

export function ListingAssocPanel({ listing }: { listing: Listing }) {
  const a = listing.assoc
  const eng = a.engagement

  const Section = ({
    label,
    children,
    empty = 'None added',
  }: {
    label: string
    children: React.ReactNode
    empty?: string
  }) => {
    const hasChildren = Array.isArray(children) ? children.length > 0 : Boolean(children)
    return (
      <div className="assoc-section">
        <div className="assoc-section-label">{label}</div>
        {hasChildren ? children : <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', padding: '4px 0' }}>{empty}</div>}
      </div>
    )
  }

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10, marginBottom: 12 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="assoc-listing-name">{listing.name}</div>
          <div className="assoc-listing-addr">{listing.address}</div>
        </div>
        <span className={clickUpStatusBadgeClass(listing.status)} style={{ flexShrink: 0 }}>
          {listing.status}
        </span>
      </div>

      <div className="assoc-section">
        <div className="assoc-section-label">Property details</div>
        <div style={{ padding: '4px 0' }}>
          <DetailRow label="Date updated" value={listing.dateUpdated} />
          <DetailRow label="Created by" value={listing.createdBy} />
          <DetailRow label="Abstracting" value={listing.abstracting} />
          <DetailRow label="Agent" value={listing.agent} />
          <DetailRow label="Buyer" value={listing.buyer} />
          <DetailRow label="Closing attorney — buyer" value={listing.closingAttorneyBuyer} />
          <DetailRow label="Lender — buyer" value={listing.lenderBuyer} />
          <DetailRow label="Seller" value={listing.seller} />
          <DetailRow label="Title opinion" value={listing.titleOpinion} />
        </div>
      </div>

      <Section label="Owners">
        {a.owners.map((o) => (
          <div className="assoc-item" key={o.id}>
            <div className="assoc-item-left">
              <Avatar name={o.name} kind="owner" />
              <div>
                <div className="assoc-name">{o.name}</div>
              </div>
            </div>
            <Link className="assoc-link" to={`/owners/${o.id}`}>
              View →
            </Link>
          </div>
        ))}
      </Section>

      <Section label="Lawyers">
        {a.lawyers.map((x, idx) => (
          <div className="assoc-item" key={`${x.name}-${idx}`}>
            <div className="assoc-item-left">
              <Avatar name={x.name} kind="lawyer" />
              <div>
                <div className="assoc-name">{x.name}</div>
                <div className="assoc-sub">{x.firm ?? ''}</div>
              </div>
            </div>
          </div>
        ))}
      </Section>

      <Section label="Agents">
        {a.agents.map((x, idx) => (
          <div className="assoc-item" key={`${x.name}-${idx}`}>
            <div className="assoc-item-left">
              <Avatar name={x.name} kind="agent" />
              <div>
                <div className="assoc-name">{x.name}</div>
                <div className="assoc-sub">{x.role ?? ''}</div>
              </div>
            </div>
          </div>
        ))}
      </Section>

      <Section label="Leads">
        {a.leads.map((x, idx) => (
          <div className="assoc-item" key={`${x.name}-${idx}`}>
            <div className="assoc-item-left">
              <Avatar name={x.name} kind="lead" />
              <div>
                <div className="assoc-name">{x.name}</div>
              </div>
            </div>
            <span
              style={{
                fontSize: 10,
                padding: '2px 7px',
                borderRadius: 10,
                fontWeight: 500,
                background: x.status === 'Hot' ? '#FCEBEB' : x.status === 'Warm' ? '#FAEEDA' : '#F1EFE8',
                color: x.status === 'Hot' ? '#791F1F' : x.status === 'Warm' ? '#633806' : '#5F5E5A',
              }}
            >
              {x.status ?? '—'}
            </span>
          </div>
        ))}
      </Section>

      <div className="assoc-section">
        <div className="assoc-section-label">Engagement tracker</div>
        <div className="assoc-subsection">
          <div className="assoc-subsection-title">From GHL</div>
          <div className="assoc-item">
            <div className="assoc-item-left" style={{ flex: 1, minWidth: 0 }}>
              <div>
                <div className="assoc-name">Engagement score</div>
                <div className="assoc-sub">Contacts engaging with posts tied to this property</div>
              </div>
            </div>
            {formatEngagementScore(eng?.ghlScore) !== null ? (
              <span className="engagement-score">
                {formatEngagementScore(eng?.ghlScore)}
                <span style={{ fontSize: 11, fontWeight: 500, color: 'var(--color-text-tertiary)' }}>/100</span>
              </span>
            ) : (
              <span className="engagement-score-muted" title="Wire GHL API + tag posts by property">
                —
              </span>
            )}
          </div>
        </div>
        <div className="assoc-subsection" style={{ marginTop: 8 }}>
          <div className="assoc-subsection-title">From Social Media</div>
          <div className="assoc-item">
            <div className="assoc-item-left" style={{ flex: 1, minWidth: 0 }}>
              <div>
                <div className="assoc-name">Engagement score</div>
                <div className="assoc-sub">Facebook interactions on property ads / posts</div>
              </div>
            </div>
            {formatEngagementScore(eng?.socialScore) !== null ? (
              <span className="engagement-score">
                {formatEngagementScore(eng?.socialScore)}
                <span style={{ fontSize: 11, fontWeight: 500, color: 'var(--color-text-tertiary)' }}>/100</span>
              </span>
            ) : (
              <span className="engagement-score-muted" title="Wire Meta Marketing API or manual CSV">
                —
              </span>
            )}
          </div>
        </div>
        <div className="assoc-sub" style={{ fontSize: 10, marginTop: 8, lineHeight: 1.45 }}>
          Connect GHL + Meta APIs to fill scores, or set engagement fields on each listing in your data file.
        </div>
      </div>

      <Section label="Transactions">
        {a.transactions.map((x, idx) => (
          <div className="assoc-item" key={`${x.desc}-${idx}`}>
            <div className="assoc-item-left">
              <div>
                <div className="assoc-name">{x.desc}</div>
                <div className="assoc-sub">
                  {(x.amount ?? '—') + ' · ' + (x.date ?? '—')}
                </div>
              </div>
            </div>
          </div>
        ))}
      </Section>

      <Section label="Documents">
        {a.documents.map((x, idx) => (
          <div className="assoc-item" key={`${x.name}-${idx}`}>
            <div className="assoc-item-left" style={{ flex: 1, minWidth: 0 }}>
              <div style={{ minWidth: 0 }}>
                {x.url ? (
                  <a className="assoc-doc-link" href={x.url} target="_blank" rel="noopener noreferrer" title={x.url}>
                    {x.name}
                  </a>
                ) : (
                  <div className="assoc-name">{x.name}</div>
                )}
              </div>
            </div>
            {x.status ? (
              <span
                style={{
                  fontSize: 10,
                  padding: '2px 7px',
                  borderRadius: 10,
                  fontWeight: 500,
                  background: x.status === 'Verified' ? '#EAF3DE' : '#FAEEDA',
                  color: x.status === 'Verified' ? '#27500A' : '#633806',
                }}
              >
                {x.status}
              </span>
            ) : x.url ? (
              <span style={{ fontSize: 10, fontWeight: 500, color: 'var(--color-text-tertiary)' }}>Open →</span>
            ) : (
              <span style={{ fontSize: 10, color: 'var(--color-text-tertiary)' }}>—</span>
            )}
          </div>
        ))}
      </Section>
    </>
  )
}
