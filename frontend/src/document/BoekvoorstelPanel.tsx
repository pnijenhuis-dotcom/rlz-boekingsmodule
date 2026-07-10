import { useEffect, useMemo, useState } from 'react'
import { ApiError, apiFetch, apiJson, apiPostJson } from '../api/client'
import type {
  BoekenResponseDto,
  BoekvoorstelDto,
  BoekvoorstelMetChecksDto,
  BoekvoorstelRegelDto,
  CheckRapportDto,
  DocumentActieResponseDto,
  VendorOptieDto,
} from '../api/types'
import { alsAiVoorstel, zekerheidPct, type AiVoorstel } from './aiVoorstel'
import { bedragAlsGetal, berekenBtwBedrag, normaliseerBedrag } from './bedrag'
import { crediteurSuggesties } from './crediteurSuggesties'
import { SearchableCombobox, type ComboboxOptie } from './SearchableCombobox'
import {
  synchroniseerAlleCaches,
  useGrootboekOpties,
  useProjectOpties,
  useProjectVerplicht,
  useTaxrateOpties,
  useVendorOpties,
} from './useSyncOpties'

/** Statische weergave van een gekozen optie (design-pass: read-only bij geboekt/verwijderd) —
 * zelfde code+omschrijving-vorm als de combobox zelf toont, alleen niet interactief. */
function optieWeergave(opties: ComboboxOptie[], id: string | null): string {
  if (!id) return '—'
  const optie = opties.find((o) => o.id === id)
  if (!optie) return id
  return optie.code ? `${optie.code} · ${optie.label}` : optie.label
}

interface StatischVeldProps {
  label: string
  waarde: string
}

/** Read-only equivalent van een invoerveld — géén disabled <input> (dat suggereert nog steeds
 * dat er iets bewerkbaar is), gewoon platte tekst op dezelfde plek in de layout. */
function StatischVeld({ label, waarde }: StatischVeldProps) {
  return (
    <div>
      <label>{label}</label>
      <p style={{ margin: 0, padding: '8px 0', fontSize: 13 }}>{waarde || '—'}</p>
    </div>
  )
}

interface RegelState {
  key: string
  ledgerId: string | null
  taxrateId: string | null
  projectId: string | null
  netto: string
  btw: string
  /** Design-pass taak 3: zodra de gebruiker zelf iets in het btw-veld typt, stopt de automatische
   * afleiding (netto x taxrate-percentage) met dat veld te overschrijven — "overschrijfbaar", dus
   * één keer aangeraakt blijft het van de gebruiker. Een geladen regel met een al opgeslagen
   * btw-bedrag telt ook als "handmatig" (kan een eerdere handmatige invoer zijn geweest). */
  btwHandmatig: boolean
  omschrijving: string
  /** Laagste AI-zekerheidsscore van de vooringevulde regelvelden (alleen bij een vers, nog niet
   * opgeslagen AI-voorstel). Elke handmatige wijziging aan de regel wist de score — dan beschrijft
   * hij de inhoud niet meer. */
  aiZekerheid: number | null
}

function nieuweRegel(): RegelState {
  return {
    key: crypto.randomUUID(),
    ledgerId: null,
    taxrateId: null,
    projectId: null,
    netto: '',
    btw: '',
    btwHandmatig: false,
    omschrijving: '',
    aiZekerheid: null,
  }
}

function regelUitDtoRegel(r: BoekvoorstelRegelDto, aiZekerheid: number | null = null): RegelState {
  return {
    key: crypto.randomUUID(),
    ledgerId: r.ledger_id,
    taxrateId: r.taxrate_id,
    projectId: r.project_id,
    netto: r.netto_bedrag ?? '',
    btw: r.btw_bedrag ?? '',
    btwHandmatig: Boolean(r.btw_bedrag),
    omschrijving: r.omschrijving ?? '',
    aiZekerheid,
  }
}

function regelsUitDto(dto: BoekvoorstelDto, ai: AiVoorstel | null): RegelState[] {
  if (dto.regels.length === 0) return [nieuweRegel()]
  // Sinds het compacte schema (2026-07-10) levert de AI één zekerheidsscore per regel.
  const aiScores =
    ai && ai.regels.length === dto.regels.length
      ? dto.regels.map((_, i) => ai.regel_zekerheid[i] ?? null)
      : null
  return dto.regels.map((r, i) => regelUitDtoRegel(r, aiScores ? aiScores[i] : null))
}

/** Fix 3: de per-regel-variant rechtstreeks uit het AI-veldvoorstel — nodig als het voorstel in
 * samengevoegde vorm is opgeslagen (dto.regels is dan de ene samengevoegde regel) en de
 * controleur alsnog wil splitsen. De AI blijft altijd alle regels extraheren; deze prefill is
 * daardoor altijd beschikbaar zolang er een AI-voorstel is. */
function regelsUitAi(ai: AiVoorstel): RegelState[] {
  if (ai.regels.length === 0) return [nieuweRegel()]
  return ai.regels.map((r, i) => ({
    key: crypto.randomUUID(),
    ledgerId: null,
    taxrateId: r.taxrate_id,
    projectId: null,
    netto: r.netto_bedrag ?? '',
    btw: r.btw_bedrag ?? '',
    btwHandmatig: Boolean(r.btw_bedrag),
    omschrijving: r.omschrijving ?? '',
    aiZekerheid: ai.regel_zekerheid[i] ?? null,
  }))
}

