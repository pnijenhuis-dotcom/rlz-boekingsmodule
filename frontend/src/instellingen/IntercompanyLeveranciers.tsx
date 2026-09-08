import { useCallback, useEffect, useMemo, useState } from 'react'
import { apiJson } from '../api/client'
import type { VendorLijstDto } from '../api/types'
import {
  haalIntercompanyLeveranciers,
  markeerIntercompanyLeverancier,
  verwijderIntercompanyLeverancier,
  type IntercompanyHistorieRegelDto,
  type IntercompanyLeverancierDto,
} from '../accordering/accorderingApi'
import { SearchableCombobox, type ComboboxOptie } from '../document/SearchableCombobox'

/** Blok "Intercompany — accordering overslaan" op Instellingen › Administraties › ‹BV› › Klant-accordering (nachtrun
 * 08/09-09 blok 1). Leest en schrijft dezelfde tabel als de doorbelasting-mapping (één bron): een leverancier die hier
 * staat slaat in deze administratie de stap "ter accordering" over (besluit Peter 08-09) en is nooit afletter-doel.
 * Rijen uit de doorbelasting-mapping staan er alleen-lezen bij (herkomst "doorbelasting"); alleen een handmatige rij
 * heeft een verwijder-kruisje (server: actief=false, nooit delete). Beheerder-only — de server weigert andere rollen,
 * de tab zelf is al Beheerder-only. Crediteur-kiezer = het bestaande doorzoekbare combobox-patroon. */

function formatMoment(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('nl-NL', { dateStyle: 'short', timeStyle: 'short' })
}

function historieTekst(h: IntercompanyHistorieRegelDto): string {
  const wie = h.actor_naam ?? 'systeem'
  const wat = h.actie === 'gemarkeerd' ? 'gemarkeerd als intercompany' : 'intercompany-markering verwijderd'
  return `${wie}: ${h.naam ?? h.vendor_id ?? '—'} ${wat}${h.reden ? ` — ${h.reden}` : ''}`
}

