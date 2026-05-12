import { useMemo } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useDashboardData } from '../data/useDashboardData'
import { clickUpStatusBadgeClass, isClickUpLysted } from '../lib/clickUpStatus'

function initials(name: string) {
  return name
    .split(' ')
    .filter(Boolean)
    .map((w) => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()
}

export function OwnerProfilePage() {
  const { ownerId } = useParams()
  const navigate = useNavigate()
  const { data } = useDashboardData()

  const owner = useMemo(() => data.owners.find((o) => o.id === ownerId) ?? null, [data.owners, ownerId])
  const owned = useMemo(
    () => data.listings.filter((l) => l.assoc.owners.some((ow) => ow.id === ownerId)),
    [data.listings, ownerId],
  )
  const lystedListings = useMemo(() => owned.filter((l) => isClickUpLysted(l.status)), [owned])
  const lawyers = useMemo(() => {
    const s = new Set<string>()
    for (const l of owned) {
      for (const x of l.assoc.lawyers) s.add(`${x.name}${x.firm ? ` — ${x.firm}` : ''}`)
    }
    return [...s]
  }, [owned])

  if (!owner) {
    return (
      <div className="owner-page">
        <button className="back-btn" onClick={() => navigate('/owners')}>
          Back
        </button>
        <div className="empty-state">Owner not found.</div>
      </div>
    )
  }

  return (
    <div className="owner-page">
      <button className="back-btn" onClick={() => navigate(-1)}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M19 12H5" />
          <polyline points="12 19 5 12 12 5" />
        </svg>
        Back
      </button>

      <div className="owner-header">
        <div className="owner-avatar-lg">{initials(owner.name)}</div>
        <div>
          <div className="owner-name">{owner.name}</div>
          <div className="owner-contact">
            {(owner.phone ?? '—') + ' · ' + (owner.email ?? '—')}
          </div>
        </div>
      </div>

      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-label">Total properties</div>
          <div className="stat-value">{owned.length}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Lysted listings</div>
          <div className="stat-value">{lystedListings.length}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Linked lawyers</div>
          <div className="stat-value">{lawyers.length}</div>
        </div>
      </div>

      <div className="owner-sections">
        <div className="owner-section full">
          <div className="owner-section-title">Owned properties</div>
          {owned.length ? (
            owned.map((l) => (
              <div className="prop-item" key={l.id}>
                <div>
                  <div className="prop-name">{l.name}</div>
                  <div className="prop-addr">
                    {l.address} · {l.type ?? '—'} · {l.sqm ?? '—'}
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span className={clickUpStatusBadgeClass(l.status)}>{l.status}</span>
                  <span style={{ fontSize: 13, fontWeight: 500 }}>{l.price ?? '—'}</span>
                </div>
              </div>
            ))
          ) : (
            <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>No properties linked.</div>
          )}
        </div>

        <div className="owner-section">
          <div className="owner-section-title">Linked lawyers & contacts</div>
          {lawyers.length ? (
            lawyers.map((l) => (
              <div
                key={l}
                style={{
                  fontSize: 12,
                  padding: '5px 0',
                  borderBottom: '0.5px solid var(--color-border-tertiary)',
                }}
              >
                {l}
              </div>
            ))
          ) : (
            <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>None linked via listings.</div>
          )}
        </div>

        <div className="owner-section">
          <div className="owner-section-title">Notes</div>
          <textarea className="notes-area" value={owner.notes ?? ''} readOnly />
          <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', marginTop: 4 }}>
            Read-only in this version (data comes from Google Sheets)
          </div>
        </div>
      </div>

      <div style={{ marginTop: 14, fontSize: 12, color: 'var(--color-text-tertiary)' }}>
        <Link to="/listings" style={{ color: 'var(--color-brand-700)', textDecoration: 'none', fontWeight: 500 }}>
          View all listings
        </Link>
      </div>
    </div>
  )
}

