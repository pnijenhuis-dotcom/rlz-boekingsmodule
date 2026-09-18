/** Instellingen › administratie › Uren & materiaal: omschrijving-chips van de veld-app (run A punt 3, Peter 18-09).
 * Default opbouwen · afbreken · ombouwen · transport · overig; 1–10 chips, ≤ 30 tekens, uniek; opslag als tekst (geen enum).
 * "overig" hoeft er niet in — de app biedt dan zelf het vrije tekstveld. Beheerder-only (server), audit oud→nieuw. */
import { useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import { Badge, Button } from '../ui/basis'
import { haalOmschrijvingChipsBeheer, zetOmschrijvingChipsBeheer } from '../meerwerk/meerwerkApi'
import { InstellingRij } from './AdministratieDetailPagina'

export const STANDAARD_CHIPS = ['opbouwen', 'afbreken', 'ombouwen', 'transport', 'overig']

/** Pure validatie (spiegel van de server): 1–10, gestript, niet leeg, ≤ 30 tekens, uniek zonder hoofdletterverschil. */
export function valideerChips(chips: string[]): string | null {
  const schoon = chips.map((c) => c.trim()).filter(Boolean)
  if (schoon.length === 0) return 'Minstens één chip.'
  if (schoon.length > 10) return 'Hoogstens tien chips.'
  if (schoon.some((c) => c.length > 30)) return 'Een chip is hoogstens 30 tekens.'
  const lager = schoon.map((c) => c.toLowerCase())
  if (new Set(lager).size !== lager.length) return 'Chips moeten uniek zijn.'
  return null
}

export function OmschrijvingChipsRij({ administratieId, administratieNaam }: { administratieId: string; administratieNaam: string }) {
  const [chips, setChips] = useState<string[] | null>(null)
  const [nieuw, setNieuw] = useState('')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [gewijzigd, setGewijzigd] = useState(false)

  useEffect(() => {
    haalOmschrijvingChipsBeheer(administratieId)
      .then((d) => setChips(d.chips.length > 0 ? d.chips : STANDAARD_CHIPS))
      .catch((err: unknown) => setFout(err instanceof ApiError ? err.message : 'Chips konden niet geladen worden.'))
  }, [administratieId])

  const huidig = chips ?? []
  const validatie = valideerChips(huidig)

  async function opslaan() {
    if (validatie) return
    setBezig(true)
    setFout(null)
    try {
      const d = await zetOmschrijvingChipsBeheer(administratieId, huidig.map((c) => c.trim()))
      setChips(d.chips)
      setGewijzigd(false)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Opslaan mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <InstellingRij
      titel="Omschrijving-chips (veld-app)"
      uitleg='Wat een veldwerker kiest bij "Wat heb je gedaan?" — tikken i.p.v. typen. "overig" opent een vrij tekstveld. 1–10 chips, opslag als tekst.'
    >
      <div data-testid="omschrijving-chips" style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 260 }}>
        <div className="chips-regel" style={{ gap: 6, flexWrap: 'wrap' }}>
          {chips === null && !fout && <span className="hint">Laden…</span>}
          {huidig.map((c) => (
            <Badge key={c} variant="stil">
              {c}{' '}
              <button
                type="button"
                className="linkbtn"
                aria-label={`Verwijder chip ${c}`}
                style={{ padding: '0 2px' }}
                onClick={() => {
                  setChips(huidig.filter((x) => x !== c))
                  setGewijzigd(true)
                }}
              >
                ×
              </button>
            </Badge>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <input
            type="text"
            maxLength={30}
            placeholder="nieuwe chip…"
            aria-label={`Nieuwe chip voor ${administratieNaam}`}
            value={nieuw}
            style={{ width: 160, padding: '2px 6px' }}
            onChange={(e) => setNieuw(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && nieuw.trim()) {
                setChips([...huidig, nieuw.trim()])
                setNieuw('')
                setGewijzigd(true)
              }
            }}
          />
          <Button
            variant="secundair"
            maat="klein"
            disabled={!nieuw.trim()}
            onClick={() => {
              setChips([...huidig, nieuw.trim()])
              setNieuw('')
              setGewijzigd(true)
            }}
          >
            + Toevoegen
          </Button>
          <Button maat="klein" disabled={!gewijzigd || bezig || validatie !== null} onClick={() => void opslaan()}>
            {bezig ? 'Bezig…' : 'Opslaan'}
          </Button>
        </div>
        {validatie && gewijzigd && <span className="fout">{validatie}</span>}
        {fout && <span className="fout">{fout}</span>}
      </div>
    </InstellingRij>
  )
}