export function IntercompanyLeveranciers({ administratieId, naam }: { administratieId: string; naam: string }) {
  const [leveranciers, setLeveranciers] = useState<IntercompanyLeverancierDto[] | null>(null)
  const [historie, setHistorie] = useState<IntercompanyHistorieRegelDto[]>([])
  const [crediteuren, setCrediteuren] = useState<{ id: string; naam: string }[]>([])
  const [keuze, setKeuze] = useState<string | null>(null)
  const [reden, setReden] = useState('')
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const [toonHistorie, setToonHistorie] = useState(false)

  const laad = useCallback(() => {
    setFout(null)
    Promise.all([haalIntercompanyLeveranciers(administratieId), apiJson<VendorLijstDto>(`/administraties/${administratieId}/crediteuren`)])
      .then(([dto, vendors]) => {
        setLeveranciers(dto.leveranciers)
        setHistorie(dto.historie)
        setCrediteuren(vendors.crediteuren.filter((v) => v.naam).map((v) => ({ id: v.id, naam: v.naam as string })))
      })
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Intercompany-leveranciers laden mislukt'))
  }, [administratieId])

  useEffect(() => laad(), [laad])

  const gemarkeerd = useMemo(() => new Set((leveranciers ?? []).map((l) => l.vendor_id)), [leveranciers])
  const opties = useMemo<ComboboxOptie[]>(
    () => crediteuren.filter((c) => !gemarkeerd.has(c.id)).map((c) => ({ id: c.id, label: c.naam })),
    [crediteuren, gemarkeerd],
  )

  const toevoegen = async () => {
    if (!keuze) return
    setBezig(true)
    setFout(null)
    try {
      const dto = await markeerIntercompanyLeverancier(administratieId, keuze, reden.trim() || null)
      setLeveranciers(dto.leveranciers)
      setHistorie(dto.historie)
      setKeuze(null)
      setReden('')
    } catch (err) {
      setFout(err instanceof Error ? err.message : 'Markeren mislukt')
    } finally {
      setBezig(false)
    }
  }

  const verwijderen = async (vendorId: string) => {
    setBezig(true)
    setFout(null)
    try {
      const dto = await verwijderIntercompanyLeverancier(administratieId, vendorId)
      setLeveranciers(dto.leveranciers)
      setHistorie(dto.historie)
    } catch (err) {
      setFout(err instanceof Error ? err.message : 'Verwijderen mislukt')
    } finally {
      setBezig(false)
    }
  }

  return (
    <section className="panel" style={{ marginTop: 16 }} aria-labelledby={`ic-kop-${administratieId}`}>
      <h3 id={`ic-kop-${administratieId}`} style={{ margin: 0 }}>
        Intercompany — accordering overslaan
      </h3>
      <p className="hint" style={{ marginTop: 4 }}>
        Facturen van deze leveranciers (eigen groepsbedrijven) gaan in {naam} niet langs de klant-accordeur: alle
        controles blijven, de stap "ter accordering" wordt overgeslagen en de factuur wordt direct geboekt. Hun open
        posten zijn nooit een afletter-doel in de bank. Dezelfde lijst die de doorbelasting gebruikt — rijen uit de
        doorbelasting-mapping staan er alleen-lezen bij.
      </p>
      {fout && <div className="fout">{fout}</div>}
      {leveranciers === null ? (
        <p className="hint" style={{ margin: 0 }}>Laden…</p>
      ) : leveranciers.length === 0 ? (
        <p className="hint" style={{ margin: 0 }}>
          Nog geen intercompany-leveranciers — elke factuur gaat hier gewoon ter accordering.
        </p>
      ) : (
        <ul className="ic-lijst" style={{ listStyle: 'none', padding: 0, margin: '8px 0', display: 'grid', gap: 4 }}>
          {leveranciers.map((l) => (
            <li key={l.vendor_id} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span>{l.naam}</span>
              {l.bron === 'doorbelasting_mapping' ? (
                <span className="chip" title="Volgt de doorbelasting-mapping (tab Doorbelasting) — hier alleen-lezen">
                  doorbelasting
                </span>
              ) : (
                <span className="chip geheugen">handmatig</span>
              )}
              {l.verwijderbaar && (
                <button
                  type="button"
                  className="linkbtn"
                  aria-label={`Verwijder ${l.naam} als intercompany-leverancier`}
                  title="Markering verwijderen (de rij blijft in de historie)"
                  disabled={bezig}
                  onClick={() => void verwijderen(l.vendor_id)}
                >
                  ✕
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap', marginTop: 8 }}>
        <div style={{ minWidth: 280, flex: '1 1 280px' }}>
          <SearchableCombobox
            label="Intercompany-leverancier toevoegen"
            opties={opties}
            waarde={keuze}
            onWijzig={setKeuze}
            placeholder="Typ om een crediteur te zoeken…"
          />
        </div>
        <label style={{ display: 'grid', gap: 2, flex: '1 1 220px' }}>
          <span className="hint">Reden (optioneel, komt in de audit)</span>
          <input
            type="text"
            value={reden}
            maxLength={500}
            onChange={(e) => setReden(e.target.value)}
            placeholder="bv. besluit 08-09 intercompany Universal"
          />
        </label>
        <button type="button" className="btn" disabled={!keuze || bezig} onClick={() => void toevoegen()}>
          Markeren als intercompany
        </button>
      </div>
      {historie.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <button type="button" className="linkbtn" onClick={() => setToonHistorie((v) => !v)}>
            {toonHistorie ? 'Verberg historie' : `Historie (${historie.length})`}
          </button>
          {toonHistorie && (
            <ul className="hint" style={{ margin: '4px 0 0', paddingLeft: 16 }}>
              {historie.map((h, i) => (
                <li key={`${h.tijdstip}-${i}`}>
                  {formatMoment(h.tijdstip)} — {historieTekst(h)}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}
