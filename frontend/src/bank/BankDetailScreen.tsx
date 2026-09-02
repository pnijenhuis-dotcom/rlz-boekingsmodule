import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { SearchableCombobox } from '../document/SearchableCombobox'
import { AnkerPopup, Checkbox, Select, SkeletonRegels, useToastOptioneel } from '../ui/basis'
import { useGrootboekOpties, useTaxrateOpties } from '../document/useSyncOpties'
import { useAdministraties } from '../werkvoorraad/useAdministraties'
import {
  boekDirect,
  haalAfletterOpdrachten,
  haalMutaties,
  haalRekeningen,
  trekAfletterenIn,
  voerAfletterOpdrachtUit,
  zetAfletterenKlaar,
  type AfletterActieResultaatDto,
  type AfletterHistorieRegelDto,
  type AfletterOpdrachtDto,
  type BankSyncRunDto,
  type MutatieDto,
  type RekeningenDto,
  type SplitsingDto,
  type VoorstelDto,
} from './bankApi'
import { AanbetalingenPaneel, KoppelRelatieForm } from './RelatieKoppeling'
import { SplitsenForm, SplitsingWeergave, SplitsingenPaneel } from './Splitsen'
import { useBankAutoVerversing } from './useBankAutoVerversing'
import { GEEN_MATCH_TEKST, HandmatigChip, VoorstelKaart, isDeelbetaling } from './VoorstelKaart'
import { amountKlasse } from '../werkvoorraad/format'

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

/** "laatst ververst"-hint (auto-verversing 25-08): vandaag → HH:MM, anders dd-mm HH:MM. */
export function formatVerversTijd(iso: string | null, nu: Date = new Date()): string {
  if (!iso) return 'nog nooit ververst'
  const d = new Date(iso)
  const tijd = d.toLocaleTimeString('nl-NL', { hour: '2-digit', minute: '2-digit' })
  const vandaag =
    d.getFullYear() === nu.getFullYear() && d.getMonth() === nu.getMonth() && d.getDate() === nu.getDate()
  if (vandaag) return `laatst ververst ${tijd}`
  return `laatst ververst ${d.toLocaleDateString('nl-NL', { day: '2-digit', month: '2-digit' })} ${tijd}`
}

/** Eénregelige samenvatting van een afgeronde achtergrondronde. */
function syncRunSamenvatting(run: BankSyncRunDto): string {
  const r = run.resultaat
  if (!r) return 'Ververst uit Reeleezee.'
  const delen = [`${r.mutaties_nieuw} nieuwe mutaties`, `${r.mutaties_bijgewerkt} bijgewerkt`]
  if (r.automatisch_afgeletterd > 0) delen.push(`${r.automatisch_afgeletterd} automatisch afgeletterd`)
  if (r.automatisch_geboekt > 0) delen.push(`${r.automatisch_geboekt} automatisch geboekt`)
  if (r.fouten.length > 0) delen.push(`${r.fouten.length} fout(en)`)
  // Blok E3 (01/02-09): de verificatie van wachtende terugval-afletteropdrachten lift in élke ronde
  // mee — alleen melden als er écht iets wachtte.
  const wachtend = r.afletteren_wachtend ?? 0
  let verificatie = ''
  if (wachtend > 0) {
    const nogOpen = wachtend - r.afletteren_geverifieerd
    verificatie =
      r.afletteren_geverifieerd > 0
        ? ` — ${r.afletteren_geverifieerd} aflettering(en) geverifieerd${nogOpen > 0 ? `, ${nogOpen} wacht${nogOpen === 1 ? '' : 'en'} nog in Reeleezee` : ''}`
        : ` — ${wachtend} afletteropdracht${wachtend === 1 ? '' : 'en'} wacht${wachtend === 1 ? '' : 'en'} nog in Reeleezee`
  }
  return `⟳ Ververst: ${delen.join(' · ')}${verificatie}`
}

/** Levenscyclus-chip van een afletter-opdracht (kliktest 2026-08-08): klaargezet → wacht op
 * verificatie → geverifieerd / afwijkend gevolgd; ingetrokken blijft zichtbaar in de historie.
 * Sinds afletteren-via-de-API (2026-08-09) is "klaargezet" de fallback-staat ná een API-fout. */
