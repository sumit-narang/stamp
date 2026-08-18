import { useEffect, useState, useCallback, useRef } from 'react'
import { flushSync } from 'react-dom'

// API base: same-origin `/stamp-api` in production (set via VITE_API_URL at build
// time), falling back to the local dev server.
const API = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

// Friendly bucket labels. Written high→low so the chips read as one continuous
// descending timeline (2026→2020, 2019→2011, …) matching the newest-first order.
const LABELS = {
  '2020-2026': '2026 - 2020',
  '2011-2019': '2019 - 2011',
  '2001-2010': '2010 - 2001',
  '1984-2000': '2000 - 1984',
  '1922-1983': '1983 - 1922',
}

// issue_date is stored ISO (YYYY-MM-DD); the detail view shows it DD-MM-YYYY.
// A handful of rows hold scrape junk instead of a date, so anything that is not
// a well-formed ISO date is passed through untouched rather than mangled.
const isoToDmy = (d) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(d)
  return m ? `${m[3]}-${m[2]}-${m[1]}` : d
}

// the 5 hand-picked stamps shown in the hero fan (left → right)
const HERO_IDS = [
  'cz313h371', // Irish Handcrafts (harp maker)
  '3r07jj778', // F.I.F.A World Cup 1990
  'dj538v485', // Irish Dance
  'tx324745r', // Cliffs of Moher
  '95947j956', // Sheep – Donegal Blackface
]

