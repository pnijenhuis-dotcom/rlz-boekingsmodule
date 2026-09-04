import { useMemo, useState } from 'react'
import { SearchableCombobox, type ComboboxOptie } from '../document/SearchableCombobox'
import { Badge, Checkbox } from '../ui/basis'
import type {
  OdooMappingInvoerDto,
  OdooMappingSoort,
  OdooMappingStandDto,
  OdooOverstapVoorbereidingDto,
  OdooRekeningDto,
  OdooTariefDto,
} from './instellingenApi'

/** Rekening-mapping RLZ → Odoo (blok A 04-09, besluit Peter beslispunt 1 van "ODOO-ADAPTER BLOK E"): bij een
 * overstap vertaalt het boekingsgeheugen zijn grootboek/btw via deze tabel, zodat de autoboek-opt-ins blijven
 * werken. Eén component, twee afnemers:
 *   - wizard-stap "mapping" (modus 'kiezen'): het deterministische voorstel staat vooringevuld, de mens bevestigt
 *     de HELE tabel — "Koppeling opslaan" blijft uit tot élke in-gebruik-rij een Odoo-tegenhanger heeft;
 *   - detail-dialoog "Mapping bekijken/corrigeren…" (modus 'corrigeren'): élke wijziging is direct een PUT =
 *     nieuwe versie (append-only), zichtbaar als versie-badge.
 * UX-patronen als norm: de kop-teller is een restant-balk (open = teal, compleet = groen ✓); de herkomst-chip
 * volgt de voorstel-kaart-semantiek (groen = exact, oranje = bevestigen mét reden, rood = nog te kiezen);
 * de lege stand is één zin, geen lege tabel. Geld-/rekeninglogica staat NIET hier: het voorstel komt van de
 * server (`app/odoo/mapping.py`), dit component kiest alleen. */

export type MappingBronWeergave = 'zelfde_code' | 'code_verlengd' | 'tarief' | 'handmatig' | null

export interface MappingTabelRij {
  soort: OdooMappingSoort
  rlz_id: string
  rlz_code: string | null
  rlz_naam: string | null
  /** Alleen btw: percentage als string ("21.00") en de verlegd-vlag — voor de RLZ-kolom. */
  rlz_percentage?: string | null
  verlegd?: boolean
  in_gebruik_observaties: number
  in_gebruik_open_regels: number
  /** Huidige keuze (voorstel, mens-keuze of geldende mapping); null = nog te kiezen. */
  odoo_id: number | null
  /** Herkomst van de huidige keuze; null zolang er niets gekozen is. */
  bron: MappingBronWeergave
  /** Alleen corrigeer-modus: geldende versie (1 = bij de overstap; > 1 = gecorrigeerd). */
  versie?: number
}

export function mappingSleutel(soort: OdooMappingSoort, rlzId: string): string {
  return `${soort}:${rlzId}`
}

function alsBron(reden: string | null | undefined): MappingBronWeergave {
  return reden === 'zelfde_code' || reden === 'code_verlengd' || reden === 'tarief' || reden === 'handmatig' ? reden : null
}

/** Wizard: voorbereidings-response → tabelrijen mét het voorstel vooringevuld. */
export function rijenUitVoorbereiding(v: OdooOverstapVoorbereidingDto): MappingTabelRij[] {
  const grootboek: MappingTabelRij[] = v.grootboek.map((r) => ({
    soort: 'grootboek',
    rlz_id: r.rlz_id,
    rlz_code: r.rlz_code,
    rlz_naam: r.rlz_naam,
    in_gebruik_observaties: r.in_gebruik_observaties,
    in_gebruik_open_regels: r.in_gebruik_open_regels,
    odoo_id: r.voorstel_odoo_id,
    bron: r.voorstel_odoo_id == null ? null : alsBron(r.reden),
  }))
  const btw: MappingTabelRij[] = v.btw.map((r) => ({
    soort: 'btw',
    rlz_id: r.rlz_id,
    rlz_code: null,
    rlz_naam: r.rlz_naam,
    rlz_percentage: r.rlz_percentage,
    verlegd: r.verlegd,
    in_gebruik_observaties: r.in_gebruik_observaties,
    in_gebruik_open_regels: r.in_gebruik_open_regels,
    odoo_id: r.voorstel_odoo_id,
    bron: r.voorstel_odoo_id == null ? null : alsBron(r.reden),
  }))
  return [...grootboek, ...btw]
}

