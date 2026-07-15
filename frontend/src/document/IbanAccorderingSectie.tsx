import { useCallback, useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import type { IbanAccorderingDto } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { useMedewerkers } from '../vragen/useMedewerkers'
import {
  accordeerIban,
  biedIbanAan,
  haalAccorderingenOp,
  haalIbanAccordeursOp,
  maskeerIban,
  SOORT_LABELS,
  wijsIbanAf,
} from './ibanAccorderingApi'

function formatDatum(iso: string): string {
  return new Date(iso).toLocaleString('nl-NL', { dateStyle: 'medium', timeStyle: 'short' })
}

interface AanbiedenVormProps {
  administratieId: string
  documentId: string
  initieelIban: string
  knopTekst: string
  onAangeboden: () => void
}

/** Aanbieden-vorm (soort + rekeningnummer): gebruikt bij de geblokkeerde IBAN-wissel-check op
 * het controlescherm (BoekvoorstelPanel) én voor de her-aanvraag na een afwijzing. Het IBAN is
 * vooringevuld vanuit de extractie maar blijft controleerbaar/corrigeerbaar — de backend
 * valideert mod-97 hoe dan ook. */
export function IbanAanbiedenVorm({
  administratieId,
  documentId,
  initieelIban,
  knopTekst,
  onAangeboden,
}: AanbiedenVormProps) {
  const [iban, setIban] = useState(initieelIban)
  const [soort, setSoort] = useState<'regulier' | 'g_rekening'>('regulier')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const aanbieden = async () => {
    setBezig(true)
    setFout(null)
    try {
      await biedIbanAan(administratieId, documentId, { nieuw_iban: iban, soort })
      onAangeboden()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Aanbieden mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <div style={{ marginTop: 10 }}>
      <div className="grid2">
        <div>
          <label htmlFor="iban-aanbieden-nummer">Rekeningnummer (IBAN) van de factuur</label>
          <input
            id="iban-aanbieden-nummer"
            value={iban}
            onChange={(e) => setIban(e.target.value)}
            placeholder="NL00BANK0123456789"
          />
        </div>
        <div>
          <label htmlFor="iban-aanbieden-soort">Soort rekening</label>
          <select
            id="iban-aanbieden-soort"
            value={soort}
            onChange={(e) => setSoort(e.target.value as 'regulier' | 'g_rekening')}
          >
            <option value="regulier">{SOORT_LABELS.regulier}</option>
            <option value="g_rekening">{SOORT_LABELS.g_rekening}</option>
          </select>
        </div>
      </div>
      {fout && <div className="fout">{fout}</div>}
      <div className="actions">
        <button
          type="button"
          className="btn secondary"
          disabled={bezig || iban.trim() === ''}
          onClick={() => void aanbieden()}
        >
          {bezig ? 'Bezig…' : knopTekst}
        </button>
      </div>
    </div>
  )
}

interface SectieProps {
  administratieId: string
  documentId: string
  onGewijzigd: () => void
}

/** Vier-ogen-sectie op het controlescherm van een document op wacht_op_iban_accordering
 * (docs/ontwerp/iban-wissel-accordering.md), rol-afhankelijk: de aanvrager (en elke
 * niet-accordeur) ziet een read-only wachtstatus zónder accordeer-acties; een ingestelde
 * accordeur ≠ aanvrager ziet het accordeer-paneel; na een afwijzing is het document zichtbaar
 * verdacht (reden + wie) met een her-aanvraag als enige weg vooruit. De backend dwingt
 * dezelfde regels server-side af — dit is uitsluitend de UI-kant. */
export function IbanAccorderingSectie({ administratieId, documentId, onGewijzigd }: SectieProps) {
  const { gebruikerId, rol } = useAuth()
  const { naamVoor } = useMedewerkers(administratieId)
  const [accorderingen, setAccorderingen] = useState<IbanAccorderingDto[] | null>(null)
  const [accordeurs, setAccordeurs] = useState<string[] | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [besluitBezig, setBesluitBezig] = useState(false)
  const [besluitFout, setBesluitFout] = useState<string | null>(null)
  const [afwijzenOpen, setAfwijzenOpen] = useState(false)
  const [afwijsReden, setAfwijsReden] = useState('')

  const laad = useCallback(() => {
    setLaadFout(null)
    Promise.all([
      haalAccorderingenOp(administratieId, { documentId }),
      haalIbanAccordeursOp(administratieId),
    ])
      .then(([lijst, accordeursDto]) => {
        setAccorderingen(lijst.accorderingen)
        setAccordeurs(accordeursDto.accordeurs)
      })
      .catch((err: unknown) => setLaadFout(err instanceof Error ? err.message : 'Onbekende fout'))
  }, [administratieId, documentId])

  useEffect(() => {
    laad()
  }, [laad])

  if (laadFout) {
    return (
      <div className="panel">
        <h2>
          IBAN-wissel <span className="chip vraag">boeken geblokkeerd</span>
        </h2>
        <div className="fout">Kon de IBAN-accordering niet laden: {laadFout}</div>
      </div>
    )
  }
  if (accorderingen === null || accordeurs === null) {
    return (
      <div className="panel">
        <p className="hint" style={{ margin: 0 }}>
          IBAN-accordering laden…
        </p>
      </div>
    )
  }

  const open = accorderingen.find((a) => a.status === 'open') ?? null
  // Lijst is nieuwste-eerst (backend): zonder open aanvraag is de eerste rij het laatste besluit.
  const laatsteAfgewezen = !open && accorderingen[0]?.status === 'afgewezen' ? accorderingen[0] : null

  const isBevoegd =
    gebruikerId !== null && (accordeurs.length > 0 ? accordeurs.includes(gebruikerId) : rol === 'beheerder')
  const accordeurNamen =
    accordeurs.length > 0 ? accordeurs.map((id) => naamVoor(id)).join(', ') : 'de beheerder(s)'

  const besluit = async (actie: 'accorderen' | 'afwijzen') => {
    if (!open) return
    setBesluitBezig(true)
    setBesluitFout(null)
    try {
      if (actie === 'accorderen') {
        await accordeerIban(administratieId, open.id)
      } else {
        await wijsIbanAf(administratieId, open.id, afwijsReden)
      }
      onGewijzigd()
    } catch (err) {
      setBesluitFout(err instanceof ApiError ? err.message : 'Besluit vastleggen mislukt.')
    } finally {
      setBesluitBezig(false)
    }
  }

  if (open) {
    const isAanvrager = gebruikerId !== null && gebruikerId === open.aangevraagd_door
    const aanvraagDetails = (
      <div className="q-item" style={{ marginBottom: 0, border: 'none', padding: 0 }}>
        <div className="meta">
          aangeboden door {naamVoor(open.aangevraagd_door)}, {formatDatum(open.aangevraagd_op)} ·{' '}
          {SOORT_LABELS[open.soort]}
        </div>
        <div style={{ fontSize: 13 }}>
          Nieuw rekeningnummer: <b style={{ fontVariantNumeric: 'tabular-nums' }}>{maskeerIban(open.nieuw_iban)}</b>{' '}
          <span className="hint" style={{ margin: 0, display: 'inline' }}>
            — wijkt af van de vertrouwde rekening(en) van deze crediteur; het volledige nummer staat op de
            factuur-preview.
          </span>
        </div>
      </div>
    )

    if (isAanvrager || !isBevoegd) {
      return (
        <div className="panel">
          <h2>
            IBAN-wissel — wacht op accordering <span className="chip vraag">boeken geblokkeerd</span>
          </h2>
          {aanvraagDetails}
          <p className="hint">
            Wacht op accordering door <b>{accordeurNamen}</b> — vier-ogen-controle: de aanvrager kan zijn
            eigen aanvraag niet beoordelen.
          </p>
        </div>
      )
    }

    return (
      <div className="panel">
        <h2>
          IBAN-wissel — uw accordering gevraagd <span className="chip vraag">boeken geblokkeerd</span>
        </h2>
        {aanvraagDetails}
        <div
          className="hint"
          style={{ color: 'var(--orange)', marginTop: 10 }}
        >
          ⚠ Vier-ogen-controle tegen IBAN-wissel-fraude: vertrouw de factuur zelf niet als bron. Verifieer
          het nieuwe rekeningnummer buiten het factuurkanaal om — bijvoorbeeld telefonisch via een al bekend
          nummer van de leverancier, nooit via contactgegevens van de factuur zelf.
        </div>
        {besluitFout && <div className="fout">{besluitFout}</div>}
        {!afwijzenOpen ? (
          <div className="actions">
            <button
              type="button"
              className="btn warn"
              disabled={besluitBezig}
              onClick={() => {
                setBesluitFout(null)
                setAfwijzenOpen(true)
              }}
            >
              Afwijzen…
            </button>
            <button
              type="button"
              className="btn green"
              disabled={besluitBezig}
              onClick={() => void besluit('accorderen')}
            >
              {besluitBezig ? 'Bezig…' : 'Accorderen en deblokkeren ✓'}
            </button>
          </div>
        ) : (
          <div style={{ marginTop: 10 }}>
            <label htmlFor="iban-afwijs-reden">Reden van afwijzing (verplicht)</label>
            <textarea
              id="iban-afwijs-reden"
              rows={2}
              placeholder="Bijv.: rekeningnummer telefonisch niet bevestigd door de leverancier"
              value={afwijsReden}
              onChange={(e) => setAfwijsReden(e.target.value)}
            />
            <div className="actions">
              <button
                type="button"
                className="btn secondary"
                disabled={besluitBezig}
                onClick={() => setAfwijzenOpen(false)}
              >
                Annuleren
              </button>
              <button
                type="button"
                className="btn warn"
                disabled={besluitBezig || afwijsReden.trim() === ''}
                onClick={() => void besluit('afwijzen')}
              >
                {besluitBezig ? 'Bezig…' : 'Afwijzen'}
              </button>
            </div>
          </div>
        )}
      </div>
    )
  }

  if (laatsteAfgewezen) {
    return (
      <div className="panel">
        <h2>
          IBAN-aanvraag afgewezen — verdacht <span className="chip blokkerend">boeken geblokkeerd</span>
        </h2>
        <div className="q-item" style={{ marginBottom: 0, border: 'none', padding: 0 }}>
          <div className="meta">
            {maskeerIban(laatsteAfgewezen.nieuw_iban)} ({SOORT_LABELS[laatsteAfgewezen.soort]}) — aangeboden
            door {naamVoor(laatsteAfgewezen.aangevraagd_door)}, afgewezen door{' '}
            <b>{naamVoor(laatsteAfgewezen.besloten_door)}</b>
            {laatsteAfgewezen.besloten_op ? `, ${formatDatum(laatsteAfgewezen.besloten_op)}` : ''}
          </div>
          <div className="vraagtekst">reden: &ldquo;{laatsteAfgewezen.afwijs_reden}&rdquo;</div>
        </div>
        <p className="hint">
          Het document blijft geblokkeerd. Na onderzoek (bijv. telefonische verificatie bij de leverancier)
          kan het rekeningnummer opnieuw ter accordering aangeboden worden — een volledige nieuwe
          vier-ogen-ronde.
        </p>
        <IbanAanbiedenVorm
          administratieId={administratieId}
          documentId={documentId}
          initieelIban={laatsteAfgewezen.nieuw_iban}
          knopTekst="Opnieuw ter accordering aanbieden"
          onAangeboden={onGewijzigd}
        />
      </div>
    )
  }

  // Wachtstatus zonder accordering-historie (hoort niet voor te komen — PART A weigert dit pad);
  // nooit stil niets tonen.
  return (
    <div className="panel">
      <h2>
        IBAN-wissel — wacht op accordering <span className="chip vraag">boeken geblokkeerd</span>
      </h2>
      <p className="hint" style={{ margin: 0 }}>
        Geen accordering-aanvraag gevonden bij dit document — neem contact op met de beheerder.
      </p>
    </div>
  )
}
