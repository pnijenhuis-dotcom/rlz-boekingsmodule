// Administratie-detailPAGINA /instellingen/administraties/{id} (Instellingen v3, mockup scherm 2 —
// akkoord Peter 01-09; HERZIET het v2-besluit 30-08 "detail-DIALOOG": eigen URL, linkbaar,
// bereikbaar voor de zoeker). Kop met naam + chips + acties (Schrijftest, Webservice, Archiveren),
// tabs Algemeen · Boeken & AI · Klant-accordering · Doorbelasting · Uren & materiaal · Voorraad.
// De tabs hergebruiken de BESTAANDE componenten/endpoints gefilterd op déze administratie — één
// bron, twee ingangen, geen tweede schrijver; élke toggle houdt de bestaande bevestigingsdialoog
// + audit (PendingToggle → InstellingenScreen.bevestigen). Toon-regel tabs = de chip-regel:
// Doorbelasting alleen als bron/doel, Uren/Voorraad alleen bij opt-in (registry DETAIL_TABS).
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import type { AdministratieInstellingenDto } from '../api/types'
import { DoorbelastingInstellingen } from '../doorbelasting/DoorbelastingInstellingen'
import { Badge, Button, Switch } from '../ui/basis'
import { AccorderingInstellingen } from './AccorderingInstellingen'
import { EigenaarCell, IbanAccordeursCell } from './AdministratieCellen'
import { chipsVoor, type PendingToggle, type ToggleType } from './AdministratiesV2'
import { EersteSyncStatus } from './AdministratieWizard'
import { AfdelingenBeheer } from './AfdelingenBeheer'
import { LeverancierAutoboeken } from './LeverancierAutoboeken'
import { LeverancierProjectverdeling, ProjectverdelingInstellingen } from './ProjectverdelingInstellingen'
import { OdooBackendRijen, OdooLeesbronRij } from './OdooBackend'
import { DETAIL_TAB_PADEN, type DetailTab, zichtbareTabs } from './instellingenRegistry'

interface Props {
  administratie: AdministratieInstellingenDto
  accordeursVersie: number
  onPending: (p: PendingToggle) => void
  onWebservice: (a: AdministratieInstellingenDto) => void
  onSchrijftest: (a: AdministratieInstellingenDto) => void
  onArchiveren: (a: AdministratieInstellingenDto) => void
  onDossierTypen: (a: AdministratieInstellingenDto) => void
  onDagmax: (administratieId: string, naam: string, waarde: string) => Promise<void>
  onHerlaad: () => void
}

function tijd(iso: string | null | undefined): string {
  if (!iso) return ''
  return new Date(iso).toLocaleTimeString('nl-NL', { hour: '2-digit', minute: '2-digit' })
}

export function ariaLabelVoor(type: ToggleType): string {
  switch (type) {
    case 'boeken':
      return 'Boeken ingeschakeld voor'
    case 'project':
      return 'Project verplicht voor'
    case 'ai_extractie':
      return 'AI-extractie voor'
    case 'is_vastgoed':
      return 'Vastgoed-koppeling voor'
    case 'uren_meerwerk':
      return 'Uren & meerwerk voor'
    case 'afdelingen':
      return 'Afdelingen van toepassing voor'
    case 'voorraad':
      return 'Voorraad bijhouden voor'
    case 'omzet_autoboeken':
      return 'Omzet-autoboeken voor'
    case 'duplicaat_autoafvoer':
      return 'Duplicaat-afvoer automatisch voor'
  }
}

/** Eén instellingenrij (mockup .rij): titel + uitleg links, bediening rechts. */
export function InstellingRij({
  titel,
  uitleg,
  children,
}: {
  titel: React.ReactNode
  uitleg?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div className="inst-rij">
      <div className="inst-rij-tekst">
        <div className="inst-rij-titel">{titel}</div>
        {uitleg && <div className="inst-rij-uitleg">{uitleg}</div>}
      </div>
      <div className="inst-rij-bediening">{children}</div>
    </div>
  )
}

