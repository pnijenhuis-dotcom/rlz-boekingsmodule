import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, apiJson } from '../api/client'
import type { BoekvoorstelDto, DoorbelastingMappingDto, DoorbelastingRunDto } from '../api/types'
import { BevestigDialog } from '../instellingen/BevestigDialog'
import { Checkbox } from '../ui/basis'
import { FoutMelding } from '../ui/FoutMelding'
import {
  haalDoorbelastingMappingsOp,
  haalDoorbelastingRunVoorDocumentOp,
  haalDoorbelastingToggleOp,
  laatDoorbelastingRunVervallen,
  startDoorbelastingRun,
} from './doorbelastingApi'
import { runVerdelingOnvolledig, VerdelingEditor, type BronRegel, type VerdelingStaat } from './VerdelingEditor'

/** Statussen waarin het blok getoond wordt: de boekbare statussen (klaarzetten kan) plus
 * ter_accordering (alleen-lezen — de verdeling ligt bij de klant). Spiegel van
 * `_KLAARZETBARE_DOCUMENTSTATUSSEN` in app/doorbelasting/service.py. */
const KLAARZETBAAR = new Set(['te_controleren', 'klaar_om_te_boeken', 'handmatig_afmaken', 'boeken_mislukt'])

/** Wat de boekknop van het controlescherm moet weten (besluit 25-08, A2: boek-checks én
 * doorbelasting-checks samen groen vóór de knop actief wordt). null = geen klaargezette run. */
export interface KlaargezetteDoorbelasting {
  runId: string
  geblokkeerd: boolean
  reden: string | null
}

interface Props {
  administratieId: string
  documentId: string
  status: string
  soort: string
  /** Telt op bij elke opslag van het boekvoorstel (regels krijgen nieuwe id's — de backend
   * neemt de verdeling per volgnummer mee; de UI herlaadt bron-regels + run). */
  boekvoorstelVersie: number
  onKlaargezet: (staat: KlaargezetteDoorbelasting | null) => void
}

/** Controlescherm-blok "Doorbelasten na boeken" (besluit Peter 25-08, punt A — herziet 13-08):
 * optioneel vinkje op een NOG NIET geboekt document; aangevinkt = een klaargezette run mét de
 * bestaande verdeel-UI inline (doelentiteiten uit de whitelist, %, doel-GB's, preview mét
 * provisie/btw). De knop wordt "Boeken + doorbelasten"; uitvinken laat de run vervallen (nooit
 * een delete). Alleen zichtbaar bij inkoopfactuur + doorbelasting-toggle aan (faalvriendelijk:
 * GET-fout = geen blok). De losse actie "Doorbelasten…" op een geboekt document blijft bestaan. */
export function DoorbelastenNaBoeken({ administratieId, documentId, status, soort, boekvoorstelVersie, onKlaargezet }: Props) {
  const relevant = soort === 'inkoopfactuur' && (KLAARZETBAAR.has(status) || status === 'ter_accordering')
  const [ingeschakeld, setIngeschakeld] = useState<boolean | null>(null)

  useEffect(() => {
    if (!relevant) return
    let actief = true
    haalDoorbelastingToggleOp(administratieId)
      .then((dto) => {
        if (actief) setIngeschakeld(dto.ingeschakeld)
      })
      .catch(() => {
        if (actief) setIngeschakeld(false)
      })
    return () => {
      actief = false
    }
  }, [administratieId, relevant])

  if (!relevant || ingeschakeld !== true) return null
  return (
    <Inhoud
      administratieId={administratieId}
      documentId={documentId}
      status={status}
      boekvoorstelVersie={boekvoorstelVersie}
      onKlaargezet={onKlaargezet}
    />
  )
}

