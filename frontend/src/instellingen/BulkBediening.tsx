import { useState } from 'react'
import { ApiError } from '../api/client'
import type { AdministratieInstellingenDto } from '../api/types'
import { Button, Select, useToastOptioneel } from '../ui/basis'
import { useMedewerkers } from '../vragen/useMedewerkers'
import { BevestigDialog } from './BevestigDialog'
import { zetAiExtractieInstelling, zetBoekenInstelling, zetEigenaar } from './instellingenApi'

/* Bulkbediening administraties (fase 3 modernisering 15-08, mockup #scherm-instellingen):
 * rijselectie + bulkbalk. Bewust client-side over de bestaande per-administratie-endpoints —
 * élke wijziging loopt dus door dezelfde server-side checks en audit als een losse wijziging;
 * één bevestigingsdialoog per bulkactie, fouten per administratie zichtbaar (niets stil). */

type BulkActie =
  | { soort: 'boeken'; ingeschakeld: boolean }
  | { soort: 'ai_extractie'; ingeschakeld: boolean }
  | { soort: 'eigenaar'; eigenaarId: string | null; eigenaarNaam: string }

function actieLabel(actie: BulkActie): string {
  if (actie.soort === 'boeken') return `Boeken ${actie.ingeschakeld ? 'AAN' : 'UIT'}`
  if (actie.soort === 'ai_extractie') return `AI-extractie ${actie.ingeschakeld ? 'AAN' : 'UIT'}`
  return actie.eigenaarId ? `Eigenaar → ${actie.eigenaarNaam}` : 'Eigenaar verwijderen'
}

export function BulkBediening({
  administraties,
  geselecteerd,
  onWisSelectie,
  onGereed,
}: {
  administraties: AdministratieInstellingenDto[]
  geselecteerd: string[]
  onWisSelectie: () => void
  onGereed: () => void
}) {
  const { meld } = useToastOptioneel()
  const [actie, setActie] = useState<BulkActie | null>(null)
  const [eigenaarKiezen, setEigenaarKiezen] = useState(false)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [deelFouten, setDeelFouten] = useState<string[]>([])

  // Eigenaar-kandidaten: medewerkers met scope op de éérste geselecteerde administratie; per
  // administratie controleert de backend de scope opnieuw — een niet-gescoopte medewerker
  // faalt daar zichtbaar per rij.
  const eersteId = geselecteerd[0] ?? null
  const { medewerkers } = useMedewerkers(eigenaarKiezen ? eersteId : null)

  const gekozen = administraties.filter((a) => geselecteerd.includes(a.id))
  if (geselecteerd.length === 0 && deelFouten.length === 0) return null

  async function voerUit() {
    if (!actie) return
    setBezig(true)
    setFout(null)
    const fouten: string[] = []
    let gelukt = 0
    for (const a of gekozen) {
      try {
        if (actie.soort === 'boeken') await zetBoekenInstelling(a.id, actie.ingeschakeld)
        else if (actie.soort === 'ai_extractie') await zetAiExtractieInstelling(a.id, actie.ingeschakeld)
        else await zetEigenaar(a.id, actie.eigenaarId)
        gelukt += 1
      } catch (err) {
        fouten.push(`${a.naam}: ${err instanceof ApiError ? err.message : 'wijzigen mislukt'}`)
      }
    }
    setBezig(false)
    setActie(null)
    setDeelFouten(fouten)
    if (gelukt > 0) {
      meld(
        `${actieLabel(actie)} toegepast op ${gelukt} ${gelukt === 1 ? 'administratie' : 'administraties'} — geauditeerd.`,
        fouten.length > 0 ? 'warn' : 'ok',
      )
    }
    onWisSelectie()
    onGereed()
  }

  return (
    <>
      {geselecteerd.length > 0 && (
        <div
          className="mb-3 flex flex-wrap items-center gap-3 rounded-[9px] border border-border bg-accent-bg px-4 py-[10px] text-[13px]"
          role="toolbar"
          aria-label="Bulk-bediening"
        >
          <b className="text-primary">{geselecteerd.length} geselecteerd</b>
          <div className="flex flex-wrap gap-2">
            <Button maat="klein" onClick={() => setActie({ soort: 'boeken', ingeschakeld: true })}>
              Boeken aan
            </Button>
            <Button variant="secundair" maat="klein" onClick={() => setActie({ soort: 'boeken', ingeschakeld: false })}>
              Boeken uit
            </Button>
            <Button
              variant="secundair"
              maat="klein"
              onClick={() => setActie({ soort: 'ai_extractie', ingeschakeld: true })}
            >
              AI aan
            </Button>
            <Button
              variant="secundair"
              maat="klein"
              onClick={() => setActie({ soort: 'ai_extractie', ingeschakeld: false })}
            >
              AI uit
            </Button>
            <Button variant="secundair" maat="klein" onClick={() => setEigenaarKiezen(true)}>
              Eigenaar toewijzen…
            </Button>
          </div>
          <Button variant="ghost" maat="klein" className="ml-auto" onClick={onWisSelectie}>
            ✕ selectie wissen
          </Button>
        </div>
      )}

      {deelFouten.length > 0 && (
        <div className="fout">
          Niet alles gelukt — deze administraties zijn ongewijzigd:
          <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
            {deelFouten.map((regel) => (
              <li key={regel}>{regel}</li>
            ))}
          </ul>
          <button type="button" className="linkbtn" onClick={() => setDeelFouten([])}>
            melding sluiten
          </button>
        </div>
      )}

      {eigenaarKiezen && (
        <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && setEigenaarKiezen(false)}>
          <div className="modal" role="dialog" aria-modal="true">
            <h2>Eigenaar toewijzen ({geselecteerd.length} administraties)</h2>
            <p className="hint" style={{ marginTop: 0 }}>
              De eigenaar krijgt de vragen van deze administraties. Kandidaten = medewerkers met scope op de
              eerste geselecteerde administratie; per administratie controleert de server de scope opnieuw.
            </p>
            <Select
              aria-label="Eigenaar voor geselecteerde administraties"
              className="w-full"
              defaultValue=""
              onChange={(e) => {
                const id = e.target.value || null
                const naam = medewerkers?.find((m) => m.id === id)?.naam ?? '—'
                setEigenaarKiezen(false)
                setActie({ soort: 'eigenaar', eigenaarId: id, eigenaarNaam: naam })
              }}
            >
              <option value="" disabled>
                — kies een medewerker —
              </option>
              {(medewerkers ?? []).map((m) => (
                <option key={m.id} value={m.id}>
                  {m.naam}
                </option>
              ))}
            </Select>
            <div className="actions">
              <button type="button" className="btn secondary" onClick={() => setEigenaarKiezen(false)}>
                Annuleren
              </button>
            </div>
          </div>
        </div>
      )}

      {actie && (
        <BevestigDialog
          titel={`Bulkactie: ${actieLabel(actie)}`}
          bericht={`"${actieLabel(actie)}" wordt toegepast op ${gekozen.length} ${gekozen.length === 1 ? 'administratie' : 'administraties'} (${gekozen
            .map((a) => a.naam)
            .join(', ')}). Elke wijziging loopt door de normale server-side checks en wordt geauditeerd.`}
          bezig={bezig}
          fout={fout}
          onBevestigen={() => void voerUit()}
          onAnnuleren={() => {
            setActie(null)
            setFout(null)
          }}
        />
      )}
    </>
  )
}