/** Detail-dialoog: geldende mapping → tabelrijen (altijd compleet — de overstap eiste dat al). */
export function rijenUitStand(s: OdooMappingStandDto): MappingTabelRij[] {
  return [...s.grootboek, ...s.btw].map((r) => ({
    soort: r.soort,
    rlz_id: r.rlz_id,
    rlz_code: r.rlz_code,
    rlz_naam: r.rlz_naam,
    in_gebruik_observaties: 0,
    in_gebruik_open_regels: 0,
    odoo_id: r.odoo_id,
    bron: alsBron(r.bron),
    versie: r.versie,
  }))
}

/** Request-body voor POST …/odoo/overstap: alleen de gekozen rijen (de server weigert een onvolledige mapping
 * met 422 zolang er in-gebruik-rijen zonder tegenhanger zijn — de knop staat dan al uit). */
export function mappingInvoer(rijen: MappingTabelRij[]): OdooMappingInvoerDto {
  const invoer: OdooMappingInvoerDto = { grootboek: [], btw: [] }
  for (const r of rijen) {
    if (r.odoo_id == null) continue
    invoer[r.soort].push({ rlz_id: r.rlz_id, odoo_id: r.odoo_id })
  }
  return invoer
}

export function mappingTelling(rijen: MappingTabelRij[]): { gekozen: number; totaal: number } {
  return { gekozen: rijen.filter((r) => r.odoo_id != null).length, totaal: rijen.length }
}

export function mappingCompleet(rijen: MappingTabelRij[]): boolean {
  return rijen.every((r) => r.odoo_id != null)
}

/** Herkomst-chip: groen = exact, oranje = bevestigen (mét reden), neutraal = handmatig, rood = nog te kiezen. */
export function bronChip(bron: MappingBronWeergave, odooId: number | null): { klasse: string; tekst: string } {
  if (odooId == null) return { klasse: 'chip blokkerend', tekst: 'kies' }
  switch (bron) {
    case 'zelfde_code':
      return { klasse: 'chip ok', tekst: 'zelfde code' }
    case 'code_verlengd':
      return { klasse: 'chip afwijking', tekst: 'code + 00 — bevestig' }
    case 'tarief':
      return { klasse: 'chip afwijking', tekst: 'tarief' }
    case 'handmatig':
      return { klasse: 'chip handmatig', tekst: 'handmatig' }
    default:
      return { klasse: 'chip handmatig', tekst: 'gekozen' }
  }
}

/** `percentage`/`rlz_percentage` zijn de canonieke FRACTIE (0.21 — zoals `taxrate_cache.percentage` en de
 * Odoo-`amount`/100, backend-schema's 04-09) → "21%". Weergave-afronding op 2 decimalen; geen geldlogica. */
export function percentageTekst(p: string | null | undefined): string | null {
  if (p == null || p === '') return null
  const n = Number(p)
  if (Number.isNaN(n)) return `${p}%`
  return `${(Math.round(n * 10000) / 100).toLocaleString('nl-NL', { maximumFractionDigits: 2 })}%`
}

export function grootboekOpties(odoo: OdooRekeningDto[]): ComboboxOptie[] {
  return odoo.map((r) => ({ id: String(r.odoo_id), code: r.code, label: r.naam }))
}

/** Btw-opties mét percentage als code; de synthetische rij heet expliciet "geen btw-code in Odoo" (= geen
 * tax_ids), zodat niemand 'm voor een echt 0%-tarief houdt. */