// icons from /image/*.svg — inlined so they inherit the button's currentColor.
// stroke-widths normalised so all three render at the same visual weight
// (the cross's 2.667/24 ratio, scaled to each icon's viewBox).
const MoonIcon = () => (
  <svg width="20" height="20" viewBox="0 0 534 534" fill="none" aria-hidden="true">
    <path d="M266.667 33.3423C137.8 33.3423 33.3334 137.809 33.3334 266.676C33.3334 395.542 137.8 500.009 266.667 500.009C372.367 500.009 471.317 439.389 500 343.006" stroke="currentColor" strokeWidth="50" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M500 333.342C494.397 333.342 488.84 333.146 483.333 332.756C283.333 366.676 183.334 250.009 266.667 33.3423" stroke="currentColor" strokeWidth="50" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)
const SunIcon = () => (
  <svg width="20" height="20" viewBox="0 0 734 734" fill="none" aria-hidden="true">
    <path d="M366.667 33.3334V100M366.667 633.333V700M100 366.667H33.3334M177.137 177.137L129.997 129.997M556.197 177.137L603.337 129.997M177.137 556.333L129.997 603.473M556.197 556.333L603.337 603.473M700 366.667H633.333M533.333 366.667C533.333 458.713 458.713 533.333 366.667 533.333C274.619 533.333 200 458.713 200 366.667C200 274.619 274.619 200 366.667 200C458.713 200 533.333 274.619 533.333 366.667Z" stroke="currentColor" strokeWidth="69" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)
const CloseIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M18 6L6 18" stroke="currentColor" strokeWidth="2.667" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M6 6L18 18" stroke="currentColor" strokeWidth="2.667" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

// The perforation is already baked into each image's alpha channel, so the CSS
// mask below is *only* there to clip the hover caption to the stamp's silhouette.
// It costs a second, no-cors download of the same file for every tile (CSS image
// loads don't share the <img crossOrigin> cache entry) — so on touch devices,
// where there is no hover and the caption never shows, skip it entirely.
const HOVERS = window.matchMedia('(hover: hover)').matches

export default function App() {
  const [buckets, setBuckets] = useState([])
  const [counts, setCounts] = useState({})
  const [total, setTotal] = useState(0)
  const [stamps, setStamps] = useState([])
  const [active, setActive] = useState('all')
  const [selected, setSelected] = useState(null)   // stamp id for modal
  const [error, setError] = useState(null)
  const stampRefs = useRef({})                      // grid .thumb by stamp id

  // the shared-element morph is janky on mobile — open/close instantly there
  // (the detail already starts from the cached grid image, so it's immediate)
  const noMorph = () =>
    !document.startViewTransition ||
    window.matchMedia('(max-width: 720px)').matches ||
    window.matchMedia('(prefers-reduced-motion: reduce)').matches

  // Open with a shared-element morph: the framed stamp flies into full screen.
  const openStamp = (id) => {
    const el = stampRefs.current[id]
    if (noMorph() || !el) {
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
    if (noMorph()) {
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
  const [curBucket, setCurBucket] = useState(null) // section handed off to the bar
  const [showTop, setShowTop] = useState(false) // scroll-to-top button
  const [fade, setFade] = useState({ l: false, r: false }) // filter-row scroll fades
  const filtersRef = useRef(null)

  // show a fade on whichever side of the filter row still has hidden chips
  const updateFade = useCallback(() => {
    const el = filtersRef.current
    if (!el) return
    setFade({
      l: el.scrollLeft > 2,
      r: el.scrollLeft + el.clientWidth < el.scrollWidth - 2,
    })
  }, [])
  useEffect(() => {
    updateFade()
    window.addEventListener('resize', updateFade)
    window.addEventListener('scroll', updateFade, { passive: true })
    return () => {
      window.removeEventListener('resize', updateFade)
      window.removeEventListener('scroll', updateFade)
    }
  }, [updateFade, buckets])
  const [theme, setTheme] = useState(() =>
    localStorage.getItem('theme') ||
    (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'),
  )

  // apply + persist the theme
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('theme', theme)
  }, [theme])

  // lock page scroll while the full-screen detail is open (grid behind stays put)
  useEffect(() => {
    const html = document.documentElement
    html.style.overflow = selected ? 'hidden' : ''
    return () => { html.style.overflow = '' }
  }, [selected])
  const sentinelRef = useRef(null)
  const sectionRefs = useRef({})
  const headingRefs = useRef({})           // each section's <h2>
  const toolbarRef = useRef(null)
  const lastY = useRef(0)

  // reveal the scroll-to-top button only while scrolling back up (and not near top)
  useEffect(() => {
    const onScroll = () => {
      const y = window.scrollY
      const scrollingUp = y < lastY.current
      setShowTop(scrollingUp && y > window.innerHeight * 0.3)
      lastY.current = y
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

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
        // the fixed hand-picked hero fan
        setHero(HERO_IDS.map((id) => imaged.find((s) => s.id === id)).filter(Boolean))
      })
      .catch(() => setError('Could not reach the API. Is it running on :8000?'))
  }, [])

  // deal the fan out shortly after it mounts
  useEffect(() => {
    if (!hero.length) return
    const t = setTimeout(() => setDealt(true), 250)
    return () => clearTimeout(t)
  }, [hero])

  // Width of a grid column, measured from a real tile. `content-visibility: auto`
  // sizes off-screen tiles from contain-intrinsic-size (aspect-ratio does NOT
  // override it), so a single flat guess for all 2,771 tiles made the page length
  // re-estimate continuously while scrolling — ~10,000px of drift. With the
  // column width known we can give every tile its true height instead.
  const [tileW, setTileW] = useState(0)
  useEffect(() => {
    const measure = () => {
      const t = document.querySelector('.thumb')
      if (t) setTileW(t.offsetWidth)
    }
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [stamps.length])

  const shown = active === 'all' ? stamps : stamps.filter((s) => s.bucket === active)

  // group shown stamps by bucket, preserving API order
  const groups = buckets
    .map((b) => ({ bucket: b, items: shown.filter((s) => s.bucket === b) }))
    .filter((g) => g.items.length)

  // scroll-spy hand-off: the sticky bar shows a section's range only once that
  // section's grid heading has scrolled up fully under the toolbar (so the grid
  // heading and the bar label are never visible at the same time).
  useEffect(() => {
    const onScroll = () => {
      const tb = toolbarRef.current
      const line = tb ? tb.getBoundingClientRect().bottom : 64
      let cur = null
      for (const g of groups) {
        const el = headingRefs.current[g.bucket]
        if (el && el.getBoundingClientRect().bottom <= line + 1) cur = g.bucket
      }
      setCurBucket(cur)
    }
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [groups])

  const rangeLabel = curBucket ? (LABELS[curBucket] || curBucket) : ''
  const rangeCount = curBucket ? counts[curBucket] : ''

  // changing filter swaps the content in place — keep the scroll position so the
  // pinned toolbar stays put and only the grid below it updates
  const selectFilter = (b) => {
    if (b === active) return
    setActive(b)
  }

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
                transitionDelay: `${Math.abs(i - 2) * 0.06}s`,
                zIndex: 5 - Math.abs(i - 2),
              }}
            >
              <span className="fan-stamp">
                <img src={`${API}/stamps/${s.id}/thumb?perf=1&frame=1&size=400`} alt="" />
              </span>
            </div>
          ))}
        </div>
        <h1>Irish Stamp Gallery</h1>
        <p className="sub">Every Irish postage stamp since 1922</p>
      </header>

      <div ref={sentinelRef} className="sticky-sentinel" />
      <div
        ref={toolbarRef}
        className={`toolbar${stuck ? ' stuck' : ''}${curBucket ? ' has-range' : ''}`}
      >
        <div className="range">{rangeLabel} <span>{rangeCount}</span></div>
        <div className="tb-spacer" />
        <div className={`filters-wrap${fade.l ? ' fade-l' : ''}${fade.r ? ' fade-r' : ''}`}>
          <nav className="filters" ref={filtersRef} onScroll={updateFade}>
            <button
              className={active === 'all' ? 'chip on' : 'chip'}
              onClick={() => selectFilter('all')}
            >
              All <span>{stamps.length}</span>
            </button>
            {buckets.map((b) => (
              <button
                key={b}
                className={active === b ? 'chip on' : 'chip'}
                onClick={() => selectFilter(b)}
              >
                {LABELS[b] || b} <span>{counts[b] || 0}</span>
              </button>
            ))}
          </nav>
        </div>
      </div>

      {error && <p className="error">{error}</p>}

      {groups.map((g) => (
        <section
          key={g.bucket}
          ref={(el) => { sectionRefs.current[g.bucket] = el }}
        >
          <h2 ref={(el) => { headingRefs.current[g.bucket] = el }}>
            {LABELS[g.bucket] || g.bucket} <span>{g.items.length}</span>
          </h2>
          <div className="grid">
            {g.items.map((s) => {
              const perfSrc = `${API}/stamps/${s.id}/thumb?perf=1&frame=1&size=360`
              // tw/th are the tile's real post-trim size; w/h (untrimmed) are only
              // a fallback for thumbs the API has not generated yet.
              const tw = s.tw || s.w
              const th = s.th || s.h
              const ratio = tw && th ? `${tw} / ${th}` : undefined
              return (
              <button
                key={s.id}
                ref={(el) => { stampRefs.current[s.id] = el }}
                className="thumb"
                onClick={() => openStamp(s.id)}
                title={s.title}
                style={{
                  ...(ratio ? { aspectRatio: ratio } : null),
                  // the height this tile will really occupy, so skipped tiles
                  // reserve exactly the right space and the page stops resizing
                  ...(tileW && tw && th
                    ? { containIntrinsicSize: `auto ${tileW}px auto ${Math.round((tileW * th) / tw)}px` }
                    : null),
                }}
              >
                <span
                  className="thumb-cut"
                  style={HOVERS
                    ? { WebkitMaskImage: `url("${perfSrc}")`, maskImage: `url("${perfSrc}")` }
                    : undefined}
                >
                  <img
                    loading="lazy"
                    crossOrigin="anonymous"
                    src={perfSrc}
                    alt={s.title}
                    style={ratio ? { aspectRatio: ratio } : undefined}
                  />
                  <span className="cap">
                    {s.title}
                    {s.year && <span className="yr"> · {s.year}</span>}
                  </span>
                </span>
              </button>
              )
            })}
          </div>
        </section>
      ))}

      {selected && (
        <DetailModal
          id={selected}
          ar={(() => {
            const s = stamps.find((x) => x.id === selected)
            const w = s && (s.tw || s.w)
            const h = s && (s.th || s.h)
            return w && h ? w / h : null
          })()}
          onClose={closeStamp}
        />
      )}

      {!selected && (
        <button
          className="theme-toggle"
          onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
          aria-label="Toggle dark mode"
          title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
        >
          {theme === 'dark' ? <SunIcon /> : <MoonIcon />}
        </button>
      )}

      {!selected && (
        <button
          className={showTop ? 'to-top show' : 'to-top'}
          onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
        >
          Back to top
        </button>
      )}
    </div>
  )
}