function Inhoud({
  administratieId,
  documentId,
  status,
  boekvoorstelVersie,
  onKlaargezet,
}: Omit<Props, 'soort'>) {
  // undefined = laden; null = geen klaargezette run (vinkje uit)
  const [run, setRun] = useState<DoorbelastingRunDto | null | undefined>(undefined)
  const [bronRegels, setBronRegels] = useState<BronRegel[]>([])
  const [regelIdsOntbreken, setRegelIdsOntbreken] = useState(false)
  const [mappings, setMappings] = useState<DoorbelastingMappingDto[]>([])
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const [vervallenVraag, setVervallenVraag] = useState(false)
  const [staat, setStaat] = useState<VerdelingStaat>({ gewijzigd: false, onvolledig: false })
  const onStaat = useCallback((s: VerdelingStaat) => setStaat(s), [])
  const bevroren = status === 'ter_accordering'

  const laadBronRegels = useCallback(async () => {
    const boekvoorstel = await apiJson<BoekvoorstelDto>(
      `/administraties/${administratieId}/documenten/${documentId}/boekvoorstel`,
    )
    const metId = boekvoorstel.regels.filter((r): r is typeof r & { id: string } => Boolean(r.id))
    setRegelIdsOntbreken(metId.length !== boekvoorstel.regels.length)
    setBronRegels(
      metId.map((r, i) => ({
        id: r.id,
        omschrijving: r.omschrijving?.trim() || `Regel ${i + 1}`,
        netto: r.netto_bedrag,
      })),
    )
  }, [administratieId, documentId])

  // Leesroute (GET, 404 → geen run): openen van het controlescherm maakt nooit een run aan —
  // de POST is het vinkje (gebruikersactie). Herladen bij elke boekvoorstel-opslag.
  useEffect(() => {
    let actief = true
    setFout(null)
    Promise.all([
      haalDoorbelastingRunVoorDocumentOp(administratieId, documentId),
      haalDoorbelastingMappingsOp(administratieId).catch(() => [] as DoorbelastingMappingDto[]),
      laadBronRegels(),
    ])
      .then(([runData, mappingLijst]) => {
        if (!actief) return
        setRun(runData && runData.status === 'klaargezet' ? runData : null)
        setMappings(mappingLijst)
      })
      .catch((err: unknown) => {
        if (actief) setFout(err instanceof ApiError ? err.message : 'Doorbelasting-status niet te laden.')
      })
    return () => {
      actief = false
    }
  }, [administratieId, documentId, boekvoorstelVersie, laadBronRegels])

  // Poort-signaal naar de boekknop: server-checks van de run + werkstaat van de editor.
  useEffect(() => {
    if (run === undefined) return
    if (run === null) {
      onKlaargezet(null)
      return
    }
    const geenVerdeling = run.regels.length === 0
    const reden = staat.gewijzigd
      ? 'De verdeling is gewijzigd maar nog niet opgeslagen — sla eerst op'
      : staat.onvolledig || runVerdelingOnvolledig(run)
        ? 'Elke verdeelde regel moet exact op 100% sluiten'
        : geenVerdeling
          ? 'Doorbelasten na boeken staat aan, maar er is nog geen verdeling opgeslagen'
          : run.checks.geblokkeerd
            ? 'Doorbelasting-checks zijn niet groen: ' +
              run.checks.resultaten
                .filter((r) => !r.ok)
                .map((r) => r.melding)
                .join('; ')
            : null
    onKlaargezet({ runId: run.id, geblokkeerd: reden !== null, reden })
  }, [run, staat, onKlaargezet])

  const aanzetten = async () => {
    setBezig(true)
    setFout(null)
    try {
      const nieuw = await startDoorbelastingRun(administratieId, documentId)
      setRun(nieuw)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Doorbelasten klaarzetten mislukt.')
    } finally {
      setBezig(false)
    }
  }

  const uitzetten = async () => {
    if (!run) return
    setBezig(true)
    setFout(null)
    try {
      await laatDoorbelastingRunVervallen(administratieId, run.id)
      setRun(null)
      setVervallenVraag(false)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Doorbelasten uitzetten mislukt.')
    } finally {
      setBezig(false)
    }
  }

  const aangevinkt = run !== null && run !== undefined

  return (
    <div className="panel">
      <h2>
        Doorbelasten na boeken{' '}
        {aangevinkt && !bevroren && <span className="chip klaar">klaargezet</span>}
        {aangevinkt && bevroren && <span className="chip klaar">bij klant — alleen-lezen</span>}
      </h2>
      <label style={{ display: 'flex', alignItems: 'center', gap: 8, margin: 0 }}>
        <Checkbox
          checked={aangevinkt}
          disabled={bezig || run === undefined || bevroren}
          aria-label="Doorbelasten na boeken"
          onChange={(e) => {
            if (e.target.checked) void aanzetten()
            else if (run && run.regels.length > 0) setVervallenVraag(true)
            else void uitzetten()
          }}
        />
        <span>
          Deze factuur na het boeken doorbelasten aan één of meer doelentiteiten (Kempen-patroon). De
          boekknop wordt dan &ldquo;Boeken + doorbelasten&rdquo;: inkoopfactuur → verkoopfacturen → spiegels in
          één gang, alle harde checks vooraf.
        </span>
      </label>
      {fout && <FoutMelding melding={fout} />}
      {aangevinkt && (
        <div style={{ marginTop: 12 }}>
          {bevroren && (
            <p className="hint" style={{ marginTop: 0 }}>
              Het document ligt bij de klant ter accordering: de accordeur ziet deze verdeling alleen-lezen.
              Afwijzen door de klant (met reden) maakt de verdeling weer bewerkbaar.
            </p>
          )}
          <VerdelingEditor
            key={run.id}
            administratieId={administratieId}
            run={run}
            bronRegels={bronRegels}
            regelIdsOntbreken={regelIdsOntbreken}
            mappings={mappings}
            bevroren={bevroren}
            onRunGewijzigd={setRun}
            onStaat={onStaat}
            compact
          />
          {regelIdsOntbreken && (
            <FoutMelding melding="Niet alle boekingsregels zijn al opgeslagen — pas het voorstel aan (de checks slaan automatisch op) en de regels verschijnen hier." />
          )}
          <p className="hint" style={{ marginBottom: 0 }}>
            Boekt de inkoopfactuur en direct daarna, via dezelfde doorbelastingsmotor, per doelentiteit
            de verkoopfactuur (kosten + provisie) en de spiegel-inkoopfactuur. Faalt een deel ná de
            inkoopboeking, dan is dat zichtbaar op het document (bestaande herstel-/stornoroutes). Later
            alsnog doorbelasten kan ook: <Link to={`/doorbelasting/${administratieId}/${documentId}`}>Doorbelasten…</Link>{' '}
            op het geboekte document.
          </p>
        </div>
      )}
      {vervallenVraag && (
        <BevestigDialog
          titel="Doorbelasten na boeken uitzetten?"
          bericht="De klaargezette verdeling vervalt (blijft als spoor in de audit staan). De factuur boekt dan als gewone inkoopfactuur; doorbelasten kan later alsnog via de actie op het geboekte document."
          bezig={bezig}
          fout={null}
          onBevestigen={() => void uitzetten()}
          onAnnuleren={() => setVervallenVraag(false)}
        />
      )}
    </div>
  )
}
