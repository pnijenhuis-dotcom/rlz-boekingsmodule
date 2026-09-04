import { useCallback, useEffect, useState } from 'react'
import type { AdministratieInstellingenDto } from '../api/types'
import { Badge, Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle, FormField, useToastOptioneel } from '../ui/basis'
import { EersteSyncStatus } from './AdministratieWizard'
import { InstellingRij } from './AdministratieDetailPagina'
import { ApiError } from '../api/client'
import {
  corrigeerOdooMapping,
  haalOdooMappingOp,
  haalOdooStandOp,
  ODOO_SYNC_ONDERDELEN,
  probeOdooKoppeling,
  startOdooSync,
  zetOdooKnipdatum,
  zetOdooOvergangsdatum,
  type OdooMappingStandDto,
  type OdooProbeDto,
  type OdooStandDto,
  type OdooSyncResultaatDto,
} from './instellingenApi'
import { OdooKoppelDialog } from './OdooKoppelWizard'
import { mappingSleutel, OdooMappingTabel, rijenUitStand, type MappingTabelRij } from './OdooMappingTabel'
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
  const [mappingDialoog, setMappingDialoog] = useState(false)
  const [overgangDialoog, setOvergangDialoog] = useState(false)
  const { mapping, fout: mappingFout, laad: laadMapping, zet: zetMapping } = useOdooMapping(a.id, !a.odoo_alleen_lezen)

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
            <span className="hint" style={{ margin: 0 }} data-testid="odoo-overgangsdatum">
              overgestapt per {datumNl(overgangsdatum)}
              {rlzVoorOverstap ? ` (voorheen RLZ-id ${rlzVoorOverstap})` : ''}
              {/* C1 (04-09): alleen bij een overstap (volledige backend mét overgangsdatum). */}
              {!a.gearchiveerd_op && (
                <>
                  {' '}
                  <button type="button" className="linkbtn" onClick={() => setOvergangDialoog(true)} aria-label={`Overgangsdatum wijzigen voor ${a.naam}`}>
                    Overgangsdatum wijzigen…
                  </button>
                </>
              )}
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

      {/* Blok A 04-09: de bij de overstap bevestigde rekening-mapping (geheugen vertaalt erlangs); correctie per
          rij = nieuwe versie. Een Odoo-administratie zónder RLZ-verleden heeft geen mapping — dan alleen de tekst. */}
      <InstellingRij titel="Rekening-mapping" uitleg="Vertaling Reeleezee-grootboek/btw → Odoo waarlangs het boekingsgeheugen (en de autoboek-instellingen) ná de overstap blijven werken; correctie per rij, append-only.">
        <span className="text-muted" style={{ fontSize: 12.5 }} data-testid="odoo-mapping-stand">
          {mappingFout
            ? `stand niet op te halen: ${mappingFout}`
            : mapping === undefined
              ? 'laden…'
              : !mapping || (mapping.grootboek.length === 0 && mapping.btw.length === 0)
                ? 'geen mapping — nieuwe Odoo-administratie zonder RLZ-verleden'
                : `${mapping.grootboek.length} grootboek · ${mapping.btw.length} btw${
                    mapping.laatst_bevestigd_op ? ` · bevestigd ${datumTijdKort(mapping.laatst_bevestigd_op)}` : ''
                  }${mapping.laatst_bevestigd_door_naam ? ` door ${mapping.laatst_bevestigd_door_naam}` : ''}`}
        </span>
        {mapping && (mapping.grootboek.length > 0 || mapping.btw.length > 0) && (
          <Button variant="secundair" maat="klein" disabled={Boolean(a.gearchiveerd_op)} onClick={() => setMappingDialoog(true)} aria-label={`Rekening-mapping bekijken of corrigeren voor ${a.naam}`}>
            Mapping bekijken/corrigeren…
          </Button>
        )}
      </InstellingRij>

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
      {mappingDialoog && mapping && (
        <OdooMappingDialog administratie={a} stand={mapping} onStand={zetMapping} onSluiten={() => setMappingDialoog(false)} onHerlaad={laadMapping} />
      )}
      {overgangDialoog && overgangsdatum && (
        <OvergangsdatumDialog
          administratie={a}
          huidig={overgangsdatum}
          onSluiten={() => setOvergangDialoog(false)}
          onGewijzigd={() => {
            setOvergangDialoog(false)
            laad()
            onHerlaad()
          }}
        />
      )}
    </>
  )
}

