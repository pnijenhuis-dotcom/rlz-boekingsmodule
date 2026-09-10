// RLZ-check als knop (nachtrun 10/11-09 blok 1; bevinding Peter 10-09 avond: "de route bestaat, de knop niet").
// Blok Webservice-gegevens op Instellingen › Administraties › ‹administratie› › Algemeen: knop "RLZ-check"
// (secundair) naast de login → POST /administraties/{id}/rlz-check (herprobe met de OPGESLAGEN login, blok C
// 10-09) → resultaat inline per leesroute (dot + label, letterlijk RLZ-antwoord ≤ 300 tekens, RLZ-recht) +
// "Administraties die deze login ziet: N" mét markering of het eigen rlz_admin_id erin zit (een verkeerd
// administratie-id is zo direct zichtbaar). Groene check ná een rode eerste sync → "Sync opnieuw starten"
// (primair) ernaast, over de bestaande eerste-sync-route. Één primaire knop; teal = actie, groen = status.
import { useState, type ReactNode } from 'react'
import { ApiError } from '../api/client'
import type { AdministratieInstellingenDto, EersteSyncRunDto } from '../api/types'
import { Button } from '../ui/basis'
import { type RlzCheckResultaatDto, startEersteSync, voerRlzCheckUit } from './instellingenApi'

/** Facturatiemodule niet afgenomen (01-09): UITSLUITEND SalesInvoices-403 — waarschuwing, geen blokkade. */
function isModuleAfwezig(route: string, stand: string): boolean {
  return route === 'SalesInvoices' && stand === '403'
}

/** Groen = elke route ok, met als enige uitzondering SalesInvoices-403 (zelfde regel als backend `probe_is_groen`). */
export function rlzCheckIsGroen(rapport: Record<string, string>): boolean {
  const routes = Object.entries(rapport)
  return routes.length > 0 && routes.every(([route, stand]) => stand === 'ok' || isModuleAfwezig(route, stand))
}

export function rlzCheckFoutTekst(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 404) return `Administratie onbekend of geen webservice-login geregistreerd — ${err.message}`
    if (err.status === 503) return `Geen opgeslagen webservice-login voor deze administratie — ${err.message}`
    return err.message
  }
  return err instanceof Error ? err.message : 'Onbekende fout'
}

/** Eén regel per route: label (groen/rood/oranje), de letterlijke RLZ-melding of "ok", het RLZ-recht. */
function RouteRij({ route, stand, melding, recht }: { route: string; stand: string; melding?: string; recht?: string }) {
  const ok = stand === 'ok'
  const afwezig = isModuleAfwezig(route, stand)
  const klasse = ok ? 'ok' : afwezig ? 'afwijking' : 'blokkerend'
  return (
    <tr data-testid={`rlz-check-route-${route}`}>
      <td style={{ whiteSpace: 'nowrap' }}>
        <span className={`chip ${klasse}`}>{ok ? 'ok' : afwezig ? '403 — facturatiemodule niet afgenomen' : `HTTP ${stand}`}</span>
      </td>
      <td style={{ fontWeight: 600, whiteSpace: 'nowrap' }}>{route}</td>
      <td style={{ fontSize: 12, wordBreak: 'break-word' }}>{ok ? <span className="text-muted">RLZ antwoordt normaal</span> : melding ?? `HTTP ${stand}`}</td>
      <td className="text-muted" style={{ fontSize: 11.5 }}>
        {recht ?? ''}
      </td>
    </tr>
  )
}

/** De instellingenrij "Webservice-gegevens" zélf (titel + uitleg links, login-chip + knoppen rechts) mét het
 * check-resultaat als volle-breedte-blok eronder — één component, zodat knop en resultaat dezelfde stand delen. */
