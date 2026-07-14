import { useState } from 'react'

/**
 * The v1 failure mode was invisible: NYS Contract Reporter and SAM.gov were
 * returning nothing for months and the dashboard looked identical to a quiet
 * week. Every run now reports per-source status and it gets shown here.
 */
export default function SourceHealth({ sources = [], searchTerms = [], windowDays }) {
  const [open, setOpen] = useState(false)
  if (!sources.length) return null

  const failed = sources.filter(s => !s.ok)
  const totalFound = sources.reduce((n, s) => n + (s.found || 0), 0)

  return (
    <div style={{
      background: 'var(--surface)',
      border: `1px solid ${failed.length ? 'var(--amber)' : 'var(--border)'}`,
      borderRadius: 'var(--radius)',
      marginBottom: 20,
      overflow: 'hidden',
    }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', gap: 10,
          padding: '10px 16px', background: 'transparent', border: 'none',
          color: 'var(--text2)', fontSize: 13, cursor: 'pointer', textAlign: 'left',
        }}
      >
        <span>{failed.length ? '⚠️' : '✓'}</span>
        <span style={{ flex: 1 }}>
          {failed.length
            ? `${failed.length} of ${sources.length} City Record sources reported a problem`
            : `City Record searched · ${totalFound} notices matched${windowDays ? ` in the last ${windowDays} days` : ''}`}
        </span>
        <span>{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div style={{ borderTop: '1px solid var(--border)', padding: '12px 16px' }}>
          <table style={{ width: '100%', fontSize: 13, borderCollapse: 'collapse' }}>
            <tbody>
              {sources.map(s => (
                <tr key={s.source} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '6px 0', color: s.ok ? 'var(--green)' : 'var(--red)' }}>
                    {s.ok ? '●' : '●'}
                  </td>
                  <td style={{ padding: '6px 8px', color: 'var(--text)' }}>{s.source}</td>
                  <td style={{ padding: '6px 8px', color: 'var(--text2)', textAlign: 'right' }}>
                    {s.found} found
                  </td>
                  <td style={{ padding: '6px 8px', color: 'var(--text2)', textAlign: 'right' }}>
                    {s.queries} quer{s.queries === 1 ? 'y' : 'ies'}
                  </td>
                  <td style={{ padding: '6px 0 6px 12px', color: 'var(--amber)', fontSize: 12 }}>
                    {s.error || s.note}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {searchTerms.length > 0 && (
            <div style={{ marginTop: 12, fontSize: 12, color: 'var(--text2)' }}>
              Search terms: {searchTerms.join(' · ')}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
