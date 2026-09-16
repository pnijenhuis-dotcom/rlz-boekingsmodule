import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '../api/client'
import type { KassaProfielStandDto, OmzetBetaalwijze, OmzetBronDefaultsDto, OmzetBronInstellingenDto, OmzetBronInstellingenWaarden, OmzetEtenDrinkenTarief, OmzetPsp } from '../api/types'
import { SearchableCombobox, type ComboboxOptie } from '../document/SearchableCombobox'
import { GebruikerRijMenu } from '../gebruikers/GebruikerRijMenu'
import { Button, Select } from '../ui/basis'
import { haalOmzetBronInstellingenOp, zetOmzetBronInstellingen } from '../omzet/omzetApi'
import { haalKassaProfielOp, zetKassaProfiel } from './instellingenApi'

/** Blok "Omzetbronnen" op Instellingen › Administraties › ‹administratie› › Boeken & AI (besluiten Peter 16-09, blok B;
 * de omzet-instellingen leven op deze tab — registry-synoniem 'omzet', anker `#omzetbronnen`). Eén bron:
 * `omzet_instelling.bron_instellingen` via GET/PUT `/administraties/{id}/omzet/bron-instellingen` (CONTRACT_4):
 *  (a) stores — AFGELEIDE weergave (0151, Peter 16-09 avond): de stores die in déze administratie landen; beheren
 *      gebeurt platformbreed op Instellingen › Boeken › Stores (Sunshine Island = eigen BV);
 *  (b) tegenrekening per betaalwijze (pin/cash/stripe/kasverschil/storting) — combobox op `rekeningen` uit de DTO,
 *      default uit `defaults` mét chip "standaard (op naam)" zolang de mens niets koos;
 *  (c) categorie-mapping pilates (productnaam → categorie) + btw-tarief per categorie (`tarieven`, default-chip);
 *  (d) combi-regel — vast "pro rato binnen de batch" (Peter 16-09), alleen informatie;
 *  (e) PSP (Stripe/Mollie/anders) + kostenrekening + eten/drinken laag/hoog.
 * Eén primaire knop "Opslaan" + ⋯ (Herstel standaard). Fouten uit de PUT (409/422) staan zichtbaar bij het veld/blok.
 * Alleen bedragen-vrije configuratie — de verdeling zelf rekent de backend (geld in code). */

export const BETAALWIJZEN: readonly { sleutel: OmzetBetaalwijze; label: string; uitleg: string }[] = [
  { sleutel: 'pin', label: 'PIN', uitleg: 'tussenrekening "PIN onderweg/kruispost" — de bank lettert de PIN-afstorting af' },
  { sleutel: 'cash', label: 'Contant', uitleg: 'kas — het kasboek is de kascheck' },
  { sleutel: 'stripe', label: 'Stripe/PSP', uitleg: 'tussenrekening "PSP onderweg" — de payout (+1…+7 d) matcht de bank' },
  { sleutel: 'kasverschil', label: 'Kasverschil', uitleg: 'rekening "kasverschillen" (oranje signaal blijft)' },
  { sleutel: 'storting', label: 'Storting automaat', uitleg: 'kas → bank; bankontvangst sealbag/storting matcht' },
] as const

const PSP_OPTIES: readonly { waarde: OmzetPsp; label: string }[] = [
  { waarde: 'stripe', label: 'Stripe — EU-dienst, btw verlegd (rubriek 4b)' },
  { waarde: 'mollie', label: 'Mollie — NL, 21 % voorbelasting' },
  { waarde: 'anders', label: 'Anders' },
]

const COMBI_REGEL = 'pro_rato_batch'

type Waarden = OmzetBronInstellingenWaarden

const CODE_DEFAULT_PSP: OmzetPsp = 'stripe'
const CODE_DEFAULT_ETEN: OmzetEtenDrinkenTarief = 'laag'

/** Spiegel van backend `mapping.normaliseer_categorie_sleutel`: lowercase → voorloopnummering weg → leestekens naar
 * spaties → whitespace inklappen. `categorie_btw` en `defaults.categorie_btw` zijn op deze sleutel geïndexeerd. */
export function categorieSleutel(categorie: string | null | undefined): string | null {
  if (!categorie) return null
  const zonderNummer = categorie.toLowerCase().replace(/^\s*\d+[.)]?\s*/, '')
  const tokens = zonderNummer.split(/[^\p{L}\p{N}]+/u).filter(Boolean)
  return tokens.length ? tokens.join(' ') : null
}