export function btwOpties(odoo: OdooTariefDto[]): ComboboxOptie[] {
  return odoo.map((t) => ({
    id: String(t.odoo_id),
    code: percentageTekst(t.percentage) ?? '',
    label: t.synthetisch ? 'Geen btw (0%) — geen btw-code in Odoo' : `${t.naam}${t.verlegd ? ' (verlegd)' : ''}`,
  }))
}

function inGebruikTekst(r: MappingTabelRij): string {
  const delen: string[] = []
  if (r.in_gebruik_observaties > 0) delen.push(`${r.in_gebruik_observaties}× geheugen`)
  if (r.in_gebruik_open_regels > 0) delen.push(`${r.in_gebruik_open_regels} open ${r.in_gebruik_open_regels === 1 ? 'regel' : 'regels'}`)
  return delen.length ? `in gebruik: ${delen.join(' · ')}` : ''
}

function rlzLabel(r: MappingTabelRij): string {
  if (r.soort === 'btw') {
    // RLZ zet het percentage van een verlegd tarief op 0 — "0%" zou daar misleiden, dus alleen het label "verlegd".
    const pct = r.verlegd ? null : percentageTekst(r.rlz_percentage)
    return [r.rlz_naam ?? 'onbekend RLZ-tarief', pct, r.verlegd ? 'verlegd' : null].filter(Boolean).join(' · ')
  }
  return [r.rlz_code, r.rlz_naam].filter(Boolean).join(' · ') || 'onbekende RLZ-rekening'
}

interface Props {
  rijen: MappingTabelRij[]
  odooGrootboek: OdooRekeningDto[]
  odooBtw: OdooTariefDto[]
  /** Keuze per rij; null = keuze gewist. In corrigeer-modus doet de aanroeper hier de PUT. */
  onKies: (rij: MappingTabelRij, odooId: number | null) => void
  modus?: 'kiezen' | 'corrigeren'
  /** Corrigeer-modus: sleutel van de rij waarvan de PUT loopt (combobox even uit). */
  bezigSleutel?: string | null
}

export function OdooMappingTabel({ rijen, odooGrootboek, odooBtw, onKies, modus = 'kiezen', bezigSleutel = null }: Props) {
  const [alleenTeKiezen, setAlleenTeKiezen] = useState(false)
  const gbOpties = useMemo(() => grootboekOpties(odooGrootboek), [odooGrootboek])
  const btwOptieLijst = useMemo(() => btwOpties(odooBtw), [odooBtw])
  const telling = mappingTelling(rijen)
  const compleet = telling.totaal > 0 && telling.gekozen === telling.totaal

  if (rijen.length === 0) {
    return (
      <p className="hint" style={{ margin: 0 }} data-testid="odoo-mapping-leeg">
        Geen boekingsgeheugen of open regels om te vertalen — mapping niet nodig.
      </p>
    )
  }

  const zichtbaar = alleenTeKiezen ? rijen.filter((r) => r.odoo_id == null) : rijen
  const grootboek = zichtbaar.filter((r) => r.soort === 'grootboek')
  const btw = zichtbaar.filter((r) => r.soort === 'btw')
  const totaalGrootboek = rijen.filter((r) => r.soort === 'grootboek').length
  const totaalBtw = rijen.filter((r) => r.soort === 'btw').length
  const nog = telling.totaal - telling.gekozen

  return (
    <div data-testid="odoo-mapping-tabel">
      {/* Kop-teller als restant-balk (UX-patronen als norm): open = teal, compleet = groen ✓. */}
      <div className={`restant-balk${compleet ? ' compleet' : ''}`} data-testid="odoo-mapping-teller">
        <span>
          <b>{telling.gekozen}</b> van {telling.totaal} gekoppeld
        </span>
        <span className="balk" aria-hidden>
          <span style={{ width: `${telling.totaal ? Math.round((telling.gekozen / telling.totaal) * 100) : 0}%` }} />
        </span>
        {compleet ? <span className="compleet-tekst">✓ alles gekoppeld</span> : <span className="nog">nog {nog} te kiezen</span>}
        {modus === 'kiezen' && (
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, margin: 0, fontSize: 12, whiteSpace: 'nowrap' }}>
            <Checkbox checked={alleenTeKiezen} onChange={(e) => setAlleenTeKiezen(e.target.checked)} aria-label="Alleen nog te kiezen" />
            alleen nog te kiezen
          </label>
        )}
      </div>

      <MappingBlok
        titel={`Grootboek (${totaalGrootboek})`}
        rlzKop="RLZ-rekening"
        odooKop="Odoo-rekening"
        rijen={grootboek}
        verborgen={alleenTeKiezen && grootboek.length === 0 && totaalGrootboek > 0}
        opties={gbOpties}
        onKies={onKies}
        modus={modus}
        bezigSleutel={bezigSleutel}
      />
      <MappingBlok
        titel={`Btw-tarieven (${totaalBtw})`}
        rlzKop="RLZ-btw-tarief"
        odooKop="Odoo-tax"
        rijen={btw}
        verborgen={alleenTeKiezen && btw.length === 0 && totaalBtw > 0}
        opties={btwOptieLijst}
        onKies={onKies}
        modus={modus}
        bezigSleutel={bezigSleutel}
      />
    </div>
  )
}

