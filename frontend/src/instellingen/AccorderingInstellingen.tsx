import { useCallback, useEffect, useState } from 'react'
import {
  haalAccorderingInstellingen,
  haalAccorderingKandidaten,
  haalApparaten,
  haalStaandeRegels,
  trekApparaatIn,
  trekStaandeRegelIn,
  zetAccorderingInstellingen,
  type ApparaatDto,
  type KandidaatDto,
  type StaandeRegelDto,
} from '../accordering/accorderingApi'
import { Select, Switch } from '../ui/basis'

interface LaagInvoer {
  accordeurId: string
  drempel: string
}

function formatMoment(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('nl-NL', { dateStyle: 'short', timeStyle: 'short' })
}

/** Geregistreerde apparaten (passkeys) per accordeur + kill-switch (blok 1c/4 accordeur-PWA,
 * besluit 2026-08-11): intrekken trekt de passkey én alle sessies van dat apparaat per direct
 * in (server-side, geauditeerd). Beheerder-only — het endpoint weigert andere rollen. */
function AccordeurApparaten({ kandidaten }: { kandidaten: KandidaatDto[] }) {
  const [perGebruiker, setPerGebruiker] = useState<Record<string, ApparaatDto[]>>({})
  const [fout, setFout] = useState<string | null>(null)

  const laad = useCallback(() => {
    setFout(null)
    Promise.all(kandidaten.map(async (k) => [k.id, (await haalApparaten(k.id)).apparaten] as const))
      .then((paren) => setPerGebruiker(Object.fromEntries(paren)))
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Apparaten laden mislukt'))
  }, [kandidaten])

  useEffect(() => {
    if (kandidaten.length > 0) laad()
  }, [kandidaten, laad])

  const intrekken = async (apparaatId: string) => {
    setFout(null)
    try {
      await trekApparaatIn(apparaatId)
      laad()
    } catch (err) {
      setFout(err instanceof Error ? err.message : 'Intrekken mislukt')
    }
  }

  if (kandidaten.length === 0) return null
  const rijen = kandidaten.flatMap((k) => (perGebruiker[k.id] ?? []).map((a) => ({ kandidaat: k, apparaat: a })))

  return (
    <>
      <h3 style={{ margin: '6px 0 0' }}>Geregistreerde apparaten (passkeys)</h3>
      {fout && <div className="fout">{fout}</div>}
      {rijen.length === 0 ? (
        <p className="hint" style={{ margin: 0 }}>
          Nog geen geregistreerde apparaten — een accordeur registreert zijn toestel bij de activering of de
          eerste login.
        </p>
      ) : (
        <>
          <table>
            <thead>
              <tr>
                <th>Accordeur</th>
                <th>Apparaat</th>
                <th>Geregistreerd</th>
                <th>Laatst gebruikt</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rijen.map(({ kandidaat, apparaat }) => (
                <tr key={apparaat.id}>
                  <td>{kandidaat.naam}</td>
                  <td>
                    {apparaat.apparaat_naam ?? 'Onbekend apparaat'}
                    {apparaat.is_dev_stub && <span className="chip"> dev-stub</span>}
                  </td>
                  <td>{formatMoment(apparaat.aangemaakt_op)}</td>
                  <td>{formatMoment(apparaat.laatst_gebruikt_op)}</td>
                  <td>
                    {apparaat.ingetrokken_op ? (
                      <span className="chip">ingetrokken</span>
                    ) : (
                      <span className="chip geheugen">actief</span>
                    )}
                  </td>
                  <td>
                    {!apparaat.ingetrokken_op && (
                      <button
                        type="button"
                        className="btn secondary"
                        onClick={() => void intrekken(apparaat.id)}
                      >
                        Toegang intrekken
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="hint" style={{ margin: 0 }}>
            Intrekken (kill-switch) blokkeert dit apparaat per direct: de passkey én alle lopende sessies
            vervallen — de accordeur kan alleen opnieuw beginnen via wachtwoord + nieuwe registratie.
          </div>
        </>
      )}
    </>
  )
}

/** Accordering-beheer voor één administratie (mockup #autorisatie, Beheerder-only): toggle,
 * sequentiële lagen met bedragdrempels, en de staande goedkeuringen (zichtbaar + intrekbaar —
 * besluit 2026-08-08). Sequentieel: laag 1 eerst, laag 2 alleen als de drempelvoorwaarde
 * geldt. */
function AdministratieAccordering({ administratieId, naam }: { administratieId: string; naam: string }) {
  const [geladen, setGeladen] = useState(false)
  const [ingeschakeld, setIngeschakeld] = useState(false)
  const [lagen, setLagen] = useState<LaagInvoer[]>([])
  const [kandidaten, setKandidaten] = useState<KandidaatDto[]>([])
  const [staandeRegels, setStaandeRegels] = useState<StaandeRegelDto[]>([])
  const [fout, setFout] = useState<string | null>(null)
  const [melding, setMelding] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)

  const laad = useCallback(() => {
    setFout(null)
    Promise.all([
      haalAccorderingInstellingen(administratieId),
      haalAccorderingKandidaten(administratieId),
      haalStaandeRegels(administratieId),
    ])
      .then(([instellingen, kandidatenDto, regelsDto]) => {
        setIngeschakeld(instellingen.ingeschakeld)
        setLagen(
          instellingen.lagen.map((laag) => ({
            accordeurId: laag.accordeur_gebruiker_id,
            drempel: laag.bedrag_drempel ?? '',
          })),
        )
        setKandidaten(kandidatenDto.kandidaten)
        setStaandeRegels(regelsDto.regels)
        setGeladen(true)
      })
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Onbekende fout'))
  }, [administratieId])

  const opslaan = async () => {
    setBezig(true)
    setFout(null)
    setMelding(null)
    try {
      await zetAccorderingInstellingen(administratieId, {
        ingeschakeld,
        lagen: lagen
          .filter((laag) => laag.accordeurId)
          .map((laag, index) => ({
            volgnummer: index + 1,
            accordeur_gebruiker_id: laag.accordeurId,
            bedrag_drempel: laag.drempel ? laag.drempel.replace(',', '.') : null,
          })),
      })
      setMelding('Opgeslagen.')
      laad()
    } catch (err) {
      setFout(err instanceof Error ? err.message : 'Opslaan mislukt')
    } finally {
      setBezig(false)
    }
  }

  const regelIntrekken = async (regelId: string) => {
    setFout(null)
    try {
      await trekStaandeRegelIn(administratieId, regelId)
      laad()
    } catch (err) {
      setFout(err instanceof Error ? err.message : 'Intrekken mislukt')
    }
  }

  return (
    <details onToggle={(e) => (e.target as HTMLDetailsElement).open && !geladen && laad()}>
      <summary style={{ cursor: 'pointer', padding: '6px 0' }}>
        <b>{naam}</b>
      </summary>
      {fout && <div className="fout">{fout}</div>}
      {!geladen && !fout ? (
        <p className="hint">Laden…</p>
      ) : geladen ? (
        <div style={{ display: 'grid', gap: 10, padding: '6px 0 12px' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0 }}>
            <Switch checked={ingeschakeld} onChange={(e) => setIngeschakeld(e.target.checked)} />
            Goedkeuring door klant vereist (boekknop wordt &ldquo;Ter accordering&rdquo;)
          </label>
          {kandidaten.length === 0 && (
            <p className="hint" style={{ margin: 0 }}>
              Geen klant-accordeurs met toegang tot deze administratie — nodig eerst een gebruiker uit met de rol
              Klant-accordeur en koppel die aan deze administratie.
            </p>
          )}
          {lagen.map((laag, index) => (
            <div key={index} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <span style={{ minWidth: 52 }}>Laag {index + 1}</span>
              <Select
                aria-label={`Accordeur laag ${index + 1}`}
                value={laag.accordeurId}
                onChange={(e) =>
                  setLagen((huidig) =>
                    huidig.map((l, i) => (i === index ? { ...l, accordeurId: e.target.value } : l)),
                  )
                }
              >
                <option value="">— kies accordeur —</option>
                {kandidaten.map((k) => (
                  <option key={k.id} value={k.id}>
                    {k.naam}
                  </option>
                ))}
              </Select>
              <input
                aria-label={`Bedragdrempel laag ${index + 1}`}
                placeholder="drempel (leeg = alle facturen)"
                style={{ width: 220 }}
                value={laag.drempel}
                onChange={(e) =>
                  setLagen((huidig) => huidig.map((l, i) => (i === index ? { ...l, drempel: e.target.value } : l)))
                }
              />
              <button
                type="button"
                className="btn secondary"
                onClick={() => setLagen((huidig) => huidig.filter((_, i) => i !== index))}
              >
                Verwijderen
              </button>
            </div>
          ))}
          <div className="actions" style={{ margin: 0 }}>
            <button
              type="button"
              className="btn secondary"
              onClick={() => setLagen((huidig) => [...huidig, { accordeurId: '', drempel: '' }])}
            >
              + Laag toevoegen
            </button>
            <button type="button" className="btn" disabled={bezig} onClick={() => void opslaan()}>
              {bezig ? 'Opslaan…' : 'Opslaan'}
            </button>
            {melding && <span className="hint">{melding}</span>}
          </div>
          <div className="hint" style={{ margin: 0 }}>
            Sequentieel: eerst laag 1 akkoord, dan pas laag 2 (indien de drempelvoorwaarde geldt). Na het laatste
            akkoord boekt de motor automatisch — de harde checks draaien dan onverkort opnieuw.
          </div>
          {staandeRegels.length > 0 && (
            <>
              <h3 style={{ margin: '6px 0 0' }}>Staande goedkeuringen</h3>
              <table>
                <thead>
                  <tr>
                    <th>Accordeur</th>
                    <th>Leverancier</th>
                    <th className="amount">Bedrag (exact)</th>
                    <th>Status</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {staandeRegels.map((regel) => (
                    <tr key={regel.id}>
                      <td>{regel.accordeur_naam ?? regel.accordeur_gebruiker_id}</td>
                      <td>{regel.leverancier_naam ?? regel.vendor_id}</td>
                      <td className="amount">€ {regel.bedrag}</td>
                      <td>
                        {regel.actief ? (
                          <span className="chip geheugen">actief</span>
                        ) : (
                          <span className="chip">ingetrokken</span>
                        )}
                      </td>
                      <td>
                        {regel.actief && (
                          <button
                            type="button"
                            className="btn secondary"
                            onClick={() => void regelIntrekken(regel.id)}
                          >
                            Intrekken
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="hint" style={{ margin: 0 }}>
                Een staande goedkeuring vervangt alleen de akkoord-klik van die accordeur bij exact hetzelfde
                bedrag van dezelfde leverancier — de harde checks (duplicaat, IBAN-wissel, regels) blijven
                onverkort blokkerend. Afwijkend bedrag = gewoon ter accordering.
              </div>
            </>
          )}
          <AccordeurApparaten kandidaten={kandidaten} />
        </div>
      ) : null}
    </details>
  )
}

export function AccorderingInstellingen({
  administraties,
}: {
  administraties: { id: string; naam: string }[]
}) {
  return (
    <div className="panel" style={{ marginTop: 16 }}>
      <h2>Klant-accordering (goedkeuring door klanten)</h2>
      <p className="hint" style={{ marginTop: 4 }}>
        Optioneel per administratie (mockup Autorisatie): accordeurs in sequentiële lagen, met optionele
        bedragdrempel per laag. De accordeur werkt straks in de mobiele goedkeur-app; dit is het kantoorbeheer.
      </p>
      {administraties.map((a) => (
        <AdministratieAccordering key={a.id} administratieId={a.id} naam={a.naam} />
      ))}
    </div>
  )
}
