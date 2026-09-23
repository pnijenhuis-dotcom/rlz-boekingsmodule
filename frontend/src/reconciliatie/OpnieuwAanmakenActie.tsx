// "Opnieuw aanmaken" op de activa-bevinding `activum_aanmaken_mislukt_mens` (BUG 24-09, casus BLOw 23-09: een medewerker
// koos twee keer "Aanmaken ná boeken", de module weigerde ná het boeken op "geen afschrijvingsrekening" en de soort stond
// in `meten` — niemand zag het). Een bevestigde mens-handeling die niet is uitgevoerd is een actie-bevinding (kernprincipe
// 4 + 7(6)); de handeling op de rij is exact de bestaande kaart-route `POST …/activa-voorstel/{regel}/aanmaken` zonder body:
// de server neemt de voorgevulde afschrijvingsrekening (koppeling > instelling > conventie code + 1). Antwoordt de server
// 422 "Kies een afschrijvingsrekening …" (geen voorvulling mogelijk), dan staat die zin op de rij en wijst de deeplink naar
// het controlescherm waar de mens de rekening kiest. Ook `activum_aanmaken_mislukt` (herkomst automatisch, in meting)
// krijgt de knop — de handeling is dezelfde. Teal = actie.
import { useState } from 'react'
import { activumAanmaken } from '../activa/activaApi'
import { ApiError } from '../api/client'
import { Button } from '../ui/basis'
import type { BevindingDto } from './reconciliatieApi'

export const ACTIVUM_MISLUKT_SOORTEN = ['activum_aanmaken_mislukt_mens', 'activum_aanmaken_mislukt'] as const

/** Is dit de rij waarop de actie hoort? Eén regel in `actieVoor`. */
export function isActivumAanmakenMislukt(r: BevindingDto): boolean {
  const soort = r.detail?.afwijking_soort
  return (
    r.blok === 'activa' &&
    typeof soort === 'string' &&
    (ACTIVUM_MISLUKT_SOORTEN as readonly string[]).includes(soort) &&
    typeof r.detail?.document_id === 'string' &&
    typeof r.detail?.regel_volgnummer === 'number' &&
    r.administratie_id !== null
  )
}

export function OpnieuwAanmakenActie({
  bevinding,
  onGelukt,
}: {
  bevinding: BevindingDto
  onGelukt: (melding: string, soort: 'ok' | 'warn') => void
}) {
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [klaar, setKlaar] = useState<string | null>(null)
  const documentId = String(bevinding.detail?.document_id ?? '')
  const regel = Number(bevinding.detail?.regel_volgnummer)
  const kan = bevinding.administratie_id !== null && documentId !== '' && Number.isInteger(regel)

  const uitvoeren = async () => {
    if (!kan || bevinding.administratie_id === null) return
    setBezig(true)
    setFout(null)
    try {
      const v = await activumAanmaken(bevinding.administratie_id, documentId, regel, {})
      const kop = v.kandidaten.find((k) => k.regel_volgnummer === regel)?.koppeling ?? null
      if (kop?.status === 'aangemaakt') {
        const tekst = `Activum aangemaakt in Reeleezee${kop.rlz_receipt_number ? ` (nr ${kop.rlz_receipt_number})` : ''}.`
        setKlaar(tekst)
        onGelukt(tekst, 'ok')
      } else if (kop?.status === 'mislukt') {
        // Niets verdwijnt stil: de server legde de nieuwe reden vast; de rij blijft tot de volgende run.
        setFout(`Opnieuw geprobeerd — nog niet gelukt: ${kop.reden ?? 'onbekende reden'}`)
      } else {
        const tekst = 'Activum gepland — wordt aangemaakt zodra de boeking staat.'
        setKlaar(tekst)
        onGelukt(tekst, 'ok')
      }
    } catch (err) {
      // 422 = geen afschrijvingsrekening bekend (de zin van de server), 409 = intussen al aangemaakt.
      setFout(err instanceof ApiError ? err.message : 'Opnieuw aanmaken mislukt.')
    } finally {
      setBezig(false)
    }
  }

  if (klaar) {
    return <span className="hint">{klaar}</span>
  }
  return (
    <>
      <Button
        variant="primair"
        maat="klein"
        onClick={() => void uitvoeren()}
        disabled={!kan || bezig}
        aria-label={`Activum opnieuw aanmaken (${bevinding.administratie_naam ?? 'deze administratie'})`}
      >
        {bezig ? 'Bezig…' : 'Opnieuw aanmaken'}
      </Button>
      {fout && (
        <>
          {' '}
          <span className="hint" role="alert" style={{ color: 'var(--red)' }}>
            {fout}
          </span>
        </>
      )}
    </>
  )
}
