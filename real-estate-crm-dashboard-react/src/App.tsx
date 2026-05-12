import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { ListingsPage } from './pages/ListingsPage'
import { OwnersPage } from './pages/OwnersPage'
import { OwnerProfilePage } from './pages/OwnerProfilePage'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Navigate to="/listings" replace />} />
        <Route path="/listings" element={<ListingsPage />} />
        <Route path="/owners" element={<OwnersPage />} />
        <Route path="/owners/:ownerId" element={<OwnerProfilePage />} />
      </Route>
    </Routes>
  )
}
