const PALETTE: Record<string, string> = {
  owner: '#e8c4d0',
  lawyer: '#c5e6de',
  agent: '#f0d4a8',
  lead: '#f3c2d2',
  doc: '#c9d8f0',
  tx: '#d4e4b8',
}
const PALETTE_TEXT: Record<string, string> = {
  owner: '#430515',
  lawyer: '#0d4a3c',
  agent: '#5c3a0a',
  lead: '#4a0f25',
  doc: '#1a3050',
  tx: '#2a3d12',
}

export function Avatar({ name, kind }: { name: string; kind: keyof typeof PALETTE }) {
  const initials = name
    .split(' ')
    .filter(Boolean)
    .map((w) => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()
  const bg = PALETTE[kind] ?? '#D3D1C7'
  const c = PALETTE_TEXT[kind] ?? '#2C2C2A'
  return (
    <div className="assoc-avatar" style={{ background: bg, color: c }}>
      {initials}
    </div>
  )
}

