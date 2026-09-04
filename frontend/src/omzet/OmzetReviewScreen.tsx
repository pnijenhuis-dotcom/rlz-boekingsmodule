import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, apiFetch, apiJson } from '../api/client'
import type {
  CheckRapportDto,
  DocumentDetailDto,
  OmzetBoekenResponseDto,
  OmzetRegelDto,
  OmzetVoorstelDto,
  OmzetVoorstelInputDto,
} from '../api/types'
import { GeboektInRlzRegel } from '../document/GeboektInRlz'
import { bedragAlsGetal, normaliseerBedrag } from '../document/bedrag'
import { SearchableCombobox } from '../document/SearchableCombobox'
import { useAutoChecks } from '../document/useAutoChecks'
import { useGrootboekOpties, useTaxrateOpties } from '../document/useSyncOpties'
import { ChecksPopup } from '../ui/ChecksPopup'
import { DatePicker } from '../ui/DatePicker'
import { haalOmzetVoorstelOp, slaOmzetVoorstelOp, voerOmzetChecksUit } from './omzetApi'
import { SkeletonPaneel } from '../ui/basis'
import { metViewerOpties } from '../document/pdfWeergaveUrl'

/** Bewerkbare regel-staat: bedragen als tekst (NL-invoer toegestaan), keuzes als id's. */
interface RegelStaat {
  categorie: string
  omzetBedrag: string
  kostprijsBedrag: string
  omzetLedgerId: string | null
  taxrateId: string | null
  kostprijsLedgerId: string | null
  herkomst: string
}

function naarRegelStaat(regel: OmzetRegelDto): RegelStaat {
  return {
    categorie: regel.categorie,
    omzetBedrag: regel.omzet_bedrag ?? '',
    kostprijsBedrag: regel.kostprijs_bedrag ?? '',
    omzetLedgerId: regel.omzet_ledger_id,
    taxrateId: regel.taxrate_id,
    kostprijsLedgerId: regel.kostprijs_ledger_id,
    herkomst: regel.herkomst,
  }
}

