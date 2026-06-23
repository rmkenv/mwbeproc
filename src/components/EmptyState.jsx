export default function EmptyState() {
  return (
    <div style={{
      textAlign: 'center', padding: '60px 20px',
      color: 'var(--text2)',
    }}>
      <div style={{ fontSize: 40, marginBottom: 12 }}>🔍</div>
      <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--text)', marginBottom: 8 }}>No opportunities match your filters</div>
      <div style={{ fontSize: 14 }}>Try adjusting the search, jurisdiction, or action filter.</div>
    </div>
  )
}