/** `defaults.categorie_btw[sleutel]` is gebouwd als `{klasse, taxrate_id}` (contract: kaal id) — beide lezen. */
function defaultTaxrate(defaults: OmzetBronDefaultsDto, sleutel: string): { taxrate_id: string | null; klasse: string | null } {
  const x = defaults.categorie_btw?.[sleutel]
  if (!x) return { taxrate_id: null, klasse: null }
  if (typeof x === 'string') return { taxrate_id: x, klasse: null }
  return { taxrate_id: x.taxrate_id ?? null, klasse: x.klasse ?? null }
}

function alsLijst<T>(x: T[] | null | undefined): T[] {
  return Array.isArray(x) ? x : []
}

/** Legacy-antwoord (vóór 16-09) droeg `psp: {}` en `rekeningen: {}` — nooit als keuze/lijst lezen. */
function alsPsp(x: unknown): OmzetPsp | null {
  return x === 'stripe' || x === 'mollie' || x === 'anders' ? x : null
}

function alsTarief(x: unknown): OmzetEtenDrinkenTarief | null {
  return x === 'laag' || x === 'hoog' ? x : null
}

/** De bewerkbare stand uit een DTO: alleen de instelbare sleutels, genormaliseerd. */
export function waardenUit(dto: OmzetBronInstellingenDto): Waarden {
  return {
    product_categorieen: { ...(dto.product_categorieen ?? {}) },
    tegenrekeningen: { ...(dto.tegenrekeningen ?? {}) },
    categorie_btw: Object.fromEntries(
      Object.entries(dto.categorie_btw ?? {}).flatMap(([k, v]) => {
        const sleutel = categorieSleutel(k)
        return sleutel ? [[sleutel, v] as const] : []
      }),
    ),
    combi_regel: dto.combi_regel ?? COMBI_REGEL,
    psp: alsPsp(dto.psp),
    psp_kosten_ledger_id: dto.psp_kosten_ledger_id ?? null,
    eten_drinken_tarief: alsTarief(dto.eten_drinken_tarief),
  }
}

/** Herstel standaard: alles wat de code zelf kan afleiden leeg (stores staan sinds 0151 niet meer in dit blok). */
export function standaardWaarden(_huidig: Waarden): Waarden {
  return {
    product_categorieen: {},
    tegenrekeningen: {},
    categorie_btw: {},
    combi_regel: COMBI_REGEL,
    psp: null,
    psp_kosten_ledger_id: null,
    eten_drinken_tarief: null,
  }
}

function foutTekst(err: unknown): string {
  if (err instanceof ApiError) return err.message
  return 'Opslaan mislukt — probeer het opnieuw.'
}

/** Pydantic-422 mét `loc` → per sectie; anders één blokfout. Sectie-sleutels = de DTO-sleutels. */
function foutenPerVeld(err: unknown): Record<string, string> {
  if (!(err instanceof ApiError)) return { _blok: foutTekst(err) }
  const detail = err.detail
  if (Array.isArray(detail)) {
    const uit: Record<string, string> = {}
    for (const item of detail as { loc?: unknown[]; msg?: string }[]) {
      const loc = Array.isArray(item.loc) ? item.loc.map(String) : []
      const veld = loc.find((x) => x !== 'body') ?? '_blok'
      uit[veld] = uit[veld] ? `${uit[veld]}; ${item.msg ?? ''}` : (item.msg ?? err.message)
    }
    return uit
  }
  if (typeof detail === 'string') {
    // Een leesbare 422/409 uit de service noemt vaak de sleutel ("… in tegenrekeningen …") — dan bij dat veld.
    const veld = ['tegenrekeningen', 'categorie_btw', 'product_categorieen', 'psp_kosten_ledger_id', 'psp', 'eten_drinken_tarief'].find((k) =>
      detail.toLowerCase().includes(k),
    )
    return { [veld ?? '_blok']: detail }
  }
  return { _blok: err.message }
}

export function StandaardChip({ tekst = 'standaard (op naam)' }: { tekst?: string }) {
  return <span className="chip geheugen">{tekst}</span>
}

function Veldfout({ tekst }: { tekst?: string }) {
  if (!tekst) return null
  return (
    <div className="fout" role="alert" style={{ marginTop: 4 }}>
      {tekst}
    </div>
  )
}

