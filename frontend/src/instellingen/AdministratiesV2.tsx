// Instellingen › Administraties v2 (opdracht 30-08 blok A; mockup instellingen-administraties-v2.html =
// bouwnorm, besluiten Peter 29-08): compacte tabel — naam + meta, module-/afwijkings-chips, sync-chip,
// acties ⚙ (detail) / 🧪 (schrijftest) / 🗑 (archiveren). Sinds Instellingen v3 (mockup
// instellingen-v3.html, akkoord Peter 01-09 — herziet 30-08): rij-klik en ⚙ openen de
// detailPAGINA /instellingen/administraties/{id} (AdministratieDetailPagina.tsx), de dialoog is
// vervallen; de tabel zelf is ongewijzigd. Defaults Boeken + AI-extractie AAN: alleen een afwijking krijgt een chip. Vastly-autoboeken
// heeft geen eigen knop meer (volgt de vastgoed-koppeling). Archiveren = login intrekken + syncs stoppen,
// data blijft; dearchiveren mét nieuwe webservice-login. NOOIT verwijderen. Bulk-selectie blijft (checkbox).
import { Fragment, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { AdministratieInstellingenDto } from '../api/types'
import { Badge, Button, Checkbox, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle, FormField } from '../ui/basis'
import { EersteSyncStatus } from './AdministratieWizard'
import { ArchiveerDialog } from './ArchiveerDialog'
import { BulkBediening } from './BulkBediening'
import { dearchiveerAdministratie } from './instellingenApi'
import { koppelFoutTekst, ProbeRapport } from './KoppelingDialogen'
import { detailPad } from './instellingenRegistry'

export type ToggleType = 'boeken' | 'project' | 'ai_extractie' | 'is_vastgoed' | 'uren_meerwerk' | 'afdelingen' | 'voorraad' | 'omzet_autoboeken'

/** Toggle-verzoek vanuit de detailpagina (v3) — InstellingenScreen bevestigt (dialoog) en schrijft. */

export interface PendingToggle {
  type: ToggleType | 'eigenaar' | 'iban_accordeurs'
  administratieId: string
  naam: string
  nieuweWaarde: boolean
  eigenaarId?: string | null
  eigenaarNaam?: string
  accordeurs?: string[]
  accordeursOmschrijving?: string
  verkoopAutoboekenAan?: boolean
}

interface Props {
  administraties: AdministratieInstellingenDto[]
  selectie: string[]
  setSelectie: (f: (huidig: string[]) => string[]) => void
  onHerlaad: () => void
  onSchrijftest: (a: AdministratieInstellingenDto) => void
}

function tijd(iso: string | null | undefined): string {
  if (!iso) return ''
  return new Date(iso).toLocaleTimeString('nl-NL', { hour: '2-digit', minute: '2-digit' })
}

function datumKort(iso: string | null | undefined): string {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('nl-NL', { day: '2-digit', month: '2-digit' })
}

/**
 * Chips: ingeschakelde modules (info) en afwijkingen van de defaults (warn) eerst; daarna — feedback
 * Peter 30-08 — de WERKELIJKE stand per rij: gedempte (stil) chips voor "aan volgens default".
 */
export type ChipVariant = 'info' | 'warn' | 'stil' | 'ok' | 'paars'

export function chipsVoor(a: AdministratieInstellingenDto): { tekst: string; variant: ChipVariant; titel?: string }[] {
  const chips: { tekst: string; variant: ChipVariant; titel?: string }[] = []
  // Platform-herkomst (Odoo-adapter blok E 03-09, notitie ①): paars, nooit teal/groen — vóór de modules.
  if (a.boekhoud_backend === 'odoo')
    chips.push({
      tekst: 'Odoo',
      variant: 'paars',
      titel: `Boekhoud-backend Odoo${a.odoo_company_naam ? ` · company ${a.odoo_company_naam}${a.odoo_company_id != null ? ` (${a.odoo_company_id})` : ''}` : ''}`,
    })
  else if (a.odoo_alleen_lezen)
    chips.push({ tekst: 'Odoo · leesbron', variant: 'paars', titel: 'Reeleezee blijft de backend; Odoo levert alleen-lezen de voorraad-uitstroom vanaf de knipdatum' })
  if (a.is_vastgoed) chips.push({ tekst: 'Vastgoed + autoboeken', variant: 'info', titel: 'Vastgoed-koppeling (Vastly) — autoboeken verkoop volgt de koppeling' })
  if (a.afgeletterd_event_ingeschakeld) chips.push({ tekst: 'afgeletterd-events', variant: 'info' })
  if (a.doorbelasting_ingeschakeld) chips.push({ tekst: 'Doorbelasting', variant: 'info' })
  if (a.uren_meerwerk_ingeschakeld) chips.push({ tekst: `Uren & meerwerk · ${Number(a.uren_dagmax_uren).toLocaleString('nl-NL')}u-max`, variant: 'info' })
  if (a.afdelingen_ingeschakeld) chips.push({ tekst: 'Afdelingen', variant: 'info' })
  if (a.voorraad_ingeschakeld) chips.push({ tekst: 'Voorraad', variant: 'info' })
  if (a.project_verplicht) chips.push({ tekst: 'Project verplicht', variant: 'info' })
  if (a.bank_autoboeken_ingeschakeld) chips.push({ tekst: 'Bank-autoboeken', variant: 'info' })
  if (a.omzet_autoboeken_ingeschakeld) chips.push({ tekst: 'Omzet-autoboeken', variant: 'info', titel: 'Kassarapporten boeken automatisch zodra álles groen is (GO 01-09)' })
  if (a.accordering_ingeschakeld) chips.push({ tekst: 'Klant-accordering', variant: 'info' })
  if (a.verkoopmodule_afwezig)
    chips.push({
      tekst: 'geen facturatiemodule',
      variant: 'warn',
      titel:
        'Reeleezee-facturatiemodule niet afgenomen (SalesInvoices gaf 403 bij de rechten-probe) — verkoop-rakende leesroutes slaan deze administratie over. Krijgt de administratie de module later wél, dan haalt een geslaagde herprobe (Webservice-gegevens wijzigen) het kenmerk weg.',
    })
  if (!a.boeken_ingeschakeld) chips.push({ tekst: 'Boeken UIT (afwijking)', variant: 'warn' })
  if (!a.ai_extractie_ingeschakeld) chips.push({ tekst: 'AI-extractie UIT (afwijking)', variant: 'warn' })
  // Werkelijke stand bij "aan volgens default": gedempt achteraan (afwijkingen en modules eerst).
  if (a.boeken_ingeschakeld) chips.push({ tekst: 'Boeken ✓', variant: 'stil', titel: 'boeken aan — default' })
  if (a.ai_extractie_ingeschakeld) chips.push({ tekst: 'AI-extractie ✓', variant: 'stil', titel: 'AI-extractie aan — default' })
  return chips
}

function SyncChip({ a }: { a: AdministratieInstellingenDto }) {
  if (a.gearchiveerd_op) return <Badge variant="stil">gearchiveerd {datumKort(a.gearchiveerd_op)}</Badge>
  const isOdoo = a.boekhoud_backend === 'odoo'
  // Odoo-administratie (blok E 03-09): geen webservice-login — de Odoo-probe-stand is de poort.
  if (isOdoo && a.odoo_probe_groen === false) {
    return (
      <Badge variant="warn" title="De laatste Odoo-rechten-probe was rood — zie het blok Boekhoud-backend op de detailpagina">
        Odoo-probe rood
      </Badge>
    )
  }
  if (isOdoo && a.odoo_probe_groen == null) {
    return (
      <Badge variant="warn" title="De Odoo-koppeling is nog nooit getest — ‘Opnieuw testen’ in het blok Boekhoud-backend">
        nog niet getest
      </Badge>
    )
  }
  if (!isOdoo && !a.webservice_username) {
    return (
      <Badge variant="warn" title="Geen webservice-gegevens in de credential-store — sync kan niet draaien">
        geen credentials
      </Badge>
    )
  }
  if (a.eerste_sync && a.eerste_sync.status === 'fout') {
    return (
      <Badge variant="warn" title={a.eerste_sync.fout_reden ?? 'eerste sync mislukt'}>
        ⚠ sync-fout
      </Badge>
    )
  }
  if (a.eerste_sync && (a.eerste_sync.status === 'bezig' || a.eerste_sync.status === 'wachtrij')) {
    return <Badge variant="stil">sync bezig…</Badge>
  }
  if (!isOdoo && a.probe_groen === false) return <Badge variant="warn">rechten-probe niet groen</Badge>
  if (a.laatste_sync_op) {
    return (
      <Badge variant="ok" title={`laatste sync ${new Date(a.laatste_sync_op).toLocaleString('nl-NL')}`}>
        ✓ {tijd(a.laatste_sync_op)}
      </Badge>
    )
  }
  return <Badge variant="stil">nog niet gesynct</Badge>
}

export function AdministratiesV2({ administraties, selectie, setSelectie, onHerlaad, onSchrijftest }: Props) {
  const navigate = useNavigate()
  const [toonGearchiveerd, setToonGearchiveerd] = useState(false)
  const [archiveerVoor, setArchiveerVoor] = useState<AdministratieInstellingenDto | null>(null)
  const [dearchiveerVoor, setDearchiveerVoor] = useState<AdministratieInstellingenDto | null>(null)
  const [bezig, setBezig] = useState(false)
  const [dialoogFout, setDialoogFout] = useState<string | null>(null)
  const [rapport, setRapport] = useState<Record<string, string> | null>(null)
  const [melding, setMelding] = useState<string | null>(null)
  const [wsGebruiker, setWsGebruiker] = useState('')
  const [wsWachtwoord, setWsWachtwoord] = useState('')

  const actieve = administraties.filter((a) => !a.gearchiveerd_op)
  const gearchiveerd = administraties.filter((a) => a.gearchiveerd_op)
  const rijen = toonGearchiveerd ? gearchiveerd : actieve
  const dearchiveer = async () => {
    if (!dearchiveerVoor) return
    setBezig(true)
    setDialoogFout(null)
    setRapport(null)
    try {
      await dearchiveerAdministratie(dearchiveerVoor.id, wsGebruiker.trim(), wsWachtwoord)
      setMelding(`"${dearchiveerVoor.naam}" teruggezet met een nieuwe webservice-login (rechten-probe groen).`)
      setDearchiveerVoor(null)
      setWsGebruiker('')
      setWsWachtwoord('')
      onHerlaad()
    } catch (err) {
      const { bericht, rapport: r } = koppelFoutTekst(err)
      setDialoogFout(bericht)
      setRapport(r)
    } finally {
      setBezig(false)
    }
  }

  return (
    <>
      {melding && (
        <div className="hint" role="status" style={{ marginBottom: 10 }}>
          {melding}
        </div>
      )}
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 8, flexWrap: 'wrap' }}>
        <span className="hint" style={{ margin: 0 }}>
          {actieve.length} actief
        </span>
        {gearchiveerd.length > 0 && (
          <button type="button" className="linkbtn" onClick={() => setToonGearchiveerd((t) => !t)} aria-pressed={toonGearchiveerd}>
            {toonGearchiveerd ? '← actieve administraties' : `gearchiveerd (${gearchiveerd.length})`}
          </button>
        )}
      </div>
      {!toonGearchiveerd && (
        <BulkBediening administraties={actieve} geselecteerd={selectie} onWisSelectie={() => setSelectie(() => [])} onGereed={onHerlaad} />
      )}
      <div className="tabel-scroll sticky-koppen">
        <table data-testid="administraties-v2">
          <thead>
            <tr>
              <th style={{ width: 36 }}>
                {!toonGearchiveerd && (
                  <Checkbox
                    aria-label="Alle administraties selecteren"
                    checked={selectie.length === actieve.length && actieve.length > 0}
                    indeterminate={selectie.length > 0 && selectie.length < actieve.length}
                    onChange={(e) => setSelectie(() => (e.target.checked ? actieve.map((a) => a.id) : []))}
                  />
                )}
              </th>
              <th>Administratie</th>
              <th>Modules &amp; afwijkingen</th>
              <th>Sync</th>
              <th className="acties" style={{ textAlign: 'right' }}>
                Acties
              </th>
            </tr>
          </thead>
          <tbody>
            {rijen.map((a) => (
              <Fragment key={a.id}>
                <tr
                  className={selectie.includes(a.id) ? 'geselecteerd' : undefined}
                  style={{ cursor: 'pointer', opacity: a.gearchiveerd_op ? 0.7 : 1 }}
                  onClick={() => navigate(detailPad(a.id))}
                  data-testid={`administratie-rij-${a.id}`}
                >
                  <td onClick={(e) => e.stopPropagation()}>
                    {!a.gearchiveerd_op && (
                      <Checkbox
                        aria-label={`Selecteer ${a.naam}`}
                        checked={selectie.includes(a.id)}
                        onChange={(e) => setSelectie((huidig) => (e.target.checked ? [...huidig, a.id] : huidig.filter((id) => id !== a.id)))}
                      />
                    )}
                  </td>
                  <td>
                    <div style={{ fontWeight: 600 }}>{a.naam}</div>
                    <div className="hint" style={{ fontSize: 11.5, margin: 0 }}>
                      {[
                        a.eigenaar_naam ? `eigenaar: ${a.eigenaar_naam}` : null,
                        a.iban_accordeurs_aantal ? `${a.iban_accordeurs_aantal} IBAN-accordeur${a.iban_accordeurs_aantal === 1 ? '' : 's'}` : null,
                        a.gearchiveerd_op ? `gearchiveerd ${datumKort(a.gearchiveerd_op)}${a.gearchiveerd_door_naam ? ` door ${a.gearchiveerd_door_naam}` : ''}` : null,
                      ]
                        .filter(Boolean)
                        .join(' · ')}
                    </div>
                  </td>
                  <td>
                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                      {chipsVoor(a).map((c) => (
                        <Badge key={c.tekst} variant={c.variant} title={c.titel}>
                          {c.tekst}
                        </Badge>
                      ))}
                    </div>
                  </td>
                  <td>
                    <SyncChip a={a} />
                  </td>
                  <td className="acties" style={{ textAlign: 'right', whiteSpace: 'nowrap' }} onClick={(e) => e.stopPropagation()}>
                    {a.gearchiveerd_op ? (
                      <Button variant="secundair" maat="klein" aria-label={`Dearchiveren ${a.naam}`} onClick={() => { setDialoogFout(null); setRapport(null); setDearchiveerVoor(a) }}>
                        Dearchiveren…
                      </Button>
                    ) : (
                      <>
                        <Button variant="ghost" maat="klein" aria-label={`Instellingen van ${a.naam}`} title="Instellingen" onClick={() => navigate(detailPad(a.id))}>
                          ⚙
                        </Button>
                        {/* RLZ-schrijftest (TEST-boeking + storno 19) — niet voor een Odoo-administratie (blok E 03-09). */}
                        {a.boekhoud_backend !== 'odoo' && (
                          <Button variant="ghost" maat="klein" aria-label={`Schrijftest voor ${a.naam}`} title="Schrijftest" onClick={() => onSchrijftest(a)}>
                            🧪
                          </Button>
                        )}
                        <Button variant="ghost" maat="klein" aria-label={`Archiveren ${a.naam}`} title="Archiveren" onClick={() => { setDialoogFout(null); setArchiveerVoor(a) }}>
                          🗑
                        </Button>
                      </>
                    )}
                  </td>
                </tr>
                {a.eerste_sync && a.eerste_sync.status === 'fout' && !a.gearchiveerd_op && (
                  <tr className="subrij">
                    <td />
                    <td colSpan={4}>
                      <EersteSyncStatus compact administratie={{ id: a.id, naam: a.naam, rlz_admin_id: a.rlz_admin_id ?? null }} initieel={a.eerste_sync} onAfgerond={onHerlaad} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
            {rijen.length === 0 && (
              <tr>
                <td colSpan={5} className="hint">
                  {toonGearchiveerd ? 'Geen gearchiveerde administraties.' : 'Geen actieve administraties.'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <ArchiveerDialog
        administratie={archiveerVoor}
        onSluiten={() => setArchiveerVoor(null)}
        onGearchiveerd={(m) => {
          setMelding(m)
          setArchiveerVoor(null)
          onHerlaad()
        }}
      />

      {/* Dearchiveren — nieuwe webservice-login, probe-gated. */}
      <Dialog open={dearchiveerVoor !== null} onOpenChange={(open) => !open && !bezig && setDearchiveerVoor(null)}>
        <DialogContent aria-describedby={undefined} data-testid="dearchiveer-dialoog">
          <DialogTitle>Dearchiveren — {dearchiveerVoor?.naam}</DialogTitle>
          <DialogDescription>
            Terugzetten vereist een nieuwe webservice-login van Reeleezee; de rechten-probe (10 leesroutes) moet groen zijn
            (een 403 op SalesInvoices = facturatiemodule niet afgenomen en telt als waarschuwing, geen blokkade).
            Het wachtwoord wordt server-side versleuteld opgeslagen en is daarna nooit meer uitleesbaar.
          </DialogDescription>
          <form
            onSubmit={(e) => {
              e.preventDefault()
              void dearchiveer()
            }}
          >
            <FormField label="Webservice-gebruiker" htmlFor="dearch-gebruiker">
              <input id="dearch-gebruiker" autoFocus value={wsGebruiker} onChange={(e) => setWsGebruiker(e.target.value)} />
            </FormField>
            <FormField label="Wachtwoord" htmlFor="dearch-wachtwoord">
              <input id="dearch-wachtwoord" type="password" value={wsWachtwoord} onChange={(e) => setWsWachtwoord(e.target.value)} />
            </FormField>
            {dialoogFout && <div className="fout">{dialoogFout}</div>}
            {rapport && <ProbeRapport rapport={rapport} />}
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setDearchiveerVoor(null)} disabled={bezig}>
                Annuleren
              </Button>
              <Button type="submit" disabled={bezig || !wsGebruiker.trim() || !wsWachtwoord}>
                {bezig ? 'Bezig…' : 'Probe draaien en terugzetten'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}
