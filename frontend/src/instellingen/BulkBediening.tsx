import { useState } from 'react'
import { ApiError } from '../api/client'
import type { AdministratieInstellingenDto } from '../api/types'
import { Button, Select, useToastOptioneel } from '../ui/basis'
import { useMedewerkers } from '../vragen/useMedewerkers'
import { BevestigDialog } from './BevestigDialog'
import { BulkAccorderingDialog } from './BulkAccorderingDialog'
import { groepLabel, useGroepen } from './groepen'
import { GroepVeld } from './GroepVeld'
import {
  zetAdministratieGroep,
  zetAiExtractieInstelling,
  zetAutoboekenLeren,
  zetBoekenInstelling,
  zetEigenaar,
  zetGroepAdministratiesBulk,
} from './instellingenApi'

/* Bulkbediening administraties (fase 3 modernisering 15-08, mockup #scherm-instellingen):
 * rijselectie + bulkbalk. Bewust client-side over de bestaande per-administratie-endpoints —
 * élke wijziging loopt dus door dezelfde server-side checks en audit als een losse wijziging;
 * één bevestigingsdialoog per bulkactie, fouten per administratie zichtbaar (niets stil). */

type BulkActie =
  | { soort: 'boeken'; ingeschakeld: boolean }
  | { soort: 'ai_extractie'; ingeschakeld: boolean }
  | { soort: 'autoboeken_leren'; ingeschakeld: boolean }
  | { soort: 'eigenaar'; eigenaarId: string | null; eigenaarNaam: string }
  // Bulk-toewijzing groepen 16-09 (Peter: "nu moet ik 1 voor 1 doen"): groepId = één PUT /groepen/{id}/administraties
  // (één transactie, uitkomst per rij); null = "geen groep" via de bestaande per-administratie-route.
  | { soort: 'groep'; groepId: string | null; groepNaam: string }

