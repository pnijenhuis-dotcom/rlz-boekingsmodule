import { useEffect, useId, useState } from 'react'
import { SearchableCombobox } from '../document/SearchableCombobox'
import { useVendorOpties } from '../document/useSyncOpties'
import { amountKlasse } from '../werkvoorraad/format'
import {
  haalAanbetalingen,
  koppelRelatie,
  stornoAanbetaling,
  zoekDebiteuren,
  type AanbetalingDto,
  type DebiteurOptieDto,
  type MutatieDto,
  type RelatieBoekingDto,
  type RelatieSoort,
} from './bankApi'

const ZOEK_DEBOUNCE_MS = 300
const MIN_ZOEKLENGTE = 2

export function formatBedrag(bedrag: string | null): string {
  if (bedrag === null) return '—'
  return Number(bedrag).toLocaleString('nl-NL', { style: 'currency', currency: 'EUR' })
}

function formatDatumKort(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('nl-NL', { day: '2-digit', month: '2-digit' })
}

/** Uitleg bij de derde verwerkroute — identiek in het koppel-formulier en het relatie-deel van
 * de splits-editor (besluit Peter 25-08, punt 3). */
export const RELATIE_UITLEG =
  'Boekt een aanbetalingsdocument op de relatie (vooruitbetalingsrekening 1403/1806) en lettert de mutatie af; ' +
  'verrekening later via de tegenregel op de factuur.'

/** Debiteur-zoekveld: debiteuren hebben geen lokale cache (verkoop maakt ze ad hoc aan), dus een
 * live RLZ-zoekactie op naam — gedebounced (300 ms), pas vanaf 2 tekens (de backend geeft korter
 * een lege lijst terug). Keuze = één regel uit de resultaatlijst. */
