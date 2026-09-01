// Instellingen v3 — twee-paneel-layout (mockup instellingen-v3.html, akkoord Peter 01-09):
// vaste linker settings-nav (zoekveld bovenaan, drie groepen, compacte stand-chips per item) op
// ÉLKE /instellingen-route + content rechts. ≤ 768px klapt de nav naar een uitklaplijst boven de
// content (ontwerpnotitie ⑩, bestaand zijbalk-patroon). Rol×sectie-matrix fail-closed: de nav
// toont alleen zichtbare items, een lege groep krijgt geen kop (ontwerpnotitie ⑦).
import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { Link, NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import {
  type InstellingenSectie,
  type ZoekAdministratie,
  zichtbareNavGroepen,
  zoekInstellingen,
} from './instellingenRegistry'

/** Compacte standen per nav-item (mockup: "24", "aan", "41%", oranje teller) — de landing-chips van
 * D2 verliezen zo niets. Alleen gevulde waarden renderen. */
export interface NavStanden {
  administraties?: number
  /** Autoboek-kandidaten (blok B): oranje teller zolang > 0. */
  autoboekKandidaten?: number
  boekenPlatformbreed?: boolean
  intakeAiPercentage?: number
}

interface Props {
  actief: InstellingenSectie | null
  standen?: NavStanden
  /** Voor de administratie-specifieke zoektreffers ("accordering arvum"). */
  administraties?: readonly ZoekAdministratie[]
  children: React.ReactNode
}

function Stand({ pad, standen }: { pad: InstellingenSectie; standen: NavStanden }) {
  switch (pad) {
    case 'administraties':
      return standen.administraties !== undefined ? <span className="snav-st">{standen.administraties}</span> : null
    case 'autoboeken':
      return standen.autoboekKandidaten ? <span className="snav-tel">{standen.autoboekKandidaten}</span> : null
    case 'boeken':
      return standen.boekenPlatformbreed === undefined ? null : (
        <span className={standen.boekenPlatformbreed ? 'snav-st' : 'snav-tel'}>{standen.boekenPlatformbreed ? 'aan' : 'uit'}</span>
      )
    case 'intake-ai':
      return standen.intakeAiPercentage === undefined ? null : (
        <span className={standen.intakeAiPercentage >= 80 ? 'snav-tel' : 'snav-st'}>{standen.intakeAiPercentage}%</span>
      )
    default:
      return null
  }
}

export function InstellingenZoeker({ administraties }: { administraties: readonly ZoekAdministratie[] }) {
  const { rol } = useAuth()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [focus, setFocus] = useState(0)
  const lijstId = useId()
  const wrapper = useRef<HTMLDivElement>(null)
  const treffers = useMemo(() => zoekInstellingen(query, { rol, administraties }), [query, rol, administraties])

  useEffect(() => {
    if (!open) return
    const sluit = (e: MouseEvent) => {
      if (wrapper.current && !wrapper.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', sluit)
    return () => document.removeEventListener('mousedown', sluit)
  }, [open])

  const kies = (pad: string) => {
    setOpen(false)
    setQuery('')
    navigate(pad)
  }

  return (
    <div className="snav-zoek" ref={wrapper}>
      <input
        type="search"
        role="combobox"
        aria-label="Zoek instelling"
        aria-expanded={open && treffers.length > 0}
        aria-controls={lijstId}
        aria-autocomplete="list"
        placeholder="Zoek instelling…"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value)
          setOpen(true)
          setFocus(0)
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') {
            e.preventDefault()
            setFocus((f) => Math.min(f + 1, treffers.length - 1))
          } else if (e.key === 'ArrowUp') {
            e.preventDefault()
            setFocus((f) => Math.max(f - 1, 0))
          } else if (e.key === 'Enter' && treffers[focus]) {
            e.preventDefault()
            kies(treffers[focus].pad)
          } else if (e.key === 'Escape') {
            setOpen(false)
          }
        }}
      />
      {open && query.trim() !== '' && (
        <ul id={lijstId} role="listbox" className="snav-zoekres" data-testid="instellingen-zoekresultaten">
          {treffers.length === 0 && (
            <li className="snav-zoekres-leeg" aria-disabled>
              Geen instelling gevonden voor &ldquo;{query}&rdquo;.
            </li>
          )}
          {treffers.map((t, i) => (
            <li
              key={t.sleutel}
              role="option"
              aria-selected={i === focus}
              className={i === focus ? 'actief' : undefined}
              onMouseEnter={() => setFocus(i)}
              onMouseDown={(e) => {
                e.preventDefault()
                kies(t.pad)
              }}
            >
              <span>{t.administratie ? <b>{t.naam}</b> : t.naam}</span>
              <span className="snav-zoekres-waar">{t.waar}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function InstellingenLayout({ actief, standen = {}, administraties = [], children }: Props) {
  const { rol } = useAuth()
  const groepen = zichtbareNavGroepen(rol)
  const actiefItem = groepen.flatMap((g) => g.items).find((i) => i.pad === actief)
  const [mobielOpen, setMobielOpen] = useState(false)
  const inhoudId = useId()

  const nav = (
    <>
      <InstellingenZoeker administraties={administraties} />
      {groepen.map((g) => (
        <div key={g.titel} className="snav-groep-blok">
          <div className="snav-groep">{g.titel}</div>
          {g.items.map((item) => {
            const inhoud = (
              <>
                <span>{item.titel}</span>
                <Stand pad={item.pad} standen={standen} />
              </>
            )
            return item.extern ? (
              <Link key={item.pad} to={item.extern} className="snav-item">
                {inhoud}
              </Link>
            ) : (
              <NavLink
                key={item.pad}
                to={`/instellingen/${item.pad}`}
                className={({ isActive }) => `snav-item${isActive || actief === item.pad ? ' actief' : ''}`}
                aria-current={actief === item.pad ? 'page' : undefined}
              >
                {inhoud}
              </NavLink>
            )
          })}
        </div>
      ))}
    </>
  )

  return (
    <div className="instellingen-laag" data-testid="instellingen-laag">
      <nav className={`snav${mobielOpen ? ' open' : ''}`} aria-label="Instellingen">
        {/* ≤ 768px: de nav klapt naar een uitklaplijst boven de content (CSS toont de knop alleen
            daar; op desktop staat .snav-inhoud altijd open). */}
        <button
          type="button"
          className="snav-toggle"
          aria-expanded={mobielOpen}
          aria-controls={inhoudId}
          onClick={() => setMobielOpen((o) => !o)}
        >
          <span className="snav-mobiel-label">Instellingen</span>
          <b>{actiefItem?.titel ?? 'Kies een onderdeel'}</b>
          <span aria-hidden>{mobielOpen ? '▴' : '▾'}</span>
        </button>
        <div id={inhoudId} className="snav-inhoud" onClick={(e) => { if ((e.target as HTMLElement).closest('a')) setMobielOpen(false) }}>
          {nav}
        </div>
      </nav>
      <div className="instellingen-content">{children}</div>
    </div>
  )
}
