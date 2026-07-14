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
  return new Date(d + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function daysUntil(d) {
  if (!d) return null
  return Math.ceil((new Date(d + 'T12:00:00') - new Date()) / 86400000)
}

function ScoreBadge({ score }) {
  const color = score >= 8 ? 'var(--green)' : score >= 6 ? 'var(--blue)' : 'var(--text2)'
  const bg = score >= 8 ? 'var(--green-dim)' : score >= 6 ? 'var(--blue-dim)' : 'var(--surface2)'
  return (
    <div style={{
      width: 40, height: 40, borderRadius: 8, background: bg, border: `1px solid ${color}`,
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
    }}>
      <span style={{ fontSize: 16, fontWeight: 700, color, lineHeight: 1 }}>{score}</span>
      <span style={{ fontSize: 9, color, lineHeight: 1, marginTop: 1 }}>FIT</span>
    </div>
  )
}

function Tag({ children, color = 'var(--text2)', bg = 'var(--surface2)', bold }) {
  return (
    <span style={{
      fontSize: 11, fontWeight: bold ? 700 : 600, padding: '2px 8px', borderRadius: 4,
      background: bg, color, border: bg === 'var(--surface2)' ? 'none' : `1px solid ${color}`,
    }}>{children}</span>
  )
}

const ACTION_COLORS = {
  PURSUE: ['var(--green)', 'var(--green-dim)'],
  MONITOR: ['var(--amber)', 'var(--amber-dim)'],
  INTEL: ['var(--text2)', 'var(--surface2)'],
}

export default function OpportunityCard({ opp, expanded, onToggle }) {
  const [showDraft, setShowDraft] = useState(false)
  const days = daysUntil(opp.due_date)
  const urgent = days !== null && days <= 14 && days >= 0
  const [ac, abg] = ACTION_COLORS[opp.action] || ACTION_COLORS.INTEL

  return (
    <div style={{
      background: 'var(--surface)',
      border: `1px solid ${expanded ? 'var(--blue)' : 'var(--border)'}`,
      borderRadius: 'var(--radius)', marginBottom: 12, overflow: 'hidden',
    }}>
      <button onClick={onToggle} style={{
        width: '100%', display: 'flex', alignItems: 'flex-start', gap: 14,
        padding: '16px 18px', background: 'transparent', border: 'none',
        textAlign: 'left', cursor: 'pointer',
      }}>
        <ScoreBadge score={opp.fit_score} />

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
            <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--text)' }}>{opp.title}</span>
            <Tag color={ac} bg={abg} bold>{opp.action}</Tag>
            <Tag>{opp.notice_type}</Tag>
            {/* An M/WBE noncompetitive purchase is the most winnable vehicle
                there is for a certified firm — surface it up front. */}
            {opp.mwbe_vehicle && (
              <Tag color="var(--purple)" bg="var(--blue-dim)" bold>M/WBE VEHICLE</Tag>
            )}
            {opp.is_new && <Tag color="var(--green)" bg="var(--green-dim)" bold>NEW</Tag>}
          </div>

          <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', fontSize: 13, color: 'var(--text2)' }}>
            <span>🏛 {opp.agency}</span>
            {opp.due_date && (
              <span style={{ color: urgent ? 'var(--red)' : 'var(--text2)' }}>
                📅 Due {fmtDate(opp.due_date)}{urgent ? ` · ${days}d left` : ''}
              </span>
            )}
            {opp.amount > 0 && <span>💰 {fmt(opp.amount)}</span>}
            {opp.pin && <span>#️⃣ {opp.pin}</span>}
          </div>
        </div>

        <span style={{ color: 'var(--text2)', fontSize: 18, flexShrink: 0, alignSelf: 'center' }}>
          {expanded ? '▲' : '▼'}
        </span>
      </button>

      {expanded && (
        <div style={{ padding: '16px 18px 18px', borderTop: '1px solid var(--border)' }}>
          <p style={{ color: 'var(--text)', marginBottom: 16, lineHeight: 1.6 }}>{opp.summary}</p>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12, marginBottom: 16 }}>
            <Panel title="Keyword Matches">
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {(opp.keyword_matches || []).map(k => (
                  <span key={k} style={{ fontSize: 12, padding: '2px 8px', borderRadius: 4, background: 'var(--blue-dim)', color: 'var(--blue)' }}>{k}</span>
                ))}
              </div>
            </Panel>

            {/* The contracting officer. This is the payoff of using CROL over
                the PDF — a name and an address to actually follow up on. */}
            <Panel title="Contracting Officer">
              {opp.contact_name || opp.contact_email ? (
                <div style={{ fontSize: 13, color: 'var(--text)', display: 'flex', flexDirection: 'column', gap: 3 }}>
                  {opp.contact_name && <span>{opp.contact_name}</span>}
                  {opp.contact_email && (
                    <a href={`mailto:${opp.contact_email}?subject=${encodeURIComponent(opp.title)}`}
                       style={{ color: 'var(--blue)' }}>{opp.contact_email}</a>
                  )}
                  {opp.contact_phone && <span style={{ color: 'var(--text2)' }}>{opp.contact_phone}</span>}
                </div>
              ) : <span style={{ fontSize: 13, color: 'var(--text2)' }}>Not listed</span>}
            </Panel>

            <Panel title="Procurement Detail">
              <div style={{ fontSize: 13, color: 'var(--text)', display: 'flex', flexDirection: 'column', gap: 3 }}>
                {opp.selection_method && <span>{opp.selection_method}</span>}
                {opp.category && <span style={{ color: 'var(--text2)' }}>{opp.category}</span>}
                <span style={{ color: 'var(--text2)' }}>Issued {fmtDate(opp.issue_date)}</span>
                {opp.vendor && <span style={{ color: 'var(--amber)' }}>Awarded to: {opp.vendor}</span>}
              </div>
            </Panel>
          </div>

          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <a href={opp.source_url} target="_blank" rel="noopener noreferrer" style={{
              padding: '8px 16px', borderRadius: 'var(--radius-sm)', background: 'var(--blue)',
              color: '#fff', fontSize: 13, fontWeight: 600, textDecoration: 'none',
            }}>View Notice ↗</a>
            <button onClick={() => setShowDraft(true)} style={{
              padding: '8px 16px', borderRadius: 'var(--radius-sm)', background: 'var(--purple)',
              color: '#fff', fontSize: 13, fontWeight: 600, border: 'none', cursor: 'pointer',
            }}>✍ Draft Response</button>
            <button onClick={() => navigator.clipboard.writeText(
              `${opp.title}\n${opp.agency} | ${opp.notice_type} | PIN ${opp.pin}\n` +
              `Due: ${fmtDate(opp.due_date)} | Value: ${fmt(opp.amount)}\n` +
              `Fit: ${opp.fit_score}/10 (${opp.action})\n` +
              `Contact: ${opp.contact_name} ${opp.contact_email}\n\n${opp.summary}\n\n${opp.source_url}`
            )} style={{
              padding: '8px 16px', borderRadius: 'var(--radius-sm)', background: 'transparent',
              border: '1px solid var(--border)', color: 'var(--text2)', fontSize: 13,
              fontWeight: 600, cursor: 'pointer',
            }}>Copy Brief</button>
          </div>

          {showDraft && <DraftResponseModal opp={opp} onClose={() => setShowDraft(false)} />}
        </div>
      )}
    </div>
  )
}

function Panel({ title, children }) {
  return (
    <div style={{ background: 'var(--surface2)', borderRadius: 'var(--radius-sm)', padding: '12px 14px' }}>
      <div style={{ fontSize: 11, color: 'var(--text2)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.06em' }}>{title}</div>
      {children}
    </div>
  )
}
