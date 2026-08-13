import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '../api/client'
import type {
  DoorbelastingMappingDto,
  DoorbelastingPreviewDto,
  DoorbelastingRunDto,
  DoorbelastingVerdeelRegelDto,
  SpiegelTaakDto,
} from '../api/types'
import { SearchableCombobox } from '../document/SearchableCombobox'
import { FoutMelding } from '../ui/FoutMelding'
import {
  boekSpiegelAlsnog,
  haalDoorbelastingMappingsOp,
  haalDoorbelastingRunVoorDocumentOp,
  haalDoorbelastingToggleOp,
  haalSpiegelTakenOp,
  zetSpiegelDoelGbs,
} from './doorbelastingApi'
import { StornoModal } from './StornoModal'
import { boekingStatusChip, formatEuroString, formatPercentage } from './status'
import { useDoelGrootboek } from './useDoelGrootboek'

interface Props {
  administratieId: string
  documentId: string
  status: string
  soort: string
}

/** Doorbelasten-sectie op het documentdetail (Kempen-doorbelasting blok 3; besluit Peter
 * 2026-08-13: de trigger is een actie op een GEBOEKT document, bewust niet de
 * mockup-boekflow). Alleen zichtbaar bij status geboekt + soort inkoopfactuur + de
 * doorbelasting-toggle van de administratie aan (faalvriendelijke GET — een fout betekent
 * gewoon: geen sectie, de rest van het scherm werkt door). */
export function DoorbelastenSectie({ administratieId, documentId, status, soort }: Props) {
  const relevant = status === 'geboekt' && soort === 'inkoopfactuur'
  const [ingeschakeld, setIngeschakeld] = useState<boolean | null>(null)

  useEffect(() => {
    if (!relevant) return
    let actief = true
    haalDoorbelastingToggleOp(administratieId)
      .then((dto) => {
        if (actief) setIngeschakeld(dto.ingeschakeld)
      })
      .catch(() => {
        // Faalvriendelijk: de sectie is verrijking — een fout hier mag het detailscherm
        // nooit blokkeren of vervuilen.
        if (actief) setIngeschakeld(false)
      })
    return () => {
      actief = false
    }
  }, [administratieId, relevant])

  if (!relevant || ingeschakeld !== true) return null
  return <DoorbelastenInhoud administratieId={administratieId} documentId={documentId} />
}

interface InhoudProps {
  administratieId: string
  documentId: string
}