function AfletterStatusChip({ opdracht }: { opdracht: AfletterOpdrachtDto }) {
  if (opdracht.status === 'geverifieerd') {
    if (opdracht.voorstel_gevolgd === false) {
      return <span className="chip ai">Afwijkend gevolgd — in RLZ anders gekoppeld dan het voorstel</span>
    }
    if (opdracht.uitvoering === 'al_afgeletterd_in_rlz') {
      return <span className="chip geheugen">Geverifieerd — al afgeletterd in RLZ</span>
    }
    return <span className="chip geheugen">Geverifieerd — afgeletterd in RLZ (open bedrag 0)</span>
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
    <span className="chip vraag">Klaargezet — nog niet gekoppeld</span>
  )
}

/** Eén melding voor de afletter-uitkomsten: succes = koppeling direct via de API gelegd én
 * geverifieerd; al afgeletterd = de vooraf-toets zag de mutatie al dicht in RLZ (kliktest
 * 2026-08-09, geen fout); fallback = opdracht staat klaar, fout zichtbaar (nooit stil). */
function afletterUitkomstMelding(resultaat: AfletterActieResultaatDto): { tekst: string; isFout: boolean } {
  if (resultaat.uitkomst === 'afgeletterd_via_api') {
    return { tekst: 'Afgeletterd — koppeling direct in Reeleezee gelegd en geverifieerd.', isFout: false }
  }
  if (resultaat.uitkomst === 'al_afgeletterd_in_rlz') {
    return {
      tekst: 'Al afgeletterd in Reeleezee — de opdracht is als geverifieerd gemarkeerd, er was geen nieuwe koppeling nodig.',
      isFout: false,
    }
  }
  return {
    tekst:
      `De API-koppeling is niet gelukt${resultaat.fout ? ` (${resultaat.fout})` : ''} — de opdracht staat ` +
      'klaar; probeer “Nu afletteren” opnieuw of leg de koppeling in Reeleezee, de eerstvolgende sync verifieert.',
    isFout: true,
  }
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
        <Checkbox checked={regelOpslaan} onChange={(e) => setRegelOpslaan(e.target.checked)} />
        Onthoud als vaste regel voor {mutatie.tegenpartij_naam ?? 'deze tegenpartij'}
      </label>
      {fout && <p className="hint" style={{ color: 'var(--red)' }}>{fout}</p>}
      <div className="actions">
        <button className="btn" onClick={() => void boek()} disabled={!ledgerId || bezig}>
          {bezig ? 'Boeken…' : 'Boeken in RLZ ✓'}
        </button>
        <button className="btn secondary" onClick={onAnnuleer} disabled={bezig}>
          Annuleren
        </button>
      </div>
    </div>
  )
}

/** Drie verwerkroutes per mutatie (25-08, deel 4): direct-op-grootboek ("Boeken…"), relatie-
 * koppeling ("Koppel aan relatie…") en splitsen ("Splitsen…") — één inline formulier tegelijk. */
type ActieModus = 'handmatig' | 'relatie' | 'splitsen' | null

