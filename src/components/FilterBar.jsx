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
  action, setAction, actions,
  type, setType, types,
  mwbeOnly, setMwbeOnly,
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
          placeholder="Filter by title, agency, PIN, keyword…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          onKeyDown={e => { if (e.key === 'Escape') setSearch('') }}
          style={{
            width: '100%',
            padding: '10px 80px 10px 38px',
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius)',
            color: 'var(--text)',
            fontSize: 14,
            outline: 'none',
          }}
        />
        {/* Filtering is live — there's nothing to submit. Say so, and give an
            obvious way out, so the box doesn't read as a dead input. */}
        {search
          ? <button
              onClick={() => setSearch('')}
              style={{
                position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)',
                padding: '4px 10px', borderRadius: 12, border: '1px solid var(--border)',
                background: 'var(--surface2)', color: 'var(--text2)', fontSize: 12, cursor: 'pointer',
              }}
            >Clear ✕</button>
          : <span style={{
              position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)',
              color: 'var(--text2)', fontSize: 11, opacity: 0.6, pointerEvents: 'none',
            }}>filters as you type</span>}
      </div>

      {/* Filters row */}
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center' }}>
          {/* Record type: open bid vs intent vs past award */}
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {types.map(t => (
              <Chip key={t.value} label={t.label} active={type === t.value} onClick={() => setType(t.value)} />
            ))}
          </div>

          <div style={{ width: 1, height: 24, background: 'var(--border)' }} />

          {/* Action chips */}
          <div style={{ display: 'flex', gap: 6 }}>
            {actions.map(a => (
              <Chip key={a} label={a} active={action === a} onClick={() => setAction(a)} />
            ))}
          </div>

          <div style={{ width: 1, height: 24, background: 'var(--border)' }} />

          {/* M/WBE vehicles — the notices explicitly reserved for certified firms */}
          <Chip label="M/WBE only" active={mwbeOnly} onClick={() => setMwbeOnly(!mwbeOnly)} />
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
