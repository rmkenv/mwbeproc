import { useState, useEffect, useMemo } from 'react'
import Header from './components/Header'
import StatsBar from './components/StatsBar'
import FilterBar from './components/FilterBar'
import OpportunityCard from './components/OpportunityCard'
import EmptyState from './components/EmptyState'

const JURISDICTIONS = ['All', 'NYC', 'NYS', 'Nassau', 'Suffolk']
const ACTIONS = ['All', 'PURSUE', 'MONITOR']
const SORT_OPTIONS = [
  { value: 'fit_score', label: 'Fit Score' },
  { value: 'due_date', label: 'Due Date' },
  { value: 'amount', label: 'Contract Value' },
]

export default function App() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState('')
  const [jurisdiction, setJurisdiction] = useState('All')
  const [action, setAction] = useState('All')
  const [sort, setSort] = useState('fit_score')
  const [expanded, setExpanded] = useState(null)

  useEffect(() => {
    fetch('/data/opportunities.json')
      .then(r => { if (!r.ok) throw new Error('Failed to load'); return r.json() })
      .then(d => { setData(d); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [])

  const filtered = useMemo(() => {
    if (!data) return []
    return data.opportunities
      .filter(o => {
        const q = search.toLowerCase()
        const matchSearch = !q ||
          o.title.toLowerCase().includes(q) ||
          o.agency.toLowerCase().includes(q) ||
          o.summary.toLowerCase().includes(q) ||
          o.keyword_matches.some(k => k.toLowerCase().includes(q))
        const matchJurisdiction = jurisdiction === 'All' || o.jurisdiction === jurisdiction
        const matchAction = action === 'All' || o.action === action
        return matchSearch && matchJurisdiction && matchAction
      })
      .sort((a, b) => {
        if (sort === 'fit_score') return b.fit_score - a.fit_score
        if (sort === 'due_date') return new Date(a.due_date) - new Date(b.due_date)
        if (sort === 'amount') return b.amount - a.amount
        return 0
      })
  }, [data, search, jurisdiction, action, sort])

  const stats = useMemo(() => {
    if (!data) return {}
    const opps = data.opportunities
    return {
      total: opps.length,
      pursue: opps.filter(o => o.action === 'PURSUE').length,
      monitor: opps.filter(o => o.action === 'MONITOR').length,
      totalValue: opps.filter(o => o.action === 'PURSUE').reduce((s, o) => s + (o.amount || 0), 0),
      generated: data.generated_at,
    }
  }, [data])

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', color: 'var(--text2)' }}>
      Loading opportunities…
    </div>
  )

  if (error) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', color: 'var(--red)' }}>
      Error: {error}
    </div>
  )

  return (
    <div style={{ maxWidth: 920, margin: '0 auto', padding: '0 16px 60px' }}>
      <Header generated={stats.generated} />
      <StatsBar stats={stats} />
      <FilterBar
        search={search} setSearch={setSearch}
        jurisdiction={jurisdiction} setJurisdiction={setJurisdiction}
        jurisdictions={JURISDICTIONS}
        action={action} setAction={setAction}
        actions={ACTIONS}
        sort={sort} setSort={setSort}
        sortOptions={SORT_OPTIONS}
        resultCount={filtered.length}
      />
      {filtered.length === 0
        ? <EmptyState />
        : filtered.map(o => (
          <OpportunityCard
            key={o.id}
            opp={o}
            expanded={expanded === o.id}
            onToggle={() => setExpanded(expanded === o.id ? null : o.id)}
          />
        ))
      }
    </div>
  )
}