function DetailModal({ id, ar, onClose }) {
  const [stamp, setStamp] = useState(null)
  // reuse the exact grid image (already cached) so the detail shows instantly
  const gridSrc = `${API}/stamps/${id}/thumb?perf=1&frame=1&size=360`
  const [src, setSrc] = useState(gridSrc)
  const esc = useCallback((e) => e.key === 'Escape' && onClose(), [onClose])

  useEffect(() => {
    fetch(`${API}/stamps/${id}`).then((r) => r.json()).then(setStamp)
    // The visible image always starts as the already-cached grid tile, so the
    // detail paints immediately; a sharper one is fetched in the background and
    // swapped in only once it has fully decoded (never a blank or half-drawn
    // frame). Mobile used to skip this entirely because the old PNGs were ~600KB;
    // as WebP the same upgrade is ~50-100KB, so it is affordable over cellular.
    const mobile = window.matchMedia('(max-width: 720px)').matches
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const target = mobile
      ? Math.round(window.innerWidth * 0.92 * dpr)
      : Math.round(Math.max(window.innerWidth * 0.48, window.innerHeight * 0.82) * dpr)
    const cap = mobile ? 1000 : 1600
    const hiRes = `${API}/stamps/${id}/thumb?size=${Math.min(cap, Math.max(700, target))}&perf=1`

    // respect Data Saver / genuinely slow links — the cached grid image is enough
    const net = navigator.connection
    const thrifty = net && (net.saveData || /(^|-)2g$/.test(net.effectiveType || ''))

    let hi
    if (!thrifty) {
      hi = new Image()
      hi.crossOrigin = 'anonymous'
      hi.onload = () => setSrc(hiRes)
      hi.src = hiRes
    }
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('keydown', esc)
      if (hi) hi.onload = null       // closed before it arrived — don't setSrc after unmount
    }
  }, [id, esc])

  const dateLabel = (s) => {
    if (s.issue_date) return isoToDmy(s.issue_date)
    if (s.year) return `${s.year} (year only)`
    if (s.bucket) return `circa ${LABELS[s.bucket] || s.bucket}`
    return 'unknown'
  }

  return (
    <div className="fs">
      {/* Backdrop uses the grid tile, never `src`: it is blurred to 70px so the
          extra detail is invisible, and a CSS background is a no-cors request
          that would not reuse the <img crossOrigin> cache entry — pointing it at
          the hi-res downloaded the sharpened image a second time. */}
      <div
        className="fs-bg"
        aria-hidden="true"
        style={{ backgroundImage: `url(${gridSrc})` }}
      />
      <button className="fs-close" onClick={onClose} title="Back to gallery"><CloseIcon /></button>
      {/* --ar lets the image occupy its final box from the very first frame.
          Without it the box is sized by whatever is loaded: the cached 360px
          grid tile is narrower than the 48vw cap, so it rendered small and then
          jumped larger when the sharpened version arrived. Mobile never showed
          this because 92vw ~= 360px there. */}
      <div
        className="fs-img"
        style={{ viewTransitionName: 'stamp', ...(ar ? { '--ar': ar } : {}) }}
      >
        {/* crossOrigin matches the grid <img> so the cached grid image is reused
            (CORS and non-CORS requests cache separately) → instant on open */}
        <img src={src} alt={stamp?.title || ''} crossOrigin="anonymous" />
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
            {stamp.image_dimensions?.[0] && (
              <Row k="Image" v={`${stamp.image_dimensions[0]}×${stamp.image_dimensions[1]}`} />
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
