import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { SearchableCombobox } from '../document/SearchableCombobox'
import { useGrootboekOpties, useTaxrateOpties } from '../document/useSyncOpties'
import { useAdministraties } from '../werkvoorraad/useAdministraties'
import {
  boekDirect,
  haalAfletterOpdrachten,
  haalMutaties,
  haalRekeningen,
  synchroniseerBank,
  trekAfletterenIn,
  verifieerAfletteren,
  zetAfletterenKlaar,
  type AfletterHistorieRegelDto,
  type AfletterOpdrachtDto,
  type MutatieDto,
  type RekeningenDto,
  type VoorstelDto,
} from './bankApi'

function formatBedrag(bedrag: string | null): string {
  if (bedrag === null) return '—'
  const getal = Number(bedrag)
  return getal.toLocaleString('nl-NL', { style: 'currency', currency: 'EUR' })
}

function formatDatumKort(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('nl-NL', { day: '2-digit', month: '2-digit' })
}

function chipKlasse(voorstel: VoorstelDto): string {
  return voorstel.kleur === 'groen' ? 'chip geheugen' : 'chip ai'
}

function formatTijdstip(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('nl-NL', { dateStyle: 'short', timeStyle: 'short' })
}

/** Levenscyclus-chip van een afletter-opdracht (kliktest 2026-08-08): klaargezet → wacht op
 * verificatie → geverifieerd / afwijkend gevolgd; ingetrokken blijft zichtbaar in de historie. */
function AfletterStatusChip({ opdracht }: { opdracht: AfletterOpdrachtDto }) {
  if (opdracht.status === 'geverifieerd') {
    return opdracht.voorstel_gevolgd === false ? (
      <span className="chip ai">Afwijkend gevolgd — in RLZ anders gekoppeld dan het voorstel</span>
    ) : (
      <span className="chip geheugen">Geverifieerd — afgeletterd in RLZ (open bedrag 0)</span>
    )
  }
  if (opdracht.status === 'ingetrokken') {
    return <span className="chip">Ingetrokken</span>
  }
  return opdracht.laatste_verificatie_poging_op ? (
    <span className="chip vraag">
      Wacht op verificatie — laatst gecontroleerd {formatTijdstip(opdracht.laatste_verificatie_poging_op)}, nog
      open in RLZ
    </span>
  ) : (
    <span className="chip vraag">Klaargezet — nog niet geverifieerd</span>
  )
}

/** Handmatig-boeken-formulier per mutatie (voorstel-volgorde stap 5, of correctie op een
 * regel-voorstel): GB-combobox + btw-code, bedrag = het volledige mutatiebedrag (splitsen in
 * meerdere regels blijft backend-mogelijk maar is geen v1-scherm-functie). Btw-splitsing doet
 * de backend — code rekent, dit formulier stuurt alleen keuzes. */
