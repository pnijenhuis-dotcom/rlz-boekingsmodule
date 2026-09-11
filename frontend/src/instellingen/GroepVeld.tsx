import { useState } from 'react'
import { ApiError } from '../api/client'
import type { GroepDto } from '../api/types'
import { Button, Select } from '../ui/basis'
import { codeGeldig, codeVoorstel, groepLabel } from './groepen'
import { maakGroepAan } from './instellingenApi'

/** Veld "Groep" (blok 8 run 11-09): keuzelijst van actieve groepen + "— geen groep —" + "Nieuwe groep…" die inline
 * een naam + code-voorstel (afgeleid uit de naam, bewerkbaar) opent en via POST /groepen aanmaakt (Beheerder-only).
 * Twee afnemers: `GroepRij` (detailpagina, slaat direct op) en de wizard (state, gaat mee in het aanmaken).
 * Leeg = geen groep — nooit een blokkade. Een huidige gearchiveerde groep blijft zichtbaar als "(gearchiveerd)". */

export const NIEUWE_GROEP = '__nieuw__'

export function GroepVeld({
  waarde,
  groepen,
  onWijzig,
  onGroepAangemaakt,
  ariaLabel,
  uitgeschakeld = false,
  kanAanmaken = true,
}: {
  waarde: string | null
  groepen: GroepDto[]
  onWijzig: (groepId: string | null) => void
  onGroepAangemaakt?: (g: GroepDto) => void
  ariaLabel: string
  uitgeschakeld?: boolean
  kanAanmaken?: boolean
}) {
  const [nieuw, setNieuw] = useState(false)
  const [naam, setNaam] = useState('')
  const [code, setCode] = useState('')
  const [codeHandmatig, setCodeHandmatig] = useState(false)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const kiesbaar = groepen.filter((g) => g.actief || g.id === waarde)

  const sluitNieuw = () => {
    setNieuw(false)
    setNaam('')
    setCode('')
    setCodeHandmatig(false)
    setFout(null)
  }

  const aanmaken = async () => {
    const schoon = naam.trim()
    if (!schoon) {
      setFout('Geef de groep een naam.')
      return
    }
    if (!codeGeldig(code)) {
      setFout('Code: 2–12 tekens, alleen hoofdletters en cijfers (bv. KEMPEN).')
      return
    }
    setBezig(true)
    setFout(null)
    try {
      const g = await maakGroepAan(schoon, code)
      onGroepAangemaakt?.(g)
      onWijzig(g.id)
      sluitNieuw()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Aanmaken mislukt — probeer het opnieuw.')
    } finally {
      setBezig(false)
    }
  }

  if (nieuw) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }} data-testid="nieuwe-groep">
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
          <input
            aria-label="Naam nieuwe groep"
            placeholder="Naam, bv. Kempen groep"
            value={naam}
            autoFocus
            disabled={bezig}
            style={{ width: 200 }}
            onChange={(e) => {
              setNaam(e.target.value)
              if (!codeHandmatig) setCode(codeVoorstel(e.target.value))
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                void aanmaken()
              }
              if (e.key === 'Escape') sluitNieuw()
            }}
          />
          <input
            aria-label="Code nieuwe groep"
            placeholder="CODE"
            value={code}
            disabled={bezig}
            maxLength={12}
            style={{ width: 120, textTransform: 'uppercase' }}
            onChange={(e) => {
              setCodeHandmatig(true)
              setCode(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ''))
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                void aanmaken()
              }
              if (e.key === 'Escape') sluitNieuw()
            }}
          />
          <Button type="button" maat="klein" disabled={bezig || !naam.trim() || !codeGeldig(code)} onClick={() => void aanmaken()}>
            {bezig ? 'Bezig…' : 'Groep aanmaken'}
          </Button>
          <button type="button" className="linkbtn" onClick={sluitNieuw} disabled={bezig}>
            annuleren
          </button>
        </div>
        <span className="hint" style={{ margin: 0, fontSize: 11.5 }}>
          De code is kort en uniek (hoofdletters/cijfers) — voorgesteld uit de naam, aan te passen. Een groep wordt nooit
          verwijderd, alleen gearchiveerd.
        </span>
        {fout && (
          <span className="text-[12px] text-red" role="alert">
            {fout}
          </span>
        )}
      </div>
    )
  }

  return (
    <Select
      aria-label={ariaLabel}
      value={waarde ?? ''}
      disabled={uitgeschakeld}
      style={{ maxWidth: 260 }}
      onChange={(e) => {
        const v = e.target.value
        if (v === NIEUWE_GROEP) {
          setNieuw(true)
          return
        }
        onWijzig(v || null)
      }}
    >
      <option value="">— geen groep —</option>
      {kiesbaar.map((g) => (
        <option key={g.id} value={g.id}>
          {groepLabel(g)}
        </option>
      ))}
      {kanAanmaken && <option value={NIEUWE_GROEP}>+ Nieuwe groep…</option>}
    </Select>
  )
}