function MappingBlok({
  titel,
  rlzKop,
  odooKop,
  rijen,
  verborgen,
  opties,
  onKies,
  modus,
  bezigSleutel,
}: {
  titel: string
  rlzKop: string
  odooKop: string
  rijen: MappingTabelRij[]
  verborgen: boolean
  opties: ComboboxOptie[]
  onKies: Props['onKies']
  modus: 'kiezen' | 'corrigeren'
  bezigSleutel: string | null
}) {
  if (rijen.length === 0 && !verborgen) return null
  return (
    <section style={{ marginBottom: 12 }}>
      <h4 style={{ margin: '0 0 6px', fontSize: 12.5 }}>{titel}</h4>
      {verborgen ? (
        <p className="hint" style={{ margin: 0 }}>
          Alles in dit blok is gekoppeld.
        </p>
      ) : (
        <div className="tabel-scroll">
          <table className="odoo-mapping-tabel">
            <thead>
              <tr>
                <th>{rlzKop}</th>
                <th>{odooKop}</th>
                <th>Herkomst</th>
              </tr>
            </thead>
            <tbody>
              {rijen.map((r) => {
                const sleutel = mappingSleutel(r.soort, r.rlz_id)
                const chip = bronChip(r.bron, r.odoo_id)
                const inGebruik = inGebruikTekst(r)
                const bezig = bezigSleutel === sleutel
                return (
                  <tr key={sleutel} data-testid={`odoo-mapping-rij-${sleutel}`}>
                    <td>
                      <div>{rlzLabel(r)}</div>
                      {inGebruik && (
                        <div className="hint" style={{ margin: 0, fontSize: 11 }}>
                          {inGebruik}
                        </div>
                      )}
                    </td>
                    <td style={{ minWidth: 220 }}>
                      {bezig ? (
                        <span className="hint" style={{ margin: 0 }}>
                          Opslaan…
                        </span>
                      ) : (
                        <SearchableCombobox
                          label={`${odooKop} voor ${rlzLabel(r)}`}
                          toonLabel={false}
                          opties={opties}
                          waarde={r.odoo_id == null ? null : String(r.odoo_id)}
                          onWijzig={(id) => onKies(r, id == null ? null : Number(id))}
                          placeholder="Kies Odoo-tegenhanger…"
                          fout={r.odoo_id == null}
                        />
                      )}
                    </td>
                    <td style={{ whiteSpace: 'nowrap' }}>
                      <span className={chip.klasse}>{chip.tekst}</span>
                      {modus === 'corrigeren' && (r.versie ?? 1) > 1 && (
                        <>
                          {' '}
                          <Badge variant="info" title="Gecorrigeerd ná de overstap — append-only, eerdere versies blijven in de audit">
                            v{r.versie}
                          </Badge>
                        </>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
