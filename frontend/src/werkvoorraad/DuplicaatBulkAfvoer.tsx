import { useState } from 'react'
import { ApiError, apiPostJson } from '../api/client'
import type { DocumentListItemDto, DuplicaatBulkAfvoerResponseDto } from '../api/types'
import { DUPLICAAT_AFVOERBARE_STATUSSEN } from '../document/DuplicaatAfvoer'
import { Button, Checkbox, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle, useToastOptioneel } from '../ui/basis'
import { isMogelijkDuplicaat } from './lijstContext'

/** Bulk-afvoer op de Mogelijk-duplicaat-tab (B2 07-09, opdracht Peter): checkbox-kolom + selecteer-alles (zichtbare
 * rijen én — GMail-patroon — "alle N op deze tab", server-side geselecteerd) + één primaire knop "Afvoeren als
 * duplicaat (n)" over de BESTAANDE per-document-route (zelfde harde match, kruisverwijzing, heropenen-terugweg,
 * audit). Expliciete mensactie mét bevestigingsdialoog; valt buiten de 20/dag-automatiseringsrem. Niet-afvoerbare
 * rijen worden overgeslagen mét reden — nooit stil; de uitkomst per rij staat na afloop uitklapbaar in het paneel. */

/** Welke rij op de tab is überhaupt afvoerbaar (spiegel van de server-side "alle"-selectie): inkoopfactuur, een
 * afvoerbare status én het duplicaat-signaal dat de tab definieert. Andere rijen krijgen een uitgeschakelde
 * checkbox mét uitleg. */
export function isDuplicaatBulkSelecteerbaar(d: DocumentListItemDto): boolean {
  return d.soort === 'inkoopfactuur' && DUPLICAAT_AFVOERBARE_STATUSSEN.includes(d.status) && isMogelijkDuplicaat(d)
}

/** Uitleg bij een uitgeschakelde checkbox — waarom deze rij niet mee kan. */
export function redenNietSelecteerbaar(d: DocumentListItemDto): string {
  if (d.soort !== 'inkoopfactuur') return 'Alleen inkoopfacturen kunnen als duplicaat afgevoerd worden'
  if (!DUPLICAAT_AFVOERBARE_STATUSSEN.includes(d.status)) {
    return `Vanuit status "${d.status.replace(/_/g, ' ')}" kan een document niet als duplicaat afgevoerd worden`
  }
  return 'Geen duplicaat-signaal op dit document'
}

export type DuplicaatBulkBody = { document_ids: string[] } | { alle: true }

export function bulkAfvoerenAlsDuplicaat(administratieId: string, body: DuplicaatBulkBody): Promise<DuplicaatBulkAfvoerResponseDto> {
  return apiPostJson(`/administraties/${administratieId}/documenten/duplicaten/afvoeren-bulk`, body)
}

interface BalkProps {
  administratieId: string
  /** Expliciet aangevinkte rijen (id's). */
  selectie: Set<string>
  /** "Alle N op deze tab" gekozen: de server selecteert zelf, de checkboxes staan op slot. */
  alleModus: boolean
  /** Selecteerbare rijen die nu zichtbaar zijn (na zoekterm/sortering). */
  zichtbaarSelecteerbaar: DocumentListItemDto[]
  /** Alle selecteerbare rijen op de tab, óók de door de zoekterm verborgen. */
  totaalOpTab: number
  onSelecteerZichtbaar: (aan: boolean) => void
  onAlleModus: (aan: boolean) => void
  onWissen: () => void
  /** Ná een geslaagde bulk-run: lijst herladen (de afgevoerde rijen verdwijnen van de tab). */
  onAfgerond: () => void
}

/** De bulk-balk boven de lijst: kop-checkbox (zichtbare rijen), tekst mét tellers, "alle N"-banner, de knop, de
 * bevestigingsdialoog en het uitkomst-paneel. Teal `btn` = actie; overgeslagen redenen uitklapbaar. */