/** Geldende rekening-mapping (GET …/odoo/mapping): `undefined` = nog aan het laden, `null` = geen koppeling (404). */
function useOdooMapping(administratieId: string, actief: boolean) {
  const [mapping, setMapping] = useState<OdooMappingStandDto | null | undefined>(undefined)
  const [fout, setFout] = useState<string | null>(null)
  const laad = useCallback(() => {
    if (!actief) return
    haalOdooMappingOp(administratieId)
      .then((m) => {
        setMapping(m)
        setFout(null)
      })
      .catch((err: unknown) => setFout(foutTekst(err)))
  }, [administratieId, actief])
  useEffect(() => {
    laad()
  }, [laad])
  return { mapping, fout, laad, zet: setMapping }
}

/** "Mapping bekijken/corrigeren…": de tabel in corrigeer-modus — élke gewijzigde rij is direct een
 * PUT …/odoo/mapping/{soort}/{rlz_id} (nieuwe versie, bron 'handmatig', audit oud→nieuw). 422 (onbekende
 * Odoo-id) = zichtbare fout, de rij houdt zijn oude waarde. */
export function OdooMappingDialog({
  administratie,
  stand,
  onStand,
  onSluiten,
  onHerlaad,
}: {
  administratie: { id: string; naam: string }
  stand: OdooMappingStandDto
  onStand: (stand: OdooMappingStandDto) => void
  onSluiten: () => void
  onHerlaad: () => void
}) {
  const toast = useToastOptioneel()
  const [bezigSleutel, setBezigSleutel] = useState<string | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const rijen = rijenUitStand(stand)

  const corrigeer = async (rij: MappingTabelRij, odooId: number | null) => {
    // Een mapping-rij kan niet leeg worden gemaakt: de overstap eiste een tegenhanger en het geheugen leest erlangs.
    if (odooId == null || odooId === rij.odoo_id) return
    const sleutel = mappingSleutel(rij.soort, rij.rlz_id)
    setBezigSleutel(sleutel)
    setFout(null)
    try {
      const nieuw = await corrigeerOdooMapping(administratie.id, rij.soort, rij.rlz_id, odooId)
      onStand(nieuw)
      const nieuweRij = [...nieuw.grootboek, ...nieuw.btw].find((r) => r.soort === rij.soort && r.rlz_id === rij.rlz_id)
      toast.meld(`Mapping gecorrigeerd${nieuweRij ? ` (v${nieuweRij.versie})` : ''} — ${rij.rlz_code ?? rij.rlz_naam ?? rij.rlz_id} → ${nieuweRij?.odoo_code ?? nieuweRij?.odoo_naam ?? odooId}`, 'ok')
    } catch (err) {
      setFout(foutTekst(err))
    } finally {
      setBezigSleutel(null)
    }
  }

  return (
    <Dialog
      open
      onOpenChange={(o) => {
        if (o || bezigSleutel) return
        onSluiten()
        onHerlaad()
      }}
    >
      {/* Geen auto-focus: het eerste focusbare element is een combobox, die zou bij openen direct zijn lijst uitklappen. */}
      <DialogContent breed aria-describedby={undefined} data-testid="odoo-mapping-dialoog" onOpenAutoFocus={(e) => e.preventDefault()}>
        <DialogTitle>Rekening-mapping Reeleezee → Odoo — {administratie.naam}</DialogTitle>
        <DialogDescription>
          Bevestigd bij de overstap{stand.laatst_bevestigd_op ? ` op ${datumTijdKort(stand.laatst_bevestigd_op)}` : ''}
          {stand.laatst_bevestigd_door_naam ? ` door ${stand.laatst_bevestigd_door_naam}` : ''}. Een correctie geldt per direct voor nieuwe
          voorstellen uit het boekingsgeheugen en wordt als nieuwe versie vastgelegd (eerdere versies blijven in de audit); reeds geboekte
          documenten veranderen niet.
        </DialogDescription>
        <OdooMappingTabel rijen={rijen} odooGrootboek={stand.odoo_grootboek} odooBtw={stand.odoo_btw} onKies={(rij, id) => void corrigeer(rij, id)} modus="corrigeren" bezigSleutel={bezigSleutel} />
        {fout && (
          <div className="fout" style={{ marginTop: 10 }}>
            {fout}
          </div>
        )}
        <DialogFooter>
          <Button
            type="button"
            onClick={() => {
              onSluiten()
              onHerlaad()
            }}
            disabled={Boolean(bezigSleutel)}
          >
            Sluiten
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** C1 (04-09): "Overgangsdatum wijzigen…" → PUT …/odoo/overgangsdatum. De server weigert met 409 zodra er al een
 * Odoo-boeking mét factuurdatum vóór de nieuwe datum bestaat (bericht noemt aantal + oudste boekstuk) — de
 * dialoog toont die servertekst rood en blijft open; 200 = toast + herlaad bij de aanroeper. */
export function OvergangsdatumDialog({
  administratie,
  huidig,
  onSluiten,
  onGewijzigd,
}: {
  administratie: { id: string; naam: string }
  huidig: string
  onSluiten: () => void
  onGewijzigd: () => void
}) {
  const toast = useToastOptioneel()
  const [datum, setDatum] = useState(huidig)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<{ tekst: string; geblokkeerd: boolean } | null>(null)

  const opslaan = async () => {
    setBezig(true)
    setFout(null)
    try {
      await zetOdooOvergangsdatum(administratie.id, datum)
      toast.meld(`Overgangsdatum gewijzigd naar ${datumNl(datum)}`, 'ok')
      onGewijzigd()
    } catch (err) {
      setFout({ tekst: foutTekst(err), geblokkeerd: err instanceof ApiError && err.status === 409 })
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && !bezig && onSluiten()}>
      <DialogContent aria-describedby={undefined} data-testid="overgangsdatum-dialoog">
        <DialogTitle>Overgangsdatum — {administratie.naam}</DialogTitle>
        <DialogDescription>
          Facturen mét factuurdatum vóór deze datum boeken in Reeleezee; vanaf deze datum boekt de administratie in Odoo. De datum kan
          niet vóór een al in Odoo geboekte factuur komen te liggen — de server weigert dat en noemt het boekstuk. Geauditeerd (oud → nieuw).
        </DialogDescription>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void opslaan()
          }}
        >
          <FormField label="Overgangsdatum" htmlFor="odoo-overgangsdatum-wijzig" hint={`Huidig: ${datumNl(huidig)}`}>
            <input id="odoo-overgangsdatum-wijzig" type="date" value={datum} onChange={(e) => setDatum(e.target.value)} required />
          </FormField>
          {fout && (
            <div className="fout" data-testid="overgangsdatum-fout">
              {fout.tekst}
              {fout.geblokkeerd && (
                <div className="hint" style={{ marginTop: 4 }}>
                  Niets gewijzigd — kies een datum op of vóór dat boekstuk, of boek die factuur eerst tegen.
                </div>
              )}
            </div>
          )}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onSluiten} disabled={bezig}>
              Annuleren
            </Button>
            <Button type="submit" disabled={bezig || !datum || datum === huidig}>
              {bezig ? 'Opslaan…' : 'Overgangsdatum opslaan'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
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
