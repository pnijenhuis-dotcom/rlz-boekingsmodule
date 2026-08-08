import { useCallback, useState } from 'react'
import {
  haalAccorderingInstellingen,
  haalAccorderingKandidaten,
  haalStaandeRegels,
  trekStaandeRegelIn,
  zetAccorderingInstellingen,
  type KandidaatDto,
  type StaandeRegelDto,
} from '../accordering/accorderingApi'

interface LaagInvoer {
  accordeurId: string
  drempel: string
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
            <input
              type="checkbox"
              style={{ width: 'auto' }}
              checked={ingeschakeld}
              onChange={(e) => setIngeschakeld(e.target.checked)}
            />
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
              <select
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
              </select>
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