/** Blok G ProfX (Peter 16-09): profiel "Winkel / kassa" bovenaan het Omzetbronnen-blok — afgeleid (≥ 1 kassarapport) of
 * Beheerder-override; het profiel bundelt de instellingen hieronder en toont een chip + filter in de administratielijst.
 * Een label alleen doet niets; daarom staat het bij de instellingen die het zet. */
function KassaProfielRegel({ administratieId, uitgeschakeld }: { administratieId: string; uitgeschakeld: boolean }) {
  const [stand, setStand] = useState<KassaProfielStandDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  useEffect(() => {
    let actief = true
    haalKassaProfielOp(administratieId)
      .then((s) => {
        if (actief) setStand(s)
      })
      .catch((err: unknown) => {
        if (actief) setFout(err instanceof Error ? err.message : 'Profiel laden mislukt.')
      })
    return () => {
      actief = false
    }
  }, [administratieId])
  const zet = async (waarde: boolean | null) => {
    setBezig(true)
    setFout(null)
    try {
      setStand(await zetKassaProfiel(administratieId, waarde))
    } catch (err) {
      setFout(err instanceof Error ? err.message : 'Profiel wijzigen mislukt.')
    } finally {
      setBezig(false)
    }
  }
  if (fout) {
    return (
      <div className="hint" role="status" data-testid="kassa-profiel">
        Profiel Winkel / kassa: {fout}
      </div>
    )
  }
  if (!stand) return <div className="hint" data-testid="kassa-profiel">Profiel Winkel / kassa laden…</div>
  const uit = uitgeschakeld || bezig
  return (
    <div
      data-testid="kassa-profiel"
      style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8, fontSize: 12.5 }}
    >
      <span>Profiel</span>
      <span className={`chip ${stand.kassa_profiel ? 'klaar' : ''}`} title="Bundelt kassarapport-bronnen, kostprijs, tegenzijde per betaalwijze en de categorie-mapping">
        Winkel / kassa {stand.kassa_profiel ? 'aan' : 'uit'}
      </span>
      <span className="hint" style={{ margin: 0 }}>
        {stand.bron === 'override'
          ? 'door de Beheerder gezet'
          : stand.kassa_profiel
            ? 'afgeleid: deze administratie heeft een herkend kassarapport'
            : 'afgeleid: nog geen kassarapport gezien'}
      </span>
      {stand.kassa_profiel ? (
        <button type="button" className="linkbtn" disabled={uit} onClick={() => void zet(false)}>
          Uitzetten
        </button>
      ) : (
        <button type="button" className="linkbtn" disabled={uit} onClick={() => void zet(true)}>
          Aanzetten
        </button>
      )}
      {stand.bron === 'override' && (
        <button type="button" className="linkbtn" disabled={uit} onClick={() => void zet(null)}>
          Terug naar afgeleid
        </button>
      )}
    </div>
  )
}

