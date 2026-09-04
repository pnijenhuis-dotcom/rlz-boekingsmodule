import { useCallback, useEffect, useState } from 'react'
import type { AdministratieInstellingenDto } from '../api/types'
import { Badge, Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle, FormField, useToastOptioneel } from '../ui/basis'
import { EersteSyncStatus } from './AdministratieWizard'
import { InstellingRij } from './AdministratieDetailPagina'
import {
  haalOdooStandOp,
  ODOO_SYNC_ONDERDELEN,
  probeOdooKoppeling,
  startOdooSync,
  zetOdooKnipdatum,
  type OdooProbeDto,
  type OdooStandDto,
  type OdooSyncResultaatDto,
} from './instellingenApi'
import { OdooKoppelDialog } from './OdooKoppelWizard'
import { datumNl, datumTijdKort, odooHost, odooKoppelFout, odooProbeGroen, OdooProbeRapport } from './odooProbe'

/** Blok "Boekhoud-backend" op de administratie-detailpagina, tab Algemeen (Odoo-adapter blok E 03-09, mockup
 * odoo-koppeling-ui.html §1). Paars = platform-herkomst (notitie ①), de company staat permanent in beeld
 * (notitie ④) en de twee koppelvormen blijven strikt gescheiden (notitie ⑤): een Odoo-administratie toont
 * "n.v.t. — volledige backend" bij Leesbron voorraad; een RLZ-administratie toont dáár de leesbron-stand óf de
 * ingang B "Odoo koppelen…". De Odoo-stand (GET …/odoo) wordt lazy opgehaald zodra er een koppeling is; de
 * lijst-DTO levert de eerste weergave zodat het blok nooit leeg flitst. De API-sleutel komt nergens terug. */

function foutTekst(err: unknown): string {
  return err instanceof Error ? err.message : 'Onbekende fout'
}

function useOdooStand(administratieId: string, actief: boolean) {
  const [stand, setStand] = useState<OdooStandDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const laad = useCallback(() => {
    if (!actief) return
    haalOdooStandOp(administratieId)
      .then((s) => {
        setStand(s)
        setFout(null)
      })
      .catch((err: unknown) => setFout(foutTekst(err)))
  }, [administratieId, actief])
  useEffect(() => {
    laad()
  }, [laad])
  return { stand, fout, laad }
}

/** Rij "Backend" + de Odoo-specifieke rijen (Verbinding · API-sleutel · Stamgegevens · Eerste sync ·
 * Leesbron voorraad) voor een administratie mét boekhoud_backend = odoo. */
