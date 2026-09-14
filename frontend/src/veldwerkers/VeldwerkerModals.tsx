// Dialogen van het veldwerkers-beheer (veldwerkers-run 14-09): één-op-één verhuisd uit gebruikers/VeldwerkersPanel.tsx
// (22-08 crediteur & tarieven, 07-09 C3 voorgeselecteerde administratie) — de tabel leeft nu op /veldwerkers
// (VeldwerkersScreen), het paneel op Gebruikers & toegang is een account-tabel. Nieuw: ZzperBureausModal (de
// omgekeerde koppeling: vanaf een ZZP'er-rij "Detacheerder koppelen…", zelfde API-routes).
import { useEffect, useState } from 'react'
import { ApiError, apiJson } from '../api/client'
import type { AdministratieDto, VendorLijstDto } from '../api/types'
import {
  koppelDetacheerder,
  koppelVeldwerkerCrediteur,
  ontkoppelDetacheerder,
  ontkoppelVeldwerkerCrediteur,
  zetDetacheerderTarief,
  zetVeldwerkerAutoboeken,
  type VeldgebruikerDto,
} from '../meerwerk/meerwerkApi'
import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  FormField,
  MultiSelect,
  Select,
  Switch,
} from '../ui/basis'
import { AdministratieCombobox } from '../ui/AdministratieCombobox'
import { kiesStandaardAdministratie, standaardRedenLabel, urenMeerwerkOptIns } from '../gebruikers/standaardAdministratie'

export function tariefLabel(uurtarief: string): string {
  return `€ ${Number(uurtarief).toLocaleString('nl-NL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}/u`
}

const BRON_LABEL: Record<string, string> = { planning: 'via planning', weekstaat: 'via uren buiten planning', handmatig: 'handmatig (vóór 04-09)' }

/** Afgeleide projecttoegang, alleen-lezen (C2 04-09): "actief op N projecten (via planning)" mét uitklap
 * per project + herkomst. Geen selectie-UI meer — koppelingen ontstaan uitsluitend via de planning
 * (of uren buiten planning); bestaande handmatige koppelingen blijven zichtbaar en staan. */