function HandmatigBoekenForm({
  administratieId,
  mutatie,
  onGeboekt,
  onAnnuleer,
}: {
  administratieId: string
  mutatie: MutatieDto
  onGeboekt: () => void
  onAnnuleer: () => void
}) {
  const grootboek = useGrootboekOpties(administratieId)
  const btwCodes = useTaxrateOpties(administratieId)
  const [ledgerId, setLedgerId] = useState<string | null>(null)
  const [taxrateId, setTaxrateId] = useState<string | null>(null)
  const [omschrijving, setOmschrijving] = useState(mutatie.omschrijving ?? '')
  const [regelOpslaan, setRegelOpslaan] = useState(false)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const boek = async () => {
    if (!ledgerId || mutatie.bedrag === null) return
    setBezig(true)
    setFout(null)
    try {
      // Bedragsplitsing (btw uit inclusief bedrag) gebeurt deterministisch in de backend voor
      // vaste regels; voor het handmatige formulier sturen we netto = volledig bedrag zonder
      // btw-splitsing, tenzij een btw-code is gekozen — dan rekent de client dezelfde formule
      // die de backend hard controleert (som regels = mutatiebedrag).
      const percentage = btwCodes.opties.find((o) => o.id === taxrateId)?.percentage
      let netto = mutatie.bedrag
      let btw: string | null = null
      if (taxrateId && percentage) {
        const bedragGetal = Number(mutatie.bedrag)
        const nettoGetal = Math.round((bedragGetal / (1 + percentage)) * 100) / 100
        netto = nettoGetal.toFixed(2)
        btw = (Math.round((bedragGetal - nettoGetal) * 100) / 100).toFixed(2)
      }
      await boekDirect(administratieId, mutatie.id, {
        regels: [
          {
            ledger_id: ledgerId,
            netto_bedrag: netto,
            btw_bedrag: btw,
            taxrate_id: taxrateId,
            project_id: null,
            omschrijving: omschrijving || null,
          },
        ],
        omschrijving: omschrijving || null,
        bron: 'handmatig',
        vaste_regel_opslaan: regelOpslaan,
      })
      onGeboekt()
    } catch (err) {
      setFout(err instanceof Error ? err.message : 'Boeken mislukt')
    } finally {
      setBezig(false)
    }
  }

  return (
    <div style={{ display: 'grid', gap: 8, padding: '8px 0' }}>
      <SearchableCombobox
        label="Grootboekrekening"
        opties={grootboek.opties}
        waarde={ledgerId}
        onWijzig={setLedgerId}
        placeholder="Zoek grootboekrekening…"
        vereist
      />
      <SearchableCombobox
        label="Btw-code"
        opties={btwCodes.opties}
        waarde={taxrateId}
        onWijzig={setTaxrateId}
        placeholder="Geen btw"
      />
      <label>
        Omschrijving
        <input value={omschrijving} onChange={(e) => setOmschrijving(e.target.value)} />
      </label>
      <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 13 }}>
        <input
          type="checkbox"
          style={{ width: 'auto' }}
          checked={regelOpslaan}
          onChange={(e) => setRegelOpslaan(e.target.checked)}
        />
        Onthoud als vaste regel voor {mutatie.tegenpartij_naam ?? 'deze tegenpartij'}
      </label>
      {fout && <p className="hint" style={{ color: 'var(--red)' }}>{fout}</p>}
      <div className="actions">
        <button className="btn green" onClick={() => void boek()} disabled={!ledgerId || bezig}>
          {bezig ? 'Boeken…' : 'Boeken in RLZ ✓'}
        </button>
        <button className="btn secondary" onClick={onAnnuleer} disabled={bezig}>
          Annuleren
        </button>
      </div>
    </div>
  )
}

