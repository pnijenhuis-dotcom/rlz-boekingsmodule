// De accordeer-flow (mockup/accordeur.html 1-op-1): wachtrij (kaartlijst + teller) →
// factuurbeeld centraal met voorgestelde boeking → Akkoord (direct, → automatisch volgende) /
// Afwijzen (bottom-sheet, verplichte reden) → lege staat. Staande-goedkeuring-voorstel ná
// akkoord op identiek leverancier+bedrag; ✓✓-beheerscherm met intrekken. Scope bewust alléén
// de wachtrij (besluit 2026-08-08). Meldingen (UX-besluit Peter 2026-08-17): éénmalig
// voorstel in de activeringsflow (ná het voorwaarden-akkoord) resp. één eenmalige
// wachtrij-kaart voor apparaten die die flow al doorliepen; élke uitkomst (aan, "niet nu",
// mislukt-na-één-herkansing) wordt per apparaat onthouden en daarna blijft de wachtrij
// schoon — beheer via het 🔔-hoekje naast de themaknop. Permissie wordt alléén gevraagd
// vanuit een expliciete klik, nooit rauw bij het laden. ?document=<id> is de deep-link uit
// mail/push — alleen navigatie; de auth-cadans blijft de poort.
//
// SNELHEIDSLAAG (harde ontwerpeis Peter, 2026-08-17 — geldt ook voor de native schil die deze
// code bundelt): (a) wachtrij + metadata staan vooraf geladen; (b) het factuurbeeld van de
// eerstvolgende factuur wordt verborgen vooruit gemonteerd (prefetch + prerender via
// factuurCache) zodat de overgang na een besluit direct is; (c) akkoord/afwijzen is
// optimistisch — de UI gaat per direct door, besluitVerzender stuurt op de achtergrond met
// retry (backend-idempotent); faalt het definitief, dan komt het document ZICHTBAAR terug in
// de rij mét melding — nooit stil verloren; (d) het boeken-na-laatste-akkoord draait
// server-side in diezelfde achtergrond-call en blokkeert de accordeur dus nooit (een boekfout
// is kantoor-werkvoorraad, niet accordeur-frictie).

import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import {
  bewaardeMeldingenKeuze,
  bewaarMeldingenKeuze,
  haalMeldingenStatus,
  zetMeldingenAan,
  zetMeldingenUit,
  type MeldingenKeuze,
  type MeldingenStatus,
} from './pushClient'
import type { StaandeRegelDto } from '../accordering/accorderingApi'
import {
  datumWeergave,
  eurWeergave,
  haalMijnAdministraties,
  haalStaandeRegels,
  haalWachtrij,
  isVoorwaardenVereist,
  trekStaandeRegelIn,
  type WachtrijItemDto,
} from './accordeurApi'
import { besluitVerzender, type BesluitOpdracht } from './besluitQueue'
import { factuurCache } from './pdfCache'
import { PdfWeergave } from './PdfWeergave'
import { VoorwaardenScherm } from './VoorwaardenScherm'

type Weergave = 'wachtrij' | 'review' | 'beheer'

/** Wachtrij-item + lokale terugkeer-melding na een definitief mislukte verzending. */
type WachtrijItem = WachtrijItemDto & { verzend_fout?: string }

/** Dubbeltik-vangnet op de geld-knoppen: de overgang naar de volgende factuur is instant —
 * een onbedoelde tweede tik (typisch < 300 ms na de eerste) zou anders de VOLGENDE factuur
 * ongezien besluiten. Elke factuur verdient een bewuste klik; dit remt de weergave niet. */
export const OVERGANGS_GUARD_MS = 300

/** iOS-toetsenbordfix (iPhone-review Peter 2026-08-11, bouwvereiste): de open bottom-sheet
 * volgt window.visualViewport zodat redenveld + knoppen boven het toetsenbord blijven.
 * Fallback zonder visualViewport: scrollIntoView bij focus (zie AfwijsSheet). */
function useSheetBovenToetsenbord(open: boolean) {
  const sheetRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const vv = window.visualViewport
    if (!vv) return
    const bijwerken = () => {
      const afgedekt = Math.max(0, window.innerHeight - vv.height - vv.offsetTop)
      if (sheetRef.current) {
        sheetRef.current.style.transform = afgedekt ? `translateY(-${afgedekt}px)` : ''
      }
    }
    vv.addEventListener('resize', bijwerken)
    vv.addEventListener('scroll', bijwerken)
    bijwerken()
    return () => {
      vv.removeEventListener('resize', bijwerken)
      vv.removeEventListener('scroll', bijwerken)
      if (sheetRef.current) sheetRef.current.style.transform = ''
    }
  }, [open])
  return sheetRef
}

