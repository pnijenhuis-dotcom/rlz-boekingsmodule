import { useState } from 'react'
import { Button, Checkbox, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle, FormField } from '../ui/basis'
import { EersteSyncStatus } from './AdministratieWizard'
import { KeuzeKaarten } from './KeuzeKaarten'
import {
  koppelOdooLeesbron,
  koppelOdooNieuw,
  ODOO_SYNC_ONDERDELEN,
  odooOverstap,
  testOdooVerbinding,
  voorbereidOdooOverstap,
  type OdooCompanyDto,
  type OdooGekoppeldeAdministratieDto,
  type OdooOverstapVoorbereidingDto,
  type OdooProbeDto,
} from './instellingenApi'
import { mappingCompleet, mappingInvoer, mappingSleutel, OdooMappingTabel, rijenUitVoorbereiding, type MappingTabelRij } from './OdooMappingTabel'
import { datumNl, odooKoppelFout, odooProbeGroen, OdooProbeRapport, odooProbeSamenvatting } from './odooProbe'

/** Odoo-koppelwizard — één component, twee ingangen (besluit Peter 03-09, mockup odoo-koppeling-ui.html §2;
 * de RLZ-wizard in Odoo-vorm, notitie ③):
 *   - ingang A "nieuw": binnen "+ Administratie toevoegen" ná de backend-keuze (stap 1 dáár) — verbinding →
 *     company's kiezen (meerdere mag, zoals de RLZ-wizard) → "Koppeling opslaan" = POST /instellingen/odoo/koppelen
 *     → resultaat mét eerste sync per administratie;
 *   - ingang B "bestaand": "Odoo koppelen…" op de detailpagina van een RLZ-administratie — éérst de koppelvorm
 *     (notitie ⑤, nooit impliciet): VOLLEDIGE backend (overstap mét verplichte overgangsdatum, POST …/odoo/overstap)
 *     óf ALLEEN-LEZEN leesbron (voorraad-uitstroom vanaf de knipdatum, default 01-09-2026, POST …/odoo/leesbron).
 * Poort = die van de RLZ-wizard: de server draait de rechten-probe en slaat alleen groen op — een 422 toont het
 * rapport rood mét de foutregels en de wizard blijft op zijn stap. De API-sleutel leeft alleen in component-state
 * en de request-body; geen enkele response draagt 'm terug. Afwijking van de mockup-placeholder "URL · database ·
 * API-sleutel": er is bewust GEEN database-veld — de JSON-2-URL bindt de database al (odoo-verkenning STAP-0).
 *
 * Blok A 04-09 (besluit Peter, beslispunt 1 van "ODOO-ADAPTER BLOK E"): de VOLLEDIGE overstap heeft een verplichte
 * mapping-stap RLZ-grootboek → Odoo-account en RLZ-btw → Odoo-tax. "Verder" op de company-stap roept
 * POST …/odoo/overstap/voorbereiden aan (voorvalidaties + probe — 422 = rapport rood, wizard blijft staan — en het
 * deterministische voorstel, niets persistent); de mens bevestigt de hele tabel, pas dán POST …/odoo/overstap mét
 * `mapping`. Zo blijft het boekingsgeheugen (en de autoboek-opt-ins) ná de overstap werken. */

export type OdooKoppelvorm = 'volledig' | 'leesbron'
type StapId = 'koppelvorm' | 'verbinding' | 'company' | 'mapping' | 'knip' | 'resultaat'

export const ODOO_KNIP_DEFAULT = '2026-09-01'

interface Props {
  ingang: 'nieuw' | 'bestaand'
  administratie?: { id: string; naam: string }
  /** Ingang A: de backend-keuze is stap 1 van de bovenliggende wizard — nummering loopt door. */
  stapOffset?: number
  /** Ingang A: "← Terug" op de eerste stap gaat naar de backend-keuze. */
  onTerug?: () => void
  /** Aangeroepen zodra er iets is opgeslagen (resultaatstap bereikt) — de aanroeper herlaadt bij sluiten. */
  onKlaar?: () => void
  onSluiten: () => void
}

/** Het servervoorstel voor een rij (id + reden) — om ná een handmatige wijziging te herkennen dat de mens terug op
 * het voorstel staat (chip weer groen/oranje i.p.v. "handmatig"). */