export function OdooBackendRijen({ administratie: a, onHerlaad }: { administratie: AdministratieInstellingenDto; onHerlaad: () => void }) {
  const toast = useToastOptioneel()
  const { stand, fout: standFout, laad } = useOdooStand(a.id, true)
  const [probeBezig, setProbeBezig] = useState(false)
  const [probeUitkomst, setProbeUitkomst] = useState<{ groen: boolean; rapport: Record<string, string>; bericht?: string } | null>(null)
  const [syncBezig, setSyncBezig] = useState(false)
  const [syncUitkomst, setSyncUitkomst] = useState<OdooSyncResultaatDto | null>(null)
  const [syncFout, setSyncFout] = useState<string | null>(null)
  const [sleutelDialoog, setSleutelDialoog] = useState(false)

  const url = stand?.odoo_url ?? a.odoo_url ?? null
  const companyNaam = stand?.company_naam ?? a.odoo_company_naam ?? null
  const companyId = stand?.company_id ?? a.odoo_company_id ?? null
  const probeGroen = stand ? stand.probe_groen : (a.odoo_probe_groen ?? null)
  const probeOp = stand?.probe_op ?? a.odoo_probe_op ?? null
  const verlooptOp = stand?.api_key_verloopt_op ?? a.odoo_api_key_verloopt_op ?? null
  const overgangsdatum = stand?.overgangsdatum ?? a.odoo_overgangsdatum ?? null
  const rlzVoorOverstap = stand?.rlz_admin_id_voor_overstap ?? null
  const laatsteSync = stand?.laatste_sync_op ?? a.laatste_sync_op ?? null

  const herprobe = async () => {
    setProbeBezig(true)
    setProbeUitkomst(null)
    try {
      const resp = await probeOdooKoppeling(a.id, {})
      setProbeUitkomst({ groen: resp.groen, rapport: resp.rapport })
      toast.meld(resp.groen ? 'Odoo-probe groen' : 'Odoo-probe rood — zie het rapport', resp.groen ? 'ok' : 'warn')
    } catch (err) {
      const { bericht, rapport } = odooKoppelFout(err)
      setProbeUitkomst({ groen: false, rapport: rapport ?? {}, bericht })
      toast.meld('Odoo-probe rood — zie het rapport', 'warn')
    } finally {
      setProbeBezig(false)
      laad()
      onHerlaad()
    }
  }

  const sync = async () => {
    setSyncBezig(true)
    setSyncFout(null)
    setSyncUitkomst(null)
    try {
      const resp = await startOdooSync(a.id)
      setSyncUitkomst(resp)
      const fouten = Object.values(resp.onderdelen).filter((o) => o.status === 'fout').length
      toast.meld(fouten === 0 ? 'Stamgegevens gesynct uit Odoo' : `Sync klaar met ${fouten} fout(en) — zie de rij Stamgegevens`, fouten === 0 ? 'ok' : 'warn')
    } catch (err) {
      setSyncFout(foutTekst(err))
    } finally {
      setSyncBezig(false)
      laad()
      onHerlaad()
    }
  }

  const stam = stand?.stamgegevens ?? null
  const rodeRegels = stand?.probe_rapport ? Object.entries(stand.probe_rapport).filter(([, v]) => v !== 'ok') : []

  return (
    <>
      <InstellingRij titel="Backend" uitleg="Boekhoud-backend van deze administratie — de company staat permanent in beeld zodat een mismatch zichtbaar is.">
        <span className="inst-links" style={{ flexWrap: 'wrap', alignItems: 'center', gap: 8 }} data-testid="backend-odoo">
          <Badge variant="paars">Odoo</Badge>
          <span className="text-muted" style={{ fontSize: 12.5 }}>
            {odooHost(url)}
            {companyId != null && (
              <>
                {' '}· company{' '}
                <b className="text-text">
                  {companyNaam ?? '—'} ({companyId})
                </b>
              </>
            )}
          </span>
          {overgangsdatum && (
            <span className="hint" style={{ margin: 0 }}>
              overgestapt per {datumNl(overgangsdatum)}
              {rlzVoorOverstap ? ` (voorheen RLZ-id ${rlzVoorOverstap})` : ''}
            </span>
          )}
        </span>
      </InstellingRij>

      <InstellingRij titel="Verbinding" uitleg={standFout ? `Stand niet op te halen: ${standFout}` : 'Rechten-probe: grootboek · btw · relaties · journals · facturen · boeken (schrijven).'}>
        {probeGroen === true && <Badge variant="ok">✓ probe groen{probeOp ? ` · ${datumTijdKort(probeOp)}` : ''}</Badge>}
        {probeGroen === false && <Badge variant="danger">✗ probe rood{probeOp ? ` · ${datumTijdKort(probeOp)}` : ''}</Badge>}
        {probeGroen === null && <Badge variant="stil">nog niet getest</Badge>}
        <Button variant="secundair" maat="klein" disabled={probeBezig || Boolean(a.gearchiveerd_op)} onClick={() => void herprobe()} aria-label={`Odoo-verbinding opnieuw testen voor ${a.naam}`}>
          {probeBezig ? 'Testen…' : 'Opnieuw testen'}
        </Button>
      </InstellingRij>
      {(rodeRegels.length > 0 || probeUitkomst) && (
        <div style={{ padding: '0 16px 10px' }} data-testid="odoo-probe-detail">
          {probeUitkomst ? (
            <div className={probeUitkomst.groen ? 'hint' : 'fout'} style={{ marginTop: 0 }}>
              {probeUitkomst.bericht ?? (probeUitkomst.groen ? 'Probe groen — alle onderdelen ok.' : 'Probe rood:')}
              {!probeUitkomst.groen && <OdooProbeRapport rapport={probeUitkomst.rapport} alleenRood />}
            </div>
          ) : (
            <OdooProbeRapport rapport={stand?.probe_rapport ?? {}} alleenRood />
          )}
        </div>
      )}

      <InstellingRij titel="API-sleutel" uitleg="De sleutel is server-side versleuteld opgeslagen (credential-store) en nooit uitleesbaar; wijzigen is probe-gated.">
        <span className="text-muted" style={{ fontSize: 12.5 }}>
          •••• ingesteld{a.odoo_api_gebruiker || stand?.api_gebruiker ? ` (${stand?.api_gebruiker ?? a.odoo_api_gebruiker})` : ''} ·{' '}
          {verlooptOp ? `verloopt ${datumNl(verlooptOp)}` : 'verloopt niet'}
        </span>
        <Button variant="secundair" maat="klein" disabled={Boolean(a.gearchiveerd_op)} onClick={() => setSleutelDialoog(true)} aria-label={`Odoo API-sleutel wijzigen voor ${a.naam}`}>
          Sleutel wijzigen…
        </Button>
      </InstellingRij>

      <InstellingRij titel="Stamgegevens" uitleg="Grootboek, btw-tarieven, relaties en projecten uit Odoo in dezelfde caches als bij Reeleezee; dagelijks in sync-alles.">
        <span className="text-muted" style={{ fontSize: 12.5 }} data-testid="odoo-stamgegevens">
          {stam
            ? `grootboek ${stam.ledgers} · btw ${stam.taxrates} · relaties ${stam.vendors} · projecten ${stam.projects}`
            : standFout
              ? 'stand onbekend'
              : 'nog niet gesynct'}
          {laatsteSync ? ` · laatst gesynct ${datumTijdKort(laatsteSync)}` : ''}
        </span>
        <Button variant="secundair" maat="klein" disabled={syncBezig || Boolean(a.gearchiveerd_op)} onClick={() => void sync()} aria-label={`Odoo-stamgegevens nu synchroniseren voor ${a.naam}`}>
          {syncBezig ? 'Sync loopt…' : '⟳ Sync nu'}
        </Button>
      </InstellingRij>
      {(syncUitkomst || syncFout) && (
        <div style={{ padding: '0 16px 10px' }} data-testid="odoo-sync-uitkomst">
          {syncFout && <div className="fout">{syncFout}</div>}
          {syncUitkomst && (
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12 }}>
              {Object.entries(syncUitkomst.onderdelen).map(([naam, o]) => (
                <li key={naam}>
                  {naam}: <span className={`chip ${o.status === 'klaar' ? 'ok' : o.status === 'fout' ? 'blokkerend' : 'stil'}`}>{o.status}</span>
                  {typeof o.aangemaakt === 'number' && (
                    <span className="hint" style={{ margin: '0 0 0 6px', fontSize: 11 }}>
                      {o.aangemaakt} nieuw · {o.bijgewerkt ?? 0} bijgewerkt
                    </span>
                  )}
                  {o.fout && <span className="fout" style={{ marginLeft: 6 }}>{o.fout}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <InstellingRij titel="Eerste sync" uitleg={a.eerste_sync && a.eerste_sync.status !== 'klaar' ? 'Bij een rode stand: foutreden + "Sync opnieuw starten".' : 'Alle onderdelen groen.'}>
        {a.eerste_sync && a.eerste_sync.status !== 'klaar' && a.eerste_sync.status !== 'geen' ? (
          <EersteSyncStatus
            compact
            administratie={{ id: a.id, naam: a.naam, rlz_admin_id: null, odoo_company_id: companyId, odoo_company_naam: companyNaam }}
            initieel={a.eerste_sync}
            onderdelen={ODOO_SYNC_ONDERDELEN}
            onAfgerond={onHerlaad}
          />
        ) : (
          <Badge variant="ok">volledig ✓</Badge>
        )}
      </InstellingRij>

      <InstellingRij titel="Leesbron voorraad" uitleg="De leesbron-variant bestaat alleen voor een Reeleezee-administratie; hier boekt Odoo zelf.">
        <Badge variant="stil">n.v.t. — volledige backend</Badge>
      </InstellingRij>

      {sleutelDialoog && (
        <OdooSleutelDialog
          administratie={a}
          huidigLabel={stand?.api_gebruiker ?? a.odoo_api_gebruiker ?? ''}
          onSluiten={() => setSleutelDialoog(false)}
          onGewijzigd={() => {
            laad()
            onHerlaad()
          }}
        />
      )}
    </>
  )
}

/** Rij "Leesbron voorraad" op een RLZ-administratie: zónder koppeling "n.v.t." + ingang B "Odoo koppelen…";
 * mét alleen-lezen-koppeling de stand (company · knip) + "Knipdatum wijzigen…". */
export function OdooLeesbronRij({ administratie: a, onHerlaad }: { administratie: AdministratieInstellingenDto; onHerlaad: () => void }) {
  const alleenLezen = Boolean(a.odoo_alleen_lezen)
  const { stand } = useOdooStand(a.id, alleenLezen)
  const [wizardOpen, setWizardOpen] = useState(false)
  const [knipDialoog, setKnipDialoog] = useState(false)
  const knip = stand?.voorraad_knip_datum ?? a.odoo_voorraad_knip_datum ?? null
  const companyNaam = stand?.company_naam ?? a.odoo_company_naam ?? null
  const companyId = stand?.company_id ?? a.odoo_company_id ?? null

  return (
    <>
      <InstellingRij
        titel="Leesbron voorraad"
        uitleg={
          alleenLezen
            ? 'Odoo levert alleen-lezen de verkoop-uitstroom (geposte verkoopfacturen en creditnota’s) vanaf de knipdatum; de Reeleezee-route stopt vanaf die datum. Backend blijft Reeleezee.'
            : 'Odoo koppelen als volledige backend (overstap mét overgangsdatum) óf als alleen-lezen leesbron voor de voorraad-uitstroom — twee verschillende dingen, de wizard vraagt het expliciet.'
        }
      >
        {alleenLezen ? (
          <span className="inst-links" style={{ flexWrap: 'wrap', alignItems: 'center', gap: 8 }} data-testid="leesbron-odoo">
            <Badge variant="paars">Odoo · leesbron</Badge>
            <span className="text-muted" style={{ fontSize: 12.5 }}>
              {companyId != null ? `${odooHost(stand?.odoo_url ?? a.odoo_url)} · company ${companyNaam ?? '—'} (${companyId}) · ` : ''}
              {knip ? `verkoop-uitstroom vanaf ${datumNl(knip)} (knip)` : 'geen knip gezet'}
            </span>
            <Button variant="secundair" maat="klein" disabled={Boolean(a.gearchiveerd_op)} onClick={() => setKnipDialoog(true)} aria-label={`Knipdatum wijzigen voor ${a.naam}`}>
              Knipdatum wijzigen…
            </Button>
          </span>
        ) : (
          <>
            <Badge variant="stil">n.v.t.</Badge>
            <Button variant="secundair" maat="klein" disabled={Boolean(a.gearchiveerd_op)} onClick={() => setWizardOpen(true)} aria-label={`Odoo koppelen aan ${a.naam}`}>
              Odoo koppelen…
            </Button>
          </>
        )}
      </InstellingRij>
      {wizardOpen && <OdooKoppelDialog administratie={{ id: a.id, naam: a.naam }} onSluiten={() => setWizardOpen(false)} onAfgerond={onHerlaad} />}
      {knipDialoog && (
        <KnipdatumDialog
          administratie={a}
          huidig={knip}
          onSluiten={() => setKnipDialoog(false)}
          onGewijzigd={() => {
            setKnipDialoog(false)
            onHerlaad()
          }}
        />
      )}
    </>
  )
}

/** "Sleutel wijzigen…": nieuwe API-sleutel (+ optioneel label) → PUT …/odoo, probe-gated — alleen groen wordt
 * opgeslagen (422 mét rapport anders). Zelfde patroon als WebserviceGegevensDialog; de sleutel reist alleen in de body. */
export function OdooSleutelDialog({
  administratie,
  huidigLabel,
  onSluiten,
  onGewijzigd,
}: {
  administratie: { id: string; naam: string }
  huidigLabel: string
  onSluiten: () => void
  onGewijzigd: () => void
}) {
  const [apiKey, setApiKey] = useState('')
  const [label, setLabel] = useState(huidigLabel)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<{ bericht: string; rapport: Record<string, string> | null } | null>(null)
  const [resultaat, setResultaat] = useState<OdooProbeDto | null>(null)

  const opslaan = async () => {
    setBezig(true)
    setFout(null)
    try {
      const resp = await probeOdooKoppeling(administratie.id, { api_key: apiKey, ...(label.trim() ? { api_gebruiker: label.trim() } : {}) })
      setResultaat(resp)
      setApiKey('')
      onGewijzigd()
    } catch (err) {
      setFout(odooKoppelFout(err))
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && !bezig && onSluiten()}>
      <DialogContent aria-describedby={undefined} data-testid="odoo-sleutel-dialoog">
        <DialogTitle>Odoo API-sleutel — {administratie.naam}</DialogTitle>
        <DialogDescription>
          De huidige sleutel is aanwezig maar niet uitleesbaar. De nieuwe sleutel wordt eerst getest (verbinding + rechten-probe op
          dezelfde company); alleen bij groen wordt hij versleuteld opgeslagen en de oude vervangen (sleutelrotatie, geauditeerd
          zonder sleutel).
        </DialogDescription>
        {resultaat ? (
          <div>
            <p className="ok" style={{ margin: 0 }}>
              {odooProbeGroen(resultaat.rapport) || resultaat.groen ? 'Opgeslagen — rechten-probe groen.' : 'Opgeslagen — zie het rapport.'}
            </p>
            <OdooProbeRapport rapport={resultaat.rapport} />
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
            <FormField label="Nieuwe API-sleutel" htmlFor="odoo-nieuwe-sleutel">
              <input id="odoo-nieuwe-sleutel" type="password" autoComplete="new-password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} required />
            </FormField>
            <FormField label="API-gebruiker (label, optioneel)" htmlFor="odoo-sleutel-label">
              <input id="odoo-sleutel-label" autoComplete="off" value={label} onChange={(e) => setLabel(e.target.value)} />
            </FormField>
            {fout && (
              <div className="fout">
                {fout.bericht}
                {fout.rapport && <OdooProbeRapport rapport={fout.rapport} />}
              </div>
            )}
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={onSluiten} disabled={bezig}>
                Annuleren
              </Button>
              <Button type="submit" disabled={bezig || !apiKey}>
                {bezig ? 'Testen en opslaan…' : 'Testen en opslaan'}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}

/** "Knipdatum wijzigen…" (leesbron): PUT …/odoo/leesbron {voorraad_knip_datum}; leeg = geen knip. */
export function KnipdatumDialog({
  administratie,
  huidig,
  onSluiten,
  onGewijzigd,
}: {
  administratie: { id: string; naam: string }
  huidig: string | null
  onSluiten: () => void
  onGewijzigd: () => void
}) {
  const [knip, setKnip] = useState(huidig ?? '')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const opslaan = async () => {
    setBezig(true)
    setFout(null)
    try {
      await zetOdooKnipdatum(administratie.id, knip || null)
      onGewijzigd()
    } catch (err) {
      setFout(foutTekst(err))
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && !bezig && onSluiten()}>
      <DialogContent aria-describedby={undefined} data-testid="knipdatum-dialoog">
        <DialogTitle>Knipdatum voorraad-uitstroom — {administratie.naam}</DialogTitle>
        <DialogDescription>
          Vanaf deze datum levert Odoo de verkoop-uitstroom en registreert de Reeleezee-route niets meer. Een verschuiving
          herrekent de voorraadaansluiting; niets wordt in Odoo of Reeleezee gewijzigd. Geauditeerd (oud → nieuw).
        </DialogDescription>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void opslaan()
          }}
        >
          <FormField label="Knipdatum" htmlFor="odoo-knip-wijzig" hint="Leeg = geen knip (Odoo levert dan géén uitstroom).">
            <input id="odoo-knip-wijzig" type="date" value={knip} onChange={(e) => setKnip(e.target.value)} />
          </FormField>
          {fout && <div className="fout">{fout}</div>}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onSluiten} disabled={bezig}>
              Annuleren
            </Button>
            <Button type="submit" disabled={bezig}>
              {bezig ? 'Opslaan…' : 'Knipdatum opslaan'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
