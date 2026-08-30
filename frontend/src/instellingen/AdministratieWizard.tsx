import { useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'
import { Button, Checkbox, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle, FormField } from '../ui/basis'
import {
  haalEersteSyncStatusOp,
  maakAdministratiesAan,
  startEersteSync,
  testVerbinding,
  type AangemaakteAdministratieDto,
  type EersteSyncRunDto,
  type GevondenAdministratieDto,
} from './instellingenApi'

/** "+ Administratie toevoegen" (feedbackronde 26-08 punt 5, besluit Peter 26-08) — de
 * onboarding-batch 15-08 als wizard in drie stappen:
 *   1. webservice-gegevens → "Verbinding testen" (GET Administrations met die login);
 *   2. gevonden administraties → Beheerder kiest (naam + RLZ-id vooringevuld, nooit een id
 *      typen; al-aangesloten rijen zijn uitgeschakeld) → "Aansluiten" (server: rechten-probe
 *      per administratie verplicht groen, anders 422 mét rapport en niets opgeslagen);
 *   3. resultaat: eerste sync als achtergrondrun met status per onderdeel (poll).
 * Het wachtwoord staat alleen in component-state en de request-body; het komt in geen enkele
 * response terug (server toont daarna alleen "aanwezig" + gebruiker). De schrijftest is bewust
 * géén stap hier — dat is een aparte expliciete knop op de administratie. */

export const POLL_INTERVAL_MS = 2500
export const ONDERDEEL_LABELS: Record<string, string> = {
  ledgers: 'Grootboek',
  taxrates: 'Btw-tarieven',
  vendors: 'Crediteuren',
  projects: 'Projecten',
  payment_accounts: 'Bankrekeningen',
}

function foutTekst(err: unknown): string {
  return err instanceof Error ? err.message : 'Onbekende fout'
}

function isLopend(run: EersteSyncRunDto | null): boolean {
  return run !== null && (run.status === 'wachtrij' || run.status === 'bezig')
}

export interface EersteSyncAdministratie {
  id: string
  naam: string
  rlz_admin_id: string | null
  probe?: Record<string, string>
}

/** Poll-blok per administratie: status per onderdeel tot klaar/fout + "Sync opnieuw starten".
 * Twee afnemers: de wizard (stap 3, ná aanmaken — haalt de status zelf op) en sinds 27-08 de
 * administratie-rij op Instellingen › Administraties (`compact`, start met de stand uit de
 * lijst-response en pollt alleen zolang de run loopt; `onAfgerond` laat de lijst herladen zodat
 * een groene run van de rij verdwijnt). Wizard-nazorg: een gesloten wizard is geen doodlopend pad meer. */
export function EersteSyncStatus({
  administratie,
  initieel,
  compact = false,
  onAfgerond,
}: {
  administratie: EersteSyncAdministratie | AangemaakteAdministratieDto
  initieel?: EersteSyncRunDto | null
  compact?: boolean
  onAfgerond?: (run: EersteSyncRunDto) => void
}) {
  const [run, setRun] = useState<EersteSyncRunDto | null>(initieel ?? null)
  const [fout, setFout] = useState<string | null>(null)
  const [herstartBezig, setHerstartBezig] = useState(false)
  const actief = useRef(true)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const afgerondRef = useRef(onAfgerond)
  afgerondRef.current = onAfgerond

  // Verse stand van buiten (lijst herladen) overnemen — geen extra poll nodig.
  useEffect(() => {
    if (initieel !== undefined) setRun(initieel)
  }, [initieel])

  const pollTot = (eerste: boolean) => {
    const poll = async () => {
      try {
        const nieuw = await haalEersteSyncStatusOp(administratie.id)
        if (!actief.current) return
        setRun(nieuw)
        if (isLopend(nieuw)) timer.current = setTimeout(() => void poll(), POLL_INTERVAL_MS)
        else if (!eerste || initieel === undefined) afgerondRef.current?.(nieuw)
      } catch (err) {
        if (actief.current) setFout(foutTekst(err))
      }
    }
    return poll
  }

  useEffect(() => {
    actief.current = true
    // Met een aangeleverde stand alleen pollen zolang de run loopt; zonder stand (wizard) direct ophalen.
    if (initieel === undefined || isLopend(initieel ?? null)) void pollTot(true)()
    return () => {
      actief.current = false
      if (timer.current) clearTimeout(timer.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [administratie.id])

  const herstart = async () => {
    setHerstartBezig(true)
    setFout(null)
    try {
      const nieuw = await startEersteSync(administratie.id)
      setRun(nieuw)
      // opnieuw pollen; klaar/fout → onAfgerond (rij herlaadt de lijst)
      timer.current = setTimeout(() => void pollTot(false)(), POLL_INTERVAL_MS)
    } catch (err) {
      setFout(foutTekst(err))
    } finally {
      setHerstartBezig(false)
    }
  }

  const statusChip = (status: string) => {
    const klasse = status === 'klaar' ? 'ok' : status === 'fout' ? 'blokkerend' : status === 'bezig' ? 'ai' : 'stil'
    return <span className={`chip ${klasse}`}>{status}</span>
  }

  const probe = 'probe' in administratie ? administratie.probe : undefined
  return (
    <div className={compact ? 'eerste-sync-rij' : 'panel'} style={compact ? undefined : { marginTop: 10 }} data-testid={`eerste-sync-${administratie.rlz_admin_id ?? administratie.id}`}>
      {compact ? (
        <div className="hint" style={{ marginTop: 0 }}>
          <b>Eerste sync</b> {run && statusChip(run.status === 'geen' ? 'wachtrij' : run.status)}{' '}
          {run?.status === 'fout' ? '— niet volledig gelukt; herstart hieronder (zelfde run als in de wizard).' : run && isLopend(run) ? '— loopt nog…' : ''}
        </div>
      ) : (
        <>
          <h3 style={{ margin: '0 0 6px' }}>
            {administratie.naam}{' '}
            <span className="hint" style={{ margin: 0, fontSize: 11 }}>· RLZ-id {administratie.rlz_admin_id}</span>{' '}
            {run && statusChip(run.status === 'geen' ? 'wachtrij' : run.status)}
          </h3>
          <div className="hint" style={{ marginTop: 0 }}>
            Rechten-probe: {probe && Object.values(probe).every((v) => v === 'ok') ? '10/10 groen' : 'zie rapport'} · eerste sync per
            onderdeel:
          </div>
        </>
      )}
      <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 12.5 }}>
        {Object.keys(ONDERDEEL_LABELS).map((naam) => {
          const stand = run?.onderdelen?.[naam]
          return (
            <li key={naam}>
              {ONDERDEEL_LABELS[naam]}: {stand ? statusChip(stand.status) : statusChip('wachtrij')}
              {stand?.status === 'klaar' && typeof stand.aangemaakt === 'number' && (
                <span className="hint" style={{ margin: '0 0 0 6px', fontSize: 11 }}>
                  {stand.aangemaakt} nieuw · {stand.bijgewerkt ?? 0} bijgewerkt
                </span>
              )}
              {stand?.status === 'fout' && stand.fout && <span className="fout" style={{ marginLeft: 6 }}>{stand.fout}</span>}
            </li>
          )
        })}
      </ul>
      {run?.status === 'fout' && run.fout_reden && <div className="fout" style={{ marginTop: 6 }}>{run.fout_reden}</div>}
      {fout && <div className="fout" style={{ marginTop: 6 }}>{fout}</div>}
      {run && !isLopend(run) && (
        <div style={{ marginTop: 6 }}>
          <Button variant="secundair" maat="klein" disabled={herstartBezig} aria-label={compact ? `Sync opnieuw starten voor ${administratie.naam}` : undefined} onClick={() => void herstart()}>
            {herstartBezig ? 'Bezig…' : 'Sync opnieuw starten'}
          </Button>
        </div>
      )}
    </div>
  )
}

export function AdministratieWizard({ open, onSluiten, onAangemaakt }: { open: boolean; onSluiten: () => void; onAangemaakt: () => void }) {
  const [stap, setStap] = useState<1 | 2 | 3>(1)
  const [gebruiker, setGebruiker] = useState('')
  const [wachtwoord, setWachtwoord] = useState('')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [rapporten, setRapporten] = useState<Record<string, Record<string, string>> | null>(null)
  const [gevonden, setGevonden] = useState<GevondenAdministratieDto[]>([])
  const [gekozen, setGekozen] = useState<string[]>([])
  const [aangemaakt, setAangemaakt] = useState<AangemaakteAdministratieDto[]>([])

  const reset = () => {
    setStap(1)
    setGebruiker('')
    setWachtwoord('')
    setBezig(false)
    setFout(null)
    setRapporten(null)
    setGevonden([])
    setGekozen([])
    setAangemaakt([])
  }

  const sluit = () => {
    if (bezig) return
    const klaar = stap === 3
    reset()
    onSluiten()
    if (klaar) onAangemaakt()
  }

  const testen = async () => {
    setBezig(true)
    setFout(null)
    try {
      const resp = await testVerbinding(gebruiker.trim(), wachtwoord)
      setGevonden(resp.administraties)
      setGekozen(resp.administraties.filter((a) => !a.al_aangesloten).length === 1 ? resp.administraties.filter((a) => !a.al_aangesloten).map((a) => a.rlz_admin_id) : [])
      setStap(2)
    } catch (err) {
      setFout(foutTekst(err))
    } finally {
      setBezig(false)
    }
  }

  const aansluiten = async () => {
    setBezig(true)
    setFout(null)
    setRapporten(null)
    try {
      const resp = await maakAdministratiesAan(gebruiker.trim(), wachtwoord, gekozen)
      setAangemaakt(resp.administraties)
      setWachtwoord('') // niet langer nodig in het geheugen van de pagina
      setStap(3)
    } catch (err) {
      setFout(foutTekst(err))
      if (err instanceof ApiError && err.detail && typeof err.detail === 'object' && 'rapporten' in err.detail) {
        setRapporten((err.detail as { rapporten: Record<string, Record<string, string>> }).rapporten)
      }
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && sluit()}>
      <DialogContent className="administratie-wizard" aria-describedby={undefined}>
        <DialogTitle>Administratie toevoegen — stap {stap} van 3</DialogTitle>
        <DialogDescription>
          {stap === 1 && 'Webservice-gegevens van Reeleezee. Het wachtwoord wordt server-side versleuteld opgeslagen (credential-store) en is daarna nooit meer uitleesbaar.'}
          {stap === 2 && 'Deze login ziet de volgende administraties. Kies welke je aansluit; vóór het opslaan wordt per administratie de rechten-probe (10 leesroutes) gedraaid — die moet volledig groen zijn.'}
          {stap === 3 && 'Aangesloten met de standaardinstellingen: Boeken en AI-extractie (AVG-gate) staan AAN, alle overige opt-ins uit — aanpassen kan per administratie via ⚙. De eerste sync draait op de achtergrond; de schrijftest is een aparte knop op de administratie. Niemand ziet de administratie tot je scopes toekent op Gebruikers & toegang.'}
        </DialogDescription>

        {stap === 1 && (
          <form
            onSubmit={(e) => {
              e.preventDefault()
              void testen()
            }}
          >
            <FormField label="Webservice-gebruiker" htmlFor="wizard-gebruiker">
              <input id="wizard-gebruiker" autoComplete="off" value={gebruiker} onChange={(e) => setGebruiker(e.target.value)} required />
            </FormField>
            <FormField label="Wachtwoord" htmlFor="wizard-wachtwoord">
              <input id="wizard-wachtwoord" type="password" autoComplete="new-password" value={wachtwoord} onChange={(e) => setWachtwoord(e.target.value)} required />
            </FormField>
            {fout && <div className="fout">{fout}</div>}
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={sluit} disabled={bezig}>
                Annuleren
              </Button>
              <Button type="submit" disabled={bezig || !gebruiker.trim() || !wachtwoord}>
                {bezig ? 'Verbinding testen…' : 'Verbinding testen →'}
              </Button>
            </DialogFooter>
          </form>
        )}

        {stap === 2 && (
          <div>
            {gevonden.length === 0 && <p className="hint">Deze login ziet geen administraties.</p>}
            <ul style={{ listStyle: 'none', padding: 0, margin: '0 0 8px' }}>
              {gevonden.map((a) => (
                <li key={a.rlz_admin_id} style={{ padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
                  <label style={{ display: 'flex', gap: 8, alignItems: 'center', margin: 0, opacity: a.al_aangesloten ? 0.6 : 1 }}>
                    <Checkbox
                      aria-label={`Aansluiten ${a.naam}`}
                      disabled={a.al_aangesloten || bezig}
                      checked={gekozen.includes(a.rlz_admin_id)}
                      onChange={(e) =>
                        setGekozen((h) => (e.target.checked ? [...h, a.rlz_admin_id] : h.filter((id) => id !== a.rlz_admin_id)))
                      }
                    />
                    <span>
                      <b>{a.naam}</b>{' '}
                      <span className="hint" style={{ margin: 0, fontSize: 11 }}>RLZ-id {a.rlz_admin_id}</span>
                      {a.al_aangesloten && (
                        <>
                          {' '}
                          <span className="chip stil">al aangesloten</span>
                        </>
                      )}
                    </span>
                  </label>
                  {rapporten?.[a.rlz_admin_id] && Object.values(rapporten[a.rlz_admin_id]).some((v) => v !== 'ok') && (
                    <div className="fout" style={{ marginTop: 4, fontSize: 12 }}>
                      Rechten-probe:{' '}
                      {Object.entries(rapporten[a.rlz_admin_id])
                        .map(([k, v]) => `${k} ${v === 'ok' ? '✓' : `✗ (${v})`}`)
                        .join(' · ')}
                    </div>
                  )}
                </li>
              ))}
            </ul>
            {fout && <div className="fout">{fout}</div>}
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => { setStap(1); setFout(null); setRapporten(null) }} disabled={bezig}>
                ← Terug
              </Button>
              <Button type="button" onClick={() => void aansluiten()} disabled={bezig || gekozen.length === 0}>
                {bezig ? 'Rechten-probe en opslaan…' : `Aansluiten (${gekozen.length}) →`}
              </Button>
            </DialogFooter>
          </div>
        )}

        {stap === 3 && (
          <div>
            {aangemaakt.map((a) => (
              <EersteSyncStatus key={a.id} administratie={a} />
            ))}
            <DialogFooter>
              <Button type="button" onClick={sluit}>
                Sluiten
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
