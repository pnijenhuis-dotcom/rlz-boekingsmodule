import { useCallback, useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import type { AdministratieDto } from '../api/types'
import {
  bevestigSplitsing,
  haalVerzamelbakOp,
  hoortNietBijOns,
  wijsSplitsingAf,
  wijsToe,
  type VerzamelbakItemDto,
} from './intakeApi'

function formatDatum(iso: string): string {
  return new Date(iso).toLocaleString('nl-NL', { dateStyle: 'medium', timeStyle: 'short' })
}

/** Verzamelbak "Niet toegewezen" (mockup werkvoorraad-paneel): platform-breed — alles wat de
 * intake niet eenduidig kon koppelen, zichtbaar tot een mens beslist. Leeg = paneel onzichtbaar
 * (mockup). Toewijzen leert het geheugen; "hoort niet bij ons" vereist een reden; een
 * splitsingsvoorstel wordt hier bevestigd of afgewezen — nooit stil auto-verwerkt. */
export function VerzamelbakPaneel({
  administraties,
  onGewijzigd,
}: {
  administraties: AdministratieDto[]
  onGewijzigd?: () => void
}) {
  const [items, setItems] = useState<VerzamelbakItemDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [keuze, setKeuze] = useState<Record<string, string>>({})
  const [bezig, setBezig] = useState<string | null>(null)
  const [redenVoor, setRedenVoor] = useState<VerzamelbakItemDto | null>(null)
  const [reden, setReden] = useState('')

  const laad = useCallback(() => {
    haalVerzamelbakOp()
      .then((data) => setItems(data.items))
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Onbekende fout'))
  }, [])

  useEffect(() => {
    laad()
  }, [laad])

  const actie = async (documentId: string, werk: () => Promise<unknown>) => {
    setBezig(documentId)
    setFout(null)
    try {
      await werk()
      laad()
      onGewijzigd?.()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Actie mislukt.')
    } finally {
      setBezig(null)
    }
  }

  if (items === null || items.length === 0) {
    // Mockup: leeg = paneel onzichtbaar. Een laadfout tonen we wel — nooit stil.
    return fout ? <div className="fout">Verzamelbak niet beschikbaar: {fout}</div> : null
  }

  return (
    <div className="panel" style={{ borderLeft: '3px solid var(--orange)' }}>
      <h2>Niet toegewezen — handmatig koppelen ({items.length})</h2>
      {fout && <div className="fout">{fout}</div>}
      <table>
        <tbody>
          <tr>
            <th>Document</th>
            <th>Binnengekomen via</th>
            <th>Tenaamstelling / suggestie</th>
            <th>Toewijzen aan</th>
            <th />
          </tr>
          {items.map((item) => {
            const suggestieNaam = administraties.find((a) => a.id === item.suggestie_administratie_id)?.naam
            const gekozen = keuze[item.document_id] ?? item.suggestie_administratie_id ?? ''
            return (
              <tr key={item.document_id}>
                <td>
                  {item.bestandsnaam}
                  {item.soort !== 'inkoopfactuur' && (
                    <div>
                      <span className="chip klaar">{item.soort}</span>
                    </div>
                  )}
                  {item.splitsing_voorstel && (
                    <div style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 4 }}>
                      Splitsingsvoorstel: {item.splitsing_voorstel.length} facturen —{' '}
                      {item.splitsing_voorstel
                        .map((s) => `p.${s.start_pagina}-${s.eind_pagina} ${s.tenaamstelling ?? '?'}`)
                        .join(' · ')}
                    </div>
                  )}
                </td>
                <td>
                  {item.bron === 'email' ? 'e-mail' : 'upload'}
                  {item.afzender_hint ? ` · ${item.afzender_hint}` : ''}
                  <div style={{ fontSize: 11, color: 'var(--muted)' }}>{formatDatum(item.aangemaakt_op)}</div>
                </td>
                <td>
                  {item.tenaamstelling ? (
                    <span>&ldquo;{item.tenaamstelling}&rdquo;</span>
                  ) : (
                    <span className="chip vraag">geen tenaamstelling gelezen</span>
                  )}
                  {suggestieNaam && (
                    <div>
                      <span className="chip ai">suggestie: {suggestieNaam}</span>
                    </div>
                  )}
                </td>
                <td>
                  {item.splitsing_voorstel ? (
                    <span className="hint" style={{ margin: 0 }}>
                      eerst de splitsing beoordelen
                    </span>
                  ) : (
                    <select
                      aria-label={`Toewijzen aan voor ${item.bestandsnaam}`}
                      value={gekozen}
                      onChange={(e) => setKeuze((k) => ({ ...k, [item.document_id]: e.target.value }))}
                    >
                      <option value="">— kies administratie —</option>
                      {administraties.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.naam}
                        </option>
                      ))}
                    </select>
                  )}
                </td>
                <td style={{ whiteSpace: 'nowrap' }}>
                  {item.splitsing_voorstel && item.splitsing_id ? (
                    <>
                      <button
                        type="button"
                        className="btn"
                        style={{ padding: '5px 12px' }}
                        disabled={bezig === item.document_id}
                        onClick={() =>
                          void actie(item.document_id, () =>
                            bevestigSplitsing(
                              item.splitsing_id!,
                              item.splitsing_voorstel!.map((s) => ({
                                start_pagina: s.start_pagina,
                                eind_pagina: s.eind_pagina,
                                tenaamstelling: s.tenaamstelling,
                              })),
                            ),
                          )
                        }
                      >
                        Splitsing bevestigen ✓
                      </button>{' '}
                      <button
                        type="button"
                        className="btn secondary"
                        style={{ padding: '5px 12px' }}
                        disabled={bezig === item.document_id}
                        onClick={() =>
                          void actie(item.document_id, () => wijsSplitsingAf(item.splitsing_id!, null))
                        }
                      >
                        Is één factuur
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        className="btn"
                        style={{ padding: '5px 12px' }}
                        disabled={!gekozen || bezig === item.document_id}
                        onClick={() => void actie(item.document_id, () => wijsToe(item.document_id, gekozen))}
                      >
                        Toewijzen ✓
                      </button>{' '}
                      <button
                        type="button"
                        className="btn secondary"
                        style={{ padding: '5px 12px' }}
                        disabled={bezig === item.document_id}
                        onClick={() => {
                          setReden('')
                          setRedenVoor(item)
                        }}
                      >
                        Hoort niet bij ons
                      </button>
                    </>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <div className="hint">
        Alles wat de intake niet eenduidig aan een administratie kan koppelen komt hier terecht — er raakt
        nooit iets kwijt. Elke handmatige toewijzing wordt onthouden: dezelfde tenaamstelling of afzender
        wordt de volgende keer automatisch gekoppeld.
      </div>

      {redenVoor && (
        <div className="modal-bg open">
          <div className="modal">
            <h2>Hoort niet bij ons — {redenVoor.bestandsnaam}</h2>
            <div className="row">
              <label htmlFor="niet-van-ons-reden">Reden (verplicht)</label>
              <textarea
                id="niet-van-ons-reden"
                rows={3}
                value={reden}
                onChange={(e) => setReden(e.target.value)}
                placeholder="Bijv.: factuur voor een ander kantoor / geen klant van ons"
              />
            </div>
            <div className="actions">
              <button type="button" className="btn secondary" onClick={() => setRedenVoor(null)}>
                Annuleren
              </button>
              <button
                type="button"
                className="btn warn"
                disabled={!reden.trim()}
                onClick={() => {
                  const doel = redenVoor
                  setRedenVoor(null)
                  void actie(doel.document_id, () => hoortNietBijOns(doel.document_id, reden.trim()))
                }}
              >
                Vastleggen ✓
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