function MutatieRij({
  administratieId,
  mutatie,
  onVerversen,
}: {
  administratieId: string
  mutatie: MutatieDto
  onVerversen: () => void
}) {
  const [actieFout, setActieFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const [handmatigOpen, setHandmatigOpen] = useState(false)

  const voorstel = mutatie.voorstel
  const opdracht = mutatie.afletter_opdracht

  const doe = async (actie: () => Promise<unknown>) => {
    setBezig(true)
    setActieFout(null)
    try {
      await actie()
      onVerversen()
    } catch (err) {
      setActieFout(err instanceof Error ? err.message : 'Actie mislukt')
    } finally {
      setBezig(false)
    }
  }

  const isAfletterVoorstel =
    (voorstel.soort === 'exacte_match' || voorstel.soort === 'deel_match' || voorstel.soort === 'rlz_voorstel') &&
    voorstel.payment_item_id !== null

  const bedragGetal = mutatie.bedrag !== null ? Number(mutatie.bedrag) : 0

  return (
    <tr style={opdracht ? { opacity: 0.75 } : undefined}>
      <td>{formatDatumKort(mutatie.boekdatum)}</td>
      <td>
        <b>{mutatie.tegenpartij_naam ?? 'Onbekende tegenpartij'}</b>
        {mutatie.omschrijving ? ` · ${mutatie.omschrijving}` : ''}
      </td>
      <td className="amount" style={{ color: bedragGetal < 0 ? 'var(--red)' : 'var(--green)' }}>
        {formatBedrag(mutatie.bedrag)}
      </td>
      <td>
        {isAfletterVoorstel ? (
          <>
            Afletteren op {voorstel.open_post?.referentie ?? 'open post'}
            {voorstel.open_post?.bedrag ? ` (${formatBedrag(voorstel.open_post.bedrag)})` : ''}
          </>
        ) : voorstel.soort === 'vaste_regel' ? (
          <>Direct op grootboek volgens vaste regel</>
        ) : (
          <>{voorstel.reden}</>
        )}
        {mutatie.regel_voorstel && (
          <div className="hint">
            Al {mutatie.regel_voorstel.aantal_boekingen}× zo geboekt — vink bij het boeken “onthoud als vaste
            regel” aan.
          </div>
        )}
      </td>
      <td>
        <span className={chipKlasse(voorstel)}>{voorstel.bron}</span>
      </td>
      <td>
        {opdracht ? (
          <>
            <AfletterStatusChip opdracht={opdracht} />{' '}
            <button
              className="btn secondary"
              disabled={bezig}
              onClick={() => void doe(() => trekAfletterenIn(administratieId, opdracht.id))}
            >
              Intrekken
            </button>
            <p className="hint" style={{ marginTop: 4 }}>
              Klaargezet — leg de koppeling in Reeleezee (RLZ toont daar meestal zelf de matchsuggestie); de
              eerstvolgende bank-sync verifieert automatisch, of gebruik “Nu verifiëren” hieronder.
            </p>
          </>
        ) : isAfletterVoorstel ? (
          <button
            className="btn green"
            disabled={bezig}
            onClick={() =>
              void doe(() => zetAfletterenKlaar(administratieId, mutatie.id, voorstel.payment_item_id ?? ''))
            }
          >
            Klaarzetten voor RLZ ✓
          </button>
        ) : voorstel.soort === 'vaste_regel' && voorstel.regels.length > 0 ? (
          <button
            className="btn green"
            disabled={bezig}
            onClick={() =>
              void doe(() =>
                boekDirect(administratieId, mutatie.id, {
                  regels: voorstel.regels.map((regel) => ({
                    ledger_id: regel.ledger_id,
                    netto_bedrag: regel.netto_bedrag,
                    btw_bedrag: regel.btw_bedrag,
                    taxrate_id: regel.taxrate_id,
                    project_id: regel.project_id,
                    omschrijving: regel.omschrijving,
                  })),
                  omschrijving: voorstel.regels[0]?.omschrijving ?? null,
                  bron: 'vaste_regel',
                  vaste_regel_opslaan: false,
                }),
              )
            }
          >
            Akkoord ✓
          </button>
        ) : handmatigOpen ? (
          <HandmatigBoekenForm
            administratieId={administratieId}
            mutatie={mutatie}
            onGeboekt={() => {
              setHandmatigOpen(false)
              onVerversen()
            }}
            onAnnuleer={() => setHandmatigOpen(false)}
          />
        ) : (
          <button className="btn" disabled={bezig} onClick={() => setHandmatigOpen(true)}>
            Boeken…
          </button>
        )}
        {actieFout && (
          <p className="hint" style={{ color: 'var(--red)' }}>
            {actieFout}
          </p>
        )}
      </td>
    </tr>
  )
}

/** Bankdetail per klant (mockup #bankdetail): bankpicker over alle PaymentAccounts incl. kas,
 * saldo + versheid, mutatielijst met voorstel + herkomst-chip. Afletteren-tegen-open-post is het
 * assist-model ("klaarzetten voor RLZ", verificatie via sync); direct-op-grootboek boekt echt.
 * Afletteren gaat NIET door de klant-accorderingsflow. */
export function BankDetailScreen() {
  const { administratieId } = useParams<{ administratieId: string }>()
  const { administraties } = useAdministraties()
  const [searchParams, setSearchParams] = useSearchParams()
  const rekeningId = searchParams.get('rekening')

  const [rekeningen, setRekeningen] = useState<RekeningenDto | null>(null)
  const [mutaties, setMutaties] = useState<MutatieDto[] | null>(null)
  const [afletterHistorie, setAfletterHistorie] = useState<AfletterHistorieRegelDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [syncBezig, setSyncBezig] = useState(false)
  const [syncMelding, setSyncMelding] = useState<string | null>(null)
  const [verifieerBezig, setVerifieerBezig] = useState(false)

  const klantNaam = useMemo(
    () => administraties?.find((a) => a.id === administratieId)?.naam ?? '…',
    [administraties, administratieId],
  )

  const laadRekeningen = useCallback(() => {
    if (!administratieId) return
    haalRekeningen(administratieId)
      .then(setRekeningen)
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Onbekende fout'))
  }, [administratieId])

  useEffect(laadRekeningen, [laadRekeningen])

  useEffect(() => {
    if (!rekeningId && rekeningen && rekeningen.rekeningen.length > 0) {
      // Default: de rekening met de meeste open mutaties (mockup: je landt waar het werk ligt).
      const drukste = [...rekeningen.rekeningen].sort((a, b) => b.open_mutaties - a.open_mutaties)[0]
      setSearchParams({ rekening: drukste.id }, { replace: true })
    }
  }, [rekeningId, rekeningen, setSearchParams])

  const laadMutaties = useCallback(() => {
    if (!administratieId || !rekeningId) return
    haalMutaties(administratieId, rekeningId)
      .then((data) => setMutaties(data.mutaties))
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Onbekende fout'))
    haalAfletterOpdrachten(administratieId, rekeningId)
      .then((data) => setAfletterHistorie(data.opdrachten))
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Onbekende fout'))
  }, [administratieId, rekeningId])

  useEffect(() => {
    setMutaties(null)
    setAfletterHistorie(null)
    laadMutaties()
  }, [laadMutaties])

  const verversAlles = useCallback(() => {
    laadRekeningen()
    laadMutaties()
  }, [laadRekeningen, laadMutaties])

  const verifieerNu = async () => {
    if (!administratieId || !rekeningId) return
    setVerifieerBezig(true)
    setSyncMelding(null)
    try {
      const resultaat = await verifieerAfletteren(administratieId, rekeningId)
      setSyncMelding(
        resultaat.geverifieerd > 0
          ? `Verificatie gedraaid: ${resultaat.geverifieerd} aflettering(en) geverifieerd.`
          : 'Verificatie gedraaid: nog geen aflettering afgerond in Reeleezee — de opdracht(en) blijven wachten.',
      )
      verversAlles()
    } catch (err) {
      setSyncMelding(err instanceof Error ? err.message : 'Verificatie mislukt')
    } finally {
      setVerifieerBezig(false)
    }
  }

  const sync = async () => {
    if (!administratieId) return
    setSyncBezig(true)
    setSyncMelding(null)
    try {
      const resultaat = await synchroniseerBank(administratieId)
      const delen = [
        `${resultaat.mutaties_nieuw} nieuwe mutaties`,
        `${resultaat.afletteren_geverifieerd} aflettering(en) geverifieerd`,
      ]
      if (resultaat.automatisch_geboekt > 0) delen.push(`${resultaat.automatisch_geboekt} automatisch geboekt`)
      if (resultaat.automatisch_fouten.length > 0) delen.push(`${resultaat.automatisch_fouten.length} autoboek-fout(en)`)
      setSyncMelding(`Gesynchroniseerd: ${delen.join(', ')}.`)
      verversAlles()
    } catch (err) {
      setSyncMelding(err instanceof Error ? err.message : 'Synchronisatie mislukt')
    } finally {
      setSyncBezig(false)
    }
  }

  if (!administratieId) return null

  const huidigeRekening = rekeningen?.rekeningen.find((r) => r.id === rekeningId) ?? null
  const totaalOpen = rekeningen?.rekeningen.reduce((som, r) => som + r.open_mutaties, 0) ?? 0
  const aantalVoorstel =
    mutaties?.filter((m) => m.voorstel.soort !== 'handmatig' || m.afletter_opdracht !== null).length ?? 0
  const aantalHandmatig =
    mutaties?.filter((m) => m.voorstel.soort === 'handmatig' && m.afletter_opdracht === null).length ?? 0

  return (
    <>
      <div className="topbar">
        <h1>
          <Link to="/bank" style={{ color: 'var(--accent)' }}>
            ← Bank
          </Link>{' '}
          <span style={{ color: 'var(--muted)', fontWeight: 400 }}>/</span> {klantNaam}
        </h1>
        <div className="bankpicker">
          <span className="bp-icon">🏦</span>
          <div>
            <label htmlFor="bank-rekening-select">Rekening</label>
            <select
              id="bank-rekening-select"
              value={rekeningId ?? ''}
              onChange={(e) => setSearchParams({ rekening: e.target.value })}
            >
              {(rekeningen?.rekeningen ?? []).map((rekening) => (
                <option key={rekening.id} value={rekening.id}>
                  {rekening.naam ?? 'Rekening'}
                  {rekening.iban ? ` · ${rekening.iban}` : ''} — {rekening.open_mutaties} open
                </option>
              ))}
            </select>
          </div>
          {huidigeRekening && (
            <span className="bp-saldo">
              Saldo {formatBedrag(huidigeRekening.saldo)} · <b>{totaalOpen} onverwerkt</b>
            </span>
          )}
        </div>
      </div>

      {fout && (
        <div className="panel">
          <p className="hint" style={{ color: 'var(--red)' }}>
            {fout}
          </p>
        </div>
      )}

      {rekeningen && !rekeningen.ooit_gesynchroniseerd && (
        <div className="panel">
          <p className="hint">
            Deze administratie is nog nooit met Reeleezee gesynchroniseerd voor bank — start hieronder de eerste
            synchronisatie.
          </p>
        </div>
      )}

      {huidigeRekening?.probe_fout && (
        <div className="panel">
          <p className="hint" style={{ color: 'var(--orange)' }}>
            ⚠️ De versheid van de bankaanlevering op deze rekening kon niet worden opgehaald (probe mislukt) —
            de getoonde importdatum kan verouderd zijn. De synchronisatie zelf is gewoon doorgegaan; probeer het
            later opnieuw met “Verversen uit Reeleezee”.
          </p>
        </div>
      )}

      {rekeningen && rekeningen.ooit_gesynchroniseerd && !rekeningen.heeft_bankaanlevering && (
        <div className="panel">
          <p className="hint">
            ⚠️ Geen bankaanlevering gevonden voor deze administratie: geen van de bankrekeningen heeft een
            bankimport of actieve bankkoppeling in Reeleezee. Richt eerst de bankaanlevering in Reeleezee in
            (MT940/CAMT-import of bankkoppeling) — tot die tijd valt hier niets te lezen.
          </p>
        </div>
      )}

      <div className="cards">
        <div className="card">
          <div className="num">{totaalOpen}</div>
          <div className="lbl">
            Onverwerkte mutaties{huidigeRekening ? ` (deze rekening: ${huidigeRekening.open_mutaties})` : ''}
          </div>
        </div>
        <div className="card">
          <div className="num">{aantalVoorstel}</div>
          <div className="lbl">Automatisch voorstel (match of regel herkend)</div>
        </div>
        <div className="card">
          <div className="num">{aantalHandmatig}</div>
          <div className="lbl">Handmatig beoordelen</div>
        </div>
      </div>

      <div className="panel">
        <h2>Onverwerkte bankmutaties</h2>
        <div className="actions" style={{ marginBottom: 8 }}>
          <button className="btn secondary" onClick={() => void sync()} disabled={syncBezig || verifieerBezig}>
            {syncBezig ? 'Synchroniseren…' : '⟳ Verversen uit Reeleezee'}
          </button>
          <button
            className="btn secondary"
            onClick={() => void verifieerNu()}
            disabled={syncBezig || verifieerBezig}
            title="Controleert alleen de klaargezette afletter-opdrachten van deze rekening bij Reeleezee (geen volledige synchronisatie)"
          >
            {verifieerBezig ? 'Verifiëren…' : '✓ Nu verifiëren'}
          </button>
          {rekeningen?.laatste_sync_op && (
            <span className="hint">
              laatste sync {new Date(rekeningen.laatste_sync_op).toLocaleString('nl-NL', { dateStyle: 'medium', timeStyle: 'short' })}
            </span>
          )}
        </div>
        {syncMelding && <p className="hint">{syncMelding}</p>}
        {mutaties === null ? (
          <p className="hint">Laden…</p>
        ) : mutaties.length === 0 ? (
          <p className="hint">Geen onverwerkte mutaties op deze rekening.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Datum</th>
                <th>Tegenpartij / omschrijving</th>
                <th className="amount">Bedrag</th>
                <th>Voorstel</th>
                <th>Bron voorstel</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {mutaties.map((mutatie) => (
                <MutatieRij
                  key={mutatie.id}
                  administratieId={administratieId}
                  mutatie={mutatie}
                  onVerversen={verversAlles}
                />
              ))}
            </tbody>
          </table>
        )}
        <div className="hint">
          Volgorde: 1) <b>exacte match</b> (referentie + bedrag) en 2) gedeeltelijke match → voorstel{' '}
          <b>klaarzetten</b>: de koppeling zelf leg je in Reeleezee (de app verifieert daarna automatisch op het
          open bedrag — afletteren via de API is nog dicht, supportvraag loopt); 3) vaste regel uit het geheugen en
          5) handmatig → <b>direct op grootboek</b> geboekt vanuit de app; 4) Reeleezee's eigen voorstel wordt
          getoond mét bron. Na 3× dezelfde handmatige boeking stelt de app een vaste regel voor. Afletteren gaat
          niet door de klant-accorderingsflow.
        </div>
      </div>

      {afletterHistorie !== null && afletterHistorie.length > 0 && (
        <div className="panel">
          <h2>Afletteren via Reeleezee — levenscyclus</h2>
          <table>
            <thead>
              <tr>
                <th>Datum</th>
                <th>Tegenpartij</th>
                <th className="amount">Bedrag</th>
                <th>Status</th>
                <th>Tijdlijn / resultaat</th>
              </tr>
            </thead>
            <tbody>
              {afletterHistorie.map((regel) => (
                <tr key={regel.opdracht.id}>
                  <td>{formatDatumKort(regel.boekdatum)}</td>
                  <td>{regel.tegenpartij_naam ?? 'Onbekende tegenpartij'}</td>
                  <td className="amount">{formatBedrag(regel.bedrag)}</td>
                  <td>
                    <AfletterStatusChip opdracht={regel.opdracht} />
                  </td>
                  <td>
                    <div className="hint">
                      Klaargezet {formatTijdstip(regel.opdracht.klaargezet_op)}
                      {regel.opdracht.geverifieerd_op &&
                        ` → geverifieerd ${formatTijdstip(regel.opdracht.geverifieerd_op)}`}
                      {!regel.opdracht.geverifieerd_op &&
                        regel.opdracht.laatste_verificatie_poging_op &&
                        ` → laatst gecontroleerd ${formatTijdstip(regel.opdracht.laatste_verificatie_poging_op)} (nog open)`}
                    </div>
                    {regel.opdracht.koppelingen.length > 0 && (
                      <div className="hint">
                        Afgeletterd tegen:{' '}
                        {regel.opdracht.koppelingen
                          .map((k) => `${k.boekstuknummer ?? k.rlz_document_id ?? '?'}${k.bedrag ? ` (${formatBedrag(k.bedrag)})` : ''}`)
                          .join(', ')}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="hint">
            Klaargezette opdrachten worden bij elke bank-sync (en met “Nu verifiëren”) tegen Reeleezee
            gecontroleerd; geverifieerd = het open bedrag in RLZ is 0. “Afwijkend gevolgd” betekent: in RLZ is
            tegen iets anders afgeletterd dan het voorstel — zichtbaar, nooit stil.
          </div>
        </div>
      )}
    </>
  )
}
