import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { haalBankOverzicht, type BankKlantDto } from './bankApi'

function formatDatumKort(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('nl-NL', { dateStyle: 'medium' })
}

/** Bank-overzicht (mockup #bank): klanten met onverwerkte bankmutaties bovenaan (klik →
 * bankdetail); daaronder compact de overige administraties — nodig om bij een klant zonder
 * eerdere sync de eerste synchronisatie te kunnen starten (bewuste, kleine uitbreiding op de
 * mockup die alleen "klanten mét open mutaties" toont). */
export function BankOverzichtScreen() {
  const navigate = useNavigate()
  const [klanten, setKlanten] = useState<BankKlantDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)

  useEffect(() => {
    let actief = true
    haalBankOverzicht()
      .then((data) => {
        if (actief) setKlanten(data.klanten)
      })
      .catch((err: unknown) => {
        if (actief) setFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
    return () => {
      actief = false
    }
  }, [])

  if (fout) {
    return (
      <div className="panel" style={{ margin: 24 }}>
        <p className="hint">Bank-overzicht kon niet geladen worden: {fout}</p>
      </div>
    )
  }
  if (klanten === null) {
    return (
      <p className="hint" style={{ padding: 24 }}>
        Laden…
      </p>
    )
  }

  const metOpen = klanten.filter((k) => k.open_mutaties > 0)
  const zonderOpen = klanten.filter((k) => k.open_mutaties === 0)

  return (
    <>
      <div className="topbar">
        <h1>Bank controleren</h1>
      </div>
      <div className="panel">
        <h2>Klanten met onverwerkte bankmutaties</h2>
        {metOpen.length === 0 ? (
          <p className="hint">Geen klanten met onverwerkte mutaties. 🎉</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Klant</th>
                <th>Rekeningen</th>
                <th>Onverwerkt</th>
                <th>Oudste onverwerkte</th>
              </tr>
            </thead>
            <tbody>
              {metOpen.map((klant) => (
                <tr
                  key={klant.administratie_id}
                  className="clickable"
                  onClick={() => navigate(`/bank/${klant.administratie_id}`)}
                >
                  <td>
                    <b>{klant.naam}</b>
                  </td>
                  <td>{klant.rekeningen.length > 0 ? klant.rekeningen.join(' · ') : '—'}</td>
                  <td>
                    <span className="chip ai">{klant.open_mutaties}</span>
                  </td>
                  <td>{formatDatumKort(klant.oudste_open_datum)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="hint">
          Alleen klanten met onverwerkte mutaties; volledig verwerkte klanten verschijnen hier pas weer bij nieuwe
          mutaties. Klik op een klant voor de rekeningen.
        </div>
      </div>

      {zonderOpen.length > 0 && (
        <div className="panel">
          <h2>Overige klanten</h2>
          <table>
            <tbody>
              {zonderOpen.map((klant) => (
                <tr
                  key={klant.administratie_id}
                  className="clickable"
                  onClick={() => navigate(`/bank/${klant.administratie_id}`)}
                >
                  <td>{klant.naam}</td>
                  <td className="hint" style={{ padding: '8px 10px' }}>
                    {klant.ooit_gesynchroniseerd
                      ? `geen open mutaties · laatste sync ${formatDatumKort(klant.laatste_sync_op)}`
                      : 'nog nooit gesynchroniseerd — open de klant om de eerste bank-sync te starten'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
