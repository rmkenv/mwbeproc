function fmt(n) {
  if (!n) return '$0'
  if (n >= 1000000) return `$${(n / 1000000).toFixed(1)}M`
  if (n >= 1000) return `$${(n / 1000).toFixed(0)}K`
  return `$${n}`
}

function Stat({ label, value, color, bg }) {
  return (
    <div style={{
      flex: 1, minWidth: 120,
      background: bg || 'var(--surface)',
      border: `1px solid var(--border)`,
      borderRadius: 'var(--radius)',
      padding: '14px 18px',
    }}>
      <div style={{ fontSize: 11, color: 'var(--text2)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 700, color: color || 'var(--text)', fontVariantNumeric: 'tabular-nums' }}>{value}</div>
    </div>
  )
}

export default function StatsBar({ stats }) {
  return (
    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 20 }}>
      <Stat label="Open Solicitations" value={stats.open || 0} />
      <Stat label="Pursue" value={stats.pursue || 0} color="var(--green)" />
      <Stat label="New This Run" value={stats.isNew || 0} color="var(--amber)" />
      <Stat label="M/WBE Vehicles" value={stats.mwbe || 0} color="var(--blue)" />
    </div>
  )
}
