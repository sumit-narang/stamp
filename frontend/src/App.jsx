import { useEffect, useState, useCallback } from 'react'

const API = 'http://localhost:8000'

// Friendly bucket labels. Written high→low so the chips read as one continuous
// descending timeline (2026→2020, 2019→2011, …) matching the newest-first order.
const LABELS = {
  '2020-2026': '2026–2020',
  '2011-2019': '2019–2011',
  '2001-2010': '2010–2001',
  '1984-2000': '2000–1984',
  '1922-1983': '1983–1922',
}

export default function App() {
  const [buckets, setBuckets] = useState([])
  const [counts, setCounts] = useState({})
  const [total, setTotal] = useState(0)
  const [stamps, setStamps] = useState([])
  const [active, setActive] = useState('all')
  const [selected, setSelected] = useState(null)   // stamp id for modal
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch(`${API}/gallery`)
      .then((r) => r.json())
      .then((d) => {
        setBuckets(d.buckets)
        setCounts(d.counts)
        setTotal(d.total)
        setStamps(d.stamps.filter((s) => s.has_image))
      })
      .catch(() => setError('Could not reach the API. Is it running on :8000?'))
  }, [])

  const shown = active === 'all' ? stamps : stamps.filter((s) => s.bucket === active)

  // group shown stamps by bucket, preserving API order
  const groups = buckets
    .map((b) => ({ bucket: b, items: shown.filter((s) => s.bucket === b) }))
    .filter((g) => g.items.length)

  return (
    <div className="app">
      <header>
        <h1>Irish Stamp Gallery</h1>
        <p className="sub">{total.toLocaleString()} stamps · 1922–2026</p>
      </header>

      <nav className="filters">
        <button
          className={active === 'all' ? 'chip on' : 'chip'}
          onClick={() => setActive('all')}
        >
          All <span>{stamps.length}</span>
        </button>
        {buckets.map((b) => (
          <button
            key={b}
            className={active === b ? 'chip on' : 'chip'}
            onClick={() => setActive(b)}
          >
            {LABELS[b] || b} <span>{counts[b] || 0}</span>
          </button>
        ))}
      </nav>

      {error && <p className="error">{error}</p>}

      {groups.map((g) => (
        <section key={g.bucket}>
          <h2>
            {LABELS[g.bucket] || g.bucket} <span>{g.items.length}</span>
          </h2>
          <div className="grid">
            {g.items.map((s) => (
              <button
                key={s.id}
                className="thumb"
                onClick={() => setSelected(s.id)}
                title={s.title}
              >
                <img
                  loading="lazy"
                  src={`${API}${s.image_api}`}
                  alt={s.title}
                />
              </button>
            ))}
          </div>
        </section>
      ))}

      {selected && (
        <DetailModal id={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  )
}

function DetailModal({ id, onClose }) {
  const [stamp, setStamp] = useState(null)
  const esc = useCallback((e) => e.key === 'Escape' && onClose(), [onClose])

  useEffect(() => {
    fetch(`${API}/stamps/${id}`).then((r) => r.json()).then(setStamp)
    document.addEventListener('keydown', esc)
    return () => document.removeEventListener('keydown', esc)
  }, [id, esc])

  const dateLabel = (s) => {
    if (s.issue_date) return s.issue_date
    if (s.year) return `${s.year} (year only)`
    if (s.bucket) return `circa ${LABELS[s.bucket] || s.bucket}`
    return 'unknown'
  }

  return (
    <div className="overlay" onClick={onClose}>
      <div className="card" onClick={(e) => e.stopPropagation()}>
        <button className="x" onClick={onClose}>×</button>
        {!stamp ? (
          <p className="loading">Loading…</p>
        ) : (
          <div className="card-body">
            <div className="card-img">
              <img src={`${API}/stamps/${id}/image`} alt={stamp.title} />
            </div>
            <div className="card-info">
              <h3>{stamp.title}</h3>
              <Row k="Issue date" v={dateLabel(stamp)} />
              <Row k="Face value" v={stamp.value_display} />
              <Row k="Currency" v={stamp.currency} />
              <Row k="Type" v={(stamp.issue_types || []).join(', ')} />
              <Row k="Designer" v={stamp.designer} />
              <Row k="Series" v={stamp.series} />
              <Row k="Bucket" v={LABELS[stamp.bucket] || stamp.bucket} />
              <Row k="Date source" v={stamp.date_source} />
              {stamp.image_dimensions?.[0] && (
                <Row k="Image" v={`${stamp.image_dimensions[0]}×${stamp.image_dimensions[1]}`} />
              )}
              <Row k="Rights" v={stamp.rights} small />
              {stamp.source_url && (
                <p className="src">
                  <a href={stamp.source_url} target="_blank" rel="noreferrer">
                    Source record ↗
                  </a>
                </p>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function Row({ k, v, small }) {
  if (!v) return null
  return (
    <p className={small ? 'row small' : 'row'}>
      <span className="k">{k}</span>
      <span className="v">{v}</span>
    </p>
  )
}
