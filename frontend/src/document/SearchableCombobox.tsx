import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { createPortal } from 'react-dom'

export interface ComboboxOptie {
  id: string
  label: string
  /** Korte, opvallende sleutel vóór de omschrijving (bv. de grootboekcode of het btw-percentage)
   * — design-pass taak 2: "optie-rijen met code vet + omschrijving". Optioneel: niet elke
   * entiteit (crediteuren/projecten) heeft zoiets. */
  code?: string
  /** Btw-percentage als fractie (0.21 voor 21%) — alleen gezet door useTaxrateOpties, puur
   * doorgeefluik voor BoekvoorstelPanel's automatische btw-afleiding (design-pass taak 3).
   * SearchableCombobox zelf doet niets met dit veld. */
  percentage?: number
  /** Standaard-btw-tarief van een grootboekrekening (14-09, `GrootboekOptieDto.standaard_taxrate_id`) — alleen gezet
   * door useGrootboekOpties, doorgeefluik voor BoekvoorstelPanel's "btw volgt de rekening" bij een grootboek-wissel.
   * SearchableCombobox zelf doet niets met dit veld. */
  standaardTaxrateId?: string | null
  /** Idem, afgeleid uit de historie (0143, `historie_taxrate_id` + `historie_taxrate_n`) — volgt ná de RLZ-default. */
  historieTaxrateId?: string | null
  historieTaxrateN?: number | null
  /** Blok C 16-09: een project met `is_actief = false` blijft zichtbaar (onderaan, chip "inactief") — de gebruiker
   * moet zien wat er bestaat; verbergen was precies Peters klacht. */
  inactief?: boolean
  /** 18-09 DEEL B (btw-keuzelijst NL-eerst): groepsnaam van de optie; mét `ingeklapteGroep` op de combobox staat deze
   * groep zonder zoekterm ingeklapt achter één regel onderaan ("Buitenland-tarieven tonen (N)"). Zoeken doorzoekt
   * altijd álles; de geselecteerde optie blijft altijd zichtbaar. */
  groep?: string
  /** Doorgeefluiken van useTaxrateOpties (18-09): RLZ-vlaggen + gebruik in 12 maanden; de combobox doet er niets mee. */
  verlegd?: boolean
  vrijgesteld?: boolean
  buitenland?: boolean
  favoriet?: boolean
  gebruik12m?: number
}

function weergaveTekst(optie: ComboboxOptie): string {
  return optie.code ? `${optie.code} · ${optie.label}` : optie.label
}

interface Props {
  label: string
  opties: ComboboxOptie[]
  waarde: string | null
  onWijzig: (id: string | null) => void
  placeholder?: string
  vereist?: boolean
  fout?: boolean
  /** Verbergt het visuele <label>-element (bv. in een tabelkolom waar de kolomkop al het label
   * is — design-pass taak 2: "dubbele labels weg"). De tekst blijft wel als aria-label op de
   * input staan, voor screenreaders die geen kolomkop-context hebben. */
  toonLabel?: boolean
  /** Vaste onderste rij ónder de opties — buiten het virtualisatievenster, altijd zichtbaar
   * (fix C3 04-09: "+ Nieuw project aanmaken…" in de projectkolom). Toetsenbord: pijl-omlaag
   * voorbij de laatste optie landt erop, Enter activeert. Géén optie: kiest niets, maar opent
   * een dialoog bij de aanroeper — daarom een knop, geen listbox-optie. */
  voetActie?: { label: string; onKies: () => void }
  /** Blok A 16-09 (feedback Peter, projectveld verplichting-scherm): leeg ≠ laden ≠ fout. De lijst is nog aan het
   * laden ("Laden…"), kon niet geladen worden ("Kon de lijst niet laden — <reden>" mét "Opnieuw" als `onOpnieuw`
   * gezet is), of is écht leeg ("Geen <meervoud van label> in deze administratie", overschrijfbaar via `leegTekst`).
   * Een filter zonder treffer blijft "Geen resultaten voor '<term>'". De stand rendert BUITEN de gevirtualiseerde
   * hoogte-container — die is bij nul opties 0 px hoog en knipte de tekst tot een sliver weg. */
  laden?: boolean
  laadFout?: string | null
  onOpnieuw?: () => void
  leegTekst?: string
  /** 18-09 DEEL B: opties mét `groep === ingeklapteGroep.groep` staan zonder zoekterm ingeklapt achter één toggle-rij
   * onderaan (label bv. "Buitenland-tarieven tonen (7)"); klik/Enter vouwt ze uit voor déze combobox; een zoekterm
   * doorzoekt altijd álle opties; de geselecteerde optie blijft zichtbaar. Pijltjes slaan de ingeklapte groep over. */
  ingeklapteGroep?: { groep: string; label: (aantal: number) => string }
}

