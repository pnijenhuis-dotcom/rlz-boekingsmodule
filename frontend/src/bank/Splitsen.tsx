import { useEffect, useMemo, useState } from 'react'
import { SearchableCombobox } from '../document/SearchableCombobox'
import { useGrootboekOpties, useTaxrateOpties } from '../document/useSyncOpties'
import { Select } from '../ui/basis'
import { amountKlasse } from '../werkvoorraad/format'
import {
  haalSplitsingen,
  hervatSplitsing,
  splitsMutatie,
  stornoSplitsDeel,
  type MutatieDto,
  type SplitsDeelDto,
  type SplitsDeelInputDto,
  type SplitsDeelSoort,
  type SplitsingDto,
} from './bankApi'
import {
  formatBedrag,
  LEGE_RELATIE_KEUZE,
  RELATIE_UITLEG,
  RelatiePicker,
  StornoRedenForm,
  type RelatieKeuze,
} from './RelatieKoppeling'

export const SOORT_LABEL: Record<SplitsDeelSoort, string> = {
  grootboek: 'Grootboek',
  open_post: 'Open post (afletteren)',
  relatie: 'Relatie (aanbetaling)',
}

/** Bedraginvoer → centen (absoluut). Accepteert "1.234,56", "1234.56", "1234,56" en "€ 12"; leeg of
 * onleesbaar = null. Geldrekenwerk in gehele centen — nooit floats optellen. */
export function parseBedragCenten(tekst: string): number | null {
  const schoon = tekst.replace(/[€\s]/g, '')
  if (!schoon) return null
  // Zowel "1.234,56" (NL) als "1234.56" (toetsenbord): laatste scheidingsteken = decimaalteken.
  const laatsteKomma = schoon.lastIndexOf(',')
  const laatstePunt = schoon.lastIndexOf('.')
  let genormaliseerd: string
  if (laatsteKomma > laatstePunt) genormaliseerd = schoon.replace(/\./g, '').replace(',', '.')
  else genormaliseerd = schoon.replace(/,/g, '')
  if (!/^-?\d+(\.\d{1,2})?$/.test(genormaliseerd)) return null
  return Math.abs(Math.round(Number(genormaliseerd) * 100))
}

function centenNaarString(centen: number): string {
  return (centen / 100).toFixed(2)
}

interface DeelInvoer {
  key: number
  soort: SplitsDeelSoort
  bedrag: string
  ledgerId: string | null
  taxrateId: string | null
  omschrijving: string
  paymentItemId: string | null
  relatie: RelatieKeuze
}

function nieuwDeel(key: number, overrides: Partial<DeelInvoer> = {}): DeelInvoer {
  return {
    key,
    soort: 'grootboek',
    bedrag: '',
    ledgerId: null,
    taxrateId: null,
    omschrijving: '',
    paymentItemId: null,
    relatie: LEGE_RELATIE_KEUZE,
    ...overrides,
  }
}

function deelCompleet(deel: DeelInvoer): boolean {
  if (parseBedragCenten(deel.bedrag) === null || parseBedragCenten(deel.bedrag) === 0) return false
  if (deel.soort === 'grootboek') return deel.ledgerId !== null
  if (deel.soort === 'open_post') return deel.paymentItemId !== null
  return deel.relatie.entityId !== null
}

/** Inline verdeel-editor (besluit Peter 25-08, punt 4): rijen met bedrag + bestemmingstype.
 * Bedragen voer je positief in — het teken volgt de mutatie (een −1.000-mutatie in 800 + 200).
 * Live rest-teller (mutatie − Σ delen) in rood tot exact 0; versturen kan pas dan én zodra elk
 * deel een complete bestemming heeft. De server toetst de som opnieuw (422). "Kruispost" is
 * gewoon een grootboekkeuze. Open-post-bestemming: alleen de open post die de matchmotor bij
 * deze mutatie kent (`voorstel.open_post`) — een los payment_item_id invoeren bestaat bewust
 * niet. */