interface AfwijsSheetProps {
  onAnnuleer: () => void
  onBevestig: (reden: string) => void
}

function AfwijsSheet({ onAnnuleer, onBevestig }: AfwijsSheetProps) {
  const [reden, setReden] = useState('')
  const [toonFout, setToonFout] = useState(false)
  const sheetRef = useSheetBovenToetsenbord(true)
  const rijRef = useRef<HTMLDivElement>(null)

  const bevestig = () => {
    const tekst = reden.trim()
    if (!tekst) {
      setToonFout(true)
      return
    }
    onBevestig(tekst)
  }

  return (
    <div className="acc-sheet-bg">
      <div className="acc-sheet" ref={sheetRef}>
        <h2>Factuur afwijzen</h2>
        <div className="acc-uitleg">
          Een reden is <b>verplicht</b>. Je afwijzing gaat mét reden terug naar de werkvoorraad van het
          kantoor ("Afgewezen — ter controle") — er verdwijnt nooit iets stil.
        </div>
        <textarea
          aria-label="Reden van afwijzing"
          placeholder="Bijv.: dit werk is nog niet opgeleverd — factuur is te vroeg gestuurd"
          value={reden}
          onChange={(e) => setReden(e.target.value)}
          onFocus={() => {
            // Fallback voor browsers zónder visualViewport: veld + knoppenrij in beeld.
            if (!window.visualViewport) {
              setTimeout(() => rijRef.current?.scrollIntoView({ block: 'end', behavior: 'smooth' }), 250)
            }
          }}
        />
        {toonFout && (
          <div className="acc-verplicht">Vul eerst een reden in — zonder reden kan er niet afgewezen worden.</div>
        )}
        <div className="acc-rij" ref={rijRef}>
          <button className="acc-btn secundair" onClick={onAnnuleer}>
            Annuleren
          </button>
          <button className="acc-btn afwijs" onClick={bevestig}>
            Afwijzen met reden
          </button>
        </div>
      </div>
    </div>
  )
}

interface StaandSheetProps {
  item: WachtrijItemDto
  onKeuze: (staandeRegel: boolean) => void
}

function StaandSheet({ item, onKeuze }: StaandSheetProps) {
  const sheetRef = useSheetBovenToetsenbord(true)
  return (
    <div className="acc-sheet-bg">
      <div className="acc-sheet" ref={sheetRef}>
        <h2>Voortaan automatisch akkoord?</h2>
        <div className="acc-uitleg">
          Je keurde eerder een factuur van <b>{item.leverancier_naam ?? 'deze leverancier'}</b> met exact{' '}
          <b>{eurWeergave(item.totaalbedrag)}</b> goed. Wil je een staande goedkeuring instellen? Elke
          volgende factuur van deze leverancier met <b>exact {eurWeergave(item.totaalbedrag)}</b> wordt dan
          automatisch namens jou geaccordeerd. Elk ander bedrag komt gewoon bij je terug.
        </div>
        <div className="acc-uitlegblok" style={{ marginBottom: 0 }}>
          De controles van het kantoor (duplicaat, IBAN-wissel, regels) blijven élke factuur toetsen — een
          staande goedkeuring vervangt alleen jouw klik. Elk automatisch akkoord komt met vermelding in de
          tijdlijn en het audit log. Je kunt de regel altijd intrekken.
        </div>
        <div className="acc-rij">
          <button className="acc-btn secundair" onClick={() => onKeuze(false)}>
            Nee, alleen deze
          </button>
          <button className="acc-btn paars" onClick={() => onKeuze(true)}>
            Ja, sta toe
          </button>
        </div>
      </div>
    </div>
  )
}

interface MeldingenSheetProps {
  status: MeldingenStatus | null
  bezig: boolean
  onAanzetten: () => void
  onUitzetten: () => void
  onSluit: () => void
}

/** Het discrete meldingen-hoekje (🔔 naast de themaknop — UX-besluit Peter 2026-08-17):
 * dé plek om meldingen later alsnog aan of uit te zetten nu de wachtrij schoon blijft.
 * Kill-switch-semantiek ongewijzigd: het kantoor kan een apparaat server-side blijven
 * intrekken, ongeacht wat hier staat. */