export function AdministratieDetailPagina({
  administratie: a,
  accordeursVersie,
  onPending,
  onWebservice,
  onSchrijftest,
  onArchiveren,
  onDossierTypen,
  onDagmax,
  onHerlaad,
}: Props) {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const tabs = zichtbareTabs(a)
  const gevraagd = searchParams.get('tab')
  const tab: DetailTab =
    gevraagd && DETAIL_TAB_PADEN.has(gevraagd) && tabs.some((t) => t.pad === gevraagd) ? (gevraagd as DetailTab) : 'algemeen'
  const kiesTab = (t: DetailTab) => navigate(t === 'algemeen' ? `/instellingen/administraties/${a.id}` : `/instellingen/administraties/${a.id}?tab=${t}`, { replace: true })

  const toggle = (type: ToggleType, huidig: boolean, titel: string, uitleg?: React.ReactNode) => (
    <InstellingRij titel={titel} uitleg={uitleg}>
      <label className="inst-switch-label">
        <Switch
          aria-label={`${ariaLabelVoor(type)} ${a.naam}`}
          checked={huidig}
          disabled={Boolean(a.gearchiveerd_op)}
          onChange={(e) =>
            onPending({ type, administratieId: a.id, naam: a.naam, nieuweWaarde: e.target.checked, verkoopAutoboekenAan: a.verkoop_autoboeken_ingeschakeld })
          }
        />
        {huidig ? 'aan' : 'uit'}
      </label>
    </InstellingRij>
  )

  const enkel = [{ id: a.id, naam: a.naam }]
  // Odoo-adapter blok E (03-09): backend is een eigenschap van de administratie, geen module (notitie ②).
  const isOdoo = a.boekhoud_backend === 'odoo'

  return (
    <div data-testid="administratie-detail">
      <div className="mb-1 text-[12.5px] text-muted">
        <Link to="/instellingen/administraties" className="text-primary no-underline hover:underline">
          Administraties
        </Link>{' '}
        <span className="text-faint">›</span> {a.naam}
      </div>
      <div className="dkop">
        <div style={{ flex: 1, minWidth: 0 }}>
          <h1 style={{ margin: 0 }}>{a.naam}</h1>
          <div className="dkop-chips">
            {chipsVoor(a).map((c) => (
              <Badge key={c.tekst} variant={c.variant} title={c.titel}>
                {c.tekst}
              </Badge>
            ))}
            {a.laatste_sync_op && (
              <Badge variant="ok" title={`laatste sync ${new Date(a.laatste_sync_op).toLocaleString('nl-NL')}`}>
                sync ✓ {tijd(a.laatste_sync_op)}
              </Badge>
            )}
            {a.gearchiveerd_op && <Badge variant="stil">gearchiveerd</Badge>}
          </div>
        </div>
        {!a.gearchiveerd_op && (
          <div className="dkop-acties">
            {/* RLZ-specifiek (TEST-boeking + storno 19, webservice-login): een Odoo-administratie heeft "Sleutel
                wijzigen…" en "Opnieuw testen" in het blok Boekhoud-backend. */}
            {!isOdoo && (
              <>
                <Button variant="secundair" maat="klein" aria-label={`Schrijftest voor ${a.naam}`} onClick={() => onSchrijftest(a)}>
                  🧪 Schrijftest
                </Button>
                <Button variant="secundair" maat="klein" aria-label={`Webservice-gegevens van ${a.naam}`} onClick={() => onWebservice(a)}>
                  ⚙ Webservice
                </Button>
              </>
            )}
            <Button variant="secundair" maat="klein" aria-label={`Archiveren ${a.naam}`} onClick={() => onArchiveren(a)}>
              🗑 Archiveren
            </Button>
          </div>
        )}
      </div>

      <div className="segment inst-tabs" role="tablist" aria-label="Instellingen van de administratie">
        {tabs.map((t) => (
          <button
            key={t.pad}
            type="button"
            role="tab"
            aria-selected={tab === t.pad}
            className={tab === t.pad ? 'actief' : undefined}
            onClick={() => kiesTab(t.pad)}
          >
            {t.titel}
          </button>
        ))}
      </div>

      {tab === 'algemeen' && (
        <div className="panel inst-paneel" role="tabpanel">
          {/* Blok "Boekhoud-backend" (Odoo-adapter blok E 03-09, mockup odoo-koppeling-ui.html §1): paars =
              platform-herkomst (notitie ①); de bestaande Webservice-/Eerste-sync-rijen verhuizen hierin. */}
          <h3 className="inst-groep-kop" data-testid="backend-blok-kop">
            Boekhoud-backend
          </h3>
          {isOdoo ? (
            <OdooBackendRijen administratie={a} onHerlaad={onHerlaad} />
          ) : (
            <>
              <InstellingRij titel="Backend" uitleg="Boekhoud-backend van deze administratie.">
                <span className="inst-links" style={{ alignItems: 'center', gap: 8 }} data-testid="backend-rlz">
                  <Badge variant="paars">Reeleezee</Badge>
                  {a.rlz_admin_id && (
                    <span className="hint" style={{ margin: 0 }}>
                      RLZ-id {a.rlz_admin_id}
                    </span>
                  )}
                </span>
              </InstellingRij>
              <InstellingRij
                titel="Webservice-gegevens"
                uitleg={
                  a.verkoopmodule_afwezig
                    ? 'Reeleezee-facturatiemodule niet afgenomen (SalesInvoices gaf 403 bij de rechten-probe) — verkoop-rakende leesroutes slaan deze administratie over. Later wél afgenomen? Draai de probe opnieuw via "Webservice"; bij SalesInvoices ok verdwijnt dit kenmerk vanzelf.'
                    : 'Login van de RLZ-webservice — wijzigen is probe-gated (10 leesroutes groen).'
                }
              >
                {a.webservice_username ? (
                  <span className={`chip ${a.probe_groen === false ? 'blokkerend' : a.probe_groen ? 'ok' : 'stil'}`} title="wachtwoord aanwezig (niet uitleesbaar)">
                    {a.webservice_username}
                  </span>
                ) : (
                  <span className="chip afwijking">geen credentials</span>
                )}
              </InstellingRij>
              <InstellingRij titel="Eerste sync" uitleg={a.eerste_sync && a.eerste_sync.status !== 'klaar' ? 'Bij een rode stand: foutreden + "Sync opnieuw starten".' : 'Alle onderdelen groen.'}>
                {a.eerste_sync && a.eerste_sync.status !== 'klaar' && a.eerste_sync.status !== 'geen' ? (
                  <EersteSyncStatus compact administratie={{ id: a.id, naam: a.naam, rlz_admin_id: a.rlz_admin_id ?? null }} initieel={a.eerste_sync} onAfgerond={onHerlaad} />
                ) : (
                  <Badge variant="ok">volledig ✓</Badge>
                )}
              </InstellingRij>
              <OdooLeesbronRij administratie={a} onHerlaad={onHerlaad} />
            </>
          )}
          <h3 className="inst-groep-kop">Algemeen</h3>
          <InstellingRij titel="Eigenaar (krijgt vragen)" uitleg="Nieuwe vragen worden standaard aan deze medewerker toegewezen.">
            <EigenaarCell
              administratie={a}
              onKies={(eigenaarId, eigenaarNaam) =>
                onPending({ type: 'eigenaar', administratieId: a.id, naam: a.naam, nieuweWaarde: eigenaarId !== null, eigenaarId, eigenaarNaam })
              }
            />
          </InstellingRij>
          <InstellingRij titel="IBAN-accordeurs" uitleg="Vier-ogen-flow bij een IBAN-wissel van een crediteur.">
            <IbanAccordeursCell
              administratie={a}
              versie={accordeursVersie}
              onWijzig={(nieuweSet, omschrijving) =>
                onPending({ type: 'iban_accordeurs', administratieId: a.id, naam: a.naam, nieuweWaarde: nieuweSet.length > 0, accordeurs: nieuweSet, accordeursOmschrijving: omschrijving })
              }
            />
          </InstellingRij>
          {toggle('is_vastgoed', a.is_vastgoed, 'Vastgoed-koppeling (Vastly)', 'Events, projectaanvragen en verkoop-autoboeken volgen deze schakelaar.')}
          {toggle('uren_meerwerk', a.uren_meerwerk_ingeschakeld, 'Uren & meerwerk (steigerbouw-tak)', 'Weekstaten, meerwerk, planning en materiaal — instellingen op de tab "Uren & materiaal" zodra aan.')}
          {toggle('voorraad', a.voorraad_ingeschakeld, 'Voorraad bijhouden', 'Controle-laag (mi-schema): instroom uit inkoopregels, uitstroom uit verkoopregels — nooit geboekt.')}
          {/* Blok "Intake-regels" (blok B 04-09): 'nooit splitsen'-regels per afzender — beheer per administratie,
              aanmaak uitsluitend via "Is één factuur" in de verzamelbak. */}
          <IntakeRegels administratieId={a.id} />
        </div>
      )}

      {tab === 'boeken-ai' && (
        <div role="tabpanel">
          <div className="panel inst-paneel">
            {toggle('boeken', a.boeken_ingeschakeld, 'Boeken', 'Default aan; uit = alleen bij uitzondering. De platformbrede noodstop blijft erboven staan.')}
            {toggle('ai_extractie', a.ai_extractie_ingeschakeld, 'AI-extractie (AVG-gate)', "PDF's gaan voor extractie naar de Claude API — default aan; de deterministische template-terugval werkt óók bij uit.")}
            {toggle('project', a.project_verplicht, 'Project verplicht bij boeken', 'Regels zonder project blokkeren dan het boeken (harde check).')}
            {toggle('afdelingen', a.afdelingen_ingeschakeld, 'Afdelingen', 'Afdeling verplicht op élk inkoopdocument + accorderingsroute per afdeling.')}
            {toggle(
              'omzet_autoboeken',
              Boolean(a.omzet_autoboeken_ingeschakeld),
              'Omzet-autoboeken (kassarapporten)',
              'Boekt een omzetrapport automatisch zodra álles groen is: harde checks (incl. memoriaal-saldo-0 en marge-plausibiliteit), categorie-mapping volledig door een mens bevestigd, geen duplicaat per periode, geen vraag of afwijzing. Anders gewoon werkvoorraad; volumerem 20/dag; chip "automatisch" + audit.',
            )}
            {toggle(
              'duplicaat_autoafvoer',
              Boolean(a.duplicaat_autoafvoer_ingeschakeld),
              'Duplicaten automatisch afvoeren',
              'Bij een harde match — zelfde crediteur (btw-nummer), zelfde referentie én zelfde totaalbedrag, origineel al geboekt óf ouder in de werkvoorraad — gaat het duplicaat automatisch naar Afgewezen met reden "Duplicaat van …" en kruisverwijzing naar het origineel. Nooit verwijderd; terughalen via Heropenen. Volumerem 20/dag; audit + tijdlijn. Zonder deze schakelaar blijft de één-klik "Afvoeren als duplicaat" gewoon beschikbaar.',
            )}
            <BtwDefaultRij administratieId={a.id} naam={a.naam} uitgeschakeld={Boolean(a.gearchiveerd_op)} />
            {a.afdelingen_ingeschakeld && (
              <div style={{ padding: '4px 16px 12px' }}>
                <AfdelingenBeheer administratieId={a.id} naam={a.naam} />
              </div>
            )}
          </div>
          <LeverancierAutoboeken administraties={enkel} vasteAdministratieId={a.id} />
          {/* Projectverdeling pro rato omzet (blok C 04-09): opt-in per leverancier + hercontrole-drempel /
              wachttijd "inkoop zonder omzet" — Beheerder-only. */}
          <LeverancierProjectverdeling administratieId={a.id} />
          <ProjectverdelingInstellingen administratieId={a.id} naam={a.naam} />
        </div>
      )}

      {tab === 'accordering' && (
        <div role="tabpanel">
          <AccorderingInstellingen administraties={enkel} />
        </div>
      )}

      {tab === 'doorbelasting' && (
        <div role="tabpanel">
          <DoorbelastingInstellingen administraties={enkel} vasteAdministratieId={a.id} />
          {!a.doorbelasting_ingeschakeld && a.doorbelasting_doel && (
            <p className="hint">
              Deze administratie is een <b>doelentiteit</b> van de doorbelasting (spiegel-inkoopfacturen landen hier). De
              bron-instellingen staan bij de bron-administratie.
            </p>
          )}
        </div>
      )}

      {tab === 'uren-materiaal' && (
        <div className="panel inst-paneel" role="tabpanel">
          <InstellingRij titel="Signaal > N uur per dag" uitleg="Som over álle weekstaten per kalenderdag; oranje vlag bij de keuring, geen blokkade (0 < N ≤ 24).">
            <label className="inst-switch-label" title="Signaal >N uur per dag">
              max/dag
              <input
                type="number"
                inputMode="decimal"
                min={0.5}
                max={24}
                step={0.5}
                aria-label={`Dagdrempel uren voor ${a.naam}`}
                defaultValue={a.uren_dagmax_uren}
                style={{ width: 70, padding: '2px 6px' }}
                onBlur={(e) => {
                  const waarde = e.target.value.replace(',', '.')
                  if (waarde !== '' && Number(waarde) !== Number(a.uren_dagmax_uren)) void onDagmax(a.id, a.naam, waarde)
                }}
              />
              u
            </label>
          </InstellingRij>
          <InstellingRij titel="Dossier-documenttypen" uitleg="Verplichte documenten per veldwerker (kopie ID, steigerpas, VCA, AVB, KvK-uittreksel …) mét vervaltermijn.">
            <Button variant="secundair" maat="klein" onClick={() => onDossierTypen(a)}>
              📁 Documenttypen…
            </Button>
          </InstellingRij>
          <InstellingRij titel="Planning, projecten en materiaal" uitleg="Weekgrid, werkopdrachten, transport-dag-agenda en de materiaalcatalogus per leverancier.">
            <span className="inst-links">
              <Link to={`/planning?administratie=${a.id}`} className="text-primary no-underline hover:underline">
                planning →
              </Link>
              <Link to="/instellingen/materiaal" className="text-primary no-underline hover:underline">
                materiaalcatalogus →
              </Link>
            </span>
          </InstellingRij>
        </div>
      )}

      {tab === 'voorraad' && (
        <div className="panel inst-paneel" role="tabpanel">
          <InstellingRij
            titel="Aansluitscherm"
            uitleg="Per artikelgroep begin + inkoop − verkoop = theoretisch vs telling; tolerantie (default 1 %) en nieuwe groepen stel je dáár in."
          >
            <Link to={`/voorraad?administratie=${a.id}`} className="text-primary no-underline hover:underline">
              aansluitscherm →
            </Link>
          </InstellingRij>
        </div>
      )}
    </div>
  )
}
