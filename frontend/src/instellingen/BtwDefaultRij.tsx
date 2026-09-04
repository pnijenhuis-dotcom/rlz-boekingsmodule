import { useCallback, useEffect, useState } from 'react'
import { ApiError, apiJson } from '../api/client'
import { Select } from '../ui/basis'
import { InstellingRij } from './AdministratieDetailPagina'

/** Btw-default per administratie (blok E medewerker-wensen 04-09, mockup
 * projectverdeling-en-regelvoorstellen.html blok 3, notitie ⑧): één instellingenrij op de tab "Boeken & AI"
 * van de administratie-detailpagina — select uit de gesyncte btw-codes (leeg = uit), Beheerder-only
 * (backend `require_beheerder` + audit oud→nieuw). Eigen fetch (GET/PUT `/administraties/{id}/btw-default`)
 * zodat de rij geen extra veld op de administratie-lijst nodig heeft. Vult in de prefill alleen regels waar
 * factuur en leverancier-geheugen niets opleveren (chip "standaard administratie" op het controlescherm). */

export interface BtwOptieDto {
  id: string
  naam: string | null
  percentage: string | number | null
}

export interface BtwDefaultDto {
  taxrate_id: string | null
  taxrate_naam: string | null
  opties: BtwOptieDto[]
}

export function haalBtwDefault(administratieId: string): Promise<BtwDefaultDto> {
  return apiJson<BtwDefaultDto>(`/administraties/${administratieId}/btw-default`)
}

export function zetBtwDefault(administratieId: string, taxrateId: string | null): Promise<BtwDefaultDto> {
  return apiJson<BtwDefaultDto>(`/administraties/${administratieId}/btw-default`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ taxrate_id: taxrateId }),
  })
}

/** Optietekst zoals de btw-combobox op het controlescherm: "21% · NL, Hoog Tarief". */
export function optieTekst(o: BtwOptieDto): string {
  const pct = o.percentage === null || o.percentage === undefined ? null : Math.round(Number(o.percentage) * 100)
  const naam = o.naam ?? o.id
  return pct === null || Number.isNaN(pct) ? naam : `${pct}% · ${naam}`
}

function foutTekst(err: unknown): string {
  if (err instanceof ApiError) return err.message
  return 'Opslaan mislukt — probeer het opnieuw.'
}

export function BtwDefaultRij({ administratieId, naam, uitgeschakeld = false }: { administratieId: string; naam: string; uitgeschakeld?: boolean }) {
  const [stand, setStand] = useState<BtwDefaultDto | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [opgeslagen, setOpgeslagen] = useState(false)

  const laad = useCallback(async () => {
    setLaadFout(null)
    try {
      setStand(await haalBtwDefault(administratieId))
    } catch (err) {
      setStand(null)
      setLaadFout(err instanceof ApiError ? err.message : 'Instelling niet beschikbaar.')
    }
  }, [administratieId])

  useEffect(() => {
    void laad()
  }, [laad])

  const wijzig = async (waarde: string) => {
    if (!stand) return
    const nieuw = waarde === '' ? null : waarde
    if (nieuw === stand.taxrate_id) return
    setBezig(true)
    setFout(null)
    setOpgeslagen(false)
    try {
      setStand(await zetBtwDefault(administratieId, nieuw))
      setOpgeslagen(true)
    } catch (err) {
      setFout(foutTekst(err))
    } finally {
      setBezig(false)
    }
  }

  const verdwenen = stand?.taxrate_id && !stand.opties.some((o) => o.id === stand.taxrate_id)

  return (
    <InstellingRij
      titel="Standaard btw-voorstel"
      uitleg="Vult alleen regels waar factuur en leverancier-geheugen niets opleveren (chip “standaard administratie”); de harde checks blijven de poort. Leeg = uit."
    >
      {laadFout ? (
        <span className="text-[12px] text-orange" role="alert">
          {laadFout}
        </span>
      ) : (
        <label className="inst-switch-label">
          <Select
            aria-label={`Standaard btw-voorstel voor ${naam}`}
            value={stand?.taxrate_id ?? ''}
            disabled={!stand || bezig || uitgeschakeld}
            onChange={(e) => void wijzig(e.target.value)}
            style={{ maxWidth: 260 }}
          >
            <option value="">uit — geen standaard</option>
            {verdwenen && stand?.taxrate_id && (
              <option value={stand.taxrate_id}>(niet meer in de gesyncte lijst)</option>
            )}
            {stand?.opties.map((o) => (
              <option key={o.id} value={o.id}>
                {optieTekst(o)}
              </option>
            ))}
          </Select>
          {opgeslagen && !fout && <span className="text-[12px] text-ok">opgeslagen</span>}
          {fout && (
            <span className="text-[12px] text-red" role="alert">
              {fout}
            </span>
          )}
        </label>
      )}
    </InstellingRij>
  )
}
