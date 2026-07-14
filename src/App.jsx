import { useState, useEffect, useMemo } from 'react'
import Header from './components/Header'
import StatsBar from './components/StatsBar'
import SourceHealth from './components/SourceHealth'
import FilterBar from './components/FilterBar'
import OpportunityCard from './components/OpportunityCard'
import EmptyState from './components/EmptyState'

const ACTIONS = ['All', 'PURSUE', 'MONITOR', 'INTEL']
// A solicitation, an intent-to-award, and a completed award are three different
// things. Mixing them into one list was the original problem.
const TYPES = [
  { value: 'All', label: 'All' },
  { value: 'SOLICITATION', label: 'Open bids' },
  { value: 'INTENT', label: 'Intent to award' },
  { value: 'AWARD', label: 'Past awards' },
]
const SORT_OPTIONS = [
  { value: 'fit_score', label: 'Fit Score' },
  { value: 'due_date', label: 'Due Date' },
  { value: 'amount', label: 'Contract Value' },
  { value: 'issue_date', label: 'Newest' },
]

export default function App() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState('')
  const [action, setAction] = useState('All')
  const [type, setType] = useState('All')
  const [mwbeOnly, setMwbeOnly] = useState(false)
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
    const q = search.toLowerCase()
    return data.opportunities
      .filter(o => {
        const matchSearch = !q ||
          o.title?.toLowerCase().includes(q) ||
          o.agency?.toLowerCase().includes(q) ||
          o.summary?.toLowerCase().includes(q) ||
          o.pin?.toLowerCase().includes(q) ||
          (o.keyword_matches || []).some(k => k.toLowerCase().includes(q))
        // While a search is active, ignore the type chip — searching should
        // look across everything, not just the currently selected tab.
        const searching = q.length > 0
        return matchSearch &&
          (action === 'All' || o.action === action) &&
          (searching || type === 'All' || o.record_type === type) &&
          (!mwbeOnly || o.mwbe_vehicle)
      })
      .sort((a, b) => {
        if (sort === 'fit_score') return b.fit_score - a.fit_score
        if (sort === 'issue_date') return (b.issue_date || '').localeCompare(a.issue_date || '')
        if (sort === 'amount') return (b.amount || 0) - (a.amount || 0)
        if (sort === 'due_date') {
          if (!a.due_date) return 1
          if (!b.due_date) return -1
          return a.due_date.localeCompare(b.due_date)
        }
        return 0
      })
  }, [data, search, action, type, mwbeOnly, sort])

  const stats = useMemo(() => {
    if (!data) return {}
    const c = data.counts || {}
    const opps = data.opportunities
    return {
      open: c.solicitations ?? 0,
      pursue: opps.filter(o => o.action === 'PURSUE').length,
      isNew: c.new_this_run ?? 0,
      mwbe: c.mwbe ?? 0,
      generated: data.generated_at,
    }
  }, [data])

  if (loading) return <Centered>Searching the City Record…</Centered>
  if (error) return <Centered color="var(--red)">Error: {error}</Centered>

  return (
    <div style={{ maxWidth: 920, margin: '0 auto', padding: '0 16px 60px' }}>
      <Header generated={stats.generated} />
      <StatsBar stats={stats} />
      <SourceHealth sources={data.sources} searchTerms={data.search_terms} windowDays={data.window_days} />
      <FilterBar
        search={search} setSearch={setSearch}
        action={action} setAction={setAction} actions={ACTIONS}
        type={type} setType={setType} types={TYPES}
        mwbeOnly={mwbeOnly} setMwbeOnly={setMwbeOnly}
        sort={sort} setSort={setSort} sortOptions={SORT_OPTIONS}
        resultCount={filtered.length}
      />
      {filtered.length === 0
        ? <EmptyState
            total={data.opportunities.length}
            filtered={filtered.length}
            hasFilters={!!search || action !== 'All' || type !== 'All' || mwbeOnly}
            onReset={() => { setSearch(''); setAction('All'); setType('All'); setMwbeOnly(false) }}
          />
        : filtered.map(o => (
          <OpportunityCard
            key={o.id}
            opp={o}
            expanded={expanded === o.id}
            onToggle={() => setExpanded(expanded === o.id ? null : o.id)}
          />
        ))}
    </div>
  )
}

function Centered({ children, color = 'var(--text2)' }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', color }}>
      {children}
    </div>
  )
}
