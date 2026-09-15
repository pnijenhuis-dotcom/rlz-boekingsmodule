// Inline-PDF-weergave voor de accordeur-PWA en de veld-app. pdfjs-dist rendert álle pagina's als canvas —
// een <object>/<iframe> toont op iOS Safari alleen de eerste pagina (bekende beperking), en
// het factuurbeeld is hier juist het centrale element (mockup). De bibliotheek wordt LAZY
// geïmporteerd (performance-budget: pdf.js zit niet in de startbundle, laadt pas bij de
// eerste factuur die opent).
//
// Feedbackpunt 2 (26-08, mockup accordeur-vragen.html): NOOIT stil wit. Expliciete laadstate
// ("PDF laden…" + spinner), zichtbare fout mét retry-knop, en een tijdslimiet op het renderen.
// OORZAAK van het witte vlak op het toestel (12:09-casus, warme backend): de eerstvolgende factuur
// wordt verborgen (display:none) voorgerenderd — daar is `container.clientWidth` 0, dus de
// schaal negatief/0 en elke pagina een lege canvas; bij het openen rendert niets opnieuw. Fix:
// de blob wordt wél alvast opgehaald én het PDF-document geparsed (prefetch blijft), maar pagina's
// worden pas getekend zodra de weergave ACTIEF is en het vak een breedte heeft (`actief`-prop +
// ResizeObserver); breedte 0 valt terug op de vensterbreedte.
//
// Peter 15-09 (inzoomen op de factuur): in de native app (Capacitor-WebView, viewport niet schaalbaar) en de
// PWA-standalone werkte knijpen niet of scrolde de hele app mee. Daarom een EIGEN zoomlaag (pdfZoom.ts, puur getest):
// knijpzoom 1×–4× met focuspunt, dubbeltik = 2× op de tikplek (of terug), pannen bínnen het vak (touch-action none
// zodra ingezoomd — de rest van het scherm scrolt niet mee), knop "⤢ Volledig scherm" = dezelfde weergave als vast
// overlay over het hele scherm (alle pagina's, zoom + pannen, sluitknop, Escape én de terug-gebaar via history). Scherp
// blijven: pagina's worden getekend op de hoogst gebruikte zoomstap × devicePixelRatio; bij een stap > 1 alleen de
// zichtbare pagina's ±1 (geheugen begrensd), de rest houdt de stap-1-canvas. Eén component voor factuur (GoedkeurenFlow)
// én werkbonnen/offertes (UrenFlow).

import { useCallback, useEffect, useRef, useState } from 'react'
import type { PDFPageProxy } from 'pdfjs-dist/legacy/build/pdf.mjs'
import {
  afstand,
  BEGINSTAND,
  clampVerschuiving,
  dubbeltik,
  knijp,
  middelpunt,
  pan,
  renderStap,
  type ZoomStand,
} from './pdfZoom'

interface Props {
  blobUrl: string | null
  laden: boolean
  fout: string | null
  /** Zichtbaar gemonteerd? Verborgen (prefetch) = alleen parsen, niet tekenen. */
  actief?: boolean
  onOpnieuw?: () => void
  /** Intern: de fullscreen-overlay rendert dezelfde component zonder eigen fullscreen-knop. */
  volledigScherm?: boolean
}

export const RENDER_TIJDSLIMIET_MS = 20_000
const DUBBELTIK_MS = 300
const DUBBELTIK_PX = 30

type RenderStand = 'wacht' | 'bezig' | 'klaar' | 'fout'

interface Pagina {
  nummer: number
  canvas: HTMLCanvasElement
  /** pdf.js-pagina (voor herrenderen op een hogere stap). */
  pagina: PDFPageProxy
  basisBreedte: number
  basisHoogte: number
  /** Stap waarop de canvas nu getekend is (1 = basis). */
  stap: number
  /** Bovenkant in CSS-px op schaal 1 binnen de inhoud. */
  top: number
}