function MeldingenSheet({ status, bezig, onAanzetten, onUitzetten, onSluit }: MeldingenSheetProps) {
  const sheetRef = useSheetBovenToetsenbord(true)
  return (
    <div className="acc-sheet-bg">
      <div className="acc-sheet" ref={sheetRef}>
        <h2>Meldingen</h2>
        <div className="acc-uitleg">
          Eén dagelijkse herinnering om 09:00 — alléén als er iets op je akkoord wacht, nooit ruis.
          Goedkeuren gebeurt altijd ín de app, nooit vanuit de melding zelf.
        </div>
        {status === 'aan' && (
          <div className="acc-uitlegblok">
            Meldingen staan <b>aan</b> op dit apparaat.
          </div>
        )}
        {status === 'uit' && (
          <div className="acc-uitlegblok">
            Meldingen staan <b>uit</b> op dit apparaat.
          </div>
        )}
        {status === 'geweigerd' && (
          <div className="acc-uitlegblok">
            Meldingen zijn <b>geblokkeerd in je toestel- of browserinstellingen</b> — sta ze daar eerst
            toe, en zet ze daarna hier aan.
          </div>
        )}
        {status === 'niet-geconfigureerd' && (
          <div className="acc-uitlegblok">Meldingen zijn op deze server (nog) niet ingericht.</div>
        )}
        {(status === 'niet-ondersteund' || status === null) && (
          <div className="acc-uitlegblok">
            Meldingen worden in deze browser niet ondersteund. Op een iPhone: zet de app eerst op je
            beginscherm.
          </div>
        )}
        <div className="acc-rij">
          <button className="acc-btn secundair" onClick={onSluit}>
            Sluiten
          </button>
          {status === 'aan' && (
            <button className="acc-btn afwijs" disabled={bezig} onClick={onUitzetten}>
              {bezig ? 'Bezig…' : 'Meldingen uitzetten'}
            </button>
          )}
          {status === 'uit' && (
            <button className="acc-btn groen" disabled={bezig} onClick={onAanzetten}>
              {bezig ? 'Bezig…' : 'Zet meldingen aan'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

/** Factuurbeeld via de prefetchcache — óók verborgen gemonteerd voor de eerstvolgende factuur,
 * zodat blob + pdf.js-render al klaarstaan vóór de gebruiker daar aankomt. */
function FactuurBeeld({ item }: { item: WachtrijItemDto }) {
  const [url, setUrl] = useState<string | null>(null)
  const [laden, setLaden] = useState(true)
  const [fout, setFout] = useState<string | null>(null)

  useEffect(() => {
    let actief = true
    setUrl(null)
    setLaden(true)
    setFout(null)
    factuurCache
      .haal(item.administratie_id, item.document_id)
      .then((blobUrl) => {
        if (actief) setUrl(blobUrl)
      })
      .catch(() => {
        if (actief) setFout('Het factuurbeeld kon niet geladen worden.')
      })
      .finally(() => {
        if (actief) setLaden(false)
      })
    return () => {
      actief = false
    }
  }, [item.administratie_id, item.document_id])

  return <PdfWeergave blobUrl={url} laden={laden} fout={fout} />
}

interface Props {
  wisselThema: () => void
  uitloggen: () => Promise<void>
}

export function GoedkeurenFlow({ wisselThema, uitloggen }: Props) {
  const { gebruikerId } = useAuth()
  const [weergave, setWeergave] = useState<Weergave>('wachtrij')
  const [items, setItems] = useState<WachtrijItem[]>([])
  const [totaalStart, setTotaalStart] = useState(0)
  const [verwerkt, setVerwerkt] = useState(0)
  const [laden, setLaden] = useState(true)
  const [fout, setFout] = useState<string | null>(null)
  const [voorwaardenNodig, setVoorwaardenNodig] = useState(false)
  const [huidige, setHuidige] = useState<WachtrijItem | null>(null)
  const [afwijsOpen, setAfwijsOpen] = useState(false)
  const [staandOpen, setStaandOpen] = useState(false)
  const [onderweg, setOnderweg] = useState(0)
  const [toast, setToast] = useState<string | null>(null)
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const laatsteOvergang = useRef(0)
  const [administratieNamen, setAdministratieNamen] = useState<string[]>([])
  const [staandeRegels, setStaandeRegels] = useState<(StaandeRegelDto & { administratie_id: string })[]>([])
  const [meldingen, setMeldingen] = useState<MeldingenStatus | null>(null)
  const [meldingenVoorstel, setMeldingenVoorstel] = useState(false)
  const [meldingenBezig, setMeldingenBezig] = useState(false)
  // Onthouden uitkomst per apparaat (UX-besluit Peter 2026-08-17): zodra er een keuze ligt
  // (aan/uit/mislukt) verschijnt het voorstel nergens meer — alleen het 🔔-hoekje blijft.
  const [meldingenKeuze, setMeldingenKeuze] = useState<MeldingenKeuze | null>(() => bewaardeMeldingenKeuze())
  const [meldingenSheetOpen, setMeldingenSheetOpen] = useState(false)
  // Eén herkansing bij een mislukte aanzet-poging in het éénmalige voorstel; daarna is
  // "mislukt" de onthouden uitkomst (eerlijke fout-toast, geen permanente banner).
  const meldingenMislukt = useRef(0)
  const [zoekParams, setZoekParams] = useSearchParams()

  const toon = useCallback((tekst: string) => {
    setToast(tekst)
    if (toastTimer.current) clearTimeout(toastTimer.current)
    toastTimer.current = setTimeout(() => setToast(null), 1900)
  }, [])

  const laadWachtrij = useCallback(async () => {
    setLaden(true)
    setFout(null)
    try {
      const { items: nieuw } = await haalWachtrij()
      // Besluiten die nog onderweg zijn naar de server (optimistisch verwerkt) horen niet
      // terug in de lijst — komen ze definitief niet aan, dan zet de mislukt-melding ze terug.
      const zichtbaar = nieuw.filter((i) => !besluitVerzender.isOnderweg(i.document_id))
      setItems(zichtbaar)
      setTotaalStart(zichtbaar.length)
      setVerwerkt(0)
      setVoorwaardenNodig(false)
    } catch (err) {
      if (isVoorwaardenVereist(err)) {
        setVoorwaardenNodig(true)
      } else {
        setFout('De wachtrij kon niet geladen worden. Probeer het opnieuw.')
      }
    } finally {
      setLaden(false)
    }
  }, [])

  useEffect(() => {
    void laadWachtrij()
    haalMijnAdministraties()
      .then(({ administraties }) => setAdministratieNamen(administraties.map((a) => a.naam)))
      .catch(() => setAdministratieNamen([]))
    haalMeldingenStatus()
      .then(setMeldingen)
      .catch(() => setMeldingen(null))
  }, [laadWachtrij])

  // Terugkeer-kanaal van de achtergrond-verzender: definitief mislukt = document zichtbaar
  // terug vooraan de rij mét melding (nooit stil verloren).
  useEffect(() => {
    besluitVerzender.zetLuisteraar({
      onDefinitiefMislukt: (opdracht: BesluitOpdracht, voorwaarden: boolean) => {
        setItems((vorige) =>
          vorige.some((i) => i.document_id === opdracht.item.document_id)
            ? vorige
            : [{ ...opdracht.item, verzend_fout: 'niet verzonden — opnieuw beoordelen' }, ...vorige],
        )
        setVerwerkt((v) => Math.max(0, v - 1))
        if (voorwaarden) setVoorwaardenNodig(true)
        toon(
          opdracht.soort === 'akkoord'
            ? 'Akkoord versturen mislukte — de factuur staat terug in je wachtrij'
            : 'Afwijzen versturen mislukte — de factuur staat terug in je wachtrij',
        )
      },
      onAantalOnderwegGewijzigd: setOnderweg,
    })
    setOnderweg(besluitVerzender.aantalOnderweg())
    return () => besluitVerzender.zetLuisteraar(null)
  }, [toon])

  const legKeuzeVast = useCallback((keuze: MeldingenKeuze) => {
    bewaarMeldingenKeuze(keuze)
    setMeldingenKeuze(keuze)
  }, [])

  /** Aanzetten mét keuze-vastlegging: 'aan' en 'geweigerd' zijn definitieve uitkomsten
   * (kaart/voorstel verdwijnt); een exception is 'fout' — de aanroeper bepaalt of er nog
   * een herkansing is (éénmalig voorstel) of dat het gewoon een losse poging was (🔔-hoekje). */
  const meldingenAanzetten = useCallback(async (): Promise<MeldingenStatus | 'fout'> => {
    setMeldingenBezig(true)
    try {
      const status = await zetMeldingenAan()
      setMeldingen(status)
      if (status === 'aan') {
        legKeuzeVast('aan')
        toon('Meldingen staan aan')
      } else if (status === 'geweigerd') {
        legKeuzeVast('uit')
        toon('Meldingen geblokkeerd — sta ze toe in je toestel- of browserinstellingen')
      }
      return status
    } catch (fout) {
      // De echte reden tonen (bewijs-push-diagnose 2026-08-17: de native registratie strandde
      // op het toestel en de generieke toast verstopte wélke stap faalde — permissie, de
      // push-dienst-registratie of de server-call).
      const reden = fout instanceof Error && fout.message ? ` (${fout.message})` : ''
      toon(`Meldingen aanzetten mislukte — probeer het opnieuw${reden}`)
      return 'fout'
    } finally {
      setMeldingenBezig(false)
    }
  }, [legKeuzeVast, toon])

  /** Het éénmalige voorstel (activeringsflow of de eenmalige wachtrij-kaart): élke uitkomst
   * sluit het voorstel definitief, behalve de éérste mislukte poging (één herkansing). */
  const eenmaligAanzetten = useCallback(async () => {
    const uitkomst = await meldingenAanzetten()
    if (uitkomst === 'fout') {
      if (meldingenMislukt.current >= 1) {
        legKeuzeVast('mislukt')
        setMeldingenVoorstel(false)
      } else {
        meldingenMislukt.current += 1
      }
      return
    }
    // 'aan'/'geweigerd' hebben hun keuze al vastgelegd; niet-ondersteund/niet-geconfigureerd
    // verbergen zichzelf via de status — het voorstel gaat in alle gevallen dicht.
    setMeldingenVoorstel(false)
  }, [legKeuzeVast, meldingenAanzetten])

  const meldingenUitzetten = useCallback(async () => {
    setMeldingenBezig(true)
    try {
      await zetMeldingenUit()
      setMeldingen('uit')
      legKeuzeVast('uit')
      toon('Meldingen staan uit')
    } finally {
      setMeldingenBezig(false)
    }
  }, [legKeuzeVast, toon])

  const openReview = (item: WachtrijItem) => {
    setHuidige(item)
    setWeergave('review')
  }

  // Deep-link uit mail/pushmelding (?document=<id>): open dat document zodra de wachtrij er
  // is — staat het er niet (meer) in, dan gewoon de wachtrij (al afgehandeld/ingetrokken).
  // Alleen navigatiesuiker: de ontgrendel-/voorwaardenpoorten zijn dan al gepasseerd.
  const deepLinkVerwerkt = useRef(false)
  useEffect(() => {
    if (laden || deepLinkVerwerkt.current) return
    const documentId = zoekParams.get('document')
    if (!documentId) return
    deepLinkVerwerkt.current = true
    const doel = items.find((i) => i.document_id === documentId)
    if (doel) openReview(doel)
    const rest = new URLSearchParams(zoekParams)
    rest.delete('document')
    setZoekParams(rest, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [laden, items, zoekParams, setZoekParams])

  // Prefetch-venster: in review de huidige + eerstvolgende factuur, op de wachtrij vast de
  // eerste — verborgen gemonteerd (prerender), al het andere wordt gesnoeid (geheugenrem).
  const volgende: WachtrijItem | null = huidige
    ? (items[items.findIndex((i) => i.document_id === huidige.document_id) + 1] ?? null)
    : null
  const venster: WachtrijItem[] =
    weergave === 'review' && huidige
      ? [huidige, ...(volgende && volgende.document_id !== huidige.document_id ? [volgende] : [])]
      : items.length > 0
        ? [items[0]]
        : []
  const vensterSleutel = venster.map((i) => i.document_id).join(',')
  useEffect(() => {
    factuurCache.snoei(vensterSleutel ? vensterSleutel.split(',') : [])
  }, [vensterSleutel])

  /** Optimistische verwerking: item per direct uit de rij, volgende factuur per direct open —
   * de server-call loopt intussen op de achtergrond (besluitVerzender, met retry). */
  const naVerwerking = (melding: string, verwerktItem: WachtrijItem) => {
    laatsteOvergang.current = Date.now()
    const rest = items.filter((i) => i.document_id !== verwerktItem.document_id)
    setItems(rest)
    setVerwerkt((v) => v + 1)
    toon(melding)
    if (rest.length > 0 && weergave === 'review') {
      openReview(rest[0])
    } else {
      setHuidige(null)
      setWeergave('wachtrij')
    }
  }

  const binnenOvergangsGuard = () => Date.now() - laatsteOvergang.current < OVERGANGS_GUARD_MS

  const akkoord = (staandeRegelAanmaken: boolean) => {
    if (!huidige || besluitVerzender.isOnderweg(huidige.document_id)) return
    const { verzend_fout: _weg, ...schoon } = huidige
    besluitVerzender.verstuur({ item: schoon, soort: 'akkoord', staandeRegelAanmaken, reden: null })
    naVerwerking(staandeRegelAanmaken ? 'Akkoord ✓ · staande goedkeuring ingesteld' : 'Akkoord ✓', huidige)
  }

  const akkoordKnop = () => {
    if (!huidige || binnenOvergangsGuard()) return
    // Staande-goedkeuring-voorstel ná de akkoord-keuze op de 2e identieke factuur (mockup):
    // één API-call, de keuze in de sheet bepaalt de staande_regel_aanmaken-vlag.
    if (huidige.staande_regel_kandidaat) setStaandOpen(true)
    else akkoord(false)
  }

  const afwijzen = (reden: string) => {
    if (!huidige || besluitVerzender.isOnderweg(huidige.document_id)) return
    setAfwijsOpen(false)
    const { verzend_fout: _weg, ...schoon } = huidige
    besluitVerzender.verstuur({ item: schoon, soort: 'afwijzen', staandeRegelAanmaken: false, reden })
    naVerwerking('Afgewezen — met reden terug naar het kantoor', huidige)
  }

  const laadStaandeRegels = useCallback(async () => {
    try {
      const { administraties } = await haalMijnAdministraties()
      const alles = await Promise.all(
        administraties.map(async (a) => {
          const { regels } = await haalStaandeRegels(a.id)
          return regels.map((r) => ({ ...r, administratie_id: a.id }))
        }),
      )
      // Alleen de eigen, actieve regels — het beheer van andermans regels is kantoor-werk.
      setStaandeRegels(alles.flat().filter((r) => r.actief && r.accordeur_gebruiker_id === gebruikerId))
    } catch {
      setStaandeRegels([])
    }
  }, [gebruikerId])

  const doeUitloggen = async () => {
    if (besluitVerzender.aantalOnderweg() > 0) {
      // Uitloggen trekt de sessie in — besluiten die nog onderweg zijn zouden dan pas bij de
      // volgende login zichtbaar terugkomen. Even laten uitrazen (seconden) is veiliger.
      toon('Nog besluiten onderweg naar de server — een moment…')
      return
    }
    try {
      await uitloggen()
    } catch {
      // Backend onbereikbaar (of andere fout): de sessie is dan niet ingetrokken — blijf in
      // de app en meld het, in lijn met "niets verdwijnt stil".
      toon('Uitloggen mislukte — server niet bereikbaar, probeer het opnieuw')
    }
  }

  const trekIn = async (regel: StaandeRegelDto & { administratie_id: string }) => {
    try {
      await trekStaandeRegelIn(regel.administratie_id, regel.id)
      toon('Staande goedkeuring ingetrokken')
      void laadStaandeRegels()
    } catch {
      toon('Intrekken mislukte — probeer het opnieuw')
    }
  }

  if (voorwaardenNodig) {
    // Zelfde uitlog-flow + toast als in de app-header: ook wie de voorwaarden NIET accepteert
    // kan de server-sessie netjes beëindigen (fail-closed-gate zonder uitgang, fix 2026-08-12).
    return (
      <>
        <VoorwaardenScherm
          naAkkoord={() => {
            void laadWachtrij()
            // Meldingen-voorstel op het logische moment (ná het voorwaarden-akkoord in de
            // activeringsflow) — de status komt vers van de server, want vóór het akkoord
            // weigert de notificatie-config-endpoint (fail-closed poort). Eénmalig: ligt er
            // op dit apparaat al een uitkomst (aan/uit/mislukt), dan nooit meer voorstellen.
            haalMeldingenStatus()
              .then((status) => {
                setMeldingen(status)
                if (status === 'uit' && bewaardeMeldingenKeuze() === null) setMeldingenVoorstel(true)
              })
              .catch(() => setMeldingen(null))
          }}
          uitloggen={doeUitloggen}
        />
        {toast && <div className="acc-toast">{toast}</div>}
      </>
    )
  }

  if (meldingenVoorstel && meldingen === 'uit') {
    // Eénmalig voorstel in de activeringsflow (UX-besluit Peter 2026-08-17) — de
    // browserpermissie komt pas ná deze expliciete klik (nooit rauw bij het laden). Elke
    // uitkomst wordt per apparaat onthouden, óók "Niet nu"; mislukken geeft een eerlijke
    // fout-toast + precies één herkansing. Later alsnog aanzetten kan via het 🔔-hoekje.
    return (
      <div className="acc-vol">
        <div className="acc-appnaam">
          RLZ <span>Goedkeuren</span>
        </div>
        <div className="acc-bio">
          <div className="acc-icoon">🔔</div>
          <b>Meldingen aanzetten?</b>
          <div className="acc-sub">
            Eén dagelijkse herinnering om 09:00 — alléén als er iets op je akkoord wacht, nooit ruis.
            Goedkeuren gebeurt altijd ín de app, nooit vanuit de melding zelf. Later aanzetten kan
            altijd nog via 🔔 rechtsboven.
          </div>
        </div>
        <button className="acc-btn groen" disabled={meldingenBezig} onClick={() => void eenmaligAanzetten()}>
          {meldingenBezig ? 'Bezig…' : 'Zet meldingen aan'}
        </button>
        <button
          className="acc-btn secundair"
          onClick={() => {
            legKeuzeVast('uit')
            setMeldingenVoorstel(false)
          }}
        >
          Niet nu
        </button>
        {toast && <div className="acc-toast">{toast}</div>}
      </div>
    )
  }

  const teller = items.length
  const tellerTekst = teller === 1 ? '1 factuur wacht op je akkoord' : `${teller} facturen wachten op je akkoord`

  return (
    <>
      <div className="acc-apphead">
        <div>
          <b>
            RLZ <span>Goedkeuren</span>
          </b>
          <div className="acc-who">{administratieNamen.join(' · ') || 'Accordeur'}</div>
        </div>
        <div className="acc-headbtns">
          <button
            className="acc-iconbtn"
            title="Staande goedkeuringen"
            onClick={() => {
              void laadStaandeRegels()
              setWeergave('beheer')
            }}
          >
            ✓✓
          </button>
          <button
            className="acc-iconbtn"
            title="Meldingen"
            aria-label="Meldingen"
            onClick={() => {
              // Vers ophalen bij het openen: de permissie kan intussen in de toestel-/
              // browserinstellingen gewijzigd zijn.
              haalMeldingenStatus()
                .then(setMeldingen)
                .catch(() => {})
              setMeldingenSheetOpen(true)
            }}
          >
            🔔
          </button>
          <button className="acc-iconbtn" title="Licht/donker (dark is default)" onClick={wisselThema}>
            ◐
          </button>
          <button className="acc-iconbtn" title="Uitloggen" aria-label="Uitloggen" onClick={() => void doeUitloggen()}>
            ⏻
          </button>
        </div>
      </div>

      <div className="acc-content">
        {weergave === 'wachtrij' && (
          <div>
            {laden && <div className="acc-qcount">Wachtrij laden…</div>}
            {fout && (
              <div className="acc-fout" style={{ maxWidth: 'none', marginBottom: 12 }}>
                {fout}{' '}
                <button className="acc-btn klein secundair" onClick={() => void laadWachtrij()}>
                  Opnieuw
                </button>
              </div>
            )}
            {/* Eénmalige meldingen-kaart (UX-besluit Peter 2026-08-17): alléén zolang er op
                dit apparaat nog géén uitkomst onthouden is (dekt apparaten die de
                activeringsflow al vóór dit voorstel doorliepen). Na élke uitkomst — aan,
                "niet nu", of mislukt-na-herkansing — blijft de wachtrij schoon; beheer
                loopt dan via het 🔔-hoekje. De geweigerd-/aan-banners zijn bewust weg. */}
            {!laden && !fout && meldingen === 'uit' && meldingenKeuze === null && (
              <div className="acc-pushnote">
                <span className="t">🔔</span>
                <div>
                  <b>Dagelijkse herinnering · 09:00</b> — alleen als er iets openstaat, nooit ruis.
                  <br />
                  <button className="acc-btn klein groen" disabled={meldingenBezig} onClick={() => void eenmaligAanzetten()}>
                    {meldingenBezig ? 'Bezig…' : 'Zet meldingen aan'}
                  </button>{' '}
                  <button className="acc-tekstlink" onClick={() => legKeuzeVast('uit')}>
                    niet nu
                  </button>
                </div>
              </div>
            )}
            {!laden && !fout && teller > 0 && (
              <>
                <div className="acc-qcount">{tellerTekst}</div>
                {items.map((item) => (
                  <button key={item.document_id} className="acc-qcard" onClick={() => openReview(item)}>
                    <div>
                      <div className="acc-lev">{item.leverancier_naam ?? 'Onbekende leverancier'}</div>
                      <div className="acc-meta">
                        {item.referentie ? `nr. ${item.referentie} · ` : ''}
                        {datumWeergave(item.factuurdatum)}
                        {item.verzend_fout && (
                          <>
                            {' · '}
                            <span className="acc-chip fout">{item.verzend_fout}</span>
                          </>
                        )}
                        {item.staande_regel_kandidaat && (
                          <>
                            {' · '}
                            <span className="acc-chip staand">zelfde bedrag als vorige</span>
                          </>
                        )}
                      </div>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <span className="acc-amt">{eurWeergave(item.totaalbedrag)}</span>
                      <span className="acc-arrow">›</span>
                    </div>
                  </button>
                ))}
              </>
            )}
            {!laden && !fout && teller === 0 && (
              <div className="acc-leeg">
                <div className="acc-big">✓</div>
                <b>Alles afgehandeld</b>
                Er staat niets meer voor je klaar. Je krijgt een melding zodra er een nieuwe factuur op je
                akkoord wacht.
              </div>
            )}
            {onderweg > 0 && (
              <div className="acc-onderweg">
                {onderweg === 1 ? '1 besluit wordt' : `${onderweg} besluiten worden`} op de achtergrond
                verzonden…
              </div>
            )}
          </div>
        )}

        {weergave === 'review' && huidige && (
          <div className="acc-revtop">
            <button className="acc-terug" onClick={() => setWeergave('wachtrij')}>
              ‹ Wachtrij
            </button>
            <span className="acc-tel">
              {verwerkt + 1} van {totaalStart}
            </span>
          </div>
        )}

        {/* Het factuurvenster blijft over weergave-wissels heen gemonteerd (stabiele keys):
            het verborgen exemplaar van de eerstvolgende factuur is al gefetcht én gerenderd
            wanneer die opent — de overgang is daardoor direct (snelheidslaag b/e). */}
        <div style={weergave === 'review' ? undefined : { display: 'none' }}>
          {venster.map((item) => {
            const actief = weergave === 'review' && huidige?.document_id === item.document_id
            return (
              <div key={item.document_id} style={actief ? undefined : { display: 'none' }} aria-hidden={!actief}>
                <FactuurBeeld item={item} />
              </div>
            )
          })}
        </div>

        {weergave === 'review' && huidige && (
          <div>
            <div className="acc-boekinfo">
              Boeking: <b>{huidige.boeking_omschrijving ?? '—'}</b>
              <br />
              <span className="acc-k">
                {eurWeergave(huidige.totaalbedrag)}
                {huidige.administratie_naam ? ` · ${huidige.administratie_naam}` : ''}
                {` · laag ${huidige.laag_volgnummer}`}
              </span>
            </div>
            {huidige.staande_regel_kandidaat && (
              <div className="acc-staandnote">
                <span>✓✓</span>
                <div>
                  Je keurde eerder een factuur van deze leverancier met <b>exact hetzelfde bedrag</b> goed. Na
                  dit akkoord kun je een staande goedkeuring instellen.
                </div>
              </div>
            )}
          </div>
        )}

        {weergave === 'beheer' && (
          <div>
            <div className="acc-revtop">
              <button className="acc-terug" onClick={() => setWeergave('wachtrij')}>
                ‹ Wachtrij
              </button>
            </div>
            <h2 style={{ fontSize: 16, marginBottom: 10 }}>Staande goedkeuringen</h2>
            <div className="acc-uitlegblok">
              Een staande goedkeuring vervangt alléén jouw akkoord-klik — nooit de controles van het kantoor.
              Duplicaat-, IBAN- en regelchecks blijven elke factuur blokkeren als er iets afwijkt. Wijkt het
              bedrag ook maar één cent af, dan komt de factuur gewoon bij je terug.
            </div>
            {staandeRegels.map((regel) => (
              <div key={regel.id} className="acc-sg-item">
                <div className="acc-kop">
                  <span className="acc-lev">{regel.leverancier_naam ?? 'Onbekende leverancier'}</span>
                  <span className="acc-amt">{eurWeergave(regel.bedrag)}</span>
                </div>
                <div className="acc-meta">
                  Automatisch akkoord bij exact dit bedrag · ingesteld {datumWeergave(regel.aangemaakt_op)} ·
                  elke toepassing zichtbaar in tijdlijn + audit log
                </div>
                <button className="acc-btn klein afwijs" onClick={() => void trekIn(regel)}>
                  Intrekken
                </button>
              </div>
            ))}
            {staandeRegels.length === 0 && (
              <div className="acc-sg-leeg">
                Je hebt nog geen staande goedkeuringen.
                <br />
                Je kunt er een instellen bij het akkoord op een terugkerende factuur met een vast bedrag.
              </div>
            )}
          </div>
        )}
      </div>

      {weergave === 'review' && huidige && (
        <div className="acc-actionbar">
          <button
            className="acc-btn afwijs"
            onClick={() => {
              if (!binnenOvergangsGuard()) setAfwijsOpen(true)
            }}
          >
            Afwijzen
          </button>
          <button className="acc-btn groen" onClick={akkoordKnop}>
            Akkoord ✓
          </button>
        </div>
      )}

      {afwijsOpen && <AfwijsSheet onAnnuleer={() => setAfwijsOpen(false)} onBevestig={(reden) => afwijzen(reden)} />}
      {meldingenSheetOpen && (
        <MeldingenSheet
          status={meldingen}
          bezig={meldingenBezig}
          onAanzetten={() => void meldingenAanzetten()}
          onUitzetten={() => void meldingenUitzetten()}
          onSluit={() => setMeldingenSheetOpen(false)}
        />
      )}
      {staandOpen && huidige && (
        <StaandSheet
          item={huidige}
          onKeuze={(staandeRegel) => {
            setStaandOpen(false)
            akkoord(staandeRegel)
          }}
        />
      )}
      {toast && <div className="acc-toast">{toast}</div>}
    </>
  )
}
