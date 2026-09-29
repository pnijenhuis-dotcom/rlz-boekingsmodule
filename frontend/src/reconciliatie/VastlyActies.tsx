// Handelingen op de drie bevindingen van blok `vastly_verkoop` (Peter 28/29-09: "deze huurfacturen horen daar sowieso
// niet in te staan … moet gewoon als omzet geboekt worden, punt"). Vastly-verkoopfacturen boeken automatisch; wat hier
// staat is precies wat het systeem NIET zelf kan beslissen, elk mét één knop op de rij:
// - `vastly_entiteit_niet_gekoppeld` (kantoorbreed): "Koppel aan administratie…" → registerrij + directe boeking van de
//   wachtende facturen (POST /reconciliatie/vastly/entiteit-koppelen);
// - `vastly_omzetrekening_ontbreekt` (per administratie): "Rekening kiezen" → PUT …/vastly-omzetrekeningen (Beheerder;
//   keuzelijst = de actieve omzetrekeningen 8xxx van de administratie);
// - `vastly_verkoop_niet_geboekt` (per document): "Opnieuw aanbieden" → hetzelfde autoboek-pad als bij intake.
// Signalering zonder handeling is niet af; een mislukte handeling is zichtbaar naast de knop, nooit stil.
import { useEffect, useState } from 'react'
import { ApiError, apiJson } from '../api/client'
import { useAuthOptioneel } from '../auth/AuthContext'
import { SearchableCombobox, type ComboboxOptie } from '../document/SearchableCombobox'
import { AdministratieCombobox } from '../ui/AdministratieCombobox'
import { Button } from '../ui/basis'
import { useAdministraties } from '../werkvoorraad/useAdministraties'
import type { BevindingDto } from './reconciliatieApi'

export function isVastlyEntiteitNietGekoppeld(r: BevindingDto): boolean {
  return (
    r.blok === 'vastly_verkoop' &&
    r.detail?.afwijking_soort === 'vastly_entiteit_niet_gekoppeld' &&
    typeof r.detail?.sleutel_soort === 'string' &&
    typeof r.detail?.sleutel === 'string'
  )
}

export function isVastlyOmzetrekeningOntbreekt(r: BevindingDto): boolean {
  return (
    r.blok === 'vastly_verkoop' &&
    r.detail?.afwijking_soort === 'vastly_omzetrekening_ontbreekt' &&
    typeof r.detail?.regelsoort === 'string' &&
    r.administratie_id !== null
  )
}

export function isVastlyVerkoopNietGeboekt(r: BevindingDto): boolean {
  return (
    r.blok === 'vastly_verkoop' &&
    r.detail?.afwijking_soort === 'vastly_verkoop_niet_geboekt' &&
    typeof r.detail?.document_id === 'string' &&
    r.administratie_id !== null
  )
}

export interface VastlyEntiteitKoppelenResultaatDto {
  sleutel_soort: string
  sleutel: string
  administratie_id: string
  administratie_naam: string
  documenten: number
  per_uitkomst: Record<string, number>
  doel_pad: string
}

export interface VastlyOmzetrekeningStandDto {
  regelsoort: string
  ledger_id: string | null
  code: string | null
  naam: string | null
  bron: 'historie' | 'mens' | null
}

export interface VastlyInstellingenDto {
  administratie_id: string
  omzetrekeningen: VastlyOmzetrekeningStandDto[]
  keuzelijst: { ledger_id: string; code: string; naam: string }[]
  entiteiten: { sleutel_soort: string; sleutel: string; weergave: string | null; bron: string }[]
}

export interface VastlyOpnieuwAanbiedenResultaatDto {
  document_id: string
  administratie_id: string
  uitkomst: 'geboekt' | 'geweigerd' | string
  reden: string | null
  doel_pad: string
}

