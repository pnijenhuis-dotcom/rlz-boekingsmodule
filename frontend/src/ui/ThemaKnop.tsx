import { useState } from 'react'
import { bewaarThema, huidigThema, pasThemaToe, type Thema } from './thema'

/* Licht/donker-toggle (topbar) — keuze wint, anders systeem (thema.ts). */
export function ThemaKnop() {
  const [thema, setThema] = useState<Thema>(() => huidigThema())

  function wissel() {
    const nieuw: Thema = thema === 'donker' ? 'licht' : 'donker'
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
