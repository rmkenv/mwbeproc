export default function Header({ generated }) {
  const date = generated
    ? new Date(generated).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' })
    : '—'

  return (
    <header style={{ padding: '28px 0 20px', borderBottom: '1px solid var(--border)', marginBottom: 20 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
            <div style={{
              width: 32, height: 32, borderRadius: 8,
              background: 'linear-gradient(135deg, var(--blue), var(--purple))',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 16
            }}>⚖️</div>
            <h1 style={{ fontSize: 20, fontWeight: 700, color: 'var(--text)' }}>
              MWBE Procurement Monitor
            </h1>
          </div>
          <p style={{ color: 'var(--text2)', fontSize: 13 }}>
            Immigration legal services opportunities · NYC · NYS · Nassau · Suffolk
          </p>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 11, color: 'var(--text2)', marginBottom: 4 }}>LAST UPDATED</div>
          <div style={{ fontSize: 13, color: 'var(--text)', fontVariantNumeric: 'tabular-nums' }}>{date}</div>
          <div style={{ marginTop: 6 }}>
            <span style={{
              fontSize: 11, padding: '2px 8px', borderRadius: 20,
              background: 'var(--teal-dim)', color: 'var(--teal)',
              border: '1px solid var(--teal)', fontWeight: 600
            }}>MWBE CERTIFIED</span>
          </div>
        </div>
      </div>
    </header>
  )
}