/** Meervoud van het veldlabel voor de lege stand — bewust een kleine, expliciete tabel (geen taalregels die stil
 * misgaan); onbekend label = neutraal "opties". */
const LABEL_MEERVOUD: Record<string, string> = {
  project: 'projecten',
  'project (vast)': 'projecten',
  leverancier: 'crediteuren',
  crediteur: 'crediteuren',
  relatie: 'relaties',
  grootboek: 'grootboekrekeningen',
  grootboekrekening: 'grootboekrekeningen',
  rekening: 'grootboekrekeningen',
  'btw-code': 'btw-codes',
  btw: 'btw-codes',
  administratie: 'administraties',
  categorie: 'categorieën',
}

export function legeStandTekst(label: string, leegTekst?: string): string {
  if (leegTekst) return leegTekst
  const meervoud = LABEL_MEERVOUD[label.trim().toLowerCase()] ?? 'opties'
  return `Geen ${meervoud} in deze administratie`
}

// Sync-caches kunnen honderden tot duizenden opties bevatten (bv. Universal: 145 projecten) —
// alleen het zichtbare venster + een kleine buffer wordt daadwerkelijk gerenderd (BOUWPLAN.md,
// UI-eisen: gevirtualiseerde lijsten voor elke lijstweergave uit een sync-cache).
const RIJHOOGTE = 32
const ZICHTBARE_RIJEN = 8
const BUFFER = 4

function useDebounced<T>(waarde: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(waarde)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(waarde), delayMs)
    return () => clearTimeout(timer)
  }, [waarde, delayMs])
  return debounced
}

// Ademruimte tussen lijst en viewportrand; de lijst klapt naar boven open ("flip") zodra er
// onder het veld minder ruimte is dan de gewenste hoogte én boven méér — en wordt in beide
// richtingen op de beschikbare ruimte afgekapt met interne scroll, zodat hij altijd volledig
// binnen de viewport valt (bugfix 2026-07-11: onderin het scherm vielen opties buiten beeld).
const VIEWPORT_MARGE = 8
const GEWENSTE_HOOGTE = ZICHTBARE_RIJEN * RIJHOOGTE + 8
// Ondergrens voor de máximale lijstbreedte: in smalle tabelkolommen (GB/btw ~80-120px) is
// 1,6× de veldbreedte nog steeds onleesbaar — "code + omschrijving" heeft ~280px nodig.
// `width: max-content` zorgt dat een korte lijst nooit onnodig breed rendert; dit is een cap.
const MIN_LEESBARE_BREEDTE = 280

interface Positie {
  /** Gezet bij openen naar beneden (afstand tot viewport-bovenkant). */
  top?: number
  /** Gezet bij openen naar boven (afstand tot viewport-ónderkant, CSS `bottom` op fixed). */
  bottom?: number
  left: number
  width: number
  maxWidth: number
  maxHeight: number
}

/** Zoekbare combobox met toetsenbordnavigatie en gevirtualiseerde opties-lijst (BOUWPLAN.md,
 * UI-eisen voor elk GB-/project-/entiteitveld) — debounced lokaal filteren, geen request per
 * toetsaanslag (de sync-cache is al lokaal). De opties-lijst rendert via een React-portal naar
 * `document.body` met een zelf-berekende `position: fixed`-plek: zo blijft hij altijd zichtbaar,
 * ook binnen containers met `overflow: hidden` (bv. de `<table>`-stijl in components.css) die 'm
 * anders zouden afknippen. */
