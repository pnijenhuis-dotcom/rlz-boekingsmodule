import { useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import type { CrediteurKvkDto, DubbelGroepDto, DubbeleCrediteurenResponseDto } from '../api/types'
import { AdministratieCombobox } from '../ui/AdministratieCombobox'
import { Badge, Button, SkeletonRegels } from '../ui/basis'
import { controleerCrediteurKvk, haalDubbeleCrediteurenOp } from './instellingenApi'

interface Props {
  administraties: { id: string; naam: string }[]
}

const SOORT_LABEL: Record<DubbelGroepDto['soort'], string> = {
  btw_nummer: 'zelfde btw-nummer',
  kvk_nummer: 'zelfde KvK-nummer',
  iban: 'zelfde IBAN',
  naam: 'zelfde naam (rechtsvorm/leestekens genegeerd)',
}

/** Instellingen › Crediteuren (punt 14, opruimrun 28-08): signalering van waarschijnlijk-dubbele
 * crediteuren per administratie — op btw-nummer, KvK-nummer, IBAN en genormaliseerde naam. Alleen
 * signaleren: samenvoegen gebeurt door een mens in RLZ, wij verwijderen niets (kernprincipe 3). De
 * KvK-knop hergebruikt de steigerbouw-A3-client en toont de officiële naam ter beoordeling. */
export function CrediteurDubbelen({ administraties }: Props) {
  const [administratieId, setAdministratieId] = useState('')
  const [data, setData] = useState<DubbeleCrediteurenResponseDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [laden, setLaden] = useState(false)
  const [kvk, setKvk] = useState<Record<string, CrediteurKvkDto | 'bezig' | { fout: string }>>({})

  useEffect(() => {
    if (!administratieId) return
    let actief = true
    setLaden(true)
    setFout(null)
    setData(null)
    setKvk({})
    haalDubbeleCrediteurenOp(administratieId)
      .then((r) => actief && setData(r))
      .catch((err) => actief && setFout(err instanceof ApiError ? err.message : 'Dubbelen ophalen mislukt.'))
      .finally(() => actief && setLaden(false))
    return () => {
      actief = false
    }
  }, [administratieId])

  const controleer = async (nummer: string) => {
    setKvk((k) => ({ ...k, [nummer]: 'bezig' }))
    try {
      const r = await controleerCrediteurKvk(administratieId, nummer)
      setKvk((k) => ({ ...k, [nummer]: r }))
    } catch (err) {
      setKvk((k) => ({ ...k, [nummer]: { fout: err instanceof ApiError ? err.message : 'KvK-controle mislukt.' } }))
    }
  }

  const kvkResultaat = (nummer: string) => {
    const r = kvk[nummer]
    if (!r) return null
    if (r === 'bezig') return <span className="hint" style={{ margin: 0 }}>KvK opzoeken…</span>
    if ('fout' in r) return <span className="fout" style={{ margin: 0 }}>{r.fout}</span>
    if (!r.gevonden) return <span className="hint" style={{ margin: 0 }}>KvK: niet gevonden{r.testomgeving ? ' (testomgeving)' : ''}</span>
    return (
      <span className="hint" style={{ margin: 0 }}>
        KvK: <b>{r.naam}</b>
        {r.rechtsvorm ? ` · ${r.rechtsvorm}` : ''}
        {r.plaats ? ` · ${r.plaats}` : ''}
        {r.uitgeschreven ? ' · UITGESCHREVEN' : ''}
        {r.testomgeving ? ' · (KvK-testomgeving, fictieve data)' : ''}
      </span>
    )
  }

  return (
    <div className="panel" data-testid="crediteur-dubbelen">
      <h3 style={{ marginTop: 0 }}>Crediteuren — dubbel-signalering</h3>
      <p className="hint">
        Crediteuren die hetzelfde btw-nummer, KvK-nummer of IBAN delen, of dezelfde naam op rechtsvorm/leestekens na
        (Wola vs. Wola b.v.). Samenvoegen doe je in Reeleezee zelf — deze app verwijdert nooit iets. Het
        crediteur-voorstel op het controlescherm herkent sinds 28-08 éérst op btw-/KvK-nummer en pas daarna op naam,
        zodat nieuwe dubbelen structureel minder ontstaan.
      </p>
      <div style={{ maxWidth: 420 }}>
        <AdministratieCombobox
          label="Administratie"
          toonLabel={false}
          administraties={administraties}
          waarde={administratieId}
          onWijzig={setAdministratieId}
          placeholder="— kies administratie —"
        />
      </div>
      {!administratieId && <p className="hint">Kies een administratie om de dubbelen te zien.</p>}
      {laden && <SkeletonRegels />}
      {fout && <div className="fout">{fout}</div>}
      {data && data.groepen.length === 0 && (
        <p className="hint" role="status">
          Geen dubbelen gevonden onder {data.aantal_crediteuren} actieve crediteuren.
        </p>
      )}
      {data && data.groepen.length > 0 && (
        <>
          <p className="hint" role="status">
            {data.groepen.length} {data.groepen.length === 1 ? 'groep' : 'groepen'} onder {data.aantal_crediteuren} actieve
            crediteuren — nummer-groepen eerst (zekerst), dan IBAN, dan naam.
          </p>
          <div className="tabel-scroll">
            <table className="lines">
              <thead>
                <tr>
                  <th>Waarop gelijk</th>
                  <th>Crediteuren</th>
                  <th>Btw-nummer</th>
                  <th>KvK-nummer</th>
                  <th>IBAN(s)</th>
                </tr>
              </thead>
              <tbody>
                {data.groepen.map((g) => (
                  <tr key={`${g.soort}:${g.sleutel}`}>
                    <td>
                      <Badge variant={g.soort === 'naam' ? 'warn' : 'info'}>{SOORT_LABEL[g.soort]}</Badge>
                      <div className="hint" style={{ margin: '4px 0 0' }}>{g.sleutel}</div>
                      {g.soort === 'kvk_nummer' && (
                        <div style={{ marginTop: 4 }}>
                          <Button variant="ghost" maat="klein" onClick={() => void controleer(g.sleutel)}>
                            KvK controleren
                          </Button>
                          <div>{kvkResultaat(g.sleutel)}</div>
                        </div>
                      )}
                    </td>
                    <td>
                      {g.crediteuren.map((c) => (
                        <div key={c.vendor_id}>
                          <b>{c.naam ?? '—'}</b>
                          <span className="hint" style={{ marginLeft: 6 }}>{c.vendor_id.slice(0, 8)}…</span>
                        </div>
                      ))}
                    </td>
                    <td>{g.crediteuren.map((c) => <div key={c.vendor_id}>{c.btw_nummer ?? '—'}</div>)}</td>
                    <td>{g.crediteuren.map((c) => <div key={c.vendor_id}>{c.kvk_nummer ?? '—'}</div>)}</td>
                    <td>{g.crediteuren.map((c) => <div key={c.vendor_id}>{c.ibans.length ? c.ibans.join(', ') : '—'}</div>)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
