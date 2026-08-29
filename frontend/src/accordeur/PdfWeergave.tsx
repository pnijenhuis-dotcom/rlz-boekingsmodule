// Inline-PDF-weergave voor de accordeur-PWA. pdfjs-dist rendert álle pagina's als canvas —
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

import { useEffect, useRef, useState } from 'react'

interface Props {
  blobUrl: string | null
  laden: boolean
  fout: string | null
  /** Zichtbaar gemonteerd? Verborgen (prefetch) = alleen parsen, niet tekenen. */
  actief?: boolean
  onOpnieuw?: () => void
}

export const RENDER_TIJDSLIMIET_MS = 20_000

type RenderStand = 'wacht' | 'bezig' | 'klaar' | 'fout'

export function PdfWeergave({ blobUrl, laden, fout, actief = true, onOpnieuw }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [stand, setStand] = useState<RenderStand>('wacht')
  const [renderFout, setRenderFout] = useState<string | null>(null)
  const [poging, setPoging] = useState(0)
  const [breedte, setBreedte] = useState(0)

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
      const container = containerRef.current
      if (!container || geannuleerd) return
      container.replaceChildren()
      // Renderscherpte: containerbreedte × devicePixelRatio — knijpzoomen blijft leesbaar
      // zonder dat we een eigen zoom-laag bouwen (native paginazoom blijft gewoon werken).
      // Breedte 0 (nog niet gelay-out) → vensterbreedte, nooit een negatieve schaal.
      const beschikbaar = (container.clientWidth || breedte || window.innerWidth) - 8
      const doelBreedte = Math.max(beschikbaar, 200)
      const dpr = Math.min(window.devicePixelRatio || 1, 3)
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
        container.appendChild(canvas)
        await pagina.render({ canvasContext: ctx, viewport, canvas }).promise
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

  const foutTekst = fout ?? renderFout
  const toonLaden = !foutTekst && (laden || stand === 'bezig' || (blobUrl !== null && stand === 'wacht'))
  const opnieuw = () => {
    setRenderFout(null)
    setStand('wacht')
    setPoging((p) => p + 1)
    onOpnieuw?.()
  }

  return (
    <div className="acc-docpane" data-stand={foutTekst ? 'fout' : toonLaden ? 'laden' : stand}>
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
      <div ref={containerRef} style={{ width: '100%' }} />
    </div>
  )
}
