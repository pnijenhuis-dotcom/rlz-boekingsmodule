import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FoutMelding } from '../ui/FoutMelding'
import { haalBankOverzicht, type BankKlantDto } from './bankApi'

function formatDatumKort(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('nl-NL', { dateStyle: 'medium' })
}

/** Laatste bank-sync per administratie (blok 1, 08-09): datum + HH:MM. */
export function formatSyncTijd(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return `${d.toLocaleDateString('nl-NL', { day: '2-digit', month: '2-digit', year: 'numeric' })} ${d.toLocaleTimeString('nl-NL', { hour: '2-digit', minute: '2-digit' })}`
}

/** Tekst voor "nog geen sync": de nachtelijke lus (sync-alles 07:00) pakt élke actieve administratie mee —
 * niemand hoeft meer "de klant te openen om de eerste bank-sync te starten" (besluit Peter 08-09). */
export const NOG_NIET_GESYNCHRONISEERD = 'nog niet gesynchroniseerd — vannacht automatisch'

/** Bank-overzicht (mockup #bank): klanten met onverwerkte bankmutaties bovenaan (klik →
 * bankdetail); daaronder compact de overige administraties. Sinds blok 1 (08-09) draait de bank-sync
 * dagelijks automatisch voor álle administraties — het overzicht toont per administratie de laatste
 * sync-tijd; het openen van een klant ververst daarnaast direct (auto-verversing 25-08). */
export function BankOverzichtScreen() {
  const navigate = useNavigate()
  const [klanten, setKlanten] = useState<BankKlantDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [herlaadTeller, setHerlaadTeller] = useState(0)

  useEffect(() => {
    let actief = true
    setFout(null)
    setKlanten(null)
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
  }, [herlaadTeller])

  if (fout) {
    return (
      <div style={{ margin: 24 }}>
        <FoutMelding
          melding="Het bank-overzicht kon niet geladen worden."
          detail={fout}
          onOpnieuw={() => setHerlaadTeller((t) => t + 1)}
        />
      </div>
    )
  }
  if (klanten === null) {
    return (
      <div className="panel" style={{ margin: 24 }} aria-busy="true">
        <span className="skeleton" style={{ width: '35%', marginBottom: 10 }} />
        <span className="skeleton" style={{ width: '65%', marginBottom: 6 }} />
        <span className="skeleton" style={{ width: '55%' }} />
      </div>
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
                <th>Laatste sync</th>
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
                  <td className="hint">
                    {klant.ooit_gesynchroniseerd ? formatSyncTijd(klant.laatste_sync_op) : NOG_NIET_GESYNCHRONISEERD}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="hint">
          Alleen klanten met onverwerkte mutaties; volledig verwerkte klanten verschijnen hier pas weer bij nieuwe
          mutaties. De bank wordt elke nacht automatisch bijgewerkt uit Reeleezee (en bij het openen van een klant).
          Klik op een klant voor de rekeningen.
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
                      ? `geen open mutaties · laatste sync ${formatSyncTijd(klant.laatste_sync_op)}`
                      : NOG_NIET_GESYNCHRONISEERD}
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