export function SearchableCombobox({
  label,
  opties,
  waarde,
  onWijzig,
  placeholder,
  vereist,
  fout,
  toonLabel = true,
  voetActie,
  laden = false,
  laadFout = null,
  onOpnieuw,
  leegTekst,
  ingeklapteGroep,
}: Props) {
  const reactId = useId()
  const inputId = `${reactId}-input`
  const listboxId = `${reactId}-listbox`

  const [open, setOpen] = useState(false)
  const [zoekterm, setZoekterm] = useState('')
  const [groepUitgevouwen, setGroepUitgevouwen] = useState(false)
  const [actieveIndex, setActieveIndex] = useState(0)
  const [scrollTop, setScrollTop] = useState(0)
  const [positie, setPositie] = useState<Positie | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  const debouncedZoekterm = useDebounced(zoekterm, 150)

  const geselecteerd = useMemo(() => opties.find((o) => o.id === waarde) ?? null, [opties, waarde])

  const gefilterd = useMemo(() => {
    const term = debouncedZoekterm.trim().toLowerCase()
    if (!term) {
      // 18-09: zonder zoekterm blijft de ingeklapte groep verborgen (behalve de geselecteerde optie) tot uitgevouwen.
      if (ingeklapteGroep && !groepUitgevouwen) {
        return opties.filter((o) => o.groep !== ingeklapteGroep.groep || o.id === waarde)
      }
      return opties
    }
    return opties.filter(
      (o) => o.label.toLowerCase().includes(term) || (o.code?.toLowerCase().includes(term) ?? false),
    )
  }, [opties, debouncedZoekterm, ingeklapteGroep, groepUitgevouwen, waarde])
  const ingeklaptAantal = useMemo(() => {
    if (!ingeklapteGroep || groepUitgevouwen || debouncedZoekterm.trim()) return 0
    return opties.filter((o) => o.groep === ingeklapteGroep.groep && o.id !== waarde).length
  }, [opties, ingeklapteGroep, groepUitgevouwen, debouncedZoekterm, waarde])

  // Breedte-anker (bugfix 2026-07-11): de gevirtualiseerde optierijen staan position:absolute
  // en dragen daardoor NIET bij aan de max-content-breedte van de listbox — die klapte dicht
  // naar minWidth (veldbreedte) en kapte opties af. Eén onzichtbaar, in-flow exemplaar van de
  // (naar tekenlengte) langste optie geeft de listbox zijn echte inhoudsbreedte terug, gemeten
  // door de browser zelf met de echte fonts/padding (zelfde CSS-klasse — geen canvas-benadering
  // die stil uit de pas kan lopen met de stylesheet). Tekenlengte is bij proportionele fonts
  // een benadering; het ellipsis-vangnet (components.css) dekt de zeldzame misser.
  const breedsteOptie = useMemo(() => {
    let beste: ComboboxOptie | null = null
    let besteLengte = -1
    for (const optie of gefilterd) {
      const lengte = (optie.code ? optie.code.length + 3 : 0) + optie.label.length
      if (lengte > besteLengte) {
        beste = optie
        besteLengte = lengte
      }
    }
    return beste
  }, [gefilterd])

  useEffect(() => {
    setActieveIndex(0)
    setScrollTop(0)
  }, [debouncedZoekterm])

  const bijwerkenPositie = useCallback(() => {
    const el = inputRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    // Scrollt het veld zelf (vrijwel) uit beeld, dan sluit de lijst — een fixed lijst die aan
    // een onzichtbaar veld "vastzit" zweeft anders los door het scherm (bugfix 2026-07-11).
    if (rect.bottom < 0 || rect.top > window.innerHeight) {
      setOpen(false)
      return
    }
    const ruimteOnder = window.innerHeight - rect.bottom - VIEWPORT_MARGE
    const ruimteBoven = rect.top - VIEWPORT_MARGE
    const naarBoven = ruimteOnder < GEWENSTE_HOOGTE && ruimteBoven > ruimteOnder
    // Breedte >= het invoerveld (design-pass taak 2) — de lijst mag breder worden om "code +
    // omschrijving" leesbaar te tonen: tot 1,6× de veldbreedte, begrensd door de viewport
    // (UI-polish 2026-07-11: de oude grens `viewport − rect.left` kapte opties af zodra het
    // veld rechts in het scherm stond). Op een viewport smaller dan het veld valt de lijst
    // terug op de veldbreedte; ellipsis op de optietekst is dan het vangnet (components.css).
    // Steekt de gerenderde lijst rechts buiten beeld, dan schuift het layout-effect hieronder
    // hem naar links — `left` hier is het uitgangspunt, niet de eindstand.
    const beschikbareBreedte = window.innerWidth - 2 * VIEWPORT_MARGE
    setPositie({
      top: naarBoven ? undefined : rect.bottom,
      bottom: naarBoven ? window.innerHeight - rect.top : undefined,
      left: rect.left,
      width: rect.width,
      maxWidth: Math.max(rect.width, Math.min(Math.max(rect.width * 1.6, MIN_LEESBARE_BREEDTE), beschikbareBreedte)),
      maxHeight: Math.max(RIJHOOGTE + 8, Math.min(GEWENSTE_HOOGTE, naarBoven ? ruimteBoven : ruimteOnder)),
    })
  }, [])

  // Naar links schuiven als de gerenderde lijst rechts buiten de viewport steekt: de echte
  // breedte (max-content, geclampt op maxWidth) is pas ná de render bekend, dus meten en vóór
  // de paint corrigeren. Stabiel: zodra links klopt, verandert er niets meer.
  useLayoutEffect(() => {
    if (!open || !listRef.current || !positie) return
    const breedte = listRef.current.offsetWidth
    const maxLinks = window.innerWidth - VIEWPORT_MARGE - breedte
    const gewenstLinks = Math.max(VIEWPORT_MARGE, Math.min(positie.left, maxLinks))
    if (Math.abs(gewenstLinks - positie.left) > 1) setPositie({ ...positie, left: gewenstLinks })
  }, [open, positie])

  useEffect(() => {
    if (!open) return
    bijwerkenPositie()
    // capture:true zodat scroll op ELKE voorouder-container (niet alleen window) de positie
    // bijwerkt — anders "drijft" de dropdown weg van het veld bij scrollen binnen een tabel-pane.
    window.addEventListener('scroll', bijwerkenPositie, true)
    window.addEventListener('resize', bijwerkenPositie)
    return () => {
      window.removeEventListener('scroll', bijwerkenPositie, true)
      window.removeEventListener('resize', bijwerkenPositie)
    }
  }, [open, bijwerkenPositie])

  useEffect(() => {
    if (!open) return
    function opKlikBuiten(e: MouseEvent) {
      const doel = e.target as Node
      const inVeld = containerRef.current?.contains(doel)
      const inLijst = listRef.current?.contains(doel)
      if (!inVeld && !inLijst) setOpen(false)
    }
    document.addEventListener('mousedown', opKlikBuiten)
    return () => document.removeEventListener('mousedown', opKlikBuiten)
  }, [open])

  const kiesOptie = useCallback(
    (optie: ComboboxOptie) => {
      onWijzig(optie.id)
      setZoekterm('')
      setOpen(false)
    },
    [onWijzig],
  )

  // De voet-actie is een virtuele extra rij áchter de laatste optie: pijl-omlaag landt erop
  // (ook bij nul zoekresultaten — dán is het de enige bereikbare rij) en Enter activeert 'm.
  // 18-09: de inklap-toggle is een virtuele rij ná de opties (vóór de voet-actie); Enter/klik vouwt uit zonder te
  // sluiten of te kiezen.
  const toggleIndex = ingeklaptAantal > 0 ? gefilterd.length : -1
  const voetIndex = voetActie ? gefilterd.length + (toggleIndex >= 0 ? 1 : 0) : -1
  const hoogsteIndex = Math.max(gefilterd.length - 1, toggleIndex, voetIndex)

  const kiesVoet = useCallback(() => {
    if (!voetActie) return
    setZoekterm('')
    setOpen(false)
    voetActie.onKies()
  }, [voetActie])

  const vouwGroepUit = useCallback(() => {
    setGroepUitgevouwen(true)
    setActieveIndex(0)
  }, [])

  const opToetsenbord = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      if (!open) {
        setOpen(true)
        return
      }
      setActieveIndex((i) => Math.min(i + 1, hoogsteIndex))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActieveIndex((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (!open) return
      if (actieveIndex === voetIndex) kiesVoet()
      else if (actieveIndex === toggleIndex) vouwGroepUit()
      else if (gefilterd[actieveIndex]) kiesOptie(gefilterd[actieveIndex])
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  // Het render-venster volgt de wérkelijke lijsthoogte — die kan door de viewport-clamp kleiner
  // zijn dan de acht standaardrijen, maar het venster mag nooit kleiner worden dan wat zichtbaar is.
  const zichtbareRijen = Math.min(ZICHTBARE_RIJEN, Math.ceil((positie?.maxHeight ?? GEWENSTE_HOOGTE) / RIJHOOGTE))
  const eersteIndex = Math.max(0, Math.floor(scrollTop / RIJHOOGTE) - BUFFER)
  const laatsteIndex = Math.min(gefilterd.length, eersteIndex + ZICHTBARE_RIJEN + BUFFER * 2)
  const zichtbareOpties = gefilterd.slice(eersteIndex, laatsteIndex)

  useEffect(() => {
    if (!open || !listRef.current) return
    const rijTop = actieveIndex * RIJHOOGTE
    const el = listRef.current
    // clientHeight i.p.v. de vaste acht rijen: bij een viewport-geclampte lijst is het zichtbare
    // venster kleiner en moet de actieve rij binnen dát venster blijven.
    const vensterHoogte = el.clientHeight || zichtbareRijen * RIJHOOGTE
    if (rijTop < el.scrollTop) el.scrollTop = rijTop
    else if (rijTop + RIJHOOGTE > el.scrollTop + vensterHoogte) {
      el.scrollTop = rijTop + RIJHOOGTE - vensterHoogte
    }
  }, [actieveIndex, open, zichtbareRijen])

  const actieveOptieId =
    open && actieveIndex === voetIndex
      ? `${listboxId}-voetactie`
      : open && actieveIndex === toggleIndex
        ? `${listboxId}-inklap`
        : open && gefilterd[actieveIndex]
          ? `${listboxId}-${gefilterd[actieveIndex].id}`
          : undefined

  return (
    <div ref={containerRef} style={{ position: 'relative' }}>
      {toonLabel && (
        <label htmlFor={inputId}>
          {label}
          {vereist && ' *'}
        </label>
      )}
      <input
        ref={inputRef}
        id={inputId}
        role="combobox"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-autocomplete="list"
        aria-activedescendant={actieveOptieId}
        aria-required={vereist}
        aria-label={toonLabel ? undefined : `${label}${vereist ? ' (verplicht)' : ''}`}
        className={fout ? 'warnfield' : undefined}
        autoComplete="off"
        placeholder={placeholder ?? 'Typen om te zoeken…'}
        value={open ? zoekterm : geselecteerd ? weergaveTekst(geselecteerd) : ''}
        // Blok 4d (08-09): het gesloten veld kapt een lange keuze af — de volledige waarde blijft als tooltip leesbaar.
        title={!open && geselecteerd ? weergaveTekst(geselecteerd) : undefined}
        onFocus={() => {
          setOpen(true)
          setZoekterm('')
        }}
        onClick={() => setOpen(true)}
        onChange={(e) => {
          setZoekterm(e.target.value)
          setOpen(true)
        }}
        onKeyDown={opToetsenbord}
      />
      {open &&
        positie &&
        createPortal(
          <div
            ref={listRef}
            role="listbox"
            id={listboxId}
            aria-label={label}
            className="combobox-listbox"
            onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
            style={{
              position: 'fixed',
              zIndex: 1000,
              // Binnen een Radix-Dialog (modal) zet Radix `pointer-events: none` op <body>; deze
              // listbox portalt náár body en zou dan onklikbaar zijn (VerplaatsModal, 27-08 punt 5).
              pointerEvents: 'auto',
              top: positie.top,
              bottom: positie.bottom,
              left: positie.left,
              minWidth: positie.width,
              maxWidth: positie.maxWidth,
              width: 'max-content',
              maxHeight: positie.maxHeight,
            }}
          >
            {breedsteOptie && (
              <div aria-hidden="true" className="combobox-optie" style={{ height: 0, visibility: 'hidden' }}>
                {breedsteOptie.code && <span className="combobox-optie-code">{breedsteOptie.code}</span>}
                <span>{breedsteOptie.label}</span>
              </div>
            )}
            {gefilterd.length === 0 && (
              // Buiten de 0-px-hoogte-container hieronder, mét minimale rijhoogte: nooit meer weggeknipt (blok A 16-09).
              <div className="combobox-leeg" role="status" data-testid="combobox-leeg" style={{ minHeight: RIJHOOGTE }}>
                {laden ? (
                  'Laden…'
                ) : laadFout ? (
                  <>
                    Kon de lijst niet laden — {laadFout}
                    {onOpnieuw && (
                      <>
                        {' '}
                        <button
                          type="button"
                          className="linkbtn"
                          onMouseDown={(e) => {
                            e.preventDefault()
                            onOpnieuw()
                          }}
                        >
                          Opnieuw
                        </button>
                      </>
                    )}
                  </>
                ) : debouncedZoekterm.trim() ? (
                  `Geen resultaten voor '${debouncedZoekterm.trim()}'`
                ) : (
                  legeStandTekst(label, leegTekst)
                )}
              </div>
            )}
            <div style={{ height: gefilterd.length * RIJHOOGTE, position: 'relative' }}>
              {zichtbareOpties.map((optie, i) => {
                const echteIndex = eersteIndex + i
                return (
                  <div
                    key={optie.id}
                    id={`${listboxId}-${optie.id}`}
                    role="option"
                    aria-selected={echteIndex === actieveIndex}
                    onMouseDown={(e) => {
                      e.preventDefault()
                      kiesOptie(optie)
                    }}
                    onMouseEnter={() => setActieveIndex(echteIndex)}
                    className={`combobox-optie${echteIndex === actieveIndex ? ' actief' : ''}`}
                    style={{ position: 'absolute', top: echteIndex * RIJHOOGTE, left: 0, right: 0, height: RIJHOOGTE }}
                  >
                    {optie.code && <span className="combobox-optie-code">{optie.code}</span>}
                    <span>{optie.label}</span>
                    {optie.inactief && (
                      <span className="chip combobox-optie-chip" title="Staat in Reeleezee op inactief">
                        inactief
                      </span>
                    )}
                  </div>
                )
              })}
            </div>
            {toggleIndex >= 0 && ingeklapteGroep && (
              <button
                type="button"
                id={`${listboxId}-inklap`}
                data-testid="combobox-inklap"
                className={`linkbtn combobox-voet${actieveIndex === toggleIndex ? ' actief' : ''}`}
                onMouseDown={(e) => {
                  e.preventDefault()
                  vouwGroepUit()
                }}
                onMouseEnter={() => setActieveIndex(toggleIndex)}
              >
                {ingeklapteGroep.label(ingeklaptAantal)}
              </button>
            )}
            {voetActie && (
              <button
                type="button"
                id={`${listboxId}-voetactie`}
                className={`linkbtn combobox-voet${actieveIndex === voetIndex ? ' actief' : ''}`}
                // mousedown i.p.v. click: de klik-buiten-handler sluit de lijst op mousedown,
                // waardoor een click-handler op deze knop nooit zou vuren (zelfde reden als bij
                // de optierijen hierboven).
                onMouseDown={(e) => {
                  e.preventDefault()
                  kiesVoet()
                }}
                onMouseEnter={() => setActieveIndex(voetIndex)}
              >
                {voetActie.label}
              </button>
            )}
          </div>,
          document.body,
        )}
    </div>
  )
}
