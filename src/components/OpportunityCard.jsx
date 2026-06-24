import { useState } from 'react'
import DraftResponseModal from './DraftResponseModal'

function fmt(n) {
  if (!n) return '—'
  if (n >= 1000000) return `$${(n / 1000000).toFixed(1)}M`
  if (n >= 1000) return `$${(n / 1000).toFixed(0)}K`
  return `$${n}`
}

function fmtDate(d) {
  if (!d) return '—'
  return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function daysUntil(d) {
  if (!d) return null
  const diff = Math.ceil((new Date(d) - new Date()) / (1000 * 60 * 60 * 24))
  return diff
}

function ScoreBadge({ score }) {
  const color = score >= 8 ? 'var(--green)' : score >= 6 ? 'var(--blue)' : 'var(--text2)'
  const bg = score >= 8 ? 'var(--green-dim)' : score >= 6 ? 'var(--blue-dim)' : 'var(--surface2)'
  return (
    <div style={{
      width: 40, height: 40, borderRadius: 8,
      background: bg, border: `1px solid ${color}`,
      display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center',
      flexShrink: 0,
    }}>
      <span style={{ fontSize: 16, fontWeight: 700, color, lineHeight: 1 }}>{score}</span>
      <span style={{ fontSize: 9, color, lineHeight: 1, marginTop: 1 }}>FIT</span>
    </div>
  )
}

function ActionBadge({ action }) {
  const isPursue = action === 'PURSUE'
  return (
    <span style={{
      fontSize: 11, fontWeight: 700, padding: '3px 8px', borderRadius: 4,
      background: isPursue ? 'var(--green-dim)' : 'var(--amber-dim)',
      color: isPursue ? 'var(--green)' : 'var(--amber)',
      border: `1px solid ${isPursue ? 'var(--green)' : 'var(--amber)'}`,
      letterSpacing: '0.04em',
    }}>{action}</span>
  )
}

function JurisdictionBadge({ jurisdiction }) {
  const colors = {
    NYC: { bg: 'var(--blue-dim)', color: 'var(--blue)' },
    NYS: { bg: 'var(--purple)', color: '#fff' },
    Nassau: { bg: 'var(--teal-dim)', color: 'var(--teal)' },
    Suffolk: { bg: 'var(--surface2)', color: 'var(--text2)' },
  }
  const c = colors[jurisdiction] || colors.Suffolk
  return (
    <span style={{
      fontSize: 11, fontWeight: 600, padding: '2px 7px', borderRadius: 4,
      background: c.bg, color: c.color,
    }}>{jurisdiction}</span>
  )
}

export default function OpportunityCard({ opp, expanded, onToggle }) {
  const [showDraft, setShowDraft] = useState(false)
  const days = daysUntil(opp.due_date)
  const urgent = days !== null && days <= 14
  const isLegistar = opp.source && opp.source.includes('Legistar')

  return (
    <div style={{
      background: 'var(--surface)',
      border: `1px solid ${expanded ? 'var(--blue)' : 'var(--border)'}`,
      borderRadius: 'var(--radius)',
      marginBottom: 12,
      transition: 'border-color 0.15s',
      overflow: 'hidden',
    }}>
      {/* Card header — always visible */}
      <button
        onClick={onToggle}
        style={{
          width: '100%', display: 'flex', alignItems: 'flex-start', gap: 14,
          padding: '16px 18px', background: 'transparent', border: 'none',
          textAlign: 'left', cursor: 'pointer',
        }}
      >
        <ScoreBadge score={opp.fit_score} />

        <div style={{ flex: 1, minWidth: 0 }}>
          {/* Title row */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
            <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--text)' }}>{opp.title}</span>
            <ActionBadge action={opp.action} />
            <JurisdictionBadge jurisdiction={opp.jurisdiction} />
            <span style={{ fontSize: 11, padding: '2px 7px', borderRadius: 4, background: 'var(--surface2)', color: 'var(--text2)' }}>
              {opp.contract_type}
            </span>
            {isLegistar && (
              <span style={{
                fontSize: 11, padding: '2px 8px', borderRadius: 4, fontWeight: 600,
                background: 'var(--amber-dim)', color: 'var(--amber)',
                border: '1px solid var(--amber)',
              }}>📡 ADVANCE SIGNAL</span>
            )}
          </div>

          {/* Meta row */}
          <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', fontSize: 13, color: 'var(--text2)' }}>
            <span>🏛 {opp.agency}</span>
            <span style={{ color: urgent ? 'var(--red)' : 'var(--text2)' }}>
              📅 Due {fmtDate(opp.due_date)}{urgent ? ` · ${days}d left` : ''}
            </span>
            {opp.amount > 0 && <span>💰 {fmt(opp.amount)}</span>}
            <span>📡 {opp.source}</span>
          </div>
        </div>

        <span style={{ color: 'var(--text2)', fontSize: 18, flexShrink: 0, alignSelf: 'center' }}>
          {expanded ? '▲' : '▼'}
        </span>
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div style={{
          padding: '0 18px 18px',
          borderTop: '1px solid var(--border)',
          paddingTop: 16,
        }}>
          {/* Summary */}
          <p style={{ color: 'var(--text)', marginBottom: 16, lineHeight: 1.6 }}>{opp.summary}</p>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12, marginBottom: 16 }}>
            {/* Keywords */}
            <div style={{ background: 'var(--surface2)', borderRadius: 'var(--radius-sm)', padding: '12px 14px' }}>
              <div style={{ fontSize: 11, color: 'var(--text2)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Keyword Matches</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {opp.keyword_matches.map(k => (
                  <span key={k} style={{
                    fontSize: 12, padding: '2px 8px', borderRadius: 4,
                    background: 'var(--blue-dim)', color: 'var(--blue)',
                  }}>{k}</span>
                ))}
              </div>
            </div>

            {/* Certifications */}
            <div style={{ background: 'var(--surface2)', borderRadius: 'var(--radius-sm)', padding: '12px 14px' }}>
              <div style={{ fontSize: 11, color: 'var(--text2)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Certifications Required</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {opp.certifications_required.map(c => (
                  <span key={c} style={{ fontSize: 13, color: 'var(--teal)' }}>✓ {c}</span>
                ))}
              </div>
            </div>

            {/* Dates */}
            <div style={{ background: 'var(--surface2)', borderRadius: 'var(--radius-sm)', padding: '12px 14px' }}>
              <div style={{ fontSize: 11, color: 'var(--text2)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Timeline</div>
              <div style={{ fontSize: 13, color: 'var(--text)' }}>
                <div style={{ marginBottom: 4 }}>Issued: {fmtDate(opp.issue_date)}</div>
                <div style={{ color: urgent ? 'var(--red)' : 'var(--text)' }}>Due: {fmtDate(opp.due_date)}</div>
              </div>
            </div>
          </div>

          {/* Actions row */}
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <a
              href={opp.source_url}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                padding: '8px 16px', borderRadius: 'var(--radius-sm)',
                background: 'var(--blue)', color: '#fff',
                fontSize: 13, fontWeight: 600, textDecoration: 'none',
                display: 'inline-block',
              }}
            >
              View Posting ↗
            </a>
            <button
              onClick={() => setShowDraft(true)}
              style={{
                padding: '8px 16px', borderRadius: 'var(--radius-sm)',
                background: 'var(--purple)', color: '#fff',
                fontSize: 13, fontWeight: 600, border: 'none', cursor: 'pointer',
              }}
            >
              ✍ Draft Response
            </button>
            <button
              onClick={() => {
                const text = `${opp.title}\n${opp.agency} | ${opp.jurisdiction} | ${opp.contract_type}\nDue: ${fmtDate(opp.due_date)} | Value: ${fmt(opp.amount)}\nFit Score: ${opp.fit_score}/10 | ${opp.action}\n\n${opp.summary}\n\nSource: ${opp.source_url}`
                navigator.clipboard.writeText(text)
              }}
              style={{
                padding: '8px 16px', borderRadius: 'var(--radius-sm)',
                background: 'transparent', border: '1px solid var(--border)',
                color: 'var(--text2)', fontSize: 13, fontWeight: 600, cursor: 'pointer',
              }}
            >
              Copy Brief
            </button>
            <span style={{ fontSize: 12, color: 'var(--text2)', alignSelf: 'center' }}>ID: {opp.id}</span>
          </div>
          {showDraft && <DraftResponseModal opp={opp} onClose={() => setShowDraft(false)} />}
        </div>
      )}
    </div>
  )
}
