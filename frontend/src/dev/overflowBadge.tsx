// Gedeelde overflow-meter voor de visuele harnassen (dev-gereedschap): rode/groene badge
// linksonder die horizontale overflow meet en de diepste boosdoeners benoemt. Geëxtraheerd uit
// visueelHarnas.tsx (responsive-fix werkvoorraad 2026-08-15) zodat élk harnas dezelfde meting
// gebruikt i.p.v. een kopie.
import { useEffect, useState } from 'react'

// Vóór de harnas-mocks geïnstalleerd worden gebonden — het ?rapporteer-kanaal moet altijd de
// échte fetch gebruiken, ook als het harnas window.fetch later vervangt.
const echteFetch = window.fetch.bind(window)

/** Elementen bínnen een horizontale scroll-container (bv. .tabel-scroll) kunnen de pagina niet
 * verbreden — die horen niet in de boosdoener-lijst (false positives, responsive-fix
 * 2026-08-15). */
function binnenScrollContainer(el: Element): boolean {
  for (let ouder = el.parentElement; ouder && ouder !== document.body; ouder = ouder.parentElement) {
    const overflowX = getComputedStyle(ouder).overflowX
    if (overflowX === 'auto' || overflowX === 'scroll' || overflowX === 'hidden') return true
  }
  return false
}

/** Korte, leesbare beschrijving van een element voor de boosdoener-lijst. */
function beschrijfElement(el: Element): string {
  const tag = el.tagName.toLowerCase()
  const klassen = typeof el.className === 'string' && el.className ? `.${el.className.trim().split(/\s+/).join('.')}` : ''
  const rect = el.getBoundingClientRect()
  return `${tag}${klassen} [${Math.round(rect.left)}..${Math.round(rect.right)}]`
}

/** Rode/groene badge linksonder: is de pagina breder dan de viewport (horizontale clipping)?
 * Bij overflow somt de badge de diepste boosdoeners op — elementen die rechts buiten de viewport
 * steken zónder kinderen die dat ook doen (de bladeren van de overflow-boom), zodat headless
 * Chrome (--dump-dom) de oorzaak direct benoemt in plaats van alleen "OVERFLOW". */
export function OverflowBadge() {
  const [meting, setMeting] = useState('')
  const [overflow, setOverflow] = useState(false)
  const [boosdoeners, setBoosdoeners] = useState<string[]>([])
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const meet = () => {
      const scrollBreedte = document.documentElement.scrollWidth
      const viewport = window.innerWidth
      setOverflow(scrollBreedte > viewport)
      setMeting(`scrollWidth ${scrollBreedte} / viewport ${viewport}`)
      if (scrollBreedte <= viewport) {
        setBoosdoeners([])
        return
      }
      const uitstekend = Array.from(document.querySelectorAll('body *')).filter((el) => {
        if (el.closest('[data-harnas-badge]')) return false
        if (binnenScrollContainer(el)) return false
        return el.getBoundingClientRect().right > viewport + 1
      })
      const bladeren = uitstekend.filter((el) => !uitstekend.some((ander) => ander !== el && el.contains(ander)))
      setBoosdoeners(bladeren.slice(0, 8).map(beschrijfElement))
    }
    // ?rapporteer=<poort>: post de meting naar een lokaal meetscript — voor browsers waar we
    // niet in kunnen kijken (Safari zonder 'Allow JavaScript from Apple Events').
    const rapporteerPoort = params.get('rapporteer')
    const rapporteer = () => {
      if (!rapporteerPoort) return
      const viewport = window.innerWidth
      const uitstekend = Array.from(document.querySelectorAll('body *')).filter((el) => {
        if (el.closest('[data-harnas-badge]')) return false
        if (binnenScrollContainer(el)) return false
        const r = el.getBoundingClientRect()
        return r.right > viewport + 1 && r.width > 0
      })
      const bladeren = uitstekend.filter((el) => !uitstekend.some((a) => a !== el && el.contains(a)))
      void echteFetch(`http://localhost:${rapporteerPoort}/meting`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ua: navigator.userAgent.slice(0, 80),
          viewport,
          scrollBreedte: document.documentElement.scrollWidth,
          boosdoeners: bladeren.slice(0, 10).map(beschrijfElement),
        }),
      }).catch(() => undefined)
    }
    const rapporteerTimer = setInterval(rapporteer, 1500)
    meet()
    const timer = setInterval(meet, 500)
    window.addEventListener('resize', meet)
    return () => {
      clearInterval(timer)
      clearInterval(rapporteerTimer)
      window.removeEventListener('resize', meet)
    }
  }, [])
  return (
    <div
      data-harnas-badge
      style={{
        position: 'fixed',
        left: 8,
        bottom: 8,
        zIndex: 999,
        padding: '4px 10px',
        borderRadius: 6,
        fontSize: 12,
        fontWeight: 700,
        color: '#fff',
        background: overflow ? '#b42318' : '#1c7a54',
        maxWidth: '90vw',
      }}
    >
      {overflow ? 'OVERFLOW' : 'past'} — {meting}
      {boosdoeners.map((b) => (
        <div key={b} style={{ fontWeight: 400, fontSize: 11 }}>
          → {b}
        </div>
      ))}
    </div>
  )
}