export function DuplicaatBulkBalk({
  administratieId,
  selectie,
  alleModus,
  zichtbaarSelecteerbaar,
  totaalOpTab,
  onSelecteerZichtbaar,
  onAlleModus,
  onWissen,
  onAfgerond,
}: BalkProps) {
  const { meld } = useToastOptioneel()
  const [dialoogOpen, setDialoogOpen] = useState(false)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [resultaat, setResultaat] = useState<DuplicaatBulkAfvoerResponseDto | null>(null)

  const zichtbaarGeselecteerd = zichtbaarSelecteerbaar.filter((d) => selectie.has(d.id)).length
  const allesZichtbaar = zichtbaarSelecteerbaar.length > 0 && zichtbaarGeselecteerd === zichtbaarSelecteerbaar.length
  const aantal = alleModus ? totaalOpTab : selectie.size
  const meerOpTab = totaalOpTab > zichtbaarSelecteerbaar.length

  const bevestig = async () => {
    if (aantal === 0) return
    setBezig(true)
    setFout(null)
    try {
      const r = await bulkAfvoerenAlsDuplicaat(administratieId, alleModus ? { alle: true } : { document_ids: [...selectie] })
      setResultaat(r)
      setDialoogOpen(false)
      meld(
        `${r.afgevoerd} ${r.afgevoerd === 1 ? 'document' : 'documenten'} afgevoerd als duplicaat` +
          (r.al_afgevoerd > 0 ? `, ${r.al_afgevoerd} al eerder afgevoerd` : '') +
          (r.overgeslagen > 0 ? ` — ${r.overgeslagen} overgeslagen, zie de redenen` : ''),
        r.overgeslagen > 0 ? 'warn' : 'ok',
      )
      onWissen()
      onAfgerond()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Bulk afvoeren mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <>
      <div className="bulk-balk" data-testid="duplicaat-bulk-balk">
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, margin: 0 }}>
          <Checkbox
            checked={alleModus || allesZichtbaar}
            indeterminate={!alleModus && zichtbaarGeselecteerd > 0 && !allesZichtbaar}
            disabled={zichtbaarSelecteerbaar.length === 0 && !alleModus}
            aria-label="Alle zichtbare duplicaten selecteren"
            onChange={(e) => {
              if (alleModus) {
                onAlleModus(false)
                onWissen()
                return
              }
              onSelecteerZichtbaar(e.target.checked)
            }}
          />
          {alleModus
            ? `Alle ${totaalOpTab} afvoerbare documenten op deze tab geselecteerd`
            : selectie.size === 0
              ? `Selecteer documenten om ze in één keer als duplicaat af te voeren (${zichtbaarSelecteerbaar.length} afvoerbaar${meerOpTab ? ` zichtbaar, ${totaalOpTab} op deze tab` : ''})`
              : `${selectie.size} van ${zichtbaarSelecteerbaar.length} geselecteerd`}
        </label>
        <div className="spacer" />
        {aantal > 0 && !alleModus && (
          <button type="button" className="linkbtn" onClick={onWissen} disabled={bezig}>
            selectie wissen
          </button>
        )}
        <button
          type="button"
          className="btn"
          disabled={aantal === 0 || bezig}
          onClick={() => {
            setFout(null)
            setDialoogOpen(true)
          }}
          title="Zelfde route als het rijmenu-item, per document: harde match, kruisverwijzing naar het origineel, terughalen via Heropenen — wat niet kan, wordt overgeslagen mét reden"
        >
          {bezig ? 'Afvoeren…' : `Afvoeren als duplicaat${aantal > 0 ? ` (${aantal})` : ''}`}
        </button>
        {!alleModus && allesZichtbaar && meerOpTab && (
          <div className="hint" data-testid="duplicaat-bulk-alle-banner" style={{ flexBasis: '100%', margin: 0 }}>
            Alle {zichtbaarSelecteerbaar.length} zichtbare rijen zijn geselecteerd.{' '}
            <button type="button" className="linkbtn" onClick={() => onAlleModus(true)}>
              Alle {totaalOpTab} afvoerbare documenten op deze tab selecteren
            </button>
          </div>
        )}
        {alleModus && (
          <div className="hint" data-testid="duplicaat-bulk-alle-banner" style={{ flexBasis: '100%', margin: 0 }}>
            De selectie wordt door de server bepaald (ook wat door de zoekterm verborgen is).{' '}
            <button
              type="button"
              className="linkbtn"
              onClick={() => {
                onAlleModus(false)
                onWissen()
              }}
            >
              Selectie wissen
            </button>
          </div>
        )}
      </div>
      {fout && !dialoogOpen && <div className="fout">{fout}</div>}
      {resultaat && (
        <div className="hint bulk-resultaat" role="status" data-testid="duplicaat-bulk-resultaat" style={{ marginBottom: 12 }}>
          <b>
            {resultaat.afgevoerd} afgevoerd als duplicaat
            {resultaat.al_afgevoerd > 0 ? `, ${resultaat.al_afgevoerd} al eerder afgevoerd` : ''}
            {resultaat.overgeslagen > 0 ? `, ${resultaat.overgeslagen} overgeslagen` : ''}.
          </b>{' '}
          {resultaat.afgevoerd > 0 && 'Terughalen kan per document via Heropenen; de kruisverwijzing naar het origineel blijft staan.'}
          {resultaat.overgeslagen > 0 && (
            <details style={{ marginTop: 4 }}>
              <summary style={{ cursor: 'pointer' }}>
                Redenen ({resultaat.overgeslagen} overgeslagen)
              </summary>
              <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                {resultaat.resultaten
                  .filter((r) => r.uitkomst === 'overgeslagen')
                  .map((r) => (
                    <li key={r.document_id}>
                      <b>{r.bestandsnaam ?? r.document_id}</b>: {r.reden ?? 'geweigerd'}
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
      {dialoogOpen && (
        <Dialog open onOpenChange={(open) => !open && !bezig && setDialoogOpen(false)}>
          <DialogContent aria-describedby={undefined} data-testid="duplicaat-bulk-dialoog">
            <DialogTitle>Afvoeren als duplicaat — {aantal === 1 ? '1 document' : `${aantal} documenten`}</DialogTitle>
            <DialogDescription>
              {alleModus
                ? `Alle ${totaalOpTab} afvoerbare documenten op de tab "Mogelijk duplicaat" gaan`
                : `${aantal === 1 ? 'Het geselecteerde document gaat' : `De ${aantal} geselecteerde documenten gaan`}`}{' '}
              naar <b>Afgewezen</b> met de reden &ldquo;Duplicaat van …&rdquo; en een kruisverwijzing naar het gevonden
              origineel — per document dezelfde controle als het rijmenu-item (crediteur, referentie én totaalbedrag gelijk
              aan een geboekte of oudere factuur).
            </DialogDescription>
            <ul className="hint" style={{ margin: '0 0 8px', paddingLeft: 18 }}>
              <li>Wat niet kan (status laat het niet toe, geen harde match, zelf het origineel) wordt overgeslagen mét reden.</li>
              <li>Er wordt niets verwijderd — terughalen kan per document via Heropenen.</li>
              <li>Dit is jouw handeling: ze telt niet mee in de dagelijkse rem op automatische afvoer.</li>
            </ul>
            {fout && <div className="fout">{fout}</div>}
            <DialogFooter>
              <Button type="button" variant="secundair" onClick={() => setDialoogOpen(false)} disabled={bezig}>
                Annuleren
              </Button>
              <Button type="button" onClick={() => void bevestig()} disabled={bezig || aantal === 0}>
                {bezig ? 'Bezig…' : `Afvoeren als duplicaat (${aantal})`}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </>
  )
}
