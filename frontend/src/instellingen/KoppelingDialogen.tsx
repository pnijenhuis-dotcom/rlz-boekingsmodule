import { useState } from 'react'
import { ApiError } from '../api/client'
import type { AdministratieInstellingenDto } from '../api/types'
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle, FormField } from '../ui/basis'
import { voerSchrijftestUit, wijzigWebserviceGegevens, type SchrijftestResultaatDto } from './instellingenApi'

export function koppelFoutTekst(err: unknown): { bericht: string; rapport: Record<string, string> | null } {
  const bericht = err instanceof Error ? err.message : 'Onbekende fout'
  if (err instanceof ApiError && err.detail && typeof err.detail === 'object' && 'rapporten' in err.detail) {
    const rapporten = Object.values((err.detail as { rapporten: Record<string, Record<string, string>> }).rapporten ?? {})
    return { bericht, rapport: rapporten[0] ?? null }
  }
  return { bericht, rapport: null }
}

/** Facturatiemodule niet afgenomen (01-09, casus A.Y. Holding 2 + Abbegaa): UITSLUITEND een 403
 * op SalesInvoices — geen blokkade maar een waarschuwing (het kenmerk verkoopmodule_afwezig
 * schakelt de verkoop-leesroutes uit; een herprobe mét ok haalt het weg). */
export function facturatiemoduleAfwezig(rapport: Record<string, string>): boolean {
  return rapport.SalesInvoices === '403'
}

/** Foutmelding uit een wizard-/koppeling-422: de backend stuurt `detail: {bericht, rapporten}`;
 * de api-laag zet `bericht` als message en het object als `ApiError.detail`. */
export function ProbeRapport({ rapport }: { rapport: Record<string, string> }) {
  return (
    <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 12 }}>
      {Object.entries(rapport).map(([endpoint, stand]) => {
        const moduleAfwezig = endpoint === 'SalesInvoices' && stand === '403'
        return (
          <li key={endpoint}>
            {endpoint}:{' '}
            <span className={`chip ${stand === 'ok' ? 'ok' : moduleAfwezig ? 'afwijking' : 'blokkerend'}`}>
              {stand === 'ok' ? 'ok' : moduleAfwezig ? '403 — facturatiemodule niet afgenomen' : `HTTP ${stand}`}
            </span>
            {stand !== 'ok' && !moduleAfwezig && stand === '403' && (
              <span className="hint" style={{ margin: '0 0 0 6px', fontSize: 11 }}>
                geef de webservice-gebruiker in RLZ leesrecht op {endpoint}
              </span>
            )}
          </li>
        )
      })}
    </ul>
  )
}

/** "Webservice-gegevens wijzigen" (stappen a-b op een bestaande administratie — dekt het
 * credential-herstel-scenario van 15-08): nieuwe login → server draait admin-pin + rechten-probe,
 * alleen groen wordt opgeslagen (credential-store, envelope). Het huidige wachtwoord is nooit
 * uitleesbaar — alleen de gebruikersnaam en "aanwezig". */
