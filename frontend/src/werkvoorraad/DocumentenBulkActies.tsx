import { useMemo, useRef, useState } from 'react'
import { ApiError, apiPostJson } from '../api/client'
import type { AdministratieDto, DocumentListItemDto } from '../api/types'
import { AdministratieCombobox } from '../ui/AdministratieCombobox'
import { AnkerPopup, Button, Checkbox, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle, Select, useToastOptioneel } from '../ui/basis'
import { useAdministraties } from './useAdministraties'

/* Bulk-acties op de klant-documentenlijst (Peter 16-09: "nu moet dat 1 voor 1"; casus ProfX Journaal-kassarapporten als
 * inkoopfactuur in de werkvoorraad). Zelfde patroon als de bulk-afvoer op de duplicaat-tab (B2 07-09): checkbox per rij +
 * kop-checkbox "alle N in deze weergave" (de weergave is een client-side filter — de zichtbare rijen gaan als id-lijst, max
 * 500), selectiebalk mét teller, één primaire knop (Verwijderen…) + ⋯ (Type wijzigen…, Verplaatsen naar administratie…,
 * Afwijzen…), één reden voor de hele selectie, bevestiging, uitkomst per rij (gelukt / overgeslagen mét reden / geen
 * toegang) ná afloop uitklapbaar, lijst herladen, selectie leeg. Alles N × de bestaande per-document-route server-side
 * (`POST …/documenten/bulk`); niets in RLZ/Odoo. Shift-klik = bereik (helper `bereikSelectie`). */

export type BulkActie = 'verwijderen' | 'afwijzen' | 'soort_wijzigen' | 'verplaatsen'

export interface DocumentenBulkRijDto {
  document_id: string
  bestandsnaam: string | null
  uitkomst: 'gelukt' | 'overgeslagen' | 'geen_toegang' | string
  reden: string | null
  status: string | null
}

export interface DocumentenBulkResponseDto {
  actie: string
  geselecteerd: number
  gelukt: number
  overgeslagen: number
  geen_toegang: number
  rijen: DocumentenBulkRijDto[]
}

export interface BulkBody {
  document_ids: string[]
  actie: BulkActie
  reden?: string
  soort?: 'inkoopfactuur' | 'kassarapport' | 'verplichting'
  doel_administratie_id?: string
  onthoud_tenaamstelling?: boolean
}

export function bulkDocumentActie(administratieId: string, body: BulkBody): Promise<DocumentenBulkResponseDto> {
  return apiPostJson(`/administraties/${administratieId}/documenten/bulk`, body)
}

/** Eindstatussen selecteer je niet in bulk (daar is alleen Openen/Herstellen); de rest wél — de server beslist per rij. */
export const NIET_BULK_SELECTEERBAAR = new Set(['geboekt', 'verwijderd', 'afgewezen', 'samengevoegd', 'afgevoerd_duplicaat', 'gesplitst', 'geaccordeerd'])

export function isBulkSelecteerbaar(d: Pick<DocumentListItemDto, 'status'>): boolean {
  return !NIET_BULK_SELECTEERBAAR.has(d.status)
}

/** Shift-klik: alle rijen tussen de laatst aangeklikte en deze rij (in lijstvolgorde) erbij — puur. */
export function bereikSelectie(ids: string[], laatste: string | null, huidige: string, selectie: Set<string>): Set<string> {
  const n = new Set(selectie)
  const van = laatste ? ids.indexOf(laatste) : -1
  const tot = ids.indexOf(huidige)
  if (van < 0 || tot < 0) {
    n.add(huidige)
    return n
  }
  const [a, b] = van < tot ? [van, tot] : [tot, van]
  for (const id of ids.slice(a, b + 1)) n.add(id)
  return n
}

export const ACTIE_LABEL: Record<BulkActie, string> = {
  verwijderen: 'Verwijderen',
  afwijzen: 'Afwijzen',
  soort_wijzigen: 'Type wijzigen',
  verplaatsen: 'Verplaatsen naar administratie',
}