function DebiteurZoeker({
  administratieId,
  waarde,
  onWijzig,
}: {
  administratieId: string
  waarde: DebiteurOptieDto | null
  onWijzig: (debiteur: DebiteurOptieDto | null) => void
}) {
  const inputId = useId()
  const [term, setTerm] = useState('')
  const [resultaten, setResultaten] = useState<DebiteurOptieDto[]>([])
  const [zoeken, setZoeken] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  useEffect(() => {
    const schoon = term.trim()
    if (schoon.length < MIN_ZOEKLENGTE) {
      setResultaten([])
      setZoeken(false)
      return
    }
    let actief = true
    setZoeken(true)
    setFout(null)
    const timer = setTimeout(() => {
      zoekDebiteuren(administratieId, schoon)
        .then((data) => {
          if (actief) setResultaten(data.debiteuren)
        })
        .catch((err: unknown) => {
          if (actief) setFout(err instanceof Error ? err.message : 'Zoeken mislukt')
        })
        .finally(() => {
          if (actief) setZoeken(false)
        })
    }, ZOEK_DEBOUNCE_MS)
    return () => {
      actief = false
      clearTimeout(timer)
    }
  }, [administratieId, term])

  if (waarde) {
    return (
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <span className="chip geheugen">Debiteur: {waarde.naam}</span>
        <button className="btn secondary" type="button" onClick={() => onWijzig(null)}>
          Andere debiteur
        </button>
      </div>
    )
  }

  return (
    <div style={{ display: 'grid', gap: 4 }}>
      <label htmlFor={inputId}>Debiteur *</label>
      <input
        id={inputId}
        value={term}
        onChange={(e) => setTerm(e.target.value)}
        placeholder="Zoek debiteur op naam (min. 2 tekens)…"
        autoComplete="off"
      />
      {zoeken && <span className="hint">Zoeken in Reeleezee…</span>}
      {fout && (
        <span className="hint" style={{ color: 'var(--red)' }}>
          {fout}
        </span>
      )}
      {!zoeken && term.trim().length >= MIN_ZOEKLENGTE && resultaten.length === 0 && !fout && (
        <span className="hint">Geen debiteuren gevonden voor “{term.trim()}”.</span>
      )}
      {resultaten.length > 0 && (
        <ul role="listbox" aria-label="Gevonden debiteuren" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {resultaten.map((d) => (
            <li key={d.id}>
              <button
                type="button"
                role="option"
                aria-selected={false}
                className="btn secondary"
                style={{ width: '100%', justifyContent: 'flex-start' }}
                onClick={() => onWijzig(d)}
              >
                {d.naam}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export interface RelatieKeuze {
  soort: RelatieSoort
  entityId: string | null
  /** Alleen voor weergave (debiteur-naam uit de live zoekactie). */
  naam: string | null
}

export const LEGE_RELATIE_KEUZE: RelatieKeuze = { soort: 'crediteur', entityId: null, naam: null }

/** Relatiekiezer: radio crediteur/debiteur + de passende picker (crediteur = sync-cache-combobox,
 * debiteur = live zoekveld). Gedeeld door het koppel-formulier en de splits-editor. */
export function RelatiePicker({
  administratieId,
  keuze,
  onWijzig,
}: {
  administratieId: string
  keuze: RelatieKeuze
  onWijzig: (keuze: RelatieKeuze) => void
}) {
  const groep = useId()
  const crediteuren = useVendorOpties(administratieId)

  return (
    <div style={{ display: 'grid', gap: 6 }}>
      <div role="radiogroup" aria-label="Relatiesoort" style={{ display: 'flex', gap: 14, fontSize: 13 }}>
        <label style={{ display: 'flex', gap: 5, alignItems: 'center' }}>
          <input
            type="radio"
            name={groep}
            value="crediteur"
            checked={keuze.soort === 'crediteur'}
            onChange={() => onWijzig({ soort: 'crediteur', entityId: null, naam: null })}
          />
          Crediteur
        </label>
        <label style={{ display: 'flex', gap: 5, alignItems: 'center' }}>
          <input
            type="radio"
            name={groep}
            value="debiteur"
            checked={keuze.soort === 'debiteur'}
            onChange={() => onWijzig({ soort: 'debiteur', entityId: null, naam: null })}
          />
          Debiteur
        </label>
      </div>
      {keuze.soort === 'crediteur' ? (
        <SearchableCombobox
          label="Crediteur"
          opties={crediteuren.opties}
          waarde={keuze.entityId}
          onWijzig={(id) =>
            onWijzig({
              soort: 'crediteur',
              entityId: id,
              naam: crediteuren.opties.find((o) => o.id === id)?.label ?? null,
            })
          }
          placeholder="Zoek crediteur…"
          vereist
        />
      ) : (
        <DebiteurZoeker
          administratieId={administratieId}
          waarde={keuze.entityId ? { id: keuze.entityId, naam: keuze.naam ?? keuze.entityId } : null}
          onWijzig={(d) => onWijzig({ soort: 'debiteur', entityId: d?.id ?? null, naam: d?.naam ?? null })}
        />
      )}
    </div>
  )
}

export function relatieSuccesMelding(resultaat: RelatieBoekingDto, keuze: RelatieKeuze): string {
  const nummer = resultaat.rlz_boekstuknummer ?? resultaat.rlz_document_id
  return (
    `Gekoppeld aan ${keuze.soort} ${keuze.naam ?? ''}: aanbetalingsdocument ${nummer} geboekt en de mutatie ` +
    `afgeletterd${resultaat.open_restant !== null && Number(resultaat.open_restant) !== 0 ? ` (open restant ${formatBedrag(resultaat.open_restant)})` : ''}.`
  ).replace(/\s{2,}/g, ' ')
}

/** Inline koppel-formulier per mutatie (zelfde patroon als HandmatigBoekenForm): derde
 * verwerkroute naast afletteren en direct-op-grootboek. Fouten (409/403/429/502) blijven in de rij
 * zichtbaar; succes meldt het boekstuknummer op schermniveau. */
export function KoppelRelatieForm({
  administratieId,
  mutatie,
  onGekoppeld,
  onAnnuleer,
}: {
  administratieId: string
  mutatie: MutatieDto
  onGekoppeld: (melding: string) => void
  onAnnuleer: () => void
}) {
  const [keuze, setKeuze] = useState<RelatieKeuze>(LEGE_RELATIE_KEUZE)
  const [omschrijving, setOmschrijving] = useState(mutatie.omschrijving ?? '')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const koppel = async () => {
    if (!keuze.entityId) return
    setBezig(true)
    setFout(null)
    try {
      const resultaat = await koppelRelatie(administratieId, mutatie.id, {
        relatie_soort: keuze.soort,
        entity_id: keuze.entityId,
        omschrijving: omschrijving.trim() || null,
      })
      onGekoppeld(relatieSuccesMelding(resultaat, keuze))
    } catch (err) {
      setFout(err instanceof Error ? err.message : 'Koppelen mislukt')
    } finally {
      setBezig(false)
    }
  }

  return (
    <div style={{ display: 'grid', gap: 8, padding: '8px 0' }} data-testid="koppel-relatie-form">
      <RelatiePicker administratieId={administratieId} keuze={keuze} onWijzig={setKeuze} />
      <label>
        Omschrijving (optioneel)
        <input value={omschrijving} onChange={(e) => setOmschrijving(e.target.value)} />
      </label>
      <p className="hint">{RELATIE_UITLEG}</p>
      {fout && (
        <p className="hint" style={{ color: 'var(--red)' }}>
          {fout}
        </p>
      )}
      <div className="actions">
        <button className="btn" onClick={() => void koppel()} disabled={!keuze.entityId || bezig}>
          {bezig ? 'Koppelen…' : 'Koppel aan relatie ✓'}
        </button>
        <button className="btn secondary" onClick={onAnnuleer} disabled={bezig}>
          Annuleren
        </button>
      </div>
    </div>
  )
}

/** Verplichte-reden-invoer voor een storno (inline, geen browser-prompt — dezelfde vorm als de
 * afwijzen-met-reden-velden elders). */
export function StornoRedenForm({
  bezig,
  onBevestig,
  onAnnuleer,
  label = 'Storno bevestigen',
}: {
  bezig: boolean
  onBevestig: (reden: string) => void
  onAnnuleer: () => void
  label?: string
}) {
  const [reden, setReden] = useState('')
  return (
    <div style={{ display: 'grid', gap: 6, padding: '6px 0' }}>
      <label>
        Reden storno *
        <input value={reden} onChange={(e) => setReden(e.target.value)} placeholder="Verplicht — waarom terugdraaien?" />
      </label>
      <div className="actions">
        <button className="btn" disabled={!reden.trim() || bezig} onClick={() => onBevestig(reden.trim())}>
          {bezig ? 'Storneren…' : label}
        </button>
        <button className="btn secondary" disabled={bezig} onClick={onAnnuleer}>
          Annuleren
        </button>
      </div>
    </div>
  )
}

/** Paneel "Openstaande aanbetalingen op relaties": RLZ kent de aanbetaling ná het afletteren
 * alleen als GB-saldo, de open post per relatie leeft hier. Alleen zichtbaar als er iets staat.
 * Storno = verplichte reden → POST → herladen. */
export function AanbetalingenPaneel({
  administratieId,
  herlaadSleutel,
}: {
  administratieId: string
  herlaadSleutel: number
}) {
  const [rijen, setRijen] = useState<AanbetalingDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [stornoId, setStornoId] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const [melding, setMelding] = useState<string | null>(null)
  const [lokaalHerlaad, setLokaalHerlaad] = useState(0)

  useEffect(() => {
    let actief = true
    haalAanbetalingen(administratieId)
      .then((data) => {
        if (actief) setRijen(data.aanbetalingen)
      })
      .catch((err: unknown) => {
        if (actief) setFout(err instanceof Error ? err.message : 'Aanbetalingen laden mislukt')
      })
    return () => {
      actief = false
    }
  }, [administratieId, herlaadSleutel, lokaalHerlaad])

  const storneer = async (boekingId: string, reden: string) => {
    setBezig(true)
    setFout(null)
    try {
      await stornoAanbetaling(administratieId, boekingId, reden)
      setMelding('Aanbetaling gestorneerd (actie 19 Correct in Reeleezee) — de mutatie staat weer open.')
      setStornoId(null)
      setLokaalHerlaad((n) => n + 1)
    } catch (err) {
      setFout(err instanceof Error ? err.message : 'Storno mislukt')
    } finally {
      setBezig(false)
    }
  }

  if (!fout && (rijen === null || rijen.length === 0)) return null

  return (
    <div className="panel">
      <h2>Openstaande aanbetalingen op relaties</h2>
      {melding && <p className="hint">{melding}</p>}
      {fout && (
        <p className="hint" style={{ color: 'var(--red)' }}>
          {fout}
        </p>
      )}
      {rijen && rijen.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Datum</th>
              <th>Relatie</th>
              <th className="amount">Bedrag</th>
              <th>Boekstuk</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rijen.map((rij) => (
              <tr key={rij.boeking_id}>
                <td>{formatDatumKort(rij.boekdatum)}</td>
                <td>
                  <span className="chip">{rij.relatie_soort}</span> {rij.entity_naam ?? rij.entity_id}
                </td>
                <td className={amountKlasse(rij.bedrag)}>{formatBedrag(rij.bedrag)}</td>
                <td>{rij.rlz_boekstuknummer ?? '—'}</td>
                <td>
                  <span className="chip vraag">{rij.status === 'geboekt' ? 'open — nog te verrekenen' : rij.status}</span>
                </td>
                <td>
                  {stornoId === rij.boeking_id ? (
                    <StornoRedenForm
                      bezig={bezig}
                      onBevestig={(reden) => void storneer(rij.boeking_id, reden)}
                      onAnnuleer={() => setStornoId(null)}
                    />
                  ) : (
                    <button className="btn secondary" disabled={bezig} onClick={() => setStornoId(rij.boeking_id)}>
                      Storno…
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="hint">
        Een aanbetaling blijft hier open tot de factuur in Reeleezee via de tegenregel op de
        vooruitbetalingsrekening wordt verrekend. Storno draait het aanbetalingsdocument terug (reden verplicht,
        audit) — de bankmutatie komt dan weer in de werkvoorraad.
      </div>
    </div>
  )
}