function voorstelVoor(v: OdooOverstapVoorbereidingDto | null, rij: MappingTabelRij): { odoo_id: number; reden: MappingTabelRij['bron'] } | null {
  if (!v) return null
  const bron = rij.soort === 'grootboek' ? v.grootboek.find((r) => r.rlz_id === rij.rlz_id) : v.btw.find((r) => r.rlz_id === rij.rlz_id)
  if (!bron || bron.voorstel_odoo_id == null) return null
  const reden = bron.reden
  return { odoo_id: bron.voorstel_odoo_id, reden: reden === 'zelfde_code' || reden === 'code_verlengd' || reden === 'tarief' ? reden : 'handmatig' }
}

function stappenVoor(ingang: Props['ingang'], vorm: OdooKoppelvorm): StapId[] {
  if (ingang === 'nieuw') return ['verbinding', 'company', 'resultaat']
  return vorm === 'leesbron'
    ? ['koppelvorm', 'verbinding', 'company', 'knip', 'resultaat']
    : ['koppelvorm', 'verbinding', 'company', 'mapping', 'resultaat']
}

export function OdooKoppelWizard({ ingang, administratie, stapOffset = 0, onTerug, onKlaar, onSluiten }: Props) {
  const [vorm, setVorm] = useState<OdooKoppelvorm>('volledig')
  const stappen = stappenVoor(ingang, vorm)
  const [stap, setStap] = useState<StapId>(stappen[0])
  const [odooUrl, setOdooUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [apiGebruiker, setApiGebruiker] = useState('')
  const [companies, setCompanies] = useState<OdooCompanyDto[]>([])
  const [gekozen, setGekozen] = useState<number[]>([])
  const [overgangsdatum, setOvergangsdatum] = useState('')
  const [knip, setKnip] = useState(ODOO_KNIP_DEFAULT)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<{ bericht: string; rapport: Record<string, string> | null } | null>(null)
  const [gekoppeld, setGekoppeld] = useState<OdooGekoppeldeAdministratieDto[]>([])
  const [leesbronProbe, setLeesbronProbe] = useState<OdooProbeDto | null>(null)
  const [voorbereiding, setVoorbereiding] = useState<OdooOverstapVoorbereidingDto | null>(null)
  const [mappingRijen, setMappingRijen] = useState<MappingTabelRij[]>([])

  const index = stappen.indexOf(stap)
  const titel =
    ingang === 'nieuw'
      ? `Administratie toevoegen — stap ${index + 1 + stapOffset} van ${stappen.length + stapOffset}`
      : `Odoo koppelen — ${administratie?.naam ?? ''} — stap ${index + 1} van ${stappen.length}`

  const naar = (s: StapId) => {
    setFout(null)
    setStap(s)
  }
  const vorige = () => {
    if (index === 0) onTerug?.()
    else naar(stappen[index - 1])
  }

  const testen = async () => {
    setBezig(true)
    setFout(null)
    try {
      const resp = await testOdooVerbinding({ odoo_url: odooUrl.trim(), api_key: apiKey, ...(apiGebruiker.trim() ? { api_gebruiker: apiGebruiker.trim() } : {}) })
      setCompanies(resp.companies)
      const vrij = resp.companies.filter((c) => !c.al_gekoppeld)
      setGekozen(vrij.length === 1 ? [vrij[0].company_id] : [])
      naar('company')
    } catch (err) {
      setFout(odooKoppelFout(err))
    } finally {
      setBezig(false)
    }
  }

  const verbinding = () => ({ odoo_url: odooUrl.trim(), api_key: apiKey, ...(apiGebruiker.trim() ? { api_gebruiker: apiGebruiker.trim() } : {}) })

  /** Volledige overstap: probe + mappingvoorstel ophalen (niets persistent) en door naar de mapping-stap. */
  const voorbereiden = async () => {
    if (!administratie) return
    setBezig(true)
    setFout(null)
    try {
      const resp = await voorbereidOdooOverstap(administratie.id, { ...verbinding(), company_id: gekozen[0] })
      setVoorbereiding(resp)
      setMappingRijen(rijenUitVoorbereiding(resp))
      naar('mapping')
    } catch (err) {
      setFout(odooKoppelFout(err))
    } finally {
      setBezig(false)
    }
  }

  const kiesMapping = (rij: MappingTabelRij, odooId: number | null) => {
    const sleutel = mappingSleutel(rij.soort, rij.rlz_id)
    setMappingRijen((huidig) =>
      huidig.map((r) => {
        if (mappingSleutel(r.soort, r.rlz_id) !== sleutel) return r
        // Terug op het voorstel = de voorstel-reden terug; iets anders = handmatig (zo legt de server het ook vast).
        const voorstel = voorstelVoor(voorbereiding, r)
        const bron = odooId == null ? null : voorstel && voorstel.odoo_id === odooId ? voorstel.reden : 'handmatig'
        return { ...r, odoo_id: odooId, bron }
      }),
    )
  }

  const opslaan = async () => {
    setBezig(true)
    setFout(null)
    try {
      if (ingang === 'nieuw') {
        const resp = await koppelOdooNieuw({ ...verbinding(), company_ids: gekozen })
        setGekoppeld(resp.administraties)
      } else if (!administratie) {
        throw new Error('Geen administratie')
      } else if (vorm === 'volledig') {
        const resp = await odooOverstap(administratie.id, { ...verbinding(), company_id: gekozen[0], overgangsdatum, mapping: mappingInvoer(mappingRijen) })
        setGekoppeld([resp])
      } else {
        const resp = await koppelOdooLeesbron(administratie.id, { ...verbinding(), company_id: gekozen[0], voorraad_knip_datum: knip || null })
        setLeesbronProbe(resp)
      }
      setApiKey('') // niet langer nodig in het geheugen van de pagina
      onKlaar?.()
      naar('resultaat')
    } catch (err) {
      setFout(odooKoppelFout(err))
    } finally {
      setBezig(false)
    }
  }

  const companyNaam = (id: number) => companies.find((c) => c.company_id === id)?.naam ?? null
  const kanOpslaan = gekozen.length > 0 && !(ingang === 'bestaand' && vorm === 'volledig' && !overgangsdatum)
  const mappingKlaar = mappingCompleet(mappingRijen)

  return (
    <>
      <DialogTitle>{titel}</DialogTitle>
      <DialogDescription>
        {stap === 'koppelvorm' &&
          'Twee verschillende dingen die nooit in elkaar overlopen: de volledige backend boekt vanaf de overgangsdatum in Odoo (Reeleezee blijft het archief van vóór die datum); de alleen-lezen leesbron laat de backend Reeleezee en leest uitsluitend de geposte verkoopfacturen uit Odoo voor de voorraad-uitstroom vanaf de knipdatum.'}
        {stap === 'verbinding' &&
          'Adres van de Odoo-omgeving en een API-sleutel van een gebruiker mét boekhoudrechten. De sleutel wordt server-side versleuteld opgeslagen (credential-store) en is daarna nooit meer uitleesbaar. De URL bindt de database — een apart database-veld is niet nodig.'}
        {stap === 'company' &&
          (ingang === 'nieuw'
            ? 'Deze sleutel ziet de volgende companies in de database. Kies welke je aansluit; vóór het opslaan draait per company de rechten-probe (grootboek · btw · relaties · journals · facturen · boeken) — die moet groen zijn, anders wordt niets opgeslagen.'
            : vorm === 'volledig'
              ? 'Kies de company waarin deze administratie vanaf de overgangsdatum boekt. Vóór het opslaan draait de rechten-probe inclusief schrijfrecht — die moet groen zijn, anders wordt niets opgeslagen.'
              : 'Kies de company waarvan de verkoopfacturen als leesbron dienen. De leesprobe (alleen leesrechten) moet groen zijn — er wordt in deze vorm nooit in Odoo geschreven.')}
        {stap === 'mapping' &&
          'Vertaal de Reeleezee-grootboekrekeningen en btw-tarieven die in het boekingsgeheugen en in open boekvoorstellen voorkomen naar hun Odoo-tegenhanger. Het voorstel is deterministisch (zelfde code, of code + "00"); bevestig of kies zelf. Zo blijven de geleerde boekvoorstellen en de autoboek-instellingen ná de overstap werken. Niets wordt opgeslagen vóór "Koppeling opslaan".'}
        {stap === 'knip' &&
          'Vanaf de knipdatum telt de voorraad-uitstroom uit Odoo (geposte verkoopfacturen en creditnota’s van deze company); de Reeleezee-uitstroomroute stopt automatisch vanaf die datum, zodat niets dubbel telt.'}
        {stap === 'resultaat' &&
          (vorm === 'leesbron' && ingang === 'bestaand'
            ? 'Leesbron gekoppeld. De dagelijkse sync leest vanaf nu de verkoop-uitstroom uit Odoo; de knipdatum is later te wijzigen in het blok Boekhoud-backend.'
            : 'Gekoppeld met de standaardinstellingen. De stamgegevens-sync (grootboek, btw, relaties, projecten) draait op de achtergrond; hieronder de stand per onderdeel. Niemand ziet een nieuwe administratie tot je scopes toekent op Gebruikers & toegang.')}
      </DialogDescription>

      {stap === 'koppelvorm' && (
        <div>
          {/* Fix C1 (04-09): zelfde keuzekaarten als de backend-keuze in "+ Administratie
              toevoegen" — één patroon voor "kies één van twee" in een wizard. */}
          <KeuzeKaarten
            naam="odoo-koppelvorm"
            waarde={vorm}
            onKies={setVorm}
            opties={[
              {
                waarde: 'volledig',
                ariaLabel: 'Volledige backend',
                kop: <b>Volledige backend</b>,
                uitleg:
                  'Boeken in Odoo vanaf een overgangsdatum — het migratiescenario van een bestaande Reeleezee-administratie.',
              },
              {
                waarde: 'leesbron',
                ariaLabel: 'Alleen-lezen leesbron',
                kop: <b>Alleen-lezen leesbron</b>,
                uitleg:
                  'Voorraad-uitstroom uit Odoo vanaf een knipdatum; de backend blijft Reeleezee. Er wordt nooit in Odoo geschreven.',
              },
            ]}
          />
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onSluiten} disabled={bezig}>
              Annuleren
            </Button>
            <Button type="button" onClick={() => naar('verbinding')}>
              Verder →
            </Button>
          </DialogFooter>
        </div>
      )}

      {stap === 'verbinding' && (
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void testen()
          }}
        >
          <FormField label="Odoo-URL" htmlFor="odoo-url" hint="bv. https://universal-steigers.odoo.com — de URL bindt de database">
            <input id="odoo-url" type="url" autoComplete="off" placeholder="https://…odoo.com" value={odooUrl} onChange={(e) => setOdooUrl(e.target.value)} required />
          </FormField>
          <FormField label="API-sleutel" htmlFor="odoo-api-key">
            <input id="odoo-api-key" type="password" autoComplete="new-password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} required />
          </FormField>
          <FormField label="API-gebruiker (label, optioneel)" htmlFor="odoo-api-gebruiker" hint="Alleen ter herkenning in het backend-blok — bv. n-module@…">
            <input id="odoo-api-gebruiker" autoComplete="off" value={apiGebruiker} onChange={(e) => setApiGebruiker(e.target.value)} />
          </FormField>
          {fout && (
            <div className="fout">
              {fout.bericht}
              {fout.rapport && <OdooProbeRapport rapport={fout.rapport} />}
            </div>
          )}
          <DialogFooter>
            {index === 0 && !onTerug ? (
              <Button type="button" variant="ghost" onClick={onSluiten} disabled={bezig}>
                Annuleren
              </Button>
            ) : (
              <Button type="button" variant="ghost" onClick={vorige} disabled={bezig}>
                ← Terug
              </Button>
            )}
            <Button type="submit" disabled={bezig || !odooUrl.trim() || !apiKey}>
              {bezig ? 'Verbinding testen…' : 'Verbinding testen →'}
            </Button>
          </DialogFooter>
        </form>
      )}

      {stap === 'company' && (
        <div>
          <p className="hint" style={{ marginTop: 0 }}>
            ✓ Verbonden — {companies.length} {companies.length === 1 ? 'company' : 'companies'} gevonden. Kies uit de lijst, nooit een id typen.
          </p>
          {companies.length === 0 && <p className="hint">Deze sleutel ziet geen companies.</p>}
          <ul style={{ listStyle: 'none', padding: 0, margin: '0 0 8px' }}>
            {companies.map((c) => (
              <li key={c.company_id} style={{ padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
                <label style={{ display: 'flex', gap: 8, alignItems: 'center', margin: 0, opacity: c.al_gekoppeld ? 0.6 : 1 }}>
                  {ingang === 'nieuw' ? (
                    <Checkbox
                      aria-label={`Koppelen ${c.naam}`}
                      disabled={c.al_gekoppeld || bezig}
                      checked={gekozen.includes(c.company_id)}
                      onChange={(e) => setGekozen((h) => (e.target.checked ? [...h, c.company_id] : h.filter((id) => id !== c.company_id)))}
                    />
                  ) : (
                    <input
                      type="radio"
                      name="odoo-company"
                      aria-label={`Koppelen ${c.naam}`}
                      disabled={c.al_gekoppeld || bezig}
                      checked={gekozen[0] === c.company_id}
                      onChange={() => setGekozen([c.company_id])}
                    />
                  )}
                  <span>
                    <b>{c.naam}</b>{' '}
                    <span className="hint" style={{ margin: 0, fontSize: 11 }}>
                      company {c.company_id}
                    </span>
                    {c.al_gekoppeld && (
                      <>
                        {' '}
                        <span className="chip stil">al gekoppeld</span>
                      </>
                    )}
                  </span>
                </label>
              </li>
            ))}
          </ul>
          {ingang === 'bestaand' && vorm === 'volledig' && (
            <FormField label="Overgangsdatum" htmlFor="odoo-overgangsdatum" hint="Vanaf deze datum boekt de administratie in Odoo; Reeleezee blijft het archief van daarvóór.">
              <input id="odoo-overgangsdatum" type="date" value={overgangsdatum} onChange={(e) => setOvergangsdatum(e.target.value)} required />
            </FormField>
          )}
          {fout && (
            <div className="fout">
              {fout.bericht}
              {fout.rapport && <OdooProbeRapport rapport={fout.rapport} />}
              <div className="hint" style={{ marginTop: 4 }}>
                Opslaan is geblokkeerd tot de probe groen is — zelfde poort als de Reeleezee-wizard; niets is opgeslagen.
              </div>
            </div>
          )}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={vorige} disabled={bezig}>
              ← Terug
            </Button>
            {ingang === 'bestaand' && vorm === 'leesbron' ? (
              <Button type="button" onClick={() => naar('knip')} disabled={bezig || gekozen.length === 0}>
                Knipdatum kiezen →
              </Button>
            ) : ingang === 'bestaand' && vorm === 'volledig' ? (
              <Button type="button" onClick={() => void voorbereiden()} disabled={bezig || !kanOpslaan}>
                {bezig ? 'Rechten-probe en mappingvoorstel…' : 'Verder →'}
              </Button>
            ) : (
              <Button type="button" onClick={() => void opslaan()} disabled={bezig || !kanOpslaan}>
                {bezig ? 'Rechten-probe en opslaan…' : ingang === 'nieuw' ? `Koppeling opslaan (${gekozen.length}) →` : 'Koppeling opslaan →'}
              </Button>
            )}
          </DialogFooter>
        </div>
      )}

      {stap === 'mapping' && voorbereiding && (
        <div data-testid="odoo-wizard-mapping">
          <p className="hint" style={{ marginTop: 0 }}>
            ✓ Rechten-probe groen · company {voorbereiding.company_naam ?? companyNaam(gekozen[0]) ?? gekozen[0]} · overgang per {datumNl(overgangsdatum)} ·{' '}
            {voorbereiding.odoo_grootboek.length} Odoo-rekeningen · {voorbereiding.odoo_btw.length} Odoo-taxen
          </p>
          <OdooMappingTabel rijen={mappingRijen} odooGrootboek={voorbereiding.odoo_grootboek} odooBtw={voorbereiding.odoo_btw} onKies={kiesMapping} />
          {fout && (
            <div className="fout" style={{ marginTop: 10 }}>
              {fout.bericht}
              {fout.rapport && <OdooProbeRapport rapport={fout.rapport} />}
              <div className="hint" style={{ marginTop: 4 }}>
                Niets is opgeslagen — pas de mapping aan en probeer opnieuw.
              </div>
            </div>
          )}
          {!mappingKlaar && (
            <p className="hint" style={{ margin: '8px 0 0' }}>
              Opslaan kan zodra élke rij een Odoo-tegenhanger heeft — de server weigert een onvolledige mapping.
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={vorige} disabled={bezig}>
              ← Terug
            </Button>
            <Button type="button" onClick={() => void opslaan()} disabled={bezig || !mappingKlaar}>
              {bezig ? 'Rechten-probe en opslaan…' : 'Koppeling opslaan →'}
            </Button>
          </DialogFooter>
        </div>
      )}

      {stap === 'knip' && (
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void opslaan()
          }}
        >
          <FormField label="Knipdatum voorraad-uitstroom" htmlFor="odoo-knip" hint="Default 01-09-2026 (migratie 0102). Leeg = geen knip: Odoo levert dan géén uitstroom tot je een datum zet.">
            <input id="odoo-knip" type="date" value={knip} onChange={(e) => setKnip(e.target.value)} />
          </FormField>
          {fout && (
            <div className="fout">
              {fout.bericht}
              {fout.rapport && <OdooProbeRapport rapport={fout.rapport} />}
              <div className="hint" style={{ marginTop: 4 }}>
                Opslaan is geblokkeerd tot de leesprobe groen is; niets is opgeslagen.
              </div>
            </div>
          )}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={vorige} disabled={bezig}>
              ← Terug
            </Button>
            <Button type="submit" disabled={bezig || gekozen.length === 0}>
              {bezig ? 'Leesprobe en opslaan…' : 'Koppeling opslaan →'}
            </Button>
          </DialogFooter>
        </form>
      )}

      {stap === 'resultaat' && (
        <div data-testid="odoo-wizard-resultaat">
          {leesbronProbe ? (
            <div>
              <p style={{ margin: '0 0 6px' }}>
                <span className={`chip ${leesbronProbe.groen ? 'ok' : 'blokkerend'}`}>{leesbronProbe.groen ? 'leesbron gekoppeld' : 'leesprobe niet groen'}</span>{' '}
                <span className="hint" style={{ margin: 0, fontSize: 11 }}>
                  company {companyNaam(gekozen[0]) ?? leesbronProbe.company_naam ?? ''} ({gekozen[0]}) · verkoop-uitstroom vanaf {knip ? datumNl(knip) : '— (geen knip gezet)'}
                </span>
              </p>
              <div className="hint" style={{ marginTop: 0 }}>
                {odooProbeSamenvatting(leesbronProbe.rapport)}
              </div>
              {!odooProbeGroen(leesbronProbe.rapport) && <OdooProbeRapport rapport={leesbronProbe.rapport} />}
            </div>
          ) : (
            gekoppeld.map((g) => (
              <EersteSyncStatus
                key={g.id}
                administratie={{ id: g.id, naam: g.naam, rlz_admin_id: null, odoo_company_id: g.company_id, odoo_company_naam: companyNaam(g.company_id), probe: g.probe }}
                onderdelen={ODOO_SYNC_ONDERDELEN}
              />
            ))
          )}
          <DialogFooter>
            <Button type="button" onClick={onSluiten}>
              Sluiten
            </Button>
          </DialogFooter>
        </div>
      )}
    </>
  )
}

/** Ingang B als eigen dialoog (detailpagina "Odoo koppelen…"): ná afronden herlaadt de aanroeper. */
export function OdooKoppelDialog({
  administratie,
  onSluiten,
  onAfgerond,
}: {
  administratie: { id: string; naam: string }
  onSluiten: () => void
  onAfgerond: () => void
}) {
  const [klaar, setKlaar] = useState(false)
  const sluit = () => {
    onSluiten()
    if (klaar) onAfgerond()
  }
  return (
    <Dialog open onOpenChange={(o) => !o && sluit()}>
      <DialogContent className="administratie-wizard" aria-describedby={undefined} data-testid="odoo-koppel-dialoog">
        <OdooKoppelWizard ingang="bestaand" administratie={administratie} onKlaar={() => setKlaar(true)} onSluiten={sluit} />
      </DialogContent>
    </Dialog>
  )
}
