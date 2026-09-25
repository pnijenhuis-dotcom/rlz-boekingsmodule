import { useEffect, useState } from 'react'
import { ApiError, apiFetch } from '../api/client'
import type { CrediteurDetailDto } from '../api/types'
import { Zijpaneel } from '../ui/basis'

export interface NieuweCrediteurVelden {
  naam: string
  kvk_nummer: string | null
  btw_nummer: string | null
  iban: string | null
}

export interface CrediteurAdresVelden {
  straat: string
  postcode: string
  plaats: string
  land: string
}

export interface NieuweCrediteurResultaat {
  id: string
  naam: string | null
  kvk_opgeslagen?: boolean
  btw_opgeslagen?: boolean
  iban_vertrouwd?: boolean
  waarschuwingen?: string[]
}

const LEEG_ADRES: CrediteurAdresVelden = { straat: '', postcode: '', plaats: '', land: '' }

/** UBL-adresregel "Straat 1, 1234 AB Plaats, NL" (documenten/ubl._leverancier_adres) deterministisch terug naar
 * velden — alleen als de vorm herkenbaar is; anders alles in `straat` zodat niets verdwijnt. */
export function adresUitRegel(regel: string | null | undefined): CrediteurAdresVelden {
  if (!regel || !regel.trim()) return LEEG_ADRES
  const delen = regel.split(',').map((d) => d.trim()).filter(Boolean)
  if (delen.length < 2) return { ...LEEG_ADRES, straat: delen[0] ?? '' }
  const straat = delen[0]
  const land = delen.length >= 3 && /^[A-Z]{2}$/.test(delen[delen.length - 1]) ? delen[delen.length - 1] : ''
  const plaatsDeel = land ? delen[delen.length - 2] : delen[delen.length - 1]
  const m = /^(\d{4}\s?[A-Z]{2})\s+(.+)$/i.exec(plaatsDeel)
  return {
    straat,
    postcode: m ? m[1].toUpperCase().replace(/^(\d{4})([A-Z]{2})$/, '$1 $2') : '',
    plaats: m ? m[2] : plaatsDeel,
    land,
  }
}

function adresPayload(a: CrediteurAdresVelden): Record<string, string> | null {
  const uit: Record<string, string> = {}
  for (const k of ['straat', 'postcode', 'plaats', 'land'] as const) {
    if (a[k].trim()) uit[k] = a[k].trim()
  }
  return Object.keys(uit).length ? uit : null
}

export const IBAN_ONTBREEKT_TEKST = 'geen IBAN — incasso/buitenland? je kunt ’m later toevoegen via de IBAN-route (vier ogen)'

/** Crediteur-zijpaneel (blok 5 feedbackrun 25-09, FV-14 + FV-15) — vervangt de modale "Nieuwe crediteur"-dialoog.
 *
 * Modus `nieuw`: voorgevuld uit de scan/UBL (naam · KvK · btw · IBAN · adres uit de UBL), chips "uit factuur"/"uit UBL"
 * per veld; opslaan = de bestaande Vendor-PUT (`POST …/crediteuren`); een 409 "bestaat al" selecteert de bestaande
 * crediteur. Ontbreekt het IBAN, dan is dat een WAARSCHUWING (incasso/buitenland), geen blokkade.
 * Modus `bewerken`: laadt `GET …/crediteuren/{id}` en slaat op met `PUT …/crediteuren/{id}` (naam/adres/KvK/btw);
 * géén IBAN-veld — de vertrouwde IBAN's staan lees-only en "IBAN toevoegen/wijzigen" opent de IBAN-route (vier ogen).
 * Het paneel is niet-modaal (Zijpaneel): de factuur links blijft leesbaar en scrollbaar. */