export function koppelEntiteit(body: {
  sleutel_soort: string
  sleutel: string
  administratie_id: string
  weergave?: string | null
}): Promise<VastlyEntiteitKoppelenResultaatDto> {
  return apiJson('/reconciliatie/vastly/entiteit-koppelen', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function haalVastlyInstellingen(administratieId: string): Promise<VastlyInstellingenDto> {
  return apiJson(`/administraties/${administratieId}/vastly-instellingen`)
}

export function zetVastlyOmzetrekening(administratieId: string, regelsoort: string, ledgerId: string): Promise<VastlyOmzetrekeningStandDto> {
  return apiJson(`/administraties/${administratieId}/vastly-omzetrekeningen`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ regelsoort, ledger_id: ledgerId }),
  })
}

export function opnieuwAanbieden(documentId: string, administratieId: string): Promise<VastlyOpnieuwAanbiedenResultaatDto> {
  return apiJson(`/reconciliatie/vastly/documenten/${documentId}/opnieuw-aanbieden`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ administratie_id: administratieId }),
  })
}

export function koppelMelding(r: VastlyEntiteitKoppelenResultaatDto): string {
  const geboekt = r.per_uitkomst.geboekt ?? 0
  const rest = r.documenten - geboekt
  const kop = `Verhuurder gekoppeld aan ${r.administratie_naam}.`
  if (r.documenten === 0) return `${kop} Er wachtten geen facturen meer.`
  if (rest === 0) return `${kop} ${geboekt} factu${geboekt === 1 ? 'ur is' : 'ren zijn'} direct automatisch als omzet geboekt.`
  return `${kop} ${geboekt} van ${r.documenten} facturen direct geboekt; ${rest} wacht(en) nog — de reden staat bij de volgende reconciliatie-run op de rij.`
}