function MutatieRij({
  administratieId,
  mutatie,
  onVerversen,
  onMelding,
  onGesplitst,
}: {
  administratieId: string
  mutatie: MutatieDto
  onVerversen: () => void
  onMelding: (tekst: string) => void
  onGesplitst: (splitsing: SplitsingDto) => void
}) {
  const [actieFout, setActieFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const [actieModus, setActieModus] = useState<ActieModus>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const menuKnop = useRef<HTMLButtonElement | null>(null)

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

  /** Afletteren via de echte API (klaarzetten of "Nu afletteren" op een bestaande opdracht):
   * succes → melding op schermniveau (de rij verdwijnt na verversen); fallback → fout in de rij,
   * de opdracht blijft klaarstaan. */
  const letterAf = async (actie: () => Promise<AfletterActieResultaatDto>) => {
    setBezig(true)
    setActieFout(null)
    try {
      const melding = afletterUitkomstMelding(await actie())
      if (melding.isFout) {
        setActieFout(melding.tekst)
      } else {
        onMelding(melding.tekst)
      }
      onVerversen()
    } catch (err) {
      setActieFout(err instanceof Error ? err.message : 'Afletteren mislukt')
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
        <div className="bank-tp">{mutatie.tegenpartij_naam ?? 'Onbekende tegenpartij'}</div>
        {mutatie.omschrijving && <div className="bank-oms">{mutatie.omschrijving}</div>}
      </td>
      <td className="amount" style={{ color: bedragGetal < 0 ? 'var(--red)' : 'var(--green)' }}>
        {formatBedrag(mutatie.bedrag)}
      </td>
      <td>
        {/* Blok E5–E8 (mockup bank-voorstel-kaart.html): kaart mét doel-post-specs + match-chip; vaste regel =
            eigen regel mét herkomst-chip; geen match = rustige tekstregel (geen lege kaart). */}
        {isAfletterVoorstel ? (
          <VoorstelKaart voorstel={voorstel} mutatieBedrag={mutatie.bedrag} />
        ) : voorstel.soort === 'vaste_regel' ? (
          <span className={chipKlasse(voorstel)} title="Direct op grootboek volgens een vaste regel (boekingsgeheugen)">
            vaste regel · {voorstel.bron}
          </span>
        ) : (
          <HandmatigChip />
        )}
        {mutatie.regel_voorstel && (
          <div className="hint">
            Al {mutatie.regel_voorstel.aantal_boekingen}× zo geboekt — vink bij het boeken “onthoud als vaste
            regel” aan.
          </div>
        )}
      </td>
      <td>
        {/* Iteratie 2 (mockup bank-voorstel-kaart ⑥, akkoord Peter 02-09): één primaire knop
            (context-afhankelijk) + een ⋯-menu voor de overige routes — nooit meer drie gestapelde
            knoppen per rij. */}
        {actieModus === 'handmatig' ? (
          <HandmatigBoekenForm
            administratieId={administratieId}
            mutatie={mutatie}
            onGeboekt={() => {
              setActieModus(null)
              onVerversen()
            }}
            onAnnuleer={() => setActieModus(null)}
          />
        ) : actieModus === null ? (
          <div className="acties-rij">
            {opdracht ? (
              <>
                <AfletterStatusChip opdracht={opdracht} />
                {opdracht.status === 'klaargezet' && (
                  <button
                    className="btn"
                    disabled={bezig}
                    onClick={() => void letterAf(() => voerAfletterOpdrachtUit(administratieId, opdracht.id))}
                  >
                    Nu afletteren ✓
                  </button>
                )}
              </>
            ) : isAfletterVoorstel ? (
              <button
                className="btn"
                disabled={bezig}
                onClick={() =>
                  void letterAf(() => zetAfletterenKlaar(administratieId, mutatie.id, voorstel.payment_item_id ?? ''))
                }
              >
                {isDeelbetaling(mutatie.bedrag, voorstel.open_post?.bedrag) ? 'Afletteren (deel) ✓' : 'Afletteren ✓'}
              </button>
            ) : voorstel.soort === 'vaste_regel' && voorstel.regels.length > 0 ? (
              <button
                className="btn"
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
            ) : (
              <button className="btn" disabled={bezig} onClick={() => setActieModus('handmatig')}>
                Boeken…
              </button>
            )}
            <button
              ref={menuKnop}
              type="button"
              className="btn secondary meer"
              aria-label="Meer acties"
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              disabled={bezig}
              title="Meer acties: koppelen aan relatie, splitsen, handmatig boeken"
              onClick={() => setMenuOpen((o) => !o)}
            >
              ⋯
            </button>
            <AnkerPopup
              open={menuOpen}
              anker={menuKnop}
              kant="onder"
              uitlijning="eind"
              className="rijmenu"
              role="menu"
              onAnkerUitBeeld={() => setMenuOpen(false)}
            >
              {opdracht ? (
                <button
                  type="button"
                  className="linkbtn"
                  role="menuitem"
                  onClick={() => {
                    setMenuOpen(false)
                    void doe(() => trekAfletterenIn(administratieId, opdracht.id))
                  }}
                >
                  Intrekken
                </button>
              ) : (
                <>
                  {/* Tweede en derde verwerkroute — beschikbaar op elke nog niet klaargezette mutatie,
                      ook naast een afletter-/regelvoorstel (bv. deelmatch → splitsen in open post + rest). */}
                  <button
                    type="button"
                    className="linkbtn"
                    role="menuitem"
                    onClick={() => {
                      setMenuOpen(false)
                      setActieModus('relatie')
                    }}
                  >
                    Koppel aan relatie…
                  </button>
                  <button
                    type="button"
                    className="linkbtn"
                    role="menuitem"
                    onClick={() => {
                      setMenuOpen(false)
                      setActieModus('splitsen')
                    }}
                  >
                    Splitsen…
                  </button>
                  {(isAfletterVoorstel || voorstel.soort === 'vaste_regel') && (
                    <button
                      type="button"
                      className="linkbtn"
                      role="menuitem"
                      onClick={() => {
                        setMenuOpen(false)
                        setActieModus('handmatig')
                      }}
                    >
                      Boeken handmatig…
                    </button>
                  )}
                </>
              )}
            </AnkerPopup>
          </div>
        ) : null}
        {actieModus === 'relatie' && (
          <KoppelRelatieForm
            administratieId={administratieId}
            mutatie={mutatie}
            onGekoppeld={(melding) => {
              setActieModus(null)
              onMelding(melding)
              onVerversen()
            }}
            onAnnuleer={() => setActieModus(null)}
          />
        )}
        {actieModus === 'splitsen' && (
          <SplitsenForm
            administratieId={administratieId}
            mutatie={mutatie}
            onGesplitst={(splitsing) => {
              setActieModus(null)
              onGesplitst(splitsing)
              onVerversen()
            }}
            onAnnuleer={() => setActieModus(null)}
          />
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
 * saldo + versheid, mutatielijst met voorstel + herkomst-chip. Afletteren-tegen-open-post gaat
 * sinds 2026-08-09 via de echte API (koppeling direct gelegd + geverifieerd); faalt de API, dan
 * blijft de opdracht klaarstaan ("Nu afletteren" / mens in RLZ, sync verifieert — fallback).
 * Direct-op-grootboek boekt echt. Afletteren gaat NIET door de klant-accorderingsflow. */
export function BankDetailScreen() {
  const { administratieId } = useParams<{ administratieId: string }>()
  const { administraties } = useAdministraties()
  // Blok E4 (01/02-09): succes-uitkomsten zijn vluchtige toasts (geen statusregels boven de tabel =
  // geen layout-shift); fouten blijven persistent zichtbaar (bestaand foutpatroon).
  const toast = useToastOptioneel()
  const [searchParams, setSearchParams] = useSearchParams()
  const rekeningId = searchParams.get('rekening')

  const [rekeningen, setRekeningen] = useState<RekeningenDto | null>(null)
  const [mutaties, setMutaties] = useState<MutatieDto[] | null>(null)
  const [afletterHistorie, setAfletterHistorie] = useState<AfletterHistorieRegelDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [afletterBezigId, setAfletterBezigId] = useState<string | null>(null)
  const [afletterMelding, setAfletterMelding] = useState<{ tekst: string; isFout: boolean } | null>(null)
  // Deel 4 (25-08): herlaadsleutel voor de aanbetalingen-/splitsingen-panelen + het zojuist-
  // gesplitst-resultaat (de rij verdwijnt na verversen, het resultaat blijft zichtbaar).
  const [herlaadSleutel, setHerlaadSleutel] = useState(0)
  const [splitsResultaat, setSplitsResultaat] = useState<SplitsingDto | null>(null)

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
    setHerlaadSleutel((n) => n + 1)
  }, [laadRekeningen, laadMutaties])

  /** Auto-verversing bij openen (besluit Peter 25-08, punt 2): éénmaal per administratie; de cache
   * staat al op het scherm, bij `klaar` herladen we alles en tonen één regel samenvatting. */
  const autoVerversing = useBankAutoVerversing(
    administratieId,
    useCallback(
      (run: BankSyncRunDto) => {
        toast.meld(syncRunSamenvatting(run))
        verversAlles()
      },
      [verversAlles, toast],
    ),
  )
  const laatsteSyncOp = autoVerversing.run?.laatste_sync_op ?? rekeningen?.laatste_sync_op ?? null

  /** "Nu afletteren" vanuit de levenscyclus-lijst: voert een eerder klaargezette opdracht alsnog
   * via de API uit; de uitkomst (succes of fallback-fout) landt zichtbaar in dezelfde sectie. */
  const voerOpdrachtUit = async (opdrachtId: string) => {
    if (!administratieId) return
    setAfletterBezigId(opdrachtId)
    setAfletterMelding(null)
    try {
      const melding = afletterUitkomstMelding(await voerAfletterOpdrachtUit(administratieId, opdrachtId))
      // Succes vluchtig (toast), fout persistent in de sectie.
      if (melding.isFout) setAfletterMelding(melding)
      else toast.meld(melding.tekst)
      verversAlles()
    } catch (err) {
      setAfletterMelding({ tekst: err instanceof Error ? err.message : 'Afletteren mislukt', isFout: true })
    } finally {
      setAfletterBezigId(null)
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
        {/* IA-verbouwing 15-08: het bank-tabblad is weg — dit rekening-afletterscherm hangt
            onder de klantpagina (breadcrumb Werkvoorraad › klant › Bank). */}
        <div>
          <div className="mb-1 text-[12.5px] text-muted">
            <Link to="/" className="text-primary no-underline hover:underline">
              Werkvoorraad
            </Link>{' '}
            <span className="text-faint">›</span>{' '}
            <Link to={`/?administratie=${administratieId}`} className="text-primary no-underline hover:underline">
              {klantNaam}
            </Link>{' '}
            <span className="text-faint">›</span> Bank
          </div>
          <h1>Afletteren — {klantNaam}</h1>
        </div>
        <div className="bankpicker">
          <span className="bp-icon">🏦</span>
          <div>
            <label htmlFor="bank-rekening-select">Rekening</label>
            <Select
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
            </Select>
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

      {(autoVerversing.fout || autoVerversing.run?.status === 'fout') && (
        <div className="panel" role="alert">
          <p className="hint" style={{ color: 'var(--red)' }}>
            ⚠️ Automatisch verversen uit Reeleezee is mislukt
            {autoVerversing.run?.fout_reden ? `: ${autoVerversing.run.fout_reden}` : ''}
            {autoVerversing.fout ? `: ${autoVerversing.fout}` : ''}. De getoonde mutaties komen uit de cache van{' '}
            {formatVerversTijd(laatsteSyncOp).replace('laatst ververst ', '')}; probeer het later opnieuw via het
            ⟳-icoon in de paneelkop.
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
            later opnieuw via het ⟳-icoon in de paneelkop.
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
        {/* Blok E1/E2 (besluiten Peter 01-09 avond — herziet 25-08 deel 4 punt 2 "handmatige knop blijft"):
            geen knoppen meer; de versheidsregel staat vast in de paneelkop (blijft zichtbaar bij scrollen)
            mét een klein ⟳-icoon als handmatige noodrem (zelfde endpoint, forceer = drempel overslaan).
            Uitkomsten = toast; geen statusregels boven de tabel (layout-shift, diagnose Cowork 01-09). */}
        <div className="p-kop bank-p-kop">
          <h2 style={{ margin: 0 }}>Onverwerkte bankmutaties</h2>
          <div className="vers" data-testid="ververs-hint">
            <span>{formatVerversTijd(laatsteSyncOp)}</span>
            {autoVerversing.bezig ? (
              <span className="chip vraag" role="status">
                ⟳ verversen uit Reeleezee…
              </span>
            ) : autoVerversing.run?.status === 'overgeslagen' ? (
              <span className="chip geheugen">actueel</span>
            ) : autoVerversing.run?.status === 'klaar' ? (
              <span className="chip geheugen">zojuist ververst</span>
            ) : null}
            <button
              type="button"
              className="knopje"
              aria-label="Nu verversen uit Reeleezee"
              title="Nu verversen (haalt ook de verificatie van wachtende afletteropdrachten mee)"
              disabled={autoVerversing.bezig}
              onClick={() => autoVerversing.herstart()}
            >
              ⟳
            </button>
          </div>
        </div>
        {mutaties === null ? (
          <SkeletonRegels />
        ) : mutaties.length === 0 ? (
          <p className="hint">Geen onverwerkte mutaties op deze rekening.</p>
        ) : (
          <table className="bank-tabel">
            <thead>
              <tr>
                <th>Datum</th>
                <th>Tegenpartij / omschrijving</th>
                <th className="amount">Bedrag</th>
                <th>
                  Voorstel{' '}
                  <span className="info-i" title={`${GEEN_MATCH_TEKST} Een kaart = afletter-voorstel met de gegevens van de open post; "handmatig" = geen open post of vaste regel gevonden.`}>
                    ⓘ
                  </span>
                </th>
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
                  onMelding={(tekst) => toast.meld(tekst)}
                  onGesplitst={setSplitsResultaat}
                />
              ))}
            </tbody>
          </table>
        )}
        {splitsResultaat && (
          <div style={{ marginTop: 12 }} data-testid="splits-resultaat">
            <h3 style={{ margin: '0 0 6px' }}>Zojuist gesplitst</h3>
            <SplitsingWeergave
              administratieId={administratieId}
              splitsing={splitsResultaat}
              onBijgewerkt={(nieuw) => {
                setSplitsResultaat(nieuw)
                verversAlles()
              }}
            />
          </div>
        )}
        <div className="hint">
          Volgorde: 1) <b>exacte match</b> (referentie + bedrag) en 2) gedeeltelijke match →{' '}
          <b>afletteren</b>: de app legt de koppeling direct via de API in Reeleezee en verifieert meteen op het
          open bedrag; lukt dat niet, dan blijft de opdracht klaarstaan (“Nu afletteren” of handmatig in
          Reeleezee, de eerstvolgende sync verifieert); 3) vaste regel uit het geheugen en 5) handmatig →{' '}
          <b>direct op grootboek</b> geboekt vanuit de app; 4) Reeleezee's eigen voorstel wordt getoond mét bron.
          Na 3× dezelfde handmatige boeking stelt de app een vaste regel voor. Afletteren gaat niet door de
          klant-accorderingsflow. Daarnaast per mutatie: <b>Koppel aan relatie</b> (aanbetaling op crediteur/
          debiteur zonder factuur, verrekening later op de factuur) en <b>Splitsen</b> (één mutatie over meerdere
          bestemmingen — grootboek, open post of relatie; de delen moeten exact optellen).
        </div>
      </div>

      <AanbetalingenPaneel administratieId={administratieId} herlaadSleutel={herlaadSleutel} />

      {rekeningId && (
        <SplitsingenPaneel administratieId={administratieId} rekeningId={rekeningId} herlaadSleutel={herlaadSleutel} />
      )}

      {afletterHistorie !== null && afletterHistorie.length > 0 && (
        <div className="panel">
          <h2>Afletteren via Reeleezee — levenscyclus</h2>
          {afletterMelding && (
            <p className="hint" style={afletterMelding.isFout ? { color: 'var(--red)' } : undefined}>
              {afletterMelding.tekst}
            </p>
          )}
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
                  <td className={amountKlasse(regel.bedrag)}>{formatBedrag(regel.bedrag)}</td>
                  <td>
                    <AfletterStatusChip opdracht={regel.opdracht} />
                    {regel.opdracht.status === 'klaargezet' && (
                      <>
                        {' '}
                        <button
                          className="btn"
                          disabled={afletterBezigId !== null}
                          onClick={() => void voerOpdrachtUit(regel.opdracht.id)}
                        >
                          {afletterBezigId === regel.opdracht.id ? 'Afletteren…' : 'Nu afletteren ✓'}
                        </button>
                      </>
                    )}
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
            Klaargezette opdrachten (fallback ná een API-fout) letter je alsnog af met “Nu afletteren”, of je
            legt de koppeling in Reeleezee; ze worden bij elke bank-sync (en met “Nu verifiëren”) tegen Reeleezee
            gecontroleerd. Geverifieerd = het open bedrag in RLZ is 0. “Afwijkend gevolgd” betekent: in RLZ is
            tegen iets anders afgeletterd dan het voorstel — zichtbaar, nooit stil.
          </div>
        </div>
      )}
    </>
  )
}
