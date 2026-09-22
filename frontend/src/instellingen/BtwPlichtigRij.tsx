import { useCallback, useEffect, useState } from 'react'
import { ApiError, apiJson } from '../api/client'
import { Switch } from '../ui/basis'
import { InstellingRij } from './AdministratieDetailPagina'

/** Btw-plichtig per administratie (BUG Peter 22-09, casus Vastgoedgroep Nederland / Studio Lacy Lion 2026-042 →
 * RLZ-04-00000925: de module splitste bruto/btw, Reeleezee boekte in de niet-btw-plichtige administratie alleen het netto →
 * € 322,38 te weinig betaald; migratie 0170). Eén instellingenrij op de tab "Boeken & AI" (anker `btw-plichtig`,
 * registry-entry): schakelaar aan/uit (Beheerder-only, PUT `/administraties/{id}/btw-plichtig`, audit oud→nieuw, bron
 * 'mens'), herkomst-chip (bevestigd door Reeleezee | door u | nog nooit bevestigd), het RLZ-signaal EnableTaxReporting en
 * — bij uit — de "geen btw"-code die de prefill kiest. Kandidaat "niet btw-plichtig" (detector) = oranje regel mét
 * handeling: bevestig de stand. Zelfstandig patroon zoals BtwDefaultRij (eigen fetch, geen PendingToggle-dialoog). */

export interface BtwPlichtigDto {
  administratie_id: string
  btw_plichtig: boolean
  bron: 'rlz' | 'mens' | null
  gewijzigd_op: string | null
  rlz_signaal: boolean | null
  rlz_gezien_op: string | null
  geen_btw_taxrate_id: string | null
  geen_btw_taxrate_naam: string | null
  kandidaat: boolean
  kandidaat_reden: 'rlz_signaal' | 'geen_tarief_met_percentage' | null
}

export function haalBtwPlichtig(administratieId: string): Promise<BtwPlichtigDto> {
  return apiJson<BtwPlichtigDto>(`/administraties/${administratieId}/btw-plichtig`)
}

export function zetBtwPlichtig(administratieId: string, btwPlichtig: boolean): Promise<BtwPlichtigDto> {
  return apiJson<BtwPlichtigDto>(`/administraties/${administratieId}/btw-plichtig`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ btw_plichtig: btwPlichtig }),
  })
}

export function herkomstTekst(stand: BtwPlichtigDto): string {
  if (stand.bron === 'mens') return 'bevestigd door het kantoor'
  if (stand.bron === 'rlz') return 'bevestigd uit Reeleezee (EnableTaxReporting)'
  return 'nog nooit bevestigd (aanname: btw-plichtig)'
}

export function kandidaatTekst(stand: BtwPlichtigDto): string | null {
  if (!stand.kandidaat) return null
  const reden =
    stand.kandidaat_reden === 'rlz_signaal'
      ? 'Reeleezee zegt dat deze administratie geen btw-aangifte doet (EnableTaxReporting uit)'
      : 'de gesyncte btw-codes kennen geen enkel tarief boven 0 %'
  return `Kandidaat “niet btw-plichtig”: ${reden}. Zolang de schakelaar aan staat splitst de module btw en boekt Reeleezee alleen het netto op de crediteurpost — bevestig de stand (aan of uit).`
}

export function BtwPlichtigRij({ administratieId, naam, uitgeschakeld = false }: { administratieId: string; naam: string; uitgeschakeld?: boolean }) {
  const [stand, setStand] = useState<BtwPlichtigDto | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [opgeslagen, setOpgeslagen] = useState(false)

  const laad = useCallback(async () => {
    setLaadFout(null)
    try {
      setStand(await haalBtwPlichtig(administratieId))
    } catch (err) {
      setStand(null)
      setLaadFout(err instanceof ApiError ? err.message : 'Instelling niet beschikbaar.')
    }
  }, [administratieId])

  useEffect(() => {
    void laad()
  }, [laad])

  const wijzig = async (nieuw: boolean) => {
    if (!stand) return
    setBezig(true)
    setFout(null)
    setOpgeslagen(false)
    try {
      setStand(await zetBtwPlichtig(administratieId, nieuw))
      setOpgeslagen(true)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Opslaan mislukt — probeer het opnieuw.')
    } finally {
      setBezig(false)
    }
  }

  const kandidaat = stand ? kandidaatTekst(stand) : null

  return (
    <div id="btw-plichtig" data-testid="btw-plichtig-rij">
      <InstellingRij
        titel="Btw-plichtig"
        uitleg={
          <>
            Uit = btw bestaat niet in deze administratie: elke boekingsregel gaat op het factuurbedrag incl. btw (btw in de kosten) met de
            btw-code “geen btw”, en de harde check “Btw in niet-btw-plichtige administratie” blokkeert elke regel mét btw. Reeleezee boekt in
            zo’n administratie anders alleen het netto op de crediteurpost — de leverancier krijgt dan te weinig (casus Studio Lacy Lion).
            Geldt voor inkoop, verkoop, kassarapporten en doorbelasting-spiegels naar deze administratie.
          </>
        }
      >
        {stand === null && !laadFout ? (
          <span className="hint" style={{ margin: 0 }}>
            laden…
          </span>
        ) : laadFout ? (
          <span className="chip blokkerend" role="alert">
            {laadFout}
          </span>
        ) : stand ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'flex-end' }}>
            <label className="inst-switch-label">
              <Switch
                aria-label={`Btw-plichtig voor ${naam}`}
                checked={stand.btw_plichtig}
                disabled={uitgeschakeld || bezig}
                onChange={(e) => void wijzig(e.target.checked)}
              />
              {stand.btw_plichtig ? 'aan' : 'uit — btw in de kosten'}
            </label>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
              <span className={`chip ${stand.bron ? 'ok' : 'stil'}`} data-testid="btw-plichtig-herkomst">
                {herkomstTekst(stand)}
              </span>
              {stand.rlz_signaal !== null && (
                <span className="chip stil" data-testid="btw-plichtig-rlz-signaal" title="Reeleezee › AdministrationSettings › EnableTaxReporting, gelezen bij de nachtelijke sync.">
                  Reeleezee: btw-aangifte {stand.rlz_signaal ? 'aan' : 'uit'}
                </span>
              )}
              {!stand.btw_plichtig && (
                <span className="chip stil" data-testid="btw-plichtig-geen-btw-code">
                  geen-btw-code: {stand.geen_btw_taxrate_naam ?? 'geen — boekt zonder btw-code'}
                </span>
              )}
            </div>
            {kandidaat && stand.btw_plichtig && (
              <div className="chip afwijking" data-testid="btw-plichtig-kandidaat" style={{ maxWidth: 520, whiteSpace: 'normal', textAlign: 'right' }}>
                {kandidaat}{' '}
                <button type="button" className="linkbtn" disabled={uitgeschakeld || bezig} onClick={() => void wijzig(true)}>
                  Blijft btw-plichtig
                </button>{' '}
                ·{' '}
                <button type="button" className="linkbtn" disabled={uitgeschakeld || bezig} onClick={() => void wijzig(false)}>
                  Niet btw-plichtig
                </button>
              </div>
            )}
            {fout && (
              <span className="chip blokkerend" role="alert">
                {fout}
              </span>
            )}
            {opgeslagen && !fout && (
              <span className="hint" style={{ margin: 0 }}>
                opgeslagen
              </span>
            )}
          </div>
        ) : null}
      </InstellingRij>
    </div>
  )
}