export function KoppelEntiteitActie({ bevinding, onGelukt }: { bevinding: BevindingDto; onGelukt: (melding: string) => void }) {
  const { administraties } = useAdministraties()
  const [keuze, setKeuze] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [klaar, setKlaar] = useState<VastlyEntiteitKoppelenResultaatDto | null>(null)
  const sleutelSoort = String(bevinding.detail?.sleutel_soort ?? '')
  const sleutel = String(bevinding.detail?.sleutel ?? '')
  const weergave = typeof bevinding.detail?.weergave === 'string' ? (bevinding.detail.weergave as string) : null

  const uitvoeren = async () => {
    if (!keuze || !sleutelSoort || !sleutel) return
    setBezig(true)
    setFout(null)
    try {
      const r = await koppelEntiteit({ sleutel_soort: sleutelSoort, sleutel, administratie_id: keuze, weergave })
      setKlaar(r)
      onGelukt(koppelMelding(r))
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Koppelen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  if (klaar) {
    return <span className="hint">gekoppeld aan {klaar.administratie_naam} — {klaar.per_uitkomst.geboekt ?? 0} geboekt</span>
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-2" style={{ minWidth: 0 }}>
      <span style={{ minWidth: 220 }}>
        <AdministratieCombobox
          label={`Administratie voor ${weergave ?? sleutel}`}
          toonLabel={false}
          administraties={administraties ?? []}
          waarde={keuze}
          onWijzig={setKeuze}
          placeholder="Koppel aan administratie…"
        />
      </span>
      <Button
        variant="primair"
        maat="klein"
        onClick={() => void uitvoeren()}
        disabled={!keuze || bezig}
        aria-label={`Koppel ${weergave ?? sleutel} aan de gekozen administratie`}
      >
        {bezig ? 'Bezig…' : 'Koppel aan administratie'}
      </Button>
      {fout && (
        <span className="hint" style={{ color: 'var(--red)' }}>
          {fout}
        </span>
      )}
    </span>
  )
}

export function RekeningKiezenActie({ bevinding, onGelukt }: { bevinding: BevindingDto; onGelukt: (melding: string) => void }) {
  const auth = useAuthOptioneel()
  const magZetten = auth === null || auth.rol === 'beheerder'
  const administratieId = bevinding.administratie_id
  const regelsoort = String(bevinding.detail?.regelsoort ?? 'overig')
  const [opties, setOpties] = useState<ComboboxOptie[] | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [keuze, setKeuze] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [klaar, setKlaar] = useState<VastlyOmzetrekeningStandDto | null>(null)

  useEffect(() => {
    if (!administratieId) return
    let actief = true
    haalVastlyInstellingen(administratieId)
      .then((d) => {
        if (actief) setOpties(d.keuzelijst.map((k) => ({ id: k.ledger_id, code: k.code, label: k.naam })))
      })
      .catch((err: unknown) => {
        if (actief) setLaadFout(err instanceof ApiError ? err.message : 'Keuzelijst niet beschikbaar.')
      })
    return () => {
      actief = false
    }
  }, [administratieId])

  const uitvoeren = async () => {
    if (!administratieId || !keuze) return
    setBezig(true)
    setFout(null)
    try {
      const r = await zetVastlyOmzetrekening(administratieId, regelsoort, keuze)
      setKlaar(r)
      onGelukt(`Omzetrekening voor ${regelsoort} gezet op ${r.code} ${r.naam ?? ''} — de wachtende facturen boeken bij de volgende heraanbieding automatisch.`)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Rekening zetten mislukt.')
    } finally {
      setBezig(false)
    }
  }

  if (klaar) {
    return (
      <span className="hint">
        {regelsoort} → {klaar.code} {klaar.naam}
      </span>
    )
  }
  if (!magZetten) {
    return <span className="hint">alleen een Beheerder kiest de omzetrekening (Instellingen › Administratie › Vastgoed-koppeling)</span>
  }
  if (laadFout) {
    return (
      <span className="hint" style={{ color: 'var(--red)' }}>
        {laadFout}
      </span>
    )
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-2" style={{ minWidth: 0 }}>
      <span style={{ minWidth: 240 }}>
        <SearchableCombobox
          label={`Omzetrekening voor ${regelsoort}`}
          toonLabel={false}
          opties={opties ?? []}
          waarde={keuze}
          onWijzig={(id) => setKeuze(id || null)}
          placeholder={opties === null ? 'Rekeningen laden…' : 'Rekening kiezen…'}
        />
      </span>
      <Button variant="primair" maat="klein" onClick={() => void uitvoeren()} disabled={!keuze || bezig} aria-label={`Omzetrekening voor ${regelsoort} kiezen`}>
        {bezig ? 'Bezig…' : 'Rekening kiezen'}
      </Button>
      {fout && (
        <span className="hint" style={{ color: 'var(--red)' }}>
          {fout}
        </span>
      )}
    </span>
  )
}

export function OpnieuwAanbiedenActie({ bevinding, onGelukt }: { bevinding: BevindingDto; onGelukt: (melding: string) => void }) {
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [klaar, setKlaar] = useState<VastlyOpnieuwAanbiedenResultaatDto | null>(null)
  const documentId = String(bevinding.detail?.document_id ?? '')
  const bestand = typeof bevinding.detail?.bestandsnaam === 'string' ? (bevinding.detail.bestandsnaam as string) : documentId

  const uitvoeren = async () => {
    if (!documentId || bevinding.administratie_id === null) return
    setBezig(true)
    setFout(null)
    try {
      const r = await opnieuwAanbieden(documentId, bevinding.administratie_id)
      setKlaar(r)
      onGelukt(r.uitkomst === 'geboekt' ? `${bestand} is automatisch als omzet geboekt.` : `${bestand} nog niet geboekt: ${r.reden ?? 'reden onbekend'}`)
    } catch (err) {
      // 409 = geen kandidaat meer (status/soort), 404 = buiten scope — zichtbaar, nooit stil.
      setFout(err instanceof ApiError ? err.message : 'Opnieuw aanbieden mislukt.')
    } finally {
      setBezig(false)
    }
  }

  if (klaar) {
    return <span className="hint">{klaar.uitkomst === 'geboekt' ? 'geboekt' : `niet geboekt — ${klaar.reden ?? ''}`}</span>
  }
  return (
    <>
      <Button variant="primair" maat="klein" onClick={() => void uitvoeren()} disabled={!documentId || bezig} aria-label={`${bestand} opnieuw aanbieden`}>
        {bezig ? 'Bezig…' : 'Opnieuw aanbieden'}
      </Button>
      {fout && (
        <>
          {' '}
          <span className="hint" style={{ color: 'var(--red)' }}>
            {fout}
          </span>
        </>
      )}
    </>
  )
}
