import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import type { Listing } from '../../types'
import { Avatar } from '../../components/Avatar'
import { clickUpStatusBadgeClass } from '../../lib/clickUpStatus'
import { DROPBOX_LINK_PLACEHOLDER, listingDetailFields } from '../../lib/listingDetails'

function formatEngagementScore(value: number | null | undefined): string | null {
  if (typeof value === 'number' && !Number.isNaN(value)) return String(Math.round(Math.min(100, Math.max(0, value))))
  return null
}

export function ListingAssocPanel({ listing }: { listing: Listing }) {
  const a = listing.assoc
  const eng = a.engagement
  const detailRows = listingDetailFields(listing)
  const [openContactIds, setOpenContactIds] = useState<Record<string, boolean>>({})

  const topContacts = useMemo(() => {
    const arr = eng?.ghlTopContacts ?? []
    return [...arr].sort((x, y) => (y.score ?? 0) - (x.score ?? 0)).slice(0, 10)
  }, [eng?.ghlTopContacts])

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
          {detailRows.length ? (
            detailRows.map((row) => (
              <div key={row.label} style={{ marginBottom: 10 }}>
                <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--color-text-tertiary)', marginBottom: 3 }}>
                  {row.label}
                </div>
                <div style={{ fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.45 }}>{row.value}</div>
              </div>
            ))
          ) : (
            <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', padding: '4px 0' }}>No ClickUp fields filled in.</div>
          )}
        </div>
      </div>

      <div className="assoc-section">
        <div className="assoc-section-label">Notes</div>
        {listing.notes?.trim() ? (
          <div
            style={{
              fontSize: 12,
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              lineHeight: 1.5,
              padding: '8px 10px',
              borderRadius: 'var(--border-radius-md)',
              border: '1px solid var(--color-border-tertiary)',
              background: 'var(--color-background-primary)',
            }}
          >
            {listing.notes}
          </div>
        ) : (
          <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', padding: '4px 0' }}>
            No description in ClickUp for this property.
          </div>
        )}
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
              <Avatar name={x.name.split(/\n/)[0] ?? x.name} kind="lawyer" />
              <div>
                <div className="assoc-name" style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                  {x.name}
                </div>
                {x.firm ? <div className="assoc-sub">{x.firm}</div> : null}
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
                <div className="assoc-sub">
                  {eng?.ghlCampaigns?.length
                    ? 'Email campaign opens + clicks (matched by property in blast HTML)'
                    : 'Contacts engaging with posts tied to this property'}
                </div>
              </div>
            </div>
            {formatEngagementScore(eng?.ghlScore) !== null ? (
              <span className="engagement-score">
                {formatEngagementScore(eng?.ghlScore)}
                <span style={{ fontSize: 11, fontWeight: 500, color: 'var(--color-text-tertiary)' }}>/100</span>
              </span>
            ) : (
              <span className="engagement-score-muted" title="Run npm run sync:ghl-campaigns or tag contacts in GHL">
                —
              </span>
            )}
          </div>
          {topContacts.length ? (
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--color-text-tertiary)', marginBottom: 6 }}>
                Top contacts
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {topContacts.map((c, idx) => {
                  const isOpen = Boolean(openContactIds[c.id])
                  return (
                    <button
                      key={c.id}
                      type="button"
                      onClick={() => setOpenContactIds((m) => ({ ...m, [c.id]: !m[c.id] }))}
                      style={{
                        textAlign: 'left',
                        padding: '8px 10px',
                        borderRadius: 'var(--border-radius-md)',
                        border: '1px solid var(--color-border-tertiary)',
                        background: 'var(--color-background-primary)',
                        cursor: 'pointer',
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'baseline' }}>
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontSize: 12, fontWeight: 700, lineHeight: 1.2, wordBreak: 'break-word' }}>
                            {idx + 1}. {c.name || 'Unknown contact'}
                          </div>
                          <div style={{ fontSize: 10, color: 'var(--color-text-tertiary)', marginTop: 3 }}>
                            {c.opened} opens · {c.clicked} clicks · score {c.score}
                          </div>
                        </div>
                        <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--color-text-tertiary)' }}>
                          {isOpen ? 'Hide' : 'View'}
                        </div>
                      </div>
                      {isOpen ? (
                        <div style={{ marginTop: 8, fontSize: 11, color: 'var(--color-text-secondary)' }}>
                          {c.email ? (
                            <div style={{ marginBottom: 4 }}>
                              <span style={{ fontWeight: 700 }}>Email:</span> {c.email}
                            </div>
                          ) : null}
                          {c.phone ? (
                            <div style={{ marginBottom: 4 }}>
                              <span style={{ fontWeight: 700 }}>Phone:</span> {c.phone}
                            </div>
                          ) : null}
                          {!c.email && !c.phone ? (
                            <div style={{ color: 'var(--color-text-tertiary)' }}>No contact info in export.</div>
                          ) : null}
                        </div>
                      ) : null}
                    </button>
                  )
                })}
              </div>
              <div style={{ fontSize: 10, color: 'var(--color-text-tertiary)', marginTop: 6, lineHeight: 1.35 }}>
                Imported from GHL “Email Statistics Details” export (local-only).
              </div>
            </div>
          ) : null}
          {eng?.ghlCampaigns?.length ? (
            <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
              {eng.ghlCampaigns.map((c) => (
                <div
                  key={c.campaignId}
                  style={{
                    padding: '8px 10px',
                    borderRadius: 'var(--border-radius-md)',
                    border: '1px solid var(--color-border-tertiary)',
                    background: 'var(--color-background-primary)',
                  }}
                >
                  <div style={{ fontSize: 12, fontWeight: 600, lineHeight: 1.35 }}>{c.name}</div>
                  {c.subject ? (
                    <div style={{ fontSize: 11, color: 'var(--color-text-secondary)', marginTop: 2 }}>{c.subject}</div>
                  ) : null}
                  <div style={{ fontSize: 10, color: 'var(--color-text-tertiary)', marginTop: 4 }}>
                    {c.sentAt ? `Sent ${c.sentAt}` : 'Sent'} · {c.stats.delivered} delivered
                  </div>
                  <div style={{ display: 'flex', gap: 12, marginTop: 6, fontSize: 11 }}>
                    <span>
                      <strong>{c.stats.opened}</strong> opens ({c.stats.openRate.toFixed(1)}%)
                    </span>
                    <span>
                      <strong>{c.stats.clicked}</strong> clicks ({c.stats.clickRate.toFixed(1)}%)
                    </span>
                  </div>
                </div>
              ))}
            </div>
          ) : null}
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

      <Section label="Documents" empty="None added">
        {a.documents.map((x, idx) => (
          <div className="assoc-item" key={`${x.name}-${idx}`}>
            <div className="assoc-item-left" style={{ flex: 1, minWidth: 0 }}>
              <div style={{ minWidth: 0 }}>
                {x.name === DROPBOX_LINK_PLACEHOLDER && !x.url ? (
                  <span className="assoc-doc-link assoc-doc-placeholder">{DROPBOX_LINK_PLACEHOLDER}</span>
                ) : x.url ? (
                  <a className="assoc-doc-link" href={x.url} target="_blank" rel="noopener noreferrer" title={x.url}>
                    {x.name}
                  </a>
                ) : (
                  <div className="assoc-name">{x.name}</div>
                )}
              </div>
            </div>
            {x.name === DROPBOX_LINK_PLACEHOLDER && !x.url ? (
              <span style={{ fontSize: 10, color: 'var(--color-text-tertiary)' }}>Pending</span>
            ) : x.status ? (
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
