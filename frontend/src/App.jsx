import { useEffect, useState, useCallback, useRef } from 'react'
import { flushSync } from 'react-dom'

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
  const stampRefs = useRef({})                      // grid .thumb by stamp id

  // Open with a shared-element morph: the framed stamp flies into full screen.
  const openStamp = (id) => {
    const el = stampRefs.current[id]
    if (!document.startViewTransition || !el) {
      setSelected(id)
      return
    }
    el.style.viewTransitionName = 'stamp'           // old snapshot = this thumb
    document.startViewTransition(() => {
      el.style.viewTransitionName = ''             // clear before render → no duplicate
      flushSync(() => setSelected(id))              // new snapshot = full-screen img
    })
  }

  // Close with the reverse morph: full-screen image flies back to its grid cell.
  const closeStamp = () => {
    const el = stampRefs.current[selected]
    if (!document.startViewTransition) {
      setSelected(null)
      return
    }
    const t = document.startViewTransition(() => {
      flushSync(() => setSelected(null))
      if (el) el.style.viewTransitionName = 'stamp'
    })
    t.finished.finally(() => {
      if (el) el.style.viewTransitionName = ''
    })
  }

  const [hero, setHero] = useState([])      // 5 portrait stamps for the fan
  const [dealt, setDealt] = useState(false)
  const [stuck, setStuck] = useState(false) // toolbar pinned to top?
  const [curBucket, setCurBucket] = useState(null) // section under the toolbar
  const sentinelRef = useRef(null)
  const sectionRefs = useRef({})

  // toolbar shows the year range only once it sticks to the top
  useEffect(() => {
    const el = sentinelRef.current
    if (!el) return
    const obs = new IntersectionObserver(
      ([e]) => setStuck(!e.isIntersecting),
      { threshold: 0 },
    )
    obs.observe(el)
    return () => obs.disconnect()
  }, [])

  useEffect(() => {
    fetch(`${API}/gallery`)
      .then((r) => r.json())
      .then((d) => {
        setBuckets(d.buckets)
        setCounts(d.counts)
        setTotal(d.total)
        const imaged = d.stamps.filter((s) => s.has_image)
        setStamps(imaged)
        // 5 random portrait stamps for the hero fan
        const portrait = imaged.filter((s) => s.h && s.w && s.h > s.w * 1.15)
        const pool = portrait.length >= 5 ? portrait : imaged
        setHero([...pool].sort(() => Math.random() - 0.5).slice(0, 5))
      })
      .catch(() => setError('Could not reach the API. Is it running on :8000?'))
  }, [])

  // deal the fan out shortly after it mounts
  useEffect(() => {
    if (!hero.length) return
    const t = setTimeout(() => setDealt(true), 250)
    return () => clearTimeout(t)
  }, [hero])

  const shown = active === 'all' ? stamps : stamps.filter((s) => s.bucket === active)

  // group shown stamps by bucket, preserving API order
  const groups = buckets
    .map((b) => ({ bucket: b, items: shown.filter((s) => s.bucket === b) }))
    .filter((g) => g.items.length)

  // scroll-spy: the range label reflects the section currently under the toolbar
  useEffect(() => {
    const onScroll = () => {
      let cur = null
      for (const g of groups) {
        const el = sectionRefs.current[g.bucket]
        if (el && el.getBoundingClientRect().top - 72 <= 0) cur = g.bucket
      }
      setCurBucket(cur || (groups[0] && groups[0].bucket) || null)
    }
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [groups])

  const rangeBucket = curBucket || (active !== 'all' ? active : buckets[0])
  const rangeLabel = rangeBucket ? (LABELS[rangeBucket] || rangeBucket) : '1922–2026'
  const rangeCount = rangeBucket ? counts[rangeBucket] : total

  return (
    <div className="app">
      <header className="hero">
        <div className={dealt ? 'fan dealt' : 'fan'}>
          {hero.map((s, i) => (
            <div
              className="fan-card"
              key={s.id}
              style={{
                '--i': i - 2,
                transitionDelay: `${Math.abs(i - 2) * 0.07}s`,
                zIndex: 5 - Math.abs(i - 2),
              }}
            >
              <img src={`${API}/stamps/${s.id}/thumb?size=400&perf=1`} alt="" />
            </div>
          ))}
        </div>
        <h1>Irish Stamp Gallery</h1>
        <p className="sub">{total.toLocaleString()} stamps · 1922–2026</p>
      </header>

      <div ref={sentinelRef} className="sticky-sentinel" />
      <div className={stuck ? 'toolbar stuck' : 'toolbar'}>
        <div className="range">{rangeLabel} <span>{rangeCount}</span></div>
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
      </div>

      {error && <p className="error">{error}</p>}

      {groups.map((g) => (
        <section
          key={g.bucket}
          ref={(el) => { sectionRefs.current[g.bucket] = el }}
        >
          <h2>
            {LABELS[g.bucket] || g.bucket} <span>{g.items.length}</span>
          </h2>
          <div className="grid">
            {g.items.map((s) => (
              <button
                key={s.id}
                ref={(el) => { stampRefs.current[s.id] = el }}
                className="thumb"
                onClick={() => openStamp(s.id)}
                title={s.title}
              >
                <img
                  loading="lazy"
                  src={`${API}/stamps/${s.id}/thumb`}
                  alt={s.title}
                />
                <span className="cap">
                  {s.title}
                  {s.year && <span className="yr"> · {s.year}</span>}
                </span>
              </button>
            ))}
          </div>
        </section>
      ))}

      {selected && (
        <DetailModal id={selected} onClose={closeStamp} />
      )}
    </div>
  )
}

function DetailModal({ id, onClose }) {
  const [stamp, setStamp] = useState(null)
  // start with the (already-cached) thumb for an instant morph, then sharpen
  const [src, setSrc] = useState(`${API}/stamps/${id}/thumb`)
  const esc = useCallback((e) => e.key === 'Escape' && onClose(), [onClose])

  useEffect(() => {
    fetch(`${API}/stamps/${id}`).then((r) => r.json()).then(setStamp)
    const hi = new Image()
    hi.onload = () => setSrc(`${API}/stamps/${id}/thumb?size=1600&perf=1`)
    hi.src = `${API}/stamps/${id}/thumb?size=1600&perf=1`
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
    <div className="fs">
      <div
        className="fs-bg"
        aria-hidden="true"
        style={{ backgroundImage: `url(${src})` }}
      />
      <button className="fs-close" onClick={onClose} title="Back to gallery">×</button>
      <div className="fs-img" style={{ viewTransitionName: 'stamp' }}>
        <img src={src} alt={stamp?.title || ''} />
      </div>
      <div className="fs-info">
        {!stamp ? (
          <p className="loading">Loading…</p>
        ) : (
          <>
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
          </>
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
