import { useState } from 'react'

const PROMPTS = [
  {
    id: 'go-no-go',
    label: 'Go / No-Go Assessment',
    template: (o) => `You are a procurement advisor for ${o.firm || '[FIRM NAME]'}, an MWBE-certified immigration legal services firm.

Opportunity: ${o.title}
Agency: ${o.agency} (${o.jurisdiction})
Type: ${o.contract_type}
Value: ${o.amount > 0 ? '$' + o.amount.toLocaleString() : 'Not specified'}
Due: ${o.due_date || 'Not specified'}
Summary: ${o.summary || 'See source posting'}

Evaluate this opportunity across these dimensions:
1. MISSION FIT — Does this align with immigration legal services?
2. CAPACITY — Can we staff this with existing attorneys and paralegals?
3. COMPETITION — Who else likely bids on this? Are we competitive?
4. CERTIFICATIONS — Do we meet stated requirements?
5. RISK — What are the top 2-3 risks if we pursue?
6. RECOMMENDATION — PURSUE / MONITOR / PASS and why in 2 sentences.`
  },
  {
    id: 'exec-summary',
    label: 'Executive Summary Draft',
    template: (o) => `Draft a 2-paragraph executive summary for an RFP response to:

Opportunity: ${o.title}
Agency: ${o.agency}
Jurisdiction: ${o.jurisdiction}
Contract Type: ${o.contract_type}

The firm is MWBE-certified with NYC, NYS, Nassau County, and Suffolk County. We specialize in immigration legal services including removal defense, asylum, SIJS, VAWA, U visas, naturalization, and community know-your-rights programming.

The executive summary should:
- Open with our understanding of the agency's mission and this specific need
- State our qualifications and why we are uniquely positioned
- Reference our MWBE certifications as a differentiator
- Close with our commitment to outcomes for the target population

Write in a professional, confident tone. Do not use bullet points.`
  },
  {
    id: 'qualifications',
    label: 'Qualifications Narrative',
    template: (o) => `Draft a qualifications narrative for this opportunity:

Opportunity: ${o.title}
Agency: ${o.agency} (${o.jurisdiction})
Keywords matched: ${(o.keyword_matches || []).join(', ')}

Include sections for:
1. Organizational Overview (4-5 sentences)
2. Relevant Experience — focus on immigration legal services, community-based work, and any prior government contracts
3. Staff Qualifications — describe the type of attorneys, paralegals, and support staff we would deploy
4. MWBE Certification Status — NYC, NYS, Nassau, and Suffolk certifications
5. Cultural and Linguistic Competency — multilingual capacity and community trust

Keep each section to 2-3 paragraphs. Write in third person.`
  },
  {
    id: 'budget',
    label: 'Budget Justification',
    template: (o) => `Draft a budget justification narrative for:

Opportunity: ${o.title}
Agency: ${o.agency}
Estimated Value: ${o.amount > 0 ? '$' + o.amount.toLocaleString() : 'TBD — research required'}

Develop a budget justification that covers:
1. Personnel costs — attorney hours at appropriate billing rates, paralegal support, administrative staff
2. Fringe benefits — standard government fringe rate
3. Indirect/overhead costs — explain our rate
4. Direct costs — filing fees, translation services, travel if applicable
5. Any subcontractors if relevant

The narrative should justify each line item and explain how costs tie to deliverables and outcomes. Use realistic market rates for immigration legal services in the NYC metro area.`
  },
  {
    id: 'agency-research',
    label: 'Agency Research Brief',
    template: (o) => `Generate a research brief on:

Agency: ${o.agency}
Jurisdiction: ${o.jurisdiction}

Include:
1. AGENCY MISSION — What does this agency do and who does it serve?
2. IMMIGRATION NEXUS — Why does this agency need immigration legal services? Who in their population has immigration needs?
3. PRIOR CONTRACTS — What types of legal or social service contracts have they awarded before?
4. KEY CONTACTS — Who are the typical procurement officers, program directors, or commissioners for this type of work?
5. POLITICAL CONTEXT — Any recent news, policy shifts, or council/legislative attention that affects their priorities?
6. OUTREACH STRATEGY — Suggest 2-3 specific actions to increase our visibility with this agency before the next RFP cycle.`
  },
  {
    id: 'outreach-email',
    label: 'Outreach Email',
    template: (o) => `Draft a brief, professional outreach email to introduce our firm to:

Agency: ${o.agency} (${o.jurisdiction})
Context: We are aware of this opportunity: ${o.title}

The email should:
- Be addressed to the procurement officer or program director (leave name as [NAME])
- Introduce our firm as an MWBE-certified immigration legal services provider
- Express interest in this opportunity or future contracting opportunities
- Note our certifications (NYC, NYS, Nassau, Suffolk MWBE)
- Request a brief informational meeting or call
- Be no more than 150 words
- Use a warm, professional tone — not a sales pitch

Subject line options: provide 3 alternatives.`
  },
]

