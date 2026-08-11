// De accordeer-flow (mockup/accordeur.html 1-op-1): wachtrij (kaartlijst + teller) →
// factuurbeeld centraal met voorgestelde boeking → Akkoord (direct, → automatisch volgende) /
// Afwijzen (bottom-sheet, verplichte reden) → lege staat. Staande-goedkeuring-voorstel ná
// akkoord op identiek leverancier+bedrag; ✓✓-beheerscherm met intrekken. Scope bewust alléén
// de wachtrij (besluit 2026-08-08). NB de dagelijkse-pushherinnering uit de mockup is bewust
// nog NIET opgenomen: push is expliciet GCP-fase — een belofte tonen die niet bestaat zou
// misleiden (afwijking gedocumenteerd in BESLISSINGEN).

import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import type { StaandeRegelDto } from '../accordering/accorderingApi'
import {
  datumWeergave,
  eurWeergave,
  geefAkkoord,
  haalFactuurBlob,
  haalMijnAdministraties,
  haalStaandeRegels,
  haalWachtrij,
  isVoorwaardenVereist,
  trekStaandeRegelIn,
  wijsAf,
  type WachtrijItemDto,
} from './accordeurApi'
import { PdfWeergave } from './PdfWeergave'
import { VoorwaardenScherm } from './VoorwaardenScherm'

type Weergave = 'wachtrij' | 'review' | 'beheer'

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

interface Props {
  wisselThema: () => void
}

export function GoedkeurenFlow({ wisselThema }: Props) {
  const { gebruikerId } = useAuth()
  const [weergave, setWeergave] = useState<Weergave>('wachtrij')
  const [items, setItems] = useState<WachtrijItemDto[]>([])
  const [totaalStart, setTotaalStart] = useState(0)
  const [verwerkt, setVerwerkt] = useState(0)
  const [laden, setLaden] = useState(true)
  const [fout, setFout] = useState<string | null>(null)
  const [voorwaardenNodig, setVoorwaardenNodig] = useState(false)
  const [huidige, setHuidige] = useState<WachtrijItemDto | null>(null)
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [pdfLaden, setPdfLaden] = useState(false)
  const [pdfFout, setPdfFout] = useState<string | null>(null)
  const [afwijsOpen, setAfwijsOpen] = useState(false)
  const [staandOpen, setStaandOpen] = useState(false)
  const [besluitBezig, setBesluitBezig] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [administratieNamen, setAdministratieNamen] = useState<string[]>([])
  const [staandeRegels, setStaandeRegels] = useState<(StaandeRegelDto & { administratie_id: string })[]>([])

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
      setItems(nieuw)
      setTotaalStart(nieuw.length)
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
  }, [laadWachtrij])

  // Factuurbeeld lazy per geopend document; blob-URL netjes opruimen.
  useEffect(() => {
    if (!huidige) return
    let vorige: string | null = null
    setPdfLaden(true)
    setPdfFout(null)
    setPdfUrl(null)
    haalFactuurBlob(huidige.administratie_id, huidige.document_id)
      .then((url) => {
        vorige = url
        setPdfUrl(url)
      })
      .catch(() => setPdfFout('Het factuurbeeld kon niet geladen worden.'))
      .finally(() => setPdfLaden(false))
    return () => {
      if (vorige) URL.revokeObjectURL(vorige)
    }
  }, [huidige])

  const openReview = (item: WachtrijItemDto) => {
    setHuidige(item)
    setWeergave('review')
  }

  const naVerwerking = (melding: string, verwerktItem: WachtrijItemDto) => {
    const rest = items.filter((i) => i.document_id !== verwerktItem.document_id)
    setItems(rest)
    setVerwerkt((v) => v + 1)
    toon(melding)
    if (rest.length > 0) {
      setTimeout(() => openReview(rest[0]), 350)
    } else {
      setHuidige(null)
      setTimeout(() => setWeergave('wachtrij'), 350)
    }
  }

  const akkoord = async (staandeRegelAanmaken: boolean) => {
    if (!huidige || besluitBezig) return
    setBesluitBezig(true)
    try {
      await geefAkkoord(huidige.administratie_id, huidige.document_id, staandeRegelAanmaken)
      naVerwerking(staandeRegelAanmaken ? 'Akkoord ✓ · staande goedkeuring ingesteld' : 'Akkoord ✓', huidige)
    } catch (err) {
      if (isVoorwaardenVereist(err)) setVoorwaardenNodig(true)
      else toon('Akkoord vastleggen mislukte — probeer het opnieuw')
    } finally {
      setBesluitBezig(false)
    }
  }

  const akkoordKnop = () => {
    if (!huidige) return
    // Staande-goedkeuring-voorstel ná de akkoord-keuze op de 2e identieke factuur (mockup):
    // één API-call, de keuze in de sheet bepaalt de staande_regel_aanmaken-vlag.
    if (huidige.staande_regel_kandidaat) setStaandOpen(true)
    else void akkoord(false)
  }

  const afwijzen = async (reden: string) => {
    if (!huidige || besluitBezig) return
    setBesluitBezig(true)
    setAfwijsOpen(false)
    try {
      await wijsAf(huidige.administratie_id, huidige.document_id, reden)
      naVerwerking('Afgewezen — met reden terug naar het kantoor', huidige)
    } catch (err) {
      if (isVoorwaardenVereist(err)) setVoorwaardenNodig(true)
      else toon('Afwijzen mislukte — probeer het opnieuw')
    } finally {
      setBesluitBezig(false)
    }
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
    return <VoorwaardenScherm naAkkoord={() => void laadWachtrij()} />
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
          <button className="acc-iconbtn" title="Licht/donker (dark is default)" onClick={wisselThema}>
            ◐
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
          </div>
        )}

        {weergave === 'review' && huidige && (
          <div>
            <div className="acc-revtop">
              <button className="acc-terug" onClick={() => setWeergave('wachtrij')}>
                ‹ Wachtrij
              </button>
              <span className="acc-tel">
                {verwerkt + 1} van {totaalStart}
              </span>
            </div>
            <PdfWeergave blobUrl={pdfUrl} laden={pdfLaden} fout={pdfFout} />
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
          <button className="acc-btn afwijs" disabled={besluitBezig} onClick={() => setAfwijsOpen(true)}>
            Afwijzen
          </button>
          <button className="acc-btn groen" disabled={besluitBezig} onClick={akkoordKnop}>
            {besluitBezig ? 'Bezig…' : 'Akkoord ✓'}
          </button>
        </div>
      )}

      {afwijsOpen && <AfwijsSheet onAnnuleer={() => setAfwijsOpen(false)} onBevestig={(reden) => void afwijzen(reden)} />}
      {staandOpen && huidige && (
        <StaandSheet
          item={huidige}
          onKeuze={(staandeRegel) => {
            setStaandOpen(false)
            void akkoord(staandeRegel)
          }}
        />
      )}
      {toast && <div className="acc-toast">{toast}</div>}
    </>
  )
}
