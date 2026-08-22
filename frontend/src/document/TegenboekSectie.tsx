import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import type { TegenboekToetsDto } from '../api/types'
import { haalTegenboekToetsOp, voerTegenboekingUit } from './tegenboekenApi'

interface Props {
  administratieId: string
  documentId: string
  status: string
  soort: string
  onGewijzigd: () => void
}

function euro(bedrag: string | number): string {
  return Number(bedrag).toLocaleString('nl-NL', { style: 'currency', currency: 'EUR' })
}

/** Tegenboek-sectie op het documentdetail (mockup tegenboek-mockup.html 1-op-1, akkoord Peter
 * 22-08 — besluit: géén suppletie-signaal). Alleen zichtbaar op een GEBOEKTE inkoopfactuur, en
 * de knop "Tegenboeken…" verschijnt alléén als storno door de aangifte-poort geblokkeerd is
 * (anders is stornering in Reeleezee de route — bestaand gedrag, ongewijzigd). Eén scherm,
 * geen wizard: keuze volledig/vervang, voorbeeld van de tegenboeking, btw-effect,
 * betaalstatus-waarschuwing (alleen als het origineel (deels) afgeletterd is), verplichte
 * reden, boeken. Ná een tegenboeking toont de sectie de chip TEGENGEBOEKT mét kruisverwijzing
 * (boekstuknummer + reden — de tijdlijn draagt hetzelfde detail). ?tegenboeken=1 in de URL
 * (het ⋯-menu in het archief) opent de flow direct. */
