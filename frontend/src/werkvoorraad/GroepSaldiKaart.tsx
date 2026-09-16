import { useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import { Badge } from '../ui/basis'
import { euro, haalGroepSaldiOp, type GroepSaldiDto } from './groepSaldiApi'

/* Kaart "Groepssaldi" bovenaan de klantenlijst zodra het Groep-filter actief is (Peter 16-09: "kan jij voor mij van de
 * Kempengroep een huidig saldo van de (cumulatieve) debiteuren en crediteuren geven?"). KP7: administratie is een filter,
 * de groep is er één meer — geen nieuwe pagina, geen knop "verversen" (regel 08-09): de bron is de nachtelijke stand
 * (sync-alles), label "stand van vannacht (dd-mm)". Drie kolommen, controleerbaar: bruto = zonder intercompany +
 * intercompany. Uitklap per administratie mét rekeningen en status; geen debiteur-/crediteurnamen. Groep onbekend of
 * nog geen stand = leesbare regel, nooit stil leeg. */

function datumKort(iso: string): string {
  const d = new Date(`${iso}T00:00:00`)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('nl-NL', { day: '2-digit', month: '2-digit' })
}

const STATUS_TEKST: Record<string, string> = {
  geen_rekening: 'geen debiteuren-/crediteurenrekening gevonden',
  ongeldig: 'RLZ-blokkering — meting ongeldig',
  fout: 'meting mislukt',
  overgeslagen: 'overgeslagen',
}

export function GroepSaldiKaart({ groepId }: { groepId: string }) {
  const [stand, setStand] = useState<GroepSaldiDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    let actief = true
    setStand(null)
    setFout(null)
    haalGroepSaldiOp(groepId)
      .then((d) => actief && setStand(d))
      .catch((err: unknown) => {
        if (!actief) return
        setFout(err instanceof ApiError ? err.message : 'Groepssaldi niet te laden.')
      })
    return () => {
      actief = false
    }
  }, [groepId])

  if (fout) {
    return (
      <div className="panel" data-testid="groep-saldi-kaart" role="status" style={{ marginBottom: 12, padding: '10px 14px' }}>
        <b>Groepssaldi</b> — {fout}
      </div>
    )
  }
  if (!stand) return null

  const t = stand.totalen
  const nietOk = stand.rijen.filter((r) => r.status !== 'ok')
  const geenStand = stand.rijen.length === 0
  const scopeTekst =
    stand.aantal_in_scope < stand.aantal_leden
      ? `${stand.aantal_in_scope} van ${stand.aantal_leden} administraties in je scope`
      : `${stand.aantal_leden} administraties`

  return (
    <div className="panel" data-testid="groep-saldi-kaart" style={{ marginBottom: 12, padding: '10px 14px' }}>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <b>Groepssaldi · {stand.groep.naam}</b>
        <span className="text-muted text-[12.5px]">
          {geenStand ? 'nog geen stand — volgt na de nachtelijke run' : `stand van vannacht (${datumKort(stand.datum)})`} · {scopeTekst}
          {stand.zonder_stand > 0 && !geenStand ? ` · ${stand.zonder_stand} zonder stand` : ''}
        </span>
        {nietOk.length > 0 && <Badge variant="warn">{nietOk.length} niet in het totaal</Badge>}
        <button type="button" className="linkbtn ml-auto" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {open ? '▾ per administratie' : '▸ per administratie'}
        </button>
      </div>
      {!geenStand && (
        <div className="tabel-scroll" style={{ marginTop: 6 }}>
          <table style={{ width: 'auto', minWidth: 520 }} data-testid="groep-saldi-totalen">
            <thead>
              <tr>
                <th></th>
                <th style={{ textAlign: 'right' }}>Bruto</th>
                <th style={{ textAlign: 'right' }}>Intercompany</th>
                <th style={{ textAlign: 'right' }}>Zonder intercompany</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Debiteuren</td>
                <td style={{ textAlign: 'right' }}>{euro(t.debiteuren)}</td>
                <td style={{ textAlign: 'right' }}>{euro(t.debiteuren_ic)}</td>
                <td style={{ textAlign: 'right' }}>
                  <b>{euro(t.debiteuren_zonder_ic)}</b>
                </td>
              </tr>
              <tr>
                <td>Crediteuren</td>
                <td style={{ textAlign: 'right' }}>{euro(t.crediteuren)}</td>
                <td style={{ textAlign: 'right' }}>{euro(t.crediteuren_ic)}</td>
                <td style={{ textAlign: 'right' }}>
                  <b>{euro(t.crediteuren_zonder_ic)}</b>
                </td>
              </tr>
            </tbody>
          </table>
          <div className="hint" style={{ marginTop: 4 }}>
            Bruto = zonder intercompany + intercompany; intercompany = open posten op groepsmaatschappijen in deze groep. Totaal over{' '}
            {t.aantal_geldig} {t.aantal_geldig === 1 ? 'administratie' : 'administraties'} met een geldige stand.
          </div>
        </div>
      )}
      {open && (
        <div className="tabel-scroll" style={{ marginTop: 8 }} data-testid="groep-saldi-per-administratie">
          <table style={{ minWidth: 760 }}>
            <thead>
              <tr>
                <th>Administratie</th>
                <th style={{ textAlign: 'right' }}>Deb. bruto</th>
                <th style={{ textAlign: 'right' }}>Deb. IC</th>
                <th style={{ textAlign: 'right' }}>Cred. bruto</th>
                <th style={{ textAlign: 'right' }}>Cred. IC</th>
                <th>Rekeningen / status</th>
              </tr>
            </thead>
            <tbody>
              {stand.rijen.map((r) => (
                <tr key={r.administratie_id} style={{ opacity: r.status === 'ok' ? 1 : 0.75 }}>
                  <td>{r.naam}</td>
                  <td style={{ textAlign: 'right' }}>{euro(r.debiteuren)}</td>
                  <td style={{ textAlign: 'right' }}>{euro(r.debiteuren_ic)}</td>
                  <td style={{ textAlign: 'right' }}>{euro(r.crediteuren)}</td>
                  <td style={{ textAlign: 'right' }}>{euro(r.crediteuren_ic)}</td>
                  <td className="text-[12px] text-muted">
                    {r.status === 'ok'
                      ? `${r.debiteuren_rekening ?? '—'} · ${r.crediteuren_rekening ?? '—'}`
                      : `${STATUS_TEKST[r.status] ?? r.status}${r.detail ? ` — ${r.detail}` : ''}`}
                  </td>
                </tr>
              ))}
              {stand.rijen.length === 0 && (
                <tr>
                  <td colSpan={6} className="hint">
                    Nog geen stand voor de administraties in je scope.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