const SOORT_LABEL: Record<NonNullable<BulkBody['soort']>, string> = {
  inkoopfactuur: 'Inkoopfactuur',
  kassarapport: 'Kassarapport (omzetboeking)',
  verplichting: 'Offerte / verplichting',
}

interface BalkProps {
  administratieId: string
  administratieNaam: string | null
  /** Aangevinkte rijen (id's). */
  selectie: Set<string>
  /** Selecteerbare rijen die nu zichtbaar zijn (de weergave ná zoekterm/statusfilter). */
  zichtbaar: DocumentListItemDto[]
  onSelecteerZichtbaar: (aan: boolean) => void
  onWissen: () => void
  /** Ná afloop: lijst herladen (rijen zijn verdwenen of veranderd). */
  onAfgerond: () => void
  /** Blok 7 (25-09): administraties van het ouder — dan geen eigen GET /auth/administraties per mount (tabwissel). */
  administraties?: AdministratieDto[] | null
}

export function DocumentenBulkBalk({ administratieId, administratieNaam, selectie, zichtbaar, onSelecteerZichtbaar, onWissen, onAfgerond, administraties: voorgeladen }: BalkProps) {
  const { meld } = useToastOptioneel()
  const { administraties } = useAdministraties(voorgeladen)
  const [actie, setActie] = useState<BulkActie | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const menuKnop = useRef<HTMLButtonElement | null>(null)
  const [reden, setReden] = useState('')
  const [soort, setSoort] = useState<NonNullable<BulkBody['soort']>>('kassarapport')
  const [doel, setDoel] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [resultaat, setResultaat] = useState<DocumentenBulkResponseDto | null>(null)

  const zichtbaarGeselecteerd = zichtbaar.filter((d) => selectie.has(d.id)).length
  const allesZichtbaar = zichtbaar.length > 0 && zichtbaarGeselecteerd === zichtbaar.length
  const aantal = selectie.size
  const gekozen = useMemo(() => zichtbaar.filter((d) => selectie.has(d.id)), [zichtbaar, selectie])
  const doelOpties = useMemo(() => (administraties ?? []).filter((a) => a.id !== administratieId), [administraties, administratieId])

  const open = (a: BulkActie) => {
    setFout(null)
    setReden('')
    setDoel(null)
    setMenuOpen(false)
    setActie(a)
  }

  const geldig =
    actie === 'verwijderen' || actie === 'afwijzen' ? reden.trim().length > 0 : actie === 'verplaatsen' ? Boolean(doel) : actie === 'soort_wijzigen'

  const bevestig = async () => {
    if (!actie || aantal === 0 || !geldig) return
    setBezig(true)
    setFout(null)
    try {
      const body: BulkBody = { document_ids: [...selectie], actie }
      if (actie === 'verwijderen' || actie === 'afwijzen') body.reden = reden.trim()
      if (actie === 'soort_wijzigen') body.soort = soort
      if (actie === 'verplaatsen' && doel) body.doel_administratie_id = doel
      const r = await bulkDocumentActie(administratieId, body)
      setResultaat(r)
      setActie(null)
      meld(
        `${ACTIE_LABEL[actie]}: ${r.gelukt} ${r.gelukt === 1 ? 'document' : 'documenten'} gelukt` +
          (r.overgeslagen > 0 ? `, ${r.overgeslagen} overgeslagen` : '') +
          (r.geen_toegang > 0 ? `, ${r.geen_toegang} zonder toegang` : '') +
          (r.overgeslagen + r.geen_toegang > 0 ? ' — zie de redenen' : ''),
        r.overgeslagen + r.geen_toegang > 0 ? 'warn' : 'ok',
      )
      onWissen()
      onAfgerond()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Bulk-actie mislukt.')
    } finally {
      setBezig(false)
    }
  }

  const doelNaam = doelOpties.find((a) => a.id === doel)?.naam ?? null

  return (
    <>
      <div className="bulk-balk" data-testid="documenten-bulk-balk">
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, margin: 0 }}>
          <Checkbox
            checked={allesZichtbaar}
            indeterminate={zichtbaarGeselecteerd > 0 && !allesZichtbaar}
            disabled={zichtbaar.length === 0}
            aria-label={`Alle ${zichtbaar.length} documenten in deze weergave selecteren`}
            onChange={(e) => onSelecteerZichtbaar(e.target.checked)}
          />
          {aantal === 0
            ? `Selecteer documenten om ze in één keer te verwijderen, af te wijzen, van type te wisselen of te verplaatsen (${zichtbaar.length} in deze weergave)`
            : `${aantal} van ${zichtbaar.length} geselecteerd`}
        </label>
        <div className="spacer" />
        {aantal > 0 && (
          <button type="button" className="linkbtn" onClick={onWissen} disabled={bezig}>
            selectie wissen
          </button>
        )}
        <button type="button" className="btn" disabled={aantal === 0 || bezig} onClick={() => open('verwijderen')} data-testid="bulk-verwijderen">
          Verwijderen…{aantal > 0 ? ` (${aantal})` : ''}
        </button>
        <button
          ref={menuKnop}
          type="button"
          className="btn secondary meer"
          aria-label="Meer bulk-acties"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          disabled={aantal === 0 || bezig}
          title="Type wijzigen, verplaatsen naar een andere administratie, afwijzen"
          onClick={() => setMenuOpen((o) => !o)}
        >
          ⋯
        </button>
        <AnkerPopup
          open={menuOpen}
          anker={menuKnop.current}
          kant="onder"
          uitlijning="eind"
          className="rijmenu"
          role="menu"
          aria-label="Meer bulk-acties"
          onAnkerUitBeeld={() => setMenuOpen(false)}
          data-testid="documenten-bulk-menu"
        >
          <button type="button" className="linkbtn" role="menuitem" onClick={() => open('soort_wijzigen')}>
            ⇄ Type wijzigen…
          </button>
          <button type="button" className="linkbtn" role="menuitem" onClick={() => open('verplaatsen')}>
            ⇥ Verplaatsen naar administratie…
          </button>
          <button type="button" className="linkbtn" role="menuitem" onClick={() => open('afwijzen')}>
            ✕ Afwijzen…
          </button>
        </AnkerPopup>
      </div>
      {fout && !actie && <div className="fout">{fout}</div>}
      {resultaat && (
        <div className="hint bulk-resultaat" role="status" data-testid="documenten-bulk-resultaat" style={{ marginBottom: 12 }}>
          <b>
            {ACTIE_LABEL[resultaat.actie as BulkActie] ?? resultaat.actie}: {resultaat.gelukt} gelukt
            {resultaat.overgeslagen > 0 ? `, ${resultaat.overgeslagen} overgeslagen` : ''}
            {resultaat.geen_toegang > 0 ? `, ${resultaat.geen_toegang} zonder toegang` : ''}.
          </b>{' '}
          {resultaat.actie === 'verwijderen' && resultaat.gelukt > 0 && 'Herstellen kan per document via "Toon afgehandelde documenten".'}
          {resultaat.overgeslagen + resultaat.geen_toegang > 0 && (
            <details style={{ marginTop: 4 }}>
              <summary style={{ cursor: 'pointer' }}>Redenen ({resultaat.overgeslagen + resultaat.geen_toegang})</summary>
              <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                {resultaat.rijen
                  .filter((r) => r.uitkomst !== 'gelukt')
                  .map((r) => (
                    <li key={r.document_id}>
                      <b>{r.bestandsnaam ?? r.document_id}</b>: {r.reden ?? r.uitkomst}
                    </li>
                  ))}
              </ul>
            </details>
          )}{' '}
          <button type="button" className="linkbtn" onClick={() => setResultaat(null)}>
            Sluiten
          </button>
        </div>
      )}
      {actie && (
        <Dialog open onOpenChange={(o) => !o && !bezig && setActie(null)}>
          <DialogContent data-testid="documenten-bulk-dialoog">
            <DialogTitle>
              {ACTIE_LABEL[actie]} — {aantal === 1 ? '1 document' : `${aantal} documenten`}
            </DialogTitle>
            <DialogDescription>
              {actie === 'verwijderen' &&
                'De documenten verdwijnen uit de werkvoorraad (module-status verwijderd) — niets wordt definitief gewist en er wordt niets in Reeleezee of Odoo geraakt; herstellen kan per document. Geboekte en ter accordering liggende documenten worden overgeslagen mét reden.'}
              {actie === 'afwijzen' && 'De documenten gaan naar Afgewezen — ter controle, met deze ene reden; boeken is dan geblokkeerd tot heropenen.'}
              {actie === 'soort_wijzigen' &&
                'De documentsoort wordt gewijzigd en de extractie draait opnieuw via het juiste pad (een kassarapport landt in het omzet-controlescherm). Alleen niet-geboekte documenten; de rest wordt overgeslagen mét reden.'}
              {actie === 'verplaatsen' &&
                `De documenten verhuizen van ${administratieNaam ?? 'deze administratie'} naar de gekozen administratie en de extractie draait daar opnieuw. Alleen niet-geboekte inkoopfacturen; de rest wordt overgeslagen mét reden.`}
            </DialogDescription>
            {gekozen.length > 0 && (
              <p className="hint" style={{ margin: '0 0 8px' }}>
                {gekozen
                  .slice(0, 6)
                  .map((d) => d.leverancier ?? d.bestandsnaam)
                  .join(', ')}
                {gekozen.length > 6 ? ` en ${gekozen.length - 6} andere` : ''}
              </p>
            )}
            {(actie === 'verwijderen' || actie === 'afwijzen') && (
              <label style={{ display: 'block' }}>
                Reden (voor alle {aantal})
                <input
                  value={reden}
                  onChange={(e) => setReden(e.target.value)}
                  autoFocus
                  aria-label="Reden"
                  placeholder={actie === 'verwijderen' ? 'bv. kassarapport, geen inkoopfactuur' : 'bv. verkeerde administratie'}
                  className="w-full"
                />
              </label>
            )}
            {actie === 'soort_wijzigen' && (
              <label style={{ display: 'block' }}>
                Nieuw type
                <Select aria-label="Nieuw documenttype" value={soort} onChange={(e) => setSoort(e.target.value as NonNullable<BulkBody['soort']>)} className="w-full">
                  {(Object.keys(SOORT_LABEL) as NonNullable<BulkBody['soort']>[]).map((s) => (
                    <option key={s} value={s}>
                      {SOORT_LABEL[s]}
                    </option>
                  ))}
                </Select>
              </label>
            )}
            {actie === 'verplaatsen' && (
              <AdministratieCombobox
                label="Doeladministratie"
                administraties={doelOpties}
                waarde={doel}
                onWijzig={setDoel}
                placeholder="Zoek administratie…"
                vereist
              />
            )}
            {fout && <div className="fout">{fout}</div>}
            <DialogFooter>
              <Button type="button" variant="secundair" onClick={() => setActie(null)} disabled={bezig}>
                Annuleren
              </Button>
              <Button type="button" onClick={() => void bevestig()} disabled={bezig || !geldig} data-testid="documenten-bulk-bevestig">
                {bezig ? 'Bezig…' : `${ACTIE_LABEL[actie]}${actie === 'verplaatsen' && doelNaam ? ` naar ${doelNaam}` : ''} (${aantal})`}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </>
  )
}