export function TegenboekSectie({ administratieId, documentId, status, soort, onGewijzigd }: Props) {
  const relevant = status === 'geboekt' && soort === 'inkoopfactuur'
  const [searchParams, setSearchParams] = useSearchParams()
  const [toets, setToets] = useState<TegenboekToetsDto | 'laden' | 'fout'>('laden')
  const [open, setOpen] = useState(false)
  const [keuze, setKeuze] = useState<'volledig' | 'vervang'>('volledig')
  const [reden, setReden] = useState('')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [geslaagd, setGeslaagd] = useState<string | null>(null)
  const autoOpen = searchParams.get('tegenboeken') === '1'

  useEffect(() => {
    if (!relevant) return
    let actief = true
    setToets('laden')
    haalTegenboekToetsOp(administratieId, documentId)
      .then((dto) => {
        if (actief) setToets(dto)
      })
      .catch(() => {
        // Faalvriendelijk: de sectie is verrijking op het detailscherm — maar bij een expliciete
        // ⋯-menu-ingang (?tegenboeken=1) tonen we de fout wél (anders lijkt de actie te ontbreken).
        if (actief) setToets('fout')
      })
    return () => {
      actief = false
    }
  }, [administratieId, documentId, relevant])

  useEffect(() => {
    if (autoOpen && typeof toets === 'object' && toets.storno_geblokkeerd && !toets.tegenboeking) {
      setOpen(true)
    }
  }, [autoOpen, toets])

  if (!relevant) return null
  if (toets === 'laden') return null
  if (toets === 'fout') {
    if (!autoOpen) return null
    return (
      <div className="panel">
        <h2>Tegenboeken</h2>
        <p className="hint">De tegenboek-toets kon niet geladen worden — probeer het opnieuw vanaf het archief.</p>
      </div>
    )
  }

  const bestaande = toets.tegenboeking
  const betaald = toets.betaalstatus !== null && Number(toets.betaalstatus.betaald_bedrag) !== 0
  const deels = betaald && !toets.betaalstatus!.volledig_afgeletterd

  if (bestaande) {
    return (
      <div className="panel">
        <h2>
          Tegenboeking <span className="chip afwijking">TEGENGEBOEKT</span>
        </h2>
        <p style={{ margin: '4px 0' }}>
          Deze boeking is tegengeboekt ({bestaande.soort === 'vervang' ? 'tegenboeken én opnieuw boeken' : 'volledig'})
          — tegenboeking <b>{bestaande.rlz_boekstuknummer ?? bestaande.rlz_tegenboeking_id}</b>, referentie{' '}
          <b>{toets.tegenboek_referentie}</b>. Kruisverwijzing staat óók in de tijdlijn en het audit-log.
        </p>
        <p className="hint" style={{ margin: 0 }}>
          reden: &ldquo;{bestaande.reden}&rdquo;
        </p>
      </div>
    )
  }

  if (!toets.storno_geblokkeerd) return null

  const sluit = () => {
    setOpen(false)
    setFout(null)
    if (autoOpen) {
      const p = new URLSearchParams(searchParams)
      p.delete('tegenboeken')
      setSearchParams(p, { replace: true })
    }
  }

  const boek = async () => {
    setBezig(true)
    setFout(null)
    try {
      const resultaat = await voerTegenboekingUit(administratieId, documentId, { soort: keuze, reden })
      setGeslaagd(
        keuze === 'vervang'
          ? `Tegenboeking ${resultaat.rlz_boekstuknummer ?? ''} geboekt — het document staat weer in de werkvoorraad om opnieuw te boeken.`
          : `Tegenboeking ${resultaat.rlz_boekstuknummer ?? ''} geboekt — origineel gemarkeerd TEGENGEBOEKT (kruisverwijzing beide kanten).`,
      )
      sluit()
      onGewijzigd()
      // Toets verversen zodat de chip + kruisverwijzing meteen zichtbaar zijn.
      haalTegenboekToetsOp(administratieId, documentId)
        .then(setToets)
        .catch(() => undefined)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Tegenboeken mislukt — probeer het opnieuw.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <div className="panel">
      <h2>Corrigeren ná ingediende btw-aangifte</h2>
      {geslaagd && <p className="hint" style={{ color: 'var(--ok)' }}>{geslaagd}</p>}
      <p style={{ margin: '4px 0 10px' }}>
        ⚠️ <b>Storno niet mogelijk:</b> {toets.blokkade_melding ?? 'de btw-aangifte over deze periode is definitief ingediend'}.
        Corrigeren kan via een <b>tegenboeking</b> in de huidige open periode — het origineel blijft staan, de
        btw-correctie telt mee in de eerstvolgende aangifte.
      </p>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button type="button" className="btn secondary" disabled title={toets.blokkade_melding ?? undefined}>
          Storneren (geblokkeerd)
        </button>
        {!open && (
          <button type="button" className="btn" onClick={() => setOpen(true)}>
            Tegenboeken…
          </button>
        )}
      </div>

      {open && (
        <div style={{ marginTop: 14 }}>
          {/* Keuze: volledig tegenboeken / tegenboeken én opnieuw boeken (mockup, één scherm). */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 10, marginBottom: 14 }}>
            {(
              [
                {
                  waarde: 'volledig' as const,
                  titel: 'Volledig tegenboeken',
                  uitleg:
                    'De boeking hoort er helemaal niet te zijn (dubbel, verkeerde administratie). Er komt één omgekeerde boeking; daarna is het saldo-effect nul.',
                },
                {
                  waarde: 'vervang' as const,
                  titel: 'Tegenboeken én opnieuw boeken',
                  uitleg:
                    'De boeking was fout (bedrag, grootboek, btw). Na de tegenboeking staat het document klaar in de werkvoorraad om opnieuw — correct — te boeken.',
                },
              ]
            ).map((optie) => (
              <label
                key={optie.waarde}
                style={{
                  border: `1.5px solid ${keuze === optie.waarde ? 'var(--primary)' : 'var(--border)'}`,
                  background: keuze === optie.waarde ? 'var(--accent-bg)' : undefined,
                  borderRadius: 11,
                  cursor: 'pointer',
                  display: 'block',
                  padding: 14,
                }}
              >
                <input
                  type="radio"
                  name="tegenboek-soort"
                  checked={keuze === optie.waarde}
                  onChange={() => setKeuze(optie.waarde)}
                  style={{ display: 'none' }}
                />
                <b style={{ display: 'block', fontSize: 13, marginBottom: 3 }}>{optie.titel}</b>
                <span style={{ fontSize: 12, color: 'var(--muted)' }}>{optie.uitleg}</span>
              </label>
            ))}
          </div>

          <h3 style={{ fontSize: 12.5, margin: '0 0 6px' }}>
            Voorbeeld van de tegenboeking (boekdatum vandaag, eerstvolgende open aangifte-periode)
          </h3>
          <div className="tabel-scroll">
            <table>
              <thead>
                <tr>
                  <th>Grootboek</th>
                  <th>Omschrijving</th>
                  <th className="amount">Netto</th>
                  <th className="amount">Btw</th>
                </tr>
              </thead>
              <tbody>
                {toets.voorbeeld.map((regel, i) => (
                  <tr key={i}>
                    <td>
                      {regel.grootboek_code ?? '—'}
                      {regel.grootboek_naam ? ` ${regel.grootboek_naam}` : ''}
                    </td>
                    <td>{regel.omschrijving}</td>
                    <td className="amount" style={{ color: 'var(--danger)', fontWeight: 600 }}>
                      {euro(regel.netto_bedrag)}
                    </td>
                    <td className="amount" style={{ color: 'var(--danger)', fontWeight: 600 }}>
                      {euro(regel.btw_bedrag)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="hint" style={{ marginTop: 10 }}>
            ℹ️ Btw-effect: <b>{euro(toets.totaal_btw)}</b> telt mee in de eerstvolgende open aangifte — geen verdere
            actie nodig. Referentie tegenboeking: <b>{toets.tegenboek_referentie}</b>.
          </p>

          {betaald && toets.betaalstatus && (
            <p style={{ background: 'var(--warn-bg)', borderRadius: 10, color: 'var(--warn)', fontSize: 12.5, margin: '10px 0', padding: '10px 14px' }}>
              ⚠️ <b>Betaalstatus origineel: {toets.betaalstatus.volledig_afgeletterd ? 'al afgeletterd' : 'deels betaald'}</b>
              {deels && (
                <>
                  {' '}
                  (betaald {euro(toets.betaalstatus.betaald_bedrag)} · openstaand {euro(toets.betaalstatus.open_bedrag)})
                </>
              )}
              . De tegenboeking laat een <b>open creditpost</b> achter — verreken die tegen een volgende factuur van
              deze leverancier, of laat terugbetalen. De post verschijnt in de open-postenlijst; hij verdwijnt niet
              stil.
            </p>
          )}

          {keuze === 'vervang' && (
            <p className="hint" style={{ margin: '10px 0' }}>
              De herboeking is gekoppeld aan de tegenboeking en wordt uitgezonderd van het duplicaatsignaal (zelfde
              leverancier, referentie en bedrag is dáár bewust) — de koppeling is zichtbaar in de tijdlijn.
            </p>
          )}

          <label style={{ display: 'block', fontSize: 12, fontWeight: 600, margin: '10px 0 5px' }} htmlFor="tegenboek-reden">
            Reden (verplicht, komt in audit en tijdlijn)
          </label>
          <textarea
            id="tegenboek-reden"
            value={reden}
            onChange={(e) => setReden(e.target.value)}
            placeholder="Bijv.: factuur dubbel geboekt — origineel zat al in periode april"
            style={{ minHeight: 56, width: '100%' }}
          />

          {fout && <div className="fout" style={{ marginTop: 8 }}>{fout}</div>}

          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 10 }}>
            <button type="button" className="btn secondary" onClick={sluit} disabled={bezig}>
              Annuleren
            </button>
            <button
              type="button"
              className="btn danger"
              onClick={() => void boek()}
              disabled={bezig || reden.trim().length < 5}
              title={reden.trim().length < 5 ? 'Reden is verplicht (minimaal 5 tekens)' : undefined}
            >
              {bezig ? 'Bezig…' : 'Tegenboeking boeken'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
