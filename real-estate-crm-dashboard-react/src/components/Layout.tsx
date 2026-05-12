import { NavLink, Outlet, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import '../styles/dashboard.css'

export function Layout() {
  const navigate = useNavigate()
  const location = useLocation()
  const [params, setParams] = useSearchParams()
  const search = params.get('q') ?? ''

  const onSearchChange = (q: string) => {
    const next = new URLSearchParams(params)
    if (q) next.set('q', q)
    else next.delete('q')
    setParams(next, { replace: true })
  }

  const showSearch = location.pathname.startsWith('/listings')

  return (
    <div className="app" style={{ position: 'relative' }}>
      <h2 className="sr-only">Real estate agency CRM dashboard with listings, associations, and owner profiles</h2>

      <div className="topbar">
        <div className="topbar-left">
          <a className="logo" href="https://katalystteam.com/" target="_blank" rel="noopener noreferrer" title="The KataLYST Team">
            <img
              className="logo-img"
              src="https://katalystteam.com/wp-content/uploads/2019/10/KLYST-LOGO-color-outlined.png"
              alt="The KataLYST Team"
              width={220}
              height={62}
            />
          </a>
          <div className="nav-tabs">
            <NavLink
              to="/listings"
              className={({ isActive }) => `nav-tab${isActive ? ' active' : ''}`}
              onClick={() => navigate('/listings')}
            >
              Listings
            </NavLink>
            <NavLink
              to="/owners"
              className={({ isActive }) => `nav-tab${isActive ? ' active' : ''}`}
              onClick={() => navigate('/owners')}
            >
              Owners
            </NavLink>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {showSearch ? (
            <input
              className="search-input"
              placeholder="Search listings..."
              value={search}
              onChange={(e) => onSearchChange(e.target.value)}
            />
          ) : null}
        </div>
      </div>

      <Outlet />
    </div>
  )
}