export function SplitsenForm({
  administratieId,
  mutatie,
  onGesplitst,
  onAnnuleer,
}: {
  administratieId: string
  mutatie: MutatieDto
  onGesplitst: (splitsing: SplitsingDto) => void
  onAnnuleer: () => void
}) {
  const grootboek = useGrootboekOpties(administratieId)
  const btwCodes = useTaxrateOpties(administratieId)
  const openPost = mutatie.voorstel.open_post
  const mutatieCenten = Math.round(Number(mutatie.bedrag ?? '0') * 100)
  const teken = mutatieCenten < 0 ? -1 : 1

  const [delen, setDelen] = useState<DeelInvoer[]>(() => {
    // Suggestie: is er een open post bekend, dan is die het voor de hand liggende eerste deel
    // (deelmatch → open post + rest), begrensd op het mutatiebedrag.
    if (openPost && openPost.bedrag !== null) {
      const postCenten = Math.min(Math.abs(Math.round(Number(openPost.bedrag) * 100)), Math.abs(mutatieCenten))
      return [
        nieuwDeel(1, { soort: 'open_post', paymentItemId: openPost.id, bedrag: centenNaarString(postCenten) }),
        nieuwDeel(2),
      ]
    }
    return [nieuwDeel(1), nieuwDeel(2)]
  })
  const [volgendeKey, setVolgendeKey] = useState(3)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const somCenten = useMemo(
    () => delen.reduce((som, d) => som + (parseBedragCenten(d.bedrag) ?? 0), 0) * teken,
    [delen, teken],
  )
  const restCenten = mutatieCenten - somCenten
  const alleCompleet = delen.every(deelCompleet)
  const kanVersturen = restCenten === 0 && alleCompleet && delen.length >= 2 && !bezig

  const wijzig = (key: number, patch: Partial<DeelInvoer>) =>
    setDelen((huidig) => huidig.map((d) => (d.key === key ? { ...d, ...patch } : d)))

  const verstuur = async () => {
    if (!kanVersturen) return
    setBezig(true)
    setFout(null)
    try {
      const body: SplitsDeelInputDto[] = delen.map((d) => {
        const centen = (parseBedragCenten(d.bedrag) ?? 0) * teken
        const bedrag = centenNaarString(centen)
        const basis: SplitsDeelInputDto = { soort: d.soort, bedrag, omschrijving: d.omschrijving.trim() || null }
        if (d.soort === 'grootboek') {
          // Zelfde btw-formule als HandmatigBoekenForm: netto uit het inclusief-bedrag, btw = rest.
          const percentage = btwCodes.opties.find((o) => o.id === d.taxrateId)?.percentage
          let netto = bedrag
          let btw: string | null = null
          if (d.taxrateId && percentage) {
            const bedragGetal = centen / 100
            const nettoGetal = Math.round((bedragGetal / (1 + percentage)) * 100) / 100
            netto = nettoGetal.toFixed(2)
            btw = (Math.round((bedragGetal - nettoGetal) * 100) / 100).toFixed(2)
          }
          basis.regels = [
            {
              ledger_id: d.ledgerId ?? '',
              netto_bedrag: netto,
              btw_bedrag: btw,
              taxrate_id: d.taxrateId,
              project_id: null,
              omschrijving: d.omschrijving.trim() || null,
            },
          ]
        } else if (d.soort === 'open_post') {
          basis.payment_item_id = d.paymentItemId ?? ''
        } else {
          basis.relatie_soort = d.relatie.soort
          basis.entity_id = d.relatie.entityId ?? ''
        }
        return basis
      })
      onGesplitst(await splitsMutatie(administratieId, mutatie.id, body))
    } catch (err) {
      setFout(err instanceof Error ? err.message : 'Splitsen mislukt')
    } finally {
      setBezig(false)
    }
  }

  return (
    <div style={{ display: 'grid', gap: 10, padding: '8px 0' }} data-testid="splitsen-form">
      <p className="hint">
        Mutatie {formatBedrag(mutatie.bedrag)} verdelen over meerdere bestemmingen. Bedragen positief invoeren —
        het teken volgt de mutatie. De delen moeten exact optellen tot het mutatiebedrag.
      </p>
      {delen.map((deel, index) => (
        <div
          key={deel.key}
          style={{ display: 'grid', gap: 6, padding: 8, border: '1px solid var(--border)', borderRadius: 8 }}
          data-testid={`splits-deel-${index + 1}`}
        >
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <label style={{ flex: '0 0 140px' }}>
              Bedrag deel {index + 1} *
              <input
                inputMode="decimal"
                value={deel.bedrag}
                onChange={(e) => wijzig(deel.key, { bedrag: e.target.value })}
                placeholder="0,00"
                aria-label={`Bedrag deel ${index + 1}`}
              />
            </label>
            <label style={{ flex: '1 1 180px' }}>
              Bestemming
              <Select
                aria-label={`Bestemming deel ${index + 1}`}
                value={deel.soort}
                onChange={(e) => {
                  const soort = e.target.value as SplitsDeelSoort
                  wijzig(deel.key, {
                    soort,
                    paymentItemId: soort === 'open_post' ? openPost?.id ?? null : null,
                  })
                }}
              >
                <option value="grootboek">{SOORT_LABEL.grootboek}</option>
                <option value="open_post" disabled={!openPost}>
                  {SOORT_LABEL.open_post}
                  {!openPost ? ' — geen open post bekend bij deze mutatie' : ''}
                </option>
                <option value="relatie">{SOORT_LABEL.relatie}</option>
              </Select>
            </label>
            {delen.length > 2 && (
              <button
                type="button"
                className="btn secondary"
                onClick={() => setDelen((huidig) => huidig.filter((d) => d.key !== deel.key))}
                aria-label={`Deel ${index + 1} verwijderen`}
              >
                ✕
              </button>
            )}
          </div>
          {deel.soort === 'grootboek' && (
            <>
              <SearchableCombobox
                label={`Grootboekrekening deel ${index + 1}`}
                opties={grootboek.opties}
                waarde={deel.ledgerId}
                onWijzig={(id) => wijzig(deel.key, { ledgerId: id })}
                placeholder="Zoek grootboekrekening (kruispost = gewoon een grootboekkeuze)…"
                vereist
              />
              <SearchableCombobox
                label={`Btw-code deel ${index + 1}`}
                opties={btwCodes.opties}
                waarde={deel.taxrateId}
                onWijzig={(id) => wijzig(deel.key, { taxrateId: id })}
                placeholder="Geen btw"
              />
            </>
          )}
          {deel.soort === 'open_post' && openPost && (
            <div className="hint">
              Afletteren tegen open post <b>{openPost.referentie ?? openPost.id}</b>
              {openPost.bedrag ? ` (${formatBedrag(openPost.bedrag)})` : ''} — de enige open post die de matchmotor bij
              deze mutatie kent.
            </div>
          )}
          {deel.soort === 'relatie' && (
            <>
              <RelatiePicker
                administratieId={administratieId}
                keuze={deel.relatie}
                onWijzig={(relatie) => wijzig(deel.key, { relatie })}
              />
              <p className="hint">{RELATIE_UITLEG}</p>
            </>
          )}
          <label>
            Omschrijving deel {index + 1}
            <input value={deel.omschrijving} onChange={(e) => wijzig(deel.key, { omschrijving: e.target.value })} />
          </label>
        </div>
      ))}
      <div className="actions" style={{ alignItems: 'center' }}>
        <button
          type="button"
          className="btn secondary"
          onClick={() => {
            setDelen((huidig) => [...huidig, nieuwDeel(volgendeKey)])
            setVolgendeKey((k) => k + 1)
          }}
          disabled={bezig}
        >
          + Deel toevoegen
        </button>
        <span
          className="hint"
          data-testid="splits-rest"
          style={{ color: restCenten === 0 ? 'var(--green)' : 'var(--red)', fontWeight: 600 }}
        >
          Rest: {formatBedrag(centenNaarString(restCenten))}
          {restCenten === 0 ? ' — klopt' : ''}
        </span>
      </div>
      {fout && (
        <p className="hint" style={{ color: 'var(--red)' }}>
          {fout}
        </p>
      )}
      <div className="actions">
        <button className="btn" onClick={() => void verstuur()} disabled={!kanVersturen}>
          {bezig ? 'Splitsen…' : 'Splitsen en verwerken ✓'}
        </button>
        <button className="btn secondary" onClick={onAnnuleer} disabled={bezig}>
          Annuleren
        </button>
      </div>
    </div>
  )
}