export function PdfWeergave({ blobUrl, laden, fout, actief = true, onOpnieuw, volledigScherm = false }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const inhoudRef = useRef<HTMLDivElement>(null)
  const paginasRef = useRef<Pagina[]>([])
  const [stand, setStand] = useState<RenderStand>('wacht')
  const [renderFout, setRenderFout] = useState<string | null>(null)
  const [poging, setPoging] = useState(0)
  const [breedte, setBreedte] = useState(0)
  const [zoom, setZoom] = useState<ZoomStand>(BEGINSTAND)
  const [fullscreen, setFullscreen] = useState(false)
  const zoomRef = useRef<ZoomStand>(BEGINSTAND)
  zoomRef.current = zoom

  // Breedte volgen: 0 zolang verborgen; zodra zichtbaar → render.
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const meet = () => setBreedte(el.clientWidth)
    meet()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(meet)
    ro.observe(el)
    return () => ro.disconnect()
  }, [actief, blobUrl])

  useEffect(() => {
    if (!blobUrl) {
      setStand('wacht')
      return
    }
    if (!actief) return
    let geannuleerd = false
    setRenderFout(null)
    setStand('bezig')
    setZoom(BEGINSTAND)
    const timer = setTimeout(() => {
      if (!geannuleerd) {
        geannuleerd = true
        setRenderFout('Het factuurbeeld laden duurt te lang.')
        setStand('fout')
      }
    }, RENDER_TIJDSLIMIET_MS)

    const render = async () => {
      // LEGACY-build (Android-bouwronde 29-08): de hoofdbuild van pdf.js 6 vereist o.a.
      // `Uint8Array.prototype.toHex` (Chromium ≥ 140) en faalde in de Android-WebView 133 van de
      // emulator met "n.toHex is not a function" — een verouderde WebView op een echt toestel
      // raakt dat óók. De legacy-build draagt de polyfills; zelfde API, zelfde worker-contract.
      const pdfjs = await import('pdfjs-dist/legacy/build/pdf.mjs')
      const workerModule = await import('pdfjs-dist/legacy/build/pdf.worker.min.mjs?url')
      pdfjs.GlobalWorkerOptions.workerSrc = workerModule.default
      const document_ = await pdfjs.getDocument({ url: blobUrl }).promise
      const inhoud = inhoudRef.current
      const container = containerRef.current
      if (!inhoud || !container || geannuleerd) return
      inhoud.replaceChildren()
      paginasRef.current = []
      // Renderscherpte: containerbreedte × devicePixelRatio; breedte 0 (nog niet gelay-out) →
      // vensterbreedte, nooit een negatieve schaal.
      const beschikbaar = (container.clientWidth || breedte || window.innerWidth) - 8
      const doelBreedte = Math.max(beschikbaar, 200)
      const dpr = Math.min(window.devicePixelRatio || 1, 3)
      let top = 0
      for (let n = 1; n <= document_.numPages; n++) {
        if (geannuleerd) return
        const pagina = await document_.getPage(n)
        const basis = pagina.getViewport({ scale: 1 })
        const schaal = (doelBreedte / basis.width) * dpr
        const viewport = pagina.getViewport({ scale: schaal })
        const canvas = document.createElement('canvas')
        canvas.width = viewport.width
        canvas.height = viewport.height
        canvas.style.width = `${viewport.width / dpr}px`
        const ctx = canvas.getContext('2d')
        if (!ctx) continue
        inhoud.appendChild(canvas)
        await pagina.render({ canvasContext: ctx, viewport, canvas }).promise
        const cssHoogte = viewport.height / dpr
        paginasRef.current.push({
          nummer: n,
          canvas,
          pagina,
          basisBreedte: doelBreedte,
          basisHoogte: cssHoogte,
          stap: 1,
          top,
        })
        top += cssHoogte + 8
      }
    }

    render()
      .then(() => {
        if (!geannuleerd) setStand('klaar')
      })
      .catch(() => {
        if (!geannuleerd) {
          setRenderFout('Het factuurbeeld kon niet weergegeven worden.')
          setStand('fout')
        }
      })
      .finally(() => clearTimeout(timer))
    return () => {
      geannuleerd = true
      clearTimeout(timer)
    }
  }, [blobUrl, actief, poging, breedte > 0])

  /** Scherp blijven bij inzoomen: zichtbare pagina's ±1 op de hoogst gebruikte stap hertekenen (geheugen begrensd). */
  const hertekenVoorStap = useCallback((z: ZoomStand) => {
    const stap = renderStap(z.schaal)
    const container = containerRef.current
    if (!container) return
    const dpr = Math.min(window.devicePixelRatio || 1, 3)
    const zichtTop = -z.y / z.schaal
    const zichtBodem = zichtTop + container.clientHeight / z.schaal
    for (const p of paginasRef.current) {
      const zichtbaar = p.top + p.basisHoogte >= zichtTop - p.basisHoogte && p.top <= zichtBodem + p.basisHoogte
      const doelStap = zichtbaar ? stap : 1
      if (p.stap === doelStap || (!zichtbaar && p.stap === 1)) continue
      const schaal = (p.basisBreedte / p.pagina.getViewport({ scale: 1 }).width) * dpr * doelStap
      const viewport = p.pagina.getViewport({ scale: schaal })
      p.canvas.width = viewport.width
      p.canvas.height = viewport.height
      p.canvas.style.width = `${viewport.width / (dpr * doelStap)}px`
      const ctx = p.canvas.getContext('2d')
      if (!ctx) continue
      p.stap = doelStap
      void p.pagina.render({ canvasContext: ctx, viewport, canvas: p.canvas }).promise
    }
  }, [])

  const inhoudHoogte = () => paginasRef.current.reduce((som, p) => som + p.basisHoogte + 8, 0)
  const viewportMaat = () => {
    const el = containerRef.current
    return { breedte: el?.clientWidth ?? window.innerWidth, hoogte: el?.clientHeight ?? window.innerHeight }
  }
  const zetZoom = useCallback(
    (z: ZoomStand) => {
      const geclampt = clampVerschuiving(z, viewportMaat(), inhoudHoogte())
      setZoom(geclampt)
      return geclampt
    },
    [], // eslint-disable-line react-hooks/exhaustive-deps
  )

  // --- gebaren (pointer events: één bron voor touch, muis en pen) ---
  const pointers = useRef(new Map<number, { x: number; y: number }>())
  const gebaar = useRef<{ begin: ZoomStand; beginAfstand: number; laatste?: { x: number; y: number } } | null>(null)
  const laatsteTik = useRef<{ t: number; x: number; y: number } | null>(null)
  const bewogen = useRef(false)

  const lokaal = (e: React.PointerEvent) => {
    const r = containerRef.current?.getBoundingClientRect()
    return { x: e.clientX - (r?.left ?? 0), y: e.clientY - (r?.top ?? 0) }
  }
  const onPointerDown = (e: React.PointerEvent) => {
    if (stand !== 'klaar') return
    pointers.current.set(e.pointerId, lokaal(e))
    bewogen.current = false
    const punten = [...pointers.current.values()]
    if (punten.length === 2) {
      gebaar.current = { begin: zoomRef.current, beginAfstand: afstand(punten[0], punten[1]) }
    } else if (punten.length === 1) {
      gebaar.current = { begin: zoomRef.current, beginAfstand: 0, laatste: punten[0] }
    }
    if (zoomRef.current.schaal > 1 || punten.length === 2) {
      // jsdom kent geen pointer capture; in de browser houdt dit het gebaar bij de viewport (ook buiten de rand).
      try {
        containerRef.current?.setPointerCapture?.(e.pointerId)
      } catch {
        /* niets — capture is comfort, geen vereiste */
      }
    }
  }
  const onPointerMove = (e: React.PointerEvent) => {
    if (!pointers.current.has(e.pointerId) || !gebaar.current) return
    const p = lokaal(e)
    pointers.current.set(e.pointerId, p)
    const punten = [...pointers.current.values()]
    if (punten.length === 2 && gebaar.current.beginAfstand > 0) {
      e.preventDefault()
      bewogen.current = true
      zetZoom(knijp(gebaar.current.begin, gebaar.current.beginAfstand, afstand(punten[0], punten[1]), middelpunt(punten[0], punten[1])))
    } else if (punten.length === 1 && gebaar.current.laatste && zoomRef.current.schaal > 1) {
      const dx = p.x - gebaar.current.laatste.x
      const dy = p.y - gebaar.current.laatste.y
      if (Math.abs(dx) + Math.abs(dy) > 2) bewogen.current = true
      gebaar.current.laatste = p
      e.preventDefault()
      zetZoom(pan(zoomRef.current, dx, dy))
    }
  }
  const onPointerUp = (e: React.PointerEvent) => {
    const p = pointers.current.get(e.pointerId)
    pointers.current.delete(e.pointerId)
    if (pointers.current.size === 0) {
      const vorige = gebaar.current
      gebaar.current = null
      if (!bewogen.current && p && vorige && vorige.beginAfstand === 0) {
        const nu = performance.now()
        const vorigeTik = laatsteTik.current
        if (vorigeTik && nu - vorigeTik.t < DUBBELTIK_MS && afstand(vorigeTik, p) < DUBBELTIK_PX) {
          laatsteTik.current = null
          hertekenVoorStap(zetZoom(dubbeltik(zoomRef.current, p)))
          return
        }
        laatsteTik.current = { t: nu, x: p.x, y: p.y }
      }
      hertekenVoorStap(zoomRef.current)
    } else if (pointers.current.size === 1) {
      // Van knijpen terug naar één vinger: doorpannen vanaf die vinger.
      const [rest] = [...pointers.current.values()]
      gebaar.current = { begin: zoomRef.current, beginAfstand: 0, laatste: rest }
    }
  }

  // Fullscreen: Escape en de terug-gebaar (history) sluiten; lichaam niet meescrollen.
  useEffect(() => {
    if (!fullscreen) return
    const sluit = () => setFullscreen(false)
    const toets = (e: KeyboardEvent) => {
      if (e.key === 'Escape') sluit()
    }
    window.history.pushState({ pdfFullscreen: true }, '')
    window.addEventListener('popstate', sluit)
    window.addEventListener('keydown', toets)
    const vorige = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('popstate', sluit)
      window.removeEventListener('keydown', toets)
      document.body.style.overflow = vorige
      if (window.history.state?.pdfFullscreen) window.history.back()
    }
  }, [fullscreen])

  const foutTekst = fout ?? renderFout
  const toonLaden = !foutTekst && (laden || stand === 'bezig' || (blobUrl !== null && stand === 'wacht'))
  const opnieuw = () => {
    setRenderFout(null)
    setStand('wacht')
    setPoging((p) => p + 1)
    onOpnieuw?.()
  }
  const ingezoomd = zoom.schaal > 1.001

  return (
    <div
      className={`acc-docpane${volledigScherm ? ' acc-docpane-vol' : ''}`}
      data-stand={foutTekst ? 'fout' : toonLaden ? 'laden' : stand}
      data-zoom={zoom.schaal.toFixed(2)}
    >
      {toonLaden && (
        <div className="acc-doc-laadt" role="status">
          <span className="acc-spinner" aria-hidden="true" />
          PDF laden…
        </div>
      )}
      {foutTekst && (
        <div className="acc-doc-fout" role="alert">
          <div>{foutTekst}</div>
          <button type="button" className="acc-btn klein secundair" onClick={opnieuw}>
            Opnieuw laden
          </button>
        </div>
      )}
      {stand === 'klaar' && !volledigScherm && (
        <div className="acc-doc-knoppen">
          {ingezoomd && (
            <button type="button" className="acc-tekstlink" onClick={() => setZoom(BEGINSTAND)} aria-label="Zoom terug naar 100 %">
              {Math.round(zoom.schaal * 100)} % · terug
            </button>
          )}
          <button
            type="button"
            className="acc-btn klein secundair"
            data-testid="pdf-volledig-scherm"
            onClick={() => setFullscreen(true)}
            aria-label="Factuur op volledig scherm bekijken"
          >
            ⤢ Volledig scherm
          </button>
        </div>
      )}
      <div
        ref={containerRef}
        className="acc-pdf-viewport"
        data-testid="pdf-viewport"
        style={{ touchAction: ingezoomd ? 'none' : 'pan-y pinch-zoom' }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        <div
          ref={inhoudRef}
          className="acc-pdf-inhoud"
          style={{
            transform: `translate(${zoom.x}px, ${zoom.y}px) scale(${zoom.schaal})`,
            transformOrigin: '0 0',
          }}
        />
      </div>
      {fullscreen && !volledigScherm && (
        <div className="acc-pdf-fullscreen" role="dialog" aria-label="Factuur op volledig scherm" data-testid="pdf-fullscreen">
          <div className="acc-pdf-fullscreen-balk">
            <span>Knijp om in te zoomen · dubbeltik = 2× · sleep om te schuiven</span>
            <button type="button" className="acc-btn klein secundair" onClick={() => setFullscreen(false)} aria-label="Volledig scherm sluiten">
              ✕ Sluiten
            </button>
          </div>
          <PdfWeergave blobUrl={blobUrl} laden={laden} fout={fout} actief onOpnieuw={onOpnieuw} volledigScherm />
        </div>
      )}
    </div>
  )
}
