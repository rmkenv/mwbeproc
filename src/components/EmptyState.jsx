export default function EmptyState({ total = 0, hasFilters = false, onReset }) {
  // Distinguish "the search found nothing" from "the scraper hasn't run yet".
  // Conflating those two is what makes a working search box look broken.
  const noData = total === 0

  return (
    <div style={{
      textAlign: 'center', padding: '48px 24px', color: 'var(--text2)',
      background: 'var(--surface)', border: '1px solid var(--border)',
      borderRadius: 'var(--radius)',
    }}>
      <div style={{ fontSize: 32, marginBottom: 12 }}>{noData ? '\u{1F4ED}' : '\u{1F50D}'}</div>

      {noData ? (
        <>
          <div style={{ color: 'var(--text)', marginBottom: 6 }}>No notices loaded yet</div>
          <div style={{ fontSize: 13 }}>
            The City Record search hasn\u2019t published results to this deployment.
            Run the <code>Search City Record</code> workflow in GitHub Actions, then redeploy.
          </div>
        </>
      ) : (
        <>
          <div style={{ color: 'var(--text)', marginBottom: 6 }}>
            No matches among {total} notice{total === 1 ? '' : 's'}
          </div>
          {hasFilters && (
            <button onClick={onReset} style={{
              marginTop: 12, padding: '6px 14px', borderRadius: 'var(--radius-sm)',
              background: 'transparent', border: '1px solid var(--border)',
              color: 'var(--blue)', fontSize: 13, cursor: 'pointer',
            }}>Clear filters</button>
          )}
        </>
      )}
    </div>
  )
}