function DeelStatusChip({ deel }: { deel: SplitsDeelDto }) {
  if (deel.status === 'verwerkt') return <span className="chip geheugen">verwerkt</span>
  if (deel.status === 'fout') return <span className="chip ai">fout</span>
  if (deel.status === 'gestorneerd') return <span className="chip">gestorneerd</span>
  return <span className="chip vraag">wacht</span>
}

function SplitsingStatusChip({ status }: { status: SplitsingDto['status'] }) {
  if (status === 'verwerkt') return <span className="chip geheugen">volledig verwerkt</span>
  if (status === 'half_verwerkt') return <span className="chip ai">half verwerkt — hervatten</span>
  if (status === 'gestorneerd') return <span className="chip">gestorneerd</span>
  return <span className="chip vraag">bezig</span>
}

/** Resultaatweergave per splitsing: chips per deel (verwerkt/fout/wacht + fouttekst), "Hervatten" bij
 * half_verwerkt (POST hervat) en per verwerkt deel "Storno deel…" (reden verplicht). Gedeeld door
 * het zojuist-gesplitst-resultaat en het paneel "Gesplitste mutaties". */
export function SplitsingWeergave({
  administratieId,
  splitsing,
  onBijgewerkt,
}: {
  administratieId: string
  splitsing: SplitsingDto
  onBijgewerkt: (splitsing: SplitsingDto) => void
}) {
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [stornoDeelId, setStornoDeelId] = useState<string | null>(null)

  const doe = async (actie: () => Promise<SplitsingDto>) => {
    setBezig(true)
    setFout(null)
    try {
      onBijgewerkt(await actie())
      setStornoDeelId(null)
    } catch (err) {
      setFout(err instanceof Error ? err.message : 'Actie mislukt')
    } finally {
      setBezig(false)
    }
  }

  return (
    <div style={{ display: 'grid', gap: 6 }} data-testid={`splitsing-${splitsing.splitsing_id}`}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <b>Mutatie {formatBedrag(splitsing.mutatie_bedrag)}</b> in {splitsing.delen.length} delen{' '}
        <SplitsingStatusChip status={splitsing.status} />
        {splitsing.status === 'half_verwerkt' && (
          <button
            className="btn"
            disabled={bezig}
            onClick={() => void doe(() => hervatSplitsing(administratieId, splitsing.splitsing_id))}
          >
            {bezig ? 'Hervatten…' : 'Hervatten'}
          </button>
        )}
      </div>
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Bestemming</th>
            <th className="amount">Bedrag</th>
            <th>Status</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {splitsing.delen.map((deel) => (
            <tr key={deel.deel_id}>
              <td>{deel.volgnummer}</td>
              <td>{SOORT_LABEL[deel.soort] ?? deel.soort}</td>
              <td className={amountKlasse(deel.bedrag)}>{formatBedrag(deel.bedrag)}</td>
              <td>
                <DeelStatusChip deel={deel} />
                {deel.fout && (
                  <div className="hint" style={{ color: 'var(--red)' }}>
                    {deel.fout}
                  </div>
                )}
              </td>
              <td>
                {deel.status === 'verwerkt' &&
                  (stornoDeelId === deel.deel_id ? (
                    <StornoRedenForm
                      bezig={bezig}
                      label="Storno deel bevestigen"
                      onBevestig={(reden) => void doe(() => stornoSplitsDeel(administratieId, deel.deel_id, reden))}
                      onAnnuleer={() => setStornoDeelId(null)}
                    />
                  ) : (
                    <button className="btn secondary" disabled={bezig} onClick={() => setStornoDeelId(deel.deel_id)}>
                      Storno deel…
                    </button>
                  ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {fout && (
        <p className="hint" style={{ color: 'var(--red)' }}>
          {fout}
        </p>
      )}
    </div>
  )
}

/** Paneel "Gesplitste mutaties" per rekening — alleen zichtbaar als er splitsingen zijn. */
export function SplitsingenPaneel({
  administratieId,
  rekeningId,
  herlaadSleutel,
}: {
  administratieId: string
  rekeningId: string
  herlaadSleutel: number
}) {
  const [splitsingen, setSplitsingen] = useState<SplitsingDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)

  useEffect(() => {
    let actief = true
    haalSplitsingen(administratieId, rekeningId)
      .then((data) => {
        if (actief) setSplitsingen(data.splitsingen)
      })
      .catch((err: unknown) => {
        if (actief) setFout(err instanceof Error ? err.message : 'Splitsingen laden mislukt')
      })
    return () => {
      actief = false
    }
  }, [administratieId, rekeningId, herlaadSleutel])

  if (!fout && (splitsingen === null || splitsingen.length === 0)) return null

  return (
    <div className="panel">
      <h2>Gesplitste mutaties</h2>
      {fout && (
        <p className="hint" style={{ color: 'var(--red)' }}>
          {fout}
        </p>
      )}
      <div style={{ display: 'grid', gap: 14 }}>
        {(splitsingen ?? []).map((s) => (
          <SplitsingWeergave
            key={s.splitsing_id}
            administratieId={administratieId}
            splitsing={s}
            onBijgewerkt={(nieuw) =>
              setSplitsingen((huidig) => (huidig ?? []).map((x) => (x.splitsing_id === nieuw.splitsing_id ? nieuw : x)))
            }
          />
        ))}
      </div>
      <div className="hint">
        Half verwerkt = een deel is blijven hangen (fout zichtbaar per deel) — “Hervatten” voert de resterende delen
        alsnog uit tegen de verse RLZ-staat, nooit stil. Een afletter-deel is niet via de API te storneren (storno
        actie 19 in Reeleezee zelf); grootboek- en relatie-delen wel, met verplichte reden.
      </div>
    </div>
  )
}
