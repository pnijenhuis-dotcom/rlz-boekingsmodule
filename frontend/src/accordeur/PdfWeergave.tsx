// Inline-PDF-weergave voor de accordeur-PWA. pdfjs-dist rendert álle pagina's als canvas —
// een <object>/<iframe> toont op iOS Safari alleen de eerste pagina (bekende beperking), en
// het factuurbeeld is hier juist het centrale element (mockup). De bibliotheek wordt LAZY
// geïmporteerd (performance-budget: pdf.js zit niet in de startbundle, laadt pas bij de
// eerste factuur die opent).

import { useEffect, useRef, useState } from 'react'

interface Props {
  blobUrl: string | null
  laden: boolean
  fout: string | null
}

export function PdfWeergave({ blobUrl, laden, fout }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [renderFout, setRenderFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)

  useEffect(() => {
    if (!blobUrl) return
    let geannuleerd = false
    setRenderFout(null)
    setBezig(true)

    const render = async () => {
      const pdfjs = await import('pdfjs-dist')
      const workerModule = await import('pdfjs-dist/build/pdf.worker.min.mjs?url')
      pdfjs.GlobalWorkerOptions.workerSrc = workerModule.default
      const document_ = await pdfjs.getDocument({ url: blobUrl }).promise
      const container = containerRef.current
      if (!container || geannuleerd) return
      container.replaceChildren()
      // Renderscherpte: containerbreedte × devicePixelRatio — knijpzoomen blijft leesbaar
      // zonder dat we een eigen zoom-laag bouwen (native paginazoom blijft gewoon werken).
      const breedte = container.clientWidth - 8
      const dpr = Math.min(window.devicePixelRatio || 1, 3)
      for (let n = 1; n <= document_.numPages; n++) {
        if (geannuleerd) return
        const pagina = await document_.getPage(n)
        const basis = pagina.getViewport({ scale: 1 })
        const schaal = (breedte / basis.width) * dpr
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
      .catch(() => {
        if (!geannuleerd) setRenderFout('Het factuurbeeld kon niet weergegeven worden.')
      })
      .finally(() => {
        if (!geannuleerd) setBezig(false)
      })
    return () => {
      geannuleerd = true
    }
  }, [blobUrl])

  return (
    <div className="acc-docpane">
      {(laden || bezig) && !fout && <div className="acc-doc-status">Factuurbeeld laden…</div>}
      {(fout ?? renderFout) && <div className="acc-doc-status">{fout ?? renderFout}</div>}
      <div ref={containerRef} style={{ width: '100%' }} />
    </div>
  )
}
