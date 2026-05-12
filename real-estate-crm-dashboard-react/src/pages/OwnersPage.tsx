import { Link } from 'react-router-dom'
import { useDashboardData } from '../data/useDashboardData'

function initials(name: string) {
  return name
    .split(' ')
    .filter(Boolean)
    .map((w) => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()
}

export function OwnersPage() {
  const { data } = useDashboardData()

  return (
    <div className="listings-panel">
      <div className="section-header">
        <span className="section-title">{`${data.owners.length} owner${data.owners.length !== 1 ? 's' : ''}`}</span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(220px,1fr))', gap: 12 }}>
        {data.owners.length ? (
          data.owners.map((o) => {
            const props = data.listings.filter((l) => l.assoc.owners.some((ow) => ow.id === o.id))
            return (
              <Link key={o.id} to={`/owners/${o.id}`} className="listing-card" style={{ textDecoration: 'none' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
                  <div
                    style={{
                      width: 36,
                      height: 36,
                      borderRadius: '50%',
                      background: 'linear-gradient(145deg, var(--color-brand-700), var(--color-brand-900))',
                      color: 'var(--color-text-on-dark)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: 13,
                      fontWeight: 600,
                      flexShrink: 0,
                    }}
                  >
                    {initials(o.name)}
                  </div>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--color-text-primary)' }}>{o.name}</div>
                    <div style={{ fontSize: 11, color: 'var(--color-text-secondary)' }}>{o.phone ?? ''}</div>
                  </div>
                </div>
                <div style={{ fontSize: 11, color: 'var(--color-text-secondary)', marginBottom: 6 }}>{o.email ?? ''}</div>
                <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)' }}>
                  {props.length} propert{props.length !== 1 ? 'ies' : 'y'}
                </div>
              </Link>
            )
          })
        ) : (
          <div className="empty-state">No owners yet.</div>
        )}
      </div>
    </div>
  )
}