function formatBedrag(waarde: number): string {
  return waarde.toLocaleString('nl-NL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** Statussen waaruit de backend een boekpoging accepteert (documenten.boeken-poort). */
const BOEKBARE_STATUSSEN = new Set(['te_controleren', 'klaar_om_te_boeken', 'boeken_mislukt', 'handmatig_afmaken'])

export function OmzetReviewScreen() {
  const { administratieId, documentId } = useParams<{ administratieId: string; documentId: string }>()

  const [detail, setDetail] = useState<DocumentDetailDto | null>(null)
  const [voorstel, setVoorstel] = useState<OmzetVoorstelDto | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [bijlageUrl, setBijlageUrl] = useState<string | null>(null)

  const [periodeStart, setPeriodeStart] = useState('')
  const [periodeEind, setPeriodeEind] = useState('')
  const [totaalOmzet, setTotaalOmzet] = useState('')
  const [totaalKostprijs, setTotaalKostprijs] = useState('')
  const [regels, setRegels] = useState<RegelStaat[]>([])
  const [voorraadLedgerId, setVoorraadLedgerId] = useState<string | null>(null)

  const [opslaanBezig, setOpslaanBezig] = useState(false)
  const [opslaanFout, setOpslaanFout] = useState<string | null>(null)
  const [checkRapport, setCheckRapport] = useState<CheckRapportDto | null>(null)
  const [boekenBezig, setBoekenBezig] = useState(false)
  const [boekenFout, setBoekenFout] = useState<string | null>(null)
  const [boekResultaat, setBoekResultaat] = useState<OmzetBoekenResponseDto | null>(null)
  // Elke wijziging maakt een eerder checkresultaat verouderd — het rapport blijft zichtbaar
  // maar telt niet meer als groen licht; de checks draaien daarna automatisch opnieuw
  // (blok B 2026-08-10: geen "Controleren"-knop meer).
  const [checksActueel, setChecksActueel] = useState(false)
  const [wijzigingsVersie, setWijzigingsVersie] = useState(0)
  const wijzigingsVersieRef = useRef(0)
  const [popupChecks, setPopupChecks] = useState<{ melding: string | null; checks: CheckRapportDto } | null>(null)

  const markeerGewijzigd = useCallback(() => {
    setChecksActueel(false)
    wijzigingsVersieRef.current += 1
    setWijzigingsVersie(wijzigingsVersieRef.current)
  }, [])

  const grootboek = useGrootboekOpties(administratieId ?? '')
  const btwCodes = useTaxrateOpties(administratieId ?? '')

  const neemVoorstelOver = useCallback((data: OmzetVoorstelDto) => {
    setVoorstel(data)
    setPeriodeStart(data.periode_start ?? '')
    setPeriodeEind(data.periode_eind ?? '')
    setTotaalOmzet(data.rapport_totaal_omzet ?? '')
    setTotaalKostprijs(data.rapport_totaal_kostprijs ?? '')
    setRegels(data.regels.map(naarRegelStaat))
    setVoorraadLedgerId(data.voorraad_ledger_id)
  }, [])

  useEffect(() => {
    if (!administratieId || !documentId) return
    let actief = true
    Promise.all([
      apiJson<DocumentDetailDto>(`/administraties/${administratieId}/documenten/${documentId}`),
      haalOmzetVoorstelOp(administratieId, documentId),
    ])
      .then(([documentDetail, voorstelData]) => {
        if (!actief) return
        setDetail(documentDetail)
        neemVoorstelOver(voorstelData)
      })
      .catch((err: unknown) => {
        if (actief) setLaadFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
    return () => {
      actief = false
    }
  }, [administratieId, documentId, neemVoorstelOver])

  useEffect(() => {
    if (!administratieId || !documentId) return
    let objectUrl: string | null = null
    let actief = true
    void apiFetch(`/administraties/${administratieId}/documenten/${documentId}/bestand`).then(async (resp) => {
      if (!resp.ok || !actief) return
      objectUrl = URL.createObjectURL(await resp.blob())
      if (actief) setBijlageUrl(objectUrl)
    })
    return () => {
      actief = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [administratieId, documentId])

  const kostprijsTotaalRegels = useMemo(
    () => regels.reduce((som, regel) => som + (bedragAlsGetal(regel.kostprijsBedrag) ?? 0), 0),
    [regels],
  )
  const omzetTotaalRegels = useMemo(
    () => regels.reduce((som, regel) => som + (bedragAlsGetal(regel.omzetBedrag) ?? 0), 0),
    [regels],
  )
  const heeftKostprijs = kostprijsTotaalRegels !== 0

  const wijzigRegel = (index: number, wijziging: Partial<RegelStaat>) => {
    setRegels((huidig) => huidig.map((regel, i) => (i === index ? { ...regel, ...wijziging } : regel)))
    markeerGewijzigd()
  }

  const bouwInvoer = (): OmzetVoorstelInputDto => ({
    periode_start: periodeStart || null,
    periode_eind: periodeEind || null,
    rapport_totaal_omzet: totaalOmzet ? normaliseerBedrag(totaalOmzet) : null,
    rapport_totaal_kostprijs: totaalKostprijs ? normaliseerBedrag(totaalKostprijs) : null,
    regels: regels.map((regel) => ({
      categorie: regel.categorie,
      omzet_bedrag: regel.omzetBedrag ? normaliseerBedrag(regel.omzetBedrag) : null,
      kostprijs_bedrag: regel.kostprijsBedrag ? normaliseerBedrag(regel.kostprijsBedrag) : null,
      omzet_ledger_id: regel.omzetLedgerId,
      taxrate_id: regel.taxrateId,
      kostprijs_ledger_id: regel.kostprijsLedgerId,
    })),
    voorraad_ledger_id: voorraadLedgerId,
    mapping_onthouden: true,
  })

  const opslaan = async (): Promise<boolean> => {
    if (!administratieId || !documentId) return false
    setOpslaanBezig(true)
    setOpslaanFout(null)
    // Versie vóór het versturen vastleggen: typt de gebruiker dóór terwijl de save loopt, dan
    // mag de response de verse invoer niet overschrijven (de volgende debounce-run pakt 'm op).
    const versieBijVersturen = wijzigingsVersieRef.current
    try {
      const data = await slaOmzetVoorstelOp(administratieId, documentId, bouwInvoer())
      if (wijzigingsVersieRef.current === versieBijVersturen) neemVoorstelOver(data)
      return true
    } catch (err) {
      setOpslaanFout(err instanceof ApiError ? err.message : 'Opslaan mislukt.')
      return false
    } finally {
      setOpslaanBezig(false)
    }
  }

  /** Checks bij openen: read-only over het opgeslagen voorstel óf de prefill — zonder opslaan
   * (blok B 2026-08-10: checks draaien automatisch, geen knop). */
  const checksBijOpenen = useCallback(async () => {
    if (!administratieId || !documentId) return
    const versieBijStart = wijzigingsVersieRef.current
    const resultaat = await voerOmzetChecksUit(administratieId, documentId)
    if (wijzigingsVersieRef.current === versieBijStart) {
      setCheckRapport(resultaat.checks)
      setChecksActueel(true)
    }
  }, [administratieId, documentId])

  /** Checks na een wijziging (gedebounced): opslaan + checks — exact wat de vroegere
   * "Controleren"-knop deed, zonder menselijke handeling. */
  const checksBijWijziging = async () => {
    if (!administratieId || !documentId) return
    const versieBijStart = wijzigingsVersieRef.current
    if (!(await opslaan())) return
    try {
      const resultaat = await voerOmzetChecksUit(administratieId, documentId)
      if (wijzigingsVersieRef.current === versieBijStart) {
        setCheckRapport(resultaat.checks)
        setChecksActueel(true)
      }
    } catch (err) {
      setOpslaanFout(err instanceof ApiError ? err.message : 'Checks uitvoeren mislukt.')
    }
  }

  const boeken = async () => {
    if (!administratieId || !documentId) return
    setBoekenBezig(true)
    setBoekenFout(null)
    try {
      if (!(await opslaan())) return
      // Rauwe apiFetch (zelfde patroon als het controlescherm): BoekenGeblokkeerdDoorChecks (409)
      // stuurt het verse CheckRapport mee in detail.checks — een object dat de generieke
      // apiJson/ApiError-afhandeling niet kan uitpakken.
      const resp = await apiFetch(`/administraties/${administratieId}/omzet/documenten/${documentId}/boeken`, {
        method: 'POST',
      })
      const body: unknown = await resp.json().catch(() => null)
      if (resp.ok) {
        const resultaat = body as OmzetBoekenResponseDto
        setBoekResultaat(resultaat)
        setDetail((huidig) => (huidig ? { ...huidig, status: resultaat.status } : huidig))
        return
      }
      const detailBody = body && typeof body === 'object' ? (body as { detail?: unknown }).detail : null
      if (resp.status === 409 && detailBody && typeof detailBody === 'object' && 'checks' in detailBody) {
        const { melding, checks } = detailBody as { melding?: string; checks: CheckRapportDto }
        setCheckRapport(checks)
        setChecksActueel(true)
        // Blok B: de server-side herdraaide checks blokkeren → pop-up met de concrete
        // gefaalde check(s); de inline lijst blijft daarnaast staan.
        setPopupChecks({ melding: melding ?? null, checks })
      } else {
        setBoekenFout(typeof detailBody === 'string' ? detailBody : resp.statusText || `Fout (${resp.status})`)
      }
    } catch (err) {
      setBoekenFout(err instanceof ApiError ? err.message : 'Boeken mislukt.')
    } finally {
      setBoekenBezig(false)
    }
  }

  // Blok B 2026-08-10: checks draaien automatisch — bij openen (read-only) en gedebounced na
  // elke wijziging (opslaan + checks). Geen "Controleren"-knop meer.
  const { checksBezig } = useAutoChecks({
    actief:
      detail !== null && voorstel !== null && detail.status !== 'geboekt' && detail.status !== 'verwijderd',
    wijzigingsVersie,
    bijOpenen: checksBijOpenen,
    bijWijziging: checksBijWijziging,
  })

  if (laadFout) return <div className="fout">Kon omzetboeking niet laden: {laadFout}</div>
  if (!detail || !voorstel || !administratieId || !documentId) return <SkeletonPaneel />

  const isGeboekt = detail.status === 'geboekt'
  const isVraagOpen = detail.status === 'vraag_open'
  const isBoekbaar = BOEKBARE_STATUSSEN.has(detail.status)
  const nieuweCategorieen = regels.filter((r) => r.herkomst === 'nieuw')
  const checksGroen = checksActueel && checkRapport !== null && !checkRapport.geblokkeerd

  return (
    <div>
      <div className="topbar">
        <h1>
          <Link to={`/?administratie=${administratieId}`}>← Werkvoorraad</Link>{' '}
          <span style={{ color: 'var(--muted)', fontWeight: 400 }}>/</span> {detail.bestandsnaam}
        </h1>
        <div className="adm-select">
          <span className="chip klaar">omzetboeking · kassarapport</span>
        </div>
      </div>

      <div className="membanner">
        <div className="icon">🧠</div>
        <div>
          <b>Rapport herkend:</b>{' '}
          {voorstel.rapport_titel ?? 'kassarapport'}
          {voorstel.entiteit_naam ? ` ${voorstel.entiteit_naam}` : ''}, periode{' '}
          {voorstel.periode_start && voorstel.periode_eind
            ? `${voorstel.periode_start} t/m ${voorstel.periode_eind} (uit het rapport zelf gelezen)`
            : 'niet herkend — vul de periode hieronder in'}
          .{' '}
          {voorstel.marge_pct !== null && (
            <>
              Marge <b>{voorstel.marge_pct}%</b> (in code berekend uit de rapport-totalen).{' '}
            </>
          )}
          Duplicaat- en plausibiliteitscontrole draaien mee in de harde checks hieronder.
        </div>
      </div>
      {nieuweCategorieen.length > 0 && (
        <div className="alertbanner">
          <div className="icon">⚠️</div>
          <div>
            <b>Nieuwe categorie{nieuweCategorieen.length === 1 ? '' : 'ën'} zonder mapping:</b>{' '}
            {nieuweCategorieen.map((r) => `‘${r.categorie}’`).join(', ')} — stel per categorie de omzet-GB,
            btw-code en kostprijs-GB in. De mapping wordt per administratie onthouden voor volgende rapporten;
            boeken is geblokkeerd tot elke categorie compleet is.
          </div>
        </div>
      )}
      {isVraagOpen && (
        <div className="alertbanner">
          <div className="icon">❓</div>
          <div>
            Er staat een open vraag op dit rapport — boeken is geblokkeerd tot de vraag beantwoord of
            ingetrokken is (zie <Link to={`/?administratie=${administratieId}&sectie=vragen&document=${documentId}`}>Vragen</Link>).
          </div>
        </div>
      )}

      <div className="review">
        <div className="docpane">
          <div className="panel">
            <div className="bijlage-inhoud">
              {!bijlageUrl && <p className="hint">Bijlage laden…</p>}
              {bijlageUrl && (
                <object data={metViewerOpties(bijlageUrl)} type="application/pdf">
                  <p className="hint">
                    PDF-weergave niet beschikbaar —{' '}
                    <a href={bijlageUrl} download={detail.bestandsnaam}>
                      download het rapport
                    </a>
                    .
                  </p>
                </object>
              )}
            </div>
          </div>
        </div>

        <div className="formpane">
          <div className="panel">
            <h2>
              Rapportperiode &amp; totalen{' '}
              <span className="chip geheugen">mapping onthouden per administratie</span>
            </h2>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
              <div>
                <label htmlFor="periode-start">Periode van</label>
                <DatePicker
                  id="periode-start"
                  value={periodeStart || null}
                  onChange={(v) => {
                    setPeriodeStart(v ?? '')
                    markeerGewijzigd()
                  }}
                  disabled={isGeboekt}
                />
              </div>
              <div>
                <label htmlFor="periode-eind">t/m</label>
                <DatePicker
                  id="periode-eind"
                  value={periodeEind || null}
                  onChange={(v) => {
                    setPeriodeEind(v ?? '')
                    markeerGewijzigd()
                  }}
                  disabled={isGeboekt}
                />
              </div>
              <div>
                <label htmlFor="totaal-omzet">Rapport-totaal omzet</label>
                <input
                  id="totaal-omzet"
                  value={totaalOmzet}
                  onChange={(e) => {
                    setTotaalOmzet(e.target.value)
                    markeerGewijzigd()
                  }}
                  disabled={isGeboekt}
                />
              </div>
              <div>
                <label htmlFor="totaal-kostprijs">Rapport-totaal kostprijs</label>
                <input
                  id="totaal-kostprijs"
                  value={totaalKostprijs}
                  onChange={(e) => {
                    setTotaalKostprijs(e.target.value)
                    markeerGewijzigd()
                  }}
                  disabled={isGeboekt}
                />
              </div>
            </div>
          </div>

          <div className="panel">
            <h2>Verkoopboeking (document 1 van 2)</h2>
            <table className="lines">
              <tbody>
                <tr>
                  <th>Categorie (rapport)</th>
                  <th>Omzet-GB (RLZ)</th>
                  <th>Btw</th>
                  <th className="amount">Omzet</th>
                </tr>
                {regels.map((regel, index) => (
                  <tr key={regel.categorie + index}>
                    <td>
                      {regel.categorie}
                      {regel.herkomst === 'nieuw' && (
                        <div>
                          <span className="chip vraag">nieuw — mapping instellen</span>
                        </div>
                      )}
                      {regel.herkomst === 'mapping' && (
                        <div>
                          <span className="chip geheugen">uit mapping</span>
                        </div>
                      )}
                    </td>
                    <td>
                      <SearchableCombobox
                        label={`Omzet-GB ${regel.categorie}`}
                        toonLabel={false}
                        opties={grootboek.opties}
                        waarde={regel.omzetLedgerId}
                        onWijzig={(id) => wijzigRegel(index, { omzetLedgerId: id })}
                        placeholder="Kies omzetrekening…"
                      />
                    </td>
                    <td>
                      <SearchableCombobox
                        label={`Btw-code ${regel.categorie}`}
                        toonLabel={false}
                        opties={btwCodes.opties}
                        waarde={regel.taxrateId}
                        onWijzig={(id) => wijzigRegel(index, { taxrateId: id })}
                        placeholder="Kies btw-code…"
                      />
                    </td>
                    <td className="amount">
                      <input
                        aria-label={`Omzetbedrag ${regel.categorie}`}
                        style={{ textAlign: 'right' }}
                        value={regel.omzetBedrag}
                        onChange={(e) => wijzigRegel(index, { omzetBedrag: e.target.value })}
                        disabled={isGeboekt}
                      />
                    </td>
                  </tr>
                ))}
                <tr>
                  <td colSpan={3}>
                    <b>Losse verkoopboeking — zonder debiteur</b>{' '}
                    <span className="hint" style={{ display: 'inline' }}>
                      — boekt in RLZ als &ldquo;Verkopen → Boekingen&rdquo; (geen dummy-debiteur)
                    </span>
                  </td>
                  <td className="amount">
                    <b>€ {formatBedrag(omzetTotaalRegels)}</b>
                  </td>
                </tr>
              </tbody>
            </table>
            <div className="hint">
              Kassabedragen zijn inclusief btw — de btw-splitsing per regel gebeurt deterministisch in de
              boekmotor op het percentage van de gekozen btw-code (vrijgesteld/0% = geen splitsing).
            </div>
          </div>

          {heeftKostprijs && (
            <div className="panel">
              <h2>Kostprijsboeking — memoriaal (document 2 van 2, gekoppeld)</h2>
              <table className="lines">
                <tbody>
                  <tr>
                    <th>Categorie</th>
                    <th>Kosten-GB (RLZ)</th>
                    <th className="amount">Debet</th>
                  </tr>
                  {regels.map((regel, index) =>
                    bedragAlsGetal(regel.kostprijsBedrag) ? (
                      <tr key={regel.categorie + index}>
                        <td>{regel.categorie}</td>
                        <td>
                          <SearchableCombobox
                            label={`Kostprijs-GB ${regel.categorie}`}
                            toonLabel={false}
                            opties={grootboek.opties}
                            waarde={regel.kostprijsLedgerId}
                            onWijzig={(id) => wijzigRegel(index, { kostprijsLedgerId: id })}
                            placeholder="Kies kostenrekening…"
                          />
                        </td>
                        <td className="amount">
                          <input
                            aria-label={`Kostprijsbedrag ${regel.categorie}`}
                            style={{ textAlign: 'right' }}
                            value={regel.kostprijsBedrag}
                            onChange={(e) => wijzigRegel(index, { kostprijsBedrag: e.target.value })}
                            disabled={isGeboekt}
                          />
                        </td>
                      </tr>
                    ) : null,
                  )}
                  <tr>
                    <td>
                      <b>aan Voorraad (tegenrekening)</b>
                    </td>
                    <td>
                      <SearchableCombobox
                        label="Voorraad-tegenrekening"
                        toonLabel={false}
                        opties={grootboek.opties}
                        waarde={voorraadLedgerId}
                        onWijzig={(id) => {
                          setVoorraadLedgerId(id)
                          markeerGewijzigd()
                        }}
                        placeholder="Kies voorraadrekening…"
                      />
                    </td>
                    <td className="amount">
                      <b>€ {formatBedrag(kostprijsTotaalRegels)} credit</b>
                    </td>
                  </tr>
                </tbody>
              </table>
              <div className="hint">
                Marge blijft per productgroep zichtbaar in RLZ (omzet én kostprijs per groep) en de voorraad
                loopt mee. Beide documenten krijgen het PDF-rapport als bijlage en worden als één logische
                transactie geboekt: faalt document 2, dan wordt document 1 teruggedraaid of zie je een
                zichtbare half-geboekt-foutstatus — nooit stil een halve boeking.
              </div>
            </div>
          )}

          <div className="panel">
            <h2>
              Harde checks{' '}
              {checksBezig ? (
                <span className="chip vraag">checks worden uitgevoerd…</span>
              ) : checkRapport !== null && checksActueel ? (
                <span className={`chip ${checkRapport.geblokkeerd ? 'blokkerend' : 'ok'}`}>
                  {checkRapport.geblokkeerd ? 'blokkerend' : 'alle checks groen'}
                </span>
              ) : (
                <span className="chip">automatisch</span>
              )}
            </h2>
            {checkRapport === null && !checksBezig && (
              <p className="hint">
                De harde checks draaien automatisch — bij het openen en na elke wijziging.
              </p>
            )}
            {checkRapport && (
              <>
                {!checksActueel && !checksBezig && (
                  <div className="hint" style={{ color: 'var(--orange)' }}>
                    Wijzigingen sinds de laatste controle — de checks draaien zo automatisch opnieuw.
                  </div>
                )}
                <table className="lines">
                  <tbody>
                    {checkRapport.resultaten.map((r) => (
                      <tr key={r.naam} style={!checksActueel ? { opacity: 0.55 } : undefined}>
                        <td>
                          <span className={`chip ${r.ok ? 'ok' : 'blokkerend'}`}>{r.ok ? 'OK' : 'Blokkerend'}</span>
                        </td>
                        <td>
                          <b>{r.naam}</b>
                        </td>
                        <td>{r.melding}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>

          <div className="panel">
            {opslaanFout && <div className="fout">{opslaanFout}</div>}
            {boekenFout && <div className="fout">{boekenFout}</div>}
            {boekResultaat && (
              <div className="hint" style={{ color: 'var(--green)' }}>
                Geboekt in RLZ — verkoopfactuur <b>{boekResultaat.verkoop_boekstuknummer ?? '—'}</b>
                {boekResultaat.memoriaal_boekstuknummer && (
                  <>
                    {' '}
                    + kostprijsmemoriaal <b>{boekResultaat.memoriaal_boekstuknummer}</b>
                  </>
                )}{' '}
                — de periode is geregistreerd en kan niet dubbel geboekt worden.
              </div>
            )}
            {isGeboekt && !boekResultaat && detail.geboekt_in_rlz && <GeboektInRlzRegel stand={detail.geboekt_in_rlz} />}
            {isGeboekt && !boekResultaat && (
              <p className="hint" style={{ marginTop: 0 }}>
                {detail.geboekt_in_rlz ? 'Wijzigen' : 'Deze omzetboeking is geboekt in RLZ. Wijzigen'} kan alleen via
                stornering in Reeleezee (actie 19) — de omzet-reconciliatie signaleert dat dan.
              </p>
            )}
            {!isGeboekt && (
              <div className="actions">
                <button
                  type="button"
                  className="btn secondary"
                  disabled={opslaanBezig || boekenBezig}
                  onClick={() => void opslaan()}
                >
                  {opslaanBezig ? 'Bezig…' : 'Opslaan'}
                </button>
                <button
                  type="button"
                  className="btn"
                  disabled={!isBoekbaar || !checksGroen || boekenBezig}
                  title={
                    !isBoekbaar
                      ? `Boeken kan niet vanuit status ${detail.status}`
                      : !checksGroen
                        ? 'De harde checks draaien automatisch — boeken kan zodra alle checks groen zijn'
                        : 'Verkoopboeking + kostprijsmemoriaal worden als één logische transactie geboekt'
                  }
                  onClick={() => void boeken()}
                >
                  {boekenBezig ? 'Bezig…' : 'Boeken in RLZ ✓'}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
      {popupChecks && (
        <ChecksPopup
          melding={popupChecks.melding}
          checks={popupChecks.checks}
          onSluiten={() => setPopupChecks(null)}
        />
      )}
    </div>
  )
}