export default function DraftResponseModal({ opp, onClose }) {
  const [activePrompt, setActivePrompt] = useState(PROMPTS[0])
  const [copied, setCopied] = useState(false)

  const fullPrompt = activePrompt.template({ ...opp, firm: '[FIRM NAME]' })

  const copyPrompt = () => {
    navigator.clipboard.writeText(fullPrompt)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      zIndex: 1000, padding: 16,
    }} onClick={onClose}>
      <div
        style={{
          background: 'var(--surface)', border: '1px solid var(--border)',
          borderRadius: 12, width: '100%', maxWidth: 780,
          maxHeight: '90vh', overflow: 'hidden',
          display: 'flex', flexDirection: 'column',
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{
          padding: '18px 20px', borderBottom: '1px solid var(--border)',
          display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
        }}>
          <div>
            <div style={{ fontSize: 13, color: 'var(--text2)', marginBottom: 4 }}>DRAFT RESPONSE PROMPTS</div>
            <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text)' }}>{opp.title}</div>
            <div style={{ fontSize: 13, color: 'var(--text2)', marginTop: 2 }}>{opp.agency} · {opp.jurisdiction}</div>
          </div>
          <button onClick={onClose} style={{
            background: 'transparent', border: 'none', color: 'var(--text2)',
            fontSize: 22, cursor: 'pointer', lineHeight: 1, padding: '0 4px',
          }}>×</button>
        </div>

        {/* Prompt selector */}
        <div style={{
          padding: '12px 20px', borderBottom: '1px solid var(--border)',
          display: 'flex', gap: 8, flexWrap: 'wrap',
        }}>
          {PROMPTS.map(p => (
            <button
              key={p.id}
              onClick={() => { setActivePrompt(p); setCopied(false) }}
              style={{
                padding: '5px 12px', borderRadius: 20, fontSize: 12,
                border: activePrompt.id === p.id ? '1px solid var(--blue)' : '1px solid var(--border)',
                background: activePrompt.id === p.id ? 'var(--blue-dim)' : 'transparent',
                color: activePrompt.id === p.id ? 'var(--blue)' : 'var(--text2)',
                cursor: 'pointer', fontWeight: activePrompt.id === p.id ? 600 : 400,
              }}
            >{p.label}</button>
          ))}
        </div>

        {/* Prompt text */}
        <div style={{ flex: 1, overflow: 'auto', padding: '16px 20px' }}>
          <pre style={{
            margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            fontSize: 13, lineHeight: 1.7, color: 'var(--text)',
            fontFamily: '-apple-system, BlinkMacSystemFont, sans-serif',
          }}>{fullPrompt}</pre>
        </div>

        {/* Footer */}
        <div style={{
          padding: '14px 20px', borderTop: '1px solid var(--border)',
          display: 'flex', gap: 10, alignItems: 'center',
        }}>
          <button onClick={copyPrompt} style={{
            padding: '8px 18px', borderRadius: 8,
            background: copied ? 'var(--green)' : 'var(--blue)',
            color: '#fff', border: 'none', fontSize: 13, fontWeight: 600, cursor: 'pointer',
          }}>
            {copied ? '✓ Copied' : 'Copy Prompt'}
          </button>
          <span style={{ fontSize: 12, color: 'var(--text2)' }}>
            Paste into Claude or any AI assistant
          </span>
        </div>
      </div>
    </div>
  )
}