export function ProjectToegang({
  info,
  rol,
  uitgeklapt,
  toggle,
}: {
  info: VeldgebruikerDto
  rol: string
  uitgeklapt: boolean
  toggle: () => void
}) {
  const aantal = info.projecten.length
  const viaPlanning = info.projecten.filter((t) => t.bron === 'planning').length
  if (aantal === 0) {
    return (
      <div style={{ fontSize: 11, color: 'var(--muted)' }}>
        nog geen projecten — toegang ontstaat zodra deze {rol === 'zzper' ? "ZZP'er" : 'uitvoerder'} in de planning staat
      </div>
    )
  }
  return (
    <div>
      <button type="button" className="linkbtn" onClick={toggle} aria-expanded={uitgeklapt} data-testid="projecttoegang">
        actief op {aantal} {aantal === 1 ? 'project' : 'projecten'}
        {viaPlanning === aantal ? ' (via planning)' : viaPlanning > 0 ? ` (${viaPlanning} via planning)` : ''} {uitgeklapt ? '▾' : '▸'}
      </button>
      {uitgeklapt && (
        <ul style={{ margin: '4px 0 0', paddingLeft: 16, fontSize: 12 }}>
          {info.projecten.map((t) => (
            <li key={`${t.administratie_id}-${t.project_id}`}>
              {t.project_naam ?? t.project_id}
              {t.administratie_naam ? ` · ${t.administratie_naam}` : ''}{' '}
              <Badge variant="stil">{BRON_LABEL[t.bron] ?? t.bron}</Badge>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function DetacheerderKoppelModal({
  detacheerder,
  zzpers,
  onSluiten,
  onGewijzigd,
}: {
  detacheerder: VeldgebruikerDto
  zzpers: VeldgebruikerDto[]
  onSluiten: () => void
  onGewijzigd: () => void
}) {
  const huidige = detacheerder.zzpers.map((z) => z.gebruiker_id)
  const [selectie, setSelectie] = useState<string[]>(huidige)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const erbij = selectie.filter((id) => !huidige.includes(id))
  const eraf = huidige.filter((id) => !selectie.includes(id))

  async function opslaan() {
    setBezig(true)
    setFout(null)
    try {
      for (const zzperId of erbij) await koppelDetacheerder(detacheerder.gebruiker_id, zzperId)
      for (const zzperId of eraf) await ontkoppelDetacheerder(detacheerder.gebruiker_id, zzperId)
      onGewijzigd()
      onSluiten()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Koppelen mislukt.')
      onGewijzigd()
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onSluiten()}>
      <DialogContent>
        <DialogTitle>ZZP'ers van {detacheerder.naam}</DialogTitle>
        <DialogDescription>
          De detacheerder vult weekstaten in NAMENS deze ZZP'ers — exact dezelfde schermen en velden; elke invoer
          wordt vastgelegd als "ingevuld door {detacheerder.naam} namens …" (zichtbaar bij de keuring en in het
          audit-log). Projectinhoud (specs, contract, meerwerk) ziet een detacheerder nooit.
        </DialogDescription>
        {zzpers.length === 0 && <p className="hint">Er zijn nog geen ZZP'ers om te koppelen.</p>}
        <MultiSelect
          opties={zzpers.map((z) => ({ waarde: z.gebruiker_id, label: z.naam }))}
          waarden={selectie}
          onChange={setSelectie}
          zoekPlaceholder="Zoek ZZP'er…"
        />
        {(erbij.length > 0 || eraf.length > 0) && (
          <p className="hint">
            {erbij.length > 0 && `${erbij.length} erbij`}
            {erbij.length > 0 && eraf.length > 0 && ' · '}
            {eraf.length > 0 && `${eraf.length} eraf`}
          </p>
        )}
        {fout && <div className="fout">{fout}</div>}
        <DialogFooter>
          <Button variant="secundair" onClick={onSluiten} disabled={bezig}>
            Annuleren
          </Button>
          <Button onClick={() => void opslaan()} disabled={bezig || (erbij.length === 0 && eraf.length === 0)}>
            {bezig ? 'Bezig…' : 'Koppelingen opslaan'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Crediteur-koppeling + los ZZP-uurtarief per administratie (factuurmatch fase 3, besluiten
 * Peter 21-08): welke RLZ-crediteur factureert het werk van deze veldwerker. Eén crediteur
 * per veldwerker per administratie (upsert); het uurtarief hoort alleen bij een ZZP'er —
 * bureau-tarieven staan per detacheerder↔zzp'er-koppeling (BureauTarievenModal). */
export function CrediteurModal({
  veldwerker,
  administraties,
  onSluiten,
  onGewijzigd,
}: {
  veldwerker: VeldgebruikerDto
  administraties: AdministratieDto[]
  onSluiten: () => void
  onGewijzigd: () => void
}) {
  // Fixrun 07-09 blok C3: opent VOORGESELECTEERD zonder picker-poort — één in scope → die; anders de
  // recentste koppeling (hier vóór de planning), anders de administratie mét uren-&-meerwerk-opt-in.
  const [standaard] = useState(() =>
    kiesStandaardAdministratie(
      administraties,
      {
        recentsteKoppeling: veldwerker.recentste_koppeling_administratie_id ?? veldwerker.crediteuren[0]?.administratie_id,
        recentstePlanning: veldwerker.recentste_planning_administratie_id,
        voorkeur: 'koppeling',
      },
      { urenMeerwerk: urenMeerwerkOptIns(administraties) },
    ),
  )
  const [administratieId, setAdministratieId] = useState(
    standaard?.id ?? veldwerker.crediteuren[0]?.administratie_id ?? administraties[0]?.id ?? '',
  )
  const standaardUitleg = standaard && administratieId === standaard.id ? standaardRedenLabel(standaard.reden) : null
  const [crediteuren, setCrediteuren] = useState<{ id: string; naam: string | null }[] | null>(null)
  const huidige = veldwerker.crediteuren.find((c) => c.administratie_id === administratieId) ?? null
  const [vendorId, setVendorId] = useState('')
  const [tarief, setTarief] = useState('')
  // Lokale spiegel van de autoboek-opt-in: de prop is een momentopname (de lijst herlaadt op
  // de achtergrond terwijl de modal openstaat) — pas ná een geslaagde server-call bijgewerkt.
  const [autoboeken, setAutoboeken] = useState(huidige?.autoboeken_ingeschakeld ?? false)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  useEffect(() => {
    if (!administratieId) return
    const koppeling = veldwerker.crediteuren.find((c) => c.administratie_id === administratieId) ?? null
    setVendorId(koppeling?.vendor_id ?? '')
    setTarief(koppeling?.uurtarief ?? '')
    setAutoboeken(koppeling?.autoboeken_ingeschakeld ?? false)
    setCrediteuren(null)
    setFout(null)
    apiJson<VendorLijstDto>(`/administraties/${administratieId}/crediteuren`)
      .then((data) => setCrediteuren(data.crediteuren))
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Crediteuren laden mislukt'))
    // veldwerker verandert niet tijdens een open modal
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [administratieId])

  async function opslaan() {
    setBezig(true)
    setFout(null)
    try {
      await koppelVeldwerkerCrediteur({
        administratie_id: administratieId,
        gebruiker_id: veldwerker.gebruiker_id,
        vendor_id: vendorId,
        uurtarief: veldwerker.rol === 'zzper' && tarief.trim() !== '' ? tarief.replace(',', '.') : null,
      })
      onGewijzigd()
      onSluiten()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Koppelen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  async function ontkoppelen() {
    setBezig(true)
    setFout(null)
    try {
      await ontkoppelVeldwerkerCrediteur(administratieId, veldwerker.gebruiker_id)
      onGewijzigd()
      onSluiten()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Ontkoppelen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  async function wisselAutoboeken(ingeschakeld: boolean) {
    setBezig(true)
    setFout(null)
    try {
      await zetVeldwerkerAutoboeken(administratieId, veldwerker.gebruiker_id, ingeschakeld)
      setAutoboeken(ingeschakeld) // pas ná de geslaagde server-call — nooit optimistisch
      onGewijzigd()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Autoboeken wijzigen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onSluiten()}>
      <DialogContent>
        <DialogTitle>Crediteur van {veldwerker.naam}</DialogTitle>
        <DialogDescription>
          Facturen van deze crediteur worden automatisch gematcht tegen de goedgekeurde urenstaten
          {veldwerker.rol === 'zzper'
            ? ' van deze ZZP’er (uren × uurtarief; zonder tarief alleen op uren — oranje).'
            : ' van de aan dit bureau gekoppelde ZZP’ers (uren × bureau-tarief per ZZP’er — knop "tarieven…").'}{' '}
          Eén veldwerker per crediteur; elke wijziging wordt geauditeerd.
        </DialogDescription>
        <AdministratieCombobox
          label="Administratie"
          administraties={administraties}
          waarde={administratieId}
          onWijzig={setAdministratieId}
        />
        {standaardUitleg && (
          <p className="hint" style={{ marginTop: -4 }} data-testid="standaard-administratie-uitleg">
            {standaardUitleg}
          </p>
        )}
        {crediteuren === null && !fout && <p className="hint">Crediteuren laden…</p>}
        {crediteuren !== null && (
          <FormField label="Crediteur (uit Reeleezee)" htmlFor="crediteur-vendor">
            <Select
              id="crediteur-vendor"
              className="w-full"
              value={vendorId}
              onChange={(e) => setVendorId(e.target.value)}
            >
              <option value="">— kies een crediteur —</option>
              {crediteuren.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.naam ?? c.id}
                </option>
              ))}
            </Select>
          </FormField>
        )}
        {veldwerker.rol === 'zzper' && (
          <FormField label="Uurtarief (optioneel — zonder tarief matcht alleen op uren)" htmlFor="crediteur-tarief">
            <input
              id="crediteur-tarief"
              type="number"
              inputMode="decimal"
              min="0"
              step="0.01"
              placeholder="bijv. 42,50"
              value={tarief}
              onChange={(e) => setTarief(e.target.value)}
            />
          </FormField>
        )}
        {/* Factuurmatch fase 4 (besluit 4, 21-08): autoboek-opt-in per koppeling — default
            UIT, direct effect (eigen audit-actie, los van de opslaan-knop). Het slot blijft
            strikt: alleen een GROENE match incl. bedrag + alle bestaande autoboek-poorten. */}
        {huidige !== null && (
          <div
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: 10,
              padding: '10px 12px',
              border: '1px solid var(--border)',
              borderRadius: 8,
            }}
          >
            <Switch
              id="crediteur-autoboeken"
              aria-label="Automatisch boeken bij een groene urenmatch"
              checked={autoboeken}
              disabled={bezig}
              onChange={(e) => void wisselAutoboeken(e.target.checked)}
            />
            <label htmlFor="crediteur-autoboeken" style={{ fontSize: 12.5, lineHeight: 1.5 }}>
              <b>Automatisch boeken bij een groene urenmatch</b>
              <span style={{ display: 'block', color: 'var(--muted)' }}>
                Boekt uitsluitend als de match GROEN is inclusief bedrag (tarief dus ingevuld) én alle vaste
                autoboek-poorten slagen (harde checks, bevestigd boekingsgeheugen, geen duplicaat/vraag,
                volumerem, accordering). Elke boeking draagt de markering &quot;automatisch&quot;; storno blijft de
                terugweg. Wijziging werkt per direct en wordt geauditeerd.
              </span>
            </label>
          </div>
        )}
        {fout && <div className="fout">{fout}</div>}
        <DialogFooter>
          {huidige !== null && (
            <Button variant="secundair" onClick={() => void ontkoppelen()} disabled={bezig}>
              Ontkoppelen
            </Button>
          )}
          <Button variant="secundair" onClick={onSluiten} disabled={bezig}>
            Annuleren
          </Button>
          <Button onClick={() => void opslaan()} disabled={bezig || vendorId === ''}>
            {bezig ? 'Bezig…' : 'Opslaan'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Bureau-tarief per detacheerder↔zzp'er-koppeling (besluit 1, 21-08: hét hoofdmechanisme van
 * de bureaufactuurmatch — bureaus factureren per ZZP'er verschillende tarieven). Leeg laten =
 * "geen tarief bekend" (match alleen op uren, oranje — geen blokkade). */
export function BureauTarievenModal({
  detacheerder,
  onSluiten,
  onGewijzigd,
}: {
  detacheerder: VeldgebruikerDto
  onSluiten: () => void
  onGewijzigd: () => void
}) {
  const [tarieven, setTarieven] = useState<Record<string, string>>(() =>
    Object.fromEntries(detacheerder.zzpers.map((z) => [z.gebruiker_id, z.uurtarief ?? ''])),
  )
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const gewijzigd = detacheerder.zzpers.filter((z) => (z.uurtarief ?? '') !== (tarieven[z.gebruiker_id] ?? ''))

  async function opslaan() {
    setBezig(true)
    setFout(null)
    try {
      for (const z of gewijzigd) {
        const waarde = (tarieven[z.gebruiker_id] ?? '').trim()
        await zetDetacheerderTarief(
          detacheerder.gebruiker_id,
          z.gebruiker_id,
          waarde === '' ? null : waarde.replace(',', '.'),
        )
      }
      onGewijzigd()
      onSluiten()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Tarieven opslaan mislukt.')
      onGewijzigd()
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onSluiten()}>
      <DialogContent>
        <DialogTitle>Bureau-tarieven van {detacheerder.naam}</DialogTitle>
        <DialogDescription>
          Het tarief per gekoppelde ZZP'er — de bureaufactuur wordt gematcht op de som van
          (goedgekeurde uren × tarief) per ZZP'er. Leeg = geen tarief bekend: match alleen op uren (oranje).
        </DialogDescription>
        {detacheerder.zzpers.map((z) => (
          <FormField key={z.gebruiker_id} label={z.naam} htmlFor={`tarief-${z.gebruiker_id}`}>
            <input
              id={`tarief-${z.gebruiker_id}`}
              type="number"
              inputMode="decimal"
              min="0"
              step="0.01"
              placeholder="geen tarief bekend"
              value={tarieven[z.gebruiker_id] ?? ''}
              onChange={(e) => setTarieven((t) => ({ ...t, [z.gebruiker_id]: e.target.value }))}
            />
          </FormField>
        ))}
        {fout && <div className="fout">{fout}</div>}
        <DialogFooter>
          <Button variant="secundair" onClick={onSluiten} disabled={bezig}>
            Annuleren
          </Button>
          <Button onClick={() => void opslaan()} disabled={bezig || gewijzigd.length === 0}>
            {bezig ? 'Bezig…' : 'Tarieven opslaan'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}


/** Omgekeerde koppeling (veldwerkers-run 14-09): vanaf een ZZP'er-rij de bureaus kiezen die namens deze ZZP'er
 * invullen — dezelfde routes als DetacheerderKoppelModal (koppel/ontkoppel per paar), geaudit. */
export function ZzperBureausModal({
  zzper,
  detacheerders,
  onSluiten,
  onGewijzigd,
}: {
  zzper: VeldgebruikerDto
  detacheerders: VeldgebruikerDto[]
  onSluiten: () => void
  onGewijzigd: () => void
}) {
  const huidige = detacheerders.filter((d) => d.zzpers.some((z) => z.gebruiker_id === zzper.gebruiker_id)).map((d) => d.gebruiker_id)
  const [selectie, setSelectie] = useState<string[]>(huidige)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const erbij = selectie.filter((id) => !huidige.includes(id))
  const eraf = huidige.filter((id) => !selectie.includes(id))

  async function opslaan() {
    setBezig(true)
    setFout(null)
    try {
      for (const id of erbij) await koppelDetacheerder(id, zzper.gebruiker_id)
      for (const id of eraf) await ontkoppelDetacheerder(id, zzper.gebruiker_id)
      onGewijzigd()
      onSluiten()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Koppelen mislukt.')
      onGewijzigd()
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onSluiten()}>
      <DialogContent>
        <DialogTitle>Detacheerder van {zzper.naam}</DialogTitle>
        <DialogDescription>
          Een gekoppelde detacheerder (bureau) vult weekstaten in NAMENS deze ZZP'er en factureert het werk per
          bureau-tarief (knop "Bureau-tarieven…" op de detacheerder-rij). Elke wijziging wordt geauditeerd.
        </DialogDescription>
        {detacheerders.length === 0 && <p className="hint">Er zijn nog geen detacheerders om te koppelen.</p>}
        <MultiSelect
          opties={detacheerders.map((d) => ({ waarde: d.gebruiker_id, label: d.naam }))}
          waarden={selectie}
          onChange={setSelectie}
          zoekPlaceholder="Zoek detacheerder…"
        />
        {(erbij.length > 0 || eraf.length > 0) && (
          <p className="hint">
            {erbij.length > 0 && `${erbij.length} erbij`}
            {erbij.length > 0 && eraf.length > 0 && ' · '}
            {eraf.length > 0 && `${eraf.length} eraf`}
          </p>
        )}
        {fout && <div className="fout">{fout}</div>}
        <DialogFooter>
          <Button variant="secundair" onClick={onSluiten} disabled={bezig}>
            Annuleren
          </Button>
          <Button onClick={() => void opslaan()} disabled={bezig || (erbij.length === 0 && eraf.length === 0)}>
            {bezig ? 'Bezig…' : 'Koppelingen opslaan'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
