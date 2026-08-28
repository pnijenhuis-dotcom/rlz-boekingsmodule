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
// BV-OPENINGSSCHERM + VERVERSEN (besluiten Peter 27-08, mockup accordeur-vragen.html scherm 0):
// de app opent met één kaart per administratie MÉT werk (teller te accorderen, chip "vragen aan
// u", oudste-wacht-regel); één administratie met werk = direct die wachtrij; alles bij = "✓ Alles
// is bij" mét verversknop. Ná akkoord/afwijzen volgt de volgende factuur van DEZELFDE
// administratie; stapel leeg = terug naar het overzicht. Verversen: pull-to-refresh op overzicht
// én wachtrij, automatisch bij terugkeer naar de voorgrond (stil — de lijst blijft staan).
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
  type MeldingenKeuze,
  type MeldingenStatus,
} from './pushClient'
import type { StaandeRegelDto } from '../accordering/accorderingApi'
import {
  beantwoordVraag,
  datumWeergave,
  eurWeergave,
  haalMijnAdministraties,
  haalStaandeRegels,
  haalVragenAanMij,
  haalWachtrij,
  isVoorwaardenVereist,
  trekStaandeRegelIn,
  type AccordeurVraagDto,
  type WachtrijItemDto,
} from './accordeurApi'
import { besluitVerzender, type BesluitOpdracht } from './besluitQueue'
import { factuurCache } from './pdfCache'
import { PdfWeergave } from './PdfWeergave'
import { VoorwaardenScherm } from './VoorwaardenScherm'
import {
  administratieVanSleutel,
  administratiesMetWerk,
  kaartSleutel,
  kiesActieveAdministratie,
  vragenChipTekst,
  wachtSindsTekst,
} from './administraties'
import { PullToRefresh } from './PullToRefresh'
import { useVerversBijVoorgrond } from './verversen'

type Weergave = 'wachtrij' | 'review' | 'beheer' | 'thread'

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

/** Factuurbeeld via de prefetchcache — óók verborgen gemonteerd voor de eerstvolgende factuur,
 * zodat blob + pdf.js-render al klaarstaan vóór de gebruiker daar aankomt. */
/** Aandeel-percentage als "50%" / "33,33%" — string uit de backend (Decimal), nooit herberekend. */
function pctWeergave(pct: string): string {
  const getal = Number(pct)
  if (!Number.isFinite(getal)) return `${pct}%`
  return `${getal.toLocaleString('nl-NL', { minimumFractionDigits: 0, maximumFractionDigits: 2 })}%`
}

function FactuurBeeld({ item, actief = true }: { item: WachtrijItemDto; actief?: boolean }) {
  const [url, setUrl] = useState<string | null>(null)
  const [laden, setLaden] = useState(true)
  const [fout, setFout] = useState<string | null>(null)
  const [poging, setPoging] = useState(0)

  useEffect(() => {
    let levend = true
    setUrl(null)
    setLaden(true)
    setFout(null)
    factuurCache
      .haal(item.administratie_id, item.document_id)
      .then((blobUrl) => {
        if (levend) setUrl(blobUrl)
      })
      .catch(() => {
        if (levend) setFout('Het factuurbeeld kon niet geladen worden.')
      })
      .finally(() => {
        if (levend) setLaden(false)
      })
    return () => {
      levend = false
    }
  }, [item.administratie_id, item.document_id, poging])

  // Retry (feedbackpunt 2): cache-rij vergeten → verse fetch + render.
  const opnieuw = () => {
    factuurCache.vergeet(item.document_id)
    setPoging((p) => p + 1)
  }

  return <PdfWeergave blobUrl={url} laden={laden} fout={fout} actief={actief} onOpnieuw={opnieuw} />
}

