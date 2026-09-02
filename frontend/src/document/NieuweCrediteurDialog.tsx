import { useState } from 'react'
import { ApiError, apiFetch } from '../api/client'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '../ui/basis'

export interface NieuweCrediteurVelden {
  naam: string
  kvk_nummer: string | null
  btw_nummer: string | null
  iban: string | null
}

export interface NieuweCrediteurResultaat {
  id: string
  naam: string | null
  kvk_opgeslagen?: boolean
  btw_opgeslagen?: boolean
  iban_vertrouwd?: boolean
  waarschuwingen?: string[]
}

/** "+ Nieuwe crediteur in RLZ" (controlescherm v2 ⑥, mockup controlescherm-v2.html): idempotente
 * vendor-aanmaak via de bestaande bouwsteen, voorgevuld uit de scan (naam · KvK · btw · IBAN, elk
 * aanpasbaar). RLZ krijgt de naam; KvK/btw landen per crediteur in het kenmerk-geheugen, het IBAN
 * wordt vertrouwd — zo vervalt de valse IBAN-wissel-blokkade bij een nieuwe entiteit. Een 409
 * "bestaat al" selecteert de bestaande crediteur (zelfde eindresultaat voor de controleur). */
export function NieuweCrediteurDialog({
  administratieId,
  documentId,
  voorgevuld,
  herkomst,
  onAangemaakt,
  onBestaand,
  onSluit,
}: {
  administratieId: string
  documentId: string
  voorgevuld: NieuweCrediteurVelden
  /** Welke velden uit de scan komen (herkomst-chip). */
  herkomst: { kvk?: boolean; btw?: boolean; iban?: boolean }
  onAangemaakt: (resultaat: NieuweCrediteurResultaat) => void
  onBestaand: (vendorId: string) => void
  onSluit: () => void
}) {
  const [naam, setNaam] = useState(voorgevuld.naam)
  const [kvk, setKvk] = useState(voorgevuld.kvk_nummer ?? '')
  const [btw, setBtw] = useState(voorgevuld.btw_nummer ?? '')
  const [iban, setIban] = useState(voorgevuld.iban ?? '')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const aanmaken = async () => {
    setBezig(true)
    setFout(null)
    try {
      const resp = await apiFetch(`/administraties/${administratieId}/crediteuren`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          naam: naam.trim(),
          kvk_nummer: kvk.trim() || null,
          btw_nummer: btw.trim() || null,
          iban: iban.trim() || null,
          document_id: documentId,
        }),
      })
      const body: unknown = await resp.json().catch(() => null)
      if (resp.ok) {
        onAangemaakt(body as NieuweCrediteurResultaat)
        return
      }
      const detail = body && typeof body === 'object' ? (body as { detail?: unknown }).detail : null
      if (resp.status === 409 && detail && typeof detail === 'object' && 'vendor_id' in detail) {
        onBestaand(String((detail as { vendor_id: unknown }).vendor_id))
        return
      }
      setFout(
        typeof detail === 'string'
          ? detail
          : detail && typeof detail === 'object' && 'message' in detail
            ? String((detail as { message: unknown }).message)
            : resp.statusText || `Fout (${resp.status})`,
      )
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Crediteur aanmaken mislukt.')
    } finally {
      setBezig(false)
    }
  }

  const chip = (uitScan: boolean | undefined) =>
    uitScan ? (
      <span className="chip ok" style={{ marginLeft: 6 }}>
        uit factuur
      </span>
    ) : null

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onSluit()}>
      <DialogContent>
        <DialogTitle>Nieuwe crediteur in Reeleezee</DialogTitle>
        <DialogDescription>
          Voorgevuld uit de scan — controleer en pas aan. De naam gaat naar Reeleezee; KvK, btw en IBAN worden bij deze
          crediteur onthouden (het IBAN als vertrouwde rekening) zodat de volgende factuur direct herkend wordt.
        </DialogDescription>
        <div className="row">
          <label htmlFor="nc-naam">Naam</label>
          <input id="nc-naam" value={naam} onChange={(e) => setNaam(e.target.value)} />
        </div>
        <div className="grid2">
          <div>
            <label htmlFor="nc-kvk">KvK-nummer{chip(herkomst.kvk)}</label>
            <input id="nc-kvk" value={kvk} inputMode="numeric" onChange={(e) => setKvk(e.target.value)} placeholder="8 cijfers" />
          </div>
          <div>
            <label htmlFor="nc-btw">Btw-nummer{chip(herkomst.btw)}</label>
            <input id="nc-btw" value={btw} onChange={(e) => setBtw(e.target.value)} placeholder="NL…B01" />
          </div>
        </div>
        <div className="row">
          <label htmlFor="nc-iban">IBAN{chip(herkomst.iban)}</label>
          <input id="nc-iban" value={iban} onChange={(e) => setIban(e.target.value)} placeholder="NL.." />
        </div>
        {fout && <div className="fout">{fout}</div>}
        <div className="actions" style={{ marginTop: 12 }}>
          <button type="button" className="btn secondary" disabled={bezig} onClick={onSluit}>
            Annuleren
          </button>
          <button type="button" className="btn" disabled={bezig || !naam.trim()} onClick={() => void aanmaken()}>
            {bezig ? 'Bezig…' : 'Aanmaken in RLZ ✓'}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