function DoorbelastenInhoud({ administratieId, documentId }: InhoudProps) {
  // undefined = laden; null = er is (nog) geen run — de knop start er pas één via het
  // reviewscherm (fix 2026-08-13: louter openen van het detail maakt niets meer aan)
  const [run, setRun] = useState<DoorbelastingRunDto | null | undefined>(undefined)
  const [spiegelTaken, setSpiegelTaken] = useState<SpiegelTaakDto[]>([])
  const [mappings, setMappings] = useState<DoorbelastingMappingDto[]>([])
  const [fout, setFout] = useState<string | null>(null)
  const [versie, setVersie] = useState(0)
  const [stornoDoel, setStornoDoel] = useState<{ boekingId: string; naam: string } | null>(null)

  useEffect(() => {
    let actief = true
    setFout(null)
    // Read-only leesroute (GET, 404 → null): het openen van het detailscherm maakt nooit een
    // run of audit-event aan — de POST leeft uitsluitend in het reviewscherm (gebruikersactie).
    // Spiegel-taken en mappings zijn verrijking voor de spiegel-flow; een fout daar degradeert
    // stil naar "geen taakdetails" (de run-chips blijven staan).
    const takenBelofte = haalSpiegelTakenOp(administratieId).catch(() => [] as SpiegelTaakDto[])
    const mappingsBelofte = haalDoorbelastingMappingsOp(administratieId).catch(() => [] as DoorbelastingMappingDto[])
    haalDoorbelastingRunVoorDocumentOp(administratieId, documentId)
      .then(async (runData) => {
        const [taken, mappingLijst] = await Promise.all([takenBelofte, mappingsBelofte])
        if (!actief) return
        setRun(runData)
        setSpiegelTaken(taken.filter((t) => t.document_id === documentId))
        setMappings(mappingLijst)
      })
      .catch((err: unknown) => {
        if (actief) setFout(err instanceof ApiError ? err.message : 'Doorbelasting-status niet te laden.')
      })
    return () => {
      actief = false
    }
  }, [administratieId, documentId, versie])

  const herlaad = () => setVersie((v) => v + 1)

  const boekingen = run?.previews.filter((p) => p.boeking_status !== null) ?? []
  const taakPerMapping = new Map(spiegelTaken.map((t) => [t.mapping_id, t]))
  const mappingPerId = new Map(mappings.map((m) => [m.id, m]))
  const volledigGeboekt = run?.status === 'geboekt'

  /** Boeking-id voor de storno-actie: spiegel_open-taken dragen hem via de taken-lijst; voor
   * andere statussen alleen als de backend hem in de preview meegeeft (optioneel veld). */
  const boekingIdVoor = (p: DoorbelastingPreviewDto): string | null =>
    p.boeking_id ?? taakPerMapping.get(p.mapping_id)?.boeking_id ?? null

  return (
    <div className="panel">
      <h2>
        Doorbelasting{' '}
        {run &&
          (volledigGeboekt ? (
            <span className="chip ok">doorbelast ✓</span>
          ) : boekingen.length > 0 ? (
            <span className="chip vraag">deels doorbelast</span>
          ) : (
            <span className="chip geheugen">nog niet doorbelast</span>
          ))}
      </h2>
      {fout && (
        <FoutMelding melding="De doorbelasting-status kon niet geladen worden." detail={fout} onOpnieuw={herlaad} />
      )}
      {run === undefined && !fout && <p className="hint">Doorbelasting-status laden…</p>}
      {run === null && !fout && (
        <>
          <p className="hint" style={{ marginTop: 0 }}>
            Deze geboekte inkoopfactuur kan per regel procentueel doorbelast worden aan de
            groepsentiteiten op de whitelist — per doelentiteit ontstaat een verkoopfactuur in deze
            administratie (kosten + provisie) en een spiegel-inkoopfactuur in de doel-administratie.
          </p>
          <div className="actions">
            <Link className="btn" to={`/doorbelasting/${administratieId}/${documentId}`}>
              Doorbelasten…
            </Link>
          </div>
        </>
      )}
      {run && (
        <>
          {boekingen.length === 0 && (
            <p className="hint" style={{ marginTop: 0 }}>
              Deze geboekte inkoopfactuur kan per regel procentueel doorbelast worden aan de
              groepsentiteiten op de whitelist — per doelentiteit ontstaat een verkoopfactuur in deze
              administratie (kosten + provisie) en een spiegel-inkoopfactuur in de doel-administratie.
            </p>
          )}
          {boekingen.length > 0 && (
            <div className="tabel-scroll">
              <table className="lines">
                <tbody>
                  <tr>
                    <th>Doelentiteit</th>
                    <th className="amount">Doorbelast (excl.)</th>
                    <th className="amount">Provisie</th>
                    <th>Status</th>
                    <th />
                  </tr>
                  {boekingen.map((p) => {
                    const chip = boekingStatusChip(p.boeking_status ?? '')
                    const stornoId = boekingIdVoor(p)
                    return (
                      <SectieBoekingRij
                        key={p.mapping_id}
                        administratieId={administratieId}
                        preview={p}
                        chipKlasse={chip.klasse}
                        chipLabel={chip.label}
                        taak={taakPerMapping.get(p.mapping_id) ?? null}
                        mapping={mappingPerId.get(p.mapping_id) ?? null}
                        regels={run.regels.filter((r) => r.mapping_id === p.mapping_id)}
                        onStorno={stornoId ? () => setStornoDoel({ boekingId: stornoId, naam: p.doelentiteit_naam }) : null}
                        onGewijzigd={herlaad}
                      />
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
          {run.laatste_fout && (
            <div className="fout">
              De laatste boekpoging gaf een fout — niets is stil half blijven hangen; probeer het via het
              reviewscherm opnieuw.
              <details style={{ marginTop: 6 }}>
                <summary style={{ cursor: 'pointer', fontSize: 12 }}>Technische details</summary>
                <code style={{ fontSize: 12, wordBreak: 'break-word' }}>{JSON.stringify(run.laatste_fout)}</code>
              </details>
            </div>
          )}
          {!volledigGeboekt && (
            <div className="actions">
              <Link className="btn" to={`/doorbelasting/${administratieId}/${documentId}`}>
                {boekingen.length > 0 ? 'Doorbelasting afmaken…' : 'Doorbelasten…'}
              </Link>
            </div>
          )}
        </>
      )}
      {stornoDoel && (
        <StornoModal
          administratieId={administratieId}
          boekingId={stornoDoel.boekingId}
          doelentiteitNaam={stornoDoel.naam}
          onGestorneerd={() => {
            setStornoDoel(null)
            herlaad()
          }}
          onAnnuleren={() => setStornoDoel(null)}
        />
      )}
    </div>
  )
}

interface RijProps {
  administratieId: string
  preview: DoorbelastingPreviewDto
  chipKlasse: string
  chipLabel: string
  taak: SpiegelTaakDto | null
  mapping: DoorbelastingMappingDto | null
  regels: DoorbelastingVerdeelRegelDto[]
  /** null = geen boeking-id beschikbaar → geen storno-knop (nooit een knop die alleen kan falen). */
  onStorno: (() => void) | null
  onGewijzigd: () => void
}

function SectieBoekingRij({
  administratieId,
  preview,
  chipKlasse,
  chipLabel,
  taak,
  mapping,
  regels,
  onStorno,
  onGewijzigd,
}: RijProps) {
  const isSpiegelOpen = preview.boeking_status === 'spiegel_open'
  return (
    <>
      <tr>
        <td>
          <b>{preview.doelentiteit_naam}</b>
        </td>
        <td className="amount">€ {formatEuroString(preview.netto_totaal)}</td>
        <td className="amount">€ {formatEuroString(preview.provisie_bedrag)}</td>
        <td>
          <span className={`chip ${chipKlasse}`}>{chipLabel}</span>
        </td>
        <td>
          {onStorno && (
            <button type="button" className="btn secondary" onClick={onStorno}>
              Storneren…
            </button>
          )}
        </td>
      </tr>
      {isSpiegelOpen && taak && (
        <tr>
          <td colSpan={5} style={{ paddingTop: 0 }}>
            <SpiegelTaakBlok
              administratieId={administratieId}
              taak={taak}
              mapping={mapping}
              regels={regels}
              onGeboekt={onGewijzigd}
            />
          </td>
        </tr>
      )}
    </>
  )
}

interface SpiegelTaakBlokProps {
  administratieId: string
  taak: SpiegelTaakDto
  mapping: DoorbelastingMappingDto | null
  regels: DoorbelastingVerdeelRegelDto[]
  onGeboekt: () => void
}

/** Open spiegel-taak: de bron-kant is geboekt, de spiegel-inkoopfactuur in de doel-administratie
 * nog niet (doel was op boekmoment niet onboarded). De verdeling is bevroren; wat hier nog wél
 * kiesbaar is zijn de doel-kosten-GB's per verdeelregel + de provisie-GB (gaten-scan-fix
 * 2026-08-13: eerst PUT doel-gbs, dan POST spiegel-boeken). */
export function SpiegelTaakBlok({ administratieId, taak, mapping, regels, onGeboekt }: SpiegelTaakBlokProps) {
  const doelAdministratieId = mapping?.doel_administratie_id ?? null
  const doelGrootboek = useDoelGrootboek([doelAdministratieId])
  const [gbPerRegel, setGbPerRegel] = useState<Record<string, string | null>>(() =>
    Object.fromEntries(regels.map((r) => [r.id, r.doel_kosten_ledger_id])),
  )
  const [provisieGb, setProvisieGb] = useState<string | null>(mapping?.provisie_kosten_ledger_id ?? null)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  if (!mapping) {
    return (
      <p className="hint" style={{ margin: 0 }}>
        Spiegel-taak open sinds {new Date(taak.aangemaakt_op).toLocaleDateString('nl-NL')} — de
        mapping-gegevens zijn niet te laden; probeer het later opnieuw.
      </p>
    )
  }
  if (!doelAdministratieId) {
    return (
      <p className="hint" style={{ margin: 0 }}>
        De doel-administratie van <b>{taak.doelentiteit_naam}</b> is nog niet onboarded — zodra de
        administratie gekoppeld is (Instellingen → Doorbelasting) kan de spiegel-inkoopfactuur hier
        alsnog geboekt worden. Verkoopreferentie bron: <b>{taak.verkoop_referentie ?? '—'}</b>.
      </p>
    )
  }

  const schema = doelGrootboek[doelAdministratieId]
  if (schema?.fout) {
    return (
      <p className="hint" style={{ margin: 0, color: 'var(--orange)' }}>
        {schema.fout}
      </p>
    )
  }

  const allesGekozen = regels.every((r) => gbPerRegel[r.id]) && provisieGb !== null

  const boeken = async () => {
    setBezig(true)
    setFout(null)
    try {
      // Stap 1: GB-toewijzing (alleen GB's — bedragen/percentages zijn bevroren). Ook al
      // ingevulde regels reizen mee: idempotent, en zo klopt de server-staat altijd met wat
      // de gebruiker hier ziet.
      const regelGbs: Record<string, string> = {}
      for (const r of regels) {
        const gekozen = gbPerRegel[r.id]
        if (gekozen) regelGbs[r.id] = gekozen
      }
      await zetSpiegelDoelGbs(administratieId, taak.boeking_id, {
        regel_gbs: regelGbs,
        ...(provisieGb && provisieGb !== mapping.provisie_kosten_ledger_id
          ? { provisie_kosten_ledger_id: provisieGb }
          : {}),
      })
      // Stap 2: de spiegel alsnog boeken.
      const resultaat = await boekSpiegelAlsnog(administratieId, taak.boeking_id)
      const nieuweStatus = resultaat.per_doelentiteit[taak.mapping_id]
      if (nieuweStatus && nieuweStatus !== 'geboekt') {
        setFout(`De spiegel is nog niet geboekt (status: ${nieuweStatus}) — probeer het opnieuw.`)
      }
      onGeboekt()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Spiegel boeken mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <div style={{ background: 'var(--bg)', borderRadius: 8, padding: '10px 12px' }}>
      <p className="hint" style={{ marginTop: 0 }}>
        Open spiegel-taak: kies per verdeelregel de kostenrekening in het rekeningschema van{' '}
        <b>{taak.doelentiteit_naam}</b> (de verdeling zelf is bevroren) en boek de spiegel-inkoopfactuur
        alsnog. Verkoopreferentie bron: <b>{taak.verkoop_referentie ?? '—'}</b>.
      </p>
      <table className="lines">
        <tbody>
          <tr>
            <th className="amount">Deel (excl.)</th>
            <th>%</th>
            <th>Kosten-GB in {taak.doelentiteit_naam}</th>
          </tr>
          {regels.map((r) => (
            <tr key={r.id}>
              <td className="amount">€ {formatEuroString(r.netto_deel)}</td>
              <td>{formatPercentage(r.percentage)}%</td>
              <td>
                <SearchableCombobox
                  label={`Kosten-GB deel € ${formatEuroString(r.netto_deel)}`}
                  toonLabel={false}
                  opties={schema?.opties ?? []}
                  waarde={gbPerRegel[r.id] ?? null}
                  onWijzig={(id) => setGbPerRegel((huidig) => ({ ...huidig, [r.id]: id }))}
                  placeholder="Kies kostenrekening…"
                  vereist
                />
              </td>
            </tr>
          ))}
          <tr>
            <td className="amount">€ {formatEuroString(taak.provisie_bedrag)}</td>
            <td />
            <td>
              <SearchableCombobox
                label={`Provisie-GB in ${taak.doelentiteit_naam}`}
                toonLabel={false}
                opties={schema?.opties ?? []}
                waarde={provisieGb}
                onWijzig={setProvisieGb}
                placeholder="Kies provisie-rekening…"
                vereist
              />
              <div className="hint" style={{ margin: '4px 0 0' }}>
                Provisie-GB — wordt als vaste keuze op de mapping onthouden.
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      {fout && <div className="fout">{fout}</div>}
      <div className="actions">
        <button
          type="button"
          className="btn green"
          disabled={!allesGekozen || bezig}
          title={
            allesGekozen
              ? 'Boekt de spiegel-inkoopfactuur in de doel-administratie'
              : 'Kies eerst voor elke regel én de provisie een rekening in de doel-administratie'
          }
          onClick={() => void boeken()}
        >
          {bezig ? 'Bezig…' : 'Spiegel alsnog boeken ✓'}
        </button>
      </div>
    </div>
  )
}