export function CrediteurPaneel({
  administratieId,
  documentId,
  modus = 'nieuw',
  vendorId = null,
  voorgevuld,
  herkomst,
  bron = 'scan',
  adres = null,
  extractieLoopt = false,
  onAangemaakt,
  onBestaand,
  onGewijzigd,
  onIbanRoute,
  onSluit,
}: {
  administratieId: string
  documentId: string
  modus?: 'nieuw' | 'bewerken'
  /** Bewerk-modus: de crediteur die geladen/bewerkt wordt. */
  vendorId?: string | null
  voorgevuld: NieuweCrediteurVelden
  /** Welke velden uit de scan/UBL komen (herkomst-chip). */
  herkomst: { kvk?: boolean; btw?: boolean; iban?: boolean; adres?: boolean }
  /** Blok 3 herstelrun 08-09: 'UBL' = deterministisch uit de XML (chip "uit UBL"), anders "uit factuur" (scan). */
  bron?: 'scan' | 'UBL'
  /** Adresregel uit de UBL — voorgevuld in de adresvelden (nieuw-modus). */
  adres?: string | null
  /** Blok 3 herstelrun 08-09: de extractie van dit (PDF-)document loopt nog — de velden volgen; nooit stil leeg. */
  extractieLoopt?: boolean
  onAangemaakt: (resultaat: NieuweCrediteurResultaat) => void
  onBestaand: (vendorId: string) => void
  onGewijzigd?: (resultaat: NieuweCrediteurResultaat) => void
  /** Bewerk-modus: "IBAN toevoegen/wijzigen" → de IBAN-wissel/vier-ogen-route op het controlescherm. */
  onIbanRoute?: () => void
  onSluit: () => void
}) {
  const bewerken = modus === 'bewerken'
  const [naam, setNaam] = useState(voorgevuld.naam)
  const [kvk, setKvk] = useState(voorgevuld.kvk_nummer ?? '')
  const [btw, setBtw] = useState(voorgevuld.btw_nummer ?? '')
  const [iban, setIban] = useState(voorgevuld.iban ?? '')
  const [adresVelden, setAdresVelden] = useState<CrediteurAdresVelden>(() => adresUitRegel(adres))
  const [detail, setDetail] = useState<CrediteurDetailDto | null>(null)
  const [laden, setLaden] = useState(bewerken)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  useEffect(() => {
    if (!bewerken || !vendorId) return
    let actueel = true
    setLaden(true)
    apiFetch(`/administraties/${administratieId}/crediteuren/${vendorId}`)
      .then(async (resp) => {
        if (!resp.ok) throw new Error(`Crediteur laden mislukt (${resp.status})`)
        return (await resp.json()) as CrediteurDetailDto
      })
      .then((d) => {
        if (!actueel) return
        setDetail(d)
        setNaam(d.naam ?? '')
        setKvk(d.kvk_nummer ?? '')
        setBtw(d.btw_nummer ?? '')
        setAdresVelden({
          straat: d.adres.straat ?? (d.adres.regel && !d.adres.plaats ? d.adres.regel : ''),
          postcode: d.adres.postcode ?? '',
          plaats: d.adres.plaats ?? '',
          land: d.adres.land ?? '',
        })
      })
      .catch((err: unknown) => {
        if (actueel) setFout(err instanceof Error ? err.message : 'Crediteur laden mislukt.')
      })
      .finally(() => {
        if (actueel) setLaden(false)
      })
    return () => {
      actueel = false
    }
  }, [administratieId, bewerken, vendorId])

  const opslaan = async () => {
    setBezig(true)
    setFout(null)
    try {
      const body: Record<string, unknown> = {
        naam: naam.trim(),
        kvk_nummer: kvk.trim() || null,
        btw_nummer: btw.trim() || null,
      }
      const adresBody = adresPayload(adresVelden)
      if (adresBody || bewerken) body.adres = adresBody
      if (!bewerken) {
        body.iban = iban.trim() || null
        body.document_id = documentId
      }
      const resp = await apiFetch(
        bewerken
          ? `/administraties/${administratieId}/crediteuren/${vendorId}`
          : `/administraties/${administratieId}/crediteuren`,
        { method: bewerken ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
      )
      const antwoord: unknown = await resp.json().catch(() => null)
      if (resp.ok) {
        if (bewerken) onGewijzigd?.(antwoord as NieuweCrediteurResultaat)
        else onAangemaakt(antwoord as NieuweCrediteurResultaat)
        return
      }
      const d = antwoord && typeof antwoord === 'object' ? (antwoord as { detail?: unknown }).detail : null
      if (resp.status === 409 && d && typeof d === 'object' && 'vendor_id' in d) {
        onBestaand(String((d as { vendor_id: unknown }).vendor_id))
        return
      }
      setFout(
        typeof d === 'string'
          ? d
          : d && typeof d === 'object' && 'message' in d
            ? String((d as { message: unknown }).message)
            : resp.statusText || `Fout (${resp.status})`,
      )
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : bewerken ? 'Crediteur bijwerken mislukt.' : 'Crediteur aanmaken mislukt.')
    } finally {
      setBezig(false)
    }
  }

  const chip = (uitBron: boolean | undefined) =>
    !bewerken && uitBron ? (
      <span className="chip ok" style={{ marginLeft: 6 }}>
        {bron === 'UBL' ? 'uit UBL' : 'uit factuur'}
      </span>
    ) : null

  const ibanOntbreekt = bewerken ? detail !== null && detail.vertrouwde_ibans.length === 0 : iban.trim() === ''

  return (
    <Zijpaneel
      titel={bewerken ? 'Crediteurgegevens bewerken' : 'Nieuwe crediteur in Reeleezee'}
      testId="crediteur-paneel"
      beschrijving={
        bewerken
          ? 'Naam, adres, KvK en btw-nummer worden bijgewerkt in Reeleezee en onthouden bij deze crediteur. Rekeningnummers wijzig je via de IBAN-route (vier ogen).'
          : `${bron === 'UBL' ? 'Voorgevuld uit de UBL (deterministisch gelezen, geen AI)' : 'Voorgevuld uit de scan'} — controleer en pas aan; de factuur blijft links zichtbaar. De naam en het adres gaan naar Reeleezee; KvK, btw en IBAN worden bij deze crediteur onthouden (het IBAN als vertrouwde rekening).`
      }
      onSluit={onSluit}
    >
      {extractieLoopt && (
        <div className="hint" role="status" data-testid="nieuwe-crediteur-verwerking-loopt">
          Verwerking loopt — de velden uit de factuur volgen zodra de extractie klaar is. Je kunt de crediteur nu ook
          handmatig invullen.
        </div>
      )}
      {laden && (
        <div className="hint" role="status">
          Crediteurgegevens laden…
        </div>
      )}
      {!bewerken && adres && (
        <div className="hint" data-testid="nieuwe-crediteur-adres">
          Adres volgens de UBL: {adres}
        </div>
      )}
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
      <fieldset style={{ border: 'none', padding: 0, margin: '8px 0 0' }} data-testid="crediteur-adres-velden">
        <legend className="hint" style={{ padding: 0 }}>
          Adres{chip(herkomst.adres)}
        </legend>
        <div className="row">
          <label htmlFor="nc-straat">Straat en huisnummer</label>
          <input id="nc-straat" value={adresVelden.straat} onChange={(e) => setAdresVelden((a) => ({ ...a, straat: e.target.value }))} />
        </div>
        <div className="grid2">
          <div>
            <label htmlFor="nc-postcode">Postcode</label>
            <input id="nc-postcode" value={adresVelden.postcode} onChange={(e) => setAdresVelden((a) => ({ ...a, postcode: e.target.value }))} />
          </div>
          <div>
            <label htmlFor="nc-plaats">Plaats</label>
            <input id="nc-plaats" value={adresVelden.plaats} onChange={(e) => setAdresVelden((a) => ({ ...a, plaats: e.target.value }))} />
          </div>
        </div>
        <div className="row">
          <label htmlFor="nc-land">Land (code)</label>
          <input id="nc-land" value={adresVelden.land} onChange={(e) => setAdresVelden((a) => ({ ...a, land: e.target.value }))} placeholder="NL" style={{ maxWidth: 120 }} />
        </div>
      </fieldset>
      {bewerken ? (
        <div className="row" data-testid="crediteur-ibans-leesonly">
          <label>Vertrouwde rekeningnummers</label>
          {detail && detail.vertrouwde_ibans.length > 0 ? (
            <ul style={{ margin: '4px 0', paddingLeft: 18 }}>
              {detail.vertrouwde_ibans.map((i) => (
                <li key={i}>{i}</li>
              ))}
            </ul>
          ) : (
            <div className="hint" style={{ marginTop: 2 }}>
              {laden ? '…' : 'Nog geen vertrouwd rekeningnummer.'}
            </div>
          )}
          {onIbanRoute && (
            <button
              type="button"
              className="linkbtn"
              data-testid="crediteur-iban-route"
              title="Een rekeningnummer toevoegen of wijzigen loopt altijd via de IBAN-wissel/vier-ogen-route — nooit als vrij veld"
              onClick={() => {
                onIbanRoute()
                onSluit()
              }}
            >
              IBAN toevoegen/wijzigen → IBAN-route (vier ogen)
            </button>
          )}
        </div>
      ) : (
        <div className="row">
          <label htmlFor="nc-iban">IBAN{chip(herkomst.iban)}</label>
          <input id="nc-iban" value={iban} onChange={(e) => setIban(e.target.value)} placeholder="NL.." />
        </div>
      )}
      {ibanOntbreekt && (
        <div className="waarschuwing" role="note" data-testid="crediteur-iban-ontbreekt">
          ⚠ {IBAN_ONTBREEKT_TEKST}
        </div>
      )}
      {fout && <div className="fout">{fout}</div>}
      <div className="actions" style={{ marginTop: 12 }}>
        <button type="button" className="btn secondary" disabled={bezig} onClick={onSluit}>
          Annuleren
        </button>
        <button type="button" className="btn" disabled={bezig || laden || !naam.trim()} onClick={() => void opslaan()}>
          {bezig ? 'Bezig…' : bewerken ? 'Opslaan in RLZ ✓' : 'Aanmaken in RLZ ✓'}
        </button>
      </div>
    </Zijpaneel>
  )
}