/** "Wordt doorbelast aan X" / "aan X en Y" / "aan X, Y en Z" — puur tekst, geen rekenwerk. */
export function doorbelastKop(namen: string[]): string {
  if (namen.length === 0) return ''
  if (namen.length === 1) return namen[0]
  return `${namen.slice(0, -1).join(', ')} en ${namen[namen.length - 1]}`
}

/** Datum + tijd voor de thread ("26-08 16:42") — presentatie. */
function tijdWeergave(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('nl-NL', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

interface VraagThreadProps {
  vraag: AccordeurVraagDto
  onBeantwoord: (vraag: AccordeurVraagDto) => void
  toon: (tekst: string) => void
  rustig?: boolean
}

/** Vraag-thread van het kantoor aan de accordeur (mockup accordeur-vragen.html, blok B5):
 * bubbels (kantoor links, "U" rechts), antwoordbalk zolang de accordeur aan de beurt is; ná het
 * versturen "Wacht op kantoor". Afgehandeld verklaren kan alleen de vraagsteller — bewust géén
 * knop hier. */
function VraagThread({ vraag, onBeantwoord, toon, rustig = false }: VraagThreadProps) {
  const [tekst, setTekst] = useState('')
  const [bezig, setBezig] = useState(false)
  const verstuur = async () => {
    const inhoud = tekst.trim()
    if (!inhoud || bezig) return
    setBezig(true)
    try {
      const nieuw = await beantwoordVraag(vraag.administratie_id, vraag.id, inhoud)
      setTekst('')
      onBeantwoord(nieuw)
    } catch {
      toon('Antwoord versturen mislukte — probeer het opnieuw')
    } finally {
      setBezig(false)
    }
  }
  return (
    <div className={`acc-thread${rustig || !vraag.ik_ben_aan_de_beurt ? ' rustig' : ''}`} aria-label="Vraag van het kantoor">
      <div className="acc-thread-kop">
        <span>💬 Vraag van het kantoor</span>
        {vraag.ik_ben_aan_de_beurt ? (
          <span className="acc-chip beurt">U bent aan de beurt</span>
        ) : (
          <span className="acc-chip wacht">Wacht op kantoor</span>
        )}
      </div>
      <div className="acc-berichten">
        <div className="acc-bericht">
          <div className="acc-bubbel">{vraag.vraag_tekst}</div>
          <div className="acc-wie">Kantoor · {tijdWeergave(vraag.gesteld_op)}</div>
        </div>
        {vraag.berichten.map((b) => (
          <div key={b.id} className={`acc-bericht${b.van_mij ? ' van-mij' : ''}`}>
            <div className="acc-bubbel">{b.tekst}</div>
            <div className="acc-wie">
              {b.van_mij ? 'U' : 'Kantoor'} · {tijdWeergave(b.geplaatst_op)}
            </div>
          </div>
        ))}
      </div>
      {vraag.ik_ben_aan_de_beurt && (
        <div className="acc-antwoordbalk">
          <input
            type="text"
            placeholder="Uw antwoord…"
            aria-label="Uw antwoord"
            value={tekst}
            onChange={(e) => setTekst(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void verstuur()
            }}
          />
          <button type="button" disabled={bezig || tekst.trim() === ''} onClick={() => void verstuur()}>
            {bezig ? '…' : 'Verstuur'}
          </button>
        </div>
      )}
      <div className="acc-afgehandeld-voet">
        Alleen de vraagsteller op kantoor kan de vraag <b>afgehandeld</b> verklaren. U ziet uitsluitend vragen die
        aan u gericht zijn — nooit intern kantooroverleg.
      </div>
    </div>
  )
}

interface Props {
  wisselThema: () => void
  uitloggen: () => Promise<void>
}

export function GoedkeurenFlow({ wisselThema, uitloggen }: Props) {
  const { gebruikerId } = useAuth()
  const [weergave, setWeergave] = useState<Weergave>('wachtrij')
  const [items, setItems] = useState<WachtrijItem[]>([])
  // BV-openingsscherm (besluit Peter 27-08): de expliciet gekozen administratie; wélke de
  // wachtrij toont volgt uit kiesActieveAdministratie (precies één met werk = automatisch die).
  const [bvKeuze, setBvKeuze] = useState<string | null>(null)
  // Verwerkt binnen de huidige BV-stapel ("N van M" in de review) — reset bij een BV-wissel.
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
  // Vragen van het kantoor aan déze accordeur (blok B5, mockup accordeur-vragen.html): alle open
  // threads; op de wachtrij-kaart als hij bij een te accorderen document hoort, anders in de
  // sectie "Vragen aan u". `vraagOpen` = de losse thread die nu open staat.
  const [vragen, setVragen] = useState<AccordeurVraagDto[]>([])
  const [vraagOpen, setVraagOpen] = useState<AccordeurVraagDto | null>(null)
  const [doorbelastOpen, setDoorbelastOpen] = useState(false)
  const [factuurLos, setFactuurLos] = useState(false)
  const [staandeRegels, setStaandeRegels] = useState<(StaandeRegelDto & { administratie_id: string })[]>([])
  const [meldingen, setMeldingen] = useState<MeldingenStatus | null>(null)
  const [meldingenVoorstel, setMeldingenVoorstel] = useState(false)
  const [meldingenBezig, setMeldingenBezig] = useState(false)
  // Onthouden uitkomst per apparaat (UX-besluit Peter 2026-08-17): zodra er een keuze ligt
  // (aan/uit/mislukt) verschijnt het voorstel nergens meer — alleen het 🔔-hoekje blijft.
  // Alleen nog de setter: de keuze wordt per apparaat onthouden (activeringsflow éénmalig);
  // een 🔔-hoekje of wachtrij-kaart bestaat sinds 26-08 niet meer (om-/uitzetten = telefooninstellingen).
  const [, setMeldingenKeuze] = useState<MeldingenKeuze | null>(() => bewaardeMeldingenKeuze())
  // Eén herkansing bij een mislukte aanzet-poging in het éénmalige voorstel; daarna is
  // "mislukt" de onthouden uitkomst (eerlijke fout-toast, geen permanente banner).
  const meldingenMislukt = useRef(0)
  const [zoekParams, setZoekParams] = useSearchParams()

  const toon = useCallback((tekst: string) => {
    setToast(tekst)
    if (toastTimer.current) clearTimeout(toastTimer.current)
    toastTimer.current = setTimeout(() => setToast(null), 1900)
  }, [])

  // Voor de stille verversing: welke factuur staat nu open (zonder de callback te herbinden).
  const huidigeRef = useRef<WachtrijItem | null>(null)
  huidigeRef.current = huidige

  /** Wachtrij (+ vragen) laden. `stil` (pull-to-refresh, voorgrond-terugkeer): de lijst blijft
   * staan tijdens het laden en een fout wordt een toast i.p.v. een leeg scherm; de teller
   * "verwerkt" blijft staan. Niet-stil (eerste keer, "Opnieuw"): volledige laadstate. */
  const laadWachtrij = useCallback(
    async (opties: { stil?: boolean } = {}) => {
      const stil = opties.stil === true
      if (!stil) {
        setLaden(true)
        setFout(null)
      }
      try {
        const { items: nieuw } = await haalWachtrij()
        // Besluiten die nog onderweg zijn naar de server (optimistisch verwerkt) horen niet
        // terug in de lijst — komen ze definitief niet aan, dan zet de mislukt-melding ze terug.
        const zichtbaar = nieuw.filter((i) => !besluitVerzender.isOnderweg(i.document_id))
        setItems(zichtbaar)
        if (!stil) setVerwerkt(0)
        setFout(null)
        setVoorwaardenNodig(false)
        // Stond er een factuur open die intussen door een ander is afgehandeld/ingetrokken, dan
        // terug naar de wachtrij — nooit een besluit op een verdwenen document.
        const open = huidigeRef.current
        if (stil && open && !zichtbaar.some((i) => i.document_id === open.document_id) && !besluitVerzender.isOnderweg(open.document_id)) {
          setHuidige(null)
          setWeergave('wachtrij')
          toon('Deze factuur is intussen afgehandeld of ingetrokken')
        }
        // Vragen aan mij: tolerant — een fout hier mag de wachtrij nooit blokkeren.
        haalVragenAanMij()
          .then(({ items: v }) => setVragen(v))
          .catch(() => setVragen([]))
      } catch (err) {
        if (isVoorwaardenVereist(err)) {
          setVoorwaardenNodig(true)
        } else if (stil) {
          toon('Verversen mislukte — controleer de verbinding')
        } else {
          setFout('De wachtrij kon niet geladen worden. Probeer het opnieuw.')
        }
      } finally {
        if (!stil) setLaden(false)
      }
    },
    [toon],
  )

  useEffect(() => {
    void laadWachtrij()
    haalMeldingenStatus()
      .then(setMeldingen)
      .catch(() => setMeldingen(null))
  }, [laadWachtrij])

  // Automatisch verversen zodra de app naar de voorgrond komt (27-08) — stil, de lijst blijft
  // staan; nooit meer een app-herstart nodig voor nieuwe boekingen.
  useVerversBijVoorgrond(() => {
    if (!voorwaardenNodig && !laden) void laadWachtrij({ stil: true })
  })

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

  const openReview = (item: WachtrijItem) => {
    // Openen bindt de wachtrij aan de administratie van dit document (deep-links landen zo
    // direct in de juiste BV-wachtrij); een BV-wissel start de "N van M"-teller opnieuw.
    if (bvKeuze !== kaartSleutel(item)) {
      setBvKeuze(kaartSleutel(item))
      setVerwerkt(0)
    }
    setHuidige(item)
    setDoorbelastOpen(false)
    setWeergave('review')
  }

  /** Kaart op het BV-overzicht: naar de wachtrij van die administratie. */
  const kiesBv = (id: string | null) => {
    setBvKeuze(id)
    setVerwerkt(0)
  }

  /** Ná een antwoord: dezelfde thread op de kaart, in de review én in de losse lijst bijwerken. */
  const werkVraagBij = useCallback((nieuw: AccordeurVraagDto) => {
    setVragen((vorige) => (vorige.some((v) => v.id === nieuw.id) ? vorige.map((v) => (v.id === nieuw.id ? nieuw : v)) : [nieuw, ...vorige]))
    setVraagOpen((v) => (v && v.id === nieuw.id ? nieuw : v))
    setItems((vorige) => vorige.map((i) => (i.vraag?.id === nieuw.id ? { ...i, vraag: nieuw } : i)))
    setHuidige((h) => (h && h.vraag?.id === nieuw.id ? { ...h, vraag: nieuw } : h))
  }, [])

  // Deep-link uit mail/pushmelding (?document=<id>): open dat document zodra de wachtrij er
  // is — staat het er niet (meer) in, dan gewoon de wachtrij (al afgehandeld/ingetrokken).
  // Alleen navigatiesuiker: de ontgrendel-/voorwaardenpoorten zijn dan al gepasseerd.
  const deepLinkVerwerkt = useRef(false)
  useEffect(() => {
    if (laden || deepLinkVerwerkt.current) return
    const documentId = zoekParams.get('document')
    const vraagId = zoekParams.get('vraag')
    if (!documentId && !vraagId) return
    if (vraagId) {
      // Deep-link uit de vraag-melding (blok B5): eerst de losse thread als die er is, anders het
      // document waar de vraag op hangt; onbekend = gewoon de wachtrij.
      if (vragen.length === 0 && items.length === 0) return
      deepLinkVerwerkt.current = true
      const vraag = vragen.find((v) => v.id === vraagId)
      const kaart = items.find((i) => i.vraag?.id === vraagId)
      if (kaart) openReview(kaart)
      else if (vraag) {
        // Een vraag draagt geen afdeling: land op de (eerste) kaart van haar administratie.
        setBvKeuze(
          administratiesMetWerk(items, vragen).find((s) => s.id === vraag.administratie_id)?.sleutel ??
            vraag.administratie_id,
        )
        setVraagOpen(vraag)
        setWeergave('thread')
      }
      return
    }
    deepLinkVerwerkt.current = true
    const doel = items.find((i) => i.document_id === documentId)
    if (doel) openReview(doel)
    const rest = new URLSearchParams(zoekParams)
    rest.delete('document')
    setZoekParams(rest, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [laden, items, zoekParams, vragen, setZoekParams])

  // BV-overzicht (27-08): standen per administratie mét werk; de actieve administratie bepaalt
  // welke facturen/vragen de wachtrij toont. Eén met werk = automatisch die (geen keuzescherm).
  const standen = administratiesMetWerk(items, vragen)
  const actieveBv = kiesActieveAdministratie(bvKeuze, standen)
  // Blok A 28-08: de kaart is per (administratie, afdeling) — `actieveBv` is de kaartsleutel.
  const bvItems: WachtrijItem[] = actieveBv ? items.filter((i) => kaartSleutel(i) === actieveBv) : []
  const bvNaam = standen.find((s) => s.sleutel === actieveBv)?.naam ?? null

  // Prefetch-venster: in review de huidige + eerstvolgende factuur VAN DEZELFDE ADMINISTRATIE,
  // op de wachtrij vast de eerste (op het overzicht: de eerste kaart) — verborgen gemonteerd
  // (prerender), al het andere wordt gesnoeid (geheugenrem).
  const volgende: WachtrijItem | null = huidige
    ? (bvItems[bvItems.findIndex((i) => i.document_id === huidige.document_id) + 1] ?? null)
    : null
  const eersteKaart: WachtrijItem | null = bvItems[0] ?? items[0] ?? null
  const venster: WachtrijItem[] =
    weergave === 'review' && huidige
      ? [huidige, ...(volgende && volgende.document_id !== huidige.document_id ? [volgende] : [])]
      : eersteKaart
        ? [eersteKaart]
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
    // Volgende factuur van DEZELFDE administratie (besluit 27-08); stapel leeg → terug naar het
    // BV-overzicht (of, bij nog precies één administratie met werk, direct díe wachtrij).
    const restBv = rest.filter((i) => i.administratie_id === verwerktItem.administratie_id)
    setItems(rest)
    setVerwerkt((v) => v + 1)
    toon(melding)
    if (restBv.length > 0 && weergave === 'review') {
      openReview(restBv[0])
    } else {
      setHuidige(null)
      setWeergave('wachtrij')
      if (restBv.length === 0) kiesBv(null)
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
          Nijenhuis <span>Boekingsmodule</span>
        </div>
        <div className="acc-bio">
          <div className="acc-icoon">🔔</div>
          <b>Meldingen aanzetten?</b>
          <div className="acc-sub">
            Eén dagelijkse herinnering om 09:00 — alléén als er iets op je akkoord wacht — en een bericht
            als het kantoor u een vraag stelt. Goedkeuren gebeurt altijd ín de app, nooit vanuit de melding
            zelf. Later aan- of uitzetten doet u in de instellingen van uw telefoon.
          </div>
        </div>
        <button className="acc-btn primair" disabled={meldingenBezig} onClick={() => void eenmaligAanzetten()}>
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

  const teller = bvItems.length
  const tellerTekst = teller === 1 ? '1 factuur wacht op je akkoord' : `${teller} facturen wachten op je akkoord`
  // "Vragen aan u" = vragen (van de actieve administratie) die NIET op een te accorderen document
  // in de wachtrij hangen (die staan op de kaart zelf). Antwoorden werkt de thread op beide
  // plekken bij.
  const wachtrijDocumenten = new Set(items.map((i) => i.document_id))
  const losseVragen = vragen.filter(
    (v) =>
      !wachtrijDocumenten.has(v.document_id) &&
      (actieveBv === null || v.administratie_id === administratieVanSleutel(actieveBv)),
  )
  const toonOverzicht = actieveBv === null && standen.length > 1
  const allesBij = standen.length === 0
  const huidigeVraag: AccordeurVraagDto | null = huidige
    ? (vragen.find((v) => v.document_id === huidige.document_id) ?? huidige.vraag ?? null)
    : null

  return (
    <>
      <div className="acc-apphead">
        {/* Compact (feedbackpunt 1, 26-08): alleen titel + actieknoppen — de administratie staat al
            bij de boeking zelf; de administraties-namenlijst is weg. */}
        <div>
          <b>
            Nijenhuis <span>Boekingsmodule</span>
          </b>
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
          <PullToRefresh onVerversen={() => laadWachtrij({ stil: true })}>
            {laden && <div className="acc-qcount">Wachtrij laden…</div>}
            {fout && (
              <div className="acc-fout" style={{ maxWidth: 'none', marginBottom: 12 }}>
                {fout}{' '}
                <button className="acc-btn klein secundair" onClick={() => void laadWachtrij()}>
                  Opnieuw
                </button>
              </div>
            )}

            {/* Scherm 0 (27-08): één kaart per administratie MÉT werk — alleen bij ≥ 2. */}
            {!laden && !fout && toonOverzicht && (
              <>
                <div className="acc-seclabel">Uw administraties</div>
                <div className="acc-qcount">
                  {standen.length} administraties met iets te doen — kies er één.
                </div>
                {standen.map((s) => {
                  const wacht = wachtSindsTekst(s.oudsteWacht)
                  return (
                    <button key={s.sleutel} className="acc-qcard acc-bvkaart" onClick={() => kiesBv(s.sleutel)} aria-label={`Administratie ${s.naam ?? ''}`}>
                      <div>
                        <div className="acc-lev">{s.naam ?? 'Administratie'}</div>
                        {wacht && <div className="acc-meta">{wacht}</div>}
                        {s.vragen > 0 && (
                          <div className="acc-kaartchips">
                            <span className="acc-chip beurt">{vragenChipTekst(s.vragen)}</span>
                          </div>
                        )}
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        {s.teAccorderen > 0 && <span className="acc-chip vraag acc-bvteller">{s.teAccorderen} te accorderen</span>}
                        <span className="acc-arrow">›</span>
                      </div>
                    </button>
                  )
                })}
              </>
            )}

            {/* Wachtrij van één administratie (bij precies één met werk zonder terugknop). */}
            {!laden && !fout && actieveBv !== null && (
              <>
                {standen.length > 1 && (
                  <div className="acc-revtop">
                    <button className="acc-terug" onClick={() => kiesBv(null)}>
                      ‹ Administraties
                    </button>
                  </div>
                )}
                {teller > 0 ? (
                  <>
                    <div className="acc-seclabel">
                      {bvNaam ? `${bvNaam} — te accorderen · ${teller}` : `Te accorderen · ${teller}`}
                    </div>
                    <div className="acc-qcount">{tellerTekst}</div>
                  </>
                ) : (
                  <div className="acc-qcount">
                    {bvNaam ? `${bvNaam} — ` : ''}geen facturen te accorderen{losseVragen.length > 0 ? ', wel een vraag aan u' : ''}
                  </div>
                )}
                {bvItems.map((item) => (
                  <button key={item.document_id} className="acc-qcard" onClick={() => openReview(item)}>
                    <div>
                      <div className="acc-lev">{item.leverancier_naam ?? 'Onbekende leverancier'}</div>
                      <div className="acc-meta">
                        {item.referentie ? `nr. ${item.referentie} · ` : ''}
                        {datumWeergave(item.factuurdatum)}
                        {item.administratie_naam ? ` · ${item.administratie_naam}` : ''}
                        {` · laag ${item.laag_volgnummer}`}
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
                      {(item.vraag || (item.doorbelasting && item.doorbelasting.length > 0)) && (
                        <div className="acc-kaartchips">
                          {item.vraag && <span className="acc-chip vraag">💬 Vraag van kantoor</span>}
                          {item.doorbelasting && item.doorbelasting.length > 0 && (
                            <span className="acc-chip wacht">Wordt doorbelast</span>
                          )}
                        </div>
                      )}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <span className="acc-amt">{eurWeergave(item.totaalbedrag)}</span>
                      <span className="acc-arrow">›</span>
                    </div>
                  </button>
                ))}
              </>
            )}

            {/* Alles bij (27-08): lege staat mét verversknop — nooit meer een app-herstart nodig. */}
            {!laden && !fout && allesBij && (
              <div className="acc-leeg">
                <div className="acc-big">✓</div>
                <b>Alles is bij</b>
                Er staat niets voor u klaar. U krijgt een melding zodra er een nieuwe factuur op uw akkoord
                wacht — of ververs hier.
                <div style={{ marginTop: 16 }}>
                  <button className="acc-btn klein secundair" onClick={() => void laadWachtrij({ stil: true })}>
                    ↻ Verversen
                  </button>
                </div>
              </div>
            )}

            {!laden && !fout && !toonOverzicht && losseVragen.length > 0 && (
              <>
                <div className="acc-seclabel">Vragen aan u · {losseVragen.length}</div>
                <div className="acc-toelicht">
                  Vragen van het kantoor die geen open accordering blokkeren — bijvoorbeeld over een eerder
                  goedgekeurde factuur.
                </div>
                {losseVragen.map((vraag) => (
                  <button
                    key={vraag.id}
                    className="acc-qcard"
                    onClick={() => {
                      setVraagOpen(vraag)
                      setWeergave('thread')
                    }}
                  >
                    <div>
                      <div className="acc-lev">{vraag.leverancier_naam ?? 'Factuur'}</div>
                      <div className="acc-meta">
                        {vraag.document_status === 'geboekt' ? 'Geboekt' : 'Factuur'}
                        {vraag.totaalbedrag ? ` · ${eurWeergave(vraag.totaalbedrag)}` : ''}
                        {vraag.administratie_naam ? ` · ${vraag.administratie_naam}` : ''}
                      </div>
                      <div className="acc-meta acc-citaat">“{vraag.vraag_tekst}”</div>
                    </div>
                    {vraag.ik_ben_aan_de_beurt ? (
                      <span className="acc-chip beurt">U bent aan de beurt</span>
                    ) : (
                      <span className="acc-chip wacht">Wacht op kantoor</span>
                    )}
                  </button>
                ))}
              </>
            )}
            {onderweg > 0 && (
              <div className="acc-onderweg">
                {onderweg === 1 ? '1 besluit wordt' : `${onderweg} besluiten worden`} op de achtergrond
                verzonden…
              </div>
            )}
          </PullToRefresh>
        )}

        {weergave === 'review' && huidige && (
          <div className="acc-revtop">
            <button className="acc-terug" onClick={() => setWeergave('wachtrij')}>
              ‹ Wachtrij
            </button>
            <span className="acc-tel">
              {verwerkt + 1} van {verwerkt + bvItems.length}
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
                <FactuurBeeld item={item} actief={actief} />
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
            {huidige.doorbelasting && huidige.doorbelasting.length > 0 && (
              // Feedbackpunt 3 (26-08): één regel, tikbaar uitklappen — verdeling alleen-lezen.
              <div className={`acc-doorbelast${doorbelastOpen ? ' open' : ''}`} aria-label="Doorbelasting">
                <button
                  type="button"
                  className="acc-doorbelast-kop"
                  aria-expanded={doorbelastOpen}
                  onClick={() => setDoorbelastOpen((v) => !v)}
                >
                  <span>
                    Wordt doorbelast aan <b>{doorbelastKop(huidige.doorbelasting.map((r) => r.doelentiteit_naam))}</b>
                  </span>
                  <span className="acc-pijl" aria-hidden="true">
                    ▶
                  </span>
                </button>
                {doorbelastOpen && (
                  <div className="acc-doorbelast-detail">
                    {huidige.doorbelasting.map((r) => (
                      <div className="acc-rij" key={r.doelentiteit_naam}>
                        <span>{r.doelentiteit_naam}</span>
                        <span className="acc-p">
                          {pctWeergave(r.percentage)} · {eurWeergave(r.netto_totaal)} excl.
                        </span>
                      </div>
                    ))}
                    {huidige.doorbelasting.map((r) => (
                      <div className="acc-rij" key={`prov-${r.doelentiteit_naam}`}>
                        <span>Provisie kantoor{huidige.doorbelasting!.length > 1 ? ` · ${r.doelentiteit_naam}` : ''}</span>
                        <span className="acc-p">{eurWeergave(r.provisie_bedrag)}</span>
                      </div>
                    ))}
                    <div className="acc-voetje">Verdeling is alleen-lezen. Klopt die niet? Wijs de factuur af met een reden.</div>
                  </div>
                )}
              </div>
            )}
            {huidigeVraag && (
              <>
                <VraagThread vraag={huidigeVraag} onBeantwoord={werkVraagBij} toon={toon} />
                <div className="acc-toelicht">
                  U kunt de factuur gewoon goedkeuren of afwijzen — de vraag blokkeert alleen het <b>boeken</b> op
                  kantoor, tot de vraagsteller hem afgehandeld verklaart.
                </div>
              </>
            )}
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

        {weergave === 'thread' && vraagOpen && (
          <div>
            <div className="acc-revtop">
              <button className="acc-terug" onClick={() => setWeergave('wachtrij')}>
                ‹ Wachtrij
              </button>
            </div>
            <div className="acc-boekinfo">
              <b>{vraagOpen.leverancier_naam ?? 'Factuur'}</b>
              {vraagOpen.totaalbedrag ? ` · ${eurWeergave(vraagOpen.totaalbedrag)}` : ''}
              <br />
              <span className="acc-k">
                {vraagOpen.document_status === 'geboekt' ? 'Geboekt' : 'Factuur'}
                {vraagOpen.administratie_naam ? ` · ${vraagOpen.administratie_naam}` : ''}
                {' · '}
                <button type="button" className="acc-tekstlink" onClick={() => setFactuurLos((v) => !v)}>
                  {factuurLos ? 'verberg factuur' : 'bekijk factuur'}
                </button>
              </span>
            </div>
            {factuurLos && (
              <FactuurBeeld
                item={{
                  document_id: vraagOpen.document_id,
                  administratie_id: vraagOpen.administratie_id,
                  administratie_naam: vraagOpen.administratie_naam,
                  leverancier_naam: vraagOpen.leverancier_naam,
                  referentie: null,
                  factuurdatum: null,
                  totaalbedrag: vraagOpen.totaalbedrag,
                  aangeboden_op: vraagOpen.gesteld_op,
                  laag_volgnummer: 0,
                  boeking_omschrijving: null,
                  staande_regel_kandidaat: false,
                }}
              />
            )}
            <VraagThread vraag={vraagOpen} onBeantwoord={werkVraagBij} toon={toon} rustig />
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
          <button className="acc-btn primair" onClick={akkoordKnop}>
            Akkoord ✓
          </button>
        </div>
      )}

      {afwijsOpen && <AfwijsSheet onAnnuleer={() => setAfwijsOpen(false)} onBevestig={(reden) => afwijzen(reden)} />}
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
