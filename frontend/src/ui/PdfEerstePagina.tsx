import { useEffect, useRef, useState } from 'react'

interface Props {
  blobUrl: string
  /** Gewenste weergavebreedte in CSS-pixels. */
  breedte: number
}

/** Alleen de EERSTE pagina van een PDF als canvas (pdf.js, lazy geïmporteerd — niet in de
 * startbundel). Gebruikt door de verzamelbak-preview (besluit Peter 25-08, D1: bij hover zien
 * voor wie een document is). Renderfout = zichtbare tekst, nooit een lege popup. */
export function PdfEerstePagina({ blobUrl, breedte }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(true)

  useEffect(() => {
    let geannuleerd = false
    setFout(null)
    setBezig(true)
    const render = async () => {
      const pdfjs = await import('pdfjs-dist')
      const workerModule = await import('pdfjs-dist/build/pdf.worker.min.mjs?url')
      pdfjs.GlobalWorkerOptions.workerSrc = workerModule.default
      const document_ = await pdfjs.getDocument({ url: blobUrl }).promise
      if (geannuleerd) return
      const pagina = await document_.getPage(1)
      const canvas = canvasRef.current
      if (!canvas || geannuleerd) return
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      const basis = pagina.getViewport({ scale: 1 })
      const viewport = pagina.getViewport({ scale: (breedte / basis.width) * dpr })
      canvas.width = viewport.width
      canvas.height = viewport.height
      canvas.style.width = `${breedte}px`
      const ctx = canvas.getContext('2d')
      if (!ctx) return
      await pagina.render({ canvasContext: ctx, viewport, canvas }).promise
    }
    render()
      .catch(() => {
        if (!geannuleerd) setFout('Voorbeeld niet weer te geven.')
      })
      .finally(() => {
        if (!geannuleerd) setBezig(false)
      })
    return () => {
      geannuleerd = true
    }
  }, [blobUrl, breedte])

  return (
    <div style={{ width: breedte }}>
      {bezig && !fout && <div className="hint">Voorbeeld laden…</div>}
      {fout && <div className="hint">{fout}</div>}
      <canvas ref={canvasRef} style={{ display: fout ? 'none' : 'block', maxWidth: '100%' }} />
    </div>
  )
}
