import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError, apiJson } from '../api/client'
import { Checkbox } from '../ui/basis'

/** Btw niet aftrekbaar per grootboekrekening (BUA — opdracht Peter 18-09, casus Rituals 88-186308; migratie 0163):
 * blok op de tab "Boeken & AI" van de administratie-detailpagina (anker `btw-aftrek`, registry-entry). Lijst van de
 * kostenrekeningen mét vinkje "btw niet aftrekbaar"; de server levert een deterministisch VOORSTEL (4xxx-kostenrekening,
 * naam representatie, relatiegeschenk, personeelsvoorziening of kantine; RLZ-default 0 %/geen) als chip "voorstel" — de
 * Beheerder bevestigt met "Voorstel overnemen (N)" of per vinkje; niets wordt stil aangezet. Opslaan = de exacte set
 * (PUT), audit oud→nieuw server-side. Gevolg op het controlescherm: op zo'n rekening zet de prefill 0 %/geen btw en
 * de factuur-btw in de kosten (chip "aftrek uitgesloten (4510)"); de harde check "Btw-bedrag past bij tarief" blijft
 * de poort. */

export interface BtwAftrekRekeningDto {
  ledger_id: string
  code: string
  naam: string
  uitgesloten: boolean
  voorstel: boolean
  standaard_percentage: string | number | null
  standaard_naam: string | null
  gezet_op: string | null
}

export interface BtwAftrekDto {
  rekeningen: BtwAftrekRekeningDto[]
  aantal_uitgesloten: number
  aantal_voorstel: number
}

export function haalBtwAftrek(administratieId: string): Promise<BtwAftrekDto> {
  return apiJson<BtwAftrekDto>(`/administraties/${administratieId}/btw-aftrek-uitgesloten`)
}

export function zetBtwAftrek(administratieId: string, ledgerIds: string[]): Promise<BtwAftrekDto> {
  return apiJson<BtwAftrekDto>(`/administraties/${administratieId}/btw-aftrek-uitgesloten`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ledger_ids: ledgerIds }),
  })
}