export function WebserviceGegevensDialog({
  administratie,
  onSluiten,
  onGewijzigd,
}: {
  administratie: AdministratieInstellingenDto
  onSluiten: () => void
  onGewijzigd: () => void
}) {
  const [gebruiker, setGebruiker] = useState(administratie.webservice_username ?? '')
  const [wachtwoord, setWachtwoord] = useState('')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<{ bericht: string; rapport: Record<string, string> | null } | null>(null)
  const [rapport, setRapport] = useState<Record<string, string> | null>(null)

  const opslaan = async () => {
    setBezig(true)
    setFout(null)
    try {
      const resp = await wijzigWebserviceGegevens(administratie.id, gebruiker.trim(), wachtwoord)
      setRapport(resp.rapport)
      setWachtwoord('')
      onGewijzigd()
    } catch (err) {
      setFout(koppelFoutTekst(err))
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && !bezig && onSluiten()}>
      <DialogContent aria-describedby={undefined}>
        <DialogTitle>Webservice-gegevens — {administratie.naam}</DialogTitle>
        <DialogDescription>
          {administratie.webservice_username
            ? `Huidige webservice-gebruiker: ${administratie.webservice_username} (wachtwoord aanwezig, niet uitleesbaar).`
            : 'Er staan nog geen webservice-gegevens in de credential-store voor deze administratie.'}{' '}
          De nieuwe login wordt eerst getest (verbinding + rechten-probe op 10 leesroutes); alleen bij volledig groen wordt
          hij versleuteld opgeslagen. Geauditeerd zonder wachtwoord.
        </DialogDescription>
        {rapport ? (
          <div>
            <p className="ok" style={{ margin: 0 }}>
              {facturatiemoduleAfwezig(rapport)
                ? 'Opgeslagen — rechten-probe groen, met één waarschuwing: de facturatiemodule is in Reeleezee niet afgenomen (verkoop-leesroutes blijven uit).'
                : 'Opgeslagen — rechten-probe groen.'}
            </p>
            <ProbeRapport rapport={rapport} />
            <DialogFooter>
              <Button type="button" onClick={onSluiten}>
                Sluiten
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault()
              void opslaan()
            }}
          >
            <FormField label="Webservice-gebruiker" htmlFor="ws-gebruiker">
              <input id="ws-gebruiker" autoComplete="off" value={gebruiker} onChange={(e) => setGebruiker(e.target.value)} required />
            </FormField>
            <FormField label="Nieuw wachtwoord" htmlFor="ws-wachtwoord">
              <input id="ws-wachtwoord" type="password" autoComplete="new-password" value={wachtwoord} onChange={(e) => setWachtwoord(e.target.value)} required />
            </FormField>
            {fout && (
              <div className="fout">
                {fout.bericht}
                {fout.rapport && <ProbeRapport rapport={fout.rapport} />}
              </div>
            )}
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={onSluiten} disabled={bezig}>
                Annuleren
              </Button>
              <Button type="submit" disabled={bezig || !gebruiker.trim() || !wachtwoord}>
                {bezig ? 'Testen en opslaan…' : 'Testen en opslaan'}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}

/** "Schrijftest uitvoeren" (stap e van het onboarding-protocol als expliciete knop): TEST-inkoop-
 * factuur van € 1,21 → boeken (17) → verifiëren → storno (19) → verifiëren concept. Nooit
 * automatisch bij opslaan; elke stap zichtbaar; geauditeerd. */
export function SchrijftestDialog({ administratie, onSluiten }: { administratie: AdministratieInstellingenDto; onSluiten: () => void }) {
  const [bezig, setBezig] = useState(false)
  const [resultaat, setResultaat] = useState<SchrijftestResultaatDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)

  const uitvoeren = async () => {
    setBezig(true)
    setFout(null)
    try {
      setResultaat(await voerSchrijftestUit(administratie.id))
    } catch (err) {
      setFout(koppelFoutTekst(err).bericht)
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && !bezig && onSluiten()}>
      <DialogContent aria-describedby={undefined}>
        <DialogTitle>Schrijftest — {administratie.naam}</DialogTitle>
        <DialogDescription>
          Schrijft één TEST-inkoopfactuur (€ 1,00 + € 0,21 btw, referentie TEST-ONB-…) naar Reeleezee, boekt hem (actie 17),
          verifieert en storneert direct (actie 19) — het document blijft als concept staan, er wordt niets verwijderd. Elke
          stap wordt geverifieerd en geauditeerd. Vereist een gesyncte administratie en &ldquo;Boeken platformbreed&rdquo; aan.
        </DialogDescription>
        {resultaat && (
          <div>
            <p style={{ margin: '0 0 6px' }}>
              <span className={`chip ${resultaat.uitkomst === 'ok' ? 'ok' : 'blokkerend'}`}>
                {resultaat.uitkomst === 'ok' ? 'schrijftest geslaagd' : 'schrijftest mislukt'}
              </span>{' '}
              <span className="hint" style={{ margin: 0, fontSize: 11 }}>
                ref {resultaat.referentie} · doc {resultaat.document_id}
              </span>
            </p>
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5 }}>
              {resultaat.stappen.map((s) => (
                <li key={s.stap}>
                  {s.stap}: <span className={`chip ${s.status === 'ok' ? 'ok' : 'blokkerend'}`}>{s.status}</span>
                  {s.detail && <span className="hint" style={{ margin: '0 0 0 6px', fontSize: 11 }}>{s.detail}</span>}
                </li>
              ))}
            </ul>
          </div>
        )}
        {fout && <div className="fout">{fout}</div>}
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={onSluiten} disabled={bezig}>
            Sluiten
          </Button>
          {!resultaat && (
            <Button type="button" onClick={() => void uitvoeren()} disabled={bezig}>
              {bezig ? 'Schrijftest loopt…' : 'Schrijftest uitvoeren'}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
