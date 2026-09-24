import { useCallback, useEffect, useState } from 'react'
import { ApiError, apiJson } from '../api/client'
import { formatBedrag } from '../werkvoorraad/format'

/** BUA-jaarrapport (besluit Peter 24-09 "nee standaard 21 % btw aanhouden … liever een correctie indienen"): lees-only blok
 * op de tab "Boeken & AI" ná "Btw niet aftrekbaar" (anker `bua-jaarrapport`, registry-entry). Er wordt géén kenmerk in bulk
 * gezet: de btw op representatie-/relatiegeschenk-/personeelsrekeningen (BUA) wordt het jaar door gewoon afgetrokken en dit
 * blok toont per rekening wat er in het gekozen jaar aan btw is afgetrokken (module-boekingen + bank) mét het voorstel voor
 * de correctie in de laatste aangifte. Kantine en sponsoring staan apart en tellen niet in het voorstel. De € 227-drempel per
 * begunstigde is niet uit de boekhouding te halen: de accountant toetst, de module past niets toe. Vanaf 1 december komt per
 * administratie mét BUA-btw een rij "BUA-correctie nog te beoordelen" in Inzicht › Reconciliatie mét "Rapport openen" → hier. */

export interface BuaJaarRekeningDto {
  ledger_id: string
  code: string
  naam: string
  categorie: string
  kenmerk: boolean
  mod_n: number
  mod_netto: string
  mod_btw: string
  bank_n: number
  bank_netto: string
  bank_btw: string
  rlz_n: number | null
  rlz_netto: string | null
  rlz_btw: string | null
  btw_totaal: string
  documenten: number
}

export interface BuaJaarrapportDto {
  jaar: number
  administratie_id: string
  administratie: string
  rlz_kant: string
  bua_btw: string
  correctie_voorstel: string
  kantine_btw: string
  sponsoring_btw: string
  rekeningen: BuaJaarRekeningDto[]
  let_op: string
}

export function haalBuaJaarrapport(administratieId: string, jaar: number): Promise<BuaJaarrapportDto> {
  return apiJson<BuaJaarrapportDto>(`/administraties/${administratieId}/bua-jaarrapport?jaar=${jaar}`)
}

function jaarOpties(): number[] {
  const nu = new Date().getFullYear()
  return [nu, nu - 1, nu - 2]
}

export function BuaJaarrapportBlok({ administratieId, naam }: { administratieId: string; naam: string }) {
  const [jaar, setJaar] = useState<number>(() => new Date().getFullYear())
  const [stand, setStand] = useState<BuaJaarrapportDto | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [laden, setLaden] = useState(false)

  const laad = useCallback(async () => {
    setLaadFout(null)
    setLaden(true)
    try {
      setStand(await haalBuaJaarrapport(administratieId, jaar))
    } catch (err) {
      setStand(null)
      setLaadFout(err instanceof ApiError ? err.message : 'Jaarrapport niet beschikbaar.')
    } finally {
      setLaden(false)
    }
  }, [administratieId, jaar])

  useEffect(() => {
    void laad()
  }, [laad])

  const metBtw = stand?.rekeningen.filter((r) => r.btw_totaal !== '0.00') ?? []

  return (
    <div className="panel" id="bua-jaarrapport" data-testid="bua-jaarrapport-blok" style={{ padding: 12, marginTop: 12 }}>
      <h2 style={{ marginTop: 0 }}>BUA-jaarrapport — btw afgetrokken op representatie, relatiegeschenken, personeel</h2>
      <p className="hint" style={{ marginTop: 0 }}>
        Standaard blijft de btw op deze rekeningen het jaar door gewoon aftrekbaar (besluit 24 september 2026); de BUA-correctie
        hoort in de laatste btw-aangifte van het jaar. Dit overzicht toont per rekening wat er in {jaar} aan btw is afgetrokken
        (geboekte inkoopfacturen + bankboekingen in de module) en het voorstel voor die correctie. Kantine en sponsoring staan
        apart en tellen niet mee.
      </p>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 }}>
        <label htmlFor={`bua-jaar-${administratieId}`} className="hint" style={{ margin: 0 }}>
          Boekjaar
        </label>
        <select id={`bua-jaar-${administratieId}`} aria-label={`Boekjaar BUA-jaarrapport ${naam}`} value={jaar} onChange={(e) => setJaar(Number(e.target.value))} style={{ maxWidth: 120 }}>
          {jaarOpties().map((j) => (
            <option key={j} value={j}>
              {j}
            </option>
          ))}
        </select>
        {stand && (
          <span className="chip afwijking" data-testid="bua-jaarrapport-voorstel">
            correctie laatste aangifte (voorstel): {formatBedrag(stand.correctie_voorstel)}
          </span>
        )}
        {laden && <span className="hint">laden…</span>}
      </div>
      {laadFout && (
        <div className="fout" role="alert">
          {laadFout}
        </div>
      )}
      {stand && (
        <>
          <div className="tabel-scroll" style={{ maxHeight: 320 }}>
            <table className="lines">
              <thead>
                <tr>
                  <th>Code</th>
                  <th>Rekening</th>
                  <th>Categorie</th>
                  <th style={{ textAlign: 'right' }}>Documenten</th>
                  <th style={{ textAlign: 'right' }}>Netto</th>
                  <th style={{ textAlign: 'right' }}>Btw afgetrokken</th>
                </tr>
              </thead>
              <tbody>
                {metBtw.map((r) => (
                  <tr key={r.ledger_id}>
                    <td style={{ whiteSpace: 'nowrap' }}>
                      <b>{r.code}</b>
                    </td>
                    <td>{r.naam}</td>
                    <td>
                      <span className={`chip ${r.categorie === 'BUA' ? 'afwijking' : 'stil'}`}>{r.categorie}</span>
                      {r.kenmerk && <span className="hint"> kenmerk “btw niet aftrekbaar” staat aan</span>}
                    </td>
                    <td style={{ textAlign: 'right' }}>{r.documenten}</td>
                    <td style={{ textAlign: 'right' }}>{formatBedrag((Number(r.mod_netto) + Number(r.bank_netto)).toFixed(2))}</td>
                    <td style={{ textAlign: 'right' }}>{formatBedrag(r.btw_totaal)}</td>
                  </tr>
                ))}
                {metBtw.length === 0 && (
                  <tr>
                    <td colSpan={6} className="hint">
                      In {jaar} is op de BUA-rekeningen van {naam} geen btw afgetrokken (module-boekingen en bank). Geen correctie te beoordelen.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <p className="hint" style={{ marginBottom: 4 }} data-testid="bua-jaarrapport-sommen">
            BUA-btw {formatBedrag(stand.bua_btw)} · kantine {formatBedrag(stand.kantine_btw)} (apart) · sponsoring {formatBedrag(stand.sponsoring_btw)} (apart) ·
            Reeleezee-kant: {stand.rlz_kant}
          </p>
          <p className="hint" role="note" style={{ margin: 0 }}>
            {stand.let_op}
          </p>
        </>
      )}
    </div>
  )
}