export function OmzetBronnenBlok({
  administratieId,
  naam,
  uitgeschakeld = false,
}: {
  administratieId: string
  naam: string
  uitgeschakeld?: boolean
}) {
  const [dto, setDto] = useState<OmzetBronInstellingenDto | null>(null)
  const [stand, setStand] = useState<Waarden | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const [fouten, setFouten] = useState<Record<string, string>>({})
  const [opgeslagen, setOpgeslagen] = useState(false)
  const [nieuwProduct, setNieuwProduct] = useState('')
  const [nieuwCategorie, setNieuwCategorie] = useState('')

  const laad = useCallback(async () => {
    setLaadFout(null)
    try {
      const d = await haalOmzetBronInstellingenOp(administratieId)
      setDto(d)
      setStand(waardenUit(d))
    } catch (err) {
      setDto(null)
      setStand(null)
      setLaadFout(err instanceof ApiError ? err.message : 'Omzetbronnen niet beschikbaar.')
    }
  }, [administratieId])

  useEffect(() => {
    void laad()
  }, [laad])

  const defaults: OmzetBronDefaultsDto = dto?.defaults ?? {}
  const rekeningOpties = useMemo<ComboboxOptie[]>(
    () => alsLijst(dto?.rekeningen).map((r) => ({ id: r.ledger_id, code: r.code ?? undefined, label: r.naam ?? r.ledger_id })),
    [dto],
  )
  const tariefOpties = useMemo<ComboboxOptie[]>(
    () =>
      alsLijst(dto?.tarieven).map((t) => {
        const pct = t.percentage === null || t.percentage === undefined ? null : Math.round(Number(t.percentage) * 100)
        return { id: t.taxrate_id, code: pct === null || Number.isNaN(pct) ? undefined : `${pct}%`, label: t.naam ?? t.taxrate_id }
      }),
    [dto],
  )

  /** Categorie-SLEUTELS: expliciete lijst uit de DTO ∪ sleutels van categorie_btw (mens + default) ∪ mapping-waarden
   * (genormaliseerd). De btw-tabel is per sleutel; de productmapping houdt de leesbare categorienaam. */
  const categorieen = useMemo(() => {
    const set = new Set<string>()
    const voeg = (c: string | null | undefined) => {
      const k = categorieSleutel(c)
      if (k) set.add(k)
    }
    for (const c of alsLijst(dto?.categorieen)) voeg(c)
    for (const c of Object.keys(defaults.categorie_btw ?? {})) voeg(c)
    for (const c of Object.keys(stand?.categorie_btw ?? {})) voeg(c)
    for (const c of Object.values(defaults.product_categorieen ?? {})) voeg(c)
    for (const c of Object.values(stand?.product_categorieen ?? {})) voeg(c)
    return [...set].sort((a, b) => a.localeCompare(b, 'nl'))
  }, [dto, defaults, stand])

  const gewijzigd = useMemo(() => {
    if (!dto || !stand) return false
    return JSON.stringify(stand) !== JSON.stringify(waardenUit(dto))
  }, [dto, stand])

  const wijzig = (patch: Partial<Waarden>) => {
    setOpgeslagen(false)
    setStand((s) => (s ? { ...s, ...patch } : s))
  }

  const opslaan = async () => {
    if (!stand) return
    setBezig(true)
    setFouten({})
    setOpgeslagen(false)
    try {
      const d = await zetOmzetBronInstellingen(administratieId, stand)
      setDto(d)
      setStand(waardenUit(d))
      setOpgeslagen(true)
    } catch (err) {
      setFouten(foutenPerVeld(err))
    } finally {
      setBezig(false)
    }
  }

  const productToevoegen = () => {
    const p = nieuwProduct.trim().toLowerCase()
    const c = nieuwCategorie.trim()
    if (!p || !c || !stand) return
    setFouten({})
    wijzig({ product_categorieen: { ...(stand.product_categorieen ?? {}), [p]: c } })
    setNieuwProduct('')
    setNieuwCategorie('')
  }

  const uit = uitgeschakeld || bezig || !stand

  if (laadFout) {
    return (
      <div className="panel" id="omzetbronnen" data-testid="omzetbronnen-blok" style={{ padding: 12 }}>
        <h3 style={{ marginTop: 0 }}>Omzetbronnen</h3>
        <div className="fout" role="alert">
          {laadFout}
        </div>
      </div>
    )
  }

  const tegen = stand?.tegenrekeningen ?? {}
  const tegenDefaults = defaults.tegenrekeningen ?? {}
  const btw = stand?.categorie_btw ?? {}
  const mapping = stand?.product_categorieen ?? {}
  const mappingDefaults = defaults.product_categorieen ?? {}
  const mappingRijen = [...new Set([...Object.keys(mappingDefaults), ...Object.keys(mapping)])].sort((a, b) => a.localeCompare(b, 'nl'))
  // De GET levert psp/eten_drinken_tarief altijd ingevuld (default gemerged; een keuze gelijk aan de default wordt niet
  // opgeslagen) — "gekozen" is dus: afwijkend van de code-default.
  const pspDefault = alsPsp(defaults.psp) ?? CODE_DEFAULT_PSP
  const etenDefault = alsTarief(defaults.eten_drinken_tarief) ?? CODE_DEFAULT_ETEN
  const pspEffectief = stand?.psp ?? pspDefault
  const etenEffectief = stand?.eten_drinken_tarief ?? etenDefault
  const pspGekozen = Boolean(stand?.psp) && stand?.psp !== pspDefault
  const etenGekozen = Boolean(stand?.eten_drinken_tarief) && stand?.eten_drinken_tarief !== etenDefault

  return (
    <div className="panel" id="omzetbronnen" data-testid="omzetbronnen-blok" style={{ padding: 12 }}>
      <h3 style={{ marginTop: 0 }}>Omzetbronnen</h3>
      <KassaProfielRegel administratieId={administratieId} uitgeschakeld={uitgeschakeld} />
      <div className="hint" style={{ marginTop: 0 }}>
        Dagstaten (zonnestudio) en betalingsexports (pilates) van {naam}: welke store hier hoort, op welke tegenrekening de
        omzet per betaalwijze landt (de bank lettert daarna af), en hoe producten naar categorie en btw gaan. Leeg = de code
        kiest zelf op naam uit het Reeleezee-rekeningschema (chip “standaard”). Wijzigingen gelden vanaf de volgende
        dagstaat/batch, nooit met terugwerkende kracht.
      </div>
      <Veldfout tekst={fouten._blok} />

      {/* (a) Stores — afgeleid uit de platformbrede routering (0151); beheren op Instellingen › Boeken › Stores. */}
      <h4 className="inst-rij-titel" style={{ marginTop: 12 }}>
        Stores (“Store Used” in de dagstaat) — stores die hier landen
      </h4>
      {(dto?.stores ?? []).length === 0 ? (
        <p className="hint" data-testid="stores-leeg">
          Nog geen store landt in deze administratie. Stores koppel je platformbreed:{' '}
          <Link to="/instellingen/boeken#stores" className="linkbtn">
            Instellingen › Boeken › Stores →
          </Link>
        </p>
      ) : (
        <p className="hint" data-testid="stores-afgeleid" style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
          {(dto?.stores ?? []).map((s) => (
            <span key={s} className="chip klaar">
              {s}
            </span>
          ))}
          <Link to="/instellingen/boeken#stores" className="linkbtn">
            Beheren op Instellingen › Boeken › Stores →
          </Link>
        </p>
      )}

      {/* (b) Tegenrekening per betaalwijze */}
      <h4 className="inst-rij-titel" style={{ marginTop: 16 }}>
        Tegenrekening per betaalwijze
      </h4>
      <div className="tabel-scroll">
        <table style={{ width: 'auto', minWidth: 560 }} aria-label="Tegenrekeningen per betaalwijze">
          <thead>
            <tr>
              <th style={{ minWidth: 140 }}>Betaalwijze</th>
              <th style={{ minWidth: 260 }}>Tegenrekening</th>
              <th style={{ minWidth: 150 }}>Herkomst</th>
            </tr>
          </thead>
          <tbody>
            {BETAALWIJZEN.map((b) => {
              const gekozen = tegen[b.sleutel] ?? null
              const def = tegenDefaults[b.sleutel] ?? null
              const effectief = gekozen ?? def
              return (
                <tr key={b.sleutel}>
                  <td>
                    <b>{b.label}</b>
                    <div className="hint" style={{ marginTop: 0 }}>
                      {b.uitleg}
                    </div>
                  </td>
                  <td>
                    <SearchableCombobox
                      label={`Tegenrekening ${b.label}`}
                      toonLabel={false}
                      opties={rekeningOpties}
                      waarde={effectief}
                      placeholder={def ? undefined : 'geen rekening op naam gevonden — kies er één'}
                      fout={Boolean(fouten.tegenrekeningen) || (!effectief && rekeningOpties.length > 0)}
                      onWijzig={(id) => wijzig({ tegenrekeningen: { ...tegen, [b.sleutel]: id } })}
                    />
                  </td>
                  <td>
                    {gekozen ? (
                      <>
                        <span className="chip handmatig">gekozen</span>{' '}
                        <button type="button" className="linkbtn" disabled={uit} onClick={() => wijzig({ tegenrekeningen: { ...tegen, [b.sleutel]: null } })}>
                          standaard
                        </button>
                      </>
                    ) : def ? (
                      <StandaardChip />
                    ) : (
                      <span className="chip afwijking">geen standaard</span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <Veldfout tekst={fouten.tegenrekeningen} />

      {/* (c) Categorie-mapping pilates + btw per categorie */}
      <h4 className="inst-rij-titel" style={{ marginTop: 16 }}>
        Categorieën en btw
      </h4>
      <div className="tabel-scroll">
        <table style={{ width: 'auto', minWidth: 520 }} aria-label="Btw-tarief per categorie">
          <thead>
            <tr>
              <th style={{ minWidth: 180 }}>Categorie</th>
              <th style={{ minWidth: 220 }}>Btw-tarief</th>
              <th style={{ minWidth: 120 }}>Herkomst</th>
            </tr>
          </thead>
          <tbody>
            {categorieen.length === 0 && (
              <tr>
                <td colSpan={3} className="hint">
                  Nog geen categorieën — die komen mee met de eerste batch of via de productmapping hieronder.
                </td>
              </tr>
            )}
            {categorieen.map((c) => {
              const gekozen = btw[c] ?? null
              const { taxrate_id: def, klasse } = defaultTaxrate(defaults, c)
              return (
                <tr key={c}>
                  <td>
                    {c}
                    {klasse && (
                      <div className="hint" style={{ marginTop: 0 }}>
                        klasse {klasse}
                      </div>
                    )}
                  </td>
                  <td>
                    <SearchableCombobox
                      label={`Btw-tarief ${c}`}
                      toonLabel={false}
                      opties={tariefOpties}
                      waarde={gekozen ?? def}
                      placeholder={def ? undefined : 'geen default — kies een tarief'}
                      fout={Boolean(fouten.categorie_btw)}
                      onWijzig={(id) => wijzig({ categorie_btw: { ...btw, [c]: id } })}
                    />
                  </td>
                  <td>
                    {gekozen ? (
                      <>
                        <span className="chip handmatig">gekozen</span>{' '}
                        <button type="button" className="linkbtn" disabled={uit} onClick={() => wijzig({ categorie_btw: { ...btw, [c]: null } })}>
                          standaard
                        </button>
                      </>
                    ) : def ? (
                      <StandaardChip tekst="standaard (RLZ-tarief)" />
                    ) : (
                      <span className="chip afwijking">geen standaard</span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <Veldfout tekst={fouten.categorie_btw} />

      <div className="hint">
        Productnaam (pilates-export) → categorie. Standaardregels komen uit de code; een eigen regel wint. Onbekende
        producten blijven een blokkerende check op het controlescherm.
      </div>
      <div className="tabel-scroll">
        <table style={{ width: 'auto', minWidth: 520 }} aria-label="Productmapping">
          <thead>
            <tr>
              <th style={{ minWidth: 220 }}>Product</th>
              <th style={{ minWidth: 180 }}>Categorie</th>
              <th style={{ minWidth: 120 }}>Herkomst</th>
            </tr>
          </thead>
          <tbody>
            {mappingRijen.length === 0 && (
              <tr>
                <td colSpan={3} className="hint">
                  Nog geen productmapping.
                </td>
              </tr>
            )}
            {mappingRijen.map((p) => {
              const eigen = mapping[p]
              const def = mappingDefaults[p]
              return (
                <tr key={p}>
                  <td>{p}</td>
                  <td>{eigen ?? def}</td>
                  <td style={{ whiteSpace: 'nowrap' }}>
                    {eigen ? (
                      <>
                        <span className="chip handmatig">eigen regel</span>{' '}
                        <button
                          type="button"
                          className="linkbtn"
                          aria-label={`Verwijder mapping ${p}`}
                          disabled={uit}
                          onClick={() => {
                            const rest = { ...mapping }
                            delete rest[p]
                            wijzig({ product_categorieen: rest })
                          }}
                        >
                          {def ? 'standaard' : 'verwijderen'}
                        </button>
                      </>
                    ) : (
                      <StandaardChip tekst="standaard" />
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <form
        style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginTop: 6 }}
        onSubmit={(e) => {
          e.preventDefault()
          productToevoegen()
        }}
      >
        <input
          aria-label="Productnaam"
          placeholder="productnaam, bv. 10 rittenkaart"
          value={nieuwProduct}
          disabled={uit}
          style={{ width: 220 }}
          onChange={(e) => setNieuwProduct(e.target.value)}
        />
        <input
          aria-label="Categorie voor product"
          placeholder="categorie"
          list="omzetbronnen-categorieen"
          value={nieuwCategorie}
          disabled={uit}
          style={{ width: 180 }}
          onChange={(e) => setNieuwCategorie(e.target.value)}
        />
        <datalist id="omzetbronnen-categorieen">
          {[...new Set([...Object.values(mappingDefaults), ...Object.values(mapping)])].sort().map((c) => (
            <option key={c} value={c} />
          ))}
        </datalist>
        <Button type="submit" variant="secundair" maat="klein" disabled={uit || !nieuwProduct.trim() || !nieuwCategorie.trim()}>
          + Productregel
        </Button>
      </form>
      <Veldfout tekst={fouten.product_categorieen} />

      {/* (d) Combi-regel */}
      <h4 className="inst-rij-titel" style={{ marginTop: 16 }}>
        Combi-abonnement
      </h4>
      <p className="hint" style={{ marginTop: 0 }} data-testid="combi-regel">
        <span className="chip klaar">pro rato binnen de batch</span> “combi Abonnement” wordt over Pilates en Yoga verdeeld
        naar de netto-omzet van diezelfde categorieën in dezelfde uitbetalingsbatch; zonder basis in de batch de laatste 30
        dagen; nog geen basis → 50/50 mét oranje signaal. Cent-exact sluitend, restcent op de grootste. De verdeling staat
        per batch in het blok “Bron” van het controlescherm.
      </p>

      {/* (e) PSP */}
      <h4 className="inst-rij-titel" style={{ marginTop: 16 }}>
        Betaalprovider en tarieven
      </h4>
      <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'minmax(0, 1fr)' }}>
        <label className="inst-switch-label" style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          Betaalprovider
          <Select
            aria-label={`Betaalprovider voor ${naam}`}
            value={pspEffectief}
            disabled={uit}
            style={{ maxWidth: 360 }}
            onChange={(e) => wijzig({ psp: alsPsp(e.target.value) })}
          >
            {PSP_OPTIES.map((o) => (
              <option key={o.waarde} value={o.waarde}>
                {o.label}
              </option>
            ))}
          </Select>
          {pspGekozen ? <span className="chip handmatig">gekozen</span> : <StandaardChip tekst="standaard" />}
          {defaults.psp_btw_herkomst && <span className="hint" style={{ marginTop: 0 }}>{defaults.psp_btw_herkomst}</span>}
        </label>
        <Veldfout tekst={fouten.psp} />
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <span>Kostenrekening PSP</span>
          <div style={{ minWidth: 280 }}>
            <SearchableCombobox
              label="Kostenrekening PSP"
              toonLabel={false}
              opties={rekeningOpties}
              waarde={stand?.psp_kosten_ledger_id ?? defaults.psp_kosten_ledger_id ?? null}
              placeholder={defaults.psp_kosten_ledger_id ? undefined : 'geen rekening “transactiekosten/bankkosten” gevonden'}
              fout={Boolean(fouten.psp_kosten_ledger_id)}
              onWijzig={(id) => wijzig({ psp_kosten_ledger_id: id })}
            />
          </div>
          {stand?.psp_kosten_ledger_id ? (
            <>
              <span className="chip handmatig">gekozen</span>
              <button type="button" className="linkbtn" disabled={uit} onClick={() => wijzig({ psp_kosten_ledger_id: null })}>
                standaard
              </button>
            </>
          ) : defaults.psp_kosten_ledger_id ? (
            <StandaardChip />
          ) : (
            <span className="chip afwijking">geen standaard</span>
          )}
        </div>
        <Veldfout tekst={fouten.psp_kosten_ledger_id} />
        <label className="inst-switch-label" style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          Eten/drinken
          <Select
            aria-label={`Btw eten/drinken voor ${naam}`}
            value={etenEffectief}
            disabled={uit}
            style={{ maxWidth: 260 }}
            onChange={(e) => wijzig({ eten_drinken_tarief: alsTarief(e.target.value) })}
          >
            <option value="laag">laag tarief (9 %)</option>
            <option value="hoog">hoog tarief (21 % — alcohol/horeca)</option>
          </Select>
          {etenGekozen ? <span className="chip handmatig">gekozen</span> : <StandaardChip tekst="standaard" />}
        </label>
        <Veldfout tekst={fouten.eten_drinken_tarief} />
      </div>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 14 }}>
        <Button maat="klein" disabled={uit || !gewijzigd} onClick={() => void opslaan()}>
          {bezig ? 'Bezig…' : 'Opslaan'}
        </Button>
        {opgeslagen && Object.keys(fouten).length === 0 && <span className="text-[12px] text-ok">opgeslagen</span>}
        {gewijzigd && !bezig && <span className="text-[12px] text-muted">niet opgeslagen wijzigingen</span>}
        <GebruikerRijMenu
          naam={`omzetbronnen van ${naam}`}
          items={[
            {
              label: 'Herstel standaard (tegenrekeningen, btw, mapping, PSP)',
              disabled: uit,
              onClick: () => stand && wijzig(standaardWaarden(stand)),
            },
            { label: 'Opnieuw laden', disabled: bezig, onClick: () => void laad() },
          ]}
        />
      </div>
    </div>
  )
}