function formatEuro(bedrag: number): string {
  return bedrag.toLocaleString('nl-NL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

interface LegeCacheBannerProps {
  naam: string
  bezig: boolean
  onSynchroniseren: () => void
}

/** Design-pass taak 3: duidelijke melding + herstelactie i.p.v. een blijkbaar-lege combobox
 * zonder verklaring. "Nu synchroniseren" verversen ALLE vier de caches (grootboek/btw/crediteuren/
 * projecten) tegelijk — een controleur die deze banner ziet, wil de hele administratie bijwerken. */
function LegeCacheBanner({ naam, bezig, onSynchroniseren }: LegeCacheBannerProps) {
  return (
    <div
      style={{
        background: 'var(--orange-bg)',
        color: 'var(--orange)',
        borderRadius: 8,
        padding: '9px 12px',
        fontSize: 12.5,
        marginBottom: 10,
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        flexWrap: 'wrap',
      }}
    >
      <span>Deze administratie is nog niet gesynchroniseerd voor {naam}.</span>
      <button type="button" className="btn secondary" disabled={bezig} onClick={onSynchroniseren}>
        {bezig ? 'Bezig…' : 'Nu synchroniseren'}
      </button>
    </div>
  )
}

interface AiChipProps {
  score: number
  drempel: number
  fuzzy?: boolean
}

/** Zekerheidsscore van de AI-extractie bij een vooringevuld veld: oranje onder de drempel of bij
 * een fuzzy crediteur-match ("bij twijfel oranje, nooit gokken"), anders groen. Verdwijnt zodra
 * de controleur het veld aanpast — de score beschrijft dan de inhoud niet meer. */
function AiChip({ score, drempel, fuzzy = false }: AiChipProps) {
  const laag = fuzzy || score < drempel
  return (
    <span
      className={`chip ${laag ? 'afwijking' : 'ok'}`}
      title={fuzzy ? 'Crediteur benaderd op naam (fuzzy match tegen de crediteuren-cache) — controleer de keuze.' : 'Zekerheid van de AI-extractie voor dit veld.'}
    >
      AI {zekerheidPct(score)}
      {fuzzy ? ' · naam benaderd' : ''}
    </span>
  )
}

interface Props {
  administratieId: string
  documentId: string
  status: string
  veldvoorstel?: Record<string, unknown> | null
  onGeboekt: () => void
  onHersteld: () => void
}

/** Controlescherm-uitbreiding (CLAUDE.md-taak 2.1, design-pass): kopgegevens + boekingsregels met
 * zoekbare GB-/btw-/project-comboboxen, harde checks zichtbaar (groen/blokkerend), live
 * aansluit-indicator, en de echte boekactie. */
export function BoekvoorstelPanel({ administratieId, documentId, status, veldvoorstel, onGeboekt, onHersteld }: Props) {
  const ai = useMemo(() => alsAiVoorstel(veldvoorstel), [veldvoorstel])
  // Chips alleen bij een vers (nog niet opgeslagen) AI-voorstel — na opslaan is de invoer van de
  // controleur, niet meer van de AI.
  const [aiChipsActief, setAiChipsActief] = useState(false)
  const [cacheVersie, setCacheVersie] = useState(0)
  const { opties: grootboekOpties, fout: grootboekFout, laden: grootboekLaden } = useGrootboekOpties(administratieId, cacheVersie)
  const { opties: taxrateOpties, fout: taxrateFout, laden: taxrateLaden } = useTaxrateOpties(administratieId, cacheVersie)
  const percentageMap = useMemo(() => {
    const map: Record<string, number> = {}
    for (const optie of taxrateOpties) if (optie.percentage !== undefined) map[optie.id] = optie.percentage
    return map
  }, [taxrateOpties])
  const { opties: vendorOpties, fout: vendorFout, laden: vendorLaden } = useVendorOpties(administratieId, cacheVersie)
  const { opties: projectOpties, laden: projectLaden } = useProjectOpties(administratieId, cacheVersie)
  const projectVerplicht = useProjectVerplicht(administratieId)

  const [synchroniserenBezig, setSynchroniserenBezig] = useState(false)
  const [synchroniserenFout, setSynchroniserenFout] = useState<string | null>(null)

  const [laden, setLaden] = useState(true)
  const [ladenFout, setLadenFout] = useState<string | null>(null)
  const [vendorId, setVendorId] = useState<string | null>(null)
  const [referentie, setReferentie] = useState('')
  const [factuurdatum, setFactuurdatum] = useState('')
  const [totaalbedrag, setTotaalbedrag] = useState('')
  const [regels, setRegels] = useState<RegelState[]>([nieuweRegel()])
  const [boekstuknummer, setBoekstuknummer] = useState<string | null>(null)

  // Fix 3: standaard één samengevoegde boekingsregel, vinkje "splitsen per regel" — keuze wordt
  // per (administratie, crediteur) onthouden (backend LeverancierVoorkeur). De inactieve modus
  // bewaart zijn eigen regels zodat heen-en-weer schakelen geen invoer weggooit. Bij projectplicht
  // is samenvoegen hard uitgesloten (samenvoegen_toegestaan=false van de backend).
  const [regelsSamenvoegen, setRegelsSamenvoegen] = useState(true)
  const [samenvoegenToegestaan, setSamenvoegenToegestaan] = useState(true)
  const [samenvoegenBeschikbaar, setSamenvoegenBeschikbaar] = useState(false)
  const [inactieveRegels, setInactieveRegels] = useState<RegelState[]>([])

  // Fix 2: "nieuwe crediteur aanmaken in RLZ" vanaf het voorstelblok onder het crediteur-veld.
  const [crediteurAanmakenBezig, setCrediteurAanmakenBezig] = useState(false)
  const [crediteurAanmakenFout, setCrediteurAanmakenFout] = useState<string | null>(null)

  const [checkRapport, setCheckRapport] = useState<CheckRapportDto | null>(null)
  // Design-pass taak 7: elke veldwijziging maakt het laatste checkresultaat ongeldig voor de
  // ACTUELE invoer — de knop "Boeken" mag dan niet meer aan staan, ook al was het vorige resultaat
  // groen. De rijen blijven zichtbaar (context), maar duidelijk gemarkeerd als verouderd.
  const [checksActueel, setChecksActueel] = useState(false)
  const [controlerenBezig, setControlerenBezig] = useState(false)
  const [controlerenFout, setControlerenFout] = useState<string | null>(null)
  const [boekenBezig, setBoekenBezig] = useState(false)
  const [boekenFout, setBoekenFout] = useState<string | null>(null)
  const [boekResultaat, setBoekResultaat] = useState<BoekenResponseDto | null>(null)
  const [herstellenBezig, setHerstellenBezig] = useState(false)
  const [herstellenFout, setHerstellenFout] = useState<string | null>(null)

  useEffect(() => {
    let actief = true
    setLaden(true)
    setLadenFout(null)
    apiJson<BoekvoorstelDto>(`/administraties/${administratieId}/documenten/${documentId}/boekvoorstel`)
      .then((dto) => {
        if (!actief) return
        const aiPrefill = !dto.opgeslagen && ai !== null
        setAiChipsActief(aiPrefill)
        setVendorId(dto.vendor_id)
        setReferentie(dto.referentie ?? '')
        setFactuurdatum(dto.factuurdatum ?? '')
        setTotaalbedrag(dto.totaalbedrag ?? '')
        setBoekstuknummer(dto.rlz_boekstuknummer)

        // Fix 3: bepaal de gesplitste én de samengevoegde variant, en welke actief start.
        const opgeslagenSamengevoegd = dto.opgeslagen && dto.regels_samenvoegen && dto.samenvoegen_toegestaan
        const gesplitst = opgeslagenSamengevoegd
          ? ai !== null
            ? regelsUitAi(ai) // dto.regels is hier de opgeslagen samengevoegde regel — splitsen prefillt uit het AI-voorstel
            : [nieuweRegel()]
          : regelsUitDto(dto, aiPrefill ? ai : null)
        const samengevoegd = opgeslagenSamengevoegd
          ? regelsUitDto(dto, null)
          : dto.samengevoegde_regel
            ? [regelUitDtoRegel(dto.samengevoegde_regel)]
            : null
        // Actieve modus volgt de dto-stand (voorkeur per crediteur, default samengevoegd); het
        // vinkje verschijnt alleen als er echt iets te splitsen valt (meer dan één factuurregel).
        const toegestaan = dto.samenvoegen_toegestaan ?? true
        const samenvoegenActief = toegestaan && Boolean(dto.regels_samenvoegen) && samengevoegd !== null
        setSamenvoegenToegestaan(toegestaan)
        setSamenvoegenBeschikbaar(toegestaan && samengevoegd !== null && gesplitst.length > 1)
        setRegelsSamenvoegen(samenvoegenActief)
        setRegels(samenvoegenActief && samengevoegd !== null ? samengevoegd : gesplitst)
        setInactieveRegels(samenvoegenActief || samengevoegd === null ? gesplitst : samengevoegd)
      })
      .catch((err: unknown) => {
        if (actief) setLadenFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
      .finally(() => {
        if (actief) setLaden(false)
      })
    return () => {
      actief = false
    }
  }, [administratieId, documentId, ai])

  // Kliktest-fix: het boekvoorstel bleek nog bewerkbaar na boeken — de backend blokkeert dit nu
  // hard (app/documenten/boekvoorstel.py::_BEVROREN_STATUSSEN), maar de UI hoort een onmogelijke
  // actie niet eens aan te bieden. isReadOnly geldt voor beide bevroren statussen; alleen bij
  // verwijderd is "herstellen" nog een geldige actie.
  const isGeboekt = status === 'geboekt'
  const isVerwijderd = status === 'verwijderd'
  const isReadOnly = isGeboekt || isVerwijderd

  // Per kopveld: zekerheids-chip zolang de huidige invoer nog gelijk is aan wat de AI voorlas —
  // wijzigt de controleur het veld, dan beschrijft de score de inhoud niet meer en verdwijnt hij.
  const aiKop = useMemo(() => {
    if (!ai || !aiChipsActief || isReadOnly) return null
    const gelijkBedrag = (invoer: string, aiWaarde: string | null) => {
      const a = bedragAlsGetal(invoer)
      const b = aiWaarde !== null ? bedragAlsGetal(aiWaarde) : null
      return a !== null && b !== null && Math.abs(a - b) < 0.005
    }
    return {
      drempel: ai.zekerheid_drempel,
      vendor:
        ai.vendor_suggestie && vendorId === ai.vendor_suggestie.vendor_id
          ? { score: ai.zekerheid.leverancier_naam ?? 0, fuzzy: ai.vendor_suggestie.match === 'fuzzy' }
          : null,
      referentie:
        ai.factuurnummer !== null && referentie.trim() === ai.factuurnummer && ai.zekerheid.factuurnummer !== undefined
          ? { score: ai.zekerheid.factuurnummer }
          : null,
      factuurdatum:
        ai.factuurdatum !== null && factuurdatum === ai.factuurdatum && ai.zekerheid.factuurdatum !== undefined
          ? { score: ai.zekerheid.factuurdatum }
          : null,
      totaalbedrag:
        gelijkBedrag(totaalbedrag, ai.totaal_incl) && ai.zekerheid.totaal_incl !== undefined
          ? { score: ai.zekerheid.totaal_incl }
          : null,
    }
  }, [ai, aiChipsActief, isReadOnly, vendorId, referentie, factuurdatum, totaalbedrag])

  const veranderInvoer = () => setChecksActueel(false)

  const wijzigVendorId = (id: string | null) => {
    setVendorId(id)
    veranderInvoer()
  }
  const wijzigReferentie = (waarde: string) => {
    setReferentie(waarde)
    veranderInvoer()
  }
  const wijzigFactuurdatum = (waarde: string) => {
    setFactuurdatum(waarde)
    veranderInvoer()
  }
  const wijzigTotaalbedrag = (waarde: string) => {
    setTotaalbedrag(waarde)
    veranderInvoer()
  }

  const wijzigRegel = (key: string, veld: keyof RegelState, waarde: string | null) => {
    setRegels((huidig) =>
      huidig.map((r) => {
        if (r.key !== key) return r
        // Elke handmatige wijziging: de AI-zekerheidsscore beschrijft deze regel niet meer.
        const bijgewerkt = { ...r, [veld]: waarde, aiZekerheid: null }
        if (veld === 'btw') {
          // Rechtstreekse invoer in het btw-veld zelf — vanaf nu is dit veld van de gebruiker;
          // leegmaken laat de automatische afleiding weer meedraaien (design-pass taak 3).
          bijgewerkt.btwHandmatig = waarde !== ''
        } else if ((veld === 'netto' || veld === 'taxrateId') && !bijgewerkt.btwHandmatig) {
          // Nog niet handmatig aangeraakt: btw-bedrag blijft live meebewegen met netto/percentage.
          const percentage = bijgewerkt.taxrateId ? percentageMap[bijgewerkt.taxrateId] : undefined
          const netto = bedragAlsGetal(bijgewerkt.netto)
          bijgewerkt.btw = percentage !== undefined && netto !== null ? formatEuro(berekenBtwBedrag(netto, percentage)) : ''
        }
        return bijgewerkt
      }),
    )
    veranderInvoer()
  }

  /** Fix 3: schakelen tussen samengevoegd en per-regel — beide modi bewaren hun eigen regels,
   * dus heen-en-weer schakelen gooit geen invoer weg. De keuze reist mee met de eerstvolgende
   * "Controleren" (PUT) en wordt daar als voorkeur per crediteur onthouden. */
  const wisselSamenvoegen = (samenvoegen: boolean) => {
    if (samenvoegen === regelsSamenvoegen) return
    setRegelsSamenvoegen(samenvoegen)
    setRegels(inactieveRegels)
    setInactieveRegels(regels)
    veranderInvoer()
  }

  const verwijderRegel = (key: string) => {
    setRegels((huidig) => (huidig.length > 1 ? huidig.filter((r) => r.key !== key) : huidig))
    veranderInvoer()
  }

  const voegRegelToe = () => {
    setRegels((r) => [...r, nieuweRegel()])
    veranderInvoer()
  }

  // Fix 2: de AI las een leveranciersnaam, maar het crediteur-veld is (nog) leeg — nooit een
  // leeg verplicht veld zonder handelingsperspectief. Voorstelblok met de gelezen naam +
  // zekerheid, klikbare koppel-suggesties uit de cache, en "nieuwe crediteur aanmaken in RLZ".
  const aiLeverancierNaam = ai?.leverancier_naam?.trim() || null
  const crediteurVoorstellen = useMemo(
    () => (aiLeverancierNaam ? crediteurSuggesties(aiLeverancierNaam, vendorOpties) : []),
    [aiLeverancierNaam, vendorOpties],
  )

  const nieuweCrediteurAanmaken = async () => {
    if (!aiLeverancierNaam) return
    setCrediteurAanmakenBezig(true)
    setCrediteurAanmakenFout(null)
    try {
      const resp = await apiFetch(`/administraties/${administratieId}/crediteuren`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ naam: aiLeverancierNaam }),
      })
      const body: unknown = await resp.json().catch(() => null)
      if (resp.ok) {
        const nieuw = body as VendorOptieDto
        setCacheVersie((v) => v + 1)
        wijzigVendorId(nieuw.id)
        return
      }
      // 409 = bestond al (bv. net gesynchroniseerd): de backend stuurt de bestaande vendor_id
      // mee — die selecteren is voor de controleur hetzelfde eindresultaat.
      const detail = body && typeof body === 'object' ? (body as { detail?: unknown }).detail : null
      if (resp.status === 409 && detail && typeof detail === 'object' && 'vendor_id' in detail) {
        setCacheVersie((v) => v + 1)
        wijzigVendorId(String((detail as { vendor_id: unknown }).vendor_id))
        return
      }
      const melding =
        typeof detail === 'string'
          ? detail
          : detail && typeof detail === 'object' && 'message' in detail
            ? String((detail as { message: unknown }).message)
            : resp.statusText || `Fout (${resp.status})`
      setCrediteurAanmakenFout(melding)
    } catch (err) {
      setCrediteurAanmakenFout(err instanceof ApiError ? err.message : 'Crediteur aanmaken mislukt.')
    } finally {
      setCrediteurAanmakenBezig(false)
    }
  }

  const nuSynchroniseren = async () => {
    setSynchroniserenBezig(true)
    setSynchroniserenFout(null)
    const fouten = await synchroniseerAlleCaches(administratieId)
    if (fouten.length > 0) setSynchroniserenFout(fouten.join('; '))
    setCacheVersie((v) => v + 1)
    setSynchroniserenBezig(false)
  }

  const controleren = async () => {
    setControlerenBezig(true)
    setControlerenFout(null)
    setBoekenFout(null)
    setBoekResultaat(null)
    try {
      const resultaat = await apiJson<BoekvoorstelMetChecksDto>(
        `/administraties/${administratieId}/documenten/${documentId}/boekvoorstel`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            vendor_id: vendorId,
            referentie: referentie || null,
            factuurdatum: factuurdatum || null,
            totaalbedrag: totaalbedrag ? normaliseerBedrag(totaalbedrag) : null,
            // Fix 3: de weergavekeuze reist mee en wordt backend-side als voorkeur per
            // (administratie, crediteur) onthouden; null = geen keuze door te geven.
            regels_samenvoegen: samenvoegenToegestaan ? regelsSamenvoegen : null,
            regels: regels.map((r) => ({
              ledger_id: r.ledgerId,
              taxrate_id: r.taxrateId,
              project_id: projectVerplicht ? r.projectId : null,
              netto_bedrag: r.netto ? normaliseerBedrag(r.netto) : null,
              btw_bedrag: r.btw ? normaliseerBedrag(r.btw) : null,
              omschrijving: r.omschrijving || null,
            })),
          }),
        },
      )
      setCheckRapport(resultaat.checks)
      setChecksActueel(true)
    } catch (err) {
      setControlerenFout(err instanceof ApiError ? err.message : 'Controleren mislukt.')
    } finally {
      setControlerenBezig(false)
    }
  }

  const boeken = async () => {
    setBoekenBezig(true)
    setBoekenFout(null)
    try {
      const resp = await apiFetch(`/administraties/${administratieId}/documenten/${documentId}/boeken`, {
        method: 'POST',
      })
      const body: unknown = await resp.json().catch(() => null)

      if (resp.ok) {
        const resultaat = body as BoekenResponseDto
        setBoekResultaat(resultaat)
        setBoekstuknummer(resultaat.rlz_boekstuknummer)
        onGeboekt()
        return
      }

      // Bij BoekenGeblokkeerdDoorChecks (409) stuurt de router het CheckRapport mee in
      // detail.checks (een object, geen platte string) — dat kan de generieke apiJson/ApiError-
      // afhandeling niet uitpakken, dus hier rechtstreeks de rauwe Response gebruiken.
      const detail = body && typeof body === 'object' ? (body as { detail?: unknown }).detail : null
      if (resp.status === 409 && detail && typeof detail === 'object' && 'checks' in detail) {
        const { message, checks } = detail as { message?: string; checks: unknown }
        setCheckRapport(checks as BoekvoorstelMetChecksDto['checks'])
        setChecksActueel(true)
        setBoekenFout(message ?? 'Boeken geblokkeerd door harde checks — zie de checks hierboven.')
      } else {
        setBoekenFout(typeof detail === 'string' ? detail : resp.statusText || `Fout (${resp.status})`)
      }
    } catch (err) {
      setBoekenFout(err instanceof ApiError ? err.message : 'Boeken mislukt.')
    } finally {
      setBoekenBezig(false)
    }
  }

  const herstellen = async () => {
    setHerstellenBezig(true)
    setHerstellenFout(null)
    try {
      await apiPostJson<DocumentActieResponseDto>(
        `/administraties/${administratieId}/documenten/${documentId}/herstellen`,
        {},
      )
      onHersteld()
    } catch (err) {
      setHerstellenFout(err instanceof ApiError ? err.message : 'Herstellen mislukt.')
    } finally {
      setHerstellenBezig(false)
    }
  }

  const totaalAlsGetal = useMemo(() => bedragAlsGetal(totaalbedrag), [totaalbedrag])
  const somRegels = useMemo(
    () => regels.reduce((acc, r) => acc + (bedragAlsGetal(r.netto) ?? 0) + (bedragAlsGetal(r.btw) ?? 0), 0),
    [regels],
  )
  const aansluitVerschil = totaalAlsGetal === null ? null : somRegels - totaalAlsGetal
  const aansluit = aansluitVerschil === null ? null : Math.abs(aansluitVerschil) <= 0.01

  if (laden) return <div className="panel">Boekvoorstel laden…</div>
  if (ladenFout) return <div className="fout">Kon boekvoorstel niet laden: {ladenFout}</div>

  const kanBoeken = checkRapport !== null && checksActueel && !checkRapport.geblokkeerd && !isReadOnly
  const boekenTitel = isReadOnly
    ? undefined
    : checkRapport === null
      ? 'Voer eerst de harde checks uit via "Controleren".'
      : !checksActueel
        ? 'Er zijn wijzigingen sinds de laatste controle — klik opnieuw op "Controleren".'
        : checkRapport.geblokkeerd
          ? 'Boeken geblokkeerd — een of meer harde checks zijn niet groen.'
          : undefined

  return (
    <>
      <div className="panel">
        <h2>Kopgegevens</h2>
        {!isReadOnly && synchroniserenFout && (
          <div className="fout">Synchroniseren gaf fouten: {synchroniserenFout}</div>
        )}
        {!isReadOnly && !vendorLaden && vendorOpties.length === 0 && !vendorFout && (
          <LegeCacheBanner naam="crediteuren" bezig={synchroniserenBezig} onSynchroniseren={() => void nuSynchroniseren()} />
        )}
        {!isReadOnly && vendorFout && <div className="fout">Kon crediteuren niet laden: {vendorFout}</div>}
        {isReadOnly ? (
          <div className="grid2">
            <StatischVeld label="Crediteur" waarde={optieWeergave(vendorOpties, vendorId)} />
            <StatischVeld label="Referentie / factuurnummer" waarde={referentie} />
            <StatischVeld label="Factuurdatum" waarde={factuurdatum} />
            <StatischVeld label="Totaalbedrag (incl. btw)" waarde={totaalbedrag ? `€ ${totaalbedrag}` : ''} />
          </div>
        ) : (
          <div className="grid2">
            <div>
              <SearchableCombobox
                label="Crediteur"
                opties={vendorOpties}
                waarde={vendorId}
                onWijzig={wijzigVendorId}
                vereist
                fout={checkRapport?.geblokkeerd && vendorId === null}
              />
              {aiKop?.vendor && (
                <div style={{ marginTop: 4 }}>
                  <AiChip score={aiKop.vendor.score} drempel={aiKop.drempel} fuzzy={aiKop.vendor.fuzzy} />
                </div>
              )}
              {vendorId === null && aiLeverancierNaam && (
                <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <div>
                    <span
                      className="chip afwijking"
                      title="De AI las deze leveranciersnaam, maar er is geen eenduidige match in de crediteuren-cache — koppel aan een bestaande crediteur of maak een nieuwe aan in RLZ."
                    >
                      AI las: „{aiLeverancierNaam}”
                      {ai?.zekerheid.leverancier_naam !== undefined
                        ? ` · ${zekerheidPct(ai.zekerheid.leverancier_naam)}`
                        : ''}
                    </span>
                  </div>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    {crediteurVoorstellen.map((s) => (
                      <button
                        key={s.optie.id}
                        type="button"
                        className="btn secondary"
                        onClick={() => wijzigVendorId(s.optie.id)}
                      >
                        Koppel aan „{s.optie.label}”
                      </button>
                    ))}
                    <button
                      type="button"
                      className="btn secondary"
                      disabled={crediteurAanmakenBezig}
                      onClick={() => void nieuweCrediteurAanmaken()}
                    >
                      {crediteurAanmakenBezig ? 'Bezig…' : `＋ Nieuwe crediteur „${aiLeverancierNaam}” aanmaken in RLZ`}
                    </button>
                  </div>
                  {crediteurAanmakenFout && <div className="fout">{crediteurAanmakenFout}</div>}
                </div>
              )}
            </div>
            <div>
              <label htmlFor="boekvoorstel-referentie">Referentie / factuurnummer</label>
              <input
                id="boekvoorstel-referentie"
                value={referentie}
                onChange={(e) => wijzigReferentie(e.target.value)}
              />
              {aiKop?.referentie && (
                <div style={{ marginTop: 4 }}>
                  <AiChip score={aiKop.referentie.score} drempel={aiKop.drempel} />
                </div>
              )}
            </div>
            <div>
              <label htmlFor="boekvoorstel-datum">Factuurdatum</label>
              <input
                id="boekvoorstel-datum"
                type="date"
                value={factuurdatum}
                onChange={(e) => wijzigFactuurdatum(e.target.value)}
              />
              {aiKop?.factuurdatum && (
                <div style={{ marginTop: 4 }}>
                  <AiChip score={aiKop.factuurdatum.score} drempel={aiKop.drempel} />
                </div>
              )}
            </div>
            <div>
              <label htmlFor="boekvoorstel-totaal">Totaalbedrag (incl. btw)</label>
              <input
                id="boekvoorstel-totaal"
                inputMode="decimal"
                placeholder="1234,56"
                title="Bijvoorbeeld 1234,56 of 1234.56"
                value={totaalbedrag}
                onChange={(e) => wijzigTotaalbedrag(e.target.value)}
              />
              {aiKop?.totaalbedrag && (
                <div style={{ marginTop: 4 }}>
                  <AiChip score={aiKop.totaalbedrag.score} drempel={aiKop.drempel} />
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="panel">
        <h2>Boekingsregels</h2>
        {!isReadOnly && !grootboekLaden && grootboekOpties.length === 0 && !grootboekFout && (
          <LegeCacheBanner naam="het grootboekschema" bezig={synchroniserenBezig} onSynchroniseren={() => void nuSynchroniseren()} />
        )}
        {!isReadOnly && !taxrateLaden && taxrateOpties.length === 0 && !taxrateFout && (
          <LegeCacheBanner naam="btw-codes" bezig={synchroniserenBezig} onSynchroniseren={() => void nuSynchroniseren()} />
        )}
        {!isReadOnly && projectVerplicht && !projectLaden && projectOpties.length === 0 && (
          <LegeCacheBanner naam="projecten" bezig={synchroniserenBezig} onSynchroniseren={() => void nuSynchroniseren()} />
        )}
        {!isReadOnly && (grootboekFout || taxrateFout) && (
          <div className="fout">Kon grootboek- en/of btw-cache niet laden — controleer of deze administratie gesynchroniseerd is.</div>
        )}
        {!isReadOnly && samenvoegenBeschikbaar && (
          <div style={{ marginBottom: 10, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0, cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={!regelsSamenvoegen}
                onChange={(e) => wisselSamenvoegen(!e.target.checked)}
              />
              Splitsen per regel
            </label>
            <span className="hint" style={{ margin: 0 }}>
              {regelsSamenvoegen
                ? `Samengevoegd tot één boekingsregel (${inactieveRegels.length} factuurregels gelezen) — keuze wordt per leverancier onthouden.`
                : 'Losse factuurregels — keuze wordt per leverancier onthouden.'}
            </span>
          </div>
        )}
        <table className="lines boekingsregels-tabel">
          <colgroup>
            <col style={{ width: '22%' }} />
            <col style={{ width: '16%' }} />
            {projectVerplicht && <col style={{ width: '14%' }} />}
            <col style={{ width: 84 }} />
            <col style={{ width: 84 }} />
            <col />
            <col style={{ width: 36 }} />
          </colgroup>
          <tbody>
            <tr>
              <th>Grootboek</th>
              <th>Btw-code</th>
              {projectVerplicht && <th>Project</th>}
              <th className="amount">Netto</th>
              <th className="amount">Btw-bedrag</th>
              <th>Omschrijving</th>
              <th />
            </tr>
            {regels.map((regel) => {
              const percentage = regel.taxrateId ? percentageMap[regel.taxrateId] : undefined
              const nettoAlsGetal = bedragAlsGetal(regel.netto)
              const verwachtBtw =
                percentage !== undefined && nettoAlsGetal !== null ? berekenBtwBedrag(nettoAlsGetal, percentage) : null
              const huidigBtw = bedragAlsGetal(regel.btw)
              const btwWijktAf = verwachtBtw !== null && (huidigBtw === null || Math.abs(huidigBtw - verwachtBtw) > 0.005)
              return (
              <tr key={regel.key}>
                <td>
                  {isReadOnly ? (
                    optieWeergave(grootboekOpties, regel.ledgerId)
                  ) : (
                    <SearchableCombobox
                      label="Grootboek"
                      opties={grootboekOpties}
                      waarde={regel.ledgerId}
                      onWijzig={(id) => wijzigRegel(regel.key, 'ledgerId', id)}
                      vereist
                      toonLabel={false}
                    />
                  )}
                </td>
                <td>
                  {isReadOnly ? (
                    optieWeergave(taxrateOpties, regel.taxrateId)
                  ) : (
                    <SearchableCombobox
                      label="Btw-code"
                      opties={taxrateOpties}
                      waarde={regel.taxrateId}
                      onWijzig={(id) => wijzigRegel(regel.key, 'taxrateId', id)}
                      vereist
                      toonLabel={false}
                    />
                  )}
                </td>
                {projectVerplicht && (
                  <td>
                    {isReadOnly ? (
                      optieWeergave(projectOpties, regel.projectId)
                    ) : (
                      <SearchableCombobox
                        label="Project"
                        opties={projectOpties}
                        waarde={regel.projectId}
                        onWijzig={(id) => wijzigRegel(regel.key, 'projectId', id)}
                        vereist
                        toonLabel={false}
                        fout={checkRapport?.geblokkeerd && regel.projectId === null}
                      />
                    )}
                  </td>
                )}
                <td className="amount">
                  {isReadOnly ? (
                    regel.netto || '—'
                  ) : (
                    <input
                      aria-label="Netto bedrag"
                      inputMode="decimal"
                      title="Bijvoorbeeld 1234,56 of 1234.56"
                      style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}
                      value={regel.netto}
                      onChange={(e) => wijzigRegel(regel.key, 'netto', e.target.value)}
                    />
                  )}
                </td>
                <td className="amount">
                  {isReadOnly ? (
                    regel.btw || '—'
                  ) : (
                    <>
                      <input
                        aria-label="Btw bedrag"
                        inputMode="decimal"
                        title="Bijvoorbeeld 1234,56 of 1234.56"
                        style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}
                        value={regel.btw}
                        onChange={(e) => wijzigRegel(regel.key, 'btw', e.target.value)}
                      />
                      {btwWijktAf && verwachtBtw !== null && (
                        <div style={{ textAlign: 'right', marginTop: 4 }}>
                          <span className="chip afwijking">Berekend: € {formatEuro(verwachtBtw)}</span>
                        </div>
                      )}
                    </>
                  )}
                </td>
                <td>
                  {isReadOnly ? (
                    regel.omschrijving || '—'
                  ) : (
                    <>
                      <input
                        aria-label="Omschrijving"
                        value={regel.omschrijving}
                        onChange={(e) => wijzigRegel(regel.key, 'omschrijving', e.target.value)}
                      />
                      {aiChipsActief && regel.aiZekerheid !== null && (
                        <div style={{ marginTop: 4 }}>
                          <AiChip score={regel.aiZekerheid} drempel={ai?.zekerheid_drempel ?? 0.8} />
                        </div>
                      )}
                    </>
                  )}
                </td>
                <td>
                  {!isReadOnly && (
                    <button
                      type="button"
                      className="btn secondary"
                      onClick={() => verwijderRegel(regel.key)}
                      aria-label="Regel verwijderen"
                    >
                      ×
                    </button>
                  )}
                </td>
              </tr>
              )
            })}
          </tbody>
        </table>
        {!isReadOnly && (
          <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <button type="button" className="btn secondary" onClick={voegRegelToe}>
              + Regel toevoegen
            </button>
            {aansluit !== null && aansluitVerschil !== null && (
              <span className={`chip ${aansluit ? 'ok' : 'afwijking'}`}>
                {aansluit
                  ? `Aansluitend — € ${formatEuro(somRegels)}`
                  : `Afwijking € ${formatEuro(Math.abs(aansluitVerschil))} (som € ${formatEuro(somRegels)} vs totaal € ${formatEuro(totaalAlsGetal ?? 0)})`}
              </span>
            )}
          </div>
        )}
        {!isReadOnly && (
          <div className="hint">
            Grootboek- en btw-lijsten komen uit de sync-cache van deze administratie (koppelcontract §2c) — nooit
            rechtstreeks live van RLZ.
          </div>
        )}
      </div>

      {!isReadOnly && (
        <div className="panel">
          <h2>Harde checks</h2>
          {controlerenFout && <div className="fout">{controlerenFout}</div>}
          {checkRapport === null && <p className="hint">Klik op "Controleren" om de harde checks uit te voeren.</p>}
          {checkRapport && (
            <>
              {!checksActueel && (
                <div className="hint" style={{ color: 'var(--orange)' }}>
                  Wijzigingen sinds de laatste controle — dit resultaat is verouderd. Klik opnieuw op "Controleren".
                </div>
              )}
              <table className="lines">
                <tbody>
                  {checkRapport.resultaten.map((r) => (
                    <tr key={r.naam} style={!checksActueel ? { opacity: 0.55 } : undefined}>
                      <td>
                        <span className={`chip ${r.ok ? 'ok' : 'blokkerend'}`}>{r.ok ? 'OK' : 'Blokkerend'}</span>
                      </td>
                      <td>
                        <b>{r.naam}</b>
                      </td>
                      <td>{r.melding}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          <div className="actions">
            <button type="button" className="btn secondary" disabled={controlerenBezig} onClick={() => void controleren()}>
              {controlerenBezig ? 'Bezig…' : 'Controleren'}
            </button>
          </div>
        </div>
      )}

      <div className="panel">
        {boekenFout && <div className="fout">{boekenFout}</div>}
        {boekResultaat && (
          <div className="hint" style={{ color: 'var(--green)' }}>
            Geboekt in RLZ — boekstuknummer <b>{boekResultaat.rlz_boekstuknummer}</b>
          </div>
        )}
        {isGeboekt && (
          <>
            <p style={{ margin: 0, fontSize: 14 }}>
              Geboekt in RLZ — boekstuknummer <b>{boekstuknummer ?? '—'}</b>
            </p>
            <p className="hint">
              Wijzigen kan alleen via stornering in Reeleezee (actie 19); daarna komt het document hier terug als
              concept.
            </p>
          </>
        )}
        {isVerwijderd && (
          <>
            {herstellenFout && <div className="fout">{herstellenFout}</div>}
            <p className="hint" style={{ marginTop: 0 }}>
              Dit document is verwijderd — het bestand en de geschiedenis blijven bewaard. Herstellen zet het terug
              op de status van vóór de verwijdering.
            </p>
            <div className="actions">
              <button type="button" className="btn" disabled={herstellenBezig} onClick={() => void herstellen()}>
                {herstellenBezig ? 'Bezig…' : '↺ Herstellen'}
              </button>
            </div>
          </>
        )}
        {!isReadOnly && (
          <div className="actions">
            <button
              type="button"
              className="btn green"
              disabled={!kanBoeken || boekenBezig}
              title={boekenTitel}
              onClick={() => void boeken()}
            >
              {boekenBezig ? 'Bezig…' : 'Boeken in RLZ ✓'}
            </button>
          </div>
        )}
      </div>
    </>
  )
}