export function BtwAftrekUitgeslotenBlok({ administratieId, naam, uitgeschakeld = false }: { administratieId: string; naam: string; uitgeschakeld?: boolean }) {
  const [stand, setStand] = useState<BtwAftrekDto | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [keuze, setKeuze] = useState<Set<string>>(new Set())
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [opgeslagen, setOpgeslagen] = useState(false)
  const [alles, setAlles] = useState(false)
  const [zoek, setZoek] = useState('')

  const laad = useCallback(async () => {
    setLaadFout(null)
    try {
      const data = await haalBtwAftrek(administratieId)
      setStand(data)
      setKeuze(new Set(data.rekeningen.filter((r) => r.uitgesloten).map((r) => r.ledger_id)))
    } catch (err) {
      setStand(null)
      setLaadFout(err instanceof ApiError ? err.message : 'Instelling niet beschikbaar.')
    }
  }, [administratieId])

  useEffect(() => {
    void laad()
  }, [laad])

  const opgeslagenSet = useMemo(() => new Set(stand?.rekeningen.filter((r) => r.uitgesloten).map((r) => r.ledger_id) ?? []), [stand])
  const gewijzigd = useMemo(() => {
    if (keuze.size !== opgeslagenSet.size) return true
    for (const id of keuze) if (!opgeslagenSet.has(id)) return true
    return false
  }, [keuze, opgeslagenSet])

  const voorstellen = useMemo(() => stand?.rekeningen.filter((r) => r.voorstel && !keuze.has(r.ledger_id)) ?? [], [stand, keuze])
  const zichtbaar = useMemo(() => {
    const rijen = stand?.rekeningen ?? []
    const term = zoek.trim().toLowerCase()
    const basis = alles ? rijen : rijen.filter((r) => r.voorstel || r.uitgesloten || keuze.has(r.ledger_id))
    return term ? rijen.filter((r) => r.code.includes(term) || r.naam.toLowerCase().includes(term)) : basis
  }, [stand, alles, zoek, keuze])

  const wissel = (id: string, aan: boolean) => {
    setOpgeslagen(false)
    setKeuze((k) => {
      const n = new Set(k)
      if (aan) n.add(id)
      else n.delete(id)
      return n
    })
  }

  const opslaan = async () => {
    setBezig(true)
    setFout(null)
    setOpgeslagen(false)
    try {
      const data = await zetBtwAftrek(administratieId, [...keuze])
      setStand(data)
      setKeuze(new Set(data.rekeningen.filter((r) => r.uitgesloten).map((r) => r.ledger_id)))
      setOpgeslagen(true)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Opslaan mislukt — probeer het opnieuw.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <div className="panel" id="btw-aftrek" data-testid="btw-aftrek-blok" style={{ padding: 12 }}>
      <h2 style={{ marginTop: 0 }}>Btw niet aftrekbaar (representatie, relatiegeschenken)</h2>
      <p className="hint" style={{ marginTop: 0 }}>
        Op een aangevinkte grootboekrekening zet het controlescherm de btw-code op 0 % en gaat de btw van de factuur in de kosten
        (netto = factuurbedrag incl. btw). Voorstel = 4xxx-kostenrekening met representatie / relatiegeschenk / personeelsvoorziening /
        kantine in de naam en geen btw-standaard in Reeleezee — u bevestigt, er wordt niets automatisch aangezet.
      </p>
      {laadFout && (
        <div className="fout" role="alert">
          {laadFout}
        </div>
      )}
      {stand && (
        <>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 }}>
            <span className="chip ok" data-testid="btw-aftrek-teller">
              {keuze.size} niet aftrekbaar
            </span>
            {voorstellen.length > 0 && (
              <button
                type="button"
                className="btn secondary"
                disabled={uitgeschakeld || bezig}
                onClick={() => {
                  setOpgeslagen(false)
                  setKeuze((k) => new Set([...k, ...voorstellen.map((r) => r.ledger_id)]))
                }}
              >
                Voorstel overnemen ({voorstellen.length})
              </button>
            )}
            <input
              aria-label={`Zoek grootboekrekening voor ${naam}`}
              placeholder="Zoek code of naam…"
              value={zoek}
              onChange={(e) => setZoek(e.target.value)}
              style={{ maxWidth: 220 }}
            />
            <button type="button" className="linkbtn" onClick={() => setAlles((v) => !v)}>
              {alles ? 'Alleen voorstel en aangevinkt' : `Alle kostenrekeningen (${stand.rekeningen.length})`}
            </button>
          </div>
          <div className="tabel-scroll" style={{ maxHeight: 320 }}>
            <table className="lines">
              <tbody>
                {zichtbaar.map((r) => (
                  <tr key={r.ledger_id}>
                    <td style={{ width: 32 }}>
                      <Checkbox
                        aria-label={`${r.code} ${r.naam} btw niet aftrekbaar`}
                        checked={keuze.has(r.ledger_id)}
                        disabled={uitgeschakeld || bezig}
                        onChange={(e) => wissel(r.ledger_id, e.target.checked)}
                      />
                    </td>
                    <td style={{ whiteSpace: 'nowrap' }}>
                      <b>{r.code}</b>
                    </td>
                    <td>{r.naam}</td>
                    <td>
                      {r.voorstel && !keuze.has(r.ledger_id) && (
                        <span className="chip afwijking" title="Deterministisch voorstel: naam + geen btw-standaard in Reeleezee — u bevestigt.">
                          voorstel
                        </span>
                      )}
                      {r.standaard_naam && <span className="hint"> standaard: {r.standaard_naam}</span>}
                    </td>
                  </tr>
                ))}
                {zichtbaar.length === 0 && (
                  <tr>
                    <td colSpan={4} className="hint">
                      {zoek.trim() ? `Geen rekening met '${zoek.trim()}'` : 'Geen voorstel en niets aangevinkt — kies "Alle kostenrekeningen" om er een te zoeken.'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="actions" style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center' }}>
            <button type="button" className="btn" disabled={!gewijzigd || bezig || uitgeschakeld} onClick={() => void opslaan()}>
              Opslaan
            </button>
            {opgeslagen && !fout && <span className="text-[12px] text-ok">opgeslagen</span>}
            {fout && (
              <span className="text-[12px] text-red" role="alert">
                {fout}
              </span>
            )}
          </div>
        </>
      )}
    </div>
  )
}
