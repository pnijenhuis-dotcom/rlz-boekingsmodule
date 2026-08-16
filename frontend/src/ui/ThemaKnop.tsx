import { useEffect, useState } from 'react'
import { bewaarThema, huidigThema, pasThemaToe, type Thema } from './thema'

/* Licht/donker-toggle (topbar) — keuze wint, anders systeem (thema.ts). */
export function ThemaKnop() {
  const [thema, setThema] = useState<Thema>(() => huidigThema())

  // Hersynchroniseer ná mount: initThema() kan pas in een later effect draaien dan de eerste
  // render van deze knop (kliktest 2026-08-16: bij systeem-donker zónder opgeslagen keuze
  // dacht de knop "licht" terwijl de pagina donker was — de eerste klik deed dan zichtbaar
  // niets). De wissel leest bovendien de LIVE DOM-stand, nooit de mogelijk verouderde state.
  useEffect(() => {
    setThema(huidigThema())
  }, [])

  function wissel() {
    const nieuw: Thema = huidigThema() === 'donker' ? 'licht' : 'donker'
    pasThemaToe(nieuw)
    bewaarThema(nieuw)
    setThema(nieuw)
  }

  return (
    <button
      type="button"
      className="shell-iconknop"
      title={thema === 'donker' ? 'Naar licht thema' : 'Naar donker thema'}
      aria-label="Thema wisselen"
      onClick={wissel}
    >
      ◐
    </button>
  )
}