function actieLabel(actie: BulkActie): string {
  if (actie.soort === 'boeken') return `Boeken ${actie.ingeschakeld ? 'AAN' : 'UIT'}`
  if (actie.soort === 'ai_extractie') return `AI-extractie ${actie.ingeschakeld ? 'AAN' : 'UIT'}`
  if (actie.soort === 'autoboeken_leren') return `Autoboeken (leren en boeken) ${actie.ingeschakeld ? 'AAN' : 'UIT'}`
  if (actie.soort === 'groep') return actie.groepId ? `Groep → ${actie.groepNaam}` : 'Uit hun groep halen'
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
  const [groepKiezen, setGroepKiezen] = useState(false)
  const [groepKeuze, setGroepKeuze] = useState<string | null>(null)
  // Groepen alleen laden zodra de kiezer opent (geen extra call voor wie nooit groepen gebruikt).
  const { groepen, zet: zetGroepLokaal } = useGroepen(true)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [deelFouten, setDeelFouten] = useState<string[]>([])
  // Bulk klant-accordering (mockup bulk-accordering.html, 01-09): de dialoog werkt op een
  // kopie van de selectie op het moment van openen — wissen van de selectie ná toepassen
  // laat de resultaatweergave intact.
  const [accorderingVoor, setAccorderingVoor] = useState<{ id: string; naam: string }[] | null>(null)

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
    if (actie.soort === 'groep' && actie.groepId) {
      // Eén transactie server-side; de uitkomst per rij komt terug (verhuisd / overgeslagen mét reden) — niets stil.
      try {
        const u = await zetGroepAdministratiesBulk(actie.groepId, { toevoegen: gekozen.map((a) => a.id), verwijderen: [] })
        gelukt = u.toegevoegd
        for (const r of u.rijen) if (r.uitkomst === 'overgeslagen') fouten.push(`${r.naam}: overgeslagen: ${r.detail ?? ''}`)
        const verhuisd = u.rijen.filter((r) => r.uitkomst === 'verhuisd')
        if (verhuisd.length > 0)
          meld(`${verhuisd.length} ${verhuisd.length === 1 ? 'administratie is' : 'administraties zijn'} verhuisd uit een andere groep.`, 'warn')
      } catch (err) {
        fouten.push(err instanceof ApiError ? err.message : 'toewijzen aan de groep mislukt')
      }
      setBezig(false)
      setActie(null)
      setDeelFouten(fouten)
      if (gelukt > 0) meld(`${actieLabel(actie)} toegepast op ${gelukt} ${gelukt === 1 ? 'administratie' : 'administraties'} — geauditeerd.`, fouten.length > 0 ? 'warn' : 'ok')
      onWisSelectie()
      onGereed()
      return
    }
    for (const a of gekozen) {
      try {
        if (actie.soort === 'boeken') await zetBoekenInstelling(a.id, actie.ingeschakeld)
        else if (actie.soort === 'ai_extractie') await zetAiExtractieInstelling(a.id, actie.ingeschakeld)
        else if (actie.soort === 'autoboeken_leren') await zetAutoboekenLeren(a.id, actie.ingeschakeld)
        else if (actie.soort === 'groep') await zetAdministratieGroep(a.id, null)
        else await zetEigenaar(a.id, actie.eigenaarId)
        gelukt += 1
      } catch (err) {
        // Autoboeken (leren en boeken), blok A 10-09: een 409 = de server weigert met uitleg (Kempen-regel "doorbelasting")
        // → per rij zichtbaar als "overgeslagen: ‹detail›", nooit stil (geen stille no-op). Andere acties: bestaande tekst.
        const overgeslagen = actie.soort === 'autoboeken_leren' && err instanceof ApiError && err.status === 409
        const tekst = err instanceof ApiError ? (overgeslagen ? `overgeslagen: ${err.message}` : err.message) : 'wijzigen mislukt'
        fouten.push(`${a.naam}: ${tekst}`)
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
            <Button variant="secundair" maat="klein" onClick={() => setActie({ soort: 'autoboeken_leren', ingeschakeld: true })}>
              Autoboeken aan
            </Button>
            <Button variant="secundair" maat="klein" onClick={() => setActie({ soort: 'autoboeken_leren', ingeschakeld: false })}>
              Autoboeken uit
            </Button>
            <Button variant="secundair" maat="klein" onClick={() => setEigenaarKiezen(true)}>
              Eigenaar toewijzen…
            </Button>
            <Button variant="secundair" maat="klein" onClick={() => setGroepKiezen(true)}>
              Toewijzen aan groep…
            </Button>
            <Button
              variant="secundair"
              maat="klein"
              onClick={() => setAccorderingVoor(gekozen.map((a) => ({ id: a.id, naam: a.naam })))}
            >
              Klant-accordering instellen…
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

      {groepKiezen && (
        <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && setGroepKiezen(false)}>
          <div className="modal" role="dialog" aria-modal="true" data-testid="bulk-groep-dialoog">
            <h2>Toewijzen aan groep ({geselecteerd.length} administraties)</h2>
            <p className="hint" style={{ marginTop: 0 }}>
              Een groep is een filter op de klantenlijst en Inzicht › Reconciliatie. Een administratie zit in hoogstens één
              groep: wie al in een andere groep zit, verhuist. &ldquo;— geen groep —&rdquo; haalt de selectie uit hun groep.
            </p>
            <GroepVeld
              ariaLabel="Groep voor geselecteerde administraties"
              waarde={groepKeuze}
              groepen={groepen ?? []}
              onWijzig={setGroepKeuze}
              onGroepAangemaakt={zetGroepLokaal}
            />
            <div className="actions">
              <button type="button" className="btn secondary" onClick={() => setGroepKiezen(false)}>
                Annuleren
              </button>
              <button
                type="button"
                className="btn"
                onClick={() => {
                  const g = (groepen ?? []).find((x) => x.id === groepKeuze)
                  setGroepKiezen(false)
                  setActie({ soort: 'groep', groepId: groepKeuze, groepNaam: g ? groepLabel(g) : '—' })
                }}
              >
                Verder
              </button>
            </div>
          </div>
        </div>
      )}

      {accorderingVoor && (
        <BulkAccorderingDialog
          administraties={accorderingVoor}
          onSluiten={() => setAccorderingVoor(null)}
          onGereed={() => {
            onWisSelectie()
            onGereed()
          }}
        />
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
