function Chip({ label, active, onClick }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: '5px 12px',
        borderRadius: 20,
        border: active ? '1px solid var(--blue)' : '1px solid var(--border)',
        background: active ? 'var(--blue-dim)' : 'transparent',
        color: active ? 'var(--blue)' : 'var(--text2)',
        fontSize: 13,
        fontWeight: active ? 600 : 400,
        transition: 'all 0.15s',
      }}
    >
      {label}
    </button>
  )
}

export default function FilterBar({
  search, setSearch,
  jurisdiction, setJurisdiction, jurisdictions,
  action, setAction, actions,
  sort, setSort, sortOptions,
  resultCount
}) {
  return (
    <div style={{ marginBottom: 20 }}>
      {/* Search */}
      <div style={{ position: 'relative', marginBottom: 12 }}>
        <span style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--text2)', fontSize: 15 }}>🔍</span>
        <input
          type="text"
          placeholder="Search by title, agency, keyword…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{
            width: '100%',
            padding: '10px 12px 10px 38px',
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius)',
            color: 'var(--text)',
            fontSize: 14,
            outline: 'none',
          }}
        />
      </div>

      {/* Filters row */}
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center' }}>
          {/* Jurisdiction chips */}
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {jurisdictions.map(j => (
              <Chip key={j} label={j} active={jurisdiction === j} onClick={() => setJurisdiction(j)} />
            ))}
          </div>

          <div style={{ width: 1, height: 24, background: 'var(--border)' }} />

          {/* Action chips */}
          <div style={{ display: 'flex', gap: 6 }}>
            {actions.map(a => (
              <Chip key={a} label={a} active={action === a} onClick={() => setAction(a)} />
            ))}
          </div>
        </div>

        {/* Sort + count */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ color: 'var(--text2)', fontSize: 13 }}>{resultCount} result{resultCount !== 1 ? 's' : ''}</span>
          <select
            value={sort}
            onChange={e => setSort(e.target.value)}
            style={{
              padding: '6px 10px',
              background: 'var(--surface)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--text)',
              fontSize: 13,
              cursor: 'pointer',
            }}
          >
            {sortOptions.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
      </div>
    </div>
  )
}