export function RlzCheck({
  administratie: a,
  titel,
  uitleg,
  children,
  onHerlaad,
}: {
  administratie: AdministratieInstellingenDto
  titel: ReactNode
  uitleg?: ReactNode
  /** De login-chip (of "geen credentials") — komt vóór de knoppen in de bediening. */
  children?: ReactNode
  /** Ná een check (probe-stand + kenmerk kunnen wijzigen) en ná het herstarten van de sync herlaadt de lijst. */
  onHerlaad: () => void
}) {
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [resultaat, setResultaat] = useState<RlzCheckResultaatDto | null>(null)
  const [syncBezig, setSyncBezig] = useState(false)
  const [syncGestart, setSyncGestart] = useState<EersteSyncRunDto | null>(null)

  const check = async () => {
    setBezig(true)
    setFout(null)
    setSyncGestart(null)
    try {
      setResultaat(await voerRlzCheckUit(a.id))
      onHerlaad()
    } catch (err) {
      setResultaat(null)
      setFout(rlzCheckFoutTekst(err))
    } finally {
      setBezig(false)
    }
  }

  const herstartSync = async () => {
    setSyncBezig(true)
    setFout(null)
    try {
      setSyncGestart(await startEersteSync(a.id))
      onHerlaad()
    } catch (err) {
      setFout(rlzCheckFoutTekst(err))
    } finally {
      setSyncBezig(false)
    }
  }

  const groen = resultaat !== null && rlzCheckIsGroen(resultaat.rapport)
  const eersteSyncFout = a.eerste_sync?.status === 'fout'
  const toonSyncKnop = groen && eersteSyncFout && syncGestart === null
  const eigenInLijst = resultaat ? resultaat.administraties_zichtbaar.some((z) => z.id === resultaat.rlz_admin_id) : false
  const routes = resultaat ? Object.keys(resultaat.rapport) : []
  const aantalRood = routes.filter((r) => resultaat!.rapport[r] !== 'ok' && !isModuleAfwezig(r, resultaat!.rapport[r])).length

  return (
    <div className="inst-rij" data-testid="rlz-check" style={{ flexWrap: 'wrap' }}>
      <div className="inst-rij-tekst">
        <div className="inst-rij-titel">{titel}</div>
        {uitleg && <div className="inst-rij-uitleg">{uitleg}</div>}
      </div>
      <div className="inst-rij-bediening" style={{ flexWrap: 'wrap' }}>
        {children}
        <Button variant="secundair" maat="klein" aria-label={`RLZ-check voor ${a.naam}`} disabled={bezig} onClick={() => void check()}>
          {bezig ? 'RLZ-check loopt…' : 'RLZ-check'}
        </Button>
        {toonSyncKnop && (
          <Button maat="klein" aria-label={`Sync opnieuw starten voor ${a.naam}`} disabled={syncBezig} onClick={() => void herstartSync()}>
            {syncBezig ? 'Bezig…' : 'Sync opnieuw starten'}
          </Button>
        )}
        {resultaat && (
          <span className={`chip ${groen ? 'ok' : 'blokkerend'}`} data-testid="rlz-check-samenvatting">
            {groen ? `${routes.length} leesroutes groen` : `${aantalRood} van ${routes.length} leesroutes rood`}
          </span>
        )}
        {syncGestart && (
          <span className="hint" style={{ margin: 0 }} role="status">
            Eerste sync opnieuw gestart — de stand verschijnt hieronder bij &ldquo;Eerste sync&rdquo;.
          </span>
        )}
      </div>
      {fout && (
        <div className="fout" role="alert" style={{ flexBasis: '100%' }}>
          {fout}
        </div>
      )}
      {resultaat && (
        <div data-testid="rlz-check-resultaat" style={{ flexBasis: '100%', minWidth: 0 }}>
          <div className="tabel-scroll">
            <table style={{ fontSize: 12.5 }}>
              <thead>
                <tr>
                  <th>Stand</th>
                  <th>Leesroute</th>
                  <th>Reeleezee zegt</th>
                  <th>RLZ-recht</th>
                </tr>
              </thead>
              <tbody>
                {routes.map((route) => (
                  <RouteRij key={route} route={route} stand={resultaat.rapport[route]} melding={resultaat.meldingen[route]} recht={resultaat.rechten[route]} />
                ))}
              </tbody>
            </table>
          </div>
          <div className="hint" style={{ marginTop: 6 }} data-testid="rlz-check-administraties">
            {resultaat.administraties_fout ? (
              <>
                Administraties die deze login ziet: <b>onbekend</b> — Reeleezee weigert <code>Administrations</code>: {resultaat.administraties_fout}
              </>
            ) : (
              <>
                Administraties die deze login ziet: <b>{resultaat.administraties_zichtbaar.length}</b>
                {resultaat.administraties_zichtbaar.length > 0 && (
                  <>
                    {' '}
                    (
                    {resultaat.administraties_zichtbaar.map((z, i) => (
                      <span key={z.id}>
                        {i > 0 && ', '}
                        <span style={{ fontWeight: z.id === resultaat.rlz_admin_id ? 700 : undefined }}>
                          {z.naam ? `${z.naam} · ` : ''}
                          {z.id}
                        </span>
                      </span>
                    ))}
                    )
                  </>
                )}{' '}
                {eigenInLijst ? (
                  <span className="chip ok">✓ deze administratie</span>
                ) : (
                  <span className="chip blokkerend" title={`Het opgeslagen RLZ-id ${resultaat.rlz_admin_id} staat niet tussen de administraties die deze login ziet — controleer het administratie-id of koppel de webservice-gebruiker in RLZ aan deze administratie`}>
                    ⚠ eigen id NIET in de lijst
                  </span>
                )}
              </>
            )}
          </div>
          {groen && eersteSyncFout && syncGestart === null && (
            <div className="hint" style={{ marginTop: 4 }}>
              De check is groen maar de laatste eerste sync was rood — start de sync opnieuw met de knop hierboven.
            </div>
          )}
        </div>
      )}
    </div>
  )
}
